"""
角色化決策引擎（Iteration 22）
──────────────────────────────
把「三個模型加權投票」改成「六個角色各司其職」。

## 為什麼要分角色，而不只是加更多模型進投票

舊投票引擎有一個結構性問題：它把所有東西都當成方向訊號來加權平均。
但本專案手上的東西根本不是同一類：

  · M1／M2／M3 回答「會漲還是會跌」——而方向已被實測證明不可預測
  · M4 波動率回答「會震多大」——這是唯一驗證出實質預測力的量
  · 振幅模型回答「這週有沒有價差可做」——同樣是量級而非方向
  · 使用者持股回答「你手上有什麼、賺還是賠」——這根本不是預測

把後三者硬塞進方向投票，只會製造出第四、第五個沒有根據的方向訊號
（Iteration 13 就是為了避免這件事，才把風險欄位排除在計分之外）。

角色化的做法是讓它們各自回答**自己能回答的問題**：

    方向角色（有投票權）    趨勢、籌碼、消息面     → 決定 Buy / Sell / Hold
    條件角色（有否決權）    風險控管、波段機會     → 決定要不要出手、押多少
    紀律角色（可覆蓋）      持倉管家              → 停損停利與集中度，直接覆蓋前兩者

## 權重是判斷，不是擬合出來的

方向角色的權重依各模型**已記錄在案的走查證據**設定：

| 角色 | 依據 | 證據 | 權重 |
|------|------|------|------|
| 籌碼 | M3 RF | 買進側 56.87%、平均 3 日 +1.10%（賣出側無 edge，已抑制） | 0.55 |
| 消息面 | M2 規則 | 結構已修正，但權重未經回測（新聞歷史僅數日） | 0.30 |
| 趨勢 | M1 LSTM | **實測等同天真基準**，預測與實際相關僅 +0.05 | 0.15 |

M1 舊版拿 0.34 權重，等於用一個沒有預測力的訊號稀釋掉另外兩個。
現在降到 0.15——**但這是根據證據做的判斷，不是回測出來的最佳值**。
真正該做的是拿掉它；保留低權重是為了讓它的線上紀錄繼續累積
（Iteration 21 的台帳會記錄，日後可以用實測資料而不是判斷來決定）。
"""

import logging

logger = logging.getLogger(__name__)

