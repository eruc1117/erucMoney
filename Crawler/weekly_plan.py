"""
本週交易計畫（Iteration 22）
────────────────────────────
把角色決策攤成「5 個交易日、每天一個動作」的可執行計畫。

## 這份計畫的地位取決於策略有沒有通過驗證

`UnifiedModel/train_weekly_policy.py` 走查完會在 bundle 裡留下 `deploy` 旗標。
本模組**必須讀它**：

    deploy=True   計畫以「建議」呈現
    deploy=False  計畫以「參考」呈現，並在回應中明白寫出它輸給買進持有多少

目前的實測結果是 **deploy=False**——外樣本 Sortino 0.170、買進持有 0.198。
也就是說這套每日進出的規則，在歷史上還不如「週一買、週五賣」。
這和本專案先前的結論一致（方向不可預測），把它包裝成建議是不誠實的。

## 計畫怎麼產生

進場條件與策略參數完全沿用回測時的定義，訊號一律取自**本週開始前**
的最後一個交易日——週中不重算。這讓計畫在週一早上就完整可讀，
也讓事後檢討有明確的比較基準（計畫 vs 實際）。

已有持倉時計畫的性質不同：不是「要不要進場」，而是「這週怎麼管理它」——
停損價、停利價、以及最晚哪一天必須處理。
"""

import logging
import math
import os
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            '..', 'UnifiedModel', 'saved_models', 'weekly_policy.joblib')

_policy = None
_policy_failed = False

ACTION_LABEL = {
    'Flat': '空手觀望', 'Buy': '買進', 'Hold': '續抱',
    'Sell': '賣出', 'Watch': '觀察', 'Manage': '管理部位',
}


def _load_policy():
    global _policy, _policy_failed
    if _policy is not None or _policy_failed:
        return _policy
    try:
        import joblib
        _policy = joblib.load(_POLICY_PATH)
        logger.info('[weekly] 策略已載入（deploy=%s，trained_at=%s）',
                    _policy.get('deploy'), _policy.get('trained_at'))
    except Exception as e:
        _policy_failed = True
        logger.warning('[weekly] 策略載入失敗：%s', e)
    return _policy


def _week_dates(today: date = None):
    """
    本週的 5 個交易日（以曆日推估，只跳過週末）。

    國定假日不在此處處理——真正的交易日曆要等資料進資料庫才知道，
    而計畫是週一早上就要能看的東西。日期是給人看的參考，
    真正決定執行的是「第幾天」。
    """
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    out, d = [], monday
    while len(out) < 5:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return monday, out


def _signals(stock_id: str) -> dict:
    """取本週開始前的最後一組訊號（籌碼機率、預測振幅、預測日波動）。"""
    sig = {'chip_p': None, 'pred_range': None, 'pred_vol': None, 'missing': []}

    try:
        import model3_chip as m3
        vs = m3._load_versions()
        panel = m3._build_panel_cached()
        if vs and panel is not None and not panel.empty:
            rows = panel[panel['stock_id'] == stock_id]
            if not rows.empty:
                bundle = vs[0][1]
                proba = bundle['model'].predict_proba(
                    rows.iloc[[-1]][bundle['feature_cols']].values)[0]
                buy_idx = [k for k, v in bundle['label_map'].items() if v == 'Buy']
                sig['chip_p'] = float(proba[buy_idx[0] if buy_idx else -1])
    except Exception as e:
        logger.warning('[weekly] 籌碼機率取得失敗：%s', e)
    if sig['chip_p'] is None:
        sig['missing'].append('籌碼機率')

    try:
        import range_model
        res = range_model.predict_ranges([stock_id])
        if res.get('available') and res['results']:
            sig['pred_range'] = res['results'][0]['range_pct'] / 100.0
            sig['range_detail'] = res['results'][0]
    except Exception as e:
        logger.warning('[weekly] 振幅預測取得失敗：%s', e)
    if sig['pred_range'] is None:
        sig['missing'].append('預測振幅')

    try:
        import risk_model
        r = risk_model.get_risk(stock_id)
        sig['pred_vol'] = r.get('predicted_vol')
        sig['risk'] = r
    except Exception as e:
        logger.warning('[weekly] 波動率取得失敗：%s', e)
    if sig['pred_vol'] is None:
        sig['missing'].append('預測波動率')

    return sig


