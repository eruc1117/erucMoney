// ============================================================
//  MOCK DATA — mirrors FastAPI / PostgreSQL / MongoDB schema
// ============================================================

// ---------- Watchlist ----------
const WATCHLIST = [
  { stock_id:'2330', stock_name:'台積電', close_price:960.00, change_value:+15.00, change_rate:+1.59, volume:42831, turnover_value:41140, foreign_buy:+8204, sentiment:'bullish', industry_type:'半導體業', market_type:'上市', foreign_holding_ratio:75.3 },
  { stock_id:'2317', stock_name:'鴻海',   close_price:198.50, change_value:+3.50,  change_rate:+1.79, volume:89423, turnover_value:17750, foreign_buy:+12531, sentiment:'bullish', industry_type:'電子零組件業', market_type:'上市', foreign_holding_ratio:42.1 },
  { stock_id:'2454', stock_name:'聯發科', close_price:1245.00,change_value:+22.00, change_rate:+1.80, volume:15678, turnover_value:19519, foreign_buy:+4892,  sentiment:'neutral', industry_type:'半導體業', market_type:'上市', foreign_holding_ratio:58.7 },
  { stock_id:'2412', stock_name:'中華電', close_price:115.50, change_value:-0.50,  change_rate:-0.43, volume:12456, turnover_value:1440,  foreign_buy:-823,   sentiment:'neutral', industry_type:'通信網路業', market_type:'上市', foreign_holding_ratio:22.4 },
  { stock_id:'6505', stock_name:'台塑化', close_price:82.80,  change_value:-0.90,  change_rate:-1.08, volume:8934,  turnover_value:740,   foreign_buy:-1205,  sentiment:'bearish', industry_type:'油電燃氣業', market_type:'上市', foreign_holding_ratio:18.9 },
];

// ---------- Stock Info by ID ----------
const STOCK_INFO = {
  '2330': { stock_id:'2330', stock_name:'台積電', industry_type:'半導體業', market_type:'上市', close_price:960.00, change_value:+15.00, change_rate:+1.59, volume:42831, turnover_value:41140, total_net_buy:+8204, foreign_holding_ratio:75.3 },
  '2317': { stock_id:'2317', stock_name:'鴻海',   industry_type:'電子零組件業', market_type:'上市', close_price:198.50, change_value:+3.50, change_rate:+1.79, volume:89423, turnover_value:17750, total_net_buy:+12531, foreign_holding_ratio:42.1 },
  '2454': { stock_id:'2454', stock_name:'聯發科', industry_type:'半導體業', market_type:'上市', close_price:1245.00, change_value:+22.00, change_rate:+1.80, volume:15678, turnover_value:19519, total_net_buy:+4892, foreign_holding_ratio:58.7 },
  '2412': { stock_id:'2412', stock_name:'中華電', industry_type:'通信網路業', market_type:'上市', close_price:115.50, change_value:-0.50, change_rate:-0.43, volume:12456, turnover_value:1440, total_net_buy:-823, foreign_holding_ratio:22.4 },
};

// ---------- Candlestick + Volume data generator ----------
function generatePriceData(startPrice, days) {
  const data = [];
  const volData = [];
  let price = startPrice;
  const startDate = new Date('2025-12-01');

  for (let i = 0; i < days; i++) {
    const date = new Date(startDate);
    date.setDate(startDate.getDate() + Math.floor(i * 1.4)); // skip weekends roughly
    const d = date.getTime();

    const change = (Math.random() - 0.48) * startPrice * 0.025;
    const open   = price;
    const close  = Math.max(price + change, startPrice * 0.7);
    const high   = Math.max(open, close) * (1 + Math.random() * 0.008);
    const low    = Math.min(open, close) * (1 - Math.random() * 0.008);
    price = close;

    data.push({ x: d, y: [+open.toFixed(2), +high.toFixed(2), +low.toFixed(2), +close.toFixed(2)] });
    volData.push({ x: d, y: Math.floor(20000 + Math.random() * 60000), color: close >= open ? '#3fb950' : '#f85149' });
  }
  return { candles: data, volumes: volData };
}

