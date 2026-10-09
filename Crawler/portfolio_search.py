"""
月調倉回測的網格搜尋（Iteration 50）：一次跑一批設定，每一個都正式寫進實驗日誌（N 加 1），印一張總表。

規則（不能破）：
    · 只在開發期（dev 2018-01~2021-12）搜；候選要到驗證期（valid 2022-01~2024-09）確認，DSR 用累積的 N。
    · 保留期（2024-10 起）不碰。
    · 每個設定一列，不挑著記——失敗的也算 N。

用法：
    python portfolio_search.py --round turnover            # 預設網格之一
    python portfolio_search.py --grid grid.json            # 自己的設定清單 [{signal, tranches, buffer, universe_n, weighting, top_n}, ...]
    python portfolio_search.py --round turnover --segment valid --only "win-t3,win3-t3"
"""

import argparse
import json
import logging
from datetime import datetime

import portfolio_backtest as pb

logger = logging.getLogger(__name__)

ROUNDS = {
    # 第一輪：換手。同一個訊號，從月月重排到分批輪動；緩衝區放大
    'turnover': [
        dict(signal='win', tranches=3), dict(signal='win', tranches=6), dict(signal='win', buffer=100), dict(signal='win', buffer=150),
        dict(signal='win3', tranches=1), dict(signal='win3', tranches=3), dict(signal='win3', tranches=6),
        dict(signal='sue', tranches=3), dict(signal='sue', tranches=6),
    ],
    # 第二輪：股票池大小與權重（接近 0050 的大型股 vs 更廣）
    'universe': [
        dict(signal='win', tranches=3, universe_n=100), dict(signal='win', tranches=3, universe_n=150), dict(signal='win', tranches=3, universe_n=500),
        dict(signal='win', tranches=3, weighting='liq'), dict(signal='win', tranches=3, universe_n=100, weighting='liq'),
        dict(signal='win', tranches=3, top_n=30), dict(signal='win', tranches=3, top_n=10),
    ],
    # 第四輪：固定持有台積電（0050 權重用滾動迴歸估），其餘資金才選股——把追蹤誤差從 20% 壓下來
    'tsmc': [
        dict(signal='win', tranches=3, universe_n=150, tsmc_weight='est'), dict(signal='win3+mom', tranches=3, tsmc_weight='est'),
        dict(signal='win', buffer=150, tsmc_weight='est'), dict(signal='win+mom', tranches=3, universe_n=150, tsmc_weight='est'),
        dict(signal='sue', tranches=6, tsmc_weight='est'), dict(signal='mom', tranches=6, tsmc_weight='est'),
        dict(signal='win', tranches=3, tsmc_weight='est'), dict(signal='win3+mom', tranches=6, tsmc_weight='est'),
    ],
    # 第五輪（Iteration 53）：不同假設的訊號家族，同一個結構（分三批、持台積電），dev 與 valid 各跑一次、不調參
    'families': [
        dict(signal='rev_accel', tranches=3, tsmc_weight='est'), dict(signal='rev_streak', tranches=3, tsmc_weight='est'),
        dict(signal='lowvol', tranches=3, tsmc_weight='est'), dict(signal='hi52', tranches=3, tsmc_weight='est'),
        dict(signal='rev1m', tranches=3, tsmc_weight='est'), dict(signal='volchg', tranches=3, tsmc_weight='est'),
        dict(signal='win3+mom+lowvol', tranches=3, tsmc_weight='est'), dict(signal='mom+hi52', tranches=3, tsmc_weight='est'),
        dict(signal='rev_accel+mom', tranches=3, tsmc_weight='est'), dict(signal='win3+mom+rev_streak', tranches=3, tsmc_weight='est'),
    ],
    # 第三輪：訊號組合（排名平均）
    'combo': [
        dict(signal='mom', tranches=3), dict(signal='win+mom', tranches=3), dict(signal='win+sue', tranches=3),
        dict(signal='win3+mom', tranches=3), dict(signal='win+mom+sue', tranches=3), dict(signal='win+mom', tranches=6),
        dict(signal='win+mom', tranches=3, universe_n=150), dict(signal='mom', tranches=6),
    ],
}


