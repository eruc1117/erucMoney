"""
用 Claude Code 訂閱額度（claude -p）對 input.jsonl 做結構化抽取。

每 15 則一批，system prompt 由 prompts/system.md 帶入，輸出用 --json-schema 強制結構。
可續跑：extracted.jsonl 已有的 news_id 會跳過。每批的 token 用量寫 usage_log.csv。

用法：
    python scripts/03_run_claude.py                     # 全部（預設 sonnet）
    python scripts/03_run_claude.py --limit 15          # 只跑一批（煙霧測試）
    python scripts/03_run_claude.py --model opus --out data/output/extracted_opus.jsonl
    python scripts/03_run_claude.py --dry-run           # 只印第一批的 prompt
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SYSTEM = os.path.join(ROOT, 'prompts', 'system.md')
SCHEMA = os.path.join(ROOT, 'prompts', 'schema.json')
ENUMS = {
    'event_type': {'earnings', 'guidance', 'm_and_a', 'regulation', 'macro_rate', 'geopolitics',
                   'supply_chain', 'product', 'legal', 'other'},
    'direction': {'positive', 'negative', 'neutral', 'mixed'},
    'scope': {'GLOBAL', 'US', 'TW'},
}


def build_prompt(batch: list) -> str:
    items = [{'news_id': b['news_id'], 'category': b['category'], 'published_at': b['published_at'],
              'title': b['title'], 'content': b['content']} for b in batch]
    return (f'以下 {len(batch)} 則新聞，依系統規則逐則分析，回傳 results 陣列（順序與長度同輸入）。\n\n'
            + json.dumps(items, ensure_ascii=False, indent=0))


def call_claude(prompt: str, system_file: str, schema: str, model: str, timeout: int = 300) -> dict:
    # schema 壓成單行；system prompt 走檔案（多行字串當命令列參數在 Windows 會被拆壞）。不加 --bare：它會略過登入憑證，回「Not logged in」
    import shutil
    exe = shutil.which('claude') or 'claude'
    cmd = [exe, '-p', '--no-session-persistence',
           '--output-format', 'json', '--json-schema', schema,
           '--system-prompt-file', system_file, '--tools', '', '--model', model]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          encoding='utf-8', timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f'claude 退出碼 {proc.returncode}：{proc.stderr[:500]}')
    obj = json.loads(proc.stdout)
    payload = obj.get('structured_output')
    if payload is None:
        raw = obj.get('result', '')
        raw = raw[raw.find('{'): raw.rfind('}') + 1]
        payload = json.loads(raw)
    return {'payload': payload, 'meta': obj}


def validate(results: list, batch: list) -> tuple[list, str]:
    want = [b['news_id'] for b in batch]
    got = {r.get('news_id'): r for r in results}
    missing = [i for i in want if i not in got]
    if missing:
        return [], f'缺 news_id {missing}'
    for r in results:
        for k, allowed in ENUMS.items():
            if r.get(k) not in allowed:
                return [], f'news_id {r.get("news_id")} {k}={r.get(k)!r} 不合法'
        if not (1 <= int(r.get('magnitude', 0)) <= 5):
            return [], f'news_id {r.get("news_id")} magnitude 越界'
    return [got[i] for i in want], 'ok'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=os.path.join(ROOT, 'data', 'input.jsonl'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'output', 'extracted.jsonl'))
    ap.add_argument('--model', default='sonnet')
    ap.add_argument('--batch-size', type=int, default=15)
    ap.add_argument('--limit', type=int, default=None, help='最多處理幾則')
    ap.add_argument('--sleep', type=float, default=4.0)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.input, encoding='utf-8') if l.strip()]
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    done = set()
    if os.path.exists(a.out):
        done = {json.loads(l)['news_id'] for l in open(a.out, encoding='utf-8') if l.strip()}
    todo = [r for r in rows if r['news_id'] not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f'輸入 {len(rows)} 則，已完成 {len(done)}，本次 {len(todo)} 則，模型 {a.model}')

    system = SYSTEM
    schema = json.dumps(json.load(open(SCHEMA, encoding='utf-8')), separators=(',', ':'))
    usage_path = os.path.join(os.path.dirname(a.out), 'usage_log.csv')
    new_usage = not os.path.exists(usage_path)

    batches = [todo[i:i + a.batch_size] for i in range(0, len(todo), a.batch_size)]
    if a.dry_run and batches:
        print(build_prompt(batches[0]))
        return

    with open(a.out, 'a', encoding='utf-8') as fout, \
         open(usage_path, 'a', newline='', encoding='utf-8') as fu:
        uw = csv.writer(fu)
        if new_usage:
            uw.writerow(['ts', 'model', 'batch', 'n', 'status', 'input_tokens', 'output_tokens',
                         'cache_read', 'cost_usd', 'duration_ms'])
        for bi, batch in enumerate(batches, 1):
            prompt = build_prompt(batch)
            status, results, meta = 'fail', [], {}
            for attempt in range(2):
                try:
                    t0 = time.time()
                    r = call_claude(prompt, system, schema, a.model)
                    meta = r['meta']
                    results, why = validate(r['payload'].get('results', []), batch)
                    if results:
                        status = 'ok'
                        break
                    print(f'  批 {bi} 第 {attempt + 1} 次：{why}')
                except Exception as e:  # noqa: BLE001
                    print(f'  批 {bi} 第 {attempt + 1} 次失敗：{str(e)[:200]}')
                time.sleep(3)
            u = meta.get('usage') or {}
            uw.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), a.model, bi, len(batch), status,
                         u.get('input_tokens'), u.get('output_tokens'),
                         u.get('cache_read_input_tokens'), meta.get('total_cost_usd'),
                         meta.get('duration_ms')])
            fu.flush()
            if status == 'ok':
                for b, r in zip(batch, results):
                    r['category'] = b['category']
                    r['model'] = a.model
                    fout.write(json.dumps(r, ensure_ascii=False) + '\n')
                fout.flush()
            print(f'批 {bi}/{len(batches)} {status}  in={u.get("input_tokens")} out={u.get("output_tokens")} '
                  f'cost={meta.get("total_cost_usd")} {time.time() - t0:.0f}s', flush=True)
            if bi < len(batches):
                time.sleep(a.sleep)


if __name__ == '__main__':
    main()
