"""測試替身：FinMind DataLoader、同步版 Thread。"""
import threading

import pandas as pd


class FakeDataLoader:
    """
    取代 FinMind.data.DataLoader。每個 dataset 對應一個 callable 或固定 DataFrame；
    丟例外用 raise_for={'taiwan_stock_daily': RuntimeError('Requests reach the upper limit')}。
    """

    def __init__(self, frames: dict = None, raise_for: dict = None):
        self.frames = frames or {}
        self.raise_for = raise_for or {}
        self.logged_in_with = None
        self.calls = []

    def login_by_token(self, api_token: str):
        self.logged_in_with = api_token

    def _get(self, name, **kw):
        self.calls.append((name, kw))
        if name in self.raise_for:
            raise self.raise_for[name]
        v = self.frames.get(name)
        if callable(v):
            v = v(**kw)
        if v is None:
            return pd.DataFrame()
        return v if isinstance(v, pd.DataFrame) else pd.DataFrame(v)

    def taiwan_stock_daily(self, **kw):                         return self._get('taiwan_stock_daily', **kw)
    def taiwan_stock_institutional_investors(self, **kw):       return self._get('taiwan_stock_institutional_investors', **kw)
    def taiwan_stock_shareholding(self, **kw):                  return self._get('taiwan_stock_shareholding', **kw)
    def taiwan_stock_info(self, **kw):                          return self._get('taiwan_stock_info', **kw)
    def taiwan_stock_dividend_result(self, **kw):               return self._get('taiwan_stock_dividend_result', **kw)
    def taiwan_stock_capital_reduction_reference_price(self, **kw):
        return self._get('taiwan_stock_capital_reduction_reference_price', **kw)
    def us_stock_price(self, **kw):                             return self._get('us_stock_price', **kw)


def patch_finmind(monkeypatch, loader: FakeDataLoader):
    """讓 FinMindScraper._build_loader 回傳假的 DataLoader（不需要安裝或連線 FinMind）。"""
    from scrapers import finmind_scraper
    monkeypatch.setattr(finmind_scraper.FinMindScraper, '_build_loader', lambda self: loader)
    return loader


class SyncThread(threading.Thread):
    """start() 直接在當前執行緒跑完 target——api.py 的背景工作在測試裡變成同步，結果可立即斷言。"""

    def start(self):
        self.run()
