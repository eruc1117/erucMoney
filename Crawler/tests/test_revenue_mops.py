"""MOPS 營業收入彙總表（Iteration 48）：巢狀表格只取最內層列、千元→元、月份對應（公布月）、寫入不動既有公告日。"""
from datetime import date

import pytest

import backfill_revenue_mops as mops
from tests.conftest import fixture_text


def test_parse_real_page_row_units_and_month():
    rows = mops.parse_summary(fixture_text('mops_revenue_summary.html'), 2026, 8)
    assert len(rows) == 1
    r = rows[0]
    assert r['stock_id'] == '1256'
    assert r['revenue'] == 648_858_000                      # 千元 × 1000
    assert r['prev_month_revenue'] == 619_291_000 and r['last_year_revenue'] == 516_828_000
    assert r['revenue_month'] == date(2026, 9, 1)            # 8 月營收 → revenue_month 是 9 月 1 日（FinMind 慣例）


NESTED = '''<html><body><table><tr><td>
  <table>
    <tr><td>公司代號</td><td>公司名稱</td><td>當月營收</td><td>上月營收</td><td>去年當月營收</td><td>a</td><td>b</td><td>c</td><td>d</td><td>e</td><td>備註</td></tr>
    <tr><td>2330</td><td>台積電</td><td>514,805,337</td><td>467,580,548</td><td>335,771,691</td><td>10.10</td><td>53.32</td><td>x</td><td>y</td><td>z</td><td>-</td></tr>
    <tr><td>9999</td><td>沒數字</td><td>-</td><td>-</td><td>-</td><td></td><td></td><td></td><td></td><td></td><td>-</td></tr>
    <tr><td>2330</td><td>台積電(重複)</td><td>1</td><td>1</td><td>1</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
    <tr><td>合計</td><td></td><td>514,805,338</td><td>1</td><td>1</td><td></td><td></td><td></td><td></td><td></td><td></td></tr>
  </table>
</td></tr></table></body></html>'''


def test_parse_nested_tables_only_innermost_rows_and_dedup():
    rows = mops.parse_summary(NESTED, 2026, 12)
    assert [r['stock_id'] for r in rows] == ['2330']        # 外層「整張表一格」的列、合計列、沒數字的列、重複代號都不算
    assert rows[0]['revenue'] == 514_805_337_000
    assert rows[0]['revenue_month'] == date(2027, 1, 1)      # 12 月營收 → 次年 1 月
    assert rows[0]['note'] == '-'
    assert mops.parse_summary('<html></html>', 2026, 1) == []


@pytest.mark.parametrize('y, m, expected', [(2026, 8, date(2026, 9, 1)), (2026, 12, date(2027, 1, 1)), (2016, 10, date(2016, 11, 1))])
def test_revenue_month_for(y, m, expected):
    assert mops.revenue_month_for(y, m) == expected


def test_months_iterator_crosses_year():
    assert list(mops.months((2025, 11), (2026, 2))) == [(2025, 11), (2025, 12), (2026, 1), (2026, 2)]
    assert list(mops.months((2026, 3), (2026, 2))) == []


@pytest.mark.db
def test_upsert_revenue_keeps_existing_announce_fields(clean_db):
    """彙總表只有營收數字：寫入後既有的公告日與來源（鉅亨速報）要原封不動，營收被最新值覆蓋。"""
    from backfill_revenue import upsert
    db = clean_db
    db.execute("""INSERT INTO stock_revenue_announce (stock_id, revenue_month, announce_date, announce_ts, revenue, announce_source)
                  VALUES ('2330', '2026-09-01', '2026-09-10', '2026-09-10 13:51:47', 1, 'cnyes_item')""")
    rows = mops.parse_summary(NESTED, 2026, 8)
    assert upsert([{'stock_id': r['stock_id'], 'revenue_month': r['revenue_month'].isoformat(), 'announce_date': None, 'revenue': r['revenue']} for r in rows]) == 1
    got = db.query("SELECT revenue, announce_date, announce_source FROM stock_revenue_announce WHERE stock_id='2330'")[0]
    assert int(got[0]) == 514_805_337_000 and got[1] == date(2026, 9, 10) and got[2] == 'cnyes_item'
    # 沒有既有列：新增，公告日留空
    upsert([{'stock_id': '1256', 'revenue_month': '2026-09-01', 'announce_date': None, 'revenue': 648_858_000}])
    assert db.query("SELECT announce_date, announce_source FROM stock_revenue_announce WHERE stock_id='1256'")[0] == (None, None)
