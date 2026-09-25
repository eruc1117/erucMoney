"""
美股特徵面板（Iteration 32）
────────────────────────────
`panel.py` 的宇宙是「台股 × 交易日」，美股只是掛在上面的外生欄位。
要預測**美股本身**，宇宙就得換成「美股標的 × 美股交易日」——這是另一張面板，
所以獨立成一個模組，而不是硬塞進 `panel.py`（那樣每個台股模型都得多背一組
不會用到的欄位，而且 `align()` 的日期下限語意會互相打架）。

## 時序：預測的是「美股 D 日開盤之後」的事，所有特徵必須在 D 日 09:30 ET 之前存在

台北時間比紐約（EDT）快 12 小時，於是同一個日曆日 D：

    台股 D 日盤     09:00~13:30 TWT  ＝  D−1 21:00 ~ D 01:30 ET   ← 在美股 D 開盤前
    韓／日 D 日盤   ~14:30 TWT       ＝  ~D 02:30 ET              ← 同上
    台指期 D 日盤   08:45~13:45 TWT  ＝  D 01:45 ET 收            ← 同上
    美股 D 日盤     09:30~16:00 ET                                ← 要預測的對象

所以**台股 D 日的整段日盤，是美股 D 日開盤前的已知資訊**。這正好是跳空模型
（Iteration 16）的鏡像：那邊是美股 D−1 → 台股 D，這邊是台股 D → 美股 D。

**但台指期夜盤絕對不能用。** `futures_daily` 標記為 trade_date D+1 的 after_market
那一列，時間是 D 15:00 TWT ~ D+1 05:00 TWT ＝ D 03:00 ~ D 17:00 ET——
它涵蓋整段美股 D 日盤，用了就是把答案當特徵。本模組只取 `position`（日盤）。

## 自身特徵一律 shift(1)

同一列（ticker, D）上，`own_*` / `us_*` 全部是 D−1 收盤為止的資訊，
`tw_*` / `asia_*` 是 D 日（美股開盤前）的資訊，`y_*` 是 D 日的結果。
shift 統一在特徵算完之後做一次，不在每個特徵各自處理——後者漏一個就是洩漏，
而洩漏的症狀是「模型好得不像話」，不會報錯。

## 區塊

| 區塊 | 來源 | 起始 | 備註 |
|------|------|------|------|
| own | us_daily_prices | 1990 | 個股自身價量（D−1 為止） |
| usmkt | us_daily_prices | 1990 | 美股大盤／半導體聚合（D−1 為止） |
| cs | 同日 12 檔橫斷面 | 1990 | 相對強弱與排名 |
| tw | stock_daily_prices | 1992 | 台股 D 日盤（美股開盤前已收） |
| asia | index_daily_prices | 2015 | 韓日 D 日收盤（美股開盤前已收） |
| twfut | futures_daily position | 2018 | 台指期 D 日盤，**不含夜盤** |
"""

import logging
import os
import sys

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── 標的：以 Crawler/backfill_us.py 的清單為唯一來源（Iteration 34 起 23 檔）──
# 兩份清單曾各自維護，改清單時漏一邊就是「排程有抓、面板沒用」這種靜默錯誤。
_CRAWLER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Crawler')
if _CRAWLER_DIR not in sys.path:
    sys.path.insert(0, _CRAWLER_DIR)
from backfill_us import TICKERS as _TICKER_ROWS      # noqa: E402
TICKERS = [t for t, _, _ in _TICKER_ROWS]

OWN_FEATURES = [
    'own_ret1', 'own_ret5', 'own_ret20',
    'own_vol5', 'own_vol20',
    'own_gap_prev', 'own_intraday_prev',
    'own_range20', 'own_volratio', 'own_dist_hi20', 'own_dist_lo20',
]

USMKT_FEATURES = [
    'usm_spy_ret1', 'usm_spy_ret5', 'usm_spy_vol20',
    'usm_qqq_ret1', 'usm_soxx_ret1', 'usm_soxx_vol20',
    'usm_risk_on', 'usm_breadth', 'usm_semi_ret1',
]

