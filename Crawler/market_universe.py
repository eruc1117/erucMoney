"""
全市場股票池 market_universe（Iteration 48，「打敗大盤」計畫階段 1）

來源：FinMind TaiwanStockInfo（現行上市櫃清單，含上市日）+ TaiwanStockDelisting（下市櫃清單），各一次呼叫。
收錄規則（build_rows）：
    · 市場 twse / tpex（興櫃不收）
    · 代號 4 碼且不以 0 開頭——00xx 是 ETF，特別股帶英文尾碼（1101B），TDR 6 碼，權證 6 碼，一律排除
    · 產業別是 ETF／ETN／受益證券／存託憑證／指數的排除
    · 下市表裡符合代號規則的股票也收，標 delisted_date；回測股票池沒有下市股就是存活者偏差
同一檔在 TaiwanStockInfo 常有多列（泛用「電子工業」+ 具體產業別），取具體的那一列。
TaiwanStockInfo 的 date 欄**不是上市日**（2026-10 實測 1,749 檔都是同步當天），所以 listing_date 這裡一律留空，
由 market_data.derive_listing_dates() 用第一筆價格日推回（只有資料起點之後才上市的股票填得出來）。

用法：
    python market_universe.py --sync          # 同步（2 次 FinMind 呼叫）
    python market_universe.py --status
"""

import argparse
import logging
import re
from datetime import date
from typing import Optional

import requests

from config import FINMIND
from db.connection import get_conn

logger = logging.getLogger(__name__)

API = 'https://api.finmindtrade.com/api/v4/data'
STOCK_ID_RE = re.compile(r'^[1-9][0-9]{3}$')
MARKETS = {'twse', 'tpex'}
EXCLUDE_INDUSTRY = {'ETF', '上櫃ETF', '上櫃指數股票型基金(ETF)', 'ETN', '上櫃ETN', '指數投資證券(ETN)',
                    'Index', '受益證券', '上櫃受益證券', '存託憑證', '上櫃存託憑證'}
GENERIC_INDUSTRY = {'電子工業', '其他', ''}


class QuotaError(RuntimeError):
    """FinMind 額度用盡或等級不足（HTTP 402／429、status != 200）。"""


def finmind(dataset: str, **params) -> list:
    """FinMind v4 單次呼叫；回 data 列。額度問題丟 QuotaError，呼叫端決定等多久。"""
    p = {'dataset': dataset, **params}
    if FINMIND.get('token'):
        p['token'] = FINMIND['token']
    r = requests.get(API, params=p, timeout=120)
    if r.status_code in (402, 429):
        raise QuotaError(f'HTTP {r.status_code}')
    try:
        j = r.json()
    except ValueError:
        raise QuotaError(f'HTTP {r.status_code} 非 JSON')
    if j.get('status') != 200:
        raise QuotaError(f"status {j.get('status')}: {j.get('msg')}")
    return j.get('data') or []


def _parse_date(raw) -> Optional[date]:
    s = str(raw or '').strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def build_rows(info: list[dict], delisted: list[dict]) -> list[dict]:
    """把兩份 FinMind 清單合成 market_universe 的列（純函式，測試用假資料）。"""
    by_id: dict[str, dict] = {}
    for x in info:
        sid = str(x.get('stock_id') or '').strip()
        market = str(x.get('type') or '').strip().lower()
        industry = str(x.get('industry_category') or '').strip()
        if not STOCK_ID_RE.match(sid) or market not in MARKETS or industry in EXCLUDE_INDUSTRY:
            continue
        cur = by_id.get(sid)
        if cur is None:
            by_id[sid] = {'stock_id': sid, 'stock_name': str(x.get('stock_name') or sid).strip(),
                          'market_type': market, 'industry_type': industry or None,
                          'listing_date': None, 'delisted_date': None}
            continue
        # 同一檔多列：具體產業別優先、上市優先於上櫃（轉上市的股票）
        if (cur['industry_type'] in GENERIC_INDUSTRY or cur['industry_type'] is None) and industry not in GENERIC_INDUSTRY:
            cur['industry_type'] = industry
        if market == 'twse' and cur['market_type'] == 'tpex':
            cur['market_type'] = 'twse'
    for x in delisted:
        sid = str(x.get('stock_id') or '').strip()
        if not STOCK_ID_RE.match(sid):
            continue
        d = _parse_date(x.get('date'))
        if sid in by_id:
            by_id[sid]['delisted_date'] = d
        else:
            by_id[sid] = {'stock_id': sid, 'stock_name': str(x.get('stock_name') or sid).strip(),
                          'market_type': None, 'industry_type': None, 'listing_date': None, 'delisted_date': d}
    return sorted(by_id.values(), key=lambda r: r['stock_id'])


