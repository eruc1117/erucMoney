"""
pytest 共用設定（Crawler）

- 把 Crawler/ 加進 sys.path，測試裡直接 `import config`、`from scrapers import ...`。
- 資料庫測試（marker `db`）一律連 CRAWLER_TEST_DB（預設 Stock_crawler_test），名字必須以 _test 結尾；
  連不上或名字不對就整批 skip，絕不碰正式的 Stock。
- 網路：所有測試都不上網。responses 攔 requests，FinMind 的 DataLoader 用假物件。
"""
import os
import sys
from pathlib import Path

import pytest

CRAWLER_DIR = Path(__file__).resolve().parent.parent
if str(CRAWLER_DIR) not in sys.path:
    sys.path.insert(0, str(CRAWLER_DIR))

# 一定要在任何專案模組 import 之前設好：config.DB 在 import 時就決定 dbname
TEST_DB = os.environ.setdefault('CRAWLER_TEST_DB', 'Stock_crawler_test')

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def fx():
    """讀 fixtures/ 的 helper：fx('twse_stock_day.json')。"""
    return fixture_text


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """爬蟲到處 time.sleep（禮貌延遲、被擋等 90 秒）；測試裡全部變成 no-op。"""
    import time
    monkeypatch.setattr(time, 'sleep', lambda *_a, **_k: None)


# ── 資料庫 ──────────────────────────────────────────────────────────────────
def _db_available() -> tuple:
    if not TEST_DB.endswith('_test'):
        return False, f'CRAWLER_TEST_DB={TEST_DB} 不是以 _test 結尾，拒絕在上面跑測試'
    try:
        from helpers import db_setup
        db_setup.ensure_database()
        return True, ''
    except Exception as e:  # noqa: BLE001
        return False, f'測試資料庫不可用：{e}'


_DB_STATE = {}


def pytest_collection_modifyitems(config, items):
    """有 db marker 的測試，資料庫不可用時全部 skip（不是 fail）。"""
    if not any(item.get_closest_marker('db') for item in items):
        return
    ok, reason = _db_available()
    _DB_STATE['ok'], _DB_STATE['reason'] = ok, reason
    if ok:
        return
    skip = pytest.mark.skip(reason=reason)
    for item in items:
        if item.get_closest_marker('db'):
            item.add_marker(skip)


@pytest.fixture(scope='session')
def test_db():
    """整個 session 建一次 schema；回傳 helpers.db_setup 模組給測試呼叫 truncate / seed。"""
    from helpers import db_setup
    db_setup.ensure_database()
    db_setup.apply_schema()
    yield db_setup
    from db.connection import close_pool
    close_pool()


@pytest.fixture
def clean_db(test_db):
    """每個測試開始前清空會被寫入的表。"""
    test_db.truncate_all()
    return test_db
