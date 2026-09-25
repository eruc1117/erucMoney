"""
閒置資金一週配置（Iteration 26）
────────────────────────────────
需求是「閒置資金，一週內買賣最大化利益」。

## 先講這個功能不能做到什麼

「最大化利益」需要知道哪支會漲多少。本專案已反覆實測**方向不可預測**
（Iteration 11：LSTM 等同天真基準；Iteration 12：超越基準 −0.09%），
而 Iteration 22 把有走查證據的訊號組成每日進出規則之後，
外樣本 Sortino 0.170 仍**輸給**買進持有的 0.198。

所以這個模組**不宣稱能最大化報酬**。它做的是一件可以做到的事：

    在有走查驗證的兩個量（週振幅、波動率）上，
    把有限的資金配置到「單位風險能換到最多價差空間」的標的，
    並確保總風險不超過使用者設定的上限。

換句話說，最大化的是**風險調整後的期望價差空間**，不是預測報酬。
頁面上會照這樣寫，不會包裝成獲利保證。

## 為什麼是振幅而不是漲跌

Iteration 19 的振幅模型走查 lift 1.98——預測振幅前 10% 的股票，
實際振幅是全體平均的近兩倍。振幅大代表**這週有價差可做**，
但**不代表會漲**。所以：

  · 振幅決定「值不值得動用資金」
  · 波動率決定「停損放哪、能押多少」（Iteration 13，相關 0.606）
  · 籌碼機率決定「偏多還是觀望」（走查買進側 56.87%，證據薄弱，權重低）

## 交易成本是這個功能的核心限制，不是附註

台股來回手續費加證交稅約 0.44%，且手續費有最低收費（預設 20 元）。
資金小的時候這件事會直接決定可行性：

    投入 5,000 元，來回成本至少 40 元（兩次最低手續費）+ 證交稅 15 元
    ＝ 1.1%，比多數個股一週的期望價差還高。

所以配置時會**先扣成本再排序**，並拒絕成本佔比過高的部位——
一個扣完成本是負的的建議，不該送到使用者面前。
"""

import logging
import math

logger = logging.getLogger(__name__)

# ── 交易成本（與 Server/lib/tradeLedger.js 同一組預設值）────────────────────
FEE_RATE = 0.001425
FEE_MIN = 20
TAX_RATE = 0.003
SHARES_PER_LOT = 1000

# ── 配置參數 ──────────────────────────────────────────────────────────────────
DEFAULT_RISK_BUDGET = 0.02     # 整週願意承受的資金損失比例（2%）
MAX_WEIGHT = 0.35              # 單一標的佔閒置資金上限
MIN_TICKET = 3000              # 單筆最小投入金額——低於此成本佔比過高
MAX_COST_RATIO = 0.4           # 來回成本不得超過期望價差的 40%
DEFAULT_MAX_POSITIONS = 5      # 預設分散檔數（風險預算先切成這麼多份）
HOLD_DAYS = 5
# 「捕捉率」：預測振幅是高低點的全距，實際能吃到的只是其中一段。
# 0.35 是保守假設（吃到約三分之一），沒有走查支撐——
# 這是一個**假設**，不是量測值，頁面上會標明。
CAPTURE_RATIO = 0.35


def round_trip_cost(amount: float) -> float:
    """一買一賣的總成本（含最低手續費與證交稅）。"""
    buy_fee = max(round(amount * FEE_RATE), FEE_MIN)
    sell_fee = max(round(amount * FEE_RATE), FEE_MIN)
    tax = round(amount * TAX_RATE)
    return float(buy_fee + sell_fee + tax)


def _gap_map(stock_ids=None) -> dict:
    """明日開盤跳空預估（Iteration 28，含台指期夜盤）。取不到就回空字典。"""
    try:
        import gap_model
        res = gap_model.predict_gaps(stock_ids)
        if not res.get('available'):
            return {}
        return {r['stock_id']: r for r in res['predictions']}
    except Exception as e:
        logger.warning('[cash] 跳空預估取得失敗：%s', e)
        return {}


def _liquidity_map(stock_ids=None) -> dict:
    """預測量能（Iteration 31）。取不到就回空字典——沒有流動性資訊時不擋任何股票。"""
    try:
        import volume_model
        return volume_model.get_liquidity(stock_ids).get('results') or {}
    except Exception as e:
        logger.warning('[cash] 流動性預估取得失敗：%s', e)
        return {}


