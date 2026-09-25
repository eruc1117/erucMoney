"""
新模型候選評估（Iteration 31）
──────────────────────────────
需求是「依照目前有的資料重新評估可以新增哪些模型」。這份資料已經反覆告訴我們
同一件事，先寫下來當作選題依據：

    方向預測沒有 edge   LSTM 方向 46.9~50.6%（Iteration 11）
                        M3 在 2018 後買進方向 51.53%（Iteration 30）
                        規則型情緒訊號 22 檔恆同（Iteration 10）
    量級與排序有 edge   波動率 相關 0.606 / R²(log) 0.483（Iteration 13）
                        振幅   排序相關 0.654（Iteration 19/30）
                        跳空   相關 0.704（Iteration 16/28/30）

所以新候選一律**不做第四個方向預測器**，而是補上決策實際需要、目前卻沒有的量：

┌─ volume ────── 未來 5 日平均成交量 ÷ 當前 20 日均量
│  用途：閒置資金進場前的流動性檢查。目前 `cash_allocator` 只用價格與振幅估
│        部位，完全沒看「這檔吃不吃得下這筆錢」。量能萎縮時同樣的單量衝擊更大。
│  基準：naive = 1.0（未來量等於現在的 20 日均量）
│
├─ drawdown ──── 未來 5 日最大不利偏移 (min(low) − close) / close
│  用途：停損距離。目前 `risk_model` 用對稱波動率推停損，但停損只會被**下跌**
│        觸發——對稱假設在偏態明顯的個股上會系統性地把停損放得太近或太遠。
│  基準：naive = −1.65 × EWMA 日波動 × √5（常態假設下的 5% 分位）
│
└─ relstrength ─ 未來 5 日報酬在同日全體中的百分位
   用途：閒置資金的選股排序、投票的優先序。這是**排序**問題不是方向問題——
         「哪幾檔會相對強」比「會不會漲」容易得多，因為大盤 beta 被排名消掉了。
   基準：naive = 過去 20 日報酬的同日百分位（動能延續假設）

## 判定

三折擴張視窗走查 + 標籤期封存。主指標一律是**排序相關（Spearman）**，
因為三個目標的用途都是排序而非精準值。要算「可新增」須同時滿足：

    排序相關 ≥ 基準 + 0.05    且    每一折都不輸基準

第二條是 Iteration 30 學到的：平均分數贏但某折輸，多半是某段期間的運氣。

用法：python explore_new_models.py [--folds 3] [--stage2]
產出：results/new_model_candidates.md
"""

import argparse
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
HORIZON = 5
BASE_BLOCKS = ['price', 'chip', 'cs', 'market']
MIN_GAIN = 0.05          # 排序相關須高出基準這麼多才算「值得新增」

HGB_PARAMS = dict(max_iter=300, learning_rate=0.05, max_depth=5,
                  min_samples_leaf=60, l2_regularization=1.0, random_state=42)


# ── 目標定義 ────────────────────────────────────────────────────────────────
def _ewma_vol(s: pd.Series, lam: float = 0.94) -> pd.Series:
    return s.pow(2).ewm(alpha=1 - lam).mean().pow(0.5)


