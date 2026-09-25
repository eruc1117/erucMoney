// ============================================================
//  APP — navigation, rendering, events
// ============================================================

let currentPage = 'overview';
let currentStock = '2330';
let currentDays = 30;
let newsFilter = 'all';

// ---------- Clock ----------
function updateClock() {
  const now = new Date();
  document.getElementById('time-display').textContent =
    now.toLocaleTimeString('zh-TW', { hour12: false });

  const h = now.getHours(), m = now.getMinutes();
  const badge = document.getElementById('market-badge');
  const isWeekday = now.getDay() >= 1 && now.getDay() <= 5;
  const isOpen = isWeekday && ((h > 9 || (h === 9 && m >= 0)) && h < 13 || (h === 13 && m === 30));
  if (isOpen) {
    badge.className = 'market-badge open';
    badge.innerHTML = '<span class="dot green"></span><span id="market-text">開市中</span>';
  } else {
    badge.className = 'market-badge closed';
    badge.innerHTML = '<span class="dot red"></span><span id="market-text">休市</span>';
  }
}

setInterval(updateClock, 1000);
updateClock();

// ---------- Navigation ----------
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', e => {
    e.preventDefault();
    const page = item.dataset.page;
    switchPage(page);
  });
});

function switchPage(page) {
  currentPage = page;

  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelector(`.nav-item[data-page="${page}"]`).classList.add('active');

  document.querySelectorAll('.page').forEach(p => p.classList.add('hidden'));
  document.getElementById('page-' + page).classList.remove('hidden');

  const titles = { overview: '市場總覽', stock: '個股分析', news: '新聞情緒', prediction: '趨勢預測' };
  document.getElementById('page-title').textContent = titles[page];

  if (page === 'overview')    renderOverview();
  if (page === 'stock')       renderStock(currentStock, currentDays);
  if (page === 'news')        renderNews();
  if (page === 'prediction')  renderPrediction();
}

// ---------- Overview ----------
function renderOverview() {
  renderWatchlist();
  initMarketTrendChart();
  initSentimentDonutChart();
}

function renderWatchlist() {
  const tbody = document.getElementById('watchlist-tbody');
  tbody.innerHTML = WATCHLIST.map(s => {
    const up = s.change_rate > 0;
    const dn = s.change_rate < 0;
    const cls = up ? 'up' : dn ? 'down' : '';
    const arrow = up ? '▲' : dn ? '▼' : '－';
    const sentBadge = sentimentBadge(s.sentiment);
    return `<tr>
      <td><strong>${s.stock_id}</strong></td>
      <td>${s.stock_name}</td>
      <td class="${cls}">${s.close_price.toFixed(2)}</td>
      <td class="${cls}">${arrow} ${Math.abs(s.change_value).toFixed(2)}</td>
      <td class="${cls}">${arrow} ${Math.abs(s.change_rate).toFixed(2)}%</td>
      <td>${s.volume.toLocaleString()}</td>
      <td class="${s.foreign_buy > 0 ? 'up' : 'down'}">${s.foreign_buy > 0 ? '+' : ''}${s.foreign_buy.toLocaleString()}</td>
      <td>${sentBadge}</td>
    </tr>`;
  }).join('');
}

function sentimentBadge(s) {
  const map = { bullish: ['利多','green'], neutral: ['中立','blue'], bearish: ['利空','red'] };
  const [label, color] = map[s] || ['中立','blue'];
  return `<span class="tag ${color}">${label}</span>`;
}

// ---------- Stock ----------
function renderStock(stockId, days) {
  currentStock = stockId;
  currentDays  = days;

  const info = STOCK_INFO[stockId] || STOCK_INFO['2330'];

  // Update quick-select buttons
  document.querySelectorAll('.btn-chip').forEach(b => {
    b.classList.toggle('active', b.dataset.stock === stockId);
  });
  document.getElementById('stock-input').value = stockId;

  // Info cards
  document.getElementById('chart-price-title').textContent = `${info.stock_id} ${info.stock_name} — 日K線`;
  const up = info.change_rate > 0, dn = info.change_rate < 0;
  const cls = up ? 'up' : dn ? 'down' : '';
  const arrow = up ? '▲' : dn ? '▼' : '－';

  document.getElementById('si-close').className    = `metric-value ${cls}`;
  document.getElementById('si-close').textContent  = info.close_price.toFixed(2);
  document.getElementById('si-change').className   = `metric-delta ${cls}`;
  document.getElementById('si-change').textContent = `${arrow} ${Math.abs(info.change_value).toFixed(2)} (${Math.abs(info.change_rate).toFixed(2)}%)`;

  document.getElementById('si-volume').textContent   = info.volume.toLocaleString();
  document.getElementById('si-turnover').textContent = `成交額 ${Math.round(info.turnover_value / 100)} 億`;

  const chipCls = info.total_net_buy > 0 ? 'up' : 'down';
  document.getElementById('si-chip').className   = `metric-value ${chipCls}`;
  document.getElementById('si-chip').textContent = `${info.total_net_buy > 0 ? '+' : ''}${info.total_net_buy.toLocaleString()} 張`;
  document.getElementById('si-foreign-ratio').textContent = `外資持股 ${info.foreign_holding_ratio}%`;

  document.getElementById('si-industry').textContent = info.industry_type;
  document.getElementById('si-market').textContent   = `${info.market_type} · TWSE`;

  initCandlestickChart(stockId, days);
  initChipChart(stockId);
}

