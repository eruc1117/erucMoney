"""
交易所官方每日檔（Iteration 48）：證交所 MI_INDEX、櫃買 afterTrading/otc、除權息與減資參考價表。

為什麼需要它：FinMind 免費額度只能「一檔一次」查，全市場 1,800 檔每天更新要 1,800 次呼叫；
而交易所的盤後檔**一天一次呼叫就是全市場**（證交所約 1,250 列、櫃買約 930 列），不吃任何額度，
而且同一份檔還附「發行量加權股價報酬指數」（含息大盤，打敗大盤計畫的對照）。
FinMind 的 TaiwanStockPrice 本來就是從這些檔來的，欄位一一對應，兩個來源可以混用。

四種檔：
    MI_INDEX  type=ALLBUT0999  上市每日收盤行情（全部，不含權證／牛熊證）+ 各種指數
    otc       type=EW          上櫃每日收盤行情（不含定價）
    TWT49U / exDailyQ          除權息計算結果（前收、參考價、權息值）——還原價 adj_close 的事件來源
    TWTAUU                     減資恢復買賣參考價（上市）

這個模組只做兩件事：抓（fetch_*，禮貌延遲與重試）和解析成 dict 列（parse_*，純函式，測試用 fixtures）。
寫入與還原價在 market_data.py。
"""

import logging
import re
import time
from datetime import date
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TWSE_MI_INDEX = 'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX'
TWSE_TWT49U = 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U'
TWSE_TWTAUU = 'https://www.twse.com.tw/rwd/zh/reducation/TWTAUU'
TPEX_OTC_DAILY = 'https://www.tpex.org.tw/www/zh-tw/afterTrading/otc'
TPEX_EXDAILYQ = 'https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ'

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) money-crawler/1.0',
           'Accept': 'application/json, text/plain, */*'}
REQUEST_TIMEOUT = 60
RETRY_WAITS = (5, 20, 60)          # 交易所偶爾回 HTML 或 5xx，等一下再試

TAIEX_NAME = '發行量加權股價指數'
TAIEX_TR_NAME = '發行量加權股價報酬指數'

_FULLWIDTH = str.maketrans('０１２３４５６７８９．，', '0123456789.,')
_ROC_DATE = re.compile(r'(\d{2,3})\s*[/年]\s*(\d{1,2})\s*[/月]\s*(\d{1,2})')


# ── 數值與日期 ────────────────────────────────────────────────────────────────

