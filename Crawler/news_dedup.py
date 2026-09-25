"""
新聞去重：標題 SimHash（Iteration 38 階段 2c）
──────────────────────────────────────────────
`insert_news_articles` 只擋「標題完全相同」。同一事件多家改寫（「台積電法說會釋利多」
vs「台積電法說：Q4 展望優於預期」）會各算一則，`news_volume_gap` 與 n_articles 被灌水。

做法：
    1. 標題正規化（去標點、空白、全形轉半形、數字統一）→ 字元 2-gram → 64 位元 SimHash
    2. 發布時間相差 ≤ 3 天且 Hamming 距離 ≤ HAMMING_MAX 視為同群
       （分成 4 段 16 位元做桶，距離 ≤ 3 者至少有一段完全相同，免 O(n²)）
    3. 同群保留來源 tier 最高、其次最早發布的一則為 canonical，
       其餘 is_canonical = FALSE、dedup_group_id = canonical 的 id

需要 news_schema.py 先幫 user_news 加上 dedup_group_id / is_canonical 欄位。

用法：
    python news_dedup.py --dry-run          # 只報告群數
    python news_dedup.py                    # 寫回 user_news
    python news_dedup.py --since 2026-09-01
"""

import argparse
import logging
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

from db.connection import get_conn

logger = logging.getLogger(__name__)

HAMMING_MAX = 3
WINDOW_DAYS = 3

def tier_of(platform: str) -> int:
    from news_sources import tier
    return tier(platform)


# ── SimHash ───────────────────────────────────────────────────────────────────
_PUNCT_RE = re.compile(r'[\s\W_]+', re.UNICODE)


def normalize_title(t: str) -> str:
    t = unicodedata.normalize('NFKC', t or '').lower()
    t = re.sub(r'\d+(\.\d+)?', '0', t)      # 數字統一，避免「漲 3%」「漲 3.2%」被判不同
    return _PUNCT_RE.sub('', t)


def _hash64(s: str) -> int:
    import hashlib
    return int.from_bytes(hashlib.blake2b(s.encode('utf-8'), digest_size=8).digest(), 'big')


def simhash(text: str) -> int:
    norm = normalize_title(text)
    grams = [norm[i:i + 2] for i in range(len(norm) - 1)] or [norm]
    v = [0] * 64
    for g in grams:
        h = _hash64(g)
        for b in range(64):
            v[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(64):
        if v[b] > 0:
            out |= 1 << b
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count('1')


# ── 分群 ──────────────────────────────────────────────────────────────────────
def group_rows(rows: list) -> dict:
    """
    rows: [(id, title, platform, published_at)]
    回傳 {id: canonical_id}（只含被併入群的列與 canonical 本身）。
    """
    items = []
    for rid, title, platform, pub in rows:
        if not title or not pub:
            continue
        items.append({'id': rid, 'h': simhash(title), 'tier': tier_of(platform), 'pub': pub})

    # 桶：4 段 16 位元
    buckets = defaultdict(list)
    for idx, it in enumerate(items):
        for k in range(4):
            buckets[(k, (it['h'] >> (16 * k)) & 0xFFFF)].append(idx)

    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    window = timedelta(days=WINDOW_DAYS)
    for members in buckets.values():
        if len(members) < 2:
            continue
        for i in range(len(members)):
            a = items[members[i]]
            for j in range(i + 1, len(members)):
                b = items[members[j]]
                if abs(a['pub'] - b['pub']) > window:
                    continue
                if hamming(a['h'], b['h']) <= HAMMING_MAX:
                    union(members[i], members[j])

    groups = defaultdict(list)
    for idx in range(len(items)):
        groups[find(idx)].append(items[idx])

    mapping = {}
    for g in groups.values():
        if len(g) < 2:
            continue
        canon = min(g, key=lambda x: (x['tier'], x['pub'], x['id']))
        for it in g:
            mapping[it['id']] = canon['id']
    return mapping


def run(since: date = None, dry_run: bool = False) -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name='user_news' AND column_name='is_canonical'")
            if not cur.fetchone() and not dry_run:
                raise RuntimeError('user_news 缺 is_canonical 欄位：先執行 python news_schema.py')
            cur.execute("""
                SELECT id, title, platform, submitted_at FROM user_news
                WHERE submitted_at IS NOT NULL
                  AND (%s::date IS NULL OR submitted_at >= %s::date - %s)
            """, (since, since, WINDOW_DAYS))
            rows = cur.fetchall()
    mapping = group_rows(rows)
    n_groups = len(set(mapping.values()))
    n_dups = sum(1 for k, v in mapping.items() if k != v)
    logger.info('[dedup] %d 則 → %d 群、%d 則為重複', len(rows), n_groups, n_dups)
    if dry_run:
        return {'rows': len(rows), 'groups': n_groups, 'duplicates': n_dups}

    with get_conn() as conn:
        with conn.cursor() as cur:
            ids = [r[0] for r in rows]
            # 先把範圍內全部重設為 canonical（重跑時群可能改變）
            cur.execute("UPDATE user_news SET dedup_group_id = id, is_canonical = TRUE WHERE id = ANY(%s)", (ids,))
            for rid, canon in mapping.items():
                cur.execute("UPDATE user_news SET dedup_group_id = %s, is_canonical = %s WHERE id = %s",
                            (canon, rid == canon, rid))
        conn.commit()
    return {'rows': len(rows), 'groups': n_groups, 'duplicates': n_dups}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default=None)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(run(date.fromisoformat(a.since) if a.since else None, dry_run=a.dry_run))
