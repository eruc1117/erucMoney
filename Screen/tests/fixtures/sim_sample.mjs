// 交易模擬匯入／匯出的共用樣本（Iteration 87）：tests 與產生範本的腳本（AI/experiments/iter87_templates.mjs）用同一份，
// 所以 AI/UserDoc/sim_templates/ 的匯出範本就是程式對這份樣本的實際輸出。
// INSTR_RESULT 的形狀照 Crawler/trading_sim.py run_text 的回傳（parsed、trades 的 line／asked、skipped）。
export const NOW = new Date(2026, 9, 19, 22, 30, 0)        // 2026-10-19 22:30 本地時間
export const FORM = { start: '2024-01-02', end: '2024-09-30', capital: 1000000, source: 'real', seed: 0 }
export const ROWS = [{ note: '零股' }, { note: '' }, { note: '用金額，當天開盤換算成股數' }]
export const INSTR_RESULT = {
  available: true, start: '2024-01-02', end: '2024-09-30', capital: 1000000, source: { kind: 'real', label: '真實行情' },
  metrics: { start: '2024-01-02', end: '2024-09-30', years: 0.74, months: 8, total_return: 0.0123, bench_return: 0.3012, active_return: -0.222, cagr_port: 0.0167, cagr_bench: 0.427, ann_active: -0.2876,
             tracking_error: 0.0412, info_ratio: -6.98, monthly_win_rate: 0.25, mdd_port: -0.0081, mdd_bench: -0.162, rel_mdd: -0.233, turnover_annual: 0.02, cost_drag_annual: 0.0001, final_nav: 1012300 },
  trades: [{ line: 1, asked: '2024-01-15', date: '2024-01-15', stock_id: '2330', side: 'buy', shares: 10, price: 589, gross: 5890, fee: 5.04, tax: 0, pnl: null, note: null },
           { line: 2, asked: '2024-06-01', date: '2024-06-03', stock_id: '2330', side: 'sell', shares: 10, price: 850, gross: 8500, fee: 7.27, tax: 25.5, pnl: 2572.19, note: '部分' }],
  skipped: [{ line: 3, date: '2024-02-01', stock_id: '0050', reason: '現金不夠' }],
  parsed: [{ line: 1, date: '2024-01-15', side: 'buy', stock_id: '2330', shares: 10, amount: null, all: false }, { line: 2, date: '2024-06-01', side: 'sell', stock_id: '2330', shares: null, amount: null, all: true },
           { line: 3, date: '2024-02-01', side: 'buy', stock_id: '0050', shares: null, amount: 50000, all: false }],
  final: { cash: 1012300, value: 1012300, holdings: [] }, realized_pnl: 2572.19, costs: 37.81,
  series: [{ d: '2024-01-02', nav: 1, bench: 1, cash: 1000000 }, { d: '2024-01-15', nav: 0.9999, bench: 1.012, cash: 994105 }, { d: '2024-06-03', nav: 1.0123, bench: 1.251, cash: 1012300 }, { d: '2024-09-30', nav: 1.0123, bench: 1.3012, cash: 1012300 }],
  caveat: '指令日當天開盤市價成交（沒行情順延）；價格是還原價、持股含息，和 0050 含息對稱；手續費 0.0855%、賣出稅 0.3%、沒有滑價。這是「照你說的做會怎樣」，不是建議。',
}