# ── 角色定義 ──────────────────────────────────────────────────────────────────
# credibility 直接寫進 API 回應並顯示在前端。這不是裝飾——
# 使用者有權知道哪些角色的意見有實測支撐、哪些只是還沒被否證。
ROLES = {
    'trend': {
        'name': '趨勢分析師', 'icon': '📈', 'kind': 'direction', 'weight': 0.15,
        'basis': 'M1 LSTM 價格預測',
        'credibility': 'none',
        'credibility_note': 'Iteration 11 實測等同天真基準（預測與實際變動相關 +0.05），'
                            '權重已降至 0.15，保留僅為累積線上紀錄',
    },
    'chip': {
        'name': '籌碼分析師', 'icon': '🏦', 'kind': 'direction', 'weight': 0.55,
        'basis': 'M3 籌碼 Random Forest',
        'credibility': 'weak',
        'credibility_note': '走查買進側 56.87%、平均 3 日報酬 +1.10%；'
                            '賣出側無 edge 已被模型抑制，故只會投 Buy 或 Hold',
    },
    'news': {
        'name': '消息面分析師', 'icon': '📰', 'kind': 'direction', 'weight': 0.30,
        'basis': 'M2 新聞情緒規則引擎',
        'credibility': 'unvalidated',
        'credibility_note': 'Iteration 10 修正了「22 檔恆同訊號」的結構問題，'
                            '但權重數值仍未經回測（新聞歷史僅數日）',
    },
    'risk': {
        'name': '風險控管', 'icon': '🛡️', 'kind': 'gate', 'weight': 0.0,
        'basis': 'M4 波動率模型',
        'credibility': 'proven',
        'credibility_note': 'Iteration 13 走查相關 0.606、R²(log) 0.483，全面優於 EWMA 基準；'
                            '**不投方向**，只決定押多少與停損放哪',
    },
    'swing': {
        'name': '波段機會', 'icon': '📐', 'kind': 'gate', 'weight': 0.0,
        'basis': '週振幅模型',
        'credibility': 'proven',
        'credibility_note': 'Iteration 19 走查 lift 1.98（預測前 10% 的實際振幅為全體近兩倍）；'
                            '**振幅大不代表會漲**，只回答「有沒有價差可做」',
    },
    'gap': {
        'name': '盤前定價', 'icon': '🌙', 'kind': 'gate', 'weight': 0.0,
        'basis': '台指期夜盤 + 美股隔夜（跳空模型 v2）',
        'credibility': 'proven',
        'credibility_note': 'Iteration 28 走查相關 0.6935、方向準確率 72.24%'
                            '（加入夜盤前為 0.6727／69.92%）。'
                            '**不投方向**——跳空在開盤瞬間發生、事後無法交易，'
                            'Iteration 15 已證實這段資訊對收盤到收盤的漲跌毫無幫助。'
                            '它的用途是告訴你「明天大概開在哪」，據以調整進場價位',
    },
    'liquidity': {
        'name': '流動性把關', 'icon': '💧', 'kind': 'gate', 'weight': 0.0,
        'basis': '成交量預測模型（Iteration 31 新增）',
        'credibility': 'proven',
        'credibility_note': '走查排序相關 0.4823、持續性基準 0.3588，每一折都勝出。'
                            '**不投方向**——它回答的是「這檔吃不吃得下這筆錢」，'
                            '與漲跌無關。量能萎縮時衝擊成本與出場難度都會上升',
    },
    'portfolio': {
        'name': '持倉管家', 'icon': '💼', 'kind': 'discipline', 'weight': 0.0,
        'basis': '使用者持股與成本',
        'credibility': 'rule',
        'credibility_note': '不做任何預測，只執行既定紀律：停損、停利、集中度。'
                            '這是全場唯一不依賴模型的角色，也因此最可靠',
    },
}

SIGNAL_SCORE = {'Buy': 1, 'Hold': 0, 'Sell': -1}

# ── 紀律參數（持倉管家）───────────────────────────────────────────────────────
# 停損距離由風險模組的波動率換算（動態），這裡只放不依賴模型的硬紀律。
TAKE_PROFIT_PCT = 20.0     # 浮動獲利達此比例 → 建議部分獲利了結
CONCENTRATION_TH = 40.0    # 單一持股佔投組比例上限
MAX_LOSS_PCT = -15.0       # 浮動虧損硬上限（波動率停損失效時的最後防線）


def _role(key, signal, confidence, reason, **extra):
    meta = ROLES[key]
    return {
        'key': key, 'name': meta['name'], 'icon': meta['icon'],
        'kind': meta['kind'], 'weight': meta['weight'], 'basis': meta['basis'],
        'credibility': meta['credibility'],
        'credibility_note': meta['credibility_note'],
        'signal': signal, 'confidence': round(float(confidence or 0), 3),
        'reason': reason, **extra,
    }


# ── 方向角色 ──────────────────────────────────────────────────────────────────
def _trend_role(stock_id, m1):
    return _role('trend', m1.get('signal', 'Hold'), m1.get('confidence', 0),
                 m1.get('reason', ''))


def _chip_role(stock_id, m3):
    return _role('chip', m3.get('signal', 'Hold'), m3.get('confidence', 0),
                 m3.get('reason', ''), engine=m3.get('engine'))


def _news_role(stock_id, m2):
    return _role('news', m2.get('signal', 'Hold'), m2.get('confidence', 0),
                 m2.get('reason', ''), features=m2.get('features', {}))


