"""/news/signals 與 /news/signals/gates（Iteration 47）：端點只轉交 news_models，不碰模型也不碰資料庫。"""
import pytest
from fastapi.testclient import TestClient

import api
import news_models


@pytest.fixture
def client():
    return TestClient(api.app)


def test_signals_passes_stock_ids_and_never_logs_ledger(client, monkeypatch):
    calls = []

    def fake_signals(ids, log=True):
        calls.append((ids, log))
        return {'available': True, 'as_of': '2026-09-24',
                'models': {'news_event_vol': {'serving': True, 'credibility': 'proven'},
                           'news_drift': {'serving': False, 'credibility': 'none'}},
                'results': [{'stock_id': '2330', 'as_of': '2026-09-24', 'close': 2475.0,
                             'dims': {'ns_has_news': 1.0, 'ns_sent': 0.3, 'ev_sue': None},
                             'event_vol': {'range_pct': 1.2, 'is_elevated': False}, 'drift': None, 'tone': None}]}
    monkeypatch.setattr(news_models, 'signals', fake_signals)

    r = client.get('/news/signals?stock_ids=2330, 2303')
    assert r.status_code == 200
    assert calls == [(['2330', '2303'], False)]        # 讀取端點不寫台帳，台帳由 20:10 排程寫
    body = r.json()
    assert body['models']['news_drift']['serving'] is False
    assert body['results'][0]['drift'] is None            # 未服役的模型不給值
    assert body['results'][0]['dims']['ev_sue'] is None   # 沒有營收歷史 → null，不是 0

    r = client.get('/news/signals')
    assert calls[-1] == (None, False)


def test_signals_unavailable_is_passed_through(client, monkeypatch):
    monkeypatch.setattr(news_models, 'signals', lambda ids, log=True: {'available': False, 'reason': '無足夠資料建立新聞訊號面板'})
    body = client.get('/news/signals').json()
    assert body == {'available': False, 'reason': '無足夠資料建立新聞訊號面板'}


def test_gates_endpoint_wraps_training_report(client, monkeypatch):
    monkeypatch.setattr(news_models, 'gates_summary', lambda: {'news_event_vol': {'gates': {'deploy': True, 'N2_gain': 0.0134}}})
    body = client.get('/news/signals/gates').json()
    assert body['models']['news_event_vol']['gates']['deploy'] is True


def test_gates_summary_missing_file_returns_empty(monkeypatch, tmp_path):
    # 讀不到報告就回空字典，端點不會 500
    import builtins
    real_open = builtins.open

    def boom(path, *a, **k):
        if str(path).endswith('news_models.json'):
            raise FileNotFoundError(path)
        return real_open(path, *a, **k)
    monkeypatch.setattr(builtins, 'open', boom)
    assert news_models.gates_summary() == {}
