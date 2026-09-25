// ============================================================
//  MOCK DATA — mirrors FastAPI / PostgreSQL / MongoDB schema
//  All generation functions run once at module load time.
// ============================================================

// ---------- stock_info ----------
export const WATCHLIST = [
  { stock_id:'2330', stock_name:'台積電', close_price:960.00, change_value:+15.00, change_rate:+1.59, volume:42831, turnover_value:41140, foreign_buy:+8204,  sentiment:'bullish', industry_type:'半導體業',    foreign_holding_ratio:75.3 },
  { stock_id:'2317', stock_name:'鴻海',   close_price:198.50, change_value:+3.50,  change_rate:+1.79, volume:89423, turnover_value:17750, foreign_buy:+12531, sentiment:'bullish', industry_type:'電子零組件業', foreign_holding_ratio:42.1 },
  { stock_id:'2454', stock_name:'聯發科', close_price:1245.00,change_value:+22.00, change_rate:+1.80, volume:15678, turnover_value:19519, foreign_buy:+4892,  sentiment:'neutral', industry_type:'半導體業',    foreign_holding_ratio:58.7 },
  { stock_id:'2412', stock_name:'中華電', close_price:115.50, change_value:-0.50,  change_rate:-0.43, volume:12456, turnover_value:1440,  foreign_buy:-823,   sentiment:'neutral', industry_type:'通信網路業',   foreign_holding_ratio:22.4 },
  { stock_id:'6505', stock_name:'台塑化', close_price:82.80,  change_value:-0.90,  change_rate:-1.08, volume:8934,  turnover_value:740,   foreign_buy:-1205,  sentiment:'bearish', industry_type:'油電燃氣業',   foreign_holding_ratio:18.9 },
]

export const STOCK_INFO = {
  '2330': { stock_id:'2330', stock_name:'台積電', industry_type:'半導體業',    market_type:'上市', close_price:960.00,  change_value:+15.00, change_rate:+1.59, volume:42831, turnover_value:41140, total_net_buy:+8204,  foreign_holding_ratio:75.3 },
  '2317': { stock_id:'2317', stock_name:'鴻海',   industry_type:'電子零組件業', market_type:'上市', close_price:198.50,  change_value:+3.50,  change_rate:+1.79, volume:89423, turnover_value:17750, total_net_buy:+12531, foreign_holding_ratio:42.1 },
  '2454': { stock_id:'2454', stock_name:'聯發科', industry_type:'半導體業',    market_type:'上市', close_price:1245.00, change_value:+22.00, change_rate:+1.80, volume:15678, turnover_value:19519, total_net_buy:+4892,  foreign_holding_ratio:58.7 },
  '2412': { stock_id:'2412', stock_name:'中華電', industry_type:'通信網路業',   market_type:'上市', close_price:115.50,  change_value:-0.50,  change_rate:-0.43, volume:12456, turnover_value:1440,  total_net_buy:-823,   foreign_holding_ratio:22.4 },
}

// ---------- stock_daily_prices (candlestick + volume) ----------
function buildPriceData(startPrice, seed) {
  const candles = [], volumes = []
  let price = startPrice
  const base = new Date('2025-12-01')
  let rng = seed

  function rand() { rng = (rng * 1664525 + 1013904223) & 0xffffffff; return (rng >>> 0) / 0xffffffff }

  for (let i = 0; i < 90; i++) {
    const d = new Date(base)
    d.setDate(base.getDate() + Math.floor(i * 1.42))
    const ts = d.getTime()
    const change = (rand() - 0.48) * startPrice * 0.025
    const open   = price
    const close  = Math.max(open + change, startPrice * 0.7)
    const high   = Math.max(open, close) * (1 + rand() * 0.008)
    const low    = Math.min(open, close) * (1 - rand() * 0.008)
    price = close
    candles.push({ x: ts, y: [+open.toFixed(2), +high.toFixed(2), +low.toFixed(2), +close.toFixed(2)] })
    volumes.push({ x: ts, y: Math.floor(15000 + rand() * 65000), up: close >= open })
  }
  return { candles, volumes }
}

export const PRICE_DATA = {
  '2330': buildPriceData(940, 42),
  '2317': buildPriceData(188, 17),
  '2454': buildPriceData(1180, 54),
  '2412': buildPriceData(117, 12),
}

