"""
夜盤資料探測：台指期夜盤對台股開盤跳空的預測力（Iteration 28 前置量測）

問題：Iteration 16 的跳空模型用「隔夜美股」預測台股次日開盤跳空，
走查相關 0.66。但台指期夜盤（15:00~翌日 05:00）是市場對次日開盤的**直接定價**，
理論上資訊含量應該更高。這支腳本只做量測，不建模、不部署。

FinMind `taiwan_futures_daily` 的 `trading_session` 分兩種：
    position      日盤 09:00~13:30
    after_market  夜盤（實測其收盤價幾乎等於同日日盤開盤 → 它領先當日開盤）

量測三件事：
  1. 夜盤隱含隔夜報酬與大盤實際開盤跳空的相關性
  2. 同上，但對個股跳空（與現有模型的比較基準）
  3. 夜盤 vs 美股隔夜，哪一個對個股跳空的解釋力高

用法：python probe_night_session.py [--start 2024-01-01]
"""

import argparse
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)


def fetch_tx(start: str, end: str) -> pd.DataFrame:
    """台指期近月，日盤與夜盤各一列。"""
    from FinMind.data import DataLoader
    dl = DataLoader()
    df = dl.taiwan_futures_daily(futures_id='TX', start_date=start, end_date=end)
    if df.empty:
        return df
    # 價差交易（契約月份含 '/'）不是單一契約報價，一律剔除
    df = df[~df['contract_date'].astype(str).str.contains('/')]
    df = df[df['volume'] > 0]
    # 近月＝該日該時段成交量最大的契約，比「最小契約月」穩健
    # （結算日前後最小月會變成即將到期、流動性已移轉的那一口）
    idx = df.groupby(['date', 'trading_session'])['volume'].idxmax()
    near = df.loc[idx, ['date', 'trading_session', 'open', 'max', 'min', 'close', 'volume']]
    return near.pivot(index='date', columns='trading_session',
                      values=['open', 'close', 'volume']).sort_index()


def load_tw(start: str) -> pd.DataFrame:
    from db.connection import get_conn
    with get_conn() as conn:
        return pd.read_sql("""
            SELECT stock_id, trade_date, open_price, close_price, adj_close
              FROM stock_daily_prices
             WHERE trade_date >= %s AND close_price > 0
             ORDER BY stock_id, trade_date
        """, conn, params=(start,))


