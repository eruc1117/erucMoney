"""排程器：各工作的 cron 時點與不重入、啟動補跑的判準（凍結時間）、失敗不中斷、每週預測的到期判斷。"""
import os
from datetime import date, datetime

import pytest
from freezegun import freeze_time

import scheduler
import weekly_forecast
from config import SCHEDULE


class FakeScheduler:
    def __init__(self, timezone=None):
        self.jobs = []
        self.started = False

    def add_job(self, func, trigger=None, **kw):
        self.jobs.append({'func': func, 'trigger': trigger, **kw})

    def start(self):
        self.started = True


def _fields(trigger) -> dict:
    return {f.name: str(f) for f in trigger.fields}


def test_start_registers_every_job_with_expected_times(monkeypatch):
    fake = FakeScheduler()
    monkeypatch.setattr(scheduler, 'BlockingScheduler', lambda timezone=None: fake)
    monkeypatch.setattr(scheduler, '_catch_up', lambda: None)
    scheduler.start()
    assert fake.started
    by = {j['id']: j for j in fake.jobs}
    assert set(by) == {'job_stock', 'job_news', 'job_vote', 'job_freshness', 'job_exogenous_6', 'job_exogenous_19',
                       'job_us_predict', 'job_weekly_forecast', 'job_model_review'}
    f = lambda k: _fields(by[k]['trigger'])
    sc, vc, nc = SCHEDULE['stock_cron'], SCHEDULE['vote_cron'], SCHEDULE['news_cron']
    assert (f('job_stock')['hour'], f('job_stock')['minute']) == (str(sc['hour']), str(sc['minute']))
    assert (f('job_vote')['hour'], f('job_vote')['minute']) == (str(vc['hour']), str(vc['minute']))
    assert f('job_news')['hour'] == '*' and f('job_news')['minute'] == str(nc['minute'])       # 每小時
    assert (f('job_freshness')['hour'], f('job_freshness')['minute']) == ('17', '30')           # 排在股價更新之前
    assert int(f('job_freshness')['hour']) < sc['hour']
    assert f('job_exogenous_6')['hour'] == '6' and f('job_exogenous_19')['hour'] == '19' and f('job_exogenous_19')['minute'] == '10'
    assert (f('job_us_predict')['hour'], f('job_us_predict')['minute']) == ('20', '0')
    assert f('job_weekly_forecast')['day_of_week'] == 'sun' and (f('job_weekly_forecast')['hour'], f('job_weekly_forecast')['minute']) == ('8', '0')
    assert (f('job_model_review')['hour'], f('job_model_review')['minute']) == ('21', '0')
    assert int(f('job_model_review')['hour']) > vc['hour']                                       # 評估在投票之後
    # 不重入：每個工作 max_instances=1，且都有 misfire 寬限
    assert all(j['max_instances'] == 1 and j['misfire_grace_time'] > 0 for j in fake.jobs)
    assert by['job_weekly_forecast']['func'] is scheduler.job_weekly_forecast


@pytest.fixture
def catch_up_env(monkeypatch, tmp_path):
    """把補跑會碰的東西全部換掉：log 目錄、資料庫查詢、各 job、新聞補跑、每週預測到期判斷。"""
    monkeypatch.setattr(scheduler, 'LOG_DIR', str(tmp_path))
    ran = []
    monkeypatch.setattr(scheduler, 'job_stock', lambda: ran.append('stock'))
    monkeypatch.setattr(scheduler, 'job_vote', lambda: ran.append('vote'))
    monkeypatch.setattr(scheduler, 'job_model_review', lambda: ran.append('model_review'))
    monkeypatch.setattr(scheduler, 'job_weekly_forecast', lambda trigger='schedule': ran.append(f'weekly:{trigger}'))
    monkeypatch.setattr(scheduler, '_catch_up_news', lambda: False)
    monkeypatch.setattr(weekly_forecast, 'due', lambda: False)
    last = {'stock_daily_prices': None, 'voting_results': None}
    monkeypatch.setattr(scheduler, '_max_trade_date', lambda table, col='trade_date': last[table])
    return ran, last, tmp_path


