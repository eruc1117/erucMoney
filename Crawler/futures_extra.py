"""
期貨未平倉與大小台結構特徵（Iteration 31）
─────────────────────────────────────────
`futures_daily` 裡有兩塊到目前為止**完全沒被任何模型用過**的資料：

  open_interest   未平倉量——期貨版的籌碼面。價漲量增而 OI 增 = 新多單進場；
                  價漲而 OI 減 = 空單回補。同樣的漲幅，兩種含意完全不同。
  MTX（小台）     小台單口只有大台的 1/4，是散戶的主要工具。
                  **小台/大台成交量比是散戶參與度的代理**——散戶佔比極端時
                  往往對應情緒過熱或過冷。

## 時序：OI 只有日盤有，所以一律落後一日

實測 `after_market` 的 open_interest **2,095 筆全部是 0**——夜盤不單獨結算未平倉，
OI 是日盤收盤後才公布的日結數字。因此：

    D 日的 OI 在 D 日 13:30（台股收盤）之前拿不到

本模組所有特徵都以 **D−1（含）以前**的 OI 計算後掛在 D 日上。這對「預測 D 日
開盤跳空」是必要的；對「D 日收盤後決策、預測 D+1 之後」其實可以放寬一天，
但兩者共用同一份特徵表，取嚴格的那個標準才不會有一個模型偷跑。
成交量沒有這個問題（盤中即時），但為了同一列的時序一致，一併落後一日。

## 為什麼期望值不低

夜盤吃掉了美股與韓日（Iteration 28/29），因為那三者講的是同一件事：隔夜的價格。
OI 講的是**部位結構**，不是價格——它是目前唯一一個與夜盤不同構的期貨面資訊。
這是它值得單獨測的理由，不是它一定會有用。
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FUTURES_EXTRA_FEATURES = [
    'oi_chg_1d',        # 未平倉量日變動率：新倉進場 vs 平倉離場
    'oi_chg_contract',  # 契約內累計未平倉變動：本月部位是持續累積還是在退場
    'oi_ratio_20d',     # 未平倉 ÷ 契約內 20 日均值：目前部位規模相對常態
    'oi_price_align',   # sign(價格變動) × sign(OI 變動)：+1 新倉推動、−1 回補推動
    'oi_vol_ratio',     # 未平倉 ÷ 日盤成交量：換手速度（低=長線持有為主）
    'oi_contract_age',  # 進入本契約第幾個交易日：OI 有明確的月週期，讓模型自己學
    'mtx_share',        # 小台量 ÷（小台量×0.25 + 大台量）：散戶參與度代理
    'mtx_share_z',      # 上述比例的 60 日 z 分數：極端才有意義，絕對值沒有
    'mtx_oi_share',     # 小台未平倉佔比：散戶留倉比重
]

# `futures_daily` 一個交易日只留近月契約一列。近月每月第三個週三結算換月，
# 換月當下 OI 從舊契約的高點掉到新契約的近乎零——跨契約的變動率毫無意義
# （實測有 +557% 的假跳動）。故所有變動與滾動統計一律**在契約內**計算。
LOAD_SQL = """
    SELECT futures_id, trade_date, contract_date,
           close_price, volume, open_interest
      FROM futures_daily
     WHERE session = 'position' AND close_price > 0
     ORDER BY trade_date
"""

# 小台契約規模是大台的 1/4，比較「參與度」時要換算成同一個口徑
MTX_MULTIPLIER = 0.25


def load_futures_extra() -> pd.DataFrame:
    """回傳以 trade_date 為索引的期貨結構特徵表（已落後一日，可直接掛上當日）。"""
    from db.connection import get_conn
    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)
    if raw.empty:
        logger.warning('[futures_extra] 無日盤資料')
        return pd.DataFrame()

    raw['trade_date'] = pd.to_datetime(raw['trade_date'])
    piv = raw.pivot(index='trade_date', columns='futures_id').sort_index()

    def col(field, fid):
        try:
            return piv[(field, fid)].astype(float)
        except KeyError:
            return pd.Series(np.nan, index=piv.index)

    tx_close, tx_vol, tx_oi = col('close_price', 'TX'), col('volume', 'TX'), col('open_interest', 'TX')
    mtx_vol, mtx_oi = col('volume', 'MTX'), col('open_interest', 'MTX')

    # 契約分組：換月那天起算新的一段，變動率不跨段
    contract = col('contract_date', 'TX').astype('object')
    if contract.isna().all():                       # 舊資料沒有 contract_date 時的退路
        contract = pd.Series('_', index=piv.index)
    grp = contract.ne(contract.shift()).cumsum()

    f = pd.DataFrame(index=piv.index)
    f['oi_chg_1d'] = tx_oi.groupby(grp).pct_change()
    # 用「契約內累計」而不是「近 5 日」：後者在每個契約的前 5 天必為 NaN
    # （覆蓋率只有 75%），而樣本對齊要求所有變體共用同一批列，
    # 等於讓一個特徵砍掉全部模型四分之一的資料
    f['oi_chg_contract'] = tx_oi / tx_oi.groupby(grp).transform('first') - 1
    f['oi_ratio_20d'] = tx_oi / tx_oi.groupby(grp).transform(
        lambda s: s.rolling(20, min_periods=3).mean())
    f['oi_price_align'] = (np.sign(tx_close.groupby(grp).pct_change())
                           * np.sign(tx_oi.groupby(grp).diff()))
    f['oi_vol_ratio'] = tx_oi / tx_vol.replace(0, np.nan)
    f['oi_contract_age'] = grp.groupby(grp).cumcount()

    # 換算成大台當量後再算佔比，否則比的是「口數」而不是「金額參與度」
    mtx_eq = mtx_vol * MTX_MULTIPLIER
    f['mtx_share'] = mtx_eq / (mtx_eq + tx_vol).replace(0, np.nan)
    m = f['mtx_share']
    f['mtx_share_z'] = ((m - m.rolling(60, min_periods=30).mean())
                        / (m.rolling(60, min_periods=30).std() + 1e-9))
    mtx_oi_eq = mtx_oi * MTX_MULTIPLIER
    f['mtx_oi_share'] = mtx_oi_eq / (mtx_oi_eq + tx_oi).replace(0, np.nan)

    f = f.replace([np.inf, -np.inf], np.nan)

    # ★ 時序關鍵：整表下移一日。掛在 D 日的每一個值都只用到 D−1（含）以前的資料。
    #   拿掉這一行，模型就會在預測 D 日開盤時看到 D 日 13:45 才公布的未平倉量。
    f = f.shift(1)

    logger.info('[futures_extra] %d 個交易日（%s ~ %s）', len(f),
                str(f.index.min())[:10], str(f.index.max())[:10])
    return f.reset_index()


def attach(panel: pd.DataFrame, date_col: str = 'trade_date') -> pd.DataFrame:
    """併到個股面板（同一交易日曆，直接對日期）。"""
    extra = load_futures_extra()
    if extra.empty:
        return panel
    p = panel.copy()
    p[date_col] = pd.to_datetime(p[date_col])
    return p.merge(extra, left_on=date_col, right_on='trade_date',
                   how='left', suffixes=('', '_fut'))
