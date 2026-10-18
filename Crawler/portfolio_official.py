"""
正式策略（Iteration 64）：候選升格、保留期開一次、每日更新的淨值。

    promote(candidate_run_id=44, note='…')   升格：(1) 用候選參數跑保留期一次（segment holdout，寫日誌、凍結、tag official）
                                               (2) 用同參數跑 2018-01-01 → 今天建 live 列（segment live，tag official-live）
                                               (3) 寫 portfolio_official。已升格就拒絕（保留期只能開一次）。
    update_daily(today)                      每天 18:50：live 列用同參數重算到最新行情，覆寫 metrics／series／positions（不算新實驗，N 不動）
    status()                                 給頁面：候選／保留期／live 的指標、live 淨值曲線、逐年、本月清單、紙上帳戶摘要

用法：
    python portfolio_official.py --promote 44 --note "理由"
    python portfolio_official.py --update
    python portfolio_official.py --status
"""
import argparse
import json
import logging
from datetime import date, datetime
from typing import Optional

import portfolio_backtest as pb
from db.connection import get_conn

logger = logging.getLogger(__name__)

HOLDOUT_START = date(2024, 10, 1)
FULL_START = date(2018, 1, 1)


def state() -> Optional[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT candidate_run_id, holdout_run_id, live_run_id, promoted_on, note, last_update_at, last_update_end, last_error
                           FROM portfolio_official WHERE id = 1""")
            r = cur.fetchone()
    if not r:
        return None
    return {'candidate_run_id': r[0], 'holdout_run_id': r[1], 'live_run_id': r[2], 'promoted_on': str(r[3]), 'note': r[4],
            'last_update_at': r[5].isoformat() if r[5] else None, 'last_update_end': str(r[6]) if r[6] else None, 'last_error': r[7]}


def _params(run_id: int) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT signal, params, name FROM portfolio_runs WHERE id = %s", (run_id,))
            r = cur.fetchone()
    if not r:
        raise ValueError(f'run {run_id} 不存在')
    p = dict(r[1] or {})
    p['signal'] = r[0]
    p['_name'] = r[2]
    return p


def _run_with(p: dict, segment: str, start: Optional[date], end: Optional[date], name: str, notes: str, save: bool = True) -> dict:
    return pb.run(p['signal'], segment, start, end, p.get('top_n', 20), p.get('buffer', 40), p.get('universe_n', 300),
                  p.get('excl_limit_pct', 0.10), p.get('tsmc_weight'), p.get('costs', pb.COSTS), name=name, notes=notes, save=save,
                  tranches=p.get('tranches', 1), weighting=p.get('weighting', 'equal'))


def promote(candidate_run_id: int = 44, note: str = '', today: Optional[date] = None) -> dict:
    """升格。保留期只能開一次：已有 portfolio_official 或日誌裡已有 holdout 列就拒絕。"""
    if state():
        raise RuntimeError('已經有正式策略了（保留期只能開一次）；要換策略請在文件記下理由並手動處理')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM portfolio_runs WHERE segment = 'holdout' LIMIT 1")
            if cur.fetchone():
                raise RuntimeError('日誌裡已經有保留期的列：保留期只能開一次')
    today = today or date.today()
    p = _params(candidate_run_id)
    base = p['_name'].replace('-dev+valid', '').replace('-dev', '').replace('-valid', '')
    logger.info('[official] 開保留期：候選 #%d %s，%s → %s', candidate_run_id, base, HOLDOUT_START, today)
    hold = _run_with(p, 'holdout', HOLDOUT_START, today, f'{base}-holdout',
                     f'保留期（只開一次）。{note}'.strip())
    pb.tag_run(hold['run_id'], 'official')
    logger.info('[official] 建 live 列：%s → %s', FULL_START, today)
    live = _run_with(p, 'live', FULL_START, today, f'{base}-live', f'正式策略，每日 18:50 重算到最新行情（不算新實驗）。{note}'.strip())
    pb.tag_run(live['run_id'], 'official-live')
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO portfolio_official (id, candidate_run_id, holdout_run_id, live_run_id, promoted_on, note, last_update_at, last_update_end)
                           VALUES (1, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)""",
                        (candidate_run_id, hold['run_id'], live['run_id'], today, note, pb.met_end(live['metrics'])))
        conn.commit()
    return {'candidate_run_id': candidate_run_id, 'holdout': {'run_id': hold['run_id'], 'experiment_n': hold['experiment_n'], 'metrics': hold['metrics']},
            'live': {'run_id': live['run_id'], 'experiment_n': live['experiment_n'], 'metrics': live['metrics']}}