# ── 條件角色 ──────────────────────────────────────────────────────────────────
def _risk_role(stock_id, risk):
    """
    不投方向，回傳 `max_position_pct` 與 `stop_pct` 供最終決策使用。
    高波動時把方向訊號的門檻拉高——不是因為高波動會跌，
    而是因為同樣的錯誤在高波動下代價更大。
    """
    vol = risk.get('predicted_vol')
    regime = risk.get('vol_regime')
    pos = risk.get('position_pct')
    stop = risk.get('stop_pct')

    if vol is None:
        return _role('risk', 'N/A', 0, '波動率不可用（資料不足或模型未訓練），'
                                       '無法給出部位建議——此時應保守處理',
                     max_position_pct=None, stop_pct=None, vol_regime=None,
                     veto=True, veto_reason='無風險評估時不建議新增部位')

    veto = regime == '高'
    return _role('risk', 'N/A', 0,
                 risk.get('reason', ''),
                 max_position_pct=pos, stop_pct=stop, vol_regime=regime,
                 predicted_vol=vol,
                 veto=veto,
                 veto_reason=('高波動區間：買進門檻提高，部位上限收緊' if veto else None))


def _swing_role(stock_id, rng):
    """
    回答「這週值不值得動手」。振幅太小時，就算方向對也沒有足夠價差
    覆蓋交易成本與滑價——這是唯一有走查支撐的「該不該出手」依據。
    """
    if not rng:
        return _role('swing', 'N/A', 0, '振幅模型不可用，無法判斷本週是否有價差可做',
                     range_pct=None, is_significant=None, veto=False)

    rp = rng.get('range_pct')
    sig = rng.get('is_significant')
    self_ratio = rng.get('self_ratio')
    peer_pct = rng.get('peer_pct')

    # 振幅低於自身歷史中位數 → 本週大概率是盤整，出手的期望價差很薄
    quiet = self_ratio is not None and self_ratio < 0.9
    reason = (f'預測本週振幅 {rp}%'
              + (f'（自身歷史的 {self_ratio:.2f} 倍、同儕第 {peer_pct:.0f} 百分位）'
                 if self_ratio is not None and peer_pct is not None else '')
              + ('；顯著偏大，波段操作有空間' if sig
                 else '；明顯偏小，本週較可能是盤整' if quiet
                 else '；屬一般水準'))
    return _role('swing', 'N/A', 0, reason,
                 range_pct=rp, is_significant=sig, self_ratio=self_ratio,
                 veto=quiet,
                 veto_reason='預測振幅低於自身歷史中位數，價差不足以覆蓋成本' if quiet else None)


def _liquidity_role(stock_id, liq):
    """
    回答「這檔吃不吃得下這筆錢」。**不投方向。**

    否決條件只有一個：預測量能落在訓練期最低的四分之一。此時同樣的單量
    衝擊成本放大、出場也更難——這與「會不會漲」無關，是能不能執行的問題。
    """
    if not liq:
        return _role('liquidity', 'N/A', 0,
                     '成交量模型不可用，無法評估流動性——此時不否決，但也沒有保障',
                     vol_multiple=None, liquidity=None, veto=False)

    mult = liq.get('vol_multiple')
    level = liq.get('liquidity')
    thin = level == 'thin'
    reason = (f'預測未來 5 日均量為目前 20 日均量的 {mult:.2f} 倍'
              + ('；量能明顯萎縮，衝擊成本與出場難度上升' if thin
                 else '；量能放大，執行條件較寬鬆' if level == 'thick'
                 else '；量能接近常態'))
    return _role('liquidity', 'N/A', 0, reason,
                 vol_multiple=mult, liquidity=level,
                 expected_daily_volume=liq.get('expected_daily_volume'),
                 veto=thin,
                 veto_reason='預測量能萎縮至歷史後四分之一，執行成本過高' if thin else None)


