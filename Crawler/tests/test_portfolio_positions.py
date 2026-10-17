"""
Iteration 76：GET /portfolio/runs/{id}/positions——「贏過大盤」清單點開看某次回測每個訊號日買了什麼。

只讀 portfolio_runs／portfolio_positions／market_universe；名稱從候選池帶，不在池內的留 None。
"""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

import portfolio_api as pa
import portfolio_backtest as pb


@pytest.mark.db
def test_run_positions_groups_by_signal_date_with_names_and_counts(clean_db):
    db = clean_db
    db.execute("INSERT INTO market_universe (stock_id, stock_name) VALUES ('1111', '甲公司'), ('2330', '台積電')")
    d1, d2 = dt.date(2024, 1, 11), dt.date(2024, 2, 15)
    pos = pd.DataFrame([
        {'rebalance_date': d1, 'exec_date': dt.date(2024, 1, 12), 'stock_id': '2330', 'rank': np.nan, 'signal_value': np.nan, 'target_weight': 0.5, 'filled': True},
        {'rebalance_date': d1, 'exec_date': dt.date(2024, 1, 12), 'stock_id': '1111', 'rank': 1, 'signal_value': 1.2, 'target_weight': 0.5, 'filled': True},
        {'rebalance_date': d2, 'exec_date': dt.date(2024, 2, 16), 'stock_id': '2330', 'rank': np.nan, 'signal_value': np.nan, 'target_weight': 0.5, 'filled': True},
        {'rebalance_date': d2, 'exec_date': dt.date(2024, 2, 16), 'stock_id': '9999', 'rank': 1, 'signal_value': 0.8, 'target_weight': 0.5, 'filled': False},
    ])
    rid = pb.save_run(1, 'a', 'win3', 'dev', dt.date(2024, 1, 1), dt.date(2024, 3, 31), {}, {'ann_active': 0.05}, pos, '')

    out = pa.run_positions(rid)
    assert out['run_id'] == rid and out['experiment_n'] == 1 and out['name'] == 'a'
    assert out['n_rebalances'] == 2 and out['n_stocks'] == 3
    assert [g['rebalance_date'] for g in out['rebalances']] == ['2024-01-11', '2024-02-15']      # 訊號日由舊到新
    g1 = out['rebalances'][0]
    assert g1['exec_date'] == '2024-01-12'
    assert [p['stock_id'] for p in g1['positions']] == ['1111', '2330']                          # 有排名的在前、台積電（沒排名）在後
    assert g1['positions'][0] == {'stock_id': '1111', 'stock_name': '甲公司', 'rank': 1, 'signal_value': 1.2, 'target_weight': 0.5, 'filled': True}
    g2 = out['rebalances'][1]['positions']
    assert {p['stock_id']: p['stock_name'] for p in g2} == {'2330': '台積電', '9999': None}       # 不在候選池的沒名字、仍要列
    assert next(p for p in g2 if p['stock_id'] == '9999')['filled'] is False
    assert out['frequent'][0] == {'stock_id': '2330', 'stock_name': '台積電', 'times': 2}        # 出現次數多的在前
    assert pa.run_positions(rid + 999) is None


def test_api_run_positions_passthrough_and_404(monkeypatch):
    from fastapi.testclient import TestClient
    import api
    monkeypatch.setattr(pa, 'run_positions', lambda rid: {'run_id': rid, 'rebalances': []} if rid == 44 else None)
    client = TestClient(api.app)
    r = client.get('/portfolio/runs/44/positions')
    assert r.status_code == 200 and r.json() == {'run_id': 44, 'rebalances': []}
    assert client.get('/portfolio/runs/45/positions').status_code == 404