const PRICE_DATA = {
  '2330': generatePriceData(940, 90),
  '2317': generatePriceData(188, 90),
  '2454': generatePriceData(1180, 90),
  '2412': generatePriceData(117, 90),
};

// ---------- Three Major Investors (stock_chip_analysis) ----------
function generateChipData(days) {
  const dates = [], foreign = [], trust = [], dealer = [];
  const base = new Date('2026-02-10');
  for (let i = 0; i < days; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    dates.push(d.toISOString().slice(0,10));
    foreign.push(Math.floor((Math.random() - 0.35) * 30000));
    trust.push(Math.floor((Math.random() - 0.45) * 8000));
    dealer.push(Math.floor((Math.random() - 0.5) * 6000));
  }
  return { dates, foreign, trust, dealer };
}

const CHIP_DATA = {
  '2330': generateChipData(20),
  '2317': generateChipData(20),
  '2454': generateChipData(20),
  '2412': generateChipData(20),
};

// ---------- Market Trend (30 days) ----------
function generateMarketTrend() {
  const dates = [], values = [];
  let v = 21000;
  const base = new Date('2026-02-10');
  for (let i = 0; i < 30; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    v += (Math.random() - 0.45) * 200;
    dates.push(d.toISOString().slice(0,10));
    values.push(+v.toFixed(2));
  }
  return { dates, values };
}
const MARKET_TREND = generateMarketTrend();

// ---------- Sentiment (MongoDB + NLP pipeline) ----------
const SENTIMENT_DIST = { bullish: 112, neutral: 67, bearish: 68 };

function generateSentimentTimeline() {
  const dates = [], scores = [];
  const base = new Date('2026-02-25');
  for (let i = 0; i < 14; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    dates.push(d.toISOString().slice(0,10));
    scores.push(+(0.4 + Math.random() * 0.45).toFixed(3));
  }
  return { dates, scores };
}
const SENTIMENT_TIMELINE = generateSentimentTimeline();

// Hot keywords (TF-IDF)
const KEYWORDS = [
  { word:'AI晶片',  freq:128 },
  { word:'台積電',  freq:115 },
  { word:'CoWoS',   freq:89  },
  { word:'輝達',    freq:83  },
  { word:'HBM記憶體',freq:72 },
  { word:'半導體',  freq:68  },
  { word:'蘋果',    freq:54  },
  { word:'美聯儲',  freq:47  },
];

