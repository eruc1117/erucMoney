"""新聞訊號特徵（Iteration 47）的純函式：新穎度、不確定性、每日表合成、面板掛載的時序與缺值語意。不碰資料庫。"""
import numpy as np
import pandas as pd
import pytest

import news_signal_features as F


def _ts(s):
    return pd.Timestamp(s)


# ── 新穎度 ─────────────────────────────────────────────────────────────────────
def test_novelty_first_title_is_one_and_duplicate_is_zero():
    df = pd.DataFrame({
        'stock_id': ['2330'] * 3,
        'effective_date': [_ts('2026-09-01'), _ts('2026-09-02'), _ts('2026-09-02')],
        'title': ['台積電法說會釋出樂觀展望', '台積電法說會釋出樂觀展望', '聯發科推出新晶片'],
    })
    nov = F.novelty_scores(df)
    assert nov.iloc[0] == 1.0                      # 第一則沒有前文可比
    assert nov.iloc[1] == 0.0                      # 與前一天標題完全相同
    assert nov.iloc[2] > 0.8                       # 完全不同的標題


def test_novelty_only_looks_back_lookback_days_and_within_stock():
    days = [_ts(f'2026-09-{d:02d}') for d in (1, 2, 3, 4, 5, 6, 7)]
    df = pd.DataFrame({
        'stock_id': ['2330'] * 7,
        'effective_date': days,
        'title': ['台積電擴廠計畫定案'] + [f'完全無關的標題{i}' for i in range(5)] + ['台積電擴廠計畫定案'],
    })
    nov = F.novelty_scores(df, lookback_days=5)
    assert nov.iloc[-1] == 1.0                     # 第 1 天的標題已經超出 5 個新聞日的回看
    other = pd.DataFrame({'stock_id': ['2303'], 'effective_date': [days[1]], 'title': ['台積電擴廠計畫定案']})
    assert F.novelty_scores(pd.concat([df.iloc[:1], other], ignore_index=True)).iloc[1] == 1.0  # 別檔的標題不算


def test_uncertainty_density_counts_hedging_terms_per_thousand_chars():
    text = '公司預期第四季可能回溫，市場傳出不排除擴產' + '。' * 80    # 預期、可能、市場傳、不排除 = 4 個（「市場傳」吃掉「傳出」，重疊不重複計）
    dens = F.uncertainty_density(text)
    assert dens == pytest.approx(1000 * 4 / len(text))
    assert np.isnan(F.uncertainty_density(''))
    assert np.isnan(F.uncertainty_density('太短'))


# ── 每日表 ─────────────────────────────────────────────────────────────────────
def _daily():
    return pd.DataFrame({
        'stock_id': ['2330', '2330'], 'effective_date': [_ts('2026-09-01'), _ts('2026-09-03')],
        'n_articles': [2, 1], 'sentiment_mean': [0.5, -0.5], 'strong_kw_hit': [1, 0],
    })


def _articles():
    return pd.DataFrame({
        'stock_id': ['2330', '2330', '2330'],
        'effective_date': [_ts('2026-09-01'), _ts('2026-09-01'), _ts('2026-09-03')],
        'news_id': [1, 2, 3], 'platform': ['鉅亨網', '經濟日報', '鉅亨網'], 'grp': ['1', '2', '3'],
        'title': ['台積電漲', '台積電法說', '台積電可能擴產'],
        'content': ['內容' * 30, '內容' * 30, '預期或許' * 20],
    })


def _mops():
    return pd.DataFrame({
        'stock_id': ['2330', '2330', '2330'],
        'effective_date': [_ts('2026-09-01'), _ts('2026-09-02'), _ts('2026-09-02')],
        'event_type': ['營收', '澄清媒體', '注意交易'], 'is_expected': [True, False, False],
    })


def test_daily_news_table_merges_sources_novelty_uncertainty_and_mops():
    t = F.daily_news_table(_daily(), _articles(), _mops()).set_index('effective_date')
    assert t.loc[_ts('2026-09-01'), 'n_sources'] == 2
    assert t.loc[_ts('2026-09-03'), 'n_sources'] == 1
    assert t.loc[_ts('2026-09-03'), 'uncertainty'] > t.loc[_ts('2026-09-01'), 'uncertainty']
    # 9/2 只有 MOPS 沒有媒體新聞：則數 0、注意交易與非例行分開數（注意交易不算非例行）
    assert t.loc[_ts('2026-09-02'), 'n_articles'] == 0
    assert t.loc[_ts('2026-09-02'), 'mops_nonroutine'] == 1
    assert t.loc[_ts('2026-09-02'), 'mops_attention'] == 1
    assert t.loc[_ts('2026-09-01'), 'mops_nonroutine'] == 0      # 營收是例行


