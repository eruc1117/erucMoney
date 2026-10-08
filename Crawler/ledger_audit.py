"""
預測台帳稽核（Iteration 32）
────────────────────────────
回答兩個問題，兩個都是原本會靜默出錯的地方：

    1. 該寫台帳的模型，今天寫了嗎？
    2. 已經到期的預測，結算了嗎？

## 為什麼需要這支

`gap_model._log_all` / `range_model._log_all` / `volume_model._log_all` 的例外
一律只記 `logger.warning`——這是刻意的，台帳是附帶效果，不該拖垮預測本身。
代價是寫入失敗完全不會浮上檯面：2026-08-10 那次，gap 與 range 因為特徵
缺失整批沒寫進台帳，前端一切正常，是人去翻資料庫才發現。

結算端同理：`resolve_predictions` 跑不跑得成沒人盯，不跑就只是台帳裡
`actual_value` 一直是 NULL，而「尚未到期」和「漏結算」在畫面上長得一模一樣。

## 這支查不出什麼

覆蓋檢查看的是「今天有沒有紀錄」，**分不出「寫入失敗」和「今天根本沒人叫它跑」**。
兩者都是要處理的狀況，所以不去區分；但看到 missing 時別直接斷定是寫入壞了，
先確認今天有沒有跑過投票或推論。

判斷「該寫」的依據是 `MODEL_TYPES[...]['logs_ledger']`，不是猜的——
LSTM 那 10 個類型本來就不落台帳，猜的話會天天誤報。

    3. 跳空模型的預測，是不是其實在描述「已經發生」的跳空？（2026-09-29 新增）

第三題來自 2026-09-20 的準確度報告：跳空 v2 線上 230 筆的預測值與**預測當天已實現**的
跳空相關 0.76、與目標日只有 −0.03——推論端把當天早上收的夜盤當成明天的。gate 只看
「方向準確率沒過」，沒人分得出那是樣本不夠還是對齊錯。所以這裡直接量：預測值對
predicted_on 當天已實現跳空的相關，超過 LEAK_CORR 就報問題。

用法：
    python ledger_audit.py              # 印出稽核結果
    python ledger_audit.py --json
"""

import argparse
import json
import logging
from datetime import date

logger = logging.getLogger(__name__)

# 台帳落後幾個日曆日才算異常。市場基準日是最後一個有行情的交易日，
# 模型當天稍晚才跑是常態，故當日與前一日都算正常。
STALE_AFTER_DAYS = 2

# 到期後幾個日曆日仍未結算才算漏結算。target_date 寫入時是用行事曆推估的，
# 回填時才會校正成真正的交易日（見 resolve_predictions 的說明），
# 故要留出推估誤差 + 遇到連假的緩衝。
OVERDUE_GRACE_DAYS = 5

# 洩漏／對齊自檢：預測值與「預測當天已實現」目標值的相關超過這個數就是在描述過去。
# 真正的隔日跳空預測與當天跳空只剩一點自相關（走查裡 own_gap_ma5 的貢獻很小）。
LEAK_CORR = 0.5
LEAK_MIN_N = 30

LEAK_SQL = """
WITH px AS (
    SELECT stock_id, trade_date,
           open_price / NULLIF(LAG(close_price) OVER (PARTITION BY stock_id ORDER BY trade_date), 0) - 1
               AS gap_today
      FROM stock_daily_prices
     WHERE trade_date >= %s
)
SELECT v.model_type, v.version,
       corr(p.predicted_value::float, px.gap_today::float) AS r_today,
       corr(p.predicted_value::float, p.actual_value::float)  AS r_target,
       COUNT(*)
  FROM model_predictions p
  JOIN model_versions v ON v.id = p.model_version_id
  JOIN px ON px.stock_id = p.stock_id AND px.trade_date = p.predicted_on
 WHERE v.target_kind = 'gap'
   AND p.actual_value IS NOT NULL
   AND p.invalid_reason IS NULL
 GROUP BY 1, 2
 ORDER BY 1, 2
"""


