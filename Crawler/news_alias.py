"""
標的別名表（Iteration 38 階段 2b）
──────────────────────────────────
新聞裡的公司不一定叫 stock_info 上的名字：「台積」「TSMC」「台灣50」都不會被
`tag_tickers` 的公司名比對命中，「國巨*」的星號更是永遠比不到。這裡把
stock_info 的名稱正規化後灌進 `instrument_alias`，再疊上追蹤股的手工別名。

比對規則：
    中文別名  子字串（≥ 2 字）
    英文別名  大小寫不分、整字比對（避免 VIA 命中 'via'、UMC 命中 'circumcision'）
    只回傳存在於 stock_info 的代碼

用法：
    python news_alias.py --seed     # 建表（若無）並灌別名
    python news_alias.py --test "台積電法說會 TSMC 與聯電（2303）"
"""

import argparse
import logging
import re

from db.connection import get_conn

logger = logging.getLogger(__name__)

# 追蹤股手工別名：代碼 → [(別名, 語言, 類型)]
SEED = {
    '2330': [('台積', 'zh', 'short_name'), ('TSMC', 'en', 'short_name'), ('台積電', 'zh', 'full_name')],
    '2303': [('聯電', 'zh', 'full_name'), ('UMC', 'en', 'short_name')],
    '2409': [('友達', 'zh', 'full_name'), ('AUO', 'en', 'short_name')],
    '3481': [('群創', 'zh', 'full_name'), ('Innolux', 'en', 'short_name')],
    '3231': [('緯創', 'zh', 'full_name'), ('Wistron', 'en', 'short_name')],
    '2324': [('仁寶', 'zh', 'full_name'), ('Compal', 'en', 'short_name')],
    '2353': [('宏碁', 'zh', 'full_name'), ('Acer', 'en', 'short_name')],
    '2352': [('佳世達', 'zh', 'full_name'), ('Qisda', 'en', 'short_name')],
    '2356': [('英業達', 'zh', 'full_name'), ('Inventec', 'en', 'short_name')],
    '2344': [('華邦電', 'zh', 'full_name'), ('華邦', 'zh', 'short_name'), ('Winbond', 'en', 'short_name')],
    '2337': [('旺宏', 'zh', 'full_name'), ('Macronix', 'en', 'short_name')],
    '3037': [('欣興', 'zh', 'full_name'), ('Unimicron', 'en', 'short_name')],
    '2388': [('威盛', 'zh', 'full_name'), ('VIA Technologies', 'en', 'full_name')],
    '6239': [('力成', 'zh', 'full_name'), ('Powertech', 'en', 'short_name')],
    '2449': [('京元電子', 'zh', 'full_name'), ('京元電', 'zh', 'short_name'), ('KYEC', 'en', 'short_name')],
    '2312': [('金寶', 'zh', 'full_name'), ('Kinpo', 'en', 'short_name')],
    '2313': [('華通', 'zh', 'full_name'), ('Compeq', 'en', 'short_name')],
    '2323': [('中環', 'zh', 'full_name'), ('CMC Magnetics', 'en', 'full_name')],
    '2367': [('燿華', 'zh', 'full_name'), ('Unitech PCB', 'en', 'full_name')],
    '5483': [('中美晶', 'zh', 'full_name'), ('SAS', 'en', 'short_name')],
    '6116': [('彩晶', 'zh', 'full_name'), ('HannStar', 'en', 'short_name')],
    '2327': [('國巨', 'zh', 'full_name'), ('Yageo', 'en', 'short_name')],
    '2883': [('凱基金', 'zh', 'full_name'), ('凱基金控', 'zh', 'full_name'), ('開發金', 'zh', 'short_name')],
    '0050': [('元大台灣50', 'zh', 'full_name'), ('台灣50', 'zh', 'short_name'), ('0050', 'zh', 'code')],
    '0056': [('元大高股息', 'zh', 'full_name'), ('0056', 'zh', 'code')],
    '0052': [('富邦科技', 'zh', 'full_name'), ('0052', 'zh', 'code')],
}

# 太短或太泛的名稱不當別名（stock_info 有些名稱是「台灣」「中華」這種）
_MIN_ZH_LEN = 2
_GENERIC = {'台灣', '中華', '中國', '亞洲', '國際', '第一', '全球', '大同', '東元', '長榮', '新光',
            '中央', '聯合', '台達', '光寶'}


def _norm_name(name: str) -> str:
    """去掉 stock_info 名稱裡的標記字元（國巨* → 國巨；xx-KY 保留）。"""
    return re.sub(r'[*＊\s]+', '', name or '').strip()


def seed() -> int:
    """建表（若無）並灌別名，回傳新增筆數。"""
    import news_schema
    news_schema.apply(tables_only=True)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT stock_id, stock_name FROM stock_info')
            rows = cur.fetchall()
            n = 0
            for code, name in rows:
                nm = _norm_name(name)
                if len(nm) >= _MIN_ZH_LEN and nm not in _GENERIC:
                    cur.execute("""INSERT INTO instrument_alias (alias, ticker, market, language, alias_type, priority)
                                   VALUES (%s, %s, 'TW', 'zh', 'full_name', 1) ON CONFLICT DO NOTHING""",
                                (nm, code))
                    n += cur.rowcount
            known = {r[0] for r in rows}
            for code, aliases in SEED.items():
                if code not in known:
                    continue
                for alias, lang, kind in aliases:
                    cur.execute("""INSERT INTO instrument_alias (alias, ticker, market, language, alias_type, priority)
                                   VALUES (%s, %s, 'TW', %s, %s, 2) ON CONFLICT DO NOTHING""",
                                (alias, code, lang, kind))
                    n += cur.rowcount
        conn.commit()
    logger.info('[alias] 新增 %d 筆別名', n)
    return n


_CACHE = None


def load_alias_map(force: bool = False) -> dict:
    """{'zh': {alias: [codes]}, 'en': {alias_lower: [codes]}}；表不存在回空。"""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    zh, en = {}, {}
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT alias, ticker, language FROM instrument_alias WHERE is_active")
                for alias, code, lang in cur.fetchall():
                    bucket = en if lang == 'en' else zh
                    key = alias.lower() if lang == 'en' else alias
                    bucket.setdefault(key, []).append(code)
    except Exception as e:
        logger.warning('[alias] 讀取別名表失敗（沿用公司名比對）：%s', e)
        return {}
    _CACHE = {'zh': zh, 'en': en,
              'en_re': re.compile(r'\b(' + '|'.join(re.escape(a) for a in sorted(en, key=len, reverse=True)) + r')\b',
                                  re.IGNORECASE) if en else None}
    return _CACHE


def match(text: str, alias_map: dict = None) -> list:
    """回傳文中命中的代碼（去重、依出現順序）。"""
    if not text:
        return []
    m = alias_map if alias_map is not None else load_alias_map()
    if not m:
        return []
    found = []
    for alias, codes in m['zh'].items():
        if alias in text:
            found += codes
    if m.get('en_re'):
        for hit in m['en_re'].findall(text):
            found += m['en'].get(hit.lower(), [])
    return list(dict.fromkeys(found))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', action='store_true')
    ap.add_argument('--test', default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    if a.seed:
        print('新增', seed(), '筆')
    if a.test:
        print(match(a.test, load_alias_map(force=True)))