# ── 面板掛載 ───────────────────────────────────────────────────────────────────
def _panel(n=70):
    dates = pd.bdate_range('2026-06-01', periods=n)
    return pd.DataFrame({'stock_id': ['2330'] * n, 'trade_date': dates,
                         'adj_close': np.linspace(100, 110, n), 'close': np.linspace(100, 110, n)})


def test_attach_news_features_keeps_nan_without_news_and_zero_counts():
    p = _panel()
    d = p['trade_date']
    table = pd.DataFrame({
        'stock_id': ['2330'], 'effective_date': [d.iloc[65]], 'n_articles': [4], 'n_sources': [2],
        'sent': [0.2], 'strong_kw_hit': [1], 'novelty': [0.9], 'uncertainty': [2.0],
        'mops_nonroutine': [0], 'mops_attention': [0],
    })
    out = F.attach_news_features(p, table)
    quiet, loud = out.iloc[60], out.iloc[65]
    assert quiet['ns_n_articles'] == 0 and quiet['ns_has_news'] == 0
    assert np.isnan(quiet['ns_sent']) and np.isnan(quiet['ns_novelty']) and np.isnan(quiet['ns_uncertainty'])
    assert loud['ns_has_news'] == 1 and loud['ns_sent'] == 0.2 and loud['ns_n_sources'] == 2
    # 前 60 日都沒新聞 → 基準 0，異常注意力 = log1p(4)
    assert loud['ns_abn_attn'] == pytest.approx(np.log1p(4))
    # 3 日情緒衰減：隔天沒新聞 → NaN（不是把昨天的情緒延用）；但 ns_sent_3d 有昨天的值
    nxt = out.iloc[66]
    assert np.isnan(nxt['ns_sent']) and np.isnan(nxt['ns_sent_3d'])
    assert set(F.NEWS_FEATURES).issubset(out.columns)


def test_attach_event_features_uses_only_announced_events_and_1330_rule():
    p = _panel(40)
    d = p['trade_date']
    # 公布時戳 13:30 之後 → t=0 是下一交易日
    sur = pd.DataFrame({
        'stock_id': ['2330'], 'revenue_month': [_ts('2026-06-01')], 'yoy': [0.3], 'sue': [1.5],
        'announce_date': [d.iloc[10].date()], 'announce_ts': [d.iloc[10] + pd.Timedelta(hours=15)],
    })
    out = F.attach_event_features(p, sur)
    assert np.isnan(out.loc[10, 'ev_sue'])                   # 公布當天盤中還不知道
    assert out.loc[11, 'ev_sue'] == 1.5 and out.loc[11, 'ev_days_since_rev'] == 0
    assert out.loc[11, 'ev_in_window'] == 0 and out.loc[12, 'ev_in_window'] == 1
    assert out.loc[31, 'ev_in_window'] == 1 and out.loc[32, 'ev_in_window'] == 0   # 第 20 日仍在窗口、第 21 日出窗
    # AR₀ 是 t=0 當天的超額報酬（單檔面板：等權基準就是自己 → 0）
    assert out.loc[11, 'ev_rev_ar0'] == pytest.approx(0.0)
    assert out.loc[11, 'ev_yoy'] == 0.3


def test_surprises_matches_event_study_definition():
    months = pd.date_range('2023-01-01', periods=40, freq='MS')
    rev = pd.DataFrame({'stock_id': '2330', 'revenue_month': months,
                        'revenue': np.exp(np.linspace(0, 1, 40)) * 1e6,
                        'announce_date': months, 'announce_ts': pd.NaT})
    s = F.surprises(rev, min_history=12)
    assert s['yoy'].notna().sum() == 28                       # 前 12 個月沒有 YoY
    assert s['sue'].notna().sum() > 0
    assert s['sue'].abs().max() < 10