def _market_last(cur):
    cur.execute("SELECT MAX(trade_date) FROM stock_daily_prices")
    row = cur.fetchone()
    return row[0] if row else None


def _us_market_last(cur):
    """美股模型（Iteration 32）的基準日在另一個市場的日曆上。

    用台股基準日去量美股模型，勞動節那種美股獨有的休市就會被報成「落後 4 天」——
    稽核工具自己誤報，比沒有稽核更糟。"""
    cur.execute("SELECT MAX(trade_date) FROM us_daily_prices")
    row = cur.fetchone()
    return row[0] if row else None


def _baseline_for(meta, tw_last, us_last):
    from resolve_predictions import US_KINDS
    return us_last or tw_last if meta.get('target_kind') in US_KINDS else tw_last


def audit(as_of: date = None) -> dict:
    """
    回傳 {
        'available': bool,
        'market_last': '2026-08-10',
        'coverage': [ {model_type, label, version, is_serving, status,
                       last_predicted_on, days_behind, rows_last} ],
        'unresolved': [ {model_type, version, target_date, n, days_overdue} ],
        'problems': ['...'],       # 給人看的摘要，空的代表沒事
    }

    `status`：ok（基準日有紀錄）／stale（有紀錄但落後）／missing（從來沒寫過）。
    """
    import model_registry as registry
    from db.connection import get_conn

    expected = {k: m for k, m in registry.MODEL_TYPES.items()
                if m.get('logs_ledger')}

    with get_conn() as conn:
        with conn.cursor() as cur:
            market_last = as_of or _market_last(cur)
            us_last = as_of or _us_market_last(cur)
            if market_last is None:
                return {'available': False, 'reason': '無行情資料，無從比對'}

            cur.execute("""
                SELECT model_version_id, MAX(predicted_on)
                  FROM model_predictions GROUP BY model_version_id
            """)
            last_by_ver = dict(cur.fetchall())

            cur.execute("""
                SELECT model_version_id, predicted_on, COUNT(*)
                  FROM model_predictions
                 GROUP BY model_version_id, predicted_on
            """)
            rows_by = {(v, d): n for v, d, n in cur.fetchall()}

            # 到期未結算：target_date 已過且超出推估誤差緩衝
            cur.execute("""
                SELECT mv.model_type, mv.version, p.target_date, COUNT(*),
                       mv.target_kind
                  FROM model_predictions p
                  JOIN model_versions mv ON mv.id = p.model_version_id
                 WHERE p.actual_value IS NULL
                   AND p.target_date < GREATEST(%s, %s)
                 GROUP BY 1, 2, 3, 5 ORDER BY 3
            """, (market_last, us_last or market_last))
            overdue_raw = cur.fetchall()

    coverage, problems = [], []
    for mt, meta in sorted(expected.items()):
        versions = registry.loadable_versions(mt)
        for ver, _path, serving in versions:
            if ver is None:
                # 資料庫沒有版本列，推論端會直接吃工作區檔案、也就寫不了台帳
                problems.append(f'{mt}：無版本紀錄，台帳無從歸屬')
                continue
            last = last_by_ver.get(ver['id'])
            baseline = _baseline_for(meta, market_last, us_last)
            if last is None:
                status, behind = 'missing', None
            else:
                behind = (baseline - last).days
                status = 'ok' if behind <= STALE_AFTER_DAYS else 'stale'
            coverage.append({
                'model_type': mt,
                'label': meta.get('label', mt),
                'version': ver['version'],
                'is_serving': bool(serving),
                'status': status,
                'last_predicted_on': last.isoformat() if last else None,
                'days_behind': behind,
                'rows_last': rows_by.get((ver['id'], last)) if last else 0,
            })
            role = '服役' if serving else '影子'
            if status == 'missing':
                problems.append(f'{mt} v{ver["version"]}（{role}）從未寫入台帳')
            elif status == 'stale':
                problems.append(
                    f'{mt} v{ver["version"]}（{role}）台帳停在 {last}，'
                    f'落後基準日 {behind} 天')

    leaks = _leak_check()

    from resolve_predictions import US_KINDS
    unresolved = []
    for mt, v, tgt, n, kind in overdue_raw:
        base = (us_last or market_last) if kind in US_KINDS else market_last
        days = (base - tgt).days
        if days < OVERDUE_GRACE_DAYS:
            continue                      # 還在 target_date 推估誤差的範圍內
        unresolved.append({'model_type': mt, 'version': v,
                           'target_date': tgt.isoformat(),
                           'n': n, 'days_overdue': days})
    if unresolved:
        total = sum(u['n'] for u in unresolved)
        problems.append(f'{total} 筆預測到期逾 {OVERDUE_GRACE_DAYS} 天仍未結算'
                        f'（最舊 {unresolved[0]["target_date"]}）')

    for lk in leaks:
        if lk['n'] >= LEAK_MIN_N and lk['r_today'] is not None and lk['r_today'] > LEAK_CORR:
            rg = '—' if lk['r_target'] is None else f'{lk["r_target"]:+.2f}'
            problems.append(
                f'{lk["model_type"]} v{lk["version"]}：預測值與預測當天已實現的跳空相關 '
                f'{lk["r_today"]:+.2f}（與目標日 {rg}），在描述已發生的事——推論端對齊錯誤')

    return {
        'available': True,
        'market_last': market_last.isoformat(),
        'us_market_last': us_last.isoformat() if us_last else None,
        'coverage': coverage,
        'unresolved': unresolved,
        'leak_checks': leaks,
        'problems': problems,
    }