def _gap_role(stock_id, gap):
    """
    回答「明天大概開在哪」。**不投方向**。

    跳空發生在開盤那一刻，事後無法交易——所以它不能拿來決定買賣。
    但它決定**買在什麼價位**：預估高開 2% 的股票，用開盤價進場等於先付 2%，
    原本要賺的價差先被吃掉一截。這才是這個角色的作用。
    """
    if not gap:
        return _role('gap', 'N/A', 0,
                     '跳空模型不可用（資料不足或模型未訓練），無法估計開盤價位',
                     gap_pct=None, implied_open=None, veto=False)

    g = gap.get('gap_pct')
    d = gap.get('direction')
    reason = (f'預估明日開盤{d}約 {g:+.2f}%'
              f'（現價 {gap.get("last_close")} → 約 {gap.get("implied_open")}）')
    # 大幅高開會直接吃掉波段價差，值得提醒但不否決——那是部位大小要處理的事
    wide = g is not None and g >= 1.5
    if wide:
        reason += f'；高開幅度已達 {g:.1f}%，以開盤價進場等於先付掉這段價差'
    elif g is not None and g <= -1.5:
        reason += f'；低開 {abs(g):.1f}%，進場成本較昨收便宜，但也代表隔夜有壞消息'
    return _role('gap', 'N/A', 0, reason,
                 gap_pct=g, implied_open=gap.get('implied_open'),
                 veto=False, wide_gap=wide)


# ── 紀律角色 ──────────────────────────────────────────────────────────────────
def _portfolio_role(stock_id, holding, risk, summary):
    """
    唯一不依賴模型的角色。沒有持股時它只回報「空手」——
    但那件事本身就會改變決策：對空手的股票發賣出訊號是沒有意義的。
    """
    if not holding:
        return _role('portfolio', 'N/A', 0,
                     '目前未持有此股票。賣出訊號對空手部位無意義（本系統不做放空），'
                     '故最終決策只在「買進」與「不動」之間',
                     held=False, override=None)

    pnl_pct = holding.get('unrealized_pct')
    weight_pct = holding.get('weight_pct')
    stop_pct = risk.get('stop_pct')
    notes, override = [], None

    if pnl_pct is not None:
        notes.append(f'持有 {holding["shares"]:.0f} 股、成本 {holding["avg_cost"]:.2f}，'
                     f'目前浮動{"獲利" if pnl_pct >= 0 else "虧損"} {abs(pnl_pct):.2f}%')

        # 停損：以風險模組的波動率停損距離為準，並有一條不依賴模型的硬上限
        if stop_pct is not None and pnl_pct <= -abs(stop_pct):
            override = 'Sell'
            notes.append(f'**已跌破停損距離 {stop_pct:.1f}%**（由波動率換算），'
                         f'紀律要求出場——停損的意義就在於不跟它辯論')
        elif pnl_pct <= MAX_LOSS_PCT:
            override = 'Sell'
            notes.append(f'**浮動虧損已達硬上限 {MAX_LOSS_PCT}%**，'
                         f'不論模型怎麼說都該出場')
        elif pnl_pct >= TAKE_PROFIT_PCT:
            override = 'Reduce'
            notes.append(f'浮動獲利已達 {TAKE_PROFIT_PCT}%，建議部分了結，'
                         f'把成本降下來再讓剩下的部位跑')

    if weight_pct is not None and weight_pct > CONCENTRATION_TH:
        notes.append(f'此股佔投組 {weight_pct:.0f}%，超過 {CONCENTRATION_TH:.0f}% 集中度上限；'
                     f'單一標的的個別風險無法靠分散抵銷，不建議再加碼')
        if override is None:
            override = 'NoAdd'

    return _role('portfolio', 'N/A', 0, '；'.join(notes) or '持有中，無紀律訊號觸發',
                 held=True, shares=holding.get('shares'),
                 avg_cost=holding.get('avg_cost'),
                 unrealized_pct=pnl_pct, weight_pct=weight_pct,
                 override=override)