def load_us(start: str) -> pd.DataFrame:
    from db.connection import get_conn
    with get_conn() as conn:
        return pd.read_sql("""
            SELECT ticker, trade_date, close_price
              FROM us_daily_prices
             WHERE trade_date >= %s AND close_price > 0
             ORDER BY ticker, trade_date
        """, conn, params=(start,))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default='2024-01-01')
    args = ap.parse_args()
    today = pd.Timestamp.today().strftime('%Y-%m-%d')

    print(f'\n抓取台指期 {args.start} ~ {today} …')
    tx = fetch_tx(args.start, today)
    if tx.empty:
        print('沒有期貨資料'); return
    tx.index = pd.to_datetime(tx.index)

    night_close = tx[('close', 'after_market')]
    day_open = tx[('open', 'position')]
    day_close = tx[('close', 'position')]
    night_vol = tx[('volume', 'after_market')]

    print(f'資料 {len(tx)} 個交易日，夜盤平均成交 {night_vol.mean():,.0f} 口'
          f'（日盤 {tx[("volume", "position")].mean():,.0f} 口）')

    # ── 1. 夜盤收盤 vs 同日日盤開盤 ──────────────────────────────────────
    # 若兩者高度一致，代表夜盤確實領先當日開盤（而非落後）
    gap_index = day_open / day_close.shift(1) - 1          # 大盤實際開盤跳空
    night_move = night_close / day_close.shift(1) - 1      # 夜盤隱含的隔夜變動
    ok = gap_index.notna() & night_move.notna()
    corr_idx = np.corrcoef(night_move[ok], gap_index[ok])[0, 1]
    err = (day_open[ok] / night_close[ok] - 1).abs()
    print(f'\n【1】夜盤隱含隔夜變動 vs 大盤開盤跳空')
    print(f'    相關係數 {corr_idx:.4f}（n={ok.sum()}）')
    print(f'    夜盤收盤與次日開盤的絕對差：中位數 {err.median():.3%}、'
          f'平均 {err.mean():.3%}、9 成分位 {err.quantile(.9):.3%}')

    # ── 2. 對個股跳空的解釋力 ───────────────────────────────────────────
    tw = load_tw(args.start)
    tw['trade_date'] = pd.to_datetime(tw['trade_date'])
    tw = tw.sort_values(['stock_id', 'trade_date'])
    g = tw.groupby('stock_id')
    # 除權息與減資會在 close 上造成機械性缺口，用 adj_close 還原（Iteration 18）
    factor = tw['adj_close'] / tw['close_price'].replace(0, np.nan)
    tw['agap'] = (tw['open_price'] * factor) / g['adj_close'].shift(1) - 1

    nm = night_move.rename('night').to_frame()
    nm.index.name = 'trade_date'
    m = tw.merge(nm, left_on='trade_date', right_index=True, how='inner').dropna(subset=['agap', 'night'])
    corr_stock = np.corrcoef(m['night'], m['agap'])[0, 1]
    print(f'\n【2】夜盤隱含變動 vs 個股開盤跳空')
    print(f'    全體相關 {corr_stock:.4f}（n={len(m):,}，{m["stock_id"].nunique()} 檔）')

    # ── 3. 與現有的美股訊號對照 ─────────────────────────────────────────
    us = load_us(args.start)
    if not us.empty:
        us['trade_date'] = pd.to_datetime(us['trade_date'])
        piv = us.pivot(index='trade_date', columns='ticker', values='close_price').sort_index()
        us_ret = (piv / piv.shift(1) - 1).reset_index().rename(columns={'trade_date': 'us_date'})

        # 台股 D 日開盤反映的是「D 之前最後一個美股交易日」的走勢。
        # 直接以同一個日期 merge 會對錯——美股與台股的休市日並不相同。
        tw_dates = pd.DataFrame({'trade_date': sorted(m['trade_date'].unique())})
        aligned = pd.merge_asof(tw_dates.sort_values('trade_date'),
                                us_ret.sort_values('us_date'),
                                left_on='trade_date', right_on='us_date',
                                allow_exact_matches=False)
        mm = m.merge(aligned, on='trade_date', how='left')

        print('')
        print('【3】與現有美股訊號的正面對決（同一批樣本）')
        for tkr in ('SOXX', 'NVDA', 'TSM', 'QQQ', 'SPY'):
            if tkr not in mm.columns:
                continue
            sub = mm.dropna(subset=[tkr, 'night', 'agap'])
            if len(sub) < 200:
                continue
            c_us = np.corrcoef(sub[tkr], sub['agap'])[0, 1]
            c_night = np.corrcoef(sub['night'], sub['agap'])[0, 1]
            print(f'    {tkr:5s} 美股隔夜 {c_us:+.4f}　夜盤 {c_night:+.4f}　（n={len(sub):,}）')

        base = mm.dropna(subset=['SOXX', 'night', 'agap']) if 'SOXX' in mm.columns else pd.DataFrame()
        if len(base) > 200:
            def r2_of(cols):
                X = np.column_stack([base[c] for c in cols] + [np.ones(len(base))])
                beta, *_ = np.linalg.lstsq(X, base['agap'].values, rcond=None)
                pred = X @ beta
                ss_res = ((base['agap'] - pred) ** 2).sum()
                ss_tot = ((base['agap'] - base['agap'].mean()) ** 2).sum()
                return 1 - ss_res / ss_tot
            r_n, r_u, r_b = r2_of(['night']), r2_of(['SOXX']), r2_of(['night', 'SOXX'])
            print('')
            print(f'【4】解釋力 R²（同一批 {len(base):,} 筆）')
            print(f'    只用夜盤      {r_n:.4f}')
            print(f'    只用費半 SOXX {r_u:.4f}')
            print(f'    兩者一起      {r_b:.4f}')
            print(f'    → 夜盤之外，美股額外貢獻 {r_b - r_n:+.4f}'
                  f'；費半之外，夜盤額外貢獻 {r_b - r_u:+.4f}')

    print('\n注意：以上只是相關性量測，不是走查驗證。要進部署還得走'
          '「擴張視窗走查 + 與現有模型對照 + 部署門檻」那一套。')


if __name__ == '__main__':
    main()