def _leak_check() -> list:
    """跳空類版本：預測值對 predicted_on 當天已實現跳空的相關。查不到就回空（不擋稽核）。"""
    from db.connection import get_conn
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MIN(predicted_on) FROM model_predictions")
                since = (cur.fetchone() or [None])[0]
                if since is None:
                    return []
                cur.execute(LEAK_SQL, (since,))
                return [{'model_type': mt, 'version': v,
                         'r_today': float(rt) if rt is not None else None,
                         'r_target': float(rg) if rg is not None else None,
                         'n': int(n)}
                        for mt, v, rt, rg, n in cur.fetchall()]
    except Exception as e:
        logger.warning('[audit] 對齊自檢失敗：%s', e)
        return []


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s [%(levelname)s] %(message)s')
    ap = argparse.ArgumentParser(description='預測台帳覆蓋與結算稽核')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    res = audit()
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif not res.get('available'):
        print(f'稽核無法進行：{res.get("reason")}')
    else:
        print(f'市場基準日 {res["market_last"]}\n')
        print(f'{"模型":<14}{"版本":<6}{"角色":<6}{"狀態":<9}{"最後寫入":<13}{"筆數"}')
        for c in res['coverage']:
            print(f'{c["model_type"]:<14}v{c["version"]:<5}'
                  f'{"服役" if c["is_serving"] else "影子":<6}'
                  f'{c["status"]:<9}{c["last_predicted_on"] or "—":<13}'
                  f'{c["rows_last"] or 0}')
        if res.get('leak_checks'):
            print('\n對齊自檢（預測值 vs 預測當天已實現跳空 / vs 目標日）：')
            for lk in res['leak_checks']:
                rt = '—' if lk['r_today'] is None else f'{lk["r_today"]:+.2f}'
                rg = '—' if lk['r_target'] is None else f'{lk["r_target"]:+.2f}'
                print(f'  {lk["model_type"]} v{lk["version"]}：{rt} / {rg}（{lk["n"]} 筆）')
        if res['unresolved']:
            print('\n到期未結算：')
            for u in res['unresolved']:
                print(f'  {u["model_type"]} v{u["version"]} '
                      f'target {u["target_date"]}：{u["n"]} 筆'
                      f'（逾期 {u["days_overdue"]} 天）')
        print()
        # 這裡刻意不用 ⚠／✓：Windows 終端是 cp950，印不出來會直接 UnicodeEncodeError，
        # 讓稽核自己掛掉——一支用來抓靜默失敗的工具，不該有自己的失敗模式。
        if res['problems']:
            for p in res['problems']:
                print(f'[!] {p}')
        else:
            print('[OK] 台帳覆蓋與結算皆正常')
