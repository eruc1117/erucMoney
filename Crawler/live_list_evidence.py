"""印出目前清單的事實（給 record_check 當證據）：訊號日、檔數、價格日期、每檔權重與收盤。只讀，不改任何東西。"""
import portfolio_api

l = portfolio_api.live_list()
if not l:
    print('沒有清單')
    raise SystemExit(0)
print(f"rebalance_date={l['rebalance_date']} exec_date={l['exec_date']} items={len(l['items'])} price_date={l['price_date']} computed_at={l['computed_at'][:16]}")
for it in l['items']:
    print(f"{it['stock_id']:>6} {str(it['stock_name'] or ''):<10} rank={it['rank']} weight={it['target_weight']:.4f} price={it['price']} price_date={it['price_date']} new={it['is_new']}")