def rerun_holdout(note: str, warmup_days: int = 420, today: Optional[date] = None) -> dict:
    """保留期用修正後的資料再算一次（使用者明確決定才做）：同參數、加暖機（動能要 252 個交易日歷史），
    舊的保留期列 tag 改 'void'（留著當證據，不刪、不算 N 減少），新列 tag 'official'，portfolio_official.holdout_run_id 指到新列。"""
    st = state()
    if not st:
        raise RuntimeError('還沒有正式策略')
    today = today or date.today()
    p = _params(st['candidate_run_id'])
    base = p['_name'].replace('-dev+valid', '').replace('-dev', '').replace('-valid', '')
    old = st['holdout_run_id']
    hold = pb.run(p['signal'], 'holdout', HOLDOUT_START, today, p.get('top_n', 20), p.get('buffer', 40), p.get('universe_n', 300),
                  p.get('excl_limit_pct', 0.10), p.get('tsmc_weight'), p.get('costs', pb.COSTS), name=f'{base}-holdout',
                  notes=f'保留期第二次（資料修正後重跑，取代 #{old}）。{note}'.strip(), save=True,
                  tranches=p.get('tranches', 1), weighting=p.get('weighting', 'equal'), warmup_days=warmup_days)
    pb.tag_run(hold['run_id'], 'official')
    with get_conn() as conn:
        with conn.cursor() as cur:
            if old:
                cur.execute("UPDATE portfolio_runs SET tag = 'void', notes = COALESCE(notes, '') || %s WHERE id = %s",
                            (f'｜作廢：對手 0050 分割未還原且無暖機，由 #{hold["run_id"]} 取代（{today}）', old))
            cur.execute("UPDATE portfolio_official SET holdout_run_id = %s, note = COALESCE(note, '') || %s WHERE id = 1",
                        (hold['run_id'], f'｜{today} 保留期重跑 #{hold["run_id"]}（取代 #{old}）：{note}'))
        conn.commit()
    logger.info('[official] 保留期重跑：#%d 取代 #%s，年化主動 %+.2f%%、IR %s', hold['run_id'], old, hold['metrics']['ann_active'] * 100, hold['metrics']['info_ratio'])
    return {'holdout': {'run_id': hold['run_id'], 'experiment_n': hold['experiment_n'], 'metrics': hold['metrics']}, 'replaced': old}


def update_run_in_place(run_id: int, res: dict) -> dict:
    """把一次重算的結果覆寫到既有的列：metrics（保留原本的 experiment_n／dsr 等實驗欄位不動）、period_end、positions、series。"""
    from psycopg2.extras import execute_values
    import pandas as pd
    met = dict(res['metrics'])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT metrics FROM portfolio_runs WHERE id = %s", (run_id,))
            old = (cur.fetchone() or [{}])[0] or {}
            for k in ('experiment_n', 'dsr', 'sr_star_m', 'var_sharpe_prior'):
                if k in old:
                    met[k] = old[k]
            cur.execute("UPDATE portfolio_runs SET metrics = %s, period_end = %s, n_rebalances = %s WHERE id = %s",
                        (json.dumps(met, ensure_ascii=False), pb.met_end(met), met.get('n_rebalances', 0), run_id))
            cur.execute("DELETE FROM portfolio_positions WHERE run_id = %s", (run_id,))
            pos = res['positions']
            if len(pos):
                execute_values(cur, """INSERT INTO portfolio_positions (run_id, rebalance_date, exec_date, stock_id, rank, signal_value, target_weight, filled)
                                       VALUES %s ON CONFLICT DO NOTHING""",
                               [(run_id, r.rebalance_date, r.exec_date, r.stock_id, None if pd.isna(r.rank) else int(r.rank),
                                 None if pd.isna(r.signal_value) else float(r.signal_value), float(r.target_weight), bool(r.filled))
                                for r in pos.itertuples(index=False)], page_size=1000)
        conn.commit()
    n = pb.save_series(run_id, pb.series_frame(res['nav'], res['bench']))
    return {'run_id': run_id, 'points': n, 'end': met['end'], 'ann_active': met['ann_active']}