def _last_close(stock_id: str):
    from db.connection import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT close_price, trade_date FROM stock_daily_prices
                     WHERE stock_id = %s AND close_price > 0
                     ORDER BY trade_date DESC LIMIT 1
                """, (stock_id,))
                row = cur.fetchone()
        return (float(row[0]), row[1]) if row else (None, None)
    except Exception:
        return (None, None)


def build_plan(stock_id: str, today: date = None) -> dict:
    """產生（或重算）本週計畫。回傳完整計畫，並寫入 weekly_plans。"""
    policy = _load_policy()
    if policy is None:
        return {'available': False,
                'reason': '週策略尚未訓練（請執行 UnifiedModel/train_weekly_policy.py）'}

    p = policy['params']
    deployed = bool(policy.get('deploy'))
    monday, days = _week_dates(today)
    sig = _signals(stock_id)
    close, close_date = _last_close(stock_id)

    import roles as role_engine
    holdings = role_engine.load_holdings()
    holding = holdings.get(stock_id)

    # 進場條件——與回測時完全相同的三個門檻，否則線上與驗證是兩件事
    checks = [
        ('籌碼機率', sig['chip_p'], p['buy_th'], 'gte'),
        ('預測振幅', sig['pred_range'], p['range_min'], 'gte'),
        ('預測日波動', sig['pred_vol'], p['vol_max'], 'lte'),
    ]
    failed = []
    for name, val, th, op in checks:
        if val is None:
            failed.append(f'{name}不可用')
        elif op == 'gte' and val < th:
            failed.append(f'{name} {val:.3f} < 門檻 {th}')
        elif op == 'lte' and val > th:
            failed.append(f'{name} {val:.3f} > 上限 {th}')
    entry_ok = not failed

    vol = sig['pred_vol']
    stop_dist = (p['stop_sigma'] * vol * math.sqrt(p['max_hold'])) if vol else None
    take_dist = (p['take_r'] * stop_dist) if stop_dist else None

    e = int(p['entry_day'])
    exit_day = min(e + int(p['max_hold']), 4)
    plan_days = []

    if holding:
        # 已持倉：這週的問題不是要不要買，而是怎麼管理
        cost = holding['avg_cost']
        stop_px = round(cost * (1 - stop_dist), 2) if stop_dist else None
        take_px = round(cost * (1 + take_dist), 2) if take_dist else None
        for i, d in enumerate(days):
            plan_days.append({
                'day': i + 1, 'date': d.isoformat(),
                'action': 'Manage',
                'label': '管理部位',
                'reason': (f'續抱；跌破 {stop_px} 出場、觸及 {take_px} 減碼'
                           if stop_px else '續抱（無風險評估，建議自行設停損）'),
            })
        summary = (f'已持有 {holding["shares"]:.0f} 股（成本 {cost:.2f}）。'
                   f'本週以停損 {stop_px}／停利 {take_px} 管理，不新增部位。')
    elif entry_ok:
        for i, d in enumerate(days):
            if i < e:
                act, reason = 'Flat', '尚未到進場日，空手等待'
            elif i == e:
                act = 'Buy'
                reason = (f'進場：籌碼機率 {sig["chip_p"]:.2f} ≥ {p["buy_th"]}、'
                          f'預測振幅 {sig["pred_range"]:.2%} ≥ {p["range_min"]:.0%}、'
                          f'預測波動 {sig["pred_vol"]:.2%} ≤ {p["vol_max"]:.1%}')
            elif i < exit_day:
                act = 'Hold'
                reason = (f'續抱；跌破 −{stop_dist:.1%} 停損、'
                          f'漲抵 +{take_dist:.1%} 停利' if stop_dist else '續抱')
            elif i == exit_day:
                act, reason = 'Sell', f'持滿 {p["max_hold"]} 個交易日，收盤出場'
            else:
                act, reason = 'Flat', '已出場，空手'
            plan_days.append({'day': i + 1, 'date': d.isoformat(),
                              'action': act, 'label': ACTION_LABEL[act], 'reason': reason})
        entry_px = close
        summary = (f'第 {e + 1} 個交易日收盤進場、第 {exit_day + 1} 日出場；'
                   + (f'停損 {entry_px * (1 - stop_dist):.2f}、'
                      f'停利 {entry_px * (1 + take_dist):.2f}（以最新收盤 {entry_px:.2f} 估）'
                      if entry_px and stop_dist else ''))
    else:
        for i, d in enumerate(days):
            plan_days.append({'day': i + 1, 'date': d.isoformat(),
                              'action': 'Flat', 'label': '空手觀望',
                              'reason': '進場條件未滿足：' + '；'.join(failed)})
        summary = '本週不進場：' + '；'.join(failed)

    plan = {
        'available': True,
        'stock_id': stock_id,
        'week_start': monday.isoformat(),
        'generated_on': (close_date.isoformat() if close_date else None),
        'deployed': deployed,
        # 這段文字會直接顯示在前端。策略沒通過驗證時，使用者有權當場看到。
        'status_note': (
            '此策略已通過走查驗證，可作為建議' if deployed else
            f'**此策略未通過走查驗證**（外樣本 Sortino '
            f'{policy.get("walk_forward_sortino", float("nan")):.3f}，'
            f'買進持有 {policy.get("buy_hold_sortino", float("nan")):.3f}）。'
            '亦即這套每日進出規則在歷史上還不如「週一買、週五賣」，'
            '以下計畫僅供參考，不建議照做。'),
        'policy': p,
        'signals': {k: sig.get(k) for k in ('chip_p', 'pred_range', 'pred_vol')},
        'signals_missing': sig['missing'],
        'entry_ok': entry_ok,
        'blocked_by': failed,
        'holding': holding,
        'summary': summary,
        'days': plan_days,
        'costs_note': ('回測未計入交易成本。台股來回手續費加證交稅約 0.44%，'
                       '任何低於此的平均單筆報酬實際上是虧的。'),
    }
    _persist(plan)
    return plan


def _persist(plan: dict) -> None:
    import json
    from db.connection import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO weekly_plans
                        (stock_id, week_start, generated_on, policy_version, days, expected)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (stock_id, week_start) DO UPDATE SET
                        generated_on = EXCLUDED.generated_on,
                        policy_version = EXCLUDED.policy_version,
                        days = EXCLUDED.days,
                        expected = EXCLUDED.expected,
                        created_at = CURRENT_TIMESTAMP
                """, (
                    plan['stock_id'], plan['week_start'],
                    plan['generated_on'] or plan['week_start'],
                    f"deploy={plan['deployed']}",
                    json.dumps(plan['days'], ensure_ascii=False),
                    json.dumps({'signals': plan['signals'], 'policy': plan['policy'],
                                'entry_ok': plan['entry_ok'],
                                'blocked_by': plan['blocked_by']}, ensure_ascii=False),
                ))
            conn.commit()
    except Exception as e:
        logger.warning('[weekly] 計畫寫入失敗：%s', e)
