"""
台灣證券交易所 (TWSE) 股票資料爬蟲
使用 TWSE 官方 JSON API，不需要 HTML 解析。

API 說明：
  - stock_day：個股每日行情（需指定日期與股票代碼）
  - chip：三大法人每日買賣超彙總
  - stock_list：上市股票清單（含個股基本資訊）
"""

import logging
from datetime import date, datetime

import requests

from models.stock import StockDailyPrice, StockChipAnalysis
from scrapers.base_scraper import BaseScraper
from config import TWSE_API

logger = logging.getLogger(__name__)

# TWSE API 回應欄位索引（stock_daily_prices）
_PRICE_FIELDS = {
    "trade_date": 0,   # 日期
    "volume": 1,       # 成交股數
    "turnover": 2,     # 成交金額
    "open": 3,         # 開盤價
    "high": 4,         # 最高價
    "low": 5,          # 最低價
    "close": 6,        # 收盤價
    "change": 7,       # 漲跌價差
    "transactions": 8, # 成交筆數
}

# TWSE API 回應欄位索引（T86 三大法人）
_CHIP_FIELDS = {
    "stock_id": 0,
    "stock_name": 1,
    "foreign_buy": 2,
    "foreign_sell": 3,
    "foreign_net": 4,
    "trust_buy": 5,
    "trust_sell": 6,
    "trust_net": 7,
    "dealer_net": 14,   # 自營商合計買超
    "total_net": 18,    # 三大法人合計
}


class TWSEScraper(BaseScraper):
    """
    因為 TWSE 提供結構化 JSON API，
    fetch_list 回傳的是 (stock_id, date) 配對，
    fetch_detail 則直接呼叫 API 取得單一股票資料。
    """

    def __init__(self, stock_ids: list[str], target_date: date | None = None, **kwargs):
        """
        Args:
            stock_ids: 要爬取的股票代碼列表，例如 ['2330', '2317']
            target_date: 爬取日期，預設為今日
        """
        super().__init__(**kwargs)
        self.stock_ids = stock_ids
        self.target_date = target_date or date.today()

    # ── 實作 BaseScraper 介面 ─────────────────────────────────────────────────

    def fetch_list(self) -> list[tuple[str, date]]:
        """回傳 (stock_id, date) 清單，供 fetch_detail 使用"""
        return [(sid, self.target_date) for sid in self.stock_ids]

    def fetch_detail(self, item: tuple[str, date]) -> StockDailyPrice | None:
        """
        呼叫 TWSE STOCK_DAY API 取得指定股票當日行情。
        """
        stock_id, trade_date = item
        return self.fetch_daily_price(stock_id, trade_date)

    # ── 個股每日行情 ──────────────────────────────────────────────────────────

    def fetch_daily_price(self, stock_id: str, trade_date: date) -> StockDailyPrice | None:
        """
        呼叫 TWSE STOCK_DAY API。
        API 回傳整個月的資料，從中找出指定日期的那一列。
        """
        date_str = trade_date.strftime("%Y%m%d")
        params = {"response": "json", "date": date_str, "stockNo": stock_id}

        data = self._call_twse_api(TWSE_API["stock_day"], params)
        if not data or data.get("stat") != "OK":
            logger.warning("[TWSE] stock_day API 失敗：%s %s", stock_id, date_str)
            return None

        rows = data.get("data", [])
        target_row = _find_row_by_date(rows, trade_date)
        if not target_row:
            logger.debug("[TWSE] 找不到 %s 在 %s 的資料", stock_id, trade_date)
            return None

        return StockDailyPrice(
            stock_id=stock_id,
            trade_date=trade_date,
            volume=_parse_int(target_row[_PRICE_FIELDS["volume"]]),
            turnover_value=_parse_float(target_row[_PRICE_FIELDS["turnover"]]),
            open_price=_parse_float(target_row[_PRICE_FIELDS["open"]]),
            high_price=_parse_float(target_row[_PRICE_FIELDS["high"]]),
            low_price=_parse_float(target_row[_PRICE_FIELDS["low"]]),
            close_price=_parse_float(target_row[_PRICE_FIELDS["close"]]),
            change_value=_parse_float(target_row[_PRICE_FIELDS["change"]]),
            transaction_count=_parse_int(target_row[_PRICE_FIELDS["transactions"]]),
        )

    # ── 三大法人籌碼 ──────────────────────────────────────────────────────────

    def fetch_chip_analysis(self, trade_date: date) -> list[StockChipAnalysis]:
        """
        呼叫 TWSE T86 API 取得所有上市股票當日三大法人買賣超。
        """
        date_str = trade_date.strftime("%Y%m%d")
        params = {"response": "json", "date": date_str, "selectType": "ALL"}

        data = self._call_twse_api(TWSE_API["chip"], params)
        if not data or data.get("stat") != "OK":
            logger.warning("[TWSE] chip API 失敗：%s", date_str)
            return []

        results = []
        for row in data.get("data", []):
            try:
                stock_id = row[_CHIP_FIELDS["stock_id"]].strip()
                foreign_net = _parse_int(row[_CHIP_FIELDS["foreign_net"]])
                trust_net = _parse_int(row[_CHIP_FIELDS["trust_net"]])
                dealer_net = _parse_int(row[_CHIP_FIELDS["dealer_net"]])
                total_net = _parse_int(row[_CHIP_FIELDS["total_net"]])

                # 買超 = 淨值為正，賣超 = 淨值為負
                results.append(StockChipAnalysis(
                    stock_id=stock_id,
                    trade_date=trade_date,
                    foreign_investor_buy=foreign_net,
                    investment_trust_buy=trust_net,
                    dealer_buy=dealer_net,
                    total_net_buy=total_net,
                ))
            except (IndexError, ValueError) as e:
                logger.debug("[TWSE] chip 資料列解析錯誤：%s", e)
                continue

        logger.info("[TWSE] 取得 %d 筆籌碼資料（%s）", len(results), date_str)
        return results

    # ── 內部工具 ──────────────────────────────────────────────────────────────

    def _call_twse_api(self, url: str, params: dict) -> dict | None:
        """呼叫 TWSE JSON API，回傳解析後的 dict"""
        self._random_delay()
        # TWSE 對過多的瀏覽器模擬標頭（Sec-Fetch-* 等）會回傳空 body，
        # 僅使用必要的三個標頭即可正常取得資料。
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.twse.com.tw/",
        }

        try:
            resp = self.session.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.warning("[TWSE] 請求失敗 %s：%s", url, e)
            return None
        except ValueError as e:
            logger.warning("[TWSE] JSON 解析失敗：%s", e)
            return None


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _find_row_by_date(rows: list[list], target: date) -> list | None:
    """從 TWSE 回傳的 data rows 中找出指定日期的列"""
    target_str = "{:d}/{:02d}/{:02d}".format(
        target.year - 1911, target.month, target.day  # 民國年
    )
    for row in rows:
        if row and row[0].strip() == target_str:
            return row
    return None


def _parse_float(raw: str) -> float | None:
    """移除千分位逗號後轉為 float；'--' 或空值回傳 None"""
    cleaned = raw.strip().replace(",", "")
    if cleaned in ("--", "", "X", "+", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int(raw: str) -> int | None:
    """移除千分位逗號後轉為 int"""
    cleaned = raw.strip().replace(",", "")
    if cleaned in ("--", "", "X"):
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None
