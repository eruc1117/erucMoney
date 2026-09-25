"""
把 extracted.jsonl 寫進 news_llm_feature（方案文件的新表；DDL 在 Crawler/news_schema.py）。

用法：
    python scripts/05_load_db.py [--pred data/output/extracted.jsonl]
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), 'Crawler'))

from db.connection import get_conn  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pred', default=os.path.join(ROOT, 'data', 'output', 'extracted.jsonl'))
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.pred, encoding='utf-8') if l.strip()]
    n = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute("""
                    INSERT INTO news_llm_feature
                        (news_id, model, event_type, direction, magnitude, is_expected,
                         affected_tickers, affected_sectors, scope, confidence, rationale, raw_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (news_id, model) DO UPDATE SET
                        event_type = EXCLUDED.event_type, direction = EXCLUDED.direction,
                        magnitude = EXCLUDED.magnitude, is_expected = EXCLUDED.is_expected,
                        affected_tickers = EXCLUDED.affected_tickers,
                        affected_sectors = EXCLUDED.affected_sectors, scope = EXCLUDED.scope,
                        confidence = EXCLUDED.confidence, rationale = EXCLUDED.rationale,
                        raw_json = EXCLUDED.raw_json, extracted_at = NOW()
                """, (r['news_id'], r.get('model', 'unknown'), r['event_type'], r['direction'],
                      r['magnitude'], r['is_expected'], r['affected_tickers'], r['affected_sectors'],
                      r['scope'], r['confidence'], r['rationale'], json.dumps(r, ensure_ascii=False)))
                n += 1
        conn.commit()
    print(f'寫入 {n} 筆')


if __name__ == '__main__':
    main()
