"""
統一特徵面板（Iteration 31）
────────────────────────────
在此之前，每個 train_*.py 各自寫一份 load_data()，各自決定要不要接夜盤、
要不要接美股。結果是 Iteration 30 要把夜盤加進振幅與波動率時，得分別改兩支
檔案、再分別驗證推論端有沒有跟上——而 `risk_model` 就曾經因為欄位對不上
靜默退回 EWMA，線上完全看不出來。

本模組把「有哪些資料」與「哪個模型要用哪些」分開：

    panel.build(blocks=['price','chip','cs','market','night'])

回傳的面板保證每一塊的欄位定義與推論端完全相同——因為推論端呼叫的是同一個函式。

## 區塊清單

| 區塊 | 來源 | 特徵數 | 起始 | 備註 |
|------|------|-------|------|------|
| price | stock_daily_prices | 24 | 1992 | 一律以 adj_close 計算 |
| chip | stock_chip_analysis | 17 | 2012 | 三大法人 |
| cs | 同日橫斷面 | 7 | 2012 | 需 price+chip |
| market | 同日全體聚合 | 5 | 2012 | 需 price+chip |
| us | us_daily_prices | 17 | 1990 | 12 檔美股／ETF |
| night | futures_daily 夜盤 | 8 | 2018 | 台指期盤後 |
| futures | futures_daily 未平倉 | 9 | 2018 | OI + 大小台結構 |
| intl | index_daily_prices | 7 | 2015 | KOSPI／Nikkei |
| holding | stock_foreign_holding | 7 | 2012 | 外資真實持股（存量），Iteration 36 |

**加入區塊會砍樣本。** night/futures 只到 2018，intl 只到 2015；一旦納入，
共同可用區間就被最晚的那個決定。這是實質代價，不是形式問題——
Iteration 30 的 M3 消融就因為納入夜盤，樣本從 2012 起縮到 2018 起，
而 M3 的買進準確率也從 56.87% 掉到 51.53%。

所以 `build()` 一律回報納入前後的樣本數，讓呼叫端看得到自己付了多少代價。
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── 區塊定義 ────────────────────────────────────────────────────────────────
# 每個區塊：欄位清單 + 掛載函式 + 資料起始年（供呼叫端預估樣本代價）
BLOCKS = {}


def _register(name, columns, attach_fn, since, note, since_date=None):
    BLOCKS[name] = {'name': name, 'columns': list(columns),
                    'attach': attach_fn, 'since': since, 'note': note,
                    'since_date': since_date}


def _feature_cols():
    from features import PRICE_FEATURES, CHIP_FEATURES, CS_FEATURES, MARKET_FEATURES
    return PRICE_FEATURES, CHIP_FEATURES, CS_FEATURES, MARKET_FEATURES


def build(blocks=('price', 'chip', 'cs', 'market'), stock_ids=None,
          min_history: int = 65) -> pd.DataFrame:
    """
    建立統一面板。

    price/chip/cs/market 由 `features.build_panel` 一次算出（它們互相依賴，
    橫斷面排名需要當日所有股票都已算好個股特徵），其餘區塊逐一 attach。

    回傳的 DataFrame 一定含 stock_id / trade_date / open / high / low /
    close / adj_close / volume，加上被要求區塊的所有特徵欄。
    """
    import sys, os
    crawler = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Crawler')
    if crawler not in sys.path:
        sys.path.insert(0, crawler)

    from features import build_panel, LOAD_SQL
    from db.connection import get_conn

    blocks = list(blocks)
    unknown = [b for b in blocks if b not in BLOCKS]
    if unknown:
        raise ValueError(f'未知的特徵區塊：{unknown}（可用：{sorted(BLOCKS)}）')

    with get_conn() as conn:
        raw = pd.read_sql(LOAD_SQL, conn)
    if stock_ids:
        raw = raw[raw['stock_id'].isin([str(s).strip() for s in stock_ids])]

    panel = build_panel(raw)
    if panel.empty:
        return panel
    panel['trade_date'] = pd.to_datetime(panel['trade_date'])
    n0 = len(panel)

    # 個股層級的區塊已由 build_panel 算完；其餘是「每個交易日一列」的外生資料
    for b in blocks:
        spec = BLOCKS[b]
        if spec['attach'] is None:
            continue
        before = len(panel)
        panel = spec['attach'](panel)
        logger.info('[panel] 掛上 %s（%d 欄，%s 起）', b, len(spec['columns']), spec['since'])
        if len(panel) != before:
            logger.warning('[panel] %s 掛載後列數由 %d 變成 %d——外生表有重複日期',
                           b, before, len(panel))

    cols = columns_for(blocks)
    have = [c for c in cols if c in panel.columns]
    missing = [c for c in cols if c not in panel.columns]
    if missing:
        logger.warning('[panel] 缺少 %d 個特徵欄（該區塊資料表可能是空的）：%s',
                       len(missing), missing[:6])

    usable = int(panel[have].notna().all(axis=1).sum()) if have else 0
    logger.info('[panel] 區塊 %s → %d 欄；%d 列中 %d 列特徵完整（%.0f%%）',
                '+'.join(blocks), len(have), n0, usable, 100 * usable / max(n0, 1))
    return panel


def columns_for(blocks) -> list:
    """指定區塊涵蓋的所有特徵欄名（順序穩定，供模型 bundle 存檔比對）。"""
    out = []
    for b in blocks:
        for c in BLOCKS[b]['columns']:
            if c not in out:
                out.append(c)
    return out


def describe() -> list:
    """區塊清單（供 API／目錄頁呈現）。"""
    return [{'name': s['name'], 'n_features': len(s['columns']),
             'since': s['since'], 'note': s['note']}
            for s in BLOCKS.values()]


def align(panel: pd.DataFrame, blocks, extra_required=()) -> pd.DataFrame:
    """
    取所有指定區塊都完整的列。

    **消融實驗一定要用這個。** 各變體若各自 dropna，比的就是資料量而不是特徵；
    Iteration 28 的 LSTM 外生實驗就是這樣把四個變體跑在不同樣本上，
    症狀是「天真基準線跟著變動」。

    除了 dropna，還會套用日期下限——因為 **dropna 抓不到被捏造的值**：
    `features.build_stock_features` 對三大法人欄位做了 `fillna(0.0)`，
    所以 2012-05（籌碼資料起點）以前的每一列都有「買賣超為零」的籌碼特徵，
    看起來完整、實際上是憑空的。首次跑本模組的評估就吃到這個坑：
    樣本從 1992 起算 165,664 列，其中前 20 年的籌碼特徵全是假的。
    """
    p = panel
    floors = [BLOCKS[b].get('since_date') for b in blocks if BLOCKS[b].get('since_date')]
    if floors:
        floor = max(pd.Timestamp(f) for f in floors)
        p = p[pd.to_datetime(p['trade_date']) >= floor]

    need = [c for c in columns_for(blocks) if c in p.columns]
    need += [c for c in extra_required if c in p.columns]
    if not need:
        return p.reset_index(drop=True)
    return p[p[need].notna().all(axis=1)].reset_index(drop=True)


# ── 外生區塊的掛載函式 ──────────────────────────────────────────────────────
def _attach_us(panel):
    from us_features import load_and_attach
    return load_and_attach(panel)


def _attach_night(panel):
    from night_features import attach as f
    return f(panel, 'TX')


def _attach_futures(panel):
    from futures_extra import attach as f
    return f(panel)


def _attach_intl(panel):
    from intl_features import attach as f
    return f(panel)


def _attach_holding(panel):
    from holding_features import attach as f
    return f(panel)


def _init():
    import sys, os
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (here, os.path.join(here, '..', 'Crawler')):
        if p not in sys.path:
            sys.path.insert(0, p)

    P, C, CS, M = _feature_cols()
    _register('price', P, None, 1992, '價量技術面，一律以 adj_close 計算')
    # since_date 只給「有捏造值風險」的區塊。籌碼欄位在 features.py 被 fillna(0)，
    # 2012-05-02（stock_chip_analysis 起點）之前全是假的零，dropna 抓不到。
    _register('chip', C, None, 2012, '三大法人買賣超，以 20 日均量標準化', '2012-05-02')
    _register('cs', CS, None, 2012, '同日橫斷面百分位排名', '2012-05-02')
    _register('market', M, None, 2012, '當日全體聚合：大盤報酬、漲家數、市場波動', '2012-05-02')

    try:
        from us_features import US_FEATURES
        _register('us', US_FEATURES, _attach_us, 1990, '12 檔美股／ETF 隔夜變動')
    except Exception as e:                                  # pragma: no cover
        logger.warning('[panel] us 區塊不可用：%s', e)
    try:
        from night_features import NIGHT_FEATURES
        _register('night', NIGHT_FEATURES, _attach_night, 2018, '台指期夜盤 15:00~05:00')
    except Exception as e:                                  # pragma: no cover
        logger.warning('[panel] night 區塊不可用：%s', e)
    try:
        from futures_extra import FUTURES_EXTRA_FEATURES
        _register('futures', FUTURES_EXTRA_FEATURES, _attach_futures, 2018,
                  '未平倉量與大小台結構（落後一日）')
    except Exception as e:                                  # pragma: no cover
        logger.warning('[panel] futures 區塊不可用：%s', e)
    try:
        from intl_features import INTL_FEATURES
        _register('intl', INTL_FEATURES, _attach_intl, 2015, 'KOSPI／Nikkei 開盤（早台股一小時）')
    except Exception as e:                                  # pragma: no cover
        logger.warning('[panel] intl 區塊不可用：%s', e)
    try:
        from holding_features import HOLDING_FEATURES
        _register('holding', HOLDING_FEATURES, _attach_holding, 2012,
                  '外資真實持股：水位、多天期變動、上限距離（存量，非買賣超）', '2012-05-02')
    except Exception as e:                                  # pragma: no cover
        logger.warning('[panel] holding 區塊不可用：%s', e)


_init()