// News feed (raw_news schema from MongoDB)
const NEWS = [
  { source_id:'n001', platform:'Yahoo Finance 台灣', raw_title:'台積電CoWoS封裝訂單爆滿，AI需求推升營收新高', author:'王大明', publish_at:'2026-03-11T09:15:00Z', sentiment:'bullish', sentiment_score:0.87, tags:['AI晶片','台積電','CoWoS'], stock_tickers:['TSMC','2330'] },
  { source_id:'n002', platform:'CNN Business', raw_title:'NVIDIA Reports Record AI Chip Revenue, TSMC Supply Tight', author:'Sarah Chen', publish_at:'2026-03-11T08:30:00Z', sentiment:'bullish', sentiment_score:0.82, tags:['NVIDIA','AI','Chips'], stock_tickers:['NVDA','TSMC'] },
  { source_id:'n003', platform:'Yahoo Finance 台灣', raw_title:'聯發科天璣9500系列出貨量超預期，Q1營收上修', author:'李小華', publish_at:'2026-03-11T08:00:00Z', sentiment:'bullish', sentiment_score:0.78, tags:['聯發科','天璣','手機晶片'], stock_tickers:['2454'] },
  { source_id:'n004', platform:'Yahoo Finance 台灣', raw_title:'鴻海MIH電動車平台獲印度大廠採用，股價震盪', author:'張志偉', publish_at:'2026-03-10T15:30:00Z', sentiment:'neutral', sentiment_score:0.55, tags:['鴻海','電動車','MIH'], stock_tickers:['2317'] },
  { source_id:'n005', platform:'CNN Business', raw_title:'Fed Signals Rates to Stay Higher as Inflation Persists', author:'Mike Johnson', publish_at:'2026-03-10T14:00:00Z', sentiment:'bearish', sentiment_score:0.22, tags:['Fed','Rates','Inflation'], stock_tickers:[] },
  { source_id:'n006', platform:'Yahoo Finance 台灣', raw_title:'台積電赴美亞利桑那廠良率突破90%，超越台灣廠標準', author:'陳俊傑', publish_at:'2026-03-10T11:00:00Z', sentiment:'bullish', sentiment_score:0.91, tags:['台積電','美國廠','良率'], stock_tickers:['2330'] },
  { source_id:'n007', platform:'CNN Business', raw_title:'China Semiconductor Restrictions Tightened, Impact Assessed', author:'Amy Wong', publish_at:'2026-03-10T09:00:00Z', sentiment:'bearish', sentiment_score:0.28, tags:['China','Restrictions','Semiconductor'], stock_tickers:['INTC','NVDA'] },
  { source_id:'n008', platform:'Yahoo Finance 台灣', raw_title:'台股外資連三日買超逾百億，半導體族群領漲', author:'黃士豪', publish_at:'2026-03-09T17:00:00Z', sentiment:'bullish', sentiment_score:0.76, tags:['外資','買超','半導體'], stock_tickers:['2330','2454'] },
  { source_id:'n009', platform:'Yahoo Finance 台灣', raw_title:'台塑化煉油利潤縮小，原油價格走軟拖累獲利', author:'林美玲', publish_at:'2026-03-09T14:00:00Z', sentiment:'bearish', sentiment_score:0.31, tags:['台塑化','原油','煉油'], stock_tickers:['6505'] },
  { source_id:'n010', platform:'CNN Business', raw_title:'Global Tech Spending Outlook Revised Upward for 2026', author:'David Lee', publish_at:'2026-03-09T10:00:00Z', sentiment:'neutral', sentiment_score:0.58, tags:['Tech','Spending','Forecast'], stock_tickers:[] },
  { source_id:'n011', platform:'Yahoo Finance 台灣', raw_title:'中華電信5G用戶數破千萬，企業寬頻帶動穩健成長', author:'吳雅婷', publish_at:'2026-03-08T16:00:00Z', sentiment:'neutral', sentiment_score:0.61, tags:['中華電','5G','寬頻'], stock_tickers:['2412'] },
  { source_id:'n012', platform:'CNN Business', raw_title:'Apple Increases TSMC Advanced Packaging Orders for iPhone 18', author:'Rachel Kim', publish_at:'2026-03-08T08:00:00Z', sentiment:'bullish', sentiment_score:0.84, tags:['Apple','TSMC','iPhone'], stock_tickers:['AAPL','TSMC','2330'] },
];

// ---------- Prediction Data ----------
function generatePredictionData() {
  const actual = [], dates = [];
  const base = new Date('2026-02-10');
  let price = 930;
  for (let i = 0; i < 30; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    price += (Math.random() - 0.45) * 18;
    dates.push(d.getTime());
    actual.push(+price.toFixed(2));
  }
  // Predicted (slight noise from actual)
  const predicted = actual.map(v => +(v + (Math.random() - 0.5) * 20).toFixed(2));

  return { dates, actual, predicted };
}
const PREDICTION_DATA = generatePredictionData();

// 7-day forecast
function generateForecast(lastPrice) {
  const rows = [];
  let price = lastPrice;
  const base = new Date('2026-03-12');
  for (let i = 0; i < 7; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    const prev = price;
    price += (Math.random() - 0.42) * 20;
    const change = price - prev;
    const pct    = (change / prev * 100);
    const margin = 12 + Math.random() * 10;
    rows.push({
      date: d.toISOString().slice(0,10),
      predicted_close: +price.toFixed(2),
      change_value: +change.toFixed(2),
      change_rate: +pct.toFixed(2),
      sentiment_weight: +(0.5 + Math.random() * 0.4).toFixed(3),
      ci_low:  +(price - margin).toFixed(2),
      ci_high: +(price + margin).toFixed(2),
    });
  }
  return rows;
}
const FORECAST = generateForecast(960);

// Feature importance
const FEATURES = [
  { name: 'X3：股價歷史 (LSTM)', value: 40 },
  { name: 'X1：新聞情緒得分 (BERT)', value: 35 },
  { name: 'X2：關鍵字頻率 (TF-IDF)', value: 25 },
];
