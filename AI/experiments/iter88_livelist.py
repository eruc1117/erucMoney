"""Iteration 88：訊號日當天的清單（成交日還沒行情、估成交日）和成交日行情到了之後的正常路徑算出來的清單要一樣。
(1) current_list(44, as_of=2026-10-12)：10-12 是訊號日、10-13 的行情不在 as_of 內 → 走 _pending_targets、exec_estimated=True；
(2) current_list(44, as_of=今天)：10-13 行情已在 → 正常路徑、覆蓋成真正的成交日；兩份清單逐檔比權重。
寫進 portfolio_live_list 的最終內容是 (2)。用法（Crawler 目錄）：PYTHONUTF8=1 PYTHONWARNINGS=ignore python ../AI/experiments/iter88_livelist.py"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'Crawler'))
import portfolio_backtest as pb  # noqa: E402
import portfolio_paper as pp  # noqa: E402
from db.connection import get_conn  # noqa: E402


def rows(rd):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT stock_id, rank, round(target_weight, 6), exec_date, is_new FROM portfolio_live_list WHERE rebalance_date = %s ORDER BY stock_id", (rd,))
        return cur.fetchall()


a = pb.current_list(44, as_of=date(2026, 10, 12))
print('(1) as_of 訊號日：', {k: a[k] for k in ('rebalance_date', 'exec_date', 'n', 'new', 'exec_estimated')})
ra = rows(date(2026, 10, 12))
b = pb.current_list(44, as_of=date.today())
print('(2) as_of 今天：', {k: b[k] for k in ('rebalance_date', 'exec_date', 'n', 'new', 'exec_estimated')})
rb = rows(date(2026, 10, 12))
wa = {s: (r, w) for s, r, w, _, _ in ra}
wb = {s: (r, w) for s, r, w, _, _ in rb}
print(f'逐檔（代碼、名次、權重）相同：{wa == wb}；(1) {len(wa)} 檔、(2) {len(wb)} 檔；只在 (1)：{sorted(set(wa) - set(wb))}；只在 (2)：{sorted(set(wb) - set(wa))}')
print('成交日：(1) 估', ra[0][3] if ra else None, '(2) 真', rb[0][3] if rb else None)
print('台積電權重：', wb.get('2330'))
print('新進（is_new）：', sorted(s for s, _, _, _, n in rb if n))
print('pending_lists(今天)：', pp.pending_lists(date.today()))