@freeze_time('2026-09-25 19:30:00')      # 週五，過了 18:00 股價、還沒到 20:00 投票
def test_catch_up_runs_only_overdue_and_stale_jobs(catch_up_env):
    ran, last, tmp = catch_up_env
    last['stock_daily_prices'] = '2026-09-24'      # 行情停在昨天 → 要補
    scheduler._catch_up()
    assert ran == ['stock']                          # 投票時間未到；模型評估只在 21:00 後
    marker = os.path.join(str(tmp), 'catchup_2026-09-25')
    assert os.path.exists(marker) and open(marker).read() == 'stock'
    ran.clear()
    scheduler._catch_up()
    assert ran == []                                 # 同一天第二次：標記存在，不再補


@freeze_time('2026-09-25 21:05:00')
def test_catch_up_after_2100_runs_vote_then_review(catch_up_env):
    ran, last, _ = catch_up_env
    last['stock_daily_prices'] = '2026-09-25'      # 行情已是今天 → 不補股價
    last['voting_results'] = '2026-09-24'
    scheduler._catch_up()
    assert ran == ['vote', 'model_review']           # 有補過才做模型評估


@freeze_time('2026-09-25 21:05:00')
def test_catch_up_nothing_when_all_fresh(catch_up_env):
    ran, last, tmp = catch_up_env
    last['stock_daily_prices'] = '2026-09-25'
    last['voting_results'] = '2026-09-25'
    scheduler._catch_up()
    assert ran == [] and open(os.path.join(str(tmp), 'catchup_2026-09-25')).read() == 'nothing'


@freeze_time('2026-09-27 10:00:00')      # 週日
def test_catch_up_skips_weekend_but_still_checks_news(catch_up_env, monkeypatch):
    ran, last, tmp = catch_up_env
    news = []
    monkeypatch.setattr(scheduler, '_catch_up_news', lambda: news.append(1) or True)
    last['stock_daily_prices'] = '2026-09-20'
    scheduler._catch_up()
    assert ran == [] and news == [1]
    assert not os.path.exists(os.path.join(str(tmp), 'catchup_2026-09-27'))    # 週末不寫標記


@freeze_time('2026-09-25 19:30:00')
def test_catch_up_records_weekly_forecast_when_due(catch_up_env, monkeypatch):
    ran, last, _ = catch_up_env
    last['stock_daily_prices'] = '2026-09-25'
    monkeypatch.setattr(weekly_forecast, 'due', lambda: True)
    scheduler._catch_up()
    assert ran == ['weekly:catch_up']


@freeze_time('2026-09-25 19:30:00')
def test_catch_up_failure_does_not_propagate_and_still_marks(catch_up_env, monkeypatch, caplog):
    ran, last, tmp = catch_up_env
    last['stock_daily_prices'] = '2026-09-24'
    def boom(): raise RuntimeError('FinMind 掛了')
    monkeypatch.setattr(scheduler, 'job_stock', boom)
    with caplog.at_level('WARNING'):
        scheduler._catch_up()                       # 不能拋出：排程器要繼續啟動
    assert '補跑中斷' in caplog.text and 'FinMind 掛了' in caplog.text
    assert open(os.path.join(str(tmp), 'catchup_2026-09-25')).read() == 'nothing'


# ── 每週預測的時間判準（純函式）────────────────────────────────────────────────
def test_weekly_due_and_next_run_times():
    sun = datetime(2026, 9, 27, 8, 0)
    assert weekly_forecast.last_due_time(datetime(2026, 9, 27, 7, 59)) == datetime(2026, 9, 20, 8, 0)   # 週日 8 點前：上週
    assert weekly_forecast.last_due_time(sun) == sun
    assert weekly_forecast.last_due_time(datetime(2026, 9, 30, 12, 0)) == sun
    assert weekly_forecast.next_run_time(datetime(2026, 9, 30, 12, 0)) == datetime(2026, 10, 4, 8, 0)
    w = weekly_forecast.week_windows(date(2026, 9, 30))
    assert (w['week1_start'], w['week1_end']) == (date(2026, 9, 28), date(2026, 10, 2))
    assert (w['week2_start'], w['week2_end']) == (date(2026, 10, 5), date(2026, 10, 9))
