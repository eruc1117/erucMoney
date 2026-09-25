"""
跑全部模型的季度 walk-forward，寫排行榜與報告（每完成一個模型就重寫，中途看得到）。

    venv/Scripts/python run_all.py                       # 全部模型、標籤 y1
    venv/Scripts/python run_all.py --models han,ding_cnn --label y3
    venv/Scripts/python run_all.py --skip-done           # 已有 results/<model>_<label>.json 的跳過

評估
    · 測試季 2024Q3 ~ 2026Q3（9 折），訓練 = 測試季開始前 GAP_DAYS 個交易日之前的全部樣本（擴張視窗）
    · 分類：accuracy、MCC、AUC、macro-F1（各折 + 全部合併）
    · 交易：每個測試日把當天樣本按 P(上漲) 排序，做多前 20%、做空後 20%（當天 ≥ 5 個樣本才做），
      隔日超額報酬的日均價差、t 值、勝率；另報「高信心」子集（|P−0.5| > 0.1）的準確率與覆蓋率
    · 集成 ensemble_top3：合併結果中 AUC 前三名（不含基準）的機率平均，事後計算，不參與排名
"""
import argparse
import json
import math
import os
import sys
import time
import traceback
from datetime import datetime

import numpy as np
import pandas as pd

import nm_config as C
from nm_models import REGISTRY, Data

LOG = open(os.path.join(C.LOG_DIR, 'run_all.log'), 'a', encoding='utf-8')


def log(msg):
    line = f'{datetime.now():%m-%d %H:%M:%S} {msg}'
    print(line, flush=True)
    LOG.write(line + '\n')
    LOG.flush()


def quarter_bounds(q: str):
    y, k = int(q[:4]), int(q[-1])
    start = pd.Timestamp(year=y, month=3 * (k - 1) + 1, day=1)
    end = start + pd.offsets.QuarterEnd(0)
    return start.date(), end.date()


def folds(d: Data, label='y1'):
    dates = d.samples.date.values
    od = d.open_days
    ok = d.samples[f'fwd_{label}'].notna().values          # y3／y5 在樣本尾端沒有標籤
    out = []
    for q in C.TEST_QUARTERS:
        s, e = quarter_bounds(q)
        i = np.searchsorted(od, s)
        cut = od[max(0, i - C.GAP_DAYS)]
        tr = np.where((dates < cut) & (dates >= C.SAMPLE_SINCE) & ok)[0]
        te = np.where((dates >= s) & (dates <= e) & ok)[0]
        if len(te) >= 50 and len(tr) >= 500:
            out.append((q, tr, te))
    return out


def metrics(y, p, ex, dates):
    from sklearn.metrics import accuracy_score, f1_score, matthews_corrcoef, roc_auc_score
    y = np.asarray(y).astype(int)
    pred = (p >= 0.5).astype(int)
    m = {'n': int(len(y)), 'acc': float(accuracy_score(y, pred)), 'mcc': float(matthews_corrcoef(y, pred)),
         'f1': float(f1_score(y, pred, average='macro'))}
    try:
        m['auc'] = float(roc_auc_score(y, p)) if len(set(y)) > 1 else float('nan')
    except ValueError:
        m['auc'] = float('nan')
    conf = np.abs(p - 0.5) > 0.1
    m['conf_cov'] = float(conf.mean())
    m['conf_acc'] = float(accuracy_score(y[conf], pred[conf])) if conf.sum() > 20 else float('nan')
    # 日曆時間多空組合
    df = pd.DataFrame({'d': dates, 'p': p, 'ex': ex})
    spreads = []
    for _, g in df.groupby('d'):
        if len(g) < 5:
            continue
        k = max(1, int(round(len(g) * 0.2)))
        g = g.sort_values('p')
        spreads.append(g.ex.values[-k:].mean() - g.ex.values[:k].mean())
    s = np.array(spreads)
    m['ls_days'] = int(len(s))
    m['ls_mean'] = float(s.mean()) if len(s) else float('nan')
    m['ls_t'] = float(s.mean() / (s.std(ddof=1) / math.sqrt(len(s)))) if len(s) > 5 and s.std(ddof=1) > 0 else float('nan')
    m['ls_win'] = float((s > 0).mean()) if len(s) else float('nan')
    return m