def upsert(rows: list[dict]) -> int:
    if not rows:
        return 0
    from psycopg2.extras import execute_values
    with get_conn() as conn:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO market_universe (stock_id, stock_name, market_type, industry_type, listing_date, delisted_date)
                VALUES %s
                ON CONFLICT (stock_id) DO UPDATE SET
                    stock_name    = COALESCE(EXCLUDED.stock_name, market_universe.stock_name),
                    market_type   = COALESCE(EXCLUDED.market_type, market_universe.market_type),
                    industry_type = COALESCE(EXCLUDED.industry_type, market_universe.industry_type),
                    listing_date  = COALESCE(EXCLUDED.listing_date, market_universe.listing_date),
                    delisted_date = EXCLUDED.delisted_date,
                    updated_at    = CURRENT_TIMESTAMP
            """, [(r['stock_id'], r['stock_name'], r['market_type'], r['industry_type'], r['listing_date'], r['delisted_date'])
                  for r in rows], page_size=500)
        conn.commit()
    return len(rows)


def sync() -> dict:
    """兩次 FinMind 呼叫，寫入 market_universe。回傳統計。"""
    info = finmind('TaiwanStockInfo')
    delisted = finmind('TaiwanStockDelisting')
    rows = build_rows(info, delisted)
    n = upsert(rows)
    out = {'info_rows': len(info), 'delisted_rows': len(delisted), 'written': n,
           'active': sum(1 for r in rows if r['delisted_date'] is None),
           'delisted': sum(1 for r in rows if r['delisted_date'] is not None)}
    logger.info('[universe] FinMind 清單 %d 列、下市 %d 列 → 股票池 %d 檔（在市 %d、下市 %d）',
                out['info_rows'], out['delisted_rows'], n, out['active'], out['delisted'])
    return out


def ids(include_delisted: bool = True, on: Optional[date] = None) -> list[str]:
    """股票池代碼。on 給日期 → 當天在市（上市日 ≤ on < 下市日，不明者視為在市）。"""
    with get_conn() as conn:
        with conn.cursor() as cur:
            if on is not None:
                cur.execute("""SELECT stock_id FROM market_universe
                               WHERE (listing_date IS NULL OR listing_date <= %s)
                                 AND (delisted_date IS NULL OR delisted_date > %s) ORDER BY 1""", (on, on))
            elif include_delisted:
                cur.execute("SELECT stock_id FROM market_universe ORDER BY 1")
            else:
                cur.execute("SELECT stock_id FROM market_universe WHERE delisted_date IS NULL ORDER BY 1")
            return [r[0] for r in cur.fetchall()]


def status() -> str:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT count(*), count(*) FILTER (WHERE delisted_date IS NULL),
                                  count(*) FILTER (WHERE market_type = 'twse'), count(*) FILTER (WHERE market_type = 'tpex'),
                                  count(*) FILTER (WHERE delisted_date >= DATE '2018-01-01'), max(updated_at)
                           FROM market_universe""")
            n, active, twse, tpex, delisted_2018, upd = cur.fetchone()
    return (f'market_universe：{n} 檔（在市 {active}；上市 {twse}、上櫃 {tpex}；2018 以後下市 {delisted_2018}）'
            f'，最後同步 {upd}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sync', action='store_true')
    ap.add_argument('--status', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    if a.sync:
        print(sync())
    if a.status or a.sync:
        print(status())


if __name__ == '__main__':
    main()