def _num(raw) -> Optional[float]:
    """'1,234.50' → 1234.5；'--'、'---'、''、'X'、'除息' → None。"""
    if raw is None:
        return None
    s = str(raw).translate(_FULLWIDTH).strip().replace(',', '')
    if not s or s in ('--', '---', '-', '+'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(raw) -> Optional[int]:
    v = _num(raw)
    return None if v is None else int(v)


def roc_date(raw: str) -> Optional[date]:
    """'113/07/01'、'113年07月01日' → date(2024, 7, 1)。"""
    m = _ROC_DATE.search(str(raw or ''))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    try:
        return date(y + 1911, mo, d)
    except ValueError:
        return None


def _ymd(raw: str) -> Optional[date]:
    s = str(raw or '').strip()
    if len(s) == 8 and s.isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    return None


def _sign(cell: str) -> Optional[int]:
    """證交所漲跌欄是一段 HTML：'<p style= color:red>+</p>' / '...green>-</p>' / ' '（平盤）/ 'X'（除權息，不可比）。"""
    s = str(cell or '')
    if '+' in s:
        return 1
    if '-' in s:
        return -1
    if not s.strip():
        return 0
    return None


def _field_index(fields: list, *names: str) -> int:
    """欄位名含空白與 <br>；找第一個正規化後相符的欄位，找不到回 -1。"""
    norm = [re.sub(r'<br>.*$', '', str(f)).replace(' ', '').strip() for f in fields]
    for name in names:
        key = name.replace(' ', '')
        if key in norm:
            return norm.index(key)
    return -1


def _cell(row: list, idx: int):
    return row[idx] if 0 <= idx < len(row) else None


# ── 證交所每日收盤行情 + 指數 ─────────────────────────────────────────────────

def parse_twse_daily(payload: dict) -> tuple[list[dict], dict]:
    """
    MI_INDEX（type=ALLBUT0999）→ (個股列, {指數名: 收盤})。

    休市日 stat 不是 'OK'，回 ([], {})。
    無成交的證券開高低收是 '--'（上市）或 0.00（上櫃），略過（回測視為當天沒有價格）。
    """
    if not isinstance(payload, dict) or str(payload.get('stat', '')).upper() != 'OK':
        return [], {}
    trade_date = _ymd(payload.get('date'))
    if trade_date is None:
        return [], {}

    rows, indexes = [], {}
    for table in payload.get('tables') or []:
        title = str(table.get('title') or '')
        fields = table.get('fields') or []
        data = table.get('data') or []
        if ('價格指數' in title or '報酬指數' in title) and data:
            i_close = _field_index(fields, '收盤指數')
            for r in data:
                name = str(_cell(r, 0) or '').strip()
                close = _num(_cell(r, i_close))
                if name and close is not None:
                    indexes[name] = close
        elif '每日收盤行情' in title and data:
            ix = {k: _field_index(fields, *v) for k, v in {
                'id': ('證券代號',), 'vol': ('成交股數',), 'txn': ('成交筆數',), 'amt': ('成交金額',),
                'open': ('開盤價',), 'high': ('最高價',), 'low': ('最低價',), 'close': ('收盤價',),
                'sign': ('漲跌(+/-)',), 'chg': ('漲跌價差',),
            }.items()}
            for r in data:
                sid = str(_cell(r, ix['id']) or '').strip()
                close = _num(_cell(r, ix['close']))
                if not sid or close is None or close <= 0:
                    continue
                sign = _sign(_cell(r, ix['sign']))
                chg = _num(_cell(r, ix['chg']))
                rows.append({
                    'stock_id': sid, 'trade_date': trade_date,
                    'open_price': _num(_cell(r, ix['open'])), 'high_price': _num(_cell(r, ix['high'])),
                    'low_price': _num(_cell(r, ix['low'])), 'close_price': close,
                    'volume': _int(_cell(r, ix['vol'])), 'turnover_value': _num(_cell(r, ix['amt'])),
                    'transaction_count': _int(_cell(r, ix['txn'])),
                    'change_value': (None if sign is None or chg is None else sign * chg),
                    'source': 'twse',
                })
    return rows, indexes


# ── 櫃買每日收盤行情 ──────────────────────────────────────────────────────────

def parse_tpex_daily(payload: dict) -> list[dict]:
    """
    afterTrading/otc（type=EW）→ 個股列。休市日 tables[0].data 是空的，回 []。
    漲跌欄是 '+0.25' / '-0.18' / '0.00'，除權息日是文字（除息／除權），轉成 None。
    """
    if not isinstance(payload, dict) or str(payload.get('stat', '')).lower() != 'ok':
        return []
    trade_date = _ymd(payload.get('date'))
    tables = payload.get('tables') or []
    if trade_date is None or not tables:
        return []
    table = tables[0]
    fields = table.get('fields') or []
    ix = {k: _field_index(fields, *v) for k, v in {
        'id': ('代號',), 'close': ('收盤',), 'chg': ('漲跌',), 'open': ('開盤',), 'high': ('最高',), 'low': ('最低',),
        'vol': ('成交股數',), 'amt': ('成交金額(元)', '成交金額'), 'txn': ('成交筆數',),
    }.items()}
    rows = []
    for r in table.get('data') or []:
        sid = str(_cell(r, ix['id']) or '').strip()
        close = _num(_cell(r, ix['close']))
        if not sid or close is None or close <= 0:      # '--' 或 0.00 都是「沒成交」，不是價格
            continue
        rows.append({
            'stock_id': sid, 'trade_date': trade_date,
            'open_price': _num(_cell(r, ix['open'])), 'high_price': _num(_cell(r, ix['high'])),
            'low_price': _num(_cell(r, ix['low'])), 'close_price': close,
            'volume': _int(_cell(r, ix['vol'])), 'turnover_value': _num(_cell(r, ix['amt'])),
            'transaction_count': _int(_cell(r, ix['txn'])),
            'change_value': _num(_cell(r, ix['chg'])),
            'source': 'tpex',
        })
    return rows


# ── 除權息參考價（兩市）與減資（上市）──────────────────────────────────────────

def _exright_rows(fields: list, data: list, date_names: tuple, id_names: tuple) -> list[dict]:
    i_date = _field_index(fields, *date_names)
    i_id = _field_index(fields, *id_names)
    i_before = _field_index(fields, '除權息前收盤價')
    i_ref = _field_index(fields, '除權息參考價')
    i_div = _field_index(fields, '權值+息值')
    i_type = _field_index(fields, '權/息')
    out = []
    for r in data:
        ex = roc_date(_cell(r, i_date))
        sid = str(_cell(r, i_id) or '').strip()
        before, ref = _num(_cell(r, i_before)), _num(_cell(r, i_ref))
        if not ex or not sid or not before or not ref or before <= 0 or ref <= 0:
            continue
        out.append({'stock_id': sid, 'ex_date': ex, 'before_price': before, 'reference_price': ref,
                    'dividend': _num(_cell(r, i_div)), 'dividend_type': str(_cell(r, i_type) or '').strip()[:8]})
    return out


def parse_twse_exright(payload: dict) -> list[dict]:
    """TWT49U → stock_dividend_result 的列（stock_id, ex_date, before_price, reference_price, dividend, dividend_type）。"""
    if not isinstance(payload, dict) or str(payload.get('stat', '')).upper() != 'OK':
        return []
    return _exright_rows(payload.get('fields') or [], payload.get('data') or [], ('資料日期',), ('股票代號',))


def parse_tpex_exright(payload: dict) -> list[dict]:
    """exDailyQ → 同上（上櫃）。"""
    if not isinstance(payload, dict) or str(payload.get('stat', '')).lower() != 'ok':
        return []
    tables = payload.get('tables') or []
    if not tables:
        return []
    return _exright_rows(tables[0].get('fields') or [], tables[0].get('data') or [], ('除權息日期',), ('代號',))


def parse_twse_capital_reduction(payload: dict) -> list[dict]:
    """TWTAUU → stock_capital_reduction 的列（stock_id, ex_date=恢復買賣日, before_price, reference_price, reason）。"""
    if not isinstance(payload, dict) or str(payload.get('stat', '')).upper() != 'OK':
        return []
    fields = payload.get('fields') or []
    i_date = _field_index(fields, '恢復買賣日期')
    i_id = _field_index(fields, '股票代號')
    i_before = _field_index(fields, '停止買賣前收盤價格')
    i_ref = _field_index(fields, '恢復買賣參考價')
    i_reason = _field_index(fields, '減資原因')
    out = {}
    for r in payload.get('data') or []:
        ex = roc_date(_cell(r, i_date))
        sid = str(_cell(r, i_id) or '').strip()
        before, ref = _num(_cell(r, i_before)), _num(_cell(r, i_ref))
        if not ex or not sid or not before or not ref or before <= 0 or ref <= 0:
            continue
        # 2014～2016 的年檔同一檔同一天印兩列（2408 2014-09-09、2438 2014-11-21，內容一樣）；主鍵是 (股票, 日)，留最後一列
        out[(sid, ex)] = {'stock_id': sid, 'ex_date': ex, 'before_price': before, 'reference_price': ref,
                          'reason': str(_cell(r, i_reason) or '').strip()[:80]}
    return list(out.values())


# ── 抓取 ──────────────────────────────────────────────────────────────────────

class ExchangeFetchError(RuntimeError):
    pass


def _get_json(url: str, params: dict) -> dict:
    last = None
    for i, wait in enumerate((0,) + RETRY_WAITS):
        if wait:
            time.sleep(wait)
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                last = ExchangeFetchError(f'HTTP {r.status_code} {url}')
                continue
            return r.json()
        except ValueError as e:               # 回了 HTML（被擋或維護中）
            last = ExchangeFetchError(f'非 JSON 回應 {url}: {e}')
        except requests.RequestException as e:
            last = ExchangeFetchError(f'{url}: {e}')
        logger.warning('[exchange] 第 %d 次失敗：%s', i + 1, last)
    raise last


def fetch_twse_daily(d: date) -> dict:
    return _get_json(TWSE_MI_INDEX, {'date': d.strftime('%Y%m%d'), 'type': 'ALLBUT0999', 'response': 'json'})


def fetch_tpex_daily(d: date) -> dict:
    return _get_json(TPEX_OTC_DAILY, {'date': d.strftime('%Y/%m/%d'), 'type': 'EW', 'response': 'json'})


def fetch_twse_exright(start: date, end: date) -> dict:
    return _get_json(TWSE_TWT49U, {'startDate': start.strftime('%Y%m%d'), 'endDate': end.strftime('%Y%m%d'), 'response': 'json'})


def fetch_tpex_exright(start: date, end: date) -> dict:
    return _get_json(TPEX_EXDAILYQ, {'startDate': start.strftime('%Y/%m/%d'), 'endDate': end.strftime('%Y/%m/%d'), 'response': 'json'})


def fetch_twse_capital_reduction(start: date, end: date) -> dict:
    return _get_json(TWSE_TWTAUU, {'startDate': start.strftime('%Y%m%d'), 'endDate': end.strftime('%Y%m%d'), 'response': 'json'})


# ── 三大法人買賣超（兩市，Iteration 71）────────────────────────────────────────

TWSE_T86 = 'https://www.twse.com.tw/rwd/zh/fund/T86'
TPEX_INSTI = 'https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade'
INSTI_MISMATCH_TOLERANCE = 0.01     # 「三大法人合計 ≠ 外資＋投信＋自營」的列超過這個比例就當格式變了


class ExchangeFormatError(Exception):
    pass


def fetch_twse_institutional(d: date) -> dict:
    return _get_json(TWSE_T86, {'date': d.strftime('%Y%m%d'), 'selectType': 'ALLBUT0999', 'response': 'json'})


def fetch_tpex_institutional(d: date) -> dict:
    return _get_json(TPEX_INSTI, {'type': 'Daily', 'sect': 'EW', 'date': d.strftime('%Y/%m/%d'), 'response': 'json'})


def _insti_row(sid: str, trade_date: date, source: str, fb, fs, fn, tb, ts, tn, db, ds, dn, total) -> Optional[dict]:
    fn, tn, dn, total = _int(fn), _int(tn), _int(dn), _int(total)
    if fn is None or tn is None or dn is None or total is None:
        return None
    return {'stock_id': sid, 'trade_date': trade_date, 'source': source,
            'foreign_buy': _int(fb), 'foreign_sell': _int(fs), 'foreign_net': fn,
            'trust_buy': _int(tb), 'trust_sell': _int(ts), 'trust_net': tn,
            'dealer_buy': _int(db), 'dealer_sell': _int(ds), 'dealer_net': dn, 'total_net': total}


def _check_identity(rows: list[dict], where: str) -> list[dict]:
    """交易所原表的合計欄要等於三個法人淨買超相加；不等的列超過容忍比例就 raise（欄位對錯了），少量不等的列丟掉。"""
    if not rows:
        return rows
    bad = [r for r in rows if r['foreign_net'] + r['trust_net'] + r['dealer_net'] != r['total_net']]
    if len(bad) / len(rows) > INSTI_MISMATCH_TOLERANCE:
        raise ExchangeFormatError(f'{where}：{len(bad)}/{len(rows)} 列合計不等於三法人相加，欄位對應可能變了（例：{bad[0]}）')
    if bad:
        logger.warning('[exchange] %s：%d 列合計不等於三法人相加，丟掉', where, len(bad))
        keep = set(map(id, bad))
        rows = [r for r in rows if id(r) not in keep]
    return rows


def _sum(*cells) -> Optional[int]:
    vals = [_int(c) for c in cells]
    if any(v is None for v in vals):
        return None
    return sum(vals)


def parse_twse_institutional(payload: dict) -> list[dict]:
    """
    fund/T86（selectType=ALLBUT0999）→ 個股列。2017-12-18 起 19 欄：外陸資（不含外資自營商）買/賣/淨、外資自營商買/賣/淨、
    投信買/賣/淨、自營商淨、自營商(自行)買/賣/淨、自營商(避險)買/賣/淨、三大法人合計。外資 = 外陸資 + 外資自營商。
    休市日 stat 不是 OK，回 []。
    """
    if not isinstance(payload, dict) or str(payload.get('stat', '')).lower() != 'ok':
        return []
    trade_date = _ymd(payload.get('date'))
    fields = payload.get('fields') or []
    if trade_date is None or not fields:
        return []
    ix = {k: _field_index(fields, *v) for k, v in {
        'id': ('證券代號',),
        'f_b': ('外陸資買進股數(不含外資自營商)', '外資買進股數'), 'f_s': ('外陸資賣出股數(不含外資自營商)', '外資賣出股數'),
        'f_n': ('外陸資買賣超股數(不含外資自營商)', '外資買賣超股數'),
        'fd_b': ('外資自營商買進股數',), 'fd_s': ('外資自營商賣出股數',), 'fd_n': ('外資自營商買賣超股數',),
        't_b': ('投信買進股數',), 't_s': ('投信賣出股數',), 't_n': ('投信買賣超股數',),
        'd_n': ('自營商買賣超股數',), 'ds_b': ('自營商買進股數(自行買賣)',), 'ds_s': ('自營商賣出股數(自行買賣)',),
        'dh_b': ('自營商買進股數(避險)',), 'dh_s': ('自營商賣出股數(避險)',),
        'total': ('三大法人買賣超股數',),
    }.items()}
    missing = [k for k, v in ix.items() if v < 0 and k not in ('fd_b', 'fd_s', 'fd_n')]
    if missing:
        raise ExchangeFormatError(f'T86 欄位找不到 {missing}：{fields}')
    has_fd = ix['fd_n'] >= 0
    rows = []
    for r in payload.get('data') or []:
        sid = str(_cell(r, ix['id']) or '').strip()
        if not sid:
            continue
        c = lambda k: _cell(r, ix[k])   # noqa: E731
        if has_fd:
            fb, fs, fn = _sum(c('f_b'), c('fd_b')), _sum(c('f_s'), c('fd_s')), _sum(c('f_n'), c('fd_n'))
        else:
            fb, fs, fn = c('f_b'), c('f_s'), c('f_n')
        row = _insti_row(sid, trade_date, 'twse', fb, fs, fn, c('t_b'), c('t_s'), c('t_n'),
                         _sum(c('ds_b'), c('dh_b')), _sum(c('ds_s'), c('dh_s')), c('d_n'), c('total'))
        if row:
            rows.append(row)
    return _check_identity(rows, f'T86 {trade_date}')


def parse_tpex_institutional(payload: dict) -> list[dict]:
    """
    insti/dailyTrade（type=Daily、sect=EW）→ 個股列。兩種版面：
      16 欄（2018 年前後）：代號、名稱、外資及陸資買/賣/淨、投信買/賣/淨、自營淨、自營(自行)買/賣/淨、自營(避險)買/賣/淨、合計；
      24 欄（之後）：欄名只剩「買進股數／賣出股數／買賣超股數」重複七組，只能按位置——
        外資及陸資(不含自營商)、外資自營商、外資及陸資合計、投信、自營商(自行)、自營商(避險)、自營商合計、三大法人合計。
    休市日 data 是空的，回 []。
    """
    if not isinstance(payload, dict):
        return []
    table = next((t for t in payload.get('tables') or [] if t.get('data')), None)
    if table is None:
        return []
    trade_date = roc_date(table.get('date') or payload.get('date'))
    fields = table.get('fields') or []
    if trade_date is None:
        return []
    rows = []
    if len(fields) == 16:
        for r in table['data']:
            sid = str(_cell(r, 0) or '').strip()
            if not sid:
                continue
            row = _insti_row(sid, trade_date, 'tpex', r[2], r[3], r[4], r[5], r[6], r[7],
                             _sum(r[9], r[12]), _sum(r[10], r[13]), r[8], r[15])
            if row:
                rows.append(row)
    elif len(fields) == 24:
        for r in table['data']:
            sid = str(_cell(r, 0) or '').strip()
            if not sid:
                continue
            row = _insti_row(sid, trade_date, 'tpex', r[8], r[9], r[10], r[11], r[12], r[13], r[20], r[21], r[22], r[23])
            if row:
                rows.append(row)
    else:
        raise ExchangeFormatError(f'櫃買三大法人表 {trade_date} 有 {len(fields)} 欄，不是 16 或 24：{fields}')
    return _check_identity(rows, f'TPEx insti {trade_date}')


# ── 個股估值：本益比、殖利率、股價淨值比（兩市，Iteration 78）──────────────────

TWSE_BWIBBU = 'https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d'
TPEX_PE = 'https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate'
VALUATION_MIN_PB_SHARE = 0.5      # 股價淨值比為正的列少於這個比例就當欄位對錯了（正常日子 > 95%）


def fetch_twse_valuation(d: date) -> dict:
    return _get_json(TWSE_BWIBBU, {'date': d.strftime('%Y%m%d'), 'selectType': 'ALL', 'response': 'json'})


def fetch_tpex_valuation(d: date) -> dict:
    return _get_json(TPEX_PE, {'date': d.strftime('%Y/%m/%d'), 'response': 'json'})


def _val_row(sid: str, trade_date: date, source: str, close, pe, dy, pb, dps, dy_year, fin_period) -> Optional[dict]:
    pe, dy, pb = _num(pe), _num(dy), _num(pb)
    if pe is None and dy is None and pb is None:
        return None
    return {'stock_id': sid, 'trade_date': trade_date, 'source': source, 'close_price': _num(close), 'pe': pe, 'dividend_yield': dy, 'pb': pb,
            'dividend_per_share': _num(dps), 'dividend_year': _int(dy_year),
            'fin_period': (str(fin_period).strip() or None) if fin_period is not None else None}


def _check_valuation(rows: list[dict], where: str) -> list[dict]:
    """沒有合計欄可驗；用「股價淨值比大多為正」當欄位對位的檢查（對錯欄會抓到殖利率或本益比的「-」／0）。"""
    if not rows:
        return rows
    ok = sum(1 for r in rows if r['pb'] is not None and r['pb'] > 0)
    if ok / len(rows) < VALUATION_MIN_PB_SHARE:
        raise ExchangeFormatError(f'{where}：只有 {ok}/{len(rows)} 列股價淨值比為正，欄位對應可能變了（例：{rows[0]}）')
    return rows


def parse_twse_valuation(payload: dict) -> list[dict]:
    """
    afterTrading/BWIBBU_d（selectType=ALL）→ 個股列：收盤價、殖利率(%)、股利年度、本益比、股價淨值比、財報年/季。
    本益比虧損或無資料印「-」→ None。欄位按名稱找；休市日 stat 不是 OK，回 []。
    """
    if not isinstance(payload, dict) or str(payload.get('stat', '')).lower() != 'ok':
        return []
    trade_date = _ymd(payload.get('date'))
    fields = payload.get('fields') or []
    if trade_date is None or not fields:
        return []
    ix = {k: _field_index(fields, *v) for k, v in {
        'id': ('證券代號',), 'close': ('收盤價',), 'dy': ('殖利率(%)',), 'dy_year': ('股利年度',),
        'pe': ('本益比',), 'pb': ('股價淨值比',), 'fin': ('財報年/季',),
    }.items()}
    missing = [k for k, v in ix.items() if v < 0 and k not in ('close', 'dy_year', 'fin')]
    if missing:
        raise ExchangeFormatError(f'BWIBBU_d 欄位找不到 {missing}：{fields}')
    rows = []
    for r in payload.get('data') or []:
        sid = str(_cell(r, ix['id']) or '').strip()
        if not sid:
            continue
        c = lambda k: _cell(r, ix[k])   # noqa: E731
        row = _val_row(sid, trade_date, 'twse', c('close'), c('pe'), c('dy'), c('pb'), None, c('dy_year'), c('fin'))
        if row:
            rows.append(row)
    return _check_valuation(rows, f'BWIBBU_d {trade_date}')


def parse_tpex_valuation(payload: dict) -> list[dict]:
    """
    afterTrading/peQryDate → 個股列：本益比、每股股利、股利年度、殖利率(%)、股價淨值比（沒有收盤價與財報期）。
    2018 與 2024 的欄位名相同，按名稱找；本益比 N/A → None。休市日 data 是空的，回 []。
    """
    if not isinstance(payload, dict):
        return []
    table = next((t for t in payload.get('tables') or [] if t.get('data')), None)
    if table is None:
        return []
    trade_date = roc_date(table.get('date') or payload.get('date'))
    fields = table.get('fields') or []
    if trade_date is None:
        return []
    ix = {k: _field_index(fields, *v) for k, v in {
        'id': ('股票代號', '代號'), 'pe': ('本益比',), 'dps': ('每股股利',), 'dy_year': ('股利年度',), 'dy': ('殖利率(%)',), 'pb': ('股價淨值比',),
    }.items()}
    missing = [k for k, v in ix.items() if v < 0 and k not in ('dps', 'dy_year')]
    if missing:
        raise ExchangeFormatError(f'櫃買 peQryDate 欄位找不到 {missing}：{fields}')
    rows = []
    for r in table['data']:
        sid = str(_cell(r, ix['id']) or '').strip()
        if not sid:
            continue
        c = lambda k: _cell(r, ix[k])   # noqa: E731
        row = _val_row(sid, trade_date, 'tpex', None, c('pe'), c('dy'), c('pb'), c('dps'), c('dy_year'), None)
        if row:
            rows.append(row)
    return _check_valuation(rows, f'TPEx peQryDate {trade_date}')


# ── 融資融券與借券賣出（兩市，Iteration 81）────────────────────────────────────

TWSE_MI_MARGN = 'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN'      # 融資融券彙總（張）
TWSE_TWT93U = 'https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U'          # 信用額度總量管制餘額表：融券＋借券賣出（股）
TPEX_MARGIN = 'https://www.tpex.org.tw/www/zh-tw/margin/balance'              # 上櫃融資融券餘額（張）
TPEX_SBL = 'https://www.tpex.org.tw/www/zh-tw/margin/sbl'                     # 上櫃信用額度總量管制餘額表（股）
LOT = 1000                                                                   # 一張 = 1,000 股
MARGIN_MISMATCH_TOLERANCE = 0.01   # 融資融券表的融券餘額（張）× 1000 與借券表的融券餘額（股）不等的列超過這個比例就當欄位對錯了


def fetch_twse_margin(d: date) -> dict:
    return _get_json(TWSE_MI_MARGN, {'date': d.strftime('%Y%m%d'), 'selectType': 'ALL', 'response': 'json'})


def fetch_twse_sbl(d: date) -> dict:
    return _get_json(TWSE_TWT93U, {'date': d.strftime('%Y%m%d'), 'response': 'json'})


def fetch_tpex_margin(d: date) -> dict:
    return _get_json(TPEX_MARGIN, {'date': d.strftime('%Y/%m/%d'), 'response': 'json'})


def fetch_tpex_sbl(d: date) -> dict:
    return _get_json(TPEX_SBL, {'date': d.strftime('%Y/%m/%d'), 'response': 'json'})


def _lots(raw) -> Optional[int]:
    v = _int(raw)
    return None if v is None else v * LOT


def parse_twse_margin(payload: dict) -> list[dict]:
    """
    MI_MARGN（selectType=ALL）第二張表「融資融券彙總」→ 個股列（單位張 → 存股）。16 欄、欄名重複只能按位置：
    代號、名稱、融資買進／賣出／現金償還／前日餘額／今日餘額／次一營業日限額、融券買進／賣出／現券償還／前日餘額／今日餘額／次一營業日限額、資券互抵、註記。
    休市日 stat 不是 OK，回 []。
    """
    if not isinstance(payload, dict) or str(payload.get('stat', '')).lower() != 'ok':
        return []
    trade_date = _ymd(payload.get('date'))
    tables = payload.get('tables') or []
    table = next((t for t in tables if '融資融券彙總' in str(t.get('title', ''))), None)
    if trade_date is None or table is None:
        return []
    fields = table.get('fields') or []
    if len(fields) != 16 or _field_index(fields, '代號') != 0 or fields[6] != '今日餘額' or fields[12] != '今日餘額':
        raise ExchangeFormatError(f'MI_MARGN {trade_date} 欄位不是預期的 16 欄：{fields}')
    rows = []
    for r in table.get('data') or []:
        sid = str(_cell(r, 0) or '').strip()
        if not sid:
            continue
        mb, ms, mbal, sb, ss, sbal = _lots(r[2]), _lots(r[3]), _lots(r[6]), _lots(r[8]), _lots(r[9]), _lots(r[12])
        if mbal is None or sbal is None:
            continue
        rows.append({'stock_id': sid, 'trade_date': trade_date, 'source': 'twse', 'margin_buy': mb, 'margin_sell': ms, 'margin_balance': mbal,
                     'short_buy': sb, 'short_sell': ss, 'short_balance': sbal})
    return rows


def parse_twse_sbl(payload: dict) -> list[dict]:
    """
    TWT93U「信用額度總量管制餘額表」→ 個股列（單位股）。15 欄、前後兩組欄名重複只能按位置：
    代號、名稱、融券：前日餘額／賣出／買進／現券／今日餘額／次一營業日限額、借券賣出：前日餘額／當日賣出／當日還券／當日調整／當日餘額／次一營業日可限額、備註。
    回 {'stock_id', 'short_balance_chk'（融券今日餘額，股，給對位檢查）, 'sbl_sell', 'sbl_balance'}。休市回 []。
    """
    if not isinstance(payload, dict) or str(payload.get('stat', '')).lower() != 'ok':
        return []
    trade_date = _ymd(payload.get('date'))
    fields = payload.get('fields') or []
    if trade_date is None or not fields:
        return []
    if len(fields) != 15 or _field_index(fields, '代號') != 0 or fields[6] != '今日餘額' or fields[9] != '當日賣出' or fields[12] != '當日餘額':
        raise ExchangeFormatError(f'TWT93U {trade_date} 欄位不是預期的 15 欄：{fields}')
    rows = []
    for r in payload.get('data') or []:
        sid = str(_cell(r, 0) or '').strip()
        if not sid:
            continue
        chk, sell, bal = _int(r[6]), _int(r[9]), _int(r[12])
        if bal is None:
            continue
        rows.append({'stock_id': sid, 'trade_date': trade_date, 'short_balance_chk': chk, 'sbl_sell': sell, 'sbl_balance': bal})
    return rows


def parse_tpex_margin(payload: dict) -> list[dict]:
    """margin/balance「上櫃股票融資融券餘額」→ 個股列（張 → 股）。欄位按名稱：代號、資買、資賣、資餘額、券賣、券買、券餘額。休市 data 空，回 []。"""
    if not isinstance(payload, dict):
        return []
    table = next((t for t in payload.get('tables') or [] if t.get('data')), None)
    if table is None:
        return []
    trade_date = roc_date(table.get('date') or payload.get('date'))
    fields = table.get('fields') or []
    if trade_date is None:
        return []
    ix = {k: _field_index(fields, *v) for k, v in {'id': ('代號',), 'mb': ('資買',), 'ms': ('資賣',), 'mbal': ('資餘額',),
                                                   'ss': ('券賣',), 'sb': ('券買',), 'sbal': ('券餘額',)}.items()}
    missing = [k for k, v in ix.items() if v < 0]
    if missing:
        raise ExchangeFormatError(f'櫃買融資融券表 {trade_date} 欄位找不到 {missing}：{fields}')
    rows = []
    for r in table['data']:
        sid = str(_cell(r, ix['id']) or '').strip()
        if not sid:
            continue
        c = lambda k: _lots(_cell(r, ix[k]))   # noqa: E731
        mbal, sbal = c('mbal'), c('sbal')
        if mbal is None or sbal is None:
            continue
        rows.append({'stock_id': sid, 'trade_date': trade_date, 'source': 'tpex', 'margin_buy': c('mb'), 'margin_sell': c('ms'), 'margin_balance': mbal,
                     'short_buy': c('sb'), 'short_sell': c('ss'), 'short_balance': sbal})
    return rows


def parse_tpex_sbl(payload: dict) -> list[dict]:
    """margin/sbl「信用額度總量管制餘額表」（上櫃）→ 個股列（股）。15 欄、同 TWT93U 的版面按位置。休市 data 空，回 []。"""
    if not isinstance(payload, dict):
        return []
    table = next((t for t in payload.get('tables') or [] if t.get('data')), None)
    if table is None:
        return []
    trade_date = roc_date(table.get('date') or payload.get('date'))
    fields = table.get('fields') or []
    if trade_date is None:
        return []
    if len(fields) != 15 or _field_index(fields, '股票代號', '代號') != 0 or fields[6] != '當日餘額' or fields[9] != '當日賣出' or fields[12] != '當日餘額':
        raise ExchangeFormatError(f'櫃買借券表 {trade_date} 欄位不是預期的 15 欄：{fields}')
    rows = []
    for r in table['data']:
        sid = str(_cell(r, 0) or '').strip()
        if not sid:
            continue
        chk, sell, bal = _int(r[6]), _int(r[9]), _int(r[12])
        if bal is None:
            continue
        rows.append({'stock_id': sid, 'trade_date': trade_date, 'short_balance_chk': chk, 'sbl_sell': sell, 'sbl_balance': bal})
    return rows


def merge_margin_sbl(margin_rows: list[dict], sbl_rows: list[dict], where: str) -> list[dict]:
    """把借券表併進融資融券列；用兩張表都有的「融券餘額」當對位檢查（不等的列超過容忍比例就 raise）。借券表沒有的股票借券欄留空。"""
    sbl = {r['stock_id']: r for r in sbl_rows}
    bad = 0
    common = 0
    for r in margin_rows:
        s = sbl.get(r['stock_id'])
        if s is None:
            r['sbl_sell'], r['sbl_balance'] = None, None
            continue
        common += 1
        if s['short_balance_chk'] is not None and s['short_balance_chk'] != r['short_balance']:
            bad += 1
        r['sbl_sell'], r['sbl_balance'] = s['sbl_sell'], s['sbl_balance']
    if common and bad / common > MARGIN_MISMATCH_TOLERANCE:
        raise ExchangeFormatError(f'{where}：{bad}/{common} 列兩張表的融券餘額不等，欄位對應可能變了')
    if bad:
        logger.warning('[exchange] %s：%d/%d 列兩張表的融券餘額不等（保留融資融券表的值）', where, bad, common)
    return margin_rows


# ── 外資持股與發行股數（兩市，Iteration 81）────────────────────────────────────

TWSE_MI_QFIIS = 'https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS'
TPEX_QFII = 'https://www.tpex.org.tw/www/zh-tw/insti/qfii'


def drop_transfer_duplicates(tw: list[dict], tp: list[dict]) -> list[dict]:
    """上櫃轉上市當天兩市的檔案都有這檔（2019-12-13 美時 1795、2026-10-15 幸福 8908 的外資持股表就是），證交所那列是首日佔位
    （持有股數 0 或幾萬股），櫃買那列才是當天的實際值；法人表與融資融券表那天也只在櫃買那邊有列。所以同一代號兩邊都有時，丟證交所列、留櫃買列，
    三張表一致。回傳去掉重複後的證交所列（櫃買列原樣用）。"""
    tp_ids = {r['stock_id'] for r in tp}
    return [r for r in tw if r['stock_id'] not in tp_ids]
HOLDING_RATIO_TOLERANCE = 0.5      # 持股比率（%）與持有股數 ÷ 發行股數 × 100 差超過這個數的列就當欄位對錯了


def fetch_twse_holding(d: date) -> dict:
    return _get_json(TWSE_MI_QFIIS, {'date': d.strftime('%Y%m%d'), 'selectType': 'ALLBUT0999', 'response': 'json'})


def fetch_tpex_holding(d: date) -> dict:
    return _get_json(TPEX_QFII, {'date': d.strftime('%Y/%m/%d'), 'response': 'json'})


def _holding_row(sid: str, trade_date: date, source: str, issued, held, ratio) -> Optional[dict]:
    issued, held, ratio = _int(issued), _int(held), _num(str(ratio).replace('%', '') if ratio is not None else None)
    if issued is None or held is None or issued <= 0:
        return None
    calc = held / issued * 100
    if ratio is not None and abs(ratio - calc) > HOLDING_RATIO_TOLERANCE:
        raise ExchangeFormatError(f'{source} 外資持股 {trade_date} {sid}：比率 {ratio} 與 {held}/{issued} 不符，欄位對應可能變了')
    return {'stock_id': sid, 'trade_date': trade_date, 'source': source, 'shares_issued': issued, 'foreign_shares': held,
            'foreign_ratio': round(calc, 2)}


def parse_twse_holding(payload: dict) -> list[dict]:
    """MI_QFIIS（selectType=ALLBUT0999）「外資及陸資投資持股統計」→ 個股列：發行股數、全體外資及陸資持有股數、持股比率（%）。休市回 []。"""
    if not isinstance(payload, dict) or str(payload.get('stat', '')).lower() != 'ok':
        return []
    trade_date = _ymd(payload.get('date'))
    fields = payload.get('fields') or []
    if trade_date is None or not fields:
        return []
    ix = {k: _field_index(fields, *v) for k, v in {'id': ('證券代號',), 'issued': ('發行股數',), 'held': ('全體外資及陸資持有股數',),
                                                   'ratio': ('全體外資及陸資持股比率',)}.items()}
    missing = [k for k, v in ix.items() if v < 0]
    if missing:
        raise ExchangeFormatError(f'MI_QFIIS 欄位找不到 {missing}：{fields}')
    rows = []
    for r in payload.get('data') or []:
        sid = str(_cell(r, ix['id']) or '').strip()
        if not sid:
            continue
        row = _holding_row(sid, trade_date, 'twse', _cell(r, ix['issued']), _cell(r, ix['held']), _cell(r, ix['ratio']))
        if row:
            rows.append(row)
    return rows


def parse_tpex_holding(payload: dict) -> list[dict]:
    """insti/qfii「櫃檯買賣股票僑外資及陸資持股比例排行表」→ 個股列：發行股數(A)、持有股數(C)、持股比率(E=C/A)（字串含 %）。休市 data 空，回 []。"""
    if not isinstance(payload, dict):
        return []
    table = next((t for t in payload.get('tables') or [] if t.get('data')), None)
    if table is None:
        return []
    trade_date = roc_date(table.get('date') or payload.get('date'))
    fields = table.get('fields') or []
    if trade_date is None:
        return []
    ix = {k: _field_index(fields, *v) for k, v in {'id': ('代號',), 'issued': ('發行股數(A)',), 'held': ('僑外資及陸資持有股數(C)',),
                                                   'ratio': ('僑外資及陸資持股比率(E=C/A)',)}.items()}
    missing = [k for k, v in ix.items() if v < 0]
    if missing:
        raise ExchangeFormatError(f'櫃買外資持股表 {trade_date} 欄位找不到 {missing}：{fields}')
    rows = []
    for r in table['data']:
        sid = str(_cell(r, ix['id']) or '').strip()
        if not sid:
            continue
        row = _holding_row(sid, trade_date, 'tpex', _cell(r, ix['issued']), _cell(r, ix['held']), _cell(r, ix['ratio']))
        if row:
            rows.append(row)
    return rows
