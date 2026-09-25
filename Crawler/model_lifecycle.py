"""
模型生命週期：線上實測評估與自動凍結（Iteration 21）
──────────────────────────────────────────────────
從 `model_predictions` 已回填的紀錄算出每個版本的**線上**表現，
並判定 candidate 是否夠格凍結為長期服役版本。

## 為什麼基準是「多數類別」而不是「明日＝今日」

方向預測的天真基準常被寫成「明日＝今日」，但那個基準**沒有方向**
（預測變動為零，既不算猜漲也不算猜跌），拿它算方向準確率是無意義的。

真正的天真基準是**多數類別**：一律猜漲能拿到多少分。台股長期上漲日
略多於下跌日，所以「一律猜漲」本身就有 50% 以上的準確率——
一個 52% 的模型看起來像有 edge，實際上可能連一律猜漲都不如。

基準率是**在同一批已到期樣本上**現算的，不是寫死的常數，
因此不會因為評估期間剛好是多頭或空頭而失真。

## 門檻

    MIN_SAMPLES     樣本數下限。太少的樣本再高的準確率都是雜訊
    MIN_MARGIN      須超越基準的幅度。Iteration 20 的教訓：
                    沒有 margin 的門檻等於沒有門檻
    MAX_P_VALUE     單尾二項檢定。margin 擋得住小幅雜訊，
                    但擋不住「樣本剛好夠、剛好多對三個百分點」

三個條件**同時**成立才自動凍結。任一不成立則維持 candidate，
使用者仍可在前端手動凍結（那是使用者的判斷，不是模型的成績）。

## 一個必須誠實面對的限制

自動凍結本質上是「在多個版本中挑表現最好的那個」，而反覆挑選會
**系統性高估**被選中者的真實表現（多重比較）。門檻擋得住單次雜訊，
擋不住挑了二十次才過關的那一次。因此：

  · 每個版本的 `evaluations` 次數會記在 live_metrics 裡
  · 前端會顯示「這是第幾次評估」——挑了很多次才過的，請自行打折

用法：
    python model_lifecycle.py                # 評估所有版本，符合條件者自動凍結
    python model_lifecycle.py --report-only  # 只印報表不凍結
    python model_lifecycle.py --type range
"""

import argparse
import logging

import model_registry as registry

logger = logging.getLogger(__name__)

# ── 自動凍結門檻 ──────────────────────────────────────────────────────────────
MIN_SAMPLES = 100          # 已到期預測筆數下限
MIN_MARGIN = 0.03          # 方向準確率須高出多數類別基準 3 個百分點
MAX_P_VALUE = 0.05         # 單尾二項檢定顯著水準

# 純量級預測（振幅／波動率）沒有方向可言，改用排序能力把關
MIN_RANK_CORR = 0.20       # 預測與實際的 Spearman 排序相關下限
MIN_RANK_MARGIN = 0.02     # 且須高出同時記下的天真基準

DIRECTIONAL_KINDS = {'close', 'us_close', 'gap', 'signal'}

FETCH_SQL = """
SELECT v.id, v.model_type, v.version, v.status, v.is_serving, v.target_kind,
       v.live_metrics,
       p.stock_id, p.ref_value, p.predicted_value, p.baseline_value,
       p.actual_value, p.ci_low, p.ci_high
  FROM model_versions v
  LEFT JOIN model_predictions p
         ON p.model_version_id = v.id AND p.actual_value IS NOT NULL
 WHERE (%s IS NULL OR v.model_type = %s)
 ORDER BY v.model_type, v.version
"""