// ---------- stock_chip_analysis (三大法人) ----------
function buildChipData(seed) {
  const dates = [], foreign = [], trust = [], dealer = []
  let rng = seed
  function rand() { rng = (rng * 1664525 + 1013904223) & 0xffffffff; return (rng >>> 0) / 0xffffffff }
  const base = new Date('2026-02-10')
  for (let i = 0; i < 20; i++) {
    const d = new Date(base); d.setDate(base.getDate() + i)
    dates.push(d.toISOString().slice(0, 10))
    foreign.push(Math.floor((rand() - 0.38) * 30000))
    trust.push(Math.floor((rand() - 0.45) * 8000))
    dealer.push(Math.floor((rand() - 0.50) * 6000))
  }
  return { dates, foreign, trust, dealer }
}

export const CHIP_DATA = {
  '2330': buildChipData(99),
  '2317': buildChipData(77),
  '2454': buildChipData(55),
  '2412': buildChipData(33),
}

// ---------- Market Trend (大盤走勢) ----------
function buildMarketTrend() {
  const dates = [], values = []
  let v = 21000, rng = 7
  function rand() { rng = (rng * 1664525 + 1013904223) & 0xffffffff; return (rng >>> 0) / 0xffffffff }
  const base = new Date('2026-02-10')
  for (let i = 0; i < 30; i++) {
    const d = new Date(base); d.setDate(base.getDate() + i)
    v += (rand() - 0.44) * 200
    dates.push(d.toISOString().slice(0, 10))
    values.push(+v.toFixed(2))
  }
  return { dates, values }
}
export const MARKET_TREND = buildMarketTrend()

// ---------- Sentiment ----------
export const SENTIMENT_DIST = { bullish: 112, neutral: 67, bearish: 68 }

function buildSentimentTimeline() {
  const dates = [], scores = []
  let rng = 22
  function rand() { rng = (rng * 1664525 + 1013904223) & 0xffffffff; return (rng >>> 0) / 0xffffffff }
  const base = new Date('2026-02-25')
  for (let i = 0; i < 14; i++) {
    const d = new Date(base); d.setDate(base.getDate() + i)
    dates.push(d.toISOString().slice(0, 10))
    scores.push(+(0.38 + rand() * 0.48).toFixed(3))
  }
  return { dates, scores }
}
export const SENTIMENT_TIMELINE = buildSentimentTimeline()

export const KEYWORDS = [
  { word: 'AI晶片',   freq: 128 },
  { word: '台積電',   freq: 115 },
  { word: 'CoWoS',    freq: 89  },
  { word: '輝達',     freq: 83  },
  { word: 'HBM記憶體',freq: 72  },
  { word: '半導體',   freq: 68  },
  { word: '蘋果',     freq: 54  },
  { word: '美聯儲',   freq: 47  },
]