def _candidates(stock_ids=None, enabled=None) -> list:
    """
    收集每檔的振幅、波動率、籌碼機率、現價、明日開盤跳空與預測量能。

    `enabled` 是使用者選中的目錄鍵。沒選到的模型不呼叫——這不只是省時間，
    而是讓「關掉某個模型」真的等於「配置時不參考它」，而不是照跑再假裝沒看。
    """
    import range_model
    import risk_model

    on = None if enabled is None else set(enabled)
    def use(key):
        return on is None or key in on

    rng = range_model.predict_ranges(stock_ids)
    if not rng.get('available'):
        return []
    gaps = _gap_map(stock_ids) if use('gap') else {}
    liqs = _liquidity_map(stock_ids) if use('volume') else {}

    out = []
    for r in rng['results']:
        sid = r['stock_id']
        close = r.get('close')
        if not close or close <= 0:
            continue
        try:
            risk = risk_model.get_risk(sid, holding_days=HOLD_DAYS)
        except Exception as e:
            logger.warning('[cash] %s 風險評估失敗：%s', sid, e)
            continue
        stop_pct = risk.get('stop_pct')
        if not stop_pct or stop_pct <= 0:
            continue                      # 沒有停損距離就無法控制風險，直接跳過

        chip_p = _chip_probability(sid) if use('m3_chip') else None
        liq = liqs.get(sid) or {}
        g = gaps.get(sid) or {}
        gap_pct = (float(g['gap_pct']) / 100.0) if g.get('gap_pct') is not None else None
        out.append({
            'stock_id': sid,
            'close': float(close),
            'gap_pct': gap_pct,
            # 明天用開盤價進場的實際成本。高開等於先付掉一段價差，
            # 用昨收估成本會系統性低估——這正是夜盤資料能修正的東西。
            'entry_price': float(close) * (1 + (gap_pct or 0.0)),
            'range_pct': float(r['range_pct']) / 100.0,
            'self_ratio': r.get('self_ratio'),
            'peer_pct': r.get('peer_pct'),
            'is_significant': bool(r.get('is_significant')),
            'stop_pct': float(stop_pct) / 100.0,
            'predicted_vol': risk.get('predicted_vol'),
            'vol_regime': risk.get('vol_regime'),
            'chip_p': chip_p,
            'vol_multiple': liq.get('vol_multiple'),
            'liquidity': liq.get('liquidity'),
            'expected_daily_volume': liq.get('expected_daily_volume'),
        })
    return out


def _chip_probability(stock_id: str):
    """M3 的 Buy 機率；取不到就回 None（該檔以中性看待）。"""
    try:
        import model3_chip as m3
        vs = m3._load_versions()
        panel = m3._build_panel_cached()
        if not vs or panel is None or panel.empty:
            return None
        rows = panel[panel['stock_id'] == stock_id]
        if rows.empty:
            return None
        bundle = vs[0][1]
        proba = bundle['model'].predict_proba(rows.iloc[[-1]][bundle['feature_cols']].values)[0]
        buy_idx = [k for k, v in bundle['label_map'].items() if v == 'Buy']
        return float(proba[buy_idx[0] if buy_idx else -1])
    except Exception:
        return None


# 量能等級 → 效率折扣。thin 打七折是保守的經驗值，不是量測值——
# 真正的衝擊成本要有逐筆成交資料才算得出來，目前沒有。
LIQUIDITY_PENALTY = {'thin': 0.7, 'normal': 1.0, 'thick': 1.05}


def _score(c: dict) -> dict:
    """
    算出每檔的「期望價差空間」與「單位風險效率」。

    期望價差 = 預測振幅 × 捕捉率 × 方向調整
      · 捕捉率是保守假設（見檔頭），不是量測值
      · 方向調整以籌碼機率為準，但**上下限收得很緊**（0.85~1.15）——
        該模型走查只有 56.87%，讓它主導配置是不誠實的
    效率 = 期望價差 ÷ 停損距離　（每承受一單位風險換到多少價差空間）
    """
    p = c.get('chip_p')
    direction = 1.0 if p is None else max(0.85, min(1.15, 0.85 + p * 0.6))
    edge = c['range_pct'] * CAPTURE_RATIO * direction
    # 以開盤價進場時，高開的部分已經先被吃掉：期望價差要扣掉它。
    # 反過來低開會讓進場成本變便宜，等於多出一段空間。
    # 跳空模型走查相關 0.6935、方向 72.24%（Iteration 28），這個修正有依據。
    gap = c.get('gap_pct')
    if gap is not None:
        edge = edge - gap
    c['gap_adjust'] = -(gap or 0.0)
    c['expected_move'] = edge
    c['direction_adj'] = direction
    c['efficiency'] = edge / c['stop_pct'] if c['stop_pct'] > 0 else 0.0

    # 流動性折扣（Iteration 31）。**不動期望價差，只動效率排序**——
    # 量能萎縮不會讓價差變小，它讓你更難用理想價格進出。把它算進成本比
    # 算進報酬誠實：前者是確定會發生的摩擦，後者是猜測。
    lv = c.get('liquidity')
    c['liquidity_penalty'] = LIQUIDITY_PENALTY.get(lv, 1.0)
    c['efficiency'] *= c['liquidity_penalty']
    return c