def run_model(name, fn, d: Data, fl, label):
    P = np.full(len(d.samples), np.nan, dtype=np.float32)
    per_fold = []
    for q, tr, te in fl:
        t0 = time.time()
        p = np.clip(np.asarray(fn(d, tr, te, label), dtype=np.float32), 1e-4, 1 - 1e-4)
        P[te] = p
        m = metrics(d.y(te, label), p, d.samples[f'fwd_{label}'].values[te], d.samples.date.values[te])
        m['fold'] = q
        m['sec'] = round(time.time() - t0, 1)
        per_fold.append(m)
        log(f'  {name} {q} n={m["n"]} acc={m["acc"]:.3f} auc={m["auc"]:.3f} mcc={m["mcc"]:+.3f} ls={m["ls_mean"] * 100:+.3f}% ({m["sec"]}s)')
    ok = ~np.isnan(P)
    pooled = metrics(d.y(np.where(ok)[0], label), P[ok], d.samples[f'fwd_{label}'].values[ok], d.samples.date.values[ok])
    return P, per_fold, pooled


def leaderboard(label) -> pd.DataFrame:
    rows = []
    for f in sorted(os.listdir(C.RESULT_DIR)):
        if f.endswith(f'_{label}.json'):
            r = json.load(open(os.path.join(C.RESULT_DIR, f), encoding='utf-8'))
            pm = r['pooled']
            wins = sum(1 for x in r['folds'] if x['auc'] == x['auc'] and x['auc'] > 0.5)
            rows.append({'model': r['name'], 'desc': r['desc'], 'paper': r['paper'], 'n': pm['n'], 'acc': pm['acc'], 'auc': pm['auc'],
                         'mcc': pm['mcc'], 'f1': pm['f1'], 'conf_acc': pm['conf_acc'], 'conf_cov': pm['conf_cov'],
                         'ls_mean': pm['ls_mean'], 'ls_t': pm['ls_t'], 'ls_win': pm['ls_win'], 'folds_auc_gt_half': f'{wins}/{len(r["folds"])}',
                         'sec': sum(x['sec'] for x in r['folds'])})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values('auc', ascending=False)


