"""Iteration 83 收尾：使用者 2026-10-18 決定「重建」——減資 factor 上限 5 → 20 後，全市場表 `market_daily_prices.adj_close` 對現行事件表重算。
--dry：只讀，逐檔算「現在的 adj_close 與依現行事件重算後會差幾列」，列出會動到的股票（預期只有 1529、2364、3043）。
--run：先印三檔除權日前後的 adj_close，再跑 `market_data.rebuild_adj()`（全市場，確保整張表與事件表一致），再印一次。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter83_rebuild_adj.py --dry | --run"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
import market_data  # noqa: E402
import market_universe  # noqa: E402
import rebuild_adj_close  # noqa: E402
from db.connection import get_conn  # noqa: E402

THREE = {'1529': date(2018, 12, 22), '2364': date(2021, 10, 8), '3043': date(2022, 12, 19)}


def show(label):
    with get_conn() as conn:
        cur = conn.cursor()
        for sid, ex in THREE.items():
            cur.execute("""SELECT trade_date, close_price, adj_close FROM market_daily_prices
                           WHERE stock_id = %s AND trade_date BETWEEN %s AND %s ORDER BY 1""", (sid, ex - timedelta(days=10), ex + timedelta(days=6)))
            rows = cur.fetchall()
            print(f'{label} {sid} 除權日 {ex}：' + '；'.join(f'{d} 收 {c} adj {a}' for d, c, a in rows))


def dry():
    ids = market_universe.ids(include_delisted=True)
    events = rebuild_adj_close.load_events(set(ids))
    diff = {}
    with get_conn() as conn:
        cur = conn.cursor()
        plain = [s for s in ids if s not in events]
        cur.execute("""SELECT stock_id, count(*) FROM market_daily_prices WHERE stock_id = ANY(%s)
                       AND (adj_close IS NULL OR adj_close <> close_price) GROUP BY 1""", (plain,))
        for sid, n in cur.fetchall():
            diff[sid] = n
        for sid, evs in events.items():
            cur.execute("SELECT trade_date, close_price, adj_close FROM market_daily_prices WHERE stock_id = %s AND close_price > 0 ORDER BY 1", (sid,))
            rows = cur.fetchall()
            if not rows:
                continue
            cum = market_data._cum_factors([(d, c) for d, c, _ in rows], evs)
            n = sum(1 for d, c, a in rows if a is None or round(float(c) * cum[d], 4) != float(a))
            if n:
                diff[sid] = n
    print(f'全市場 {len(ids)} 檔（有事件 {len(events)} 檔）：重算後會變動的股票 {len(diff)} 檔、{sum(diff.values())} 列')
    for sid in sorted(diff):
        print(f'  {sid}：{diff[sid]} 列、事件 {[(str(d), round(f, 2)) for d, f, *_ in events.get(sid, [])]}')


if __name__ == '__main__':
    if '--dry' in sys.argv:
        show('重建前')
        dry()
    elif '--run' in sys.argv:
        show('重建前')
        n = market_data.rebuild_adj()
        print(f'rebuild_adj 更新 {n} 列')
        show('重建後')
    else:
        print(__doc__)