def add_targets(p: pd.DataFrame) -> pd.DataFrame:
    """三個候選目標 + 各自的天真基準，全部只用當日（含）以前的資訊算基準。"""
    d = p.sort_values(['stock_id', 'trade_date']).reset_index(drop=True).copy()
    g = d.groupby('stock_id')

    # 高低價也要還原公司行動，否則減資日的 low 會製造假的巨大回撤
    factor = d['adj_close'] / d['close'].replace(0, np.nan)
    d['adj_high'] = d['high'] * factor
    d['adj_low'] = d['low'] * factor

    # ── volume：未來 5 日均量 ÷ 當前 20 日均量 ───────────────────────────
    vol20 = g['volume'].transform(lambda s: s.rolling(20, min_periods=10).mean())
    fwd_vol = g['volume'].transform(
        lambda s: s.shift(-HORIZON).rolling(HORIZON).mean())
    d['y_volume'] = fwd_vol / vol20.replace(0, np.nan)
    # 天真基準必須是「持續性」而不是常數 1.0。量能有很強的自相關，
    # 用常數當基準等於宣告基準沒有排序能力，模型再爛也會贏——
    # 這正是 Iteration 11 對 LSTM「明日=今日」基準犯過的相反錯誤的鏡像。
    # 正確的對照是「未來 5 日的量像最近 5 日的量」。
    d['base_volume'] = g['volume'].transform(
        lambda s: s.rolling(5, min_periods=3).mean()) / vol20.replace(0, np.nan)

    # ── drawdown：未來 5 日最低點相對今日收盤（負值，越負越糟）────────────
    fwd_low = g['adj_low'].transform(
        lambda s: s.shift(-HORIZON).rolling(HORIZON).min())
    d['y_drawdown'] = (fwd_low - d['adj_close']) / d['adj_close']
    daily = g['adj_close'].transform(lambda s: s.pct_change())
    ew = daily.groupby(d['stock_id']).transform(_ewma_vol)
    # 常態假設下 5 日累積的 5% 分位。這是業界最常見的做法，也是要被打敗的對象
    d['base_drawdown'] = -1.65 * ew * np.sqrt(HORIZON)

    # ── relstrength：未來 5 日報酬的同日百分位 ───────────────────────────
    fwd_ret = g['adj_close'].transform(lambda s: s.shift(-HORIZON) / s - 1)
    # 實際報酬本身留著：排序相關與百分位差距都不是錢，最後要看的是
    # 「照這個模型排序選前 20%，實際多賺多少」
    d['fwd_ret'] = fwd_ret
    d['y_relstrength'] = fwd_ret.groupby(d['trade_date']).rank(pct=True)
    # 天真：動能延續——過去 20 日報酬的同日百分位
    d['base_relstrength'] = d.groupby('trade_date')['ret_20d'].rank(pct=True)

    return d


# 波動率模型當初是「模型 × EWMA 取平均」才通過部署門檻（Iteration 13）。
# 下檔風險是同一類問題，若只比純模型而不給混合的機會，就是拿不同的標準在評。
BLEND_WITH_BASE = {'drawdown'}

TARGETS = {
    'volume': dict(y='y_volume', base='base_volume', horizon=HORIZON,
                   label='成交量預測', unit='倍',
                   use='閒置資金進場前的流動性檢查與衝擊成本估計'),
    'drawdown': dict(y='y_drawdown', base='base_drawdown', horizon=HORIZON,
                     label='下檔風險預測', unit='%',
                     use='非對稱停損距離（取代對稱波動率推算）'),
    'relstrength': dict(y='y_relstrength', base='base_relstrength', horizon=HORIZON,
                        label='相對強弱排序', unit='百分位',
                        use='閒置資金選股排序、投票優先序'),
}


