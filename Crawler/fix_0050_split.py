"""0050 在 2025-06-18 做 1 拆 4 的分割（前一日收盤 188.65 → 當天 47.57），還原價沒處理，對手曲線從那天起少了四分之三。
把分割當成一個公司行動寫進 stock_capital_reduction（factor = 參考價 ÷ 前收 = 0.25，和減資同一套回溯還原），再重建 0050 的 adj_close。
只寫一列、只重建一檔；重跑是冪等的（ON CONFLICT 不重複）。
    python fix_0050_split.py            # 寫事件 + 重建
    python fix_0050_split.py --check    # 只看前後的 adj_close
"""
import sys
from datetime import date

from db.connection import get_conn

EX = date(2025, 6, 18)
SPLIT = 4


def main():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date, close_price FROM stock_daily_prices WHERE stock_id='0050' AND trade_date < %s ORDER BY trade_date DESC LIMIT 1", (EX,))
            prev_d, before = cur.fetchone()
            cur.execute("SELECT close_price FROM stock_daily_prices WHERE stock_id='0050' AND trade_date = %s", (EX,))
            first = cur.fetchone()[0]
            print(f'分割前最後收盤 {prev_d} {before}；分割日 {EX} 收盤 {first}；比例 {float(before) / float(first):.2f}')
            if '--check' in sys.argv:
                cur.execute("SELECT trade_date, close_price, adj_close FROM stock_daily_prices WHERE stock_id='0050' AND trade_date IN ('2024-10-01','2025-06-17','2025-06-18','2026-10-08') ORDER BY 1")
                for r in cur.fetchall():
                    print('  ', r)
                return
            ref = round(float(before) / SPLIT, 4)
            cur.execute("""INSERT INTO stock_capital_reduction (stock_id, ex_date, before_price, reference_price, reason)
                           VALUES ('0050', %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""", (EX, before, ref, f'股票分割 1 拆 {SPLIT}（ETF），還原用'))
        conn.commit()
    print(f'已寫入分割事件：ex {EX}、前收 {before}、參考價 {ref}（factor {ref / float(before):.4f}）')
    import rebuild_adj_close as rb
    n = rb.rebuild(['0050'])
    print('rebuild rows', n)
    main_check()


def main_check():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT trade_date, close_price, adj_close FROM stock_daily_prices WHERE stock_id='0050' AND trade_date IN ('2024-10-01','2025-06-17','2025-06-18','2026-10-08') ORDER BY 1")
            for r in cur.fetchall():
                print('  ', r)


if __name__ == '__main__':
    main()
