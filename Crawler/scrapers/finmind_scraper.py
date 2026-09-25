"""
FinMind API 股票資料爬蟲

資料來源：FinMind (https://finmindtrade.com/)
取代原有 TWSE 直接爬蟲，改用 FinMind SDK 取得結構化資料。

安裝：pip install FinMind
Token：免費帳號有速率限制，可至 https://finmindtrade.com/ 註冊申請
"""

import logging
from datetime import date
from typing import Optional

from models.stock import StockDailyPrice, StockChipAnalysis, StockForeignHolding
from config import FINMIND

logger = logging.getLogger(__name__)


class FinMindScraper:
    """
    使用 FinMind DataLoader 抓取台灣股市資料。

    Args:
        stock_ids : 股票代碼列表，例如 ['2330', '2317']
        start_date: 資料起始日期（含）
        end_date  : 資料結束日期（含），預設今日
        token     : FinMind API Token；省略則使用 config.FINMIND['token']
    """

    def __init__(
        self,
        stock_ids: list[str],
        start_date: date,
        end_date: Optional[date] = None,
        token: str = "",
    ):
        self.stock_ids  = stock_ids
        self.start_date = start_date
        self.end_date   = end_date or date.today()
        self.token      = token or FINMIND.get("token", "")
        self._dl        = self._build_loader()

    # ── 初始化 DataLoader ─────────────────────────────────────────────────────

    def _build_loader(self):
        from FinMind.data import DataLoader
        dl = DataLoader()
        if self.token:
            dl.login_by_token(api_token=self.token)
            logger.info("[FinMind] 已登入（token）")
        else:
            logger.info("[FinMind] 使用匿名模式（速率限制較低，建議申請 token）")
        return dl

    # ── 個股每日行情 ──────────────────────────────────────────────────────────

    def fetch_prices(self) -> list[StockDailyPrice]:
        """
        呼叫 FinMind taiwan_stock_daily() 取得個股日行情。

        FinMind 欄位對照：
          date             → trade_date
          Trading Volume   → volume（成交股數）
          Trading money    → turnover_value（成交金額）
          open             → open_price
          max              → high_price
          min              → low_price
          close            → close_price
          spread           → change_value（漲跌）
          Trading turnover → transaction_count（成交筆數）

        change_rate 由公式計算：spread / (close - spread) * 100
        """
        results = []
        start = self.start_date.isoformat()
        end   = self.end_date.isoformat()

        for stock_id in self.stock_ids:
            try:
                df = self._dl.taiwan_stock_daily(
                    stock_id=stock_id,
                    start_date=start,
                    end_date=end,
                )
                if df is None or df.empty:
                    logger.warning("[FinMind] 無行情資料：%s %s~%s", stock_id, start, end)
                    continue

                for _, row in df.iterrows():
                    close  = _to_float(row.get("close"))
                    spread = _to_float(row.get("spread"))

                    change_rate = None
                    if spread is not None and close is not None:
                        prev = close - spread
                        if prev and prev != 0:
                            change_rate = round(spread / prev * 100, 3)

                    results.append(StockDailyPrice(
                        stock_id=stock_id,
                        trade_date=date.fromisoformat(str(row["date"])[:10]),
                        open_price=_to_float(row.get("open")),
                        high_price=_to_float(row.get("max")),
                        low_price=_to_float(row.get("min")),
                        close_price=close,
                        volume=_to_int(row.get("Trading_Volume", row.get("Trading Volume"))),
                        turnover_value=_to_float(row.get("Trading_money", row.get("Trading money"))),
                        transaction_count=_to_int(row.get("Trading_turnover", row.get("Trading turnover"))),
                        change_value=spread,
                        change_rate=change_rate,
                    ))

                logger.info("[FinMind] 行情：%s 取得 %d 筆", stock_id, len(df))

            except Exception as e:
                logger.error("[FinMind] 行情抓取失敗 %s：%s", stock_id, e)

        return results

    # ── 美股日行情 ────────────────────────────────────────────────────────────

    def fetch_us_prices(self) -> list[dict]:
        """
        呼叫 FinMind us_stock_price() 取得美股日行情（Iteration 14 新增）。

        FinMind 欄位：date, stock_id, Open, High, Low, Close, Adj_Close, Volume

        **務必使用 Adj_Close 計算報酬率**——它已還原分割與配息；
        用原始 Close 會在除權息日產生假跳空，被模型當成真實波動學習。
        原始 Close 仍保留供顯示與對帳。
        """
        results = []
        start = self.start_date.isoformat()
        end = self.end_date.isoformat()

        for ticker in self.stock_ids:
            try:
                df = self._dl.us_stock_price(
                    stock_id=ticker, start_date=start, end_date=end)
                if df is None or df.empty:
                    logger.warning("[FinMind] 無美股資料：%s %s~%s", ticker, start, end)
                    continue

                for _, row in df.iterrows():
                    results.append({
                        'ticker': ticker,
                        'trade_date': date.fromisoformat(str(row["date"])[:10]),
                        'open_price': _to_float(row.get("Open")),
                        'high_price': _to_float(row.get("High")),
                        'low_price': _to_float(row.get("Low")),
                        'close_price': _to_float(row.get("Close")),
                        'adj_close': _to_float(row.get("Adj_Close", row.get("Close"))),
                        'volume': _to_int(row.get("Volume")),
                    })
                logger.info("[FinMind] 美股：%s 取得 %d 筆", ticker, len(df))
            except Exception as e:
                logger.error("[FinMind] 美股抓取失敗 %s：%s", ticker, e)

        return results

    # ── 除權息結果 ────────────────────────────────────────────────────────────

    def fetch_dividend_results(self) -> list[dict]:
        """
        呼叫 FinMind taiwan_stock_dividend_result()（Iteration 17 新增）。

        FinMind 欄位：
          date                      除權息交易日
          before_price              除權息前一日收盤
          reference_price           除權息參考價（交易所計算的理論開盤基準）
          stock_and_cache_dividend  配息／配股金額
          stock_or_cache_dividend   息 / 權 / 權息

        `reference_price` 是修正跳空的關鍵——用它取代前一日收盤，
        即可扣除配息造成的機械性缺口。
        """
        results = []
        start = self.start_date.isoformat()
        end = self.end_date.isoformat()

        for sid in self.stock_ids:
            try:
                df = self._dl.taiwan_stock_dividend_result(
                    stock_id=sid, start_date=start, end_date=end)
                if df is None or df.empty:
                    logger.info("[FinMind] 無除權息資料：%s", sid)
                    continue

                for _, row in df.iterrows():
                    ref = _to_float(row.get("reference_price"))
                    if ref is None or ref <= 0:
                        continue          # 無參考價則無法修正，略過
                    results.append({
                        'stock_id': sid,
                        'ex_date': date.fromisoformat(str(row["date"])[:10]),
                        'before_price': _to_float(row.get("before_price")),
                        'reference_price': ref,
                        'dividend': _to_float(row.get("stock_and_cache_dividend")),
                        'dividend_type': str(row.get("stock_or_cache_dividend") or '')[:8],
                    })
                logger.info("[FinMind] 除權息：%s 取得 %d 筆", sid, len(df))
            except Exception as e:
                logger.error("[FinMind] 除權息抓取失敗 %s：%s", sid, e)

        return results

    # ── 減資參考價 ────────────────────────────────────────────────────────────

    def fetch_capital_reductions(self) -> list[dict]:
        """
        呼叫 FinMind taiwan_stock_capital_reduction_reference_price()（Iteration 18）。

        FinMind 欄位：
          date                            減資後首個交易日
          ClosingPriceonTheLastTradingDay 最後交易日收盤
          PostReductionReferencePrice     減資後參考價
          ReasonforCapitalReduction       減資原因

        方向與除權息相反：減資參考價**高於**前收（股份被註銷），
        例如 2409 於 2022-10-11 現金減資，14.70 → 15.87（+7.96%）。
        """
        results = []
        start = self.start_date.isoformat()
        end = self.end_date.isoformat()

        for sid in self.stock_ids:
            try:
                df = self._dl.taiwan_stock_capital_reduction_reference_price(
                    stock_id=sid, start_date=start, end_date=end)
                if df is None or df.empty:
                    continue

                for _, row in df.iterrows():
                    ref = _to_float(row.get("PostReductionReferencePrice"))
                    before = _to_float(row.get("ClosingPriceonTheLastTradingDay"))
                    if not ref or not before or ref <= 0 or before <= 0:
                        continue
                    results.append({
                        'stock_id': sid,
                        'ex_date': date.fromisoformat(str(row["date"])[:10]),
                        'before_price': before,
                        'reference_price': ref,
                        'reason': str(row.get("ReasonforCapitalReduction") or '')[:80],
                    })
                logger.info("[FinMind] 減資：%s 取得 %d 筆", sid, len(df))
            except Exception as e:
                logger.error("[FinMind] 減資抓取失敗 %s：%s", sid, e)

        return results

    # ── 三大法人籌碼 ──────────────────────────────────────────────────────────

    def fetch_chips(self) -> list[StockChipAnalysis]:
        """
        呼叫 FinMind taiwan_stock_institutional_investors() 取得三大法人資料。

        FinMind 回傳格式（每筆為單一法人）：
          date, stock_id, name, buy, sell, net  （單位：張）

        name 可能值：Foreign_Investor, Investment_Trust,
                     Dealer_self, Dealer_Hedging, Dealer（合計）

        彙總方式：
          foreign_investor_buy = Foreign_Investor.net
          investment_trust_buy = Investment_Trust.net
          dealer_buy           = Dealer.net
                                 或 Dealer_self.net + Dealer_Hedging.net
          total_net_buy        = 三者合計
        """
        results = []
        start = self.start_date.isoformat()
        end   = self.end_date.isoformat()

        for stock_id in self.stock_ids:
            try:
                df = self._dl.taiwan_stock_institutional_investors(
                    stock_id=stock_id,
                    start_date=start,
                    end_date=end,
                )
                if df is None or df.empty:
                    logger.warning("[FinMind] 無籌碼資料：%s %s~%s", stock_id, start, end)
                    continue

                for trade_date_str, group in df.groupby("date"):
                    net_map = {
                        row["name"]: (_to_int(row.get("buy", 0)) or 0) - (_to_int(row.get("sell", 0)) or 0)
                        for _, row in group.iterrows()
                    }

                    foreign = net_map.get("Foreign_Investor", 0) or 0
                    trust   = net_map.get("Investment_Trust", 0) or 0
                    # 優先用合計 Dealer；若無則加總子項
                    dealer  = (
                        net_map.get("Dealer")
                        or ((net_map.get("Dealer_self") or 0) + (net_map.get("Dealer_Hedging") or 0))
                    ) or 0
                    total   = foreign + trust + dealer

                    results.append(StockChipAnalysis(
                        stock_id=stock_id,
                        trade_date=date.fromisoformat(str(trade_date_str)[:10]),
                        foreign_investor_buy=foreign,
                        investment_trust_buy=trust,
                        dealer_buy=dealer,
                        total_net_buy=total,
                        foreign_holding_ratio=None,  # 需另呼叫 taiwan_stock_shareholding
                    ))

                logger.info("[FinMind] 籌碼：%s 取得 %d 日", stock_id, len(df.groupby("date")))

            except Exception as e:
                logger.error("[FinMind] 籌碼抓取失敗 %s：%s", stock_id, e)

        return results

    # ── 外資持股（絕對持股，非買賣超）─────────────────────────────────────────

    def fetch_foreign_holding(self) -> list[StockForeignHolding]:
        """
        呼叫 FinMind taiwan_stock_shareholding() 取得外資持股統計（Iteration 35）。

        FinMind 欄位對照（每檔每日一列）：
          ForeignInvestmentShares          → foreign_shares（外資持有股數）
          ForeignInvestmentSharesRatio     → foreign_ratio（外資持股比例 %）
          ForeignInvestmentUpperLimitRatio → foreign_upper_limit_ratio（投資上限 %）
          NumberOfSharesIssued             → shares_issued（已發行股數）

        與 fetch_chips 的差別：那邊是「今天買賣了多少」，這邊是「今天手上有多少」。
        每檔一次呼叫，額度計算與行情、籌碼相同。
        """
        results = []
        start = self.start_date.isoformat()
        end   = self.end_date.isoformat()

        for stock_id in self.stock_ids:
            try:
                df = self._dl.taiwan_stock_shareholding(
                    stock_id=stock_id,
                    start_date=start,
                    end_date=end,
                )
                if df is None or df.empty:
                    logger.warning("[FinMind] 無外資持股資料：%s %s~%s", stock_id, start, end)
                    continue

                for _, row in df.iterrows():
                    results.append(StockForeignHolding(
                        stock_id=stock_id,
                        trade_date=date.fromisoformat(str(row["date"])[:10]),
                        foreign_shares=_to_int(row.get("ForeignInvestmentShares")),
                        foreign_ratio=_to_float(row.get("ForeignInvestmentSharesRatio")),
                        foreign_upper_limit_ratio=_to_float(row.get("ForeignInvestmentUpperLimitRatio")),
                        shares_issued=_to_int(row.get("NumberOfSharesIssued")),
                    ))

                logger.info("[FinMind] 外資持股：%s 取得 %d 筆", stock_id, len(df))

            except Exception as e:
                logger.error("[FinMind] 外資持股抓取失敗 %s：%s", stock_id, e)

        return results

    # ── 個股基本資訊 ──────────────────────────────────────────────────────────

    def fetch_stock_info(self) -> list[dict]:
        """
        呼叫 FinMind taiwan_stock_info() 取得個股基本資訊。
        僅回傳 stock_ids 中的股票資訊。

        Returns:
            [{ stock_id, stock_name, industry_type, market_type }, ...]
        """
        try:
            df = self._dl.taiwan_stock_info()
            if df is None or df.empty:
                return []

            target  = set(self.stock_ids)
            results = []
            for _, row in df.iterrows():
                sid = str(row.get("stock_id", "")).strip()
                if sid not in target:
                    continue
                results.append({
                    "stock_id":      sid,
                    "stock_name":    str(row.get("stock_name", sid)).strip(),
                    "industry_type": str(row.get("industry_category", "")).strip() or None,
                    "market_type":   str(row.get("type", "上市")).strip() or "上市",
                })
            return results

        except Exception as e:
            logger.error("[FinMind] 個股基本資訊抓取失敗：%s", e)
            return []


# ── 工具函式 ───────────────────────────────────────────────────────────────────

def _to_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
        return None if (f != f) else f   # NaN → None
    except (ValueError, TypeError):
        return None


def _to_int(val) -> Optional[int]:
    if val is None:
        return None
    try:
        f = float(val)
        if f != f:       # NaN
            return None
        return int(f)
    except (ValueError, TypeError):
        return None