CS_FEATURES = [
    'cs_ret1_rank', 'cs_rel_ret1', 'cs_rel_ret5', 'cs_vol_rank',
]

TW_FEATURES = [
    'tw_mkt_ret', 'tw_mkt_gap', 'tw_mkt_intraday', 'tw_breadth',
    'tw_2330_ret', 'tw_2330_gap', 'tw_2330_intraday',
    'tw_stale_days',
]

ASIA_FEATURES = ['asia_kr_ret', 'asia_jp_ret', 'asia_mean_ret', 'asia_kr_vol10']

TWFUT_FEATURES = ['twf_day_ret', 'twf_day_intraday', 'twf_day_volratio']

BLOCKS = {
    'own':   {'columns': OWN_FEATURES,   'since': 1990, 'since_date': None,
              'note': '個股自身價量（D−1 收盤為止）'},
    'usmkt': {'columns': USMKT_FEATURES, 'since': 1990, 'since_date': None,
              'note': '美股大盤與半導體聚合（D−1 收盤為止）'},
    'cs':    {'columns': CS_FEATURES,    'since': 1990, 'since_date': None,
              'note': '同日 12 檔之間的相對強弱'},
    'tw':    {'columns': TW_FEATURES,    'since': 1992, 'since_date': None,
              'note': '台股當日日盤（美股開盤前 8 小時已收盤）'},
    'asia':  {'columns': ASIA_FEATURES,  'since': 2015, 'since_date': '2015-01-05',
              'note': '韓日當日收盤'},
    'twfut': {'columns': TWFUT_FEATURES, 'since': 2018, 'since_date': '2018-01-02',
              'note': '台指期日盤（夜盤涵蓋美股盤中，一律不用）'},
}

DEFAULT_BLOCKS = ('own', 'usmkt', 'cs', 'tw')

LOAD_US_SQL = """
    SELECT ticker, trade_date, open_price, high_price, low_price,
           close_price, adj_close, volume
      FROM us_daily_prices
     WHERE close_price > 0 AND adj_close > 0
     ORDER BY ticker, trade_date
"""

LOAD_TW_SQL = """
    SELECT p.stock_id, p.trade_date, p.open_price, p.close_price, p.adj_close
      FROM stock_daily_prices p
      JOIN stock_info i ON i.stock_id = p.stock_id AND i.is_tracking
     WHERE p.close_price > 0 AND p.adj_close > 0
     ORDER BY p.trade_date, p.stock_id
"""

LOAD_TWFUT_SQL = """
    SELECT trade_date, open_price, close_price, volume
      FROM futures_daily
     WHERE futures_id = 'TX' AND session = 'position' AND close_price > 0
     ORDER BY trade_date
"""


