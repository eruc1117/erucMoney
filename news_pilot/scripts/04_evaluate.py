"""
評估抽取結果。

A. 對 gold_60.csv（人工標註）：event_type / direction / is_expected / scope 一致率、magnitude MAE、
   ticker 召回率與精確率、JSON 失敗率（usage_log.csv 的 fail 批次）、兩模型互相一致率。
B. 訊號檢查：magnitude 對上 affected_tickers 在 effective_date 的 |change_rate|，
   看 4–5 分組的平均波動是否明顯高於 1–2 分組（不需要 gold）。

用法：
    python scripts/04_evaluate.py                                  # 預設 data/output/extracted.jsonl
    python scripts/04_evaluate.py --pred data/output/extracted_opus.jsonl --compare data/output/extracted.jsonl
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), 'Crawler'))

THRESH = {'event_type': 0.85, 'direction': 0.85, 'is_expected': 0.80, 'scope': 0.95,
          'magnitude_mae': 0.7, 'ticker_recall': 0.90, 'ticker_precision': 0.85, 'json_fail': 0.05}


def load_jsonl(p):
    return {r['news_id']: r for r in (json.loads(l) for l in open(p, encoding='utf-8') if l.strip())}


def load_gold(p):
    gold = {}
    with open(p, encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if not row.get('event_type'):
                continue
            gold[int(row['news_id'])] = {
                'event_type': row['event_type'].strip(),
                'direction': row['direction'].strip(),
                'magnitude': int(row['magnitude']),
                'is_expected': row['is_expected'].strip().lower() in ('1', 'true', 'y', 'yes', '是'),
                'affected_tickers': [t.strip() for t in row['affected_tickers'].replace(',', ';').split(';') if t.strip()],
                'scope': row['scope'].strip(),
                'category': row.get('category', ''),
            }
    return gold


def agreement(pred, ref, key):
    ids = [i for i in ref if i in pred]
    if not ids:
        return None, 0
    hit = sum(1 for i in ids if pred[i][key] == ref[i][key])
    return hit / len(ids), len(ids)


def report_vs_gold(pred, gold, label):
    print(f'\n== {label} vs 黃金標準（{sum(1 for i in gold if i in pred)} 則） ==')
    for k in ('event_type', 'direction', 'is_expected', 'scope'):
        acc, n = agreement(pred, gold, k)
        if acc is not None:
            flag = 'PASS' if acc >= THRESH[k] else 'FAIL'
            print(f'  {k:12s} 一致率 {acc:6.1%}  (門檻 {THRESH[k]:.0%}) {flag}')
    ids = [i for i in gold if i in pred]
    if ids:
        mae = sum(abs(pred[i]['magnitude'] - gold[i]['magnitude']) for i in ids) / len(ids)
        print(f'  magnitude    MAE    {mae:6.2f}  (門檻 {THRESH["magnitude_mae"]}) {"PASS" if mae <= THRESH["magnitude_mae"] else "FAIL"}')
        tp = fp = fn = 0
        for i in ids:
            p, g = set(pred[i]['affected_tickers']), set(gold[i]['affected_tickers'])
            tp += len(p & g)
            fp += len(p - g)
            fn += len(g - p)
        rec = tp / (tp + fn) if tp + fn else None
        prec = tp / (tp + fp) if tp + fp else None
        if rec is not None:
            print(f'  ticker 召回率 {rec:6.1%}  (門檻 90%) {"PASS" if rec >= 0.9 else "FAIL"}')
        if prec is not None:
            print(f'  ticker 精確率 {prec:6.1%}  (門檻 85%) {"PASS" if prec >= 0.85 else "FAIL"}')
    # 依類別拆
    by_cat = defaultdict(list)
    for i in ids:
        by_cat[pred[i].get('category', '?')].append(i)
    for cat, cids in sorted(by_cat.items()):
        sub = {i: gold[i] for i in cids}
        accs = [agreement(pred, sub, k)[0] for k in ('event_type', 'direction')]
        print(f'  [{cat}] n={len(cids)} event_type {accs[0]:.0%} direction {accs[1]:.0%}')


def report_json_fail(usage_path):
    if not os.path.exists(usage_path):
        return
    rows = list(csv.DictReader(open(usage_path, encoding='utf-8')))
    if not rows:
        return
    fail = sum(1 for r in rows if r['status'] != 'ok') / len(rows)
    tok_in = sum(int(r['input_tokens'] or 0) for r in rows)
    tok_out = sum(int(r['output_tokens'] or 0) for r in rows)
    print(f'\n== 批次 {len(rows)}，JSON 失敗率 {fail:.1%} (門檻 5%) {"PASS" if fail <= 0.05 else "FAIL"}；'
          f'tokens in {tok_in:,} / out {tok_out:,} ==')


def report_signal(pred):
    """magnitude 分組 vs effective_date 的 |change_rate|。"""
    from db.connection import get_conn
    import news_align
    input_rows = load_jsonl(os.path.join(ROOT, 'data', 'input.jsonl'))
    try:
        open_days = news_align.load_open_days('TW')
    except Exception:
        open_days = []
    if not open_days:
        # trading_calendar 尚未建：直接用價格表的交易日
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT DISTINCT trade_date FROM stock_daily_prices WHERE stock_id='0050' ORDER BY 1")
                open_days = [r[0] for r in cur.fetchall()]
    pairs = []
    for i, r in pred.items():
        src = input_rows.get(i)
        if not src:
            continue
        pub = datetime.fromisoformat(src['published_at'])
        eff, _ = news_align.effective_date(pub, open_days, 'TW')
        for tk in r['affected_tickers']:
            if tk.isdigit():
                pairs.append((tk, eff, r['magnitude']))
    if not pairs:
        print('\n（沒有台股 ticker，略過訊號檢查）')
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            groups = defaultdict(list)
            for tk, eff, mag in pairs:
                cur.execute("SELECT change_rate FROM stock_daily_prices WHERE stock_id=%s AND trade_date=%s", (tk, eff))
                row = cur.fetchone()
                if row and row[0] is not None:
                    groups[mag].append(abs(float(row[0])))
    print('\n== 訊號檢查：magnitude vs effective_date |報酬| ==')
    for m in sorted(groups):
        v = groups[m]
        print(f'  magnitude {m}: n={len(v):3d}  平均 |ret| {sum(v) / len(v):.2f}%')
    lo = [x for m in (1, 2) for x in groups.get(m, [])]
    hi = [x for m in (4, 5) for x in groups.get(m, [])]
    if lo and hi:
        print(f'  1–2 分 {sum(lo) / len(lo):.2f}%  vs  4–5 分 {sum(hi) / len(hi):.2f}%  '
              f'{"有訊號" if sum(hi) / len(hi) > 1.3 * sum(lo) / len(lo) else "無明顯差異"}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pred', default=os.path.join(ROOT, 'data', 'output', 'extracted.jsonl'))
    ap.add_argument('--gold', default=os.path.join(ROOT, 'data', 'gold_60.csv'))
    ap.add_argument('--compare', default=None, help='另一模型的輸出，算兩者一致率')
    a = ap.parse_args()

    pred = load_jsonl(a.pred)
    print(f'預測 {len(pred)} 則（{a.pred}）')
    if os.path.exists(a.gold):
        gold = load_gold(a.gold)
        if gold:
            report_vs_gold(pred, gold, os.path.basename(a.pred))
        else:
            print('gold 檔存在但沒有已填的列')
    else:
        print('（無 gold_60.csv，略過一致率）')
    if a.compare and os.path.exists(a.compare):
        other = load_jsonl(a.compare)
        print(f'\n== 兩模型一致率（{os.path.basename(a.pred)} vs {os.path.basename(a.compare)}）==')
        for k in ('event_type', 'direction', 'is_expected', 'scope'):
            acc, n = agreement(pred, other, k)
            if acc is not None:
                print(f'  {k:12s} {acc:6.1%} (n={n})')
        ids = [i for i in pred if i in other]
        if ids:
            print(f'  magnitude MAE {sum(abs(pred[i]["magnitude"] - other[i]["magnitude"]) for i in ids) / len(ids):.2f}')
    report_json_fail(os.path.join(os.path.dirname(a.pred), 'usage_log.csv'))
    try:
        report_signal(pred)
    except Exception as e:  # noqa: BLE001
        print(f'\n（訊號檢查失敗：{e}）')


if __name__ == '__main__':
    main()
