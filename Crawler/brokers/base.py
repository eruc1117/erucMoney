"""
券商介面的共同形狀。引擎（trading_engine.py）只呼叫這四個方法：
    execute(orders, exec_date) → [Fill]   把一批委託送出去，回每張的結果（成交／未成交／拒絕）
    positions() → {stock_id: shares}
    cash() → float
    configured() → (bool, 說明)
委託單本身存在 trading_orders 表，券商只負責「送出去、拿回結果」；誰下單、為什麼下，是引擎的事。
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


class BrokerNotConfigured(RuntimeError):
    """券商沒設定好（沒申請 API、沒填環境變數、套件沒裝）。引擎遇到就停下來記錯誤，不會自己想辦法。"""


@dataclass
class Fill:
    order_id: int
    status: str                      # filled / unfilled / rejected
    filled_shares: int = 0
    filled_price: Optional[float] = None
    fee: float = 0.0
    tax: float = 0.0
    broker_ref: Optional[str] = None
    note: Optional[str] = None
    extra: dict = field(default_factory=dict)


class Broker:
    name = 'base'

    def configured(self) -> tuple:
        return True, ''

    def execute(self, orders: list, exec_date: date) -> list:
        raise NotImplementedError

    def positions(self) -> dict:
        raise NotImplementedError

    def cash(self) -> float:
        raise NotImplementedError
