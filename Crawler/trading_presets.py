"""
交易策略範本（Iteration 79）：十種常見的規則式策略，給條件規則模擬（trading_strategy）用；
前端「模板」按鈕與「比較全部策略」都從這裡拿，前端不再自己寫一份。

為什麼放後端：Iteration 61 的六個模板寫死在 RuleBuilder.jsx，沒有測試、兩個前端各一份；
搬到這裡之後 tests 能用合成行情（不連庫）驗每一種策略「照定義會做什麼」，
API 也能一次把全部範本套在同一檔、同一期間跑完給比較表。

範本裡買進金額寫成「資金的比例」（then.frac），build() 依使用者的資金換成元；
起始日買進的規則寫 '@start'，build() 換成期間起始日。其他欄位和 trading_strategy 的規則一樣。
這些策略只是「常見做法」的定義，不是任何推薦；比較表是事後結果、不是對未來的預測（caveat 會寫）。
"""
from datetime import date

import synthetic_market as sm
import trading_strategy as st

START_TOKEN = '@start'


def _buy(frac: float) -> dict:
    return {'side': 'buy', 'frac': frac, 'unit': '元'}


SELL_ALL = {'side': 'sell', 'unit': '全部'}

PRESETS = [
    {'key': 'buyhold', 'label': '買進持有', 'hint': '起始日買 50%，之後不動（對照組）', 'rules': [
        {'when': {'type': 'on_date', 'date': START_TOKEN}, 'then': _buy(0.5), 'max_times': 1, 'only_if_flat': False}]},
    {'key': 'dca', 'label': '定期定額', 'hint': '每月 5 日買 1.5%（約 5 年半把資金投完）', 'rules': [
        {'when': {'type': 'monthly_day', 'd': 5}, 'then': _buy(0.015), 'max_times': None, 'only_if_flat': False}]},
    {'key': 'ma20', 'label': '均線進出', 'hint': '向上穿過 20 日均線買 10%，跌破就賣光', 'rules': [
        {'when': {'type': 'cross_above_ma', 'n': 20}, 'then': _buy(0.10), 'max_times': None, 'only_if_flat': True},
        {'when': {'type': 'cross_below_ma', 'n': 20}, 'then': SELL_ALL, 'max_times': None, 'only_if_flat': False}]},
    {'key': 'ma60', 'label': '季線趨勢', 'hint': '向上穿過 60 日均線買 30%，跌破就賣光（比 20 日少進出）', 'rules': [
        {'when': {'type': 'cross_above_ma', 'n': 60}, 'then': _buy(0.30), 'max_times': None, 'only_if_flat': True},
        {'when': {'type': 'cross_below_ma', 'n': 60}, 'then': SELL_ALL, 'max_times': None, 'only_if_flat': False}]},
    {'key': 'stop', 'label': '停損停利', 'hint': '起始日買 30%；比成本低 10% 賣光、高 20% 賣光', 'rules': [
        {'when': {'type': 'on_date', 'date': START_TOKEN}, 'then': _buy(0.30), 'max_times': 1, 'only_if_flat': False},
        {'when': {'type': 'loss_from_cost', 'x': 10}, 'then': SELL_ALL, 'max_times': None, 'only_if_flat': False},
        {'when': {'type': 'gain_from_cost', 'x': 20}, 'then': SELL_ALL, 'max_times': None, 'only_if_flat': False}]},
    {'key': 'dip', 'label': '逢低加碼', 'hint': '每月 5 日買 1%；5 日跌 5% 以上再加 2%（最多 10 次、冷卻 5 日）', 'rules': [
        {'when': {'type': 'monthly_day', 'd': 5}, 'then': _buy(0.01), 'max_times': None, 'only_if_flat': False},
        {'when': {'type': 'change_below', 'n': 5, 'x': -5}, 'then': _buy(0.02), 'max_times': 10, 'only_if_flat': False, 'cooldown': 5}]},
    {'key': 'rsi', 'label': 'RSI 反轉', 'hint': 'RSI(14) < 30 買 10%，> 70 賣光（冷卻 5 日）', 'rules': [
        {'when': {'type': 'rsi_below', 'n': 14, 'x': 30}, 'then': _buy(0.10), 'max_times': None, 'only_if_flat': True, 'cooldown': 5},
        {'when': {'type': 'rsi_above', 'n': 14, 'x': 70}, 'then': SELL_ALL, 'max_times': None, 'only_if_flat': False, 'cooldown': 5}]},
    {'key': 'dcama', 'label': '定投在均線下', 'hint': '每月 5 日 且 前一日收盤在 60 日均線之下 才買 2%（AND）', 'rules': [
        {'when': {'op': 'and', 'conds': [{'type': 'monthly_day', 'd': 5}, {'type': 'below_ma', 'n': 60}]}, 'then': _buy(0.02), 'max_times': None, 'only_if_flat': False}]},
    {'key': 'confirm', 'label': '雙重確認', 'hint': '穿過 20 日均線 且 RSI(14) > 50 才買 10%；跌破 20 日均線 或 比成本低 10% 就賣光', 'rules': [
        {'when': {'op': 'and', 'conds': [{'type': 'cross_above_ma', 'n': 20}, {'type': 'rsi_above', 'n': 14, 'x': 50}]}, 'then': _buy(0.10), 'max_times': None, 'only_if_flat': True},
        {'when': {'op': 'or', 'conds': [{'type': 'cross_below_ma', 'n': 20}, {'type': 'loss_from_cost', 'x': 10}]}, 'then': SELL_ALL, 'max_times': None, 'only_if_flat': False}]},
    {'key': 'breakout', 'label': '動能突破', 'hint': '60 日漲 20% 以上 且 在 20 日均線之上 買 10%；20 日跌 10% 以上 或 比成本低 15% 就賣光', 'rules': [
        {'when': {'op': 'and', 'conds': [{'type': 'change_above', 'n': 60, 'x': 20}, {'type': 'above_ma', 'n': 20}]}, 'then': _buy(0.10), 'max_times': None, 'only_if_flat': True},
        {'when': {'op': 'or', 'conds': [{'type': 'change_below', 'n': 20, 'x': -10}, {'type': 'loss_from_cost', 'x': 15}]}, 'then': SELL_ALL, 'max_times': None, 'only_if_flat': False}]},
]
KEYS = [p['key'] for p in PRESETS]