# ── 美股自身 ────────────────────────────────────────────────────────────────
def _own_features(d: pd.DataFrame, forward: bool = False) -> pd.DataFrame:
    """
    單一標的的價量特徵與目標。

    還原係數 f = adj_close ÷ close_price 套在開高低上——與 `resolve_predictions`
    及台股各模型同一口徑。不套的話，分割日（NVDA 分割過多次）的開盤價
    相對前一日還原收盤會出現數倍的假跳空。
    """
    d = d.sort_values('trade_date').reset_index(drop=True)
    f = d['adj_close'] / d['close_price']
    adj_open = d['open_price'] * f
    adj_high = d['high_price'] * f
    adj_low = d['low_price'] * f
    c = d['adj_close']
    prev_c = c.shift(1)

    out = pd.DataFrame({'ticker': d['ticker'], 'trade_date': d['trade_date'],
                        'close': d['close_price'], 'adj_close': c,
                        'open': d['open_price'], 'volume': d['volume']})

    ret1 = c.pct_change()
    # ── 目標（D 日的結果，不做 shift）────────────────────────────────────
    out['y_gap'] = adj_open / prev_c - 1            # 開盤跳空：D 開 ÷ D−1 收
    out['y_intraday'] = c / adj_open - 1            # 盤中：D 收 ÷ D 開（可交易的一段）
    out['y_ret'] = ret1                             # 全日：D 收 ÷ D−1 收

    # ── 特徵（先照原序算，最後統一 shift(1)）──────────────────────────────
    feat = pd.DataFrame(index=d.index)
    feat['own_ret1'] = ret1
    feat['own_ret5'] = c.pct_change(5)
    feat['own_ret20'] = c.pct_change(20)
    feat['own_vol5'] = ret1.rolling(5, min_periods=4).std()
    feat['own_vol20'] = ret1.rolling(20, min_periods=12).std()
    feat['own_gap_prev'] = adj_open / prev_c - 1
    feat['own_intraday_prev'] = c / adj_open - 1
    feat['own_range20'] = ((adj_high - adj_low) / c).rolling(20, min_periods=12).mean()
    v20 = d['volume'].rolling(20, min_periods=10).mean()
    feat['own_volratio'] = d['volume'] / v20.replace(0, np.nan)
    feat['own_dist_hi20'] = c / adj_high.rolling(20, min_periods=12).max() - 1
    feat['own_dist_lo20'] = c / adj_low.rolling(20, min_periods=12).min() - 1

    out[OWN_FEATURES] = feat[OWN_FEATURES].shift(1)

    # 波動率目標與其 EWMA 基準（見 train_us.py 的說明）
    out['fwd_vol5'] = ret1.shift(-5).rolling(5).std()
    out['fwd_vol20'] = ret1.shift(-20).rolling(20).std()
    out['ewma_vol'] = _ewma_vol(ret1).shift(1)
    # 未還原的參考價：台帳的 ref_value 用它，與前端顯示的報價一致
    out['prev_close'] = d['close_price'].shift(1)
    out['is_forward'] = False
    if forward:
        out = pd.concat([out, _forward_row(d, feat, ret1, out)], ignore_index=True)
    return out


def _forward_row(d, feat, ret1, out) -> pd.DataFrame:
    """
    「還沒開盤的那一場」——推論時要預測的就是這一列。

    面板裡的每一列都對應一個**已經發生**的美股交易日，最後一列的 own_* 是
    D−1 的資訊、目標是 D 的跳空。但線上要問的是「今晚會怎麼開」，
    那一天在面板裡根本沒有列。硬拿最後一列來預測，等於用 D−1 的美股與
    D 的台股去預測**已經開過**的 D——那是回顧，不是預測。

    所以補一列：日期取下一個工作日，own_* 直接取**未 shift** 的最後一筆
    （＝D 收盤為止的資訊），tw/asia 則由 `_attach_asof` 自動接上最新一場
    亞洲盤。目標欄留 NaN，訓練端的 `align` 會自然把它排除。
    """
    last = d.iloc[-1]
    # 下一場的日期至少是「今天」：美股連假（例如勞動節）時，單純 +1 個工作日
    # 會落在休市日，而 `_attach_asof` 是以這個日期去找最近一場亞洲盤——
    # 日期落後一天，接到的就是昨天的台股，今天盤後的資訊等於白抓。
    nxt = max(pd.Timestamp(last['trade_date']) + pd.tseries.offsets.BDay(1),
              pd.Timestamp('today').normalize())
    row = {c: np.nan for c in out.columns}
    row.update({
        'ticker': last['ticker'], 'trade_date': nxt,
        'close': last['close_price'], 'adj_close': last['adj_close'],
        'open': last['open_price'], 'volume': last['volume'],
        'prev_close': last['close_price'],
        'ewma_vol': _ewma_vol(ret1).iloc[-1],
        'is_forward': True,
    })
    for c in OWN_FEATURES:
        row[c] = feat[c].iloc[-1]
    return pd.DataFrame([row])


def _ewma_vol(ret: pd.Series, lam: float = 0.94) -> pd.Series:
    """RiskMetrics EWMA 波動率——波動率模型要打敗的天真基準。"""
    var = (ret ** 2).ewm(alpha=1 - lam, min_periods=20).mean()
    return np.sqrt(var)


