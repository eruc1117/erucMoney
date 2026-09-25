"""
新聞來源登記表（Iteration 38）：platform → tier / scope / language

方案文件第 7 表 `source` 的精簡版。先放程式常數而不建表——來源只有十幾個，
改動時 code review 比 SQL 更容易看見。`news_dedup`（tier）、`news_schema --fill`
（回填 user_news.scope / source_tier / language）都從這裡讀。

scope 規則（方案文件）：
    TW      台灣媒體的台股／本地新聞 → 只影響台股
    US      美國公司與美國政策       → 同時影響美股與台股
    GLOBAL  跨國事件、世界頭條       → 同時影響美股與台股

用法：
    python news_sources.py --fill    # 回填 user_news 的 scope / source_tier / language / content_kind / source_url
"""

import argparse
import logging

logger = logging.getLogger(__name__)

# platform → (tier, scope, language)
SOURCES = {
    # 台灣通訊社／官方 tier 1
    '中央社財經':      (1, 'TW', 'zh'),
    # 主流財經媒體 tier 2
    '鉅亨網':          (2, 'TW', 'zh'),
    '鉅亨網美股':      (2, 'US', 'zh'),
    '鉅亨網頭條':      (2, 'GLOBAL', 'zh'),
    '鉅亨網營收':      (2, 'TW', 'zh'),       # 營收速報個股快訊（Iteration 39）
    '經濟日報證券':    (2, 'TW', 'zh'),
    '經濟日報產業':    (2, 'TW', 'zh'),
    '自由財經':        (2, 'TW', 'zh'),
    'Yahoo Finance 台灣': (3, 'TW', 'zh'),
    # 國際 tier 1
    'MOPS重大訊息':    (1, 'TW', 'zh'),
    'BBC Business':    (1, 'GLOBAL', 'en'),
    'BBC World':       (1, 'GLOBAL', 'en'),
    'CNN Business':    (2, 'US', 'en'),
}
DEFAULT = (3, 'TW', 'zh')     # Yahoo 個股 RSS、使用者貼上


def info(platform: str) -> tuple:
    if not platform:
        return DEFAULT
    if platform.startswith('Yahoo個股'):
        return (3, 'TW', 'zh')
    return SOURCES.get(platform, DEFAULT)


def tier(platform: str) -> int:
    return info(platform)[0]


def scope(platform: str) -> str:
    return info(platform)[1]


def fill_user_news() -> dict:
    """回填 user_news 的來源欄位（只補 NULL，不覆蓋既有值）。需先跑 news_schema.py。"""
    from db.connection import get_conn
    out = {}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT platform FROM user_news")
            platforms = [r[0] for r in cur.fetchall()]
            n = 0
            for p in platforms:
                t, sc, lang = info(p)
                cur.execute("""
                    UPDATE user_news SET
                        source_tier = COALESCE(source_tier, %s),
                        scope       = COALESCE(scope, %s),
                        language    = COALESCE(language, %s)
                    WHERE platform IS NOT DISTINCT FROM %s
                      AND (source_tier IS NULL OR scope IS NULL OR language IS NULL)
                """, (t, sc, lang, p))
                n += cur.rowcount
            out['source_fields'] = n
            # source_url 與 content_kind：從 news_crawl_raw 以標題對回（回填與即時管線都先寫 raw 表）
            cur.execute("""
                UPDATE user_news u SET source_url = r.source_url
                FROM (SELECT DISTINCT ON (title) title, source_url FROM news_crawl_raw
                      WHERE source_url IS NOT NULL ORDER BY title, id) r
                WHERE u.source_url IS NULL AND u.title = r.title
            """)
            out['source_url'] = cur.rowcount
            cur.execute("""
                UPDATE user_news SET content_kind = CASE
                    WHEN platform LIKE '鉅亨網%%' THEN 'api'
                    WHEN platform = 'MOPS重大訊息' THEN 'filing'
                    WHEN platform LIKE 'Yahoo個股%%' OR platform IN ('中央社財經','經濟日報證券','經濟日報產業','自由財經','BBC Business','BBC World') THEN 'body'
                    ELSE 'user' END
                WHERE content_kind IS NULL
            """)
            out['content_kind'] = cur.rowcount
        conn.commit()
    logger.info('[sources] 回填 %s', out)
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--fill', action='store_true')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    if a.fill:
        print(fill_user_news())
    else:
        for p, v in SOURCES.items():
            print(f'{p:20s} tier={v[0]} scope={v[1]} lang={v[2]}')
