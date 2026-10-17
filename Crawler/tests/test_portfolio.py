"""月調倉選股（Iteration 49）：DSR 公式、營收驚喜、反應日、股票池與排除、三種訊號的點時規則、緩衝區、模擬帳的成本／未成交／強制平倉、實驗日誌。"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

import dsr
import portfolio_backtest as pb
import portfolio_signal as ps


# ── DSR ───────────────────────────────────────────────────────────────────────
def test_norm_ppf_and_cdf():
    assert dsr.norm_ppf(0.975) == pytest.approx(1.95996, abs=1e-4)
    assert dsr.norm_ppf(0.5) == pytest.approx(0.0, abs=1e-9)
    assert dsr.norm_cdf(1.95996) == pytest.approx(0.975, abs=1e-4)


def test_expected_max_sharpe_matches_plan_example():
    # 計畫文件的例子：5 年資料、年化 Sharpe 標準誤約 0.45、測 100 個版本 → SR* ≈ 2.53 × 0.45 ≈ 1.13
    assert dsr.expected_max_sharpe(100, 0.45 ** 2) == pytest.approx(1.14, abs=0.03)
    assert dsr.expected_max_sharpe(1, 0.2) == 0.0 and dsr.expected_max_sharpe(50, 0.0) == 0.0


def test_deflated_sharpe_falls_with_more_trials():
    rng = np.random.default_rng(0)
    r = list(rng.normal(0.01, 0.03, 60))          # 月 Sharpe 約 0.33
    one = dsr.deflated_sharpe(r, 1, 0.0)
    many = dsr.deflated_sharpe(r, 200, 0.1)
    assert one['sr'] > 0 and one['dsr'] > many['dsr'] and 0 <= many['dsr'] <= 1
    assert dsr.deflated_sharpe([0.01, 0.01], 1, 0.0)['dsr'] == 0.0      # 樣本太少


# ── 營收驚喜與反應日 ──────────────────────────────────────────────────────────
def _rev(sid, months, growth=0.02, jump_at=None, jump=0.5):
    rows = []
    v = 100.0
    for i, m in enumerate(months):
        v *= (1 + growth)
        if jump_at is not None and m == jump_at:
            v *= (1 + jump)
        rows.append({'stock_id': sid, 'revenue_month': m, 'revenue': v, 'announce_date': pd.NaT, 'announce_ts': pd.NaT, 'announce_source': None})
    return rows


def test_surprises_need_history_and_flag_a_jump():
    months = pd.date_range('2020-01-01', '2023-12-01', freq='MS')
    rev = pd.DataFrame(_rev('1111', months, jump_at=pd.Timestamp('2023-10-01')))
    sur = ps.surprises(rev)
    s = sur.set_index('revenue_month')['sue']
    assert s.loc['2020-06-01':'2021-03-01'].isna().all()               # 12 個月 YoY + 3 期趨勢 + 12 個月標準差都還沒湊齊
    assert s.loc['2023-10-01'] > 3 and abs(s.loc['2023-09-01']) < 1     # 跳升那個月 SUE 很大，前一個月正常
    assert ps.surprises(rev.iloc[:5]).empty


def test_reaction_day_rules():
    days = pd.to_datetime(['2024-07-08', '2024-07-09', '2024-07-10', '2024-07-11', '2024-07-15']).values   # 7/12 週五休、7/13-14 週末
    rd = lambda d, ts=None: ps.reaction_day(pd.Timestamp(d), pd.Timestamp(ts) if ts else pd.NaT, days)
    assert rd('2024-07-09', '2024-07-09 13:00') == pd.Timestamp('2024-07-09')      # 收盤前 → 當天
    assert rd('2024-07-09', '2024-07-09 17:30') == pd.Timestamp('2024-07-10')      # 收盤後 → 次一交易日
    assert rd('2024-07-09') == pd.Timestamp('2024-07-10')                          # 只有日期 → 當成盤後
    assert rd('2024-07-11', '2024-07-11 18:00') == pd.Timestamp('2024-07-15')      # 跨休假
    assert rd('2024-07-13', '2024-07-13 10:00') == pd.Timestamp('2024-07-15')      # 假日 10 點公告 → 下一個交易日
    assert ps.reaction_day(pd.NaT, pd.NaT, days) is None


# ── 合成市場 ──────────────────────────────────────────────────────────────────
def _market(n_days=90, start='2024-01-02', stocks=('1111', '2222', '3333', '4444'), seed=1, meta=None):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_days)
    rows = []
    for k, sid in enumerate(list(stocks) + [ps.BENCH]):
        px = 100.0 * (1 + k * 0.1)
        for d in days:
            r = rng.normal(0.0003 * (k + 1), 0.01)
            px *= (1 + r)
            rows.append({'stock_id': sid, 'trade_date': d, 'open_price': px * 0.995, 'high_price': px * 1.01, 'low_price': px * 0.99,
                         'close_price': px, 'adj_close': px, 'turnover_value': 1e8 * (len(stocks) - k + 1)})
    prices = pd.DataFrame(rows)
    if meta is None:
        meta = pd.DataFrame({'stock_id': list(stocks), 'listing_date': pd.NaT, 'delisted_date': pd.NaT}).set_index('stock_id')
    return ps.Market(prices, meta), prices


def test_schedule_signal_on_11th_and_exec_next_day():
    mkt, _ = _market(n_days=70)
    sch = ps.rebalance_schedule(mkt, date(2024, 1, 1), date(2024, 3, 31))
    assert [(s.date(), e.date()) for s, e in sch] == [(date(2024, 1, 11), date(2024, 1, 12)), (date(2024, 2, 12), date(2024, 2, 13)), (date(2024, 3, 11), date(2024, 3, 12))]
    # 2/11 是週日 → 2/12；成交日超出期間的那個月不排
    assert ps.rebalance_schedule(mkt, date(2024, 1, 1), date(2024, 1, 11)) == []


def test_eligible_liquidity_top_n_and_limit_up_exclusion():
    mkt, prices = _market(n_days=80)
    d = pd.Timestamp('2024-03-11')
    assert list(ps.eligible(mkt, d, universe_n=2, excl_limit_pct=0)) == ['1111', '2222']          # 成交金額最大的兩檔
    # 讓 4444 在過去 20 日漲停兩次
    mkt.limit_up_20.loc[d, '4444'] = 2
    assert '4444' not in ps.eligible(mkt, d, universe_n=4, excl_limit_pct=0.25)
    assert list(ps.eligible(mkt, d, universe_n=4, excl_limit_pct=0.25)) == ['1111', '2222', '3333']
    # 沒有漲停紀錄的不會因為「前 10%」被排除
    mkt.limit_up_20.loc[d, '4444'] = 0
    assert len(ps.eligible(mkt, d, universe_n=4, excl_limit_pct=0.25)) == 4
    # 下市股不在候選裡
    meta = pd.DataFrame({'stock_id': ['1111', '2222'], 'listing_date': [pd.NaT, pd.NaT], 'delisted_date': [pd.NaT, pd.Timestamp('2024-03-01')]}).set_index('stock_id')
    mkt2 = ps.Market(prices, meta)
    assert list(ps.eligible(mkt2, d, universe_n=5, excl_limit_pct=0)) == ['1111']


def test_signal_win_sums_ar_from_month_start_to_signal_day():
    mkt, _ = _market(n_days=80)
    d = pd.Timestamp('2024-03-11')
    s = ps.signal_win(mkt, d)
    expected = mkt.ar.loc['2024-03-01':d, '1111'].sum()
    assert s['1111'] == pytest.approx(expected)
    assert ps.BENCH in s.index and s[ps.BENCH] == pytest.approx(0.0, abs=1e-12)


def test_signal_sue_uses_only_current_month_and_ar0_only_precise_dates():
    mkt, _ = _market(n_days=80)
    d = pd.Timestamp('2024-03-11')
    sur = pd.DataFrame([
        {'stock_id': '1111', 'revenue_month': pd.Timestamp('2024-03-01'), 'sue': 1.5, 'announce_date': pd.Timestamp('2024-03-08'), 'announce_ts': pd.Timestamp('2024-03-08 14:00'), 'announce_source': 'cnyes_item'},
        {'stock_id': '2222', 'revenue_month': pd.Timestamp('2024-03-01'), 'sue': -0.5, 'announce_date': pd.Timestamp('2024-03-09'), 'announce_ts': pd.NaT, 'announce_source': 'estimated'},
        {'stock_id': '3333', 'revenue_month': pd.Timestamp('2024-04-01'), 'sue': 9.0, 'announce_date': pd.NaT, 'announce_ts': pd.NaT, 'announce_source': None},   # 下個月的，訊號日看不到
        {'stock_id': '4444', 'revenue_month': pd.Timestamp('2024-03-01'), 'sue': 0.2, 'announce_date': pd.Timestamp('2024-03-12'), 'announce_ts': pd.Timestamp('2024-03-12 15:00'), 'announce_source': 'mops_item'},  # 反應日 3/13 > d
    ])
    sue = ps.signal_sue(sur, d)
    assert set(sue.index) == {'1111', '2222', '4444'} and sue['1111'] == 1.5
    ar0 = ps.signal_ar0(sur, mkt, d)
    assert list(ar0.index) == ['1111']                                        # estimated 不算、未來反應日不算
    assert ar0['1111'] == pytest.approx(mkt.ar.at[pd.Timestamp('2024-03-11'), '1111'])   # 3/8 週五 14:00 盤後 → 3/11
    ids = pd.Index(['1111', '2222'])
    assert list(ps.scores_on('sue', mkt, sur, d, ids).index) == ['1111', '2222']
    with pytest.raises(ValueError):
        ps.scores_on('nope', mkt, sur, d, ids)


def test_build_targets_buffer_and_tsmc_weight():
    scores = pd.Series({'a': 5, 'b': 4, 'c': 3, 'd': 2, 'e': 1})
    t = ps.build_targets(scores, prev_holdings=[], top_n=2, buffer=3)
    assert list(t['stock_id']) == ['a', 'b'] and t['target_weight'].tolist() == [0.5, 0.5] and t['rank'].tolist() == [1, 2]
    t = ps.build_targets(scores, prev_holdings=['c', 'e'], top_n=2, buffer=3)     # c 還在前 3 → 留；e 第 5 → 賣；補 a
    assert list(t['stock_id']) == ['c', 'a']
    t = ps.build_targets(scores, prev_holdings=[], top_n=2, buffer=3, tsmc_weight=0.5)
    assert t.set_index('stock_id')['target_weight'].to_dict() == {'a': 0.25, 'b': 0.25, ps.TSMC: 0.5}
    assert ps.build_targets(pd.Series(dtype=float), [], 2, 3).empty


def test_build_targets_tranche_mode_only_swaps_the_expired_batch():
    scores = pd.Series({'a': 9, 'b': 8, 'c': 7, 'd': 6, 'e': 5, 'f': 4, 'g': 3})
    held = ['e', 'f', 'g', 'd']                       # 上期持股（排名不高也留著）
    t = ps.build_targets(scores, held, top_n=6, buffer=40, tranche_new=2, release=['e'])
    assert list(t['stock_id']) == ['f', 'g', 'd', 'a', 'b', 'c']   # 只賣到期那批 e；持股不足 top_n 時補滿（下市缺口才不會一直空著）
    assert t['target_weight'].round(6).tolist() == [round(1 / 6, 6)] * 6
    # 初期沒持股：一次最多補到 top_n（不只一批）
    t0 = ps.build_targets(scores, [], top_n=6, buffer=40, tranche_new=2, release=[])
    assert list(t0['stock_id']) == ['a', 'b', 'c', 'd', 'e', 'f']


def test_composite_scores_are_rank_averages_and_require_all_parts():
    mkt, _ = _market(n_days=80)
    d = pd.Timestamp('2024-03-11')
    ids = pd.Index(['1111', '2222', '3333'])
    sur = pd.DataFrame([{'stock_id': '1111', 'revenue_month': pd.Timestamp('2024-03-01'), 'sue': 1.0, 'announce_date': pd.NaT, 'announce_ts': pd.NaT, 'announce_source': None},
                        {'stock_id': '2222', 'revenue_month': pd.Timestamp('2024-03-01'), 'sue': -1.0, 'announce_date': pd.NaT, 'announce_ts': pd.NaT, 'announce_source': None}])
    c = ps.scores_on('win+sue', mkt, sur, d, ids)
    assert set(c.index) == {'1111', '2222'}                         # 3333 沒有 SUE → 不進組合
    w = ps.signal_win(mkt, d).reindex(ids).rank(pct=True)
    s = ps.signal_sue(sur, d).reindex(ids).rank(pct=True)
    assert c['1111'] == pytest.approx((w['1111'] + s['1111']) / 2)
    assert ps.signal_mom(mkt, d).empty                               # 80 天不夠 252 日動能
    assert set(ps.signal_win3(mkt, d).index) >= set(ids)


def test_estimate_tsmc_weight_recovers_known_mix():
    """0050 = 0.5 × 台積電 + 0.5 × 其他等權 → 估計約 0.5；歷史不足 120 天 → None。"""
    rng = np.random.default_rng(3)
    days = pd.bdate_range('2023-01-02', periods=320)
    others = [str(1000 + i) for i in range(6)]
    r = {s: rng.normal(0.0005, 0.015, len(days)) for s in others}
    r[ps.TSMC] = rng.normal(0.0005, 0.02, len(days))
    r[ps.BENCH] = 0.5 * r[ps.TSMC] + 0.5 * np.mean([r[s] for s in others], axis=0)
    rows = []
    for s, ret in r.items():
        px = 100 * np.cumprod(1 + ret)
        for d, p in zip(days, px):
            rows.append({'stock_id': s, 'trade_date': d, 'open_price': p, 'high_price': p, 'low_price': p, 'close_price': p, 'adj_close': p, 'turnover_value': 1e8})
    meta = pd.DataFrame({'stock_id': others + [ps.TSMC], 'listing_date': pd.NaT, 'delisted_date': pd.NaT}).set_index('stock_id')
    mkt = ps.Market(pd.DataFrame(rows), meta)
    w = ps.estimate_tsmc_weight(mkt, days[-1])
    assert w == pytest.approx(0.5, abs=0.03)
    assert ps.estimate_tsmc_weight(mkt, days[100]) is None


def test_family_signals_shapes_and_point_in_time():
    mkt, _ = _market(n_days=300, start='2023-06-01')
    d = pd.Timestamp('2024-07-11')
    lv, hi, rv, vc = ps.signal_lowvol(mkt, d), ps.signal_hi52(mkt, d), ps.signal_rev1m(mkt, d), ps.signal_volchg(mkt, d)
    for s in (lv, hi, rv, vc):
        assert '1111' in s.index and np.isfinite(s['1111'])
    assert (lv <= 0).all() and (hi <= 1.0 + 1e-9).all()
    assert rv['1111'] == pytest.approx(-mkt.ar.loc[:d, '1111'].iloc[-21:].sum())
    assert ps.signal_hi52(mkt, pd.Timestamp('2023-09-01')).empty          # 不足 252 日
    months = pd.date_range('2021-01-01', '2024-07-01', freq='MS')
    rev = pd.DataFrame(_rev('1111', months, growth=0.03) + _rev('2222', months, growth=-0.01))
    sur = ps.surprises(rev)
    acc, streak = ps.signal_rev_accel(sur, d), ps.signal_rev_streak(sur, d)
    assert set(acc.index) == {'1111', '2222'} and streak['1111'] > streak['2222'] == 0
    # 訊號日所在月還沒公布的（revenue_month 在下個月）不會被用到
    assert ps.signal_rev_streak(sur, pd.Timestamp('2024-09-11')).empty
    assert len(ps.scores_on('rev_accel+mom', mkt, sur, d, pd.Index(['1111', '2222']))) == 2


def test_resmom_strips_beta_and_is_point_in_time():
    """殘差動能：一檔只是 β = 2 跟著 0050 漲（無 α）的股票，`mom` 會把它排很前面，`resmom` 不會；不足 252 日回空。"""
    rng = np.random.default_rng(7)
    days = pd.bdate_range('2023-01-02', periods=320)
    rb = rng.normal(0.002, 0.008, len(days))                # 0050 一路漲（趨勢夠大，隨機種子不會翻成負）
    r = {'hibeta': 2.0 * rb + rng.normal(0, 0.002, len(days)),       # 高 β、無 α
         'alpha': rb + 0.001 + rng.normal(0, 0.002, len(days)),      # β = 1、正 α（真正的個股動能）
         'flat': rb * 0.0 + rng.normal(0, 0.01, len(days)),
         ps.BENCH: rb}
    rows = []
    for sid, ret in r.items():
        px = 100 * np.cumprod(1 + ret)
        for d, p in zip(days, px):
            rows.append({'stock_id': sid, 'trade_date': d, 'open_price': p, 'high_price': p, 'low_price': p, 'close_price': p, 'adj_close': p, 'turnover_value': 1e8})
    meta = pd.DataFrame({'stock_id': ['hibeta', 'alpha', 'flat'], 'listing_date': pd.NaT, 'delisted_date': pd.NaT}).set_index('stock_id')
    mkt = ps.Market(pd.DataFrame(rows), meta)
    d = days[-1]
    mom, res = ps.signal_mom(mkt, d), ps.signal_resmom(mkt, d)
    assert mom['hibeta'] > mom['flat']                  # 減 0050 的動能把高 β 當成強勢（flat 的異常報酬就是 −0050）
    # 殘差動能看的是 α：有 α 的為正且排第一；高 β 無 α 的殘差只剩波動拖累（log 報酬的凸性），不會因為 β 高而排前面
    assert res['alpha'] > 0 and res.idxmax() == 'alpha' and res['hibeta'] < res['alpha'] / 5
    # α = 0.001／日 × 231 日 ÷ 殘差標準差 0.002 ≈ 115。若在同一窗口帶截距做 OLS，殘差總和恆為 0，
    # 這個值會變成「最近 21 日殘差的負值 ÷ 標準差」，只剩 ±幾——這條斷言就是抓那個錯誤用的
    assert res['alpha'] > 50
    assert ps.signal_resmom(mkt, days[200]).empty       # 不足 252 日
    # 只用 d 以前的資料：改動 d 之後的價格不影響訊號
    mkt2 = ps.Market(pd.DataFrame(rows), meta)
    mkt2.adj.iloc[-1] = mkt2.adj.iloc[-1] * 5
    assert ps.signal_resmom(mkt2, days[-2]).equals(ps.signal_resmom(mkt, days[-2]))


def test_rev_yoy3_and_market_state_gate():
    months = pd.date_range('2021-01-01', '2024-07-01', freq='MS')
    rev = pd.DataFrame(_rev('1111', months, growth=0.03) + _rev('2222', months, growth=-0.01))
    sur = ps.surprises(rev)
    d = pd.Timestamp('2024-07-11')
    y = ps.signal_rev_yoy3(sur, d)
    assert y['1111'] > 0 > y['2222']
    assert y['1111'] == pytest.approx(sur[(sur.stock_id == '1111') & (sur.revenue_month <= '2024-07-01')]['yoy'].iloc[-3:].mean())
    assert ps.signal_rev_yoy3(sur, pd.Timestamp('2024-09-11')).empty          # 當月那一期還沒有
    # sur 裡有未來月份（2024-08、2024-09）時，7/11 的訊號不能用到它們
    months_fut = pd.date_range('2021-01-01', '2024-09-01', freq='MS')
    sur_fut = ps.surprises(pd.DataFrame(_rev('1111', months_fut, growth=0.03, jump_at=pd.Timestamp('2024-08-01'), jump=5.0) + _rev('2222', months_fut, growth=-0.01)))
    assert ps.signal_rev_yoy3(sur_fut, d).equals(y)
    # 市場狀態閘門：合成市場 0050 緩漲 → UP → `mom~up` 照常參與；人工把 0050 改成一年跌 → DOWN → 成分拿掉
    mkt, _ = _market(n_days=300, start='2023-06-01')
    ids = pd.Index(['1111', '2222', '3333', '4444'])
    assert ps.market_state_up(mkt, d) is True
    up = ps.scores_on('win3+mom~up', mkt, sur, d, ids)
    assert up.equals(ps.scores_on('win3+mom', mkt, sur, d, ids))
    mkt.adj[ps.BENCH] = mkt.adj[ps.BENCH].values[::-1]           # 把 0050 倒過來：過去一年是跌的
    assert ps.market_state_up(mkt, d) is False
    down = ps.scores_on('win3+mom~up', mkt, sur, d, ids)
    assert down.equals(ps.scores_on('win3', mkt, sur, d, ids))
    assert ps.scores_on('mom~up', mkt, sur, d, ids).empty          # 全部成分都被閘門拿掉 → 那個月不調倉
    assert ps.market_state_up(mkt, pd.Timestamp('2023-08-01')) is None


def test_three_year_gate_uses_bench_history():
    """~up3：載入範圍只有 300 天時三年期算不出（不閘門）；掛上 0050 長序列 bench_hist 後用它算，且只看 ≤ d 的部分。"""
    mkt, _ = _market(n_days=300, start='2023-06-01')
    d = pd.Timestamp('2024-07-11')
    ids = pd.Index(['1111', '2222', '3333', '4444'])
    assert ps.market_state_up(mkt, d, 756) is None
    assert ps.scores_on('win3+mom~up3', mkt, sur_empty(), d, ids).equals(ps.scores_on('win3+mom', mkt, sur_empty(), d, ids))
    days = pd.bdate_range('2020-01-01', '2024-12-31')
    hist = pd.Series(np.linspace(200.0, 100.0, len(days)), index=days)          # 一路跌 → 三年 DOWN
    mkt.bench_hist = hist
    assert ps.market_state_up(mkt, d, 756) is False
    assert ps.scores_on('win3+mom~up3', mkt, sur_empty(), d, ids).equals(ps.scores_on('win3', mkt, sur_empty(), d, ids))
    up = hist[::-1].set_axis(days).copy()                                        # 一路漲 → UP
    up[up.index > d] = 1.0                                                       # d 之後崩到 1：若沒切 ≤ d，三年報酬會變負
    mkt.bench_hist = up
    assert ps.market_state_up(mkt, d, 756) is True
    assert ps.needs_bench_history('win3+mom~up3') and not ps.needs_bench_history('win3+mom~up')
    assert ps._gated_parts('win3+mom~up3', mkt, d) == ['win3', 'mom']


def test_momrev_keeps_only_positive_sue():
    """以營收為條件的動能：值等於 mom，但只留當月 SUE > 0 的股票；沒有 SUE 或 SUE ≤ 0 的不給值。"""
    mkt, _ = _market(n_days=300, start='2023-06-01')
    d = pd.Timestamp('2024-07-11')
    sur = pd.DataFrame([{'stock_id': '1111', 'revenue_month': pd.Timestamp('2024-07-01'), 'sue': 1.2},
                        {'stock_id': '2222', 'revenue_month': pd.Timestamp('2024-07-01'), 'sue': -0.3},
                        {'stock_id': '3333', 'revenue_month': pd.Timestamp('2024-06-01'), 'sue': 2.0}])     # 上個月的，當月沒有
    for c in ('announce_date', 'announce_ts', 'announce_source'):
        sur[c] = pd.NaT if c != 'announce_source' else None
    mom, mr = ps.signal_mom(mkt, d), ps.signal_momrev(mkt, sur, d)
    assert list(mr.index) == ['1111'] and mr['1111'] == pytest.approx(mom['1111'])
    ids = pd.Index(['1111', '2222', '3333', '4444'])
    assert set(ps.scores_on('win3+momrev', mkt, sur, d, ids).index) == {'1111'}       # 組合裡其他股票因缺成分被排除


def test_cont_prefers_many_small_gains_over_one_jump():
    """資訊連續性：同樣的累積報酬，天天小漲的股票 cont 高、一次跳空的低；值在 [−1, 1]；只看 12-1 窗口、不足 252 日回空。"""
    mkt, prices = _market(n_days=300, start='2023-06-01')
    d = pd.Timestamp('2024-07-11')
    days = mkt.adj.index
    bench = mkt.adj[ps.BENCH]
    i = days.get_loc(d)
    # 1111：形成期每天比 0050 多 0.1%；2222：只在形成期中間一天多 23%（累積差不多），其餘和 0050 同步
    steady = bench * (1.001 ** np.arange(len(days)))
    jump = bench.copy()
    jump.iloc[i - 150:] *= 1.23
    for sid, s in (('1111', steady), ('2222', jump)):
        mkt.adj[sid] = s.values
        mkt.close[sid] = s.values
    mkt.ar = np.log(mkt.adj).diff().sub(np.log(mkt.adj[ps.BENCH]).diff(), axis=0)
    c = ps.signal_cont(mkt, d)
    assert c['1111'] == pytest.approx(1.0) and abs(c['2222']) < 0.05
    assert ps.signal_mom(mkt, d)['1111'] == pytest.approx(ps.signal_mom(mkt, d)['2222'], abs=0.05)   # 累積差不多，只有連續性不同
    assert c.between(-1, 1).all()
    assert ps.signal_cont(mkt, days[200]).empty
    # 窗口外（最近 21 日）的大跌不影響
    mkt.ar.iloc[i - 5, mkt.ar.columns.get_loc('1111')] = -0.5
    assert ps.signal_cont(mkt, d)['1111'] == pytest.approx(1.0)


def test_imom_counts_only_intraday_returns():
    """日內動能：報酬全在隔夜（開盤跳上去、盤中不動）的股票 imom ≈ 0，全在盤中的股票 imom > 0；開盤 ≤ 0 當缺值。"""
    mkt, prices = _market(n_days=300, start='2023-06-01')
    d = pd.Timestamp('2024-07-11')
    p = prices.copy()
    g = 1.002
    for sid, mode in (('1111', 'overnight'), ('2222', 'intraday')):
        m = p['stock_id'] == sid
        n = m.sum()
        px = 100.0 * g ** np.arange(n)
        p.loc[m, 'close_price'] = px
        p.loc[m, 'adj_close'] = px
        p.loc[m, 'open_price'] = px if mode == 'overnight' else px / g       # 隔夜型：開盤 = 收盤；日內型：開盤 = 前收
    b = p['stock_id'] == ps.BENCH
    p.loc[b, 'open_price'] = p.loc[b, 'close_price']                          # 0050 日內報酬 0，方便看絕對值
    p.loc[(p['stock_id'] == '3333') & (p['trade_date'] == pd.Timestamp('2024-03-01')), 'open_price'] = 0.0
    mkt2 = ps.Market(p, mkt.meta)
    im = ps.signal_imom(mkt2, d)
    assert im['1111'] == pytest.approx(0.0, abs=1e-9)
    assert im['2222'] == pytest.approx(np.log(g) * (252 - 21), rel=1e-6)
    assert np.isnan(mkt2.ar_intra.at[pd.Timestamp('2024-03-01'), '3333']) and '3333' in im.index   # 一天缺值不影響 min_count
    assert ps.signal_imom(mkt2, mkt2.adj.index[200]).empty
    # mom 對兩檔一樣（總報酬相同），imom 把隔夜型排到後面
    mom = ps.signal_mom(mkt2, d)
    assert mom['1111'] == pytest.approx(mom['2222'])


def test_mom127_skips_last_six_months():
    """中期動能 12-7：最近 126 個交易日的大漲不影響；形成期 = 252 到 126 日前。"""
    mkt, _ = _market(n_days=300, start='2023-06-01')
    d = pd.Timestamp('2024-07-11')
    i = mkt.adj.index.get_loc(d)
    before = ps.signal_mom127(mkt, d)
    mkt.ar.iloc[i - 100, mkt.ar.columns.get_loc('1111')] += 0.5
    after = ps.signal_mom127(mkt, d)
    assert after['1111'] == pytest.approx(before['1111'])
    mkt.ar.iloc[i - 130, mkt.ar.columns.get_loc('1111')] += 0.5
    assert ps.signal_mom127(mkt, d)['1111'] == pytest.approx(before['1111'] + 0.5)
    assert ps.signal_mom127(mkt, mkt.adj.index[200]).empty
    ids = pd.Index(['1111', '2222', '3333', '4444'])
    assert len(ps.scores_on('win3+mom127', mkt, sur_empty(), d, ids)) == 4


def test_ovn1m_counts_only_last_month_overnight():
    """隔夜短期持續：報酬全在隔夜的股票 ovn1m = 21 天的隔夜報酬，全在盤中的 ≈ 0；只看最近 21 天；不足回空。"""
    mkt, prices = _market(n_days=300, start='2023-06-01')
    d = pd.Timestamp('2024-07-11')
    p = prices.copy()
    g = 1.002
    for sid, mode in (('1111', 'overnight'), ('2222', 'intraday')):
        m = p['stock_id'] == sid
        px = 100.0 * g ** np.arange(m.sum())
        p.loc[m, 'close_price'] = px
        p.loc[m, 'adj_close'] = px
        p.loc[m, 'open_price'] = px if mode == 'overnight' else px / g
    b = p['stock_id'] == ps.BENCH
    p.loc[b, 'open_price'] = p.loc[b, 'close_price']
    bench_adj = p.loc[b].set_index('trade_date')['adj_close']
    mkt2 = ps.Market(p, mkt.meta)
    ov = ps.signal_ovn1m(mkt2, d)
    i = mkt2.adj.index.get_loc(d)
    bench_ovn = np.log(bench_adj).diff().iloc[i - 20:i + 1].sum()                      # 0050 的報酬全在隔夜（開盤 = 收盤）
    assert ov['1111'] == pytest.approx(21 * np.log(g) - bench_ovn, rel=1e-6)
    assert ov['2222'] == pytest.approx(-bench_ovn, rel=1e-6)
    assert ps.signal_ovn1m(mkt2, mkt2.adj.index[10]).empty
    # 22 天前的隔夜跳空不算
    mkt2.ar_over.iloc[i - 21, mkt2.ar_over.columns.get_loc('1111')] += 1.0
    assert ps.signal_ovn1m(mkt2, d)['1111'] == pytest.approx(ov['1111'], rel=1e-6)


def test_illiq_is_higher_for_thin_stocks_and_point_in_time():
    """Amihud 非流動性：同樣的報酬、成交金額小 10 倍的股票 illiq 高 log(10)；不足 252 日回空；成交金額 0 的日子當缺值。"""
    mkt, prices = _market(n_days=300, start='2023-06-01')
    d = pd.Timestamp('2024-07-11')
    p = prices.copy()
    for sid in ('1111', '2222'):
        m = p['stock_id'] == sid
        p.loc[m, 'close_price'] = p.loc[p['stock_id'] == '3333', 'close_price'].values
        p.loc[m, 'adj_close'] = p.loc[m, 'close_price']
        p.loc[m, 'turnover_value'] = 1e8 if sid == '1111' else 1e7
    p.loc[(p['stock_id'] == '1111') & (p['trade_date'] == pd.Timestamp('2024-03-01')), 'turnover_value'] = 0.0
    mkt2 = ps.Market(p, mkt.meta)
    il = ps.signal_illiq(mkt2, d)
    assert il['2222'] - il['1111'] == pytest.approx(np.log(10), abs=0.02)      # 一天缺值讓平均略不同
    assert ps.signal_illiq(mkt2, mkt2.adj.index[200]).empty
    # 點時：d 之後的資料與 253 天前的資料都不影響；d 當天的成交金額會
    i = mkt2.adj.index.get_loc(d)
    c2 = mkt2.turnover.columns.get_loc('2222')
    mkt2.turnover.iloc[i + 1, c2] = 1.0
    mkt2.turnover.iloc[i - 253, c2] = 1.0
    assert ps.signal_illiq(mkt2, d)['2222'] == pytest.approx(il['2222'])
    mkt2.turnover.iloc[i, c2] = 1.0
    assert ps.signal_illiq(mkt2, d)['2222'] > il['2222']
    ids = pd.Index(['1111', '2222', '3333', '4444'])
    assert len(ps.scores_on('win3+mom+illiq', mkt2, sur_empty(), d, ids)) == 4


def test_indmom_and_relmom_use_industry_means_with_min_members():
    """產業動能：同產業 ≥ 5 檔才有值、值 = 產業 mom 平均；relmom = mom − indmom；沒有產業欄位回空。"""
    stocks = tuple(f'{1000 + i}' for i in range(8))
    meta = pd.DataFrame({'stock_id': list(stocks), 'listing_date': pd.NaT, 'delisted_date': pd.NaT,
                         'industry_type': ['半導體業'] * 5 + ['航運業'] * 2 + [None]}).set_index('stock_id')
    mkt, _ = _market(n_days=300, start='2023-06-01', stocks=stocks, meta=meta)
    d = pd.Timestamp('2024-07-11')
    mom = ps.signal_mom(mkt, d)
    im = ps.signal_indmom(mkt, d)
    assert set(im.index) == set(stocks[:5])                                   # 航運只有 2 檔、第八檔沒產業 → 沒值
    assert im.iloc[0] == pytest.approx(mom[list(stocks[:5])].mean())
    rm = ps.signal_relmom(mkt, d)
    assert rm['1000'] == pytest.approx(mom['1000'] - im['1000'])
    assert abs(rm[list(stocks[:5])].sum()) < 1e-9                             # 同產業相對動能和為 0
    plain, _ = _market(n_days=300, start='2023-06-01')                       # meta 沒有 industry_type
    assert ps.signal_indmom(plain, d).empty and ps.signal_relmom(plain, d).empty
    ids = pd.Index(stocks)
    assert set(ps.scores_on('win3+mom+indmom', mkt, sur_empty(), d, ids).index) == set(stocks[:5])


def test_seas_averages_same_month_windows_of_prior_years():
    """同月季節性：前 1～3 年「同月 11 日之後到次月 11 日之後」的累積異常報酬平均；只有一年歷史就用一年；窗口外的報酬不影響。"""
    mkt, _ = _market(n_days=800, start='2021-01-04')
    days = mkt.adj.index
    d = days[days.searchsorted(pd.Timestamp('2024-01-11'))]
    col = mkt.ar.columns.get_loc('1111')
    # 2023-01-12 ~ 2023-02-13 與 2022-01-12 ~ 2022-02-11 各塞一個 +0.5；2021 的窗口在資料前（start 2021-01-04 有，塞 +0.2）
    def window(y):
        s = days.searchsorted(pd.Timestamp(year=y, month=1, day=11))
        e = days.searchsorted(pd.Timestamp(year=y, month=2, day=11))
        return s + 1, e + 1
    base = {y: mkt.ar.iloc[slice(*window(y)), col].sum() for y in (2021, 2022, 2023)}
    before = ps.signal_seas(mkt, d)['1111']
    assert before == pytest.approx(np.mean(list(base.values())))
    s1, _ = window(2023)
    mkt.ar.iloc[s1, col] += 0.5
    assert ps.signal_seas(mkt, d)['1111'] == pytest.approx(before + 0.5 / 3)
    mkt.ar.iloc[s1 - 1, col] += 5.0                                           # 窗口起點的前一天（訊號日當天）不算
    assert ps.signal_seas(mkt, d)['1111'] == pytest.approx(before + 0.5 / 3)
    d2 = days[days.searchsorted(pd.Timestamp('2022-03-11'))]                   # 只有 2021 一年可回看
    one = ps.signal_seas(mkt, d2)
    assert not one.empty and ps.signal_seas(mkt, days[5]).empty
    # 窗口起點早於資料起點（資料 2021-01-04 起，前一年 2020-12-11 沒有）→ 半截窗口不算、回空
    d4 = days[days.searchsorted(pd.Timestamp('2021-12-13'))]
    assert ps.signal_seas(mkt, d4).empty
    d5 = days[days.searchsorted(pd.Timestamp('2022-01-11'))]                   # 2021-01-11 起的窗口完整 → 有值
    assert not ps.signal_seas(mkt, d5).empty


def test_fflow_is_net_buy_value_over_turnover_in_last_21_days():
    """法人流量：Σ(淨買超股數 × 收盤) ÷ Σ 成交金額，最近 21 日含訊號日；沒掛法人表回空；有值天數不足 80% 不給值；d 之後的不算。"""
    mkt, _ = _market(n_days=120, start='2024-01-02')
    d = pd.Timestamp('2024-05-13')
    assert ps.signal_fflow(mkt, d).empty                                        # mkt.insti 沒掛
    days = mkt.adj.index
    i = days.get_loc(d)
    win = days[i - 20:i + 1]
    fn = pd.DataFrame(0.0, index=days, columns=mkt.close.columns)
    fn.loc[win, '1111'] = 1000.0                                                # 每天淨買 1,000 股
    fn.loc[days[i + 1], '1111'] = 1e9                                           # 訊號日之後的大買不算
    fn.loc[win[:10], '2222'] = 500.0                                            # 只有 10 天有值
    fn.loc[win[10:], '2222'] = np.nan
    mkt.insti = {'foreign_net': fn, 'trust_net': fn * 0}
    ff = ps.signal_fflow(mkt, d)
    expect = (1000.0 * mkt.close.loc[win, '1111']).sum() / mkt.turnover.loc[win, '1111'].sum()
    assert ff['1111'] == pytest.approx(expect)
    assert '2222' not in ff.index
    fn.loc[win[:16], '3333'] = 1.0                                               # 16/21 ≥ 80% → 有值；15/21 → 沒有
    fn.loc[win[16:], '3333'] = np.nan
    fn.loc[win[:15], '4444'] = 1.0
    fn.loc[win[15:], '4444'] = np.nan
    ff2 = ps.signal_fflow(mkt, d)
    assert '3333' in ff2.index and '4444' not in ff2.index
    assert ps.signal_tflow(mkt, d)['1111'] == 0.0
    assert ps.needs_institutional('win3+mom+fflow') and not ps.needs_institutional('win3+mom')
    ids = pd.Index(['1111', '3333', '4444'])
    assert set(ps.scores_on('win3+mom+fflow', mkt, sur_empty(), d, ids).index) <= {'1111', '3333', '4444'}


def test_vmom_divides_mom_by_same_window_vol_and_momx_drops_top_decile_vol():
    """波動處理的動能（Iteration 78）：vmom ＝ mom ÷ 同 12-1 窗口的日異常報酬標準差；momx ＝ mom 但波動最高十分位不給值；歷史不足回空。"""
    mkt, prices = _market(n_days=300, start='2023-06-01')
    d = pd.Timestamp('2024-07-11')
    mom = ps.signal_mom(mkt, d)
    sl = ps._mom_window(mkt, d, 252, 21)
    seg = mkt.ar.iloc[sl]
    vm = ps.signal_vmom(mkt, d)
    assert set(vm.index) == {s for s in mom.index if seg[s].std() > 0}         # 0050 對自己的異常報酬恆為 0，波動 0 不給值
    for sid in vm.index:
        assert vm[sid] == pytest.approx(mom[sid] / seg[sid].std())
    assert ps.signal_vmom(mkt, mkt.adj.index[200]).empty and ps.signal_momx(mkt, mkt.adj.index[200]).empty
    # 把一檔做成極端波動：momx 不給它值，其他檔的值和 mom 一樣；vmom 把它排到後面
    p = prices.copy()
    m = (p['stock_id'] == '1111') & (p['trade_date'] <= d)
    wild = p.loc[m, 'adj_close'].values * np.where(np.arange(m.sum()) % 2 == 0, 1.3, 0.7)
    p.loc[m, 'adj_close'] = wild
    p.loc[m, 'close_price'] = wild
    mkt2 = ps.Market(p, mkt.meta)
    mom2, mx2, vm2 = ps.signal_mom(mkt2, d), ps.signal_momx(mkt2, d), ps.signal_vmom(mkt2, d)
    assert '1111' in mom2.index and '1111' not in mx2.index
    others = [s for s in mom2.index if s != '1111']
    assert (mx2.reindex(others) == mom2.reindex(others)).all()
    assert vm2.rank()['1111'] <= vm2.rank().drop('1111').min() or abs(vm2['1111']) < abs(vm2.drop('1111')).min()
    ids = pd.Index(list(mom2.index))
    assert len(ps.scores_on('win3+vmom', mkt2, sur_empty(), d, ids)) >= 1
    assert '1111' not in ps.scores_on('win3+momx', mkt2, sur_empty(), d, ids).index


def test_dy_and_ep_read_valuation_on_signal_day_with_lag_and_exclusions():
    """價值訊號（Iteration 80）：dy 取訊號日的殖利率（> 30 不給值、0 照給），ep ＝ 1 ÷ 本益比（虧損沒有值）；d 沒列就沿用最近 5 個交易日；d 之後的不算；沒掛表回空。"""
    mkt, _ = _market(n_days=120, start='2024-01-02')
    d = pd.Timestamp('2024-05-13')
    assert ps.signal_dy(mkt, d).empty and ps.signal_ep(mkt, d).empty
    days = mkt.adj.index
    i = days.get_loc(d)
    cols = mkt.close.columns
    dy = pd.DataFrame(np.nan, index=days, columns=cols)
    pe = pd.DataFrame(np.nan, index=days, columns=cols)
    dy.loc[d, '1111'], pe.loc[d, '1111'] = 4.5, 12.0
    dy.loc[d, '2222'], pe.loc[d, '2222'] = 0.0, np.nan                         # 沒配息、虧損
    dy.loc[d, '3333'], pe.loc[d, '3333'] = 76.0, 8.0                           # 一次性大額股利
    dy.loc[days[i - 5], '4444'], pe.loc[days[i - 5], '4444'] = 3.0, 20.0       # 五天前的最後一筆：沿用
    dy.loc[days[i - 6], '5555'], pe.loc[days[i - 6], '5555'] = 9.0, 5.0        # 六天前：太舊
    dy.loc[days[i + 1], '5555'], pe.loc[days[i + 1], '5555'] = 9.0, 5.0        # d 之後：不算
    mkt.val = {'dividend_yield': dy, 'pe': pe}
    s_dy, s_ep = ps.signal_dy(mkt, d), ps.signal_ep(mkt, d)
    assert s_dy['1111'] == 4.5 and s_dy['2222'] == 0.0 and s_dy['4444'] == 3.0
    assert '3333' not in s_dy.index and '5555' not in s_dy.index
    assert s_ep['1111'] == pytest.approx(1 / 12) and s_ep['3333'] == pytest.approx(1 / 8) and s_ep['4444'] == pytest.approx(1 / 20)
    assert '2222' not in s_ep.index and '5555' not in s_ep.index
    assert ps.needs_valuation('win3+mom+dy') and ps.needs_valuation('ep') and not ps.needs_valuation('win3+mom')
    ids = pd.Index(['1111', '2222', '3333', '4444'])
    assert set(ps.scores_on('dy', mkt, sur_empty(), d, ids).index) == {'1111', '2222', '4444'}


def sur_empty():
    return pd.DataFrame(columns=['stock_id', 'revenue_month', 'yoy', 'surprise', 'sue', 'announce_date', 'announce_ts', 'announce_source'])


def test_liq_weighting_caps_single_name():
    liq = pd.Series({'a': 1000.0, 'b': 10.0, 'c': 10.0})
    w = ps._weights(['a', 'b', 'c'], 1.0, 'liq', liq, cap=0.5)
    assert w['a'] == pytest.approx(0.5) and w['b'] == pytest.approx(0.25) and w['c'] == pytest.approx(0.25)
    assert ps._weights(['a', 'b'], 0.8, 'equal', None) == {'a': 0.4, 'b': 0.4}


def test_simulate_tranches_cut_turnover():
    """分批輪動：每月只換 1/3，年換手應該明顯低於月月重排。"""
    mkt, _ = _market(n_days=300, stocks=tuple(str(1000 + i) for i in range(12)), start='2023-06-01')
    base = pb.simulate(mkt, pd.DataFrame(), 'win', date(2024, 1, 1), date(2024, 10, 31), top_n=6, buffer=6, universe_n=12, excl_limit_pct=0)
    tr = pb.simulate(mkt, pd.DataFrame(), 'win', date(2024, 1, 1), date(2024, 10, 31), top_n=6, buffer=6, universe_n=12, excl_limit_pct=0, tranches=3)
    assert tr['traded_total'] < base['traded_total']
    assert tr['n_rebalances'] == base['n_rebalances']


# ── 模擬帳 ────────────────────────────────────────────────────────────────────
def _flat_market(stocks=('1111', '2222'), n_days=100, start='2023-11-01', price=100.0, drift=0.0):
    days = pd.bdate_range(start, periods=n_days)
    rows = []
    for k, sid in enumerate(list(stocks) + [ps.BENCH]):
        for i, d in enumerate(days):
            px = price * (1 + drift) ** i
            rows.append({'stock_id': sid, 'trade_date': d, 'open_price': px, 'high_price': px, 'low_price': px, 'close_price': px,
                         'adj_close': px, 'turnover_value': 1e8 * (10 - k)})
    meta = pd.DataFrame({'stock_id': list(stocks), 'listing_date': pd.NaT, 'delisted_date': pd.NaT}).set_index('stock_id')
    return pd.DataFrame(rows), meta


def test_simulate_costs_and_flat_prices():
    """價格不動：買 2 檔各半後 NAV 只少掉買進成本（手續費 + 滑價），下月續抱不交易。"""
    prices, meta = _flat_market()
    mkt = ps.Market(prices, meta)
    scores = pd.Series({'1111': 2.0, '2222': 1.0})
    sim = pb.simulate(mkt, pd.DataFrame(), 'win', date(2024, 1, 1), date(2024, 2, 29), top_n=2, buffer=40, universe_n=5, excl_limit_pct=0)
    nav = sim['nav']
    buy_cost = pb.COSTS['fee'] + pb.COSTS['slip']
    assert nav.iloc[-1] == pytest.approx(1 / (1 + buy_cost), rel=1e-6)     # 全部投入：本金 = 市值 × (1 + 成本)
    assert sim['n_rebalances'] == 2 and len(sim['positions']) == 4 and sim['positions']['filled'].all()
    assert sum(1 for t in sim['trades'] if t[2] == 'buy') == 2         # 第二個月名單不變、權重不變 → 不交易
    assert sim['cost_total'] == pytest.approx(buy_cost / (1 + buy_cost), rel=1e-6)


def test_simulate_unfilled_when_locked_and_forced_liquidation():
    prices, meta = _flat_market(stocks=('1111', '2222', '3333'), n_days=140)
    # 2222 在第一個成交日（1/12）一字漲停：高 = 低 = 開 = 前收 × 1.1
    d_exec = pd.Timestamp('2024-01-12')
    sel = (prices['stock_id'] == '2222') & (prices['trade_date'] == d_exec)
    prices.loc[sel, ['open_price', 'high_price', 'low_price', 'close_price', 'adj_close']] = 110.0
    # 3333 從 2/1 起沒有價格（下市）
    prices = prices[~((prices['stock_id'] == '3333') & (prices['trade_date'] >= '2024-02-01'))]
    mkt = ps.Market(prices, meta)
    assert bool(mkt.locked.at[d_exec, '2222'])
    sim = pb.simulate(mkt, pd.DataFrame(), 'win', date(2024, 1, 1), date(2024, 4, 30), top_n=3, buffer=40, universe_n=5, excl_limit_pct=0)
    first = sim['positions'][sim['positions']['exec_date'] == d_exec.date()].set_index('stock_id')
    assert first.loc['2222', 'filled'] == False and first.loc['1111', 'filled'] == True   # noqa: E712
    assert any(t[2] == 'forced_sell' and t[1] == '3333' for t in sim['trades'])
    assert sim['nav'].notna().all() and sim['nav'].iloc[-1] > 0.9


def test_simulate_holds_when_signal_missing():
    """訊號不足 top_n 檔的月份不調倉：持股照舊、不算換手、不記持股；一旦有訊號才建倉。"""
    prices, meta = _flat_market(stocks=('1111', '2222'), n_days=140)
    mkt = ps.Market(prices, meta)
    d = pd.Timestamp('2024-03-11')
    sur = pd.DataFrame([{'stock_id': s, 'revenue_month': pd.Timestamp('2024-03-01'), 'sue': v, 'announce_date': pd.NaT, 'announce_ts': pd.NaT, 'announce_source': None}
                        for s, v in (('1111', 1.0), ('2222', 0.5))])
    sim = pb.simulate(mkt, sur, 'sue', date(2024, 1, 1), date(2024, 4, 30), top_n=2, buffer=40, universe_n=5, excl_limit_pct=0)
    assert sim['skipped'] == [date(2024, 1, 11), date(2024, 2, 12), date(2024, 4, 11)]      # 只有 3 月有 SUE
    assert sim['n_rebalances'] == 1 and set(sim['positions']['rebalance_date']) == {d.date()}
    assert sim['nav'].loc[:'2024-03-11'].eq(1.0).all() and sim['nav'].iloc[-1] < 1.0          # 3/12 才建倉、吃到成本
    assert sum(1 for t in sim['trades'] if t[2] == 'buy') == 2


def test_metrics_shape_and_active_sign():
    prices, meta = _flat_market(stocks=('1111', '2222'), n_days=310, drift=0.001)
    # 組合股每天漲 0.1%，0050 不漲 → 主動報酬為正
    prices.loc[prices['stock_id'] == ps.BENCH, ['open_price', 'high_price', 'low_price', 'close_price', 'adj_close']] = 100.0
    mkt = ps.Market(prices, meta)
    sim = pb.simulate(mkt, pd.DataFrame(), 'win', date(2024, 1, 1), date(2024, 12, 31), top_n=2, buffer=40, universe_n=5, excl_limit_pct=0)
    met, m_act = pb.metrics(sim['nav'], mkt.adj[ps.BENCH], sim)
    assert met['ann_active'] > 0.15 and met['info_ratio'] > 0 and met['monthly_win_rate'] >= 0.9   # 第一個月吃掉建倉成本
    assert met['months'] == len(m_act) and met['cagr_bench'] == pytest.approx(0.0, abs=1e-9)
    assert met['turnover_annual'] < 1.5 and met['cost_drag_annual'] > 0


# ── 實驗日誌 ──────────────────────────────────────────────────────────────────
@pytest.mark.db
def test_save_run_increments_n_and_prior_variance(clean_db):
    db = clean_db
    assert pb.next_n_and_var() == (1, 0.0)
    pos = pd.DataFrame([{'rebalance_date': date(2024, 1, 11), 'exec_date': date(2024, 1, 12), 'stock_id': '1111', 'rank': 1, 'signal_value': 1.2, 'target_weight': 0.5, 'filled': True},
                        {'rebalance_date': date(2024, 1, 11), 'exec_date': date(2024, 1, 12), 'stock_id': '2330', 'rank': np.nan, 'signal_value': np.nan, 'target_weight': 0.5, 'filled': True}])
    rid = pb.save_run(1, 'a', 'sue', 'dev', date(2024, 1, 1), date(2024, 3, 31), {'top_n': 2}, {'sharpe_m_active': 0.3, 'n_rebalances': 3}, pos, 'first')
    pb.save_run(2, 'b', 'win', 'dev', date(2024, 1, 1), date(2024, 3, 31), {}, {'sharpe_m_active': 0.1, 'n_rebalances': 3}, pd.DataFrame(), '')
    n, var = pb.next_n_and_var()
    assert n == 3 and var == pytest.approx(np.var([0.3, 0.1]))
    assert db.query('SELECT count(*) FROM portfolio_positions WHERE run_id = %s', (rid,))[0][0] == 2
    assert db.query("SELECT rank, signal_value FROM portfolio_positions WHERE stock_id = '2330'")[0] == (None, None)
    log = pb.experiment_log()
    assert list(log['experiment_n']) == [1, 2] and log.iloc[0]['notes'] == 'first'


def test_index_series_aligns_ffills_and_rebases():
    """含息大盤對齊淨值曲線日期：第一天歸一到 1、指數缺的日子沿用前一日、起點沒有指數就整條留空。"""
    import datetime as dt
    import portfolio_api as pa

    class Cur:
        def __init__(self, rows): self.rows = rows
        def execute(self, sql, params=None): pass
        def fetchall(self): return self.rows

    d = [dt.date(2024, 1, 2), dt.date(2024, 1, 3), dt.date(2024, 1, 4)]
    out = pa._index_series(Cur([(d[0], 100.0), (d[2], 110.0)]), d)
    assert out == {d[0]: 1.0, d[1]: 1.0, d[2]: 1.1}
    assert pa._index_series(Cur([(d[1], 100.0)]), d) == {}   # 起點那天沒有指數 → 無法歸一，整條不給
    assert pa._index_series(Cur([]), d) == {}
    assert pa._index_series(Cur([(d[0], 100.0)]), []) == {}