def _cross_section(panel: pd.DataFrame) -> pd.DataFrame:
    """同一美股交易日、各標的之間的相對位置。全部由已 shift 的欄位算出。"""
    g = panel.groupby('trade_date')
    panel['cs_ret1_rank'] = g['own_ret1'].rank(pct=True)
    panel['cs_vol_rank'] = g['own_vol20'].rank(pct=True)
    spy = panel[panel['ticker'] == 'SPY'][['trade_date', 'own_ret1', 'own_ret5']]
    spy = spy.rename(columns={'own_ret1': '_spy1', 'own_ret5': '_spy5'})
    panel = panel.merge(spy, on='trade_date', how='left')
    panel['cs_rel_ret1'] = panel['own_ret1'] - panel['_spy1']
    panel['cs_rel_ret5'] = panel['own_ret5'] - panel['_spy5']
    return panel.drop(columns=['_spy1', '_spy5'])


def _us_market(own: pd.DataFrame) -> pd.DataFrame:
    """美股大盤聚合，一列一個美股交易日；欄位取自已 shift 的個股特徵，故同樣是 D−1 為止。"""
    piv = own.pivot_table(index='trade_date', columns='ticker',
                          values='own_ret1', aggfunc='last')
    out = pd.DataFrame(index=piv.index)
    for tk, col in (('SPY', 'usm_spy_ret1'), ('QQQ', 'usm_qqq_ret1'),
                    ('SOXX', 'usm_soxx_ret1')):
        out[col] = piv[tk] if tk in piv.columns else np.nan
    for tk, col in (('SPY', 'usm_spy_ret5'), ):
        src = own[own['ticker'] == tk].set_index('trade_date')['own_ret5']
        out[col] = src.reindex(out.index)
    for tk, col in (('SPY', 'usm_spy_vol20'), ('SOXX', 'usm_soxx_vol20')):
        src = own[own['ticker'] == tk].set_index('trade_date')['own_vol20']
        out[col] = src.reindex(out.index)
    out['usm_risk_on'] = out['usm_qqq_ret1'] - out['usm_spy_ret1']
    out['usm_breadth'] = (piv > 0).mean(axis=1)
    semis = [t for t in ('SOXX', 'NVDA', 'AMD', 'MU', 'INTC', 'AVGO') if t in piv.columns]
    out['usm_semi_ret1'] = piv[semis].mean(axis=1) if semis else np.nan
    return out.reset_index()


# ── 台股日盤 ────────────────────────────────────────────────────────────────
def _tw_daily() -> pd.DataFrame:
    """
    台股當日日盤的聚合特徵，一列一個台股交易日。

    `tw_2330_intraday`（台積電當日 收 ÷ 開）是本模組真正想問的東西：
    開盤跳空那一段是美股 D−1 的回聲，**盤中那一段才是台灣時區新加進去的資訊**。
    若美股 D 日的跳空真的能被台股預測，多半就是靠這一欄。
    """
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_TW_SQL, conn)
    if raw.empty:
        logger.warning('[us_panel] 無台股行情，tw 區塊不可用')
        return pd.DataFrame()

    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    raw = raw.sort_values(['stock_id', 'trade_date'])
    f = raw['adj_close'] / raw['close_price']
    raw['adj_open'] = raw['open_price'] * f
    g = raw.groupby('stock_id')
    raw['prev_adj'] = g['adj_close'].shift(1)
    raw['ret'] = raw['adj_close'] / raw['prev_adj'] - 1
    raw['gap'] = raw['adj_open'] / raw['prev_adj'] - 1
    raw['intraday'] = raw['adj_close'] / raw['adj_open'] - 1

    agg = raw.groupby('trade_date').agg(
        tw_mkt_ret=('ret', 'mean'),
        tw_mkt_gap=('gap', 'mean'),
        tw_mkt_intraday=('intraday', 'mean'),
        tw_breadth=('ret', lambda s: float((s > 0).mean())),
    ).reset_index()

    t = raw[raw['stock_id'] == '2330'][['trade_date', 'ret', 'gap', 'intraday']]
    t = t.rename(columns={'ret': 'tw_2330_ret', 'gap': 'tw_2330_gap',
                          'intraday': 'tw_2330_intraday'})
    out = agg.merge(t, on='trade_date', how='left')
    return out.replace([np.inf, -np.inf], np.nan)