def write_report(d: Data, label):
    lb = leaderboard(label)
    if lb.empty:
        return
    lb.to_csv(os.path.join(C.RESULT_DIR, f'leaderboard_{label}.csv'), index=False, encoding='utf-8-sig')
    fl = folds(d, label)
    L = [f'# 新聞 + 股價 → 走勢：多模型比較（Iteration 40，標籤 {label}）', '',
         f'產出 {datetime.now():%Y-%m-%d %H:%M}。樣本 {len(d.samples):,}（{d.samples.stock_id.nunique()} 檔 × 有新聞的交易日，'
         f'{d.samples.date.min()} ~ {d.samples.date.max()}），新聞 {len(d.news):,} 則。',
         f'標籤 = 隔日（{label}）相對股票池等權均值的超額報酬是否 > 0；正類比例 {d.samples[label].mean():.3f}。',
         f'測試 {len(fl)} 個季度（{fl[0][0]} ~ {fl[-1][0]}）擴張視窗 walk-forward，訓練與測試之間空 {C.GAP_DAYS} 個交易日。',
         '交易欄：每個測試日按 P 排序做多前 20%／做空後 20%（當天 ≥ 5 檔），隔日超額報酬日均價差（未扣成本）。', '',
         '## 排行榜（按合併 AUC）', '',
         '| 模型 | 說明 | 出處 | AUC | Acc | MCC | F1 | 高信心 Acc（覆蓋） | 多空日均 | t | 勝率 | AUC>0.5 折數 | 秒 |',
         '|------|------|------|-----|-----|-----|----|-----------------|---------|---|------|------------|----|']
    for r in lb.itertuples(index=False):
        L.append(f'| {r.model} | {r.desc} | {r.paper} | {r.auc:.3f} | {r.acc:.3f} | {r.mcc:+.3f} | {r.f1:.3f} | '
                 f'{r.conf_acc:.3f}（{r.conf_cov:.0%}） | {r.ls_mean * 100:+.3f}% | {r.ls_t:+.1f} | {r.ls_win:.0%} | {r.folds_auc_gt_half} | {r.sec:.0f} |')
    L += ['', '## 各折 AUC', '', '| 模型 | ' + ' | '.join(q for q, _, _ in fl) + ' |', '|------|' + '---|' * len(fl)]
    for r in lb.itertuples(index=False):
        res = json.load(open(os.path.join(C.RESULT_DIR, f'{r.model}_{label}.json'), encoding='utf-8'))
        by = {x['fold']: x['auc'] for x in res['folds']}
        L.append(f'| {r.model} | ' + ' | '.join(f'{by.get(q, float("nan")):.3f}' for q, _, _ in fl) + ' |')
    L += ['', '## 讀法', '',
          '- **AUC 0.50 = 沒有訊號**；文獻上新聞模型的隔日方向 AUC 多在 0.52~0.58（StockNet 0.58 acc、HAN 約 0.6 acc 是在他們的資料上）。',
          '- 純價格基準（price_logreg / gru_price）是門檻：新聞模型要贏它才算新聞有增量。',
          '- 多空日均價差是可交易性：t > 2 且勝率 > 55% 才值得再看成本。台股個股當沖成本約 0.3~0.5% 來回，日均價差要明顯高於此。',
          '- 各折 AUC 看穩定度：只有一兩折很高、其餘 0.5 的是運氣。',
          '- 前視偏誤：MiniLM（2021）與中文財經情緒模型（2023 前）權重不含測試期；字典與 TF-IDF 無此問題。', '']
    path = C.REPORT_MD if label == 'y1' else C.REPORT_MD.replace('.md', f'_{label}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))


def ensemble(d: Data, label, fl):
    lb = leaderboard(label)
    base = {'majority', 'persist', 'price_logreg', 'gru_price', 'ensemble_top3'}
    top = [m for m in lb.model if m not in base][:3]
    if len(top) < 2:
        return
    P = np.nanmean([np.load(os.path.join(C.RESULT_DIR, f'{m}_{label}_prob.npy')) for m in top], axis=0)
    per_fold = []
    for q, tr, te in fl:
        m = metrics(d.y(te, label), P[te], d.samples[f'fwd_{label}'].values[te], d.samples.date.values[te])
        m['fold'], m['sec'] = q, 0
        per_fold.append(m)
    ok = ~np.isnan(P)
    pooled = metrics(d.y(np.where(ok)[0], label), P[ok], d.samples[f'fwd_{label}'].values[ok], d.samples.date.values[ok])
    save(d, 'ensemble_top3', f'前三名機率平均（{" + ".join(top)}）', '集成', label, P, per_fold, pooled)


def save(d, name, desc, paper, label, P, per_fold, pooled):
    np.save(os.path.join(C.RESULT_DIR, f'{name}_{label}_prob.npy'), P)
    json.dump({'name': name, 'desc': desc, 'paper': paper, 'label': label, 'folds': per_fold, 'pooled': pooled,
               'at': datetime.now().isoformat(timespec='seconds')},
              open(os.path.join(C.RESULT_DIR, f'{name}_{label}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', default='')
    ap.add_argument('--label', default='y1')
    ap.add_argument('--skip-done', action='store_true')
    a = ap.parse_args()
    want = [m for m in a.models.split(',') if m]
    d = Data()
    fl = folds(d, a.label)
    log(f'樣本 {len(d.samples):,}、折 {[q for q, _, _ in fl]}、emb {"有" if d.emb is not None else "無"}、sent_zh {"有" if d.sent_zh is not None else "無"}')
    for name, desc, paper, fn, need_emb in REGISTRY:
        if want and name not in want:
            continue
        if need_emb and d.emb is None:
            log(f'{name} 跳過：沒有 emb_minilm.npy（先跑 embed.py）')
            continue
        if a.skip_done and os.path.exists(os.path.join(C.RESULT_DIR, f'{name}_{a.label}.json')):
            log(f'{name} 已有結果，跳過')
            continue
        log(f'=== {name}：{desc}')
        try:
            P, per_fold, pooled = run_model(name, fn, d, fl, a.label)
            save(d, name, desc, paper, a.label, P, per_fold, pooled)
            log(f'=== {name} 合併 acc={pooled["acc"]:.3f} auc={pooled["auc"]:.3f} mcc={pooled["mcc"]:+.3f} '
                f'ls={pooled["ls_mean"] * 100:+.3f}% t={pooled["ls_t"]:+.1f}')
        except Exception as e:      # noqa: BLE001
            log(f'!!! {name} 失敗：{e}\n{traceback.format_exc()}')
        try:
            write_report(d, a.label)
        except Exception as e:      # noqa: BLE001
            log(f'寫報告失敗：{e}')
    try:
        ensemble(d, a.label, fl)
        write_report(d, a.label)
    except Exception as e:      # noqa: BLE001
        log(f'集成失敗：{e}\n{traceback.format_exc()}')
    log('全部完成')


if __name__ == '__main__':
    main()
