"""
紙上券商：用隔天的實際行情模擬零股限價單，成交寫進 portfolio_paper_trades（和 Iteration 54 的模擬帳戶同一本帳、同一條淨值）。

成交規則（比 portfolio_paper.fill 多了「限價」這一層）：
    買：開盤 ≤ 限價才成交，成交價 = 開盤（限價單在開盤價更好時以開盤成交）；開盤跳過限價 → 未成交
    賣：開盤 ≥ 限價才成交
    一字鎖漲跌停（高 = 低、相對前收 ≥ 9.5%）→ 未成交
    沒行情（停牌）→ 未成交
    賣超過持股：沒持股拒絕、有持股就縮到持股數；買超過現金 → 縮到現金放得下（不夠買 1 股拒絕）
費率與模擬帳戶一致：單邊手續費 0.0855%、賣出證交稅 0.3%。
"""
import logging
from datetime import date

import portfolio_paper as pp
import trading_rules as tr
from db.connection import get_conn

from .base import Broker, Fill

logger = logging.getLogger(__name__)


class PaperBroker(Broker):
    name = 'paper'

    def configured(self):
        return (True, '模擬帳戶') if pp.state() else (False, '模擬帳戶還沒開（python portfolio_paper.py --start）')

    def positions(self) -> dict:
        return pp.holdings()

    def cash(self) -> float:
        st = pp.state()
        return st['cash'] if st else 0.0

    def execute(self, orders: list, exec_date: date) -> list:
        st = pp.state()
        if not st:
            return [Fill(o['id'], 'rejected', note='模擬帳戶還沒開') for o in orders]
        held = pp.holdings()
        px = pp.day_prices(exec_date, [o['stock_id'] for o in orders])
        res = tr.fill_orders(orders, px, held, st['cash'])        # 成交規則與回放同一份（trading_rules.fill_orders）
        cash = res['cash']
        fills, rows = [], []
        for f in res['fills']:
            o = f['order']
            if f['status'] == 'filled':
                rows.append((o.get('rebalance_date'), exec_date, o['stock_id'], o['side'], f['filled_shares'], f['filled_price'], f['gross'], f['fee'], f['tax'], True,
                             f"order {o['id']} {o['reason']}"))
                fills.append(Fill(o['id'], 'filled', f['filled_shares'], f['filled_price'], f['fee'], f['tax'], broker_ref=f'paper-{o["id"]}'))
            else:
                fills.append(Fill(o['id'], f['status'], note=f.get('note')))
        with get_conn() as conn:
            with conn.cursor() as cur:
                if rows:
                    from psycopg2.extras import execute_values
                    execute_values(cur, """INSERT INTO portfolio_paper_trades (rebalance_date, trade_date, stock_id, side, shares, price, gross, fee, tax, filled, note)
                                           VALUES %s""", rows)
                cur.execute("UPDATE portfolio_paper_state SET cash = %s, updated_at = CURRENT_TIMESTAMP WHERE id = 1", (round(cash, 2),))
            conn.commit()
        logger.info('[broker/paper] %s：%d 張委託，成交 %d', exec_date, len(orders), sum(1 for f in fills if f.status == 'filled'))
        return fills