def _asia_daily() -> pd.DataFrame:
    """
    韓日**當日收盤**報酬。對台股模型這是洩漏（台股 13:30 就收了），
    對美股模型則完全合法——韓日 14:30 TWT 收盤 ＝ 02:30 ET，美股還沒開。
    """
    from db.connection import get_conn
    from intl_features import LOAD_SQL, SYMBOLS
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)
    if raw.empty:
        return pd.DataFrame()
    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    out = None
    for sym, tag in SYMBOLS.items():
        d = raw[raw['symbol'] == sym].sort_values('trade_date')
        if d.empty:
            continue
        f = pd.DataFrame({'trade_date': d['trade_date'].values})
        r = d['close_price'].pct_change()
        f[f'asia_{tag}_ret'] = r.values
        if tag == 'kr':
            f['asia_kr_vol10'] = r.rolling(10, min_periods=5).std().values
        out = f if out is None else out.merge(f, on='trade_date', how='outer')
    if out is None:
        return pd.DataFrame()
    out = out.sort_values('trade_date').reset_index(drop=True)
    cols = [c for c in ('asia_kr_ret', 'asia_jp_ret') if c in out.columns]
    # 指數偶有異常報價，10% 以上的單日變動幾乎都是換算錯誤（與 intl_features 同口徑）
    for c in cols:
        out.loc[out[c].abs() > 0.10, c] = np.nan
    out['asia_mean_ret'] = out[cols].mean(axis=1) if cols else np.nan
    return out


def _twfut_daily() -> pd.DataFrame:
    """台指期**日盤**。夜盤（after_market）涵蓋整段美股盤中，這裡碰都不碰。"""
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_TWFUT_SQL, conn)
    if raw.empty:
        return pd.DataFrame()
    d = raw.copy()
    d['trade_date'] = pd.to_datetime(d['trade_date'])
    d = d.sort_values('trade_date')
    out = pd.DataFrame({'trade_date': d['trade_date'].values})
    out['twf_day_ret'] = (d['close_price'] / d['close_price'].shift(1) - 1).values
    out['twf_day_intraday'] = (d['close_price'] / d['open_price'] - 1).values
    v20 = d['volume'].rolling(20, min_periods=10).mean()
    out['twf_day_volratio'] = (d['volume'] / v20.replace(0, np.nan)).values
    return out.replace([np.inf, -np.inf], np.nan)