def label(cfg: dict) -> str:
    bits = [cfg['signal']]
    if cfg.get('tranches', 1) > 1:
        bits.append(f"t{cfg['tranches']}")
    else:
        bits.append(f"b{cfg.get('buffer', 40)}")
    if cfg.get('universe_n', 300) != 300:
        bits.append(f"u{cfg['universe_n']}")
    if cfg.get('top_n', 20) != 20:
        bits.append(f"n{cfg['top_n']}")
    if cfg.get('weighting', 'equal') != 'equal':
        bits.append(cfg['weighting'])
    if cfg.get('tsmc_weight'):
        bits.append(f"tsmc{cfg['tsmc_weight']}")
    return '-'.join(bits)


def run_grid(configs: list, segment: str, notes: str = '', save: bool = True) -> list:
    cache: dict = {}
    rows = []
    for i, cfg in enumerate(configs, 1):
        cfg = dict(cfg)
        name = f"{label(cfg)}-{segment}"
        logger.info('[search] (%d/%d) %s', i, len(configs), name)
        try:
            res = pb.run(cfg['signal'], segment, top_n=cfg.get('top_n', 20), buffer=cfg.get('buffer', 40), universe_n=cfg.get('universe_n', 300),
                         excl_limit_pct=cfg.get('excl_limit_pct', 0.10), tsmc_weight=cfg.get('tsmc_weight'), name=name,
                         notes=notes or f'網格 {segment}', save=save, tranches=cfg.get('tranches', 1), weighting=cfg.get('weighting', 'equal'),
                         _cache=cache)
        except Exception as e:      # noqa: BLE001
            logger.error('[search] %s 失敗：%s', name, e)
            rows.append({'name': name, 'error': str(e)})
            continue
        m = res['metrics']
        rows.append({'n': m['experiment_n'], 'name': name, 'ann_active': m['ann_active'], 'ir': m['info_ratio'], 'dsr': m['dsr'],
                     'win': m['monthly_win_rate'], 'turnover': m['turnover_annual'], 'cost': m['cost_drag_annual'], 'te': m['tracking_error'],
                     'rel_mdd': m['rel_mdd'], 'cagr': m['cagr_port'], 'bench': m['cagr_bench']})
    return rows


def table(rows: list) -> str:
    L = ['| N | 設定 | 年化主動 | IR | DSR | 月勝率 | 換手 | 成本/年 | 追蹤誤差 | 相對最大落後 |', '|---|---|---|---|---|---|---|---|---|---|']
    for r in sorted(rows, key=lambda x: -(x.get('ann_active') if x.get('ann_active') is not None else -9)):
        if 'error' in r:
            L.append(f"| | {r['name']} | 失敗：{r['error'][:60]} | | | | | | | |")
            continue
        L.append(f"| {r['n']} | {r['name']} | {r['ann_active'] * 100:+.2f}% | {r['ir']} | {r['dsr']:.3f} | {r['win'] * 100:.0f}% | {r['turnover']:.1f} | "
                 f"{r['cost'] * 100:.2f}% | {r['te'] * 100:.1f}% | {r['rel_mdd'] * 100:.1f}% |")
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--round', choices=list(ROUNDS))
    ap.add_argument('--grid', help='JSON 檔：設定清單')
    ap.add_argument('--segment', default='dev', choices=['dev', 'valid'])
    ap.add_argument('--only', help='只跑名字裡含這些片段的設定，逗號分隔')
    ap.add_argument('--notes', default='')
    ap.add_argument('--no-save', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    configs = ROUNDS[a.round] if a.round else json.load(open(a.grid, encoding='utf-8'))
    if a.only:
        keys = [k.strip() for k in a.only.split(',')]
        configs = [c for c in configs if any(k in label(c) for k in keys)]
    t0 = datetime.now()
    rows = run_grid(configs, a.segment, a.notes, save=not a.no_save)
    print(f"\n## 網格 {a.round or a.grid} on {a.segment}（{len(rows)} 個設定，{(datetime.now() - t0).total_seconds():.0f} 秒）\n")
    print(table(rows))


if __name__ == '__main__':
    main()