# ── 走查 ────────────────────────────────────────────────────────────────────
def walk_forward(d: pd.DataFrame, feature_cols: list, spec: dict,
                 n_folds: int = 3) -> list:
    """
    擴張視窗走查 + 標籤期封存。

    封存不可省：目標用到未來 HORIZON 天，訓練集尾端那幾天的標籤會跨進測試期，
    不切掉等於讓模型看過測試期的一部分。
    """
    dates = np.sort(d['trade_date'].unique())
    start = int(len(dates) * 0.5)
    bounds = np.linspace(start, len(dates), n_folds + 1).astype(int)

    y_col, b_col, h = spec['y'], spec['base'], spec['horizon']
    out = []
    for i in range(n_folds):
        lo, hi = dates[bounds[i]], dates[bounds[i + 1] - 1]
        te = (d['trade_date'] >= lo) & (d['trade_date'] <= hi)
        embargo = dates[max(bounds[i] - h, 0)]
        tr = d['trade_date'] < embargo
        if tr.sum() < 2000 or te.sum() < 200:
            continue

        m = HistGradientBoostingRegressor(**HGB_PARAMS)
        m.fit(d.loc[tr, feature_cols].values, d.loc[tr, y_col].values)
        pred = m.predict(d.loc[te, feature_cols].values)

        actual = d.loc[te, y_col].values
        base = d.loc[te, b_col].values
        fret = d.loc[te, 'fwd_ret'].values if 'fwd_ret' in d.columns else np.full(len(actual), np.nan)
        ok = np.isfinite(pred) & np.isfinite(actual) & np.isfinite(base)
        if ok.sum() < 100:
            continue
        pred, actual, base, fret = pred[ok], actual[ok], base[ok], fret[ok]

        # 基準若是常數（volume 的 1.0）就沒有排序可言，記為 0
        if spec.get('blend'):
            # 與基準取平均後再評——與 risk_model 線上實際的做法一致
            pred = 0.5 * pred + 0.5 * base

        base_rank = 0.0 if np.std(base) < 1e-12 else spearmanr(base, actual).statistic
        # 決策相關指標：照預測排序取前後各 20%，看實際值差多少。
        # 排序相關 0.05 聽起來像沒有，但若它換得出可觀的分位差距就是可用的；
        # 反之相關再高、分位沒差距也沒有決策價值。
        k = max(int(len(pred) * 0.2), 20)
        order = np.argsort(pred)
        lo_mean = float(np.mean(actual[order[:k]]))
        hi_mean = float(np.mean(actual[order[-k:]]))
        # 換算成錢：照預測排序，前 20% 與後 20% 的**實際 5 日報酬**差距
        top_r, bot_r = fret[order[-k:]], fret[order[:k]]
        ret_spread = (float(np.nanmean(top_r) - np.nanmean(bot_r))
                      if np.isfinite(top_r).any() and np.isfinite(bot_r).any() else float('nan'))
        out.append({
            'fold': i + 1, 'from': str(lo)[:10], 'to': str(hi)[:10],
            'n_train': int(tr.sum()), 'n_test': int(ok.sum()),
            'rank_corr': float(spearmanr(pred, actual).statistic),
            'base_rank_corr': float(base_rank),
            'corr': float(np.corrcoef(pred, actual)[0, 1]),
            'mae': float(np.mean(np.abs(pred - actual))),
            'base_mae': float(np.mean(np.abs(base - actual))),
            'top_mean': hi_mean, 'bottom_mean': lo_mean, 'spread': hi_mean - lo_mean,
            'ret_spread': ret_spread,
        })
    return out


