"""正式策略（Iteration 64）：升格只能一次、保留期只開一次、live 列原地覆寫（N 不動）、每日更新的略過條件、狀態。測試庫；回測本體用假的。"""
from datetime import date

import pandas as pd
import pytest

import portfolio_backtest as pb
import portfolio_official as po

pytestmark = pytest.mark.db


def _fake_res(start, end, ann=0.05, nav_pts=3):
    idx = pd.to_datetime([start, end])
    nav = pd.Series([1.0, 1.0 + ann], index=idx)
    bench = pd.Series([1.0, 1.02], index=idx)
    return {'nav': nav, 'bench': bench, 'positions': pd.DataFrame([{'rebalance_date': end, 'exec_date': end, 'stock_id': '2330', 'rank': None, 'signal_value': None, 'target_weight': 0.5, 'filled': True}]),
            'metrics': {'start': str(start), 'end': str(end), 'ann_active': ann, 'info_ratio': 0.5, 'n_rebalances': 1, 'yearly_active': {}}}


def _seed_candidate(db):
    db.execute("""INSERT INTO portfolio_runs (id, experiment_n, name, signal, segment, period_start, period_end, params, metrics, tag)
                  VALUES (44, 44, 'win3+mom-t3-tsmcest-dev+valid', 'win3+mom', 'dev', '2018-01-01', '2024-09-30',
                          '{"top_n": 20, "tranches": 3, "tsmc_weight": "est"}', '{"ann_active": 0.0705, "info_ratio": 0.564, "end": "2024-09-30"}', 'candidate')""")


def test_promote_once_and_update_in_place(clean_db, monkeypatch):
    db = clean_db
    _seed_candidate(db)
    calls = []
    counter = {'n': 44}

    def fake_run(signal, segment, start, end, top_n, buffer, universe_n, excl, tsmc, costs, name=None, notes='', save=True, tranches=1, weighting='equal', **kw):
        calls.append((segment, start, end, name, save))
        res = _fake_res(start or date(2018, 1, 1), end, ann=0.03 if segment == 'holdout' else 0.06)
        res['params'] = {'signal': signal, 'tranches': tranches, 'tsmc_weight': tsmc, 'top_n': top_n}
        if save:
            counter['n'] += 1
            res['run_id'] = pb.save_run(counter['n'], name, signal, segment, start or date(2018, 1, 1), end, res['params'], res['metrics'], res['positions'], notes,
                                        series=pb.series_frame(res['nav'], res['bench']))
            res['experiment_n'] = counter['n']
        return res
    monkeypatch.setattr(pb, 'run', fake_run)
    assert po.state() is None
    r = po.promote(44, note='測試升格', today=date(2026, 10, 10))
    assert [c[0] for c in calls] == ['holdout', 'live'] and calls[0][1] == date(2024, 10, 1) and calls[1][1] == date(2018, 1, 1)
    assert calls[0][3] == 'win3+mom-t3-tsmcest-holdout' and calls[1][3] == 'win3+mom-t3-tsmcest-live'
    st = po.state()
    assert st['candidate_run_id'] == 44 and st['holdout_run_id'] == r['holdout']['run_id'] and st['live_run_id'] == r['live']['run_id'] and st['promoted_on'] == '2026-10-10'
    tags = dict(db.query("SELECT id, tag FROM portfolio_runs WHERE id IN (%s, %s)", (st['holdout_run_id'], st['live_run_id'])))
    assert tags[st['holdout_run_id']] == 'official' and tags[st['live_run_id']] == 'official-live'
    # 再升格一次：拒絕
    with pytest.raises(RuntimeError):
        po.promote(44)
    # 每日更新：升格那天算到 10/10；塞一筆 10/11 的行情 → 重算 live 列到 10/11、覆寫 series、N 不動
    db.execute("INSERT INTO market_daily_prices (stock_id, trade_date, close_price, adj_close, source) SELECT '9999', '2026-10-11', 10, 10, 'test'")
    assert 'skipped' not in po.update_daily(today=date(2026, 10, 11))
    assert calls[-1][0] == 'live' and calls[-1][4] is False and calls[-1][2] == date(2026, 10, 11)
    st2 = po.state()
    assert st2['last_update_end'] == '2026-10-11' and st2['last_error'] is None
    n_runs = db.query("SELECT count(*), max(experiment_n) FROM portfolio_runs")[0]
    assert n_runs == (3, 46)                                           # 候選 + holdout + live；每日更新沒有新列
    pts = db.query("SELECT count(*), max(trade_date) FROM portfolio_run_series WHERE run_id = %s", (st['live_run_id'],))[0]
    assert pts[0] == 2 and str(pts[1]) == '2026-10-11'
    assert 'skipped' in po.update_daily(today=date(2026, 10, 11))      # 同一天再跑：略過
    s = po.status()
    assert s['promoted'] and set(s['segments']) >= {'full', 'holdout', 'live'} and s['segments']['holdout']['metrics']['ann_active'] == 0.03
    # 段別與標記的中文由 API 給（Iteration 86：頁面不寫死）：full 是候選全期間列、live 叫「實單」、tag 也帶中文
    import portfolio_api
    assert s['segments']['full']['segment_label'] == portfolio_api.SEGMENT_LABEL_FULL and s['segments']['full']['segment'] == 'dev'
    assert s['segments']['live']['segment_label'] == portfolio_api.SEGMENT_LABEL['live'] == '實單'
    assert s['segments']['live']['tag'] == 'official-live' and s['segments']['live']['tag_label'] == portfolio_api.TAG_LABEL['official-live']
    assert s['segments']['holdout']['tag_label'] == portfolio_api.TAG_LABEL['official']
    assert portfolio_api.tag_label(None) is None and portfolio_api.tag_label('x') == 'x'
    assert s['official']['live_run_id'] == st['live_run_id']


