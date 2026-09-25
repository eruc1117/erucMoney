// ============================================================
//  CHART INSTANCES — ApexCharts
// ============================================================

const CHART_DEFAULTS = {
  theme: { mode: 'dark' },
  chart: { background: 'transparent', toolbar: { show: false }, animations: { enabled: true, speed: 400 } },
  grid: { borderColor: '#30363d', strokeDashArray: 3 },
  tooltip: { theme: 'dark' },
};

let charts = {};

function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

// ---------- Market Trend Line ----------
function initMarketTrendChart() {
  destroyChart('market-trend');
  charts['market-trend'] = new ApexCharts(document.getElementById('chart-market-trend'), {
    ...CHART_DEFAULTS,
    chart: { ...CHART_DEFAULTS.chart, type: 'area', height: 220 },
    series: [{ name: '加權指數', data: MARKET_TREND.values }],
    xaxis: {
      categories: MARKET_TREND.dates,
      labels: { style: { colors: '#8b949e', fontSize: '11px' }, rotate: -30, maxHeight: 50 },
      tickAmount: 6,
    },
    yaxis: {
      labels: { style: { colors: '#8b949e', fontSize: '11px' }, formatter: v => v.toLocaleString() },
      min: Math.min(...MARKET_TREND.values) * 0.995,
    },
    stroke: { curve: 'smooth', width: 2, colors: ['#58a6ff'] },
    fill: { type: 'gradient', gradient: { shadeIntensity: 1, opacityFrom: 0.3, opacityTo: 0.01, stops: [0, 100] } },
    colors: ['#58a6ff'],
    dataLabels: { enabled: false },
    tooltip: { ...CHART_DEFAULTS.tooltip, x: { show: true } },
  });
  charts['market-trend'].render();
}

// ---------- Sentiment Donut ----------
function initSentimentDonutChart() {
  destroyChart('sentiment-donut');
  charts['sentiment-donut'] = new ApexCharts(document.getElementById('chart-sentiment-donut'), {
    ...CHART_DEFAULTS,
    chart: { ...CHART_DEFAULTS.chart, type: 'donut', height: 220 },
    series: [SENTIMENT_DIST.bullish, SENTIMENT_DIST.neutral, SENTIMENT_DIST.bearish],
    labels: ['利多', '中立', '利空'],
    colors: ['#3fb950', '#58a6ff', '#f85149'],
    plotOptions: { pie: { donut: { size: '62%', labels: { show: true, total: { show: true, label: '總新聞', color: '#8b949e', fontSize: '12px', formatter: () => (SENTIMENT_DIST.bullish + SENTIMENT_DIST.neutral + SENTIMENT_DIST.bearish) + ' 則' } } } } },
    legend: { position: 'bottom', labels: { colors: '#8b949e' }, fontSize: '12px' },
    dataLabels: { style: { fontSize: '12px' } },
  });
  charts['sentiment-donut'].render();
}

// ---------- Candlestick ----------
function initCandlestickChart(stockId, days) {
  destroyChart('candlestick');
  destroyChart('volume');

  const data = PRICE_DATA[stockId] || PRICE_DATA['2330'];
  const slice = data.candles.slice(-days);
  const volSlice = data.volumes.slice(-days);

  charts['candlestick'] = new ApexCharts(document.getElementById('chart-candlestick'), {
    ...CHART_DEFAULTS,
    chart: { ...CHART_DEFAULTS.chart, type: 'candlestick', height: 280, id: 'candles', brush: { enabled: false } },
    series: [{ data: slice }],
    xaxis: {
      type: 'datetime',
      labels: { style: { colors: '#8b949e', fontSize: '11px' }, datetimeUTC: false },
      axisBorder: { color: '#30363d' },
    },
    yaxis: {
      tooltip: { enabled: true },
      labels: { style: { colors: '#8b949e', fontSize: '11px' } },
    },
    plotOptions: {
      candlestick: {
        colors: { upward: '#3fb950', downward: '#f85149' },
        wick: { useFillColor: true },
      },
    },
    tooltip: { ...CHART_DEFAULTS.tooltip, x: { format: 'yyyy-MM-dd' } },
  });
  charts['candlestick'].render();

  charts['volume'] = new ApexCharts(document.getElementById('chart-volume'), {
    ...CHART_DEFAULTS,
    chart: { ...CHART_DEFAULTS.chart, type: 'bar', height: 100, brush: { enabled: false } },
    series: [{ name: '成交量', data: volSlice.map(v => ({ x: v.x, y: v.y })) }],
    xaxis: {
      type: 'datetime',
      labels: { show: false },
      axisBorder: { color: '#30363d' },
    },
    yaxis: { labels: { style: { colors: '#8b949e', fontSize: '10px' }, formatter: v => (v/1000).toFixed(0) + 'K' } },
    colors: volSlice.map(v => v.color),
    plotOptions: { bar: { columnWidth: '80%' } },
    dataLabels: { enabled: false },
    tooltip: { ...CHART_DEFAULTS.tooltip, x: { format: 'yyyy-MM-dd' } },
  });
  charts['volume'].render();
}

