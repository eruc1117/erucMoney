"""
基底爬蟲類別
提供：隨機延遲、UA 輪替、重試機制、Session 管理
所有具體爬蟲皆繼承此類別
"""

import logging
import random
import time
from abc import ABC, abstractmethod

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import DELAY_MIN, DELAY_MAX, MAX_RETRIES, REQUEST_TIMEOUT
from utils.user_agents import get_headers

logger = logging.getLogger(__name__)


class BaseScraper(ABC):

    def __init__(self, proxy: str | None = None):
        """
        Args:
            proxy: HTTP/HTTPS Proxy URL，格式 'http://user:pass@host:port'
                   為 None 時不使用代理
        """
        self.proxy = proxy
        self.session = self._build_session()

    # ── Session 建立 ──────────────────────────────────────────────────────────

    def _build_session(self) -> requests.Session:
        session = requests.Session()

        # 自動重試策略（針對 5xx 與連線錯誤）
        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=1.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        if self.proxy:
            session.proxies = {"http": self.proxy, "https": self.proxy}

        return session

    # ── 請求工具 ──────────────────────────────────────────────────────────────

    def get(self, url: str, referer: str = "") -> requests.Response | None:
        """
        發送 GET 請求，自動套用隨機 UA 與延遲。

        Returns:
            Response 物件；失敗時回傳 None
        """
        self._random_delay()
        headers = get_headers(referer=referer)

        try:
            resp = self.session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            logger.debug("GET %s → %s", url, resp.status_code)
            return resp
        except requests.RequestException as e:
            logger.warning("請求失敗 [%s]: %s", url, e)
            return None

    def _random_delay(self):
        """隨機等待，模擬人類瀏覽行為"""
        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        logger.debug("延遲 %.2f 秒", delay)
        time.sleep(delay)

    # ── 子類別必須實作 ────────────────────────────────────────────────────────

    @abstractmethod
    def fetch_list(self) -> list:
        """抓取文章/資料清單，回傳待爬連結或原始資料列表"""
        ...

    @abstractmethod
    def fetch_detail(self, url: str) -> object | None:
        """抓取單一頁面詳細內容，回傳對應的資料模型"""
        ...

    def run(self) -> list:
        """
        執行完整爬取流程：
        1. fetch_list() 取得清單
        2. 逐一 fetch_detail()
        3. 回傳所有成功解析的資料
        """
        items = []
        urls = self.fetch_list()
        logger.info("[%s] 取得 %d 筆清單", self.__class__.__name__, len(urls))

        for url in urls:
            item = self.fetch_detail(url)
            if item:
                items.append(item)

        logger.info("[%s] 成功解析 %d 筆", self.__class__.__name__, len(items))
        return items