def summarise(folds: list) -> dict:
    if not folds:
        return {}
    w = np.array([f['n_test'] for f in folds], dtype=float)
    def wm(k):
        v = np.array([f[k] for f in folds], dtype=float)
        return float(np.sum(v * w) / w.sum())
    gains = [f['rank_corr'] - f['base_rank_corr'] for f in folds]
    return {
        'rank_corr': wm('rank_corr'), 'base_rank_corr': wm('base_rank_corr'),
        'corr': wm('corr'), 'mae': wm('mae'), 'base_mae': wm('base_mae'),
        'gain': wm('rank_corr') - wm('base_rank_corr'),
        'spread': wm('spread'), 'top_mean': wm('top_mean'), 'bottom_mean': wm('bottom_mean'),
        'ret_spread': wm('ret_spread'),
        'all_folds_win': all(g > 0 for g in gains),
        'worst_fold_gain': float(min(gains)), 'n_folds': len(folds),
        'n_test': int(w.sum()),
    }


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--folds', type=int, default=3)
    ap.add_argument('--stage2', action='store_true',
                    help='加做外生區塊消融（樣本砍到 2018 起）')
    args = ap.parse_args()

    import panel as P

    print('建立統一面板…')
    blocks_all = BASE_BLOCKS + (['night', 'futures'] if args.stage2 else [])
    raw = P.build(blocks=blocks_all)
    d = add_targets(raw)

    base_cols = P.columns_for(BASE_BLOCKS)
    base_cols = [c for c in base_cols if c in d.columns]

    # ── 第一階段：模型本身贏不贏得了天真基準 ──────────────────────────────
    print(f'\n{"="*70}\n第一階段：基礎特徵（{len(base_cols)} 個）能否勝過天真基準\n{"="*70}')
    stage1 = {}
    for key, spec in TARGETS.items():
        # 用 panel.align 而不是自己 dropna——它同時套用日期下限，
        # 擋掉 2012 以前那批「籌碼特徵是捏造的零」的列
        dd = P.align(d, BASE_BLOCKS, extra_required=[spec['y'], spec['base']])
        spec = dict(spec, blend=(key in BLEND_WITH_BASE))
        folds = walk_forward(dd, base_cols, spec, args.folds)
        s = summarise(folds)
        if not s:
            print(f'  {spec["label"]:12} 樣本不足，略過')
            continue
        s['folds'] = folds
        s['n_rows'] = len(dd)
        s['span'] = f'{dd.trade_date.min().date()} ~ {dd.trade_date.max().date()}'
        stage1[key] = s
        verdict = ('可新增' if s['gain'] >= MIN_GAIN and s['all_folds_win']
                   else '不新增')
        print(f'  {spec["label"]:12} {len(dd):>7,} 列  '
              f'排序相關 {s["rank_corr"]:+.4f}（基準 {s["base_rank_corr"]:+.4f}，'
              f'差距 {s["gain"]:+.4f}）  最差折 {s["worst_fold_gain"]:+.4f}  '
              f'前後 20% 實際值差 {s["spread"]:+.4f}  '
              f'實際報酬差 {s["ret_spread"]:+.2%}  → {verdict}')

    # ── 第二階段：夜盤與期貨結構有沒有增量 ────────────────────────────────
    stage2 = {}
    if args.stage2:
        combos = [('基礎', BASE_BLOCKS),
                  ('＋夜盤', BASE_BLOCKS + ['night']),
                  ('＋夜盤＋期貨結構', BASE_BLOCKS + ['night', 'futures'])]
        print(f'\n{"="*70}\n第二階段：外生區塊消融（同一批樣本）\n{"="*70}')
        for key, spec in TARGETS.items():
            if key not in stage1:
                continue
            # 第二階段必須沿用第一階段的混合設定，否則兩階段的數字不可比
            spec = dict(spec, blend=(key in BLEND_WITH_BASE))
            widest = P.columns_for(BASE_BLOCKS + ['night', 'futures'])
            widest = [c for c in widest if c in d.columns]
            dd = P.align(d, BASE_BLOCKS + ['night', 'futures'],
                         extra_required=[spec['y'], spec['base']])
            print(f'\n  {spec["label"]}（共同樣本 {len(dd):,} 列，'
                  f'{dd.trade_date.min().date()} 起）')
            rows = []
            for name, blocks in combos:
                cols = [c for c in P.columns_for(blocks) if c in dd.columns]
                s = summarise(walk_forward(dd, cols, spec, args.folds))
                if not s:
                    continue
                s['name'], s['n_features'] = name, len(cols)
                rows.append(s)
                print(f'    {name:18} 特徵 {len(cols):>3} 個　'
                      f'排序相關 {s["rank_corr"]:+.4f}（基準 {s["base_rank_corr"]:+.4f}）　'
                      f'實際報酬差 {s["ret_spread"]:+.2%}')
            stage2[key] = {'rows': rows, 'n_rows': len(dd),
                           'span': f'{dd.trade_date.min().date()} ~ {dd.trade_date.max().date()}'}

    write_report(stage1, stage2, base_cols, args)