// ---------- News (MongoDB raw_news) ----------
export const NEWS = [
  { source_id:'n01', platform:'Yahoo Finance 台灣', raw_title:'台積電CoWoS封裝訂單爆滿，AI需求推升營收新高',       author:'王大明', publish_at:'2026-03-11T09:15:00Z', sentiment:'bullish', sentiment_score:0.87, tags:['AI晶片','台積電','CoWoS'],    tickers:['2330'] },
  { source_id:'n02', platform:'CNN Business',       raw_title:'NVIDIA Reports Record AI Chip Revenue, TSMC Supply Tight', author:'Sarah Chen', publish_at:'2026-03-11T08:30:00Z', sentiment:'bullish', sentiment_score:0.82, tags:['NVIDIA','AI','Chips'],       tickers:['NVDA','TSMC'] },
  { source_id:'n03', platform:'Yahoo Finance 台灣', raw_title:'聯發科天璣9500出貨超預期，Q1營收上修',               author:'李小華', publish_at:'2026-03-11T08:00:00Z', sentiment:'bullish', sentiment_score:0.78, tags:['聯發科','天璣','手機晶片'],  tickers:['2454'] },
  { source_id:'n04', platform:'Yahoo Finance 台灣', raw_title:'鴻海MIH電動車平台獲印度大廠採用，股價震盪',           author:'張志偉', publish_at:'2026-03-10T15:30:00Z', sentiment:'neutral', sentiment_score:0.55, tags:['鴻海','電動車','MIH'],       tickers:['2317'] },
  { source_id:'n05', platform:'CNN Business',       raw_title:'Fed Signals Rates to Stay Higher as Inflation Persists', author:'Mike Johnson', publish_at:'2026-03-10T14:00:00Z', sentiment:'bearish', sentiment_score:0.22, tags:['Fed','Rates','Inflation'],   tickers:[] },
  { source_id:'n06', platform:'Yahoo Finance 台灣', raw_title:'台積電赴美廠良率突破90%，超越台灣廠標準',             author:'陳俊傑', publish_at:'2026-03-10T11:00:00Z', sentiment:'bullish', sentiment_score:0.91, tags:['台積電','美國廠','良率'],    tickers:['2330'] },
  { source_id:'n07', platform:'CNN Business',       raw_title:'China Semiconductor Restrictions Tightened',             author:'Amy Wong', publish_at:'2026-03-10T09:00:00Z', sentiment:'bearish', sentiment_score:0.28, tags:['China','Restrictions','IC'],  tickers:['INTC','NVDA'] },
  { source_id:'n08', platform:'Yahoo Finance 台灣', raw_title:'台股外資連三日買超逾百億，半導體族群領漲',             author:'黃士豪', publish_at:'2026-03-09T17:00:00Z', sentiment:'bullish', sentiment_score:0.76, tags:['外資','買超','半導體'],      tickers:['2330','2454'] },
  { source_id:'n09', platform:'Yahoo Finance 台灣', raw_title:'台塑化煉油利潤縮小，原油走軟拖累獲利',                 author:'林美玲', publish_at:'2026-03-09T14:00:00Z', sentiment:'bearish', sentiment_score:0.31, tags:['台塑化','原油','煉油'],      tickers:['6505'] },
  { source_id:'n10', platform:'CNN Business',       raw_title:'Global Tech Spending Outlook Revised Upward for 2026',   author:'David Lee', publish_at:'2026-03-09T10:00:00Z', sentiment:'neutral', sentiment_score:0.58, tags:['Tech','Spending','Forecast'], tickers:[] },
  { source_id:'n11', platform:'Yahoo Finance 台灣', raw_title:'中華電信5G用戶破千萬，企業寬頻帶動穩健成長',           author:'吳雅婷', publish_at:'2026-03-08T16:00:00Z', sentiment:'neutral', sentiment_score:0.61, tags:['中華電','5G','寬頻'],       tickers:['2412'] },
  { source_id:'n12', platform:'CNN Business',       raw_title:'Apple Increases TSMC Packaging Orders for iPhone 18',    author:'Rachel Kim', publish_at:'2026-03-08T08:00:00Z', sentiment:'bullish', sentiment_score:0.84, tags:['Apple','TSMC','iPhone'],     tickers:['AAPL','2330'] },
]

// ---------- Prediction ----------
function buildPrediction() {
  const actual = [], dates = []
  let price = 930, rng = 88
  function rand() { rng = (rng * 1664525 + 1013904223) & 0xffffffff; return (rng >>> 0) / 0xffffffff }
  const base = new Date('2026-02-10')
  for (let i = 0; i < 30; i++) {
    const d = new Date(base); d.setDate(base.getDate() + i)
    price += (rand() - 0.45) * 18
    dates.push(d.getTime())
    actual.push(+price.toFixed(2))
  }
  const predicted = actual.map(v => +(v + (Math.random() - 0.5) * 20).toFixed(2))
  return { dates, actual, predicted }
}
export const PREDICTION_DATA = buildPrediction()

export function buildForecast(lastPrice = 960) {
  const rows = []
  let price = lastPrice, rng = 11
  function rand() { rng = (rng * 1664525 + 1013904223) & 0xffffffff; return (rng >>> 0) / 0xffffffff }
  const base = new Date('2026-03-12')
  for (let i = 0; i < 7; i++) {
    const d = new Date(base); d.setDate(base.getDate() + i)
    const prev = price
    price += (rand() - 0.42) * 20
    const cv = price - prev
    const margin = 12 + rand() * 10
    rows.push({
      date: d.toISOString().slice(0, 10),
      predicted_close: +price.toFixed(2),
      change_value: +cv.toFixed(2),
      change_rate: +(cv / prev * 100).toFixed(2),
      sentiment_weight: +(0.5 + rand() * 0.4).toFixed(3),
      ci_low:  +(price - margin).toFixed(2),
      ci_high: +(price + margin).toFixed(2),
    })
  }
  return rows
}

export const FEATURES = [
  { name: 'X3：股價歷史 (LSTM)',      value: 40 },
  { name: 'X1：新聞情緒得分 (BERT)',  value: 35 },
  { name: 'X2：關鍵字頻率 (TF-IDF)', value: 25 },
]