# ── 對外介面 ────────────────────────────────────────────────────────────────
def build(blocks=DEFAULT_BLOCKS, tickers=None, forward: bool = False) -> pd.DataFrame:
    """
    建立美股面板。回傳欄位：ticker / trade_date / close / adj_close / open /
    volume / prev_close / y_gap / y_intraday / y_ret / fwd_vol5 / ewma_vol
    ＋ 指定區塊的特徵欄。
    """
    import os
    import sys
    crawler = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Crawler')
    if crawler not in sys.path:
        sys.path.insert(0, crawler)

    from db.connection import get_conn

    blocks = list(blocks)
    unknown = [b for b in blocks if b not in BLOCKS]
    if unknown:
        raise ValueError(f'未知的特徵區塊：{unknown}（可用：{sorted(BLOCKS)}）')

    with get_conn() as conn:
        raw = pd.read_sql(LOAD_US_SQL, conn)
    if raw.empty:
        logger.warning('[us_panel] us_daily_prices 是空的')
        return pd.DataFrame()

    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    for c in ('open_price', 'high_price', 'low_price', 'close_price', 'adj_close', 'volume'):
        raw[c] = pd.to_numeric(raw[c], errors='coerce')
    want = [t for t in (tickers or TICKERS)]
    raw = raw[raw['ticker'].isin(want)]

    panel = pd.concat([_own_features(d, forward=forward)
                       for _, d in raw.groupby('ticker')], ignore_index=True)
    panel = panel.sort_values(['trade_date', 'ticker']).reset_index(drop=True)

    if forward:
        # 落後的標的（前一場沒抓到）其 forward 列會落在另一個日期上，
        # 橫斷面就會拿一兩檔去算全體的排名。寧可少幾檔，不要算錯。
        fwd = panel[panel['is_forward']]
        if not fwd.empty:
            main_date = fwd['trade_date'].max()
            stale = fwd[fwd['trade_date'] != main_date]
            if not stale.empty:
                logger.warning('[us_panel] %d 檔行情落後，未納入本次預測：%s',
                               len(stale), '、'.join(sorted(stale['ticker'])))
                panel = panel.drop(stale.index)

    # 資料錯誤過濾：單日 ±50% 以上的跳空在這些標的上一律是資料問題，不是行情
    for c in ('y_gap', 'y_intraday', 'y_ret'):
        panel.loc[panel[c].abs() > 0.5, c] = np.nan

    if 'usmkt' in blocks:
        panel = panel.merge(_us_market(panel), on='trade_date', how='left')
    if 'cs' in blocks:
        panel = _cross_section(panel)
    if 'tw' in blocks:
        panel = _attach_asof(panel, _tw_daily(), 'tw_stale_days')
    if 'asia' in blocks:
        panel = _attach_asof(panel, _asia_daily())
    if 'twfut' in blocks:
        panel = _attach_asof(panel, _twfut_daily())

    n_ok = int(panel[[c for c in columns_for(blocks) if c in panel.columns]]
               .notna().all(axis=1).sum())
    logger.info('[us_panel] %s → %d 列 / %d 檔（%s ~ %s），特徵完整 %d 列',
                '+'.join(blocks), len(panel), panel['ticker'].nunique(),
                str(panel['trade_date'].min())[:10], str(panel['trade_date'].max())[:10],
                n_ok)
    return panel


def _attach_asof(panel: pd.DataFrame, side: pd.DataFrame, stale_col: str = None):
    """
    以 as-of（backward、**允許同日**）併入亞洲時區的當日資料。

    允許同日正是重點：台股／韓日／台指期日盤在美股同一日開盤前就收了。
    休市日不同用 as-of 而非 inner-join，否則美股獨有的交易日會整批掉樣本；
    `stale_col` 記下用的是幾天前的台股資料（美股連假後會拉長）。
    """
    if side is None or side.empty:
        return panel
    p = panel.sort_values('trade_date')
    s = side.sort_values('trade_date').rename(columns={'trade_date': '_src_date'})
    merged = pd.merge_asof(p, s, left_on='trade_date', right_on='_src_date',
                           direction='backward', allow_exact_matches=True)
    if stale_col:
        merged[stale_col] = (merged['trade_date'] - merged['_src_date']).dt.days
    return merged.drop(columns=['_src_date']).reset_index(drop=True)


def columns_for(blocks) -> list:
    out = []
    for b in blocks:
        for c in BLOCKS[b]['columns']:
            if c not in out:
                out.append(c)
    return out


def align(panel: pd.DataFrame, blocks, extra_required=()) -> pd.DataFrame:
    """指定區塊都完整的列（含日期下限）——與 `panel.align` 同語意。"""
    p = panel
    floors = [BLOCKS[b].get('since_date') for b in blocks if BLOCKS[b].get('since_date')]
    if floors:
        floor = max(pd.Timestamp(f) for f in floors)
        p = p[p['trade_date'] >= floor]
    need = [c for c in columns_for(blocks) if c in p.columns]
    need += [c for c in extra_required if c in p.columns]
    if not need:
        return p.reset_index(drop=True)
    return p[p[need].notna().all(axis=1)].reset_index(drop=True)


def describe() -> list:
    return [{'name': k, 'n_features': len(v['columns']), 'since': v['since'],
             'note': v['note']} for k, v in BLOCKS.items()]