// Period buttons
document.querySelectorAll('.btn-period').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.btn-period').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderStock(currentStock, parseInt(btn.dataset.days));
  });
});

// Quick select chips
document.querySelectorAll('.btn-chip').forEach(btn => {
  btn.addEventListener('click', () => renderStock(btn.dataset.stock, currentDays));
});

// Search button
document.getElementById('btn-load-stock').addEventListener('click', () => {
  const id = document.getElementById('stock-input').value.trim();
  if (STOCK_INFO[id]) {
    renderStock(id, currentDays);
  } else {
    alert(`找不到股票代碼 "${id}"，請輸入 2330 / 2317 / 2454 / 2412`);
  }
});

// ---------- News ----------
function renderNews() {
  initSentimentTimelineChart();
  initKeywordsChart();
  renderNewsFeed(newsFilter);
}

function renderNewsFeed(filter) {
  const feed = document.getElementById('news-feed');
  const filtered = filter === 'all' ? NEWS : NEWS.filter(n => n.sentiment === filter);
  if (!filtered.length) { feed.innerHTML = '<div style="padding:20px;color:#8b949e;text-align:center;">無符合條件的新聞</div>'; return; }

  feed.innerHTML = filtered.map(n => {
    const d = new Date(n.publish_at);
    const time = d.toLocaleString('zh-TW', { month:'numeric', day:'numeric', hour:'2-digit', minute:'2-digit' });
    const sc = n.sentiment_score;
    const scCls = sc >= 0.6 ? 'up' : sc <= 0.4 ? 'down' : 'muted';
    const tags = n.tags.map(t => `<span class="news-tag">${t}</span>`).join('');
    return `<div class="news-card">
      <div class="news-sentiment">
        <span class="sentiment-label ${n.sentiment}">${sentimentLabel(n.sentiment)}</span>
        <span class="sentiment-score ${scCls}">${sc.toFixed(2)}</span>
      </div>
      <div class="news-body">
        <div class="news-title">${n.raw_title}</div>
        <div class="news-meta">
          <span>${n.platform}</span>
          <span>${n.author}</span>
          <span>${time}</span>
          ${n.stock_tickers.length ? `<span>📌 ${n.stock_tickers.join(', ')}</span>` : ''}
        </div>
        <div class="news-tags">${tags}</div>
      </div>
    </div>`;
  }).join('');
}

function sentimentLabel(s) {
  return { bullish:'利多', neutral:'中立', bearish:'利空' }[s] || '中立';
}

document.querySelectorAll('.btn-filter').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.btn-filter').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    newsFilter = btn.dataset.filter;
    renderNewsFeed(newsFilter);
  });
});

// ---------- Prediction ----------
function renderPrediction() {
  initPredictionChart();
  renderForecastTable();
  initFeaturesChart();
}

function renderForecastTable() {
  const tbody = document.getElementById('forecast-tbody');
  tbody.innerHTML = FORECAST.map(row => {
    const up = row.change_value > 0;
    const cls = up ? 'up' : 'down';
    const arrow = up ? '▲' : '▼';
    const dir = up
      ? '<span class="tag green">上漲</span>'
      : '<span class="tag red">下跌</span>';
    return `<tr>
      <td>${row.date}</td>
      <td class="${cls}"><strong>${row.predicted_close.toFixed(2)}</strong></td>
      <td class="${cls}">${arrow} ${Math.abs(row.change_value).toFixed(2)}</td>
      <td class="${cls}">${arrow} ${Math.abs(row.change_rate).toFixed(2)}%</td>
      <td>${row.sentiment_weight.toFixed(3)}</td>
      <td class="muted">${row.ci_low.toFixed(2)} – ${row.ci_high.toFixed(2)}</td>
      <td>${dir}</td>
    </tr>`;
  }).join('');
}

// Retrain button
document.getElementById('btn-retrain').addEventListener('click', () => {
  const status = document.getElementById('retrain-status');
  status.classList.remove('hidden');
  setTimeout(() => {
    status.innerHTML = '<span class="dot green"></span><span>模型重訓完成！最新權重已儲存。</span>';
    setTimeout(() => status.classList.add('hidden'), 3000);
  }, 3500);
});

// Predict button
document.getElementById('btn-predict').addEventListener('click', () => {
  const stockId = document.getElementById('pred-stock').value;
  destroyChart('prediction');
  initPredictionChart();
  renderForecastTable();
});

// ---------- Init ----------
renderOverview();