def update_daily(today: Optional[date] = None, force: bool = False) -> dict:
    """排程入口：live 列重算到最新行情。沒升格就略過；行情沒新的也略過（force=True 照樣重算，資料修正後用）。"""
    st = state()
    if not st:
        return {'skipped': '還沒有正式策略（python portfolio_official.py --promote 44）'}
    today = today or date.today()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT max(trade_date) FROM market_daily_prices")
            last_mkt = cur.fetchone()[0]
    if not last_mkt:
        return {'skipped': '沒有行情'}
    if not force and st['last_update_end'] and str(last_mkt) <= st['last_update_end']:
        return {'skipped': f'行情沒有比 {st["last_update_end"]} 更新的'}
    try:
        p = _params(st['live_run_id'])
        res = _run_with(p, 'live', FULL_START, min(today, last_mkt), p['_name'], '', save=False)
        out = update_run_in_place(st['live_run_id'], res)
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE portfolio_official SET last_update_at = CURRENT_TIMESTAMP, last_update_end = %s, last_error = NULL WHERE id = 1", (out['end'],))
            conn.commit()
        logger.info('[official] live 更新到 %s：%d 點、年化主動 %+.2f%%', out['end'], out['points'], out['ann_active'] * 100)
        return out
    except Exception as e:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE portfolio_official SET last_error = %s WHERE id = 1", (f'{type(e).__name__}: {e}',))
            conn.commit()
        raise


def status() -> dict:
    """給頁面。"""
    import portfolio_api
    st = state()
    if not st:
        return {'promoted': False}
    cand = portfolio_api.get_run(st['candidate_run_id'], step=5)
    hold = portfolio_api.get_run(st['holdout_run_id'], step=1) if st['holdout_run_id'] else None
    live = portfolio_api.get_run(st['live_run_id'], step=5) if st['live_run_id'] else None
    runs = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, segment, metrics, period_start, period_end, name, experiment_n, tag FROM portfolio_runs WHERE tag = 'candidate' OR id IN (%s, %s)",
                        (st['holdout_run_id'] or -1, st['live_run_id'] or -1))
            for rid, seg, met, ps, pe, name, n, tag in cur.fetchall():
                key = 'live' if rid == st['live_run_id'] else 'holdout' if rid == st['holdout_run_id'] else ('full' if str(ps) == '2018-01-01' and str(pe) == '2024-09-30' else seg)
                # 段別與標記的中文由 portfolio_api 統一給（Iteration 86：頁面不再自己寫死）；full 是候選的全期間列、資料表裡段別是 dev
                label = portfolio_api.SEGMENT_LABEL_FULL if key == 'full' else portfolio_api.SEGMENT_LABEL.get(key, key)
                runs[key] = {'id': rid, 'experiment_n': n, 'name': name, 'period_start': str(ps), 'period_end': str(pe), 'metrics': met or {},
                             'segment': seg, 'segment_label': label, 'tag': tag, 'tag_label': portfolio_api.tag_label(tag)}
    paper = portfolio_api.paper()
    return {'promoted': True, 'official': st, 'segments': runs, 'params': (cand or {}).get('run', {}).get('params'),
            'live_series': (live or {}).get('series', []), 'holdout_series': (hold or {}).get('series', []),
            'last_positions': (live or {}).get('positions', []), 'last_rebalance': (live or {}).get('last_rebalance'),
            'current_list': portfolio_api.live_list(), 'paper': {k: paper.get(k) for k in ('opened', 'review', 'pending')} if paper else None,
            'thresholds': portfolio_api.THRESHOLDS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--promote', type=int, metavar='RUN_ID'); ap.add_argument('--note', default='')
    ap.add_argument('--update', action='store_true'); ap.add_argument('--force', action='store_true'); ap.add_argument('--status', action='store_true')
    ap.add_argument('--rerun-holdout', action='store_true', help='保留期用修正後資料重跑一次（要在 --note 寫理由）')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    if a.promote:
        r = promote(a.promote, a.note)
        print(json.dumps({k: (v if k == 'candidate_run_id' else {kk: vv for kk, vv in v.items() if kk != 'metrics'} | {'ann_active': v['metrics']['ann_active'], 'info_ratio': v['metrics']['info_ratio'], 'end': v['metrics']['end']}) for k, v in r.items()}, ensure_ascii=False, indent=1))
    if a.rerun_holdout:
        r = rerun_holdout(a.note)
        m = r['holdout']['metrics']
        print(json.dumps({'run_id': r['holdout']['run_id'], 'replaced': r['replaced'], 'ann_active': m['ann_active'], 'info_ratio': m['info_ratio'], 'start': m['start'], 'end': m['end'], 'skipped_months': m.get('skipped_months')}, ensure_ascii=False))
    if a.update:
        print(update_daily(force=a.force))
    if a.status or not (a.promote or a.update or a.rerun_holdout):
        st = status()
        print(json.dumps({k: st[k] for k in ('promoted', 'official') if k in st}, ensure_ascii=False, indent=1, default=str))
        for k, v in (st.get('segments') or {}).items():
            m = v['metrics']
            print(f"{k:8s} #{v['experiment_n']} {v['period_start']}～{v['period_end']} 年化主動 {m.get('ann_active', 0) * 100:+.2f}% IR {m.get('info_ratio')}")


if __name__ == '__main__':
    main()
