"""
新聞訊號模型（Iteration 47）
──────────────────────────
依「新聞與股價關聯性」研究方案，把六個維度做成三個可上台帳的模型，
每一個都用「價格控制組 vs 價格＋新聞」的消融回答 N2（新聞有沒有增量資訊）：

    news_event_vol   事件波動：次日振幅 (高−低)÷收盤。方案 §04／MopsEventStudy：新聞與非例行公告
                     是波動訊號不是方向訊號；異常注意力放大 |AR|。   量級模型，排序相關把關（target_kind range, h=1）
    news_drift       營收漂移：月營收公布後 20 日超額報酬。PEAD（Ball & Brown 1968）；
                     universe 研究：AR₀ 對 CAR[1,20] 係數 +0.41、極端 YoY 反轉。 方向模型（target_kind signal, h=20）
    news_tone        新聞語調：有新聞日的 3 日超額報酬。Tetlock 2007；Iteration 40 已示警 AUC≈0.5，
                     這裡用同一套關卡再驗一次，通不過就照實登錄為 none。   方向模型（target_kind signal, h=3）

## 為什麼是消融而不是單看準確率

方案 §03「新聞因子最可能的失敗方式，是它其實只是動能或成交量的代理」。所以每個模型跑兩個變體：
`price_only`（10 個價量控制特徵）與 `price_news`（控制＋新聞／事件特徵），在**同一批列、同一組折**上比。
新聞變體只有高出控制組 DEPLOY_MARGIN、且每一折都不輸，才算有增量、才部署；否則模型照樣登錄
（credibility=none），但不服役、不進投票。

## 樣本的實質代價

新聞只有 2023-09 起：三年、26 檔、約 18,000 個股票日。方向模型再受「有新聞」「在漂移窗口內」限制。
走查用 3 折擴張視窗，測試期是後半段（約 1.5 年），封存 = 預測視野。
樣本這麼小，任何「通過」都要在線上台帳累積 100 筆後再看一次。

## 五道關卡怎麼對應

    N0 時間戳   effective_date 13:30 規則 + 面板只用 ≤ D 的新聞（news_signal_features 說明）
    N1 漂移     news_drift 的目標本身就是 t+1 之後的報酬（不含 t=0）
    N2 增量     price_only vs price_news 的消融（本檔的部署判定）
    N3 漲跌停   方向模型另報「剔除事件日或次日鎖死（|報酬| ≥ 9.5%）」的成績
    N4 成本     方向模型另報出手列的平均超額報酬扣掉來回 0.585%（手續費 0.1425%×2＋證交稅 0.3%）

用法：python train_news_models.py [--model news_event_vol|news_drift|news_tone|all] [--folds 3]
產出：results/news_models.md、results/news_models.json、saved_models/<name>.joblib
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'Crawler'))

RESULTS_DIR = os.path.join(BASE_DIR, 'results')
MODEL_DIR = os.path.join(BASE_DIR, 'saved_models')

DEPLOY_MARGIN = 0.01          # 新聞變體的主指標須高出價格控制組這麼多
DIR_MARGIN = 0.03             # 方向模型出手列的方向準確率須高出多數類別這麼多
ACT_RATE = 0.20               # 方向模型的出手率：|預測| 前 20% 才出手，其餘棄權（0）
ROUND_TRIP_COST = 0.00585     # 手續費 0.1425%×2 + 證交稅 0.3%
LOCK_LIMIT = 0.095            # 台股漲跌停 ±10%，留一點價格跳動的餘裕

PRICE_CONTROLS = ['ret_1d', 'ret_5d', 'ret_20d', 'vol_5d', 'vol_20d', 'atr_pct',
                  'vol_ratio', 'turnover_ratio', 'ma20_dev', 'rsi_14', 'hl_pos', 'gap_pct']

PARAMS = dict(max_iter=250, learning_rate=0.05, max_depth=3,
              min_samples_leaf=100, l2_regularization=1.0, random_state=42)

from news_signal_features import NEWS_FEATURES, EVENT_FEATURES   # noqa: E402

SPECS = {
    'news_event_vol': {
        'label': '事件波動（次日振幅）', 'target_kind': 'range', 'horizon': 1,
        'target': 'y_range1', 'baseline': 'base_range', 'rank_metric': True,
        'row_filter': None,
        'news_cols': ['ns_n_articles', 'ns_n_sources', 'ns_abn_attn', 'ns_attn_3d', 'ns_has_news',
                      'ns_strong_kw', 'ns_novelty', 'ns_uncertainty', 'ns_sent',
                      'ns_mops_nonroutine', 'ns_mops_attention',
                      'ev_days_since_rev', 'ev_sue', 'ev_in_window'],
    },
    'news_drift': {
        'label': '營收漂移（PEAD 覆蓋層）', 'target_kind': 'signal', 'horizon': 20,
        'target': 'y_exc20', 'baseline': None, 'rank_metric': True,
        'row_filter': 'in_window',
        'news_cols': ['ev_sue', 'ev_yoy', 'ev_yoy_extreme', 'ev_days_since_rev', 'ev_rev_ar0',
                      'ns_sent_3d', 'ns_abn_attn', 'ns_mops_nonroutine'],
    },
    'news_tone': {
        'label': '新聞語調（3 日）', 'target_kind': 'signal', 'horizon': 3,
        'target': 'y_exc3', 'baseline': None, 'rank_metric': True,
        'row_filter': 'has_news',
        'news_cols': ['ns_sent', 'ns_sent_3d', 'ns_strong_kw', 'ns_novelty', 'ns_uncertainty',
                      'ns_abn_attn', 'ns_n_sources', 'ns_mops_nonroutine'],
    },
}


# ── 資料 ─────────────────────────────────────────────────────────────────────
def load_data(for_inference: bool = False) -> pd.DataFrame:
    """
    統一面板（price + news + event）加上三個目標與一個天真基準。
    for_inference=True 不剔除目標缺失的列——目標要未來資料，剔除會讓線上基準日永遠落後。
    """
    import panel as P
    raw = P.build(blocks=['price', 'news', 'event'])
    d = raw.sort_values(['stock_id', 'trade_date']).reset_index(drop=True)
    g = d.groupby('stock_id')

    f = d['adj_close'] / d['close'].replace(0, np.nan)
    adj_high, adj_low = d['high'] * f, d['low'] * f
    d['_rng'] = (adj_high - adj_low) / g['adj_close'].shift(1)         # 當日振幅 ÷ 前收（與 resolve 同口徑）
    d['y_range1'] = g['_rng'].shift(-1)
    d['base_range'] = g['_rng'].transform(lambda s: s.rolling(20, min_periods=10).median())

    for h in (3, 20):
        y = g['adj_close'].shift(-h) / d['adj_close'] - 1
        d[f'y_ret{h}'] = y
        d[f'y_exc{h}'] = y - y.groupby(d['trade_date']).transform('mean')
    # N3：事件日或次日鎖死（漲跌停）的列另外標記
    d['_locked'] = (d['ret_1d'].abs() >= LOCK_LIMIT) | (g['ret_1d'].shift(-1).abs() >= LOCK_LIMIT)

    # 只要求價量特徵完整：新聞欄位在沒新聞的日子本來就是 NaN（方案 §06「沒有新聞 ≠ 中性」），
    # 拿它們 dropna 等於只留有新聞的日子，事件波動模型就再也學不到「沒人報導的日子比較不震」。
    # 樹模型原生處理缺失。日期下限另外套：2023-09 之前的 0 則數是「還沒抓」，不是「沒新聞」。
    from news_signal_features import NEWS_SINCE
    d = P.align(d, ['price'], extra_required=['base_range'])
    d = d[d['trade_date'] >= pd.Timestamp(NEWS_SINCE)].reset_index(drop=True)
    if not for_inference:
        d = d[d[['y_range1', 'y_exc3', 'y_exc20']].notna().all(axis=1)].reset_index(drop=True)
    return d.drop(columns=['_rng'])


def rows_for(spec: dict, d: pd.DataFrame) -> pd.DataFrame:
    if spec['row_filter'] == 'in_window':
        return d[d['ev_in_window'] == 1].reset_index(drop=True)
    if spec['row_filter'] == 'has_news':
        return d[d['ns_has_news'] == 1].reset_index(drop=True)
    return d


def variants_for(spec: dict, d: pd.DataFrame) -> dict:
    ctrl = [c for c in PRICE_CONTROLS if c in d.columns]
    news = [c for c in spec['news_cols'] if c in d.columns]
    return {'price_only': ctrl, 'price_news': ctrl + news}


# ── 走查 ─────────────────────────────────────────────────────────────────────
def make_folds(d: pd.DataFrame, n_folds: int, embargo: int):
    dates = np.sort(d['trade_date'].unique())
    start = int(len(dates) * 0.5)
    bounds = np.linspace(start, len(dates), n_folds + 1).astype(int)
    for i in range(n_folds):
        lo, hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        te = (d['trade_date'] >= lo) & (d['trade_date'] <= hi)
        tr = d['trade_date'] < dates[max(bounds[i] - embargo, 0)]
        if tr.sum() < 500 or te.sum() < 100:
            continue
        yield i + 1, tr.values, te.values, str(lo)[:10], str(hi)[:10]


def _fit(d, cols, target, tr):
    m = HistGradientBoostingRegressor(**PARAMS)
    m.fit(d.loc[tr, cols].values, d.loc[tr, target].values)
    return m


def _direction_stats(pred: np.ndarray, actual_exc: np.ndarray, actual_raw: np.ndarray,
                     locked: np.ndarray, act_rate: float) -> dict:
    """方向模型：|預測| 前 act_rate 出手，其餘棄權。回方向準確率、多數類別、N3、N4。"""
    k = max(int(len(pred) * act_rate), 10)
    thr = np.sort(np.abs(pred))[-k]
    act = np.abs(pred) >= thr
    sig = np.sign(pred[act])
    exc, raw, lk = actual_exc[act], actual_raw[act], locked[act]
    ok = raw != 0
    correct = (sig[ok] == np.sign(raw[ok]))
    up = (raw[ok] > 0).mean() if ok.any() else 0.5
    out = {
        'n_act': int(act.sum()), 'act_rate': float(act.mean()),
        'dir_acc': float(correct.mean()) if ok.any() else None,
        'majority': float(max(up, 1 - up)),
        'dir_acc_exc': float((sig == np.sign(exc)).mean()),
        'mean_exc_ret': float((sig * exc).mean()),
        'net_exc_ret': float((sig * exc).mean() - ROUND_TRIP_COST),
        'threshold': float(thr),
    }
    if (~lk).sum() >= 10:
        okn = ok & ~lk
        out['dir_acc_unlocked'] = float((sig[okn] == np.sign(raw[okn])).mean()) if okn.any() else None
        out['n_unlocked'] = int((~lk).sum())
    return out


def walk_forward(spec: dict, d: pd.DataFrame, n_folds: int) -> dict:
    variants = variants_for(spec, d)
    target = spec['target']
    folds = []
    for i, tr, te, lo, hi in make_folds(d, n_folds, spec['horizon']):
        rec = {'fold': i, 'from': lo, 'to': hi, 'n_train': int(tr.sum()), 'n_test': int(te.sum())}
        act = d.loc[te, target].values
        for name, cols in variants.items():
            m = _fit(d, cols, target, tr)
            pred = m.predict(d.loc[te, cols].values)
            rec[name] = {'rank_corr': float(spearmanr(pred, act).statistic),
                         'mae': float(np.mean(np.abs(pred - act)))}
            if spec['target_kind'] == 'signal':
                h = spec['horizon']
                rec[name].update(_direction_stats(
                    pred, act, d.loc[te, f'y_ret{h}'].values, d.loc[te, '_locked'].values, ACT_RATE))
        if spec['baseline']:
            base = d.loc[te, spec['baseline']].values
            rec['baseline'] = {'rank_corr': float(spearmanr(base, act).statistic),
                               'mae': float(np.mean(np.abs(base - act)))}
        folds.append(rec)

    w = np.array([f['n_test'] for f in folds], dtype=float)

    def wm(getter):
        vals = np.array([getter(f) for f in folds], dtype=float)
        return float(np.nansum(vals * w) / w.sum())

    summary = {'folds': folds, 'n_folds': len(folds)}
    for name in variants:
        summary[name] = {'rank_corr': wm(lambda f: f[name]['rank_corr']),
                         'mae': wm(lambda f: f[name]['mae'])}
        if spec['target_kind'] == 'signal':
            for k in ('dir_acc', 'majority', 'dir_acc_exc', 'mean_exc_ret', 'net_exc_ret', 'dir_acc_unlocked'):
                summary[name][k] = wm(lambda f: (f[name].get(k) if f[name].get(k) is not None else np.nan))
    if spec['baseline']:
        summary['baseline'] = {'rank_corr': wm(lambda f: f['baseline']['rank_corr']),
                               'mae': wm(lambda f: f['baseline']['mae'])}

    gain = summary['price_news']['rank_corr'] - summary['price_only']['rank_corr']
    worst = min(f['price_news']['rank_corr'] - f['price_only']['rank_corr'] for f in folds) if folds else np.nan
    gates = {
        'N2_gain': gain, 'N2_worst_fold': worst,
        'N2_pass': bool(folds) and gain >= DEPLOY_MARGIN and worst > 0,
    }
    if spec['baseline']:
        gates['beats_naive'] = summary['price_news']['rank_corr'] > summary['baseline']['rank_corr']
    if spec['target_kind'] == 'signal':
        pn = summary['price_news']
        gates['N1_dir_margin'] = pn['dir_acc'] - pn['majority']
        gates['N1_pass'] = (pn['dir_acc'] - pn['majority']) >= DIR_MARGIN
        gates['N3_dir_acc_unlocked'] = pn.get('dir_acc_unlocked')
        gates['N3_pass'] = (pn.get('dir_acc_unlocked') or 0) - pn['majority'] >= DIR_MARGIN
        gates['N4_net_exc_ret'] = pn['net_exc_ret']
        gates['N4_pass'] = pn['net_exc_ret'] > 0
        deploy = gates['N2_pass'] and gates['N1_pass'] and gates['N3_pass'] and gates['N4_pass']
    else:
        deploy = gates['N2_pass'] and gates.get('beats_naive', True)
    gates['deploy'] = bool(deploy)
    summary['gates'] = gates
    summary['variants'] = variants
    return summary


# ── 存檔與登錄 ────────────────────────────────────────────────────────────────
def save_model(name: str, spec: dict, d: pd.DataFrame, summary: dict):
    import joblib
    cols = summary['variants']['price_news']
    m = HistGradientBoostingRegressor(**dict(PARAMS, early_stopping=True, validation_fraction=0.15))
    m.fit(d[cols].values, d[spec['target']].values)
    bundle = {
        'model': m, 'feature_cols': cols, 'blocks': ['price', 'news', 'event'],
        'target_kind': spec['target_kind'], 'horizon': spec['horizon'],
        'row_filter': spec['row_filter'], 'baseline_col': spec['baseline'],
        'trained_at': datetime.now().isoformat(),
        'walk_forward': {k: summary[k] for k in ('price_only', 'price_news', 'baseline') if k in summary},
        'gates': summary['gates'],
    }
    if spec['target_kind'] == 'signal':
        pred = m.predict(d[cols].values)
        k = max(int(len(pred) * ACT_RATE), 10)
        bundle['act_threshold'] = float(np.sort(np.abs(pred))[-k])
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, f'{name}.joblib')
    joblib.dump(bundle, path)
    print(f'  模型已存 {path}')
    try:
        import model_registry as registry
        v = registry.register_training(name, train_metrics={
            'rows': len(d), 'features': len(cols), 'horizon': spec['horizon'],
            'rank_corr': summary['price_news']['rank_corr'],
            'price_only_rank_corr': summary['price_only']['rank_corr'],
            'gates': summary['gates']})
        if v:
            print(f'  已登錄為 {name} v{v["version"]}（candidate{"" if summary["gates"]["deploy"] else "，未通過關卡，不服役"}）')
    except Exception as e:
        print(f'  （模型登錄略過：{e}）')


def fmt(x, digits=4, pct=False):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return '—'
    return f'{x:+.2%}' if pct else f'{x:.{digits}f}'


def write_report(results: dict, d_all: pd.DataFrame, n_folds: int):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    L = ['# 新聞訊號模型（Iteration 47）', '',
         f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
         f'**面板：** {len(d_all):,} 個股票日 / {d_all["stock_id"].nunique()} 檔　'
         f'{d_all.trade_date.min().date()} ~ {d_all.trade_date.max().date()}（新聞自 2023-09 起）',
         f'**驗證：** {n_folds} 折擴張視窗走查，測試期為後半段，封存 = 預測視野；'
         f'每個模型比 `price_only`（{len(PRICE_CONTROLS)} 個價量控制）與 `price_news`。',
         f'**部署門檻：** 新聞變體排序相關高出控制組 +{DEPLOY_MARGIN} 且每折不輸（N2）；'
         f'方向模型另需出手列（|預測| 前 {ACT_RATE:.0%}）方向準確率高出多數類別 +{DIR_MARGIN:.0%}（含剔除鎖死，N3）'
         f'且扣成本後超額報酬 > 0（N4）。', '']
    for name, r in results.items():
        spec = SPECS[name]
        s = r['summary']
        L += [f'## {name}：{spec["label"]}', '',
              f'目標 `{spec["target"]}`（target_kind {spec["target_kind"]}、視野 {spec["horizon"]} 日）；'
              f'列篩選：{spec["row_filter"] or "全部"}；樣本 {r["n"]:,} 列。', '',
              '| 折 | 測試期 | 測試列 | price_only | price_news | 差距 |' + (' 天真基準 |' if spec['baseline'] else ''),
              '|----|--------|-------|-----------|-----------|------|' + ('---------|' if spec['baseline'] else '')]
        for f in s['folds']:
            row = (f"| {f['fold']} | {f['from']} ~ {f['to']} | {f['n_test']:,} | "
                   f"{f['price_only']['rank_corr']:.4f} | {f['price_news']['rank_corr']:.4f} | "
                   f"{f['price_news']['rank_corr'] - f['price_only']['rank_corr']:+.4f} |")
            if spec['baseline']:
                row += f" {f['baseline']['rank_corr']:.4f} |"
            L.append(row)
        g = s['gates']
        L += ['', f'加權平均排序相關：price_only {s["price_only"]["rank_corr"]:.4f}、'
                  f'price_news {s["price_news"]["rank_corr"]:.4f}、差距 **{g["N2_gain"]:+.4f}**、最差折 {g["N2_worst_fold"]:+.4f}'
                  + (f'、天真基準 {s["baseline"]["rank_corr"]:.4f}' if spec['baseline'] else '') + '。']
        if spec['target_kind'] == 'signal':
            pn, po = s['price_news'], s['price_only']
            L += ['',
                  '| 變體 | 出手列方向準確率 | 多數類別 | 超額方向 | 剔除鎖死 | 平均超額報酬 | 扣成本 |',
                  '|------|----------------|---------|---------|---------|-----------|-------|']
            for nm, v in (('price_only', po), ('price_news', pn)):
                L.append(f"| {nm} | {fmt(v['dir_acc'], pct=True)} | {fmt(v['majority'], pct=True)} | "
                         f"{fmt(v['dir_acc_exc'], pct=True)} | {fmt(v.get('dir_acc_unlocked'), pct=True)} | "
                         f"{fmt(v['mean_exc_ret'], pct=True)} | {fmt(v['net_exc_ret'], pct=True)} |")
            L += ['', f'關卡：N1 方向 {"通過" if g["N1_pass"] else "未過"}（{g["N1_dir_margin"]:+.2%}）、'
                      f'N2 增量 {"通過" if g["N2_pass"] else "未過"}、N3 剔除鎖死 {"通過" if g["N3_pass"] else "未過"}、'
                      f'N4 扣成本 {"通過" if g["N4_pass"] else "未過"}（{g["N4_net_exc_ret"]:+.2%}）。']
        else:
            L += ['', f'關卡：N2 增量 {"通過" if g["N2_pass"] else "未過"}；'
                      f'贏過天真基準（20 日振幅中位數）{"是" if g.get("beats_naive") else "否"}。']
        L += ['', f'**部署判定：{"通過" if g["deploy"] else "未通過"}**。', '']
    L += ['## 怎麼讀', '',
          '- 三個模型都登錄進模型版本頁（candidate），**只有通過的才服役**、才在投票／週預測裡有值；'
          '未通過的留在目錄裡標 credibility=none，線上台帳照樣累積，讓它有機會被否證或平反。',
          '- 方向模型的「多數類別」是出手列裡漲或跌較多的那一邊——這比 50% 難打，也是本專案一貫的基準。',
          '- 樣本只有三年、26 檔。任何通過都要等線上台帳 100 筆再看一次（model_lifecycle 的門檻）。']
    path = os.path.join(RESULTS_DIR, 'news_models.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'報告已寫入 {path}')

    js = {name: {'label': SPECS[name]['label'], 'target_kind': SPECS[name]['target_kind'],
                 'horizon': SPECS[name]['horizon'], 'n': r['n'],
                 'price_only': r['summary']['price_only'], 'price_news': r['summary']['price_news'],
                 'baseline': r['summary'].get('baseline'), 'gates': r['summary']['gates'],
                 'trained_at': datetime.now().isoformat(timespec='minutes')}
          for name, r in results.items()}
    with open(os.path.join(RESULTS_DIR, 'news_models.json'), 'w', encoding='utf-8') as f:
        json.dump(js, f, ensure_ascii=False, indent=2, default=lambda o: None if isinstance(o, float) and np.isnan(o) else o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='all', choices=['all'] + list(SPECS))
    ap.add_argument('--folds', type=int, default=3)
    ap.add_argument('--no-save', action='store_true', help='只走查、不存檔不登錄')
    args = ap.parse_args()

    print('載入統一面板（price + news + event）…')
    d_all = load_data()
    print(f'{len(d_all):,} 列 / {d_all["stock_id"].nunique()} 檔　'
          f'{d_all.trade_date.min().date()} ~ {d_all.trade_date.max().date()}')

    results = {}
    names = list(SPECS) if args.model == 'all' else [args.model]
    for name in names:
        spec = SPECS[name]
        d = rows_for(spec, d_all)
        print(f'\n=== {name}：{spec["label"]}　{len(d):,} 列 ===')
        s = walk_forward(spec, d, args.folds)
        g = s['gates']
        print(f'  排序相關 price_only {s["price_only"]["rank_corr"]:.4f} → price_news {s["price_news"]["rank_corr"]:.4f}'
              f'（{g["N2_gain"]:+.4f}，最差折 {g["N2_worst_fold"]:+.4f}）'
              + (f'　天真基準 {s["baseline"]["rank_corr"]:.4f}' if spec['baseline'] else ''))
        if spec['target_kind'] == 'signal':
            pn = s['price_news']
            print(f'  出手 {ACT_RATE:.0%}：方向 {pn["dir_acc"]:.2%} 對多數類別 {pn["majority"]:.2%}；'
                  f'剔除鎖死 {fmt(pn.get("dir_acc_unlocked"), pct=True)}；扣成本超額 {pn["net_exc_ret"]:+.2%}')
        print(f'  部署判定：{"通過" if g["deploy"] else "未通過"}')
        results[name] = {'summary': s, 'n': len(d)}
        if not args.no_save:
            save_model(name, spec, d, s)

    write_report(results, d_all, args.folds)


if __name__ == '__main__':
    main()
