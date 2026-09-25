"""
投票引擎：整合三模型輸出，執行加權多數決，結果寫入 voting_results。
"""
import json
import logging
import requests
from datetime import date

from db.connection import get_conn
import model2_news as m2
import model3_chip as m3

logger = logging.getLogger(__name__)

# ── 預設與個股權重 ──────────────────────────────────────────────────────────
WEIGHTS_DEFAULT = {'m1': 0.34, 'm2': 0.33, 'm3': 0.33}

WEIGHTS_BY_STOCK = {
    # 可依需求擴充
}

SIGNAL_SCORE = {'Buy': 1, 'Hold': 0, 'Sell': -1}

LSTM_BASE_URL = 'http://localhost:8001'


def _get_m1_signal(stock_id: str, models=None) -> dict:
    """
    呼叫 LSTM serve.py，將預測價格轉換為 Buy/Sell/Hold。

    `models` 是要納入的 LSTM 模型鍵清單（例：['m02_stacked','m09_technical']）。
    傳多個時取各模型 7 日均價的平均再比對現價——Iteration 31 之前這裡寫死
    m02_stacked，等於「趨勢預測」頁跑的十個模型有九個從來沒進過決策。
    多模型平均**不會**讓它變準（Iteration 11 已證十個模型的 MAE 全落在
    5.17~5.25、天真基準 5.20），但使用者有權選擇要聽誰的。

    **實測表現（Iteration 11，`LSTM/results/m1_rule_backtest.md`）：**
      觸發率 36%、方向準確率 52.12%、單次平均報酬 +1.02%，
      但同期**無條件 7 日平均報酬就是 +1.03%** —— 亦即這條規則的報酬
      完全來自市場 beta，沒有超額報酬；預測變動與實際變動的相關係數僅 +0.05。

    權重處理（Iteration 22，`roles.py`）：趨勢分析師權重由 0.34 降為 0.15，
    理由就是上面那組數字——沒有超額報酬的訊號不該與籌碼、新聞等權。
    Iteration 31 起使用者也能在每頁停用趨勢角色。MODEL-004／005 的
    「投票端處理待決定」到此為止。
    """
    try:
        # 取近期收盤價作為基準
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT close_price FROM stock_daily_prices
                    WHERE stock_id = %s ORDER BY trade_date DESC LIMIT 1
                """, (stock_id,))
                row = cur.fetchone()
        current_price = float(row[0]) if row else None

        # 呼叫 LSTM 預測（7 天）。可指定多個模型，逐一取回後平均
        keys = [k.split(':', 1)[-1] for k in (models or ['m02_stacked'])] or ['m02_stacked']
        predictions, used = [], []
        for mk in keys:
            try:
                resp = requests.get(
                    f'{LSTM_BASE_URL}/model/predict',
                    params={'stock_id': stock_id, 'model': mk, 'days': 7},
                    timeout=15,
                )
                part = resp.json()  # [{"date":..., "predicted_close":...}, ...]
                if isinstance(part, list) and part:
                    predictions.extend(part)
                    used.append(mk)
            except Exception as e:
                logger.warning('[model1/lstm] %s 模型 %s 失敗: %s', stock_id, mk, e)

        if not isinstance(predictions, list) or not predictions or current_price is None:
            return {'stock_id': stock_id, 'signal': 'Hold', 'confidence': 0.0,
                    'reason': 'LSTM 無預測資料'}

        # LSTM API 回傳的欄位是 `predicted_close`。舊版讀 `p.get('predicted')`，
        # 永遠取不到值而回退成 current_price → change_pct 恆為 0.0
        # → **M1 自實作以來永遠輸出 Hold**（同 Iteration 5 的 FinMind volume 欄名 bug）。
        vals = [p.get('predicted_close', p.get('predicted')) for p in predictions]
        vals = [float(v) for v in vals if v is not None]
        if not vals:
            return {'stock_id': stock_id, 'signal': 'Hold', 'confidence': 0.0,
                    'reason': 'LSTM 回傳格式非預期（缺 predicted_close 欄位）'}
        avg_pred = sum(vals) / len(vals)
        change_pct = (avg_pred - current_price) / current_price * 100
        who = '＋'.join(used) if used else 'm02_stacked'

        if change_pct >= 2.0:
            signal, confidence = 'Buy', min(0.5 + change_pct * 0.05, 0.95)
            reason = f'{who} 預測 7 日均價較現價高 {change_pct:.1f}%（現價 {current_price:.1f}）'
        elif change_pct <= -2.0:
            signal, confidence = 'Sell', min(0.5 + abs(change_pct) * 0.05, 0.95)
            reason = f'{who} 預測 7 日均價較現價低 {abs(change_pct):.1f}%（現價 {current_price:.1f}）'
        else:
            signal, confidence = 'Hold', 0.4
            reason = f'{who} 預測價格與現價接近（變動 {change_pct:+.1f}%）'

        return {'stock_id': stock_id, 'signal': signal, 'confidence': round(confidence, 3),
                'reason': reason, 'models_used': used}

    except Exception as e:
        logger.warning('[model1/lstm] %s 呼叫失敗: %s', stock_id, e)
        return {'stock_id': stock_id, 'signal': 'Hold', 'confidence': 0.0,
                'reason': f'LSTM 服務不可用: {str(e)[:60]}'}


_range_cache = {}
_gap_cache = {}


def _get_range_info(stock_id: str) -> dict | None:
    """
    取該股的週振幅預測（波段機會角色用）。

    振幅模型一次算全市場，故整批投票只呼叫一次並快取——
    每檔各算一次會把 24 檔的投票時間拉長數十倍。
    """
    try:
        if not _range_cache:
            import range_model
            res = range_model.predict_ranges()
            if not res.get('available'):
                _range_cache['__none__'] = True
                return None
            for r in res['results']:
                _range_cache[r['stock_id']] = r
        return _range_cache.get(stock_id)
    except Exception as e:
        logger.warning('[voting] 振幅資訊取得失敗：%s', e)
        return None


def _get_gap_info(stock_id: str) -> dict | None:
    """取該股的明日開盤跳空預估（盤前定價角色用）。整批投票只算一次。"""
    try:
        if not _gap_cache:
            import gap_model
            res = gap_model.predict_gaps()
            if not res.get('available'):
                _gap_cache['__none__'] = True
                return None
            for r in res['predictions']:
                _gap_cache[r['stock_id']] = r
        return _gap_cache.get(stock_id)
    except Exception as e:
        logger.warning('[voting] 跳空資訊取得失敗：%s', e)
        return None


def run_vote(stock_id: str, vote_date: date = None, enabled=None) -> dict:
    """
    執行單一股票的角色化投票。

    `enabled` 是使用者選中的模型目錄鍵（見 `model_catalog`）。None 代表用預設集合。
    沒被選中的模型**不呼叫**——這不只是省時間，而是讓「關掉某個模型」真的
    等於「決策時不參考它」，而不是照跑再假裝沒看到。

    Returns: 完整投票結果 dict，並寫入 voting_results 表。
    """
    import model_catalog as cat
    selected = cat.resolve(enabled, 'voting')
    enabled_roles = {cat.CATALOG[k]['role_key'] for k in selected if k in cat.CATALOG}
    lstm_keys = [k for k in selected if k.startswith('lstm:')]
    if vote_date is None:
        vote_date = date.today()

    weights = WEIGHTS_BY_STOCK.get(stock_id, WEIGHTS_DEFAULT)

    m1 = (_get_m1_signal(stock_id, models=lstm_keys or None) if 'trend' in enabled_roles
          else {'signal': 'Hold', 'confidence': 0.0, 'reason': '趨勢模型已由使用者停用'})
    m2_result = (m2.get_signal(stock_id) if 'news' in enabled_roles
                 else {'signal': 'Hold', 'confidence': 0.0,
                       'reason': '新聞模型已由使用者停用', 'features': {}})
    m3_result = (m3.get_signal(stock_id) if 'chip' in enabled_roles
                 else {'signal': 'Hold', 'confidence': 0.0,
                       'reason': '籌碼模型已由使用者停用'})

    # 風險評估（Iteration 13）——**不參與計分**。
    # M1/M2/M3 回答「買還是賣」，風險模組回答「押多少、停損放哪」，兩者正交。
    # 實測方向預測超越基準 -0.09%（無預測力），波動率預測相關係數 0.606，
    # 故只用後者做風險控管，不讓它變成第四個買賣訊號。
    try:
        import risk_model
        risk = risk_model.get_risk(stock_id)
    except Exception as e:
        logger.warning('[voting] %s 風險評估失敗: %s', stock_id, e)
        risk = {'predicted_vol': None, 'vol_regime': None, 'stop_pct': None,
                'position_pct': None, 'reason': f'風險模組不可用: {str(e)[:60]}'}

    # ── 角色化決策（Iteration 22）────────────────────────────────────────────
    # 舊的三模型等權投票把所有東西都當方向訊號加權平均，包括那些根本
    # 不預測方向的模組。角色化讓每個角色只回答自己能回答的問題：
    # 方向角色投票、條件角色否決、紀律角色覆蓋。
    import roles as role_engine

    holdings = role_engine.load_holdings()
    rng = _get_range_info(stock_id) if 'swing' in enabled_roles else None
    gap_info = _get_gap_info(stock_id) if 'gap' in enabled_roles else None
    liq = _get_liquidity_info(stock_id) if 'liquidity' in enabled_roles else None
    decision = role_engine.decide(
        stock_id, m1, m2_result, m3_result, risk,
        rng=rng, holding=holdings.get(stock_id), gap=gap_info,
        liq=liq, enabled=enabled_roles)
    decision['selected_models'] = selected

    score = decision['score']
    final = decision['final_action']
    # voting_results.final_signal 是三分類（舊欄位、前端與歷史紀錄仍在用）；
    # Reduce／NoAdd 沒有對應的三分類，映射時保守處理
    final_signal = {'Buy': 'Buy', 'Sell': 'Sell', 'Hold': 'Hold',
                    'Reduce': 'Sell', 'NoAdd': 'Hold'}.get(final, 'Hold')

    m2_features = m2_result.get('features', {})

    result = {
        'stock_id':    stock_id,
        'vote_date':   vote_date.isoformat(),
        'm1_signal':   m1['signal'],
        'm2_signal':   m2_result['signal'],
        'm3_signal':   m3_result['signal'],
        'final_signal': final_signal,
        'final_action': final,
        'roles':        decision['roles'],
        'decision_path': decision['decision_path'],
        'target_position_pct': decision['target_position_pct'],
        'holding':      holdings.get(stock_id),
        'range_info':   rng,
        'score':       round(score, 4),
        'weights':     weights,
        'm1_reason':   m1['reason'],
        'm2_reason':   m2_result['reason'],
        'm3_reason':   m3_result['reason'],
        'm1_confidence': m1.get('confidence', 0),
        'm2_confidence': m2_result.get('confidence', 0),
        'm3_confidence': m3_result.get('confidence', 0),
        'm2_features': m2_features,
        # 風險欄位（不影響 final_signal）
        'predicted_vol': risk.get('predicted_vol'),
        'vol_regime':    risk.get('vol_regime'),
        'stop_pct':      risk.get('stop_pct'),
        'position_pct':  risk.get('position_pct'),
        'risk_reason':   risk.get('reason'),
    }

    # 寫入 DB（upsert）
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO voting_results
                        (stock_id, vote_date, m1_signal, m2_signal, m3_signal,
                         final_signal, score, weights, m1_reason, m2_reason, m3_reason,
                         m2_features, predicted_vol, vol_regime, stop_pct,
                         position_pct, risk_reason,
                         roles, final_action, target_position_pct,
                         decision_path, holding_snapshot)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            %s,%s,%s,%s,%s)
                    ON CONFLICT (stock_id, vote_date) DO UPDATE SET
                        m1_signal    = EXCLUDED.m1_signal,
                        m2_signal    = EXCLUDED.m2_signal,
                        m3_signal    = EXCLUDED.m3_signal,
                        final_signal = EXCLUDED.final_signal,
                        score        = EXCLUDED.score,
                        weights      = EXCLUDED.weights,
                        m1_reason    = EXCLUDED.m1_reason,
                        m2_reason    = EXCLUDED.m2_reason,
                        m3_reason    = EXCLUDED.m3_reason,
                        m2_features  = EXCLUDED.m2_features,
                        predicted_vol = EXCLUDED.predicted_vol,
                        vol_regime    = EXCLUDED.vol_regime,
                        stop_pct      = EXCLUDED.stop_pct,
                        position_pct  = EXCLUDED.position_pct,
                        risk_reason   = EXCLUDED.risk_reason,
                        roles               = EXCLUDED.roles,
                        final_action        = EXCLUDED.final_action,
                        target_position_pct = EXCLUDED.target_position_pct,
                        decision_path       = EXCLUDED.decision_path,
                        holding_snapshot    = EXCLUDED.holding_snapshot,
                        created_at   = CURRENT_TIMESTAMP
                """, (
                    stock_id, vote_date,
                    m1['signal'], m2_result['signal'], m3_result['signal'],
                    final_signal, round(score, 4),
                    json.dumps(weights),
                    m1['reason'], m2_result['reason'], m3_result['reason'],
                    json.dumps(m2_features),
                    risk.get('predicted_vol'), risk.get('vol_regime'),
                    risk.get('stop_pct'), risk.get('position_pct'),
                    risk.get('reason'),
                    json.dumps(decision['roles'], ensure_ascii=False),
                    final, decision['target_position_pct'],
                    json.dumps(decision['decision_path'], ensure_ascii=False),
                    json.dumps(holdings.get(stock_id), ensure_ascii=False),
                ))
            conn.commit()
    except Exception as e:
        logger.error('[voting] DB 寫入失敗 %s: %s', stock_id, e)

    logger.info('[voting] %s → %s (score=%.3f) M1=%s M2=%s M3=%s',
                stock_id, final, score, m1['signal'], m2_result['signal'], m3_result['signal'])
    return result