def test_update_without_promotion_is_skipped(clean_db):
    assert 'skipped' in po.update_daily()
    assert po.status() == {'promoted': False}


def test_rerun_holdout_voids_old_and_uses_warmup(clean_db, monkeypatch):
    db = clean_db
    _seed_candidate(db)
    seen = []
    counter = {'n': 44}

    def fake_run(signal, segment, start, end, top_n, buffer, universe_n, excl, tsmc, costs, name=None, notes='', save=True, tranches=1, weighting='equal', warmup_days=0, **kw):
        seen.append((segment, warmup_days, name))
        res = _fake_res(start or date(2018, 1, 1), end, ann=0.126 if warmup_days else 0.03)
        res['params'] = {'signal': signal, 'tranches': tranches, 'tsmc_weight': tsmc, 'top_n': top_n, 'warmup_days': warmup_days}
        if save:
            counter['n'] += 1
            res['run_id'] = pb.save_run(counter['n'], name, signal, segment, start or date(2018, 1, 1), end, res['params'], res['metrics'], res['positions'], notes,
                                        series=pb.series_frame(res['nav'], res['bench']))
            res['experiment_n'] = counter['n']
        return res
    monkeypatch.setattr(pb, 'run', fake_run)
    with pytest.raises(RuntimeError):
        po.rerun_holdout('還沒升格')
    r0 = po.promote(44, note='x', today=date(2026, 10, 10))
    old = r0['holdout']['run_id']
    r = po.rerun_holdout('對手修正後重跑', today=date(2026, 10, 11))
    assert seen[-1] == ('holdout', 420, 'win3+mom-t3-tsmcest-holdout') and r['replaced'] == old
    st = po.state()
    assert st['holdout_run_id'] == r['holdout']['run_id'] != old and '重跑' in st['note']
    tags = dict(db.query("SELECT id, tag FROM portfolio_runs WHERE id IN (%s, %s)", (old, st['holdout_run_id'])))
    assert tags[old] == 'void' and tags[st['holdout_run_id']] == 'official'
    assert '作廢' in db.query("SELECT notes FROM portfolio_runs WHERE id = %s", (old,))[0][0]
    assert db.query("SELECT max(experiment_n) FROM portfolio_runs")[0][0] == 47          # 候選 44 + holdout 45 + live 46 + 重跑 47
    s = po.status()
    assert s['segments']['holdout']['metrics']['ann_active'] == 0.126

