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