# ── 彙整 ──────────────────────────────────────────────────────────────────────
def decide(stock_id, m1, m2, m3, risk, rng=None, holding=None, summary=None,
           gap=None, liq=None, enabled=None):
    """
    產出角色化決策。

    `enabled` 是啟用的角色鍵集合（由 `model_catalog.resolve` 換算而來）。
    被停用的角色**照樣回傳**，只是標記 `enabled: False`——
    不回傳會讓前端以為那個角色不存在，使用者就看不出自己關掉了什麼。
    停用的方向角色不計入加權（分母也跟著縮小，其餘角色的相對權重自然放大），
    停用的閘門角色不否決。

    Returns {
      'stock_id', 'roles': [...], 'score', 'raw_signal', 'final_action',
      'target_position_pct', 'decision_path': [...]
    }

    `decision_path` 記錄每一步為什麼把訊號改成現在這樣——
    決策系統最怕的是「它說買，但沒人知道為什麼」。
    """
    roles = [
        _trend_role(stock_id, m1),
        _chip_role(stock_id, m3),
        _news_role(stock_id, m2),
        _risk_role(stock_id, risk),
        _swing_role(stock_id, rng),
        _gap_role(stock_id, gap),
        _liquidity_role(stock_id, liq),
        _portfolio_role(stock_id, holding, risk, summary),
    ]
    # 持倉管家不依賴任何模型，永遠啟用——它是唯一不能被關掉的紀律
    on = None if enabled is None else (set(enabled) | {'portfolio'})
    for r in roles:
        r['enabled'] = True if on is None else (r['key'] in on)
    by_key = {r['key']: r for r in roles}

    def active(key):
        """閘門是否生效：既要角色本身啟用，也要它真的投了否決。"""
        r = by_key[key]
        return r['enabled'] and r.get('veto')

    # 1. 方向角色加權（只算啟用的）
    dir_roles = [r for r in roles if r['kind'] == 'direction' and r['enabled']]
    total_w = sum(r['weight'] for r in dir_roles) or 1.0
    score = sum(r['weight'] * SIGNAL_SCORE.get(r['signal'], 0) for r in dir_roles) / total_w
    raw = 'Buy' if score >= 0.30 else 'Sell' if score <= -0.30 else 'Hold'

    if dir_roles:
        detail = '、'.join(f'{r["name"]} {r["signal"]} × {r["weight"]}' for r in dir_roles)
        path = [f'方向角色加權分數 {score:+.3f} → {raw}（{detail}）']
    else:
        # 全部方向角色都被關掉：分數恆為 0，只剩閘門與紀律在運作。
        # 這不是錯誤，但必須講出來——否則畫面會顯示一個沒有任何方向依據的「觀望」
        path = ['所有方向角色都已停用，無方向依據；僅由閘門與紀律決定']
    off = [r['name'] for r in roles if not r['enabled']]
    if off:
        path.append(f'已停用：{"、".join(off)}')

    action = raw

    # 2. 條件角色否決（只擋新增部位，不擋出場——擋住出場是危險的）
    swing, risk_r = by_key['swing'], by_key['risk']
    if action == 'Buy' and active('swing'):
        action = 'Hold'
        path.append(f'波段機會角色否決買進：{swing["veto_reason"]}')
    if action == 'Buy' and active('liquidity'):
        action = 'Hold'
        path.append(f'流動性把關否決買進：{by_key["liquidity"]["veto_reason"]}')
    if action == 'Buy' and active('risk'):
        # 高波動不是不能買，是要更強的理由
        if score < 0.55:
            action = 'Hold'
            path.append(f'風險控管角色否決買進：{risk_r["veto_reason"]}'
                        f'（分數 {score:+.2f} 未達高波動時所需的 +0.55）')
        else:
            path.append(f'高波動但方向分數 {score:+.2f} 夠強，維持買進但收緊部位')

    # 2b. 盤前定價：不改變買賣決定，但要把「進場成本」講清楚
    gap_r = by_key['gap']
    if action == 'Buy' and gap_r['enabled'] and gap_r.get('wide_gap'):
        path.append(f'盤前定價：預估高開 {gap_r["gap_pct"]:.1f}%，'
                    f'以開盤價進場會先付掉這段價差——買進決定不變，'
                    f'但請把它算進成本')

    # 3. 紀律角色覆蓋（最高優先，因為它不依賴任何預測）
    pf = by_key['portfolio']
    override = pf.get('override')
    if not pf.get('held'):
        if action == 'Sell':
            action = 'Hold'
            path.append('持倉管家：未持有此股，賣出訊號無法執行（不做放空）→ 改為觀望')
    else:
        if override == 'Sell':
            action = 'Sell'
            path.append('持倉管家覆蓋：已觸發停損紀律，無論模型訊號為何一律出場')
        elif override == 'Reduce':
            action = 'Reduce' if action != 'Sell' else 'Sell'
            path.append('持倉管家覆蓋：已達停利水位，建議部分了結')
        elif override == 'NoAdd' and action == 'Buy':
            action = 'Hold'
            path.append('持倉管家覆蓋：此股集中度已超過上限，不再加碼')

    # 4. 目標部位
    target = risk_r.get('max_position_pct') if risk_r['enabled'] else None
    if not risk_r['enabled'] and action == 'Buy':
        # 部位大小完全來自風險模組。關掉它就沒有依據可以給——
        # 給一個「預設值」比不給更危險，因為看起來像是有算過
        path.append('風險控管已停用：無部位建議可給（部位大小原本完全由波動率換算）')
    if action in ('Hold', 'NoAdd'):
        target = holding.get('weight_pct') if holding else 0.0
    elif action == 'Sell':
        target = 0.0
    elif action == 'Reduce' and holding:
        target = round((holding.get('weight_pct') or 0) * 0.5, 1)
    elif action == 'Buy' and target is not None and active('risk'):
        target = round(target * 0.5, 1)
        path.append('高波動：目標部位減半')

    return {
        'stock_id': stock_id,
        'roles': roles,
        'score': round(score, 4),
        'raw_signal': raw,
        'final_action': action,
        'target_position_pct': target,
        'decision_path': path,
    }