def write_report(stage1, stage2, base_cols, args):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, 'new_model_candidates.md')
    L = [
        '# 新模型候選評估（Iteration 31）',
        '',
        f'**執行時間：** {datetime.now().strftime("%Y-%m-%d %H:%M")}',
        f'**驗證：** {args.folds} 折擴張視窗走查 + {HORIZON} 日標籤期封存',
        f'**基礎特徵：** {len(base_cols)} 個（price + chip + cs + market）',
        f'**新增門檻：** 排序相關須高出天真基準 +{MIN_GAIN:.2f}，且每一折都不輸',
        '',
        '## 選題依據',
        '',
        '這份資料已反覆證實：方向預測沒有 edge（LSTM 46.9~50.6%、M3 在 2018 後 51.53%），',
        '量級與排序有（波動率 0.606、振幅 0.654、跳空 0.704）。',
        '故候選一律不做第四個方向預測器，改補決策實際需要、目前卻沒有的量。',
        '',
        '## 第一階段：能否勝過天真基準',
        '',
        '| 候選 | 用途 | 樣本 | 期間 | 排序相關 | 天真基準 | 差距 | 最差折 | 前後20%實際報酬差 | 判定 |',
        '|------|------|------|------|---------|---------|------|--------|-----------------|------|',
    ]
    for key, s in stage1.items():
        spec = TARGETS[key]
        ok = s['gain'] >= MIN_GAIN and s['all_folds_win']
        L.append(f"| **{spec['label']}** | {spec['use']} | {s['n_rows']:,} | {s['span']} | "
                 f"{s['rank_corr']:+.4f} | {s['base_rank_corr']:+.4f} | "
                 f"{s['gain']:+.4f} | {s['worst_fold_gain']:+.4f} | "
                 f"{s['ret_spread']:+.2%} | "
                 f"{'**可新增**' if ok else '不新增'} |")

    L += ['', '### 逐折明細', '']
    for key, s in stage1.items():
        L += [f"**{TARGETS[key]['label']}**", '',
              '| 折 | 測試期 | 訓練列 | 測試列 | 排序相關 | 基準 | MAE | 基準 MAE |',
              '|----|--------|-------|-------|---------|------|-----|---------|']
        for f in s['folds']:
            L.append(f"| {f['fold']} | {f['from']} ~ {f['to']} | {f['n_train']:,} | "
                     f"{f['n_test']:,} | {f['rank_corr']:+.4f} | {f['base_rank_corr']:+.4f} | "
                     f"{f['mae']:.4f} | {f['base_mae']:.4f} |")
        L.append('')

    if stage2:
        L += ['## 第二階段：夜盤與期貨結構的增量', '',
              '樣本砍到 2018 起（期貨資料起點），三個變體共用同一批列。', '']
        for key, blk in stage2.items():
            L += [f"**{TARGETS[key]['label']}**（{blk['n_rows']:,} 列，{blk['span']}）", '',
                  '| 特徵組合 | 特徵數 | 排序相關 | 相關係數 | MAE |',
                  '|---------|-------|---------|---------|-----|']
            for r in blk['rows']:
                L.append(f"| {r['name']} | {r['n_features']} | {r['rank_corr']:+.4f} | "
                         f"{r['corr']:+.4f} | {r['mae']:.4f} |")
            L.append('')

    L += ['## 天真基準是什麼', '',
          '| 候選 | 基準 | 為什麼是這個 |',
          '|------|------|------------|',
          '| 成交量 | 未來 5 日均量 = 最近 5 日均量 | 量能自相關極強，'
          '常數基準會讓任何模型都贏。要打敗的是「量能持續」這個假設 |',
          '| 下檔風險 | −1.65 × EWMA 日波動 × √5 | 常態假設下的 5% 分位，'
          '業界推停損最常見的做法，也是 `risk_model` 現在實質在做的事 |',
          '| 相對強弱 | 過去 20 日報酬的同日百分位 | 動能延續假設。'
          '若模型贏不過它，代表「相對強弱」只是動能的複述 |',
          '']
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    print(f'\n報告已寫入 {path}')


if __name__ == '__main__':
    main()