_liq_cache = {}


def _get_liquidity_info(stock_id: str):
    """
    成交量模型的單檔結果（Iteration 31）。

    一次算全市場再快取——批次投票逐檔各算一次會把面板重建 20 幾遍
    （Iteration 22 那次是 23 秒）。
    """
    try:
        if not _liq_cache:
            import volume_model
            res = volume_model.get_liquidity()
            _liq_cache.update(res.get('results') or {})
            _liq_cache.setdefault('__loaded__', True)
        return _liq_cache.get(stock_id)
    except Exception as e:
        logger.warning('[voting] 流動性資訊取得失敗：%s', e)
        return None


def run_vote_batch(stock_ids: list, vote_date: date = None, enabled=None) -> list:
    """
    批次執行多個股票的投票，並在最後做**投組層級的相關性調整**。

    單筆風險建議假設各檔獨立，但 24 檔多為台灣電子股，實測平均相關係數 0.44、
    分散比率僅 1.47。照單筆建議全部下單會使投組日波動達 7.3%，
    遠超 2% 目標——這是 Iteration 13 記在遺留問題裡的缺陷，本迭代補上。

    調整是全體同比例縮放，不改變個股之間的相對大小（相對排序來自波動率預測）。
    """
    results = []
    for sid in stock_ids:
        try:
            results.append(run_vote(sid, vote_date, enabled=enabled))
        except Exception as e:
            logger.error('[voting/batch] %s 失敗: %s', sid, e)

    if len(results) < 2:
        return results

    try:
        import portfolio_risk
        positions = {r['stock_id']: r['position_pct'] / 100.0
                     for r in results if r.get('position_pct')}
        vols = {r['stock_id']: r['predicted_vol']
                for r in results if r.get('predicted_vol')}
        if len(positions) >= 2:
            adj = portfolio_risk.adjust_positions(positions, vols)
            if adj.get('available'):
                _persist_portfolio_adjustment(results, adj, vote_date)
                logger.info('[voting/batch] 投組調整：%d 檔，平均相關 %.2f，'
                            '分散比率 %.2f，縮放 %.2f',
                            adj['n_stocks'], adj['avg_corr'],
                            adj['diversification_ratio'], adj['scale'])
    except Exception as e:
        logger.warning('[voting/batch] 投組相關性調整失敗（保留單筆建議）: %s', e)

    return results


def _persist_portfolio_adjustment(results: list, adj: dict, vote_date: date) -> None:
    """把調整後部位寫回 voting_results，並在 risk_reason 附註調整依據。"""
    vote_date = vote_date or date.today()
    note = f'　【投組調整】{adj["reason"]}'
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in results:
                sid = r['stock_id']
                if sid not in adj['adjusted']:
                    continue
                new_pos = round(adj['adjusted'][sid] * 100, 2)
                r['position_pct_solo'] = r.get('position_pct')
                r['position_pct'] = new_pos
                r['risk_reason'] = (r.get('risk_reason') or '') + note
                cur.execute("""
                    UPDATE voting_results
                       SET position_pct = %s,
                           risk_reason  = %s
                     WHERE stock_id = %s AND vote_date = %s
                """, (new_pos, r['risk_reason'], sid, vote_date))
        conn.commit()
