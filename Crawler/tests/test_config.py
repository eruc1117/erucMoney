"""設定：.env 手寫解析、缺密碼明講、FINMIND_TOKEN 空字串＝匿名。"""
import importlib
import os

import pytest

import config


def test_load_env_parses_quotes_spaces_and_comments(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text(
        '# 註解\n'
        '\n'
        'T_A = "quoted value"\n'
        "T_B='single'  \n"
        'T_C=with=equals=inside\n'
        'T_D=   spaced   \n'
        'not a kv line\n'
        'T_E=\n',
        encoding='utf-8')
    for k in ('T_A', 'T_B', 'T_C', 'T_D', 'T_E'):
        monkeypatch.delenv(k, raising=False)
    config._load_env(env)
    assert os.environ['T_A'] == 'quoted value'
    assert os.environ['T_B'] == 'single'
    assert os.environ['T_C'] == 'with=equals=inside'      # 只切第一個 =
    assert os.environ['T_D'] == 'spaced'
    assert os.environ['T_E'] == ''


def test_load_env_does_not_override_existing_environment(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('T_X=from_file\n', encoding='utf-8')
    monkeypatch.setenv('T_X', 'from_shell')
    config._load_env(env)
    assert os.environ['T_X'] == 'from_shell'


def test_load_env_missing_file_is_silent(tmp_path):
    config._load_env(tmp_path / 'nope.env')     # 不能拋例外：沒有 .env 的機器也要能 import


def test_validate_reports_missing_password(monkeypatch):
    monkeypatch.setitem(config.DB, 'password', '')
    with pytest.raises(ValueError, match='DB_PASSWORD'):
        config.validate()
    monkeypatch.setitem(config.DB, 'password', 'x')
    config.validate()


def test_test_db_override_only_changes_dbname(monkeypatch):
    """CRAWLER_TEST_DB 只換資料庫名，其餘連線參數照 .env；沒設時回到 DB_NAME。"""
    monkeypatch.setenv('CRAWLER_TEST_DB', 'Whatever_test')
    monkeypatch.setenv('DB_NAME', 'Stock')
    m = importlib.reload(config)
    assert m.DB['dbname'] == 'Whatever_test'
    monkeypatch.delenv('CRAWLER_TEST_DB')
    m = importlib.reload(config)
    assert m.DB['dbname'] == 'Stock'
    # 還原成測試庫，後面的測試才不會連錯
    monkeypatch.setenv('CRAWLER_TEST_DB', os.environ.get('PYTEST_CRAWLER_DB', 'Stock_crawler_test'))
    importlib.reload(config)


def test_finmind_empty_token_means_anonymous(monkeypatch):
    from datetime import date
    from scrapers import finmind_scraper
    from helpers.fakes import FakeDataLoader

    fake = FakeDataLoader()
    monkeypatch.setattr('FinMind.data.DataLoader', lambda: fake, raising=False)
    import FinMind.data
    monkeypatch.setattr(FinMind.data, 'DataLoader', lambda: fake)

    monkeypatch.setitem(finmind_scraper.FINMIND, 'token', '')
    finmind_scraper.FinMindScraper(['2330'], date(2026, 9, 1))
    assert fake.logged_in_with is None            # 空字串：不呼叫 login_by_token

    finmind_scraper.FinMindScraper(['2330'], date(2026, 9, 1), token='abc123')
    assert fake.logged_in_with == 'abc123'        # 有 token 才登入
