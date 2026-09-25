"""
股票資料模型
對應 DB.md 的 PostgreSQL stock_daily_prices / stock_chip_analysis schema
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass
class StockDailyPrice:
    stock_id: str
    trade_date: date
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    close_price: Optional[float] = None
    volume: Optional[int] = None
    turnover_value: Optional[float] = None
    transaction_count: Optional[int] = None
    change_value: Optional[float] = None
    change_rate: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "stock_id": self.stock_id,
            "trade_date": self.trade_date.isoformat(),
            "open_price": self.open_price,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "close_price": self.close_price,
            "volume": self.volume,
            "turnover_value": self.turnover_value,
            "transaction_count": self.transaction_count,
            "change_value": self.change_value,
            "change_rate": self.change_rate,
        }


@dataclass
class StockChipAnalysis:
    stock_id: str
    trade_date: date
    foreign_investor_buy: Optional[int] = None   # 外資買超張數
    investment_trust_buy: Optional[int] = None   # 投信買超張數
    dealer_buy: Optional[int] = None             # 自營商買超張數
    total_net_buy: Optional[int] = None          # 合計買超張數
    foreign_holding_ratio: Optional[float] = None  # 外資持股比例 (%)

    def to_dict(self) -> dict:
        return {
            "stock_id": self.stock_id,
            "trade_date": self.trade_date.isoformat(),
            "foreign_investor_buy": self.foreign_investor_buy,
            "investment_trust_buy": self.investment_trust_buy,
            "dealer_buy": self.dealer_buy,
            "total_net_buy": self.total_net_buy,
            "foreign_holding_ratio": self.foreign_holding_ratio,
        }


@dataclass
class StockForeignHolding:
    """外資持股（FinMind TaiwanStockShareholding，Iteration 35）。

    這是**絕對持股**，不是買賣超：外資今天手上有幾股、佔已發行股數幾 %。
    三大法人裡只有外資有這份每日資料（證交所「外資及陸資投資持股統計」）；
    投信、自營商沒有對應的每日持股揭露，只能用買賣超累計推估。
    """
    stock_id: str
    trade_date: date
    foreign_shares: Optional[int] = None            # 外資持有股數（股）
    foreign_ratio: Optional[float] = None           # 外資持股比例 (%)
    foreign_upper_limit_ratio: Optional[float] = None  # 外資投資上限 (%)
    shares_issued: Optional[int] = None             # 已發行股數（股）

    def to_dict(self) -> dict:
        return {
            "stock_id": self.stock_id,
            "trade_date": self.trade_date.isoformat(),
            "foreign_shares": self.foreign_shares,
            "foreign_ratio": self.foreign_ratio,
            "foreign_upper_limit_ratio": self.foreign_upper_limit_ratio,
            "shares_issued": self.shares_issued,
        }