# ── 統計小工具（避免為了兩個函式綁死 scipy）───────────────────────────────────
def _spearman(a, b):
    n = len(a)
    if n < 3:
        return None

    def ranks(xs):
        order = sorted(range(n), key=lambda i: xs[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((ra[i] - ma) * (rb[i] - mb) for i in range(n))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((x - mb) ** 2 for x in rb) ** 0.5
    return num / (da * db) if da and db else None


def _binom_p(successes: int, n: int, p0: float) -> float:
    """單尾二項檢定 P(X >= successes | p0)。"""
    if n == 0:
        return 1.0
    p0 = min(max(p0, 1e-6), 1 - 1e-6)
    try:
        from scipy.stats import binomtest
        return float(binomtest(successes, n, p0, alternative='greater').pvalue)
    except Exception:
        # 常態近似後備（scipy 不可用時）
        import math
        mu, sd = n * p0, (n * p0 * (1 - p0)) ** 0.5
        if sd == 0:
            return 1.0
        z = (successes - 0.5 - mu) / sd
        return 0.5 * math.erfc(z / math.sqrt(2))


# ── 指標計算 ──────────────────────────────────────────────────────────────────
def _direction(pred, actual, ref, kind):
    """回傳 (預測方向, 實際方向)，各為 +1 / −1 / 0（0 代表棄權或無變動）。"""
    if kind == 'gap':
        base = 0.0
    elif kind == 'signal':
        # signal 的 predicted_value 直接就是 +1 買 / −1 賣 / 0 觀望
        pd_ = 1 if pred > 0.5 else (-1 if pred < -0.5 else 0)
        ad = 1 if actual > 0 else (-1 if actual < 0 else 0)
        return pd_, ad
    else:
        base = ref if ref is not None else 0.0
    pd_ = 1 if pred > base else (-1 if pred < base else 0)
    ad = 1 if actual > base else (-1 if actual < base else 0)
    return pd_, ad


def compute_metrics(kind: str, rows: list) -> dict:
    """
    rows: [(ref, pred, baseline, actual, ci_low, ci_high), ...]（皆已到期）
    """
    n = len(rows)
    out = {'n': n, 'target_kind': kind}
    if n == 0:
        return out

    preds = [float(r[1]) for r in rows]
    actuals = [float(r[3]) for r in rows]

    # 誤差：模型 vs 同時記下的天真基準
    out['mae'] = sum(abs(p - a) for p, a in zip(preds, actuals)) / n
    based = [(float(r[2]), float(r[3])) for r in rows if r[2] is not None]
    out['baseline_mae'] = (sum(abs(b - a) for b, a in based) / len(based)
                           if based else None)
    out['baseline_n'] = len(based)

    # 信賴區間命中率（有記 CI 才算）
    ci = [r for r in rows if r[4] is not None and r[5] is not None]
    if ci:
        hit = sum(1 for r in ci if float(r[4]) <= float(r[3]) <= float(r[5]))
        out['ci_hit_rate'] = hit / len(ci)
        out['ci_n'] = len(ci)

    if kind in DIRECTIONAL_KINDS:
        pairs = []
        for ref, pred, _b, actual, _l, _h in rows:
            pd_, ad = _direction(float(pred), float(actual),
                                 float(ref) if ref is not None else None, kind)
            if pd_ == 0 or ad == 0:
                continue                      # 模型棄權或實際無變動，不計入
            pairs.append((pd_, ad))
        m = len(pairs)
        out['direction_n'] = m
        if m > 0:
            correct = sum(1 for pd_, ad in pairs if pd_ == ad)
            up = sum(1 for _pd, ad in pairs if ad > 0)
            # 多數類別基準：一律猜漲 vs 一律猜跌，取高者
            base_rate = max(up, m - up) / m
            out['direction_acc'] = correct / m
            out['baseline_direction_acc'] = base_rate
            out['margin'] = out['direction_acc'] - base_rate
            out['p_value'] = _binom_p(correct, m, base_rate)
    else:
        out['rank_corr'] = _spearman(preds, actuals)
        if based:
            out['baseline_rank_corr'] = _spearman([b for b, _ in based],
                                                  [a for _, a in based])

    return out


def _gate(metrics: dict) -> tuple:
    """回傳 (是否通過, 說明)。"""
    kind = metrics.get('target_kind')
    n = metrics.get('n', 0)
    if n < MIN_SAMPLES:
        return False, f'已到期樣本 {n} 筆，未達 {MIN_SAMPLES} 筆下限'

    if kind in DIRECTIONAL_KINDS:
        if metrics.get('direction_acc') is None:
            return False, '無可判定方向的樣本'
        # 棄權（Hold／平盤）不計入方向準確率，所以要另外檢查「真正出手的次數」。
        # 否則一個 95% 時間都觀望的模型，可以靠 5 次全中就取得凍結資格。
        dn = metrics.get('direction_n', 0)
        if dn < MIN_SAMPLES:
            return False, (f'實際出手 {dn} 次（共 {n} 筆），未達 {MIN_SAMPLES} 次下限'
                           '——棄權不計入方向準確率')
        acc = metrics['direction_acc']
        base = metrics['baseline_direction_acc']
        margin = metrics['margin']
        p = metrics['p_value']
        if margin < MIN_MARGIN:
            return False, (f'方向準確率 {acc:.2%}，多數類別基準 {base:.2%}，'
                           f'差距 {margin:+.2%} 未達 {MIN_MARGIN:.0%} 門檻')
        if p > MAX_P_VALUE:
            return False, (f'差距 {margin:+.2%} 達標，但單尾二項檢定 p={p:.3f} '
                           f'> {MAX_P_VALUE}，尚無法排除雜訊')
        return True, (f'方向準確率 {acc:.2%} vs 基準 {base:.2%}'
                      f'（{margin:+.2%}，p={p:.4f}，n={metrics["direction_n"]}）')

    rc = metrics.get('rank_corr')
    brc = metrics.get('baseline_rank_corr')
    if rc is None:
        return False, '樣本不足以計算排序相關'
    if rc < MIN_RANK_CORR:
        return False, f'排序相關 {rc:.3f} 未達 {MIN_RANK_CORR} 門檻'
    if brc is not None and rc - brc < MIN_RANK_MARGIN:
        return False, (f'排序相關 {rc:.3f}，天真基準 {brc:.3f}，'
                       f'差距 {rc - brc:+.3f} 未達 {MIN_RANK_MARGIN}')
    mae, bmae = metrics.get('mae'), metrics.get('baseline_mae')
    if bmae is not None and mae >= bmae:
        return False, f'MAE {mae:.4f} 未優於天真基準 {bmae:.4f}'
    return True, (f'排序相關 {rc:.3f}'
                  + (f' vs 基準 {brc:.3f}' if brc is not None else '')
                  + f'，MAE {mae:.4f}'
                  + (f' vs {bmae:.4f}' if bmae is not None else ''))


# ── 主流程 ────────────────────────────────────────────────────────────────────
def evaluate_all(model_type: str = None) -> list:
    """回傳每個版本的線上指標與凍結判定（不做任何寫入）。"""
    from db.connection import get_conn
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(FETCH_SQL, (model_type, model_type))
            rows = cur.fetchall()

    versions, order = {}, []
    for (vid, mtype, ver, status, serving, kind, live,
         sid, ref, pred, base, actual, cl, ch) in rows:
        if vid not in versions:
            versions[vid] = {
                'id': vid, 'model_type': mtype, 'version': ver,
                'status': status, 'is_serving': serving,
                'target_kind': kind, 'live_metrics': live, 'rows': [],
            }
            order.append(vid)
        if actual is not None:
            versions[vid]['rows'].append((ref, pred, base, actual, cl, ch))

    out = []
    for vid in order:
        v = versions[vid]
        metrics = compute_metrics(v['target_kind'], v.pop('rows'))
        passed, note = _gate(metrics)
        # 只有 candidate 有「自動凍結」這件事可談
        v.update({'metrics': metrics,
                  'gate_passed': passed and v['status'] == 'candidate',
                  'gate_note': note})
        out.append(v)
    return out


def run(model_type: str = None, report_only: bool = False) -> dict:
    import json
    results = evaluate_all(model_type)
    frozen = []

    for v in results:
        if not v['gate_passed'] or report_only:
            continue
        prev = v.get('live_metrics') or {}
        evaluations = int(prev.get('evaluations', 0)) + 1
        payload = dict(v['metrics'])
        payload['evaluations'] = evaluations
        payload['gate_note'] = v['gate_note']
        res = registry.freeze(v['model_type'], reason='auto',
                              note=v['gate_note'], live_metrics=payload)
        if res.get('ok'):
            frozen.append({'model_type': v['model_type'],
                           'version': v['version'], 'note': v['gate_note']})
            logger.info('[lifecycle] 自動凍結 %s v%s：%s',
                        v['model_type'], v['version'], v['gate_note'])
        else:
            logger.warning('[lifecycle] %s 凍結失敗：%s',
                           v['model_type'], res.get('reason'))

    # 未凍結者也把當下指標記下來，前端才有東西看、也才數得出評估次數
    if not report_only:
        from db.connection import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                for v in results:
                    if any(f['model_type'] == v['model_type'] and
                           f['version'] == v['version'] for f in frozen):
                        continue
                    prev = v.get('live_metrics') or {}
                    payload = dict(v['metrics'])
                    payload['evaluations'] = int(prev.get('evaluations', 0)) + 1
                    payload['gate_note'] = v['gate_note']
                    cur.execute('UPDATE model_versions SET live_metrics = %s WHERE id = %s',
                                (json.dumps(payload), v['id']))
            conn.commit()

    return {'evaluated': len(results), 'frozen': frozen, 'results': results}


def _print_report(results):
    print(f'\n{"類型":<22}{"版本":>4} {"狀態":<10}{"樣本":>6} {"主指標":>28}  判定')
    print('─' * 110)
    for v in results:
        m = v['metrics']
        if m['n'] == 0:
            main = '（尚無已到期預測）'
        elif 'direction_acc' in m:
            main = (f"方向 {m['direction_acc']:.2%} / 基準 {m['baseline_direction_acc']:.2%}"
                    f" ({m['margin']:+.2%})")
        elif m.get('rank_corr') is not None:
            main = f"排序相關 {m['rank_corr']:.3f}"
        else:
            main = '—'
        status = v['status'] + ('/服役' if v['is_serving'] else '')
        mark = '✔ 可凍結' if v['gate_passed'] else v['gate_note']
        print(f"{v['model_type']:<22}{v['version']:>4} {status:<10}{m['n']:>6} "
              f"{main:>28}  {mark}")
    print()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    ap = argparse.ArgumentParser(description='模型線上實測評估與自動凍結')
    ap.add_argument('--type', default=None, help='只評估指定 model_type')
    ap.add_argument('--report-only', action='store_true', help='只印報表，不執行凍結')
    args = ap.parse_args()

    res = run(model_type=args.type, report_only=args.report_only)
    _print_report(res['results'])
    if args.report_only:
        print('（--report-only：未執行任何凍結）')
    elif res['frozen']:
        for f in res['frozen']:
            print(f"已凍結 {f['model_type']} v{f['version']} → {f['note']}")
    else:
        print('本次無版本達到自動凍結門檻。')