# ── 持股讀取 ──────────────────────────────────────────────────────────────────
def load_holdings(user_id: int = 1) -> dict:
    """
    回傳 {stock_id: {shares, avg_cost, last_price, unrealized_pct, weight_pct}}。

    weight_pct 是該股市值佔全部持股市值的比例——集中度判斷需要它，
    所以必須一次讀全部，不能單檔查。

    階段 1（多使用者）：持股按 user_id 隔離。排程投票（20:00）沒有登入者，用 admin（id=1）的持股；
    API 端（/cash/plan）由 Node 把登入者的 user_id 傳進來。
    """
    from db.connection import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT h.stock_id, h.shares, h.avg_cost, p.close_price
                      FROM user_holdings h
                      LEFT JOIN LATERAL (
                        SELECT close_price FROM stock_daily_prices
                         WHERE stock_id = h.stock_id AND close_price > 0
                         ORDER BY trade_date DESC LIMIT 1
                      ) p ON TRUE
                     WHERE h.user_id = %s
                """, (int(user_id or 1),))
                rows = cur.fetchall()
    except Exception as e:
        logger.warning('[roles] 持股讀取失敗：%s', e)
        return {}

    out, total = {}, 0.0
    for sid, shares, cost, price in rows:
        shares, cost = float(shares), float(cost)
        price = float(price) if price is not None else None
        mv = shares * price if price is not None else shares * cost
        total += mv
        out[sid] = {'shares': shares, 'avg_cost': cost, 'last_price': price,
                    'market_value': mv,
                    'unrealized_pct': ((price - cost) / cost * 100)
                                      if price is not None and cost else None}
    for v in out.values():
        v['weight_pct'] = (v['market_value'] / total * 100) if total > 0 else None
    return out