def _fill(scored: list, amount: float, risk_budget: float, slots: int):
    """把風險預算切成 slots 份，依效率順序填入。回傳 (選中, 被排除)。"""
    risk_left = amount * risk_budget
    cash_left = amount
    picks, rejected = [], []

    for c in scored:
        if len(picks) >= slots:
            break
        remaining = max(1, slots - len(picks))
        # 每檔先分到剩餘風險的等份；前面若有檔位沒用完，會自動流到後面
        budget = min(risk_left / remaining / c['stop_pct'],
                     amount * MAX_WEIGHT, cash_left)
        if budget < MIN_TICKET:
            rejected.append({**_public(c), 'reason':
                             f'可配置金額 {budget:,.0f} 元低於最小單筆 {MIN_TICKET:,} 元'})
            continue

        # 換算成可買股數（優先整張，不足一張才用零股）
        entry = c.get('entry_price') or c['close']
        shares = int(budget // entry)
        if shares <= 0:
            rejected.append({**_public(c), 'reason':
                             f'預估進場價 {entry:.2f} 元，可配置金額買不到 1 股'})
            continue
        lots, odd = divmod(shares, SHARES_PER_LOT)
        cost_basis = shares * entry

        fees = round_trip_cost(cost_basis)
        expected_gain = cost_basis * c['expected_move']
        if expected_gain <= 0 or fees / expected_gain > MAX_COST_RATIO:
            ratio = (fees / expected_gain * 100) if expected_gain > 0 else 999
            rejected.append({**_public(c), 'reason':
                             f'來回成本 {fees:,.0f} 元佔期望價差 {expected_gain:,.0f} 元的 '
                             f'{ratio:.0f}%，超過 {MAX_COST_RATIO:.0%} 上限'})
            continue

        risk_amount = cost_basis * c['stop_pct']
        picks.append({
            **_public(c),
            'shares': shares, 'lots': lots, 'odd_shares': odd,
            'cost_basis': round(cost_basis, 0),
            'weight_pct': round(cost_basis / amount * 100, 1),
            'entry_price': round(entry, 2),
            'stop_price': round(entry * (1 - c['stop_pct']), 2),
            'target_price': round(entry * (1 + max(c['expected_move'], 0)), 2),
            'risk_amount': round(risk_amount, 0),
            'expected_gain': round(expected_gain, 0),
            'round_trip_cost': round(fees, 0),
            'expected_net': round(expected_gain - fees, 0),
        })
        cash_left -= cost_basis
        risk_left -= risk_amount
        if cash_left < MIN_TICKET or risk_left <= 0:
            break
    return picks, rejected


def allocate(amount: float, risk_budget: float = DEFAULT_RISK_BUDGET,
             max_positions: int = DEFAULT_MAX_POSITIONS,
             stock_ids=None, exclude_held: bool = False, enabled=None, user_id: int = 1) -> dict:
    """
    把閒置資金配置到一週的部位上。

    amount        閒置資金（元）
    risk_budget   整週願意承受的資金損失比例（0.02 = 2%）
    max_positions 最多分散幾檔（風險預算會先切成這麼多份）
    exclude_held  是否排除已持有的股票（避免在同一檔上重複押注）
    enabled       啟用的模型目錄鍵；None 代表全用（見 `model_catalog`）
    """
    if not amount or amount <= 0:
        return {'available': False, 'reason': '請輸入大於 0 的閒置資金金額'}

    cands = _candidates(stock_ids, enabled=enabled)
    if not cands:
        return {'available': False,
                'reason': '無法取得振幅或波動率預測（模型未訓練或資料不足）'}

    held = {}
    if exclude_held:
        try:
            import roles
            held = roles.load_holdings(user_id)
        except Exception:
            held = {}

    scored = [_score(c) for c in cands if c['stock_id'] not in held]
    # 效率高的排前面：同樣的風險，先看能換到最多價差空間的
    scored.sort(key=lambda c: -c['efficiency'])

    # **風險預算要先切分再配置，不能貪婪地一檔吃完。**
    # 直接照效率順序填的話，第一檔就會把 2% 的風險用光，
    # 結果是「只買一檔、資金用不到兩成」——既沒有分散，資金效率也差。
    # 本專案實測 24 檔平均相關 0.44、分散比率僅 1.47（Iteration 14），
    # 分散的效果有限但不是沒有，而單押一檔的個別風險完全無法抵銷。
    # 檔數切太細，每一份風險換算出的金額就會低於最小單筆，結果是一檔都配不出來。
    # 與其回一個空清單叫使用者自己調參數，不如自動往下縮到配得出來為止，
    # 並在診斷裡說明「本來想分 5 檔，資金只夠分 2 檔」。
    wanted = max(1, min(max_positions, len(scored)))
    best_stop = min(c['stop_pct'] for c in scored)

    # 檔數切太細時每一份都太小，會被最小單筆或成本佔比擋掉。
    # 與其回一個空清單叫使用者自己調參數，先自動往下縮到配得出東西為止——
    # 「分散 5 檔」是偏好，「至少要能出手」是前提。
    slots = wanted
    picks, rejected = [], []
    while slots >= 1:
        picks, rejected = _fill(scored, amount, risk_budget, slots)
        if picks:
            break
        slots -= 1
    slots = max(slots, 1)

    # ── 診斷：為什麼只投入這麼多、為什麼一檔都配不出來 ──────────────────────
    # 固定風險法下「投入比例 ≈ 風險上限 ÷ 停損距離」是數學必然，
    # 不解釋的話使用者只會看到「30 萬只用了 3 萬」而覺得系統壞了。
    avg_stop = (sum(c['stop_pct'] for c in scored) / len(scored)) if scored else 0
    diagnostics = []
    if avg_stop > 0:
        cap = risk_budget / avg_stop
        diagnostics.append(
            f'目前 {len(scored)} 檔候選的平均停損距離 {avg_stop:.1%}。'
            f'固定風險法下可投入比例 ≈ 風險上限 ÷ 停損距離 = '
            f'{risk_budget:.1%} ÷ {avg_stop:.1%} ≈ {cap:.0%}——'
            f'這是數學上限，不是系統少配。要投入更多只有兩條路：'
            f'提高風險上限，或等波動收斂讓停損距離變窄。')
    if slots < wanted and picks:
        diagnostics.append(
            f'原本要分散 {wanted} 檔，但 {risk_budget:.1%} 的風險預算切成 {wanted} 份之後，'
            f'每份換算出的金額低於最小單筆 {MIN_TICKET:,} 元，已自動縮減為 {slots} 檔。'
            f'分散得愈細、每檔金額愈小，最低手續費的佔比就愈高。')
    if not picks and scored:
        # 說明真正的阻因，不要籠統地叫使用者「調參數」
        cost_blocked = sum(1 for r in rejected if '來回成本' in r['reason'])
        size_blocked = sum(1 for r in rejected if '最小單筆' in r['reason'])
        if cost_blocked >= size_blocked:
            # 最低手續費 20 元 ×2 + 證交稅，要讓成本佔期望價差低於上限所需的單筆金額
            move = max((c['expected_move'] for c in scored), default=0.03)
            denom = MAX_COST_RATIO * move - TAX_RATE
            need_ticket = (FEE_MIN * 2 / denom) if denom > 0 else float('inf')
            diagnostics.append(
                f'配不出任何部位的主因是**交易成本**：每筆金額太小，'
                f'兩次最低手續費（{FEE_MIN} 元 ×2）加證交稅就吃掉期望價差的四成以上。'
                + (f'以目前最好的候選估算，單筆至少要 {need_ticket:,.0f} 元才划算。'
                   if need_ticket < 1e7 else '在目前的期望價差下，任何金額都無法覆蓋成本。'))
        else:
            need = MIN_TICKET * best_stop / amount
            diagnostics.append(
                f'配不出任何部位的主因是**單筆金額不足**：以最小單筆 {MIN_TICKET:,} 元與'
                f'最窄停損 {best_stop:.1%} 計算，風險上限至少要 {need:.2%}'
                f'（目前 {risk_budget:.2%}）。')
        diagnostics.append(
            '這是系統刻意不出手，不是找不到標的——'
            '一筆扣完成本期望為負的交易，不該送到你面前。')

    invested = sum(p['cost_basis'] for p in picks)
    total_risk = sum(p['risk_amount'] for p in picks)
    total_net = sum(p['expected_net'] for p in picks)
    total_cost = sum(p['round_trip_cost'] for p in picks)

    return {
        'available': True,
        'amount': round(amount, 0),
        'risk_budget_pct': round(risk_budget * 100, 2),
        'max_positions': max_positions,
        'picks': picks,
        'rejected': rejected[:12],
        'diagnostics': diagnostics,
        'summary': {
            'n_picks': len(picks),
            'invested': round(invested, 0),
            'idle_left': round(amount - invested, 0),
            'invested_pct': round(invested / amount * 100, 1) if amount else 0,
            'total_risk': round(total_risk, 0),
            'total_risk_pct': round(total_risk / amount * 100, 2) if amount else 0,
            'total_cost': round(total_cost, 0),
            'expected_net': round(total_net, 0),
            'expected_net_pct': round(total_net / amount * 100, 2) if amount else 0,
        },
        'assumptions': {
            'capture_ratio': CAPTURE_RATIO,
            'hold_days': HOLD_DAYS,
            'fee_rate': FEE_RATE, 'fee_min': FEE_MIN, 'tax_rate': TAX_RATE,
            'max_weight_pct': MAX_WEIGHT * 100,
            'min_ticket': MIN_TICKET,
            'max_positions': max_positions,
        },
        'honesty': [
            '這裡最大化的是**風險調整後的期望價差空間**，不是預測報酬。'
            '本專案已反覆實測方向不可預測（Iteration 11、12），'
            'Iteration 22 的每日進出策略走查也輸給買進持有，故不做獲利宣稱。',
            f'期望價差 = 預測振幅 × 捕捉率 {CAPTURE_RATIO}。'
            '**捕捉率是保守假設，不是量測值**——實際能吃到振幅的多少沒有走查支撐。',
            '振幅模型（走查 lift 1.98）只回答「這週會不會震」，不回答「會不會漲」。'
            '方向側只用籌碼機率做 0.85~1.15 的微調，因為該模型走查僅 56.87%。',
            '所有金額都已扣除來回手續費與證交稅（含最低收費）。'
            f'單筆低於 {MIN_TICKET:,} 元或成本佔期望價差超過 {MAX_COST_RATIO:.0%} 者一律不建議。',
            '停損價由波動率模型換算（Iteration 13，走查相關 0.606），'
            '是這份配置裡證據最強的一環——它決定的是虧損上限，不是獲利。',
            '進場價已用明日開盤跳空預估修正（Iteration 28，含台指期夜盤，'
            '走查相關 0.6935、方向準確率 72.24%）：高開會先吃掉一段價差，'
            '用昨收估成本會系統性低估。',
        ],
    }


def _public(c: dict) -> dict:
    return {
        'stock_id': c['stock_id'], 'close': c['close'],
        'range_pct': round(c['range_pct'] * 100, 2),
        'self_ratio': c.get('self_ratio'), 'peer_pct': c.get('peer_pct'),
        'is_significant': c.get('is_significant'),
        'gap_pct': round(c['gap_pct'] * 100, 2) if c.get('gap_pct') is not None else None,
        'gap_adjust_pct': round(c.get('gap_adjust', 0) * 100, 2),
        'stop_pct': round(c['stop_pct'] * 100, 2),
        'vol_regime': c.get('vol_regime'),
        'chip_p': round(c['chip_p'], 3) if c.get('chip_p') is not None else None,
        'expected_move_pct': round(c.get('expected_move', 0) * 100, 2),
        'efficiency': round(c.get('efficiency', 0), 3),
        # 流動性（Iteration 31）。模型停用或不可用時為 None，
        # 前端據此顯示「未參考」而不是假裝量能正常
        'vol_multiple': c.get('vol_multiple'),
        'liquidity': c.get('liquidity'),
        'expected_daily_volume': c.get('expected_daily_volume'),
        'liquidity_penalty': c.get('liquidity_penalty'),
    }