CAVEAT = ('這十種是常見做法的定義，不是推薦；同一檔、同一期間、同一筆資金下照規則做的事後結果。'
          '總報酬以全部資金算，沒投進去的部分是閒置現金；買進持有是對照組。過去成立不代表未來。')


def _replace_start(w, start: date):
    if st.is_group(w):
        return {'op': w['op'], 'conds': [_replace_start(c, start) for c in w['conds']]}
    return {**w, 'date': str(start)} if w.get('type') == 'on_date' and w.get('date') == START_TOKEN else dict(w)


def build(key: str, stock_id: str, start: date, capital: float) -> list:
    """把範本換成 trading_strategy 的規則：套上股票代號、買進金額 = round(資金 × frac)、'@start' = 起始日。"""
    p = next((p for p in PRESETS if p['key'] == key), None)
    if p is None:
        raise KeyError(f'沒有 {key} 這個範本')
    sid = str(stock_id).strip().upper()
    out = []
    for r in p['rules']:
        t = r['then']
        then = {'side': t['side'], 'qty': max(1, round(float(capital) * t['frac'])), 'unit': t['unit']} if 'frac' in t else dict(t)
        out.append({'stock_id': sid, 'when': _replace_start(r['when'], start), 'then': then,
                    'max_times': r.get('max_times'), 'only_if_flat': bool(r.get('only_if_flat')), 'cooldown': int(r.get('cooldown') or 0)})
    return out


def list_presets(stock_id: str, start: date, capital: float) -> list:
    """給前端的清單：每個範本附已套好的規則與每條的文字。"""
    out = []
    for p in PRESETS:
        rules = build(p['key'], stock_id, start, capital)
        out.append({'key': p['key'], 'label': p['label'], 'hint': p['hint'], 'rules': rules, 'texts': [st.rule_text(r) for r in rules]})
    return out


_METRIC_KEYS = ('total_return', 'bench_return', 'active_return', 'ann_active', 'cagr_port', 'mdd_port', 'mdd_bench', 'monthly_win_rate', 'final_nav')


def compare(stock_id: str, start: date, end: date, capital: float = 1_000_000, source=None) -> dict:
    """同一檔、同一期間、同一筆資金，把全部範本各跑一次，回每個範本的摘要（成交筆數、觸發次數、報酬、回撤、期末）。
    完整的成交與觸發紀錄不回（前端按「套用」再用 /trading/sim/rules 跑那一個）。"""
    src = source or sm.DbSource()
    sid = str(stock_id).strip().upper()
    if end < start or (end - start).days > st.MAX_YEARS * 366:
        return {'available': False, 'reason': f'期間要正向且最多 {st.MAX_YEARS} 年'}
    items, bench = [], None
    for p in PRESETS:
        rules = build(p['key'], sid, start, capital)
        r = st.simulate_rules(rules, start, end, capital, src)
        if not r.get('available'):
            return {'available': False, 'reason': r.get('reason'), 'errors': r.get('errors')}
        m = r.get('metrics') or {}
        if bench is None and m.get('bench_return') is not None:
            bench = m['bench_return']
        items.append({'key': p['key'], 'label': p['label'], 'hint': p['hint'], 'n_rules': len(rules), 'texts': [st.rule_text(x) for x in rules],
                      'trades': len(r['trades']), 'buys': sum(1 for t in r['trades'] if t['side'] == 'buy'), 'sells': sum(1 for t in r['trades'] if t['side'] == 'sell'),
                      'fired': sum(x['fired'] for x in r['rules']), 'missing': r['missing'],
                      'metrics': {k: m.get(k) for k in _METRIC_KEYS}, 'final_value': r['final']['value'], 'final_cash': r['final']['cash'],
                      'realized_pnl': r['realized_pnl'], 'costs': r['costs']})
    return {'available': True, 'stock_id': sid, 'start': str(start), 'end': str(end), 'capital': capital, 'n_presets': len(items),
            'bench_return': bench, 'source': src.describe(), 'items': items,
            'caveat': (sm.SYNTHETIC_CAVEAT + ' ' if src.kind == 'synthetic' else '') + CAVEAT}