// ---------- Three Major Investors ----------
function initChipChart(stockId) {
  destroyChart('chip');
  const d = CHIP_DATA[stockId] || CHIP_DATA['2330'];
  charts['chip'] = new ApexCharts(document.getElementById('chart-chip'), {
    ...CHART_DEFAULTS,
    chart: { ...CHART_DEFAULTS.chart, type: 'bar', height: 240 },
    series: [
      { name: '外資買超', data: d.foreign },
      { name: '投信買超', data: d.trust },
      { name: '自營商買超', data: d.dealer },
    ],
    xaxis: {
      categories: d.dates,
      labels: { style: { colors: '#8b949e', fontSize: '10px' }, rotate: -30 },
      tickAmount: 10,
    },
    yaxis: { labels: { style: { colors: '#8b949e', fontSize: '11px' }, formatter: v => (v >= 0 ? '+' : '') + v.toLocaleString() } },
    colors: ['#58a6ff', '#3fb950', '#e3b341'],
    plotOptions: { bar: { columnWidth: '70%', grouped: true } },
    dataLabels: { enabled: false },
    legend: { position: 'top', labels: { colors: '#8b949e' }, fontSize: '12px' },
  });
  charts['chip'].render();
}

// ---------- Sentiment Timeline ----------
function initSentimentTimelineChart() {
  destroyChart('sentiment-timeline');
  charts['sentiment-timeline'] = new ApexCharts(document.getElementById('chart-sentiment-timeline'), {
    ...CHART_DEFAULTS,
    chart: { ...CHART_DEFAULTS.chart, type: 'line', height: 220 },
    series: [{ name: '平均情緒分數', data: SENTIMENT_TIMELINE.scores }],
    xaxis: {
      categories: SENTIMENT_TIMELINE.dates,
      labels: { style: { colors: '#8b949e', fontSize: '11px' }, rotate: -30 },
      tickAmount: 7,
    },
    yaxis: {
      min: 0, max: 1,
      labels: { style: { colors: '#8b949e', fontSize: '11px' }, formatter: v => v.toFixed(2) },
    },
    stroke: { curve: 'smooth', width: 2, colors: ['#e3b341'] },
    annotations: {
      yaxis: [
        { y: 0.6, borderColor: '#3fb950', label: { text: '利多閾值 0.6', style: { color: '#3fb950', background: 'transparent', fontSize: '10px' } } },
        { y: 0.4, borderColor: '#f85149', label: { text: '利空閾值 0.4', style: { color: '#f85149', background: 'transparent', fontSize: '10px' } } },
      ],
    },
    markers: { size: 4, colors: ['#e3b341'] },
    dataLabels: { enabled: false },
  });
  charts['sentiment-timeline'].render();
}

// ---------- Keyword Bar ----------
function initKeywordsChart() {
  destroyChart('keywords');
  charts['keywords'] = new ApexCharts(document.getElementById('chart-keywords'), {
    ...CHART_DEFAULTS,
    chart: { ...CHART_DEFAULTS.chart, type: 'bar', height: 220 },
    series: [{ name: '出現次數', data: KEYWORDS.map(k => k.freq) }],
    xaxis: {
      categories: KEYWORDS.map(k => k.word),
      labels: { style: { colors: '#8b949e', fontSize: '11px' } },
    },
    yaxis: { labels: { style: { colors: '#8b949e', fontSize: '11px' } } },
    colors: ['#bc8cff'],
    plotOptions: { bar: { borderRadius: 4, horizontal: true, barHeight: '60%' } },
    dataLabels: { enabled: true, style: { fontSize: '11px', colors: ['#c9d1d9'] } },
    tooltip: { ...CHART_DEFAULTS.tooltip },
  });
  charts['keywords'].render();
}

// ---------- Prediction Line ----------
function initPredictionChart() {
  destroyChart('prediction');
  charts['prediction'] = new ApexCharts(document.getElementById('chart-prediction'), {
    ...CHART_DEFAULTS,
    chart: { ...CHART_DEFAULTS.chart, type: 'line', height: 280 },
    series: [
      { name: '實際收盤價', data: PREDICTION_DATA.actual },
      { name: 'LSTM 預測',  data: PREDICTION_DATA.predicted },
    ],
    xaxis: {
      type: 'datetime',
      categories: PREDICTION_DATA.dates,
      labels: { style: { colors: '#8b949e', fontSize: '11px' }, datetimeUTC: false, format: 'MM/dd' },
    },
    yaxis: {
      labels: { style: { colors: '#8b949e', fontSize: '11px' } },
      min: Math.min(...PREDICTION_DATA.actual, ...PREDICTION_DATA.predicted) * 0.99,
    },
    stroke: { curve: 'smooth', width: [2, 2], dashArray: [0, 5] },
    colors: ['#3fb950', '#58a6ff'],
    markers: { size: 0 },
    dataLabels: { enabled: false },
    legend: { position: 'top', labels: { colors: '#8b949e' }, fontSize: '12px' },
  });
  charts['prediction'].render();
}

// ---------- Feature Importance ----------
function initFeaturesChart() {
  destroyChart('features');
  charts['features'] = new ApexCharts(document.getElementById('chart-features'), {
    ...CHART_DEFAULTS,
    chart: { ...CHART_DEFAULTS.chart, type: 'bar', height: 200 },
    series: [{ name: '重要性 (%)', data: FEATURES.map(f => f.value) }],
    xaxis: {
      categories: FEATURES.map(f => f.name),
      labels: { style: { colors: '#8b949e', fontSize: '12px' } },
    },
    yaxis: {
      max: 50,
      labels: { style: { colors: '#8b949e', fontSize: '11px' }, formatter: v => v + '%' },
    },
    colors: ['#58a6ff'],
    plotOptions: { bar: { borderRadius: 4, columnWidth: '50%' } },
    dataLabels: { enabled: true, formatter: v => v + '%', style: { fontSize: '12px', colors: ['#c9d1d9'] } },
  });
  charts['features'].render();
}
