const API = "/api";
let performanceChart = null;
let allocationChart = null;
let valueChart = null;
let currentCategory = "stock";
let currentTimeframe = 365;
let currentValueTimeframe = 365;
let currentHoldings = [];
let currentWatchlist = [];
let holdingsSort = { key: null, dir: 1 };
let watchlistSort = { key: null, dir: 1 };
let fundamentalsCache = {};
let expandedHoldings = new Set();

const PERF_COLORS = ["#00ff66", "#ff6600", "#0088ff", "#ffcc00", "#ff3b3b", "#aa66ff", "#00ccff", "#ff00aa"];

function fundamentalsKey(row) {
  return `${row.symbol}::${row.category || row.asset_type}`;
}

function fmtNum(n, decimals = 2) {
  return typeof n === "number" ? n.toLocaleString("no-NO", { maximumFractionDigits: decimals }) : null;
}

function renderFundamentals(data) {
  if (!data || !data.available) {
    return `<div class="fundamentals-empty">${(data && data.note) || "No fundamentals available"}</div>`;
  }

  const stats = [];
  const addStat = (label, value) => {
    if (value === null || value === undefined || value === "") return;
    stats.push(`<div class="stat"><span class="stat-label">${label}</span><span class="stat-value">${value}</span></div>`);
  };

  if (data.pe_ratio !== undefined) {
    // Stock/fund fundamentals
    addStat("P/E", fmtNum(data.pe_ratio));
    addStat("Fwd P/E", fmtNum(data.forward_pe));
    addStat("EPS", fmtNum(data.eps));
    addStat("Div Yield", data.dividend_yield_pct != null ? `${fmtNum(data.dividend_yield_pct)}%` : null);
    addStat("Sector", data.sector);
    addStat("Category", data.industry);
    addStat("Analyst Target", fmtNum(data.analyst_target_mean));
    addStat("Analyst Rec", data.analyst_recommendation ? data.analyst_recommendation.replace(/_/g, " ") : null);
    addStat("52W High", fmtNum(data.week52_high));
    addStat("52W Low", fmtNum(data.week52_low));
  } else {
    // Crypto fundamentals
    addStat("Rank", data.market_cap_rank ? `#${data.market_cap_rank}` : null);
    addStat("Market Cap", data.market_cap ? `${fmtNum(data.market_cap, 0)} NOK` : null);
    addStat("Circ. Supply", fmtNum(data.circulating_supply, 0));
    addStat("ATH", data.ath ? `${fmtNum(data.ath)} NOK` : null);
    addStat("vs ATH", data.ath_change_pct != null ? `${fmtNum(data.ath_change_pct)}%` : null);
    addStat("24h", data.change_24h_pct != null ? `${fmtNum(data.change_24h_pct)}%` : null);
    addStat("7d", data.change_7d_pct != null ? `${fmtNum(data.change_7d_pct)}%` : null);
    addStat("30d", data.change_30d_pct != null ? `${fmtNum(data.change_30d_pct)}%` : null);
  }

  const headlines = data.headlines || [];
  const headlinesHtml = headlines.length
    ? `<div class="headlines"><span class="stat-label">Headlines</span>${headlines.map(h =>
        `<div class="headline">${h.url ? `<a href="${h.url}" target="_blank" rel="noopener">${h.title}</a>` : h.title}${h.publisher ? ` <span class="reason">— ${h.publisher}</span>` : ""}</div>`
      ).join("")}</div>`
    : "";

  const summary = data.summary ? data.summary.slice(0, 350) + (data.summary.length > 350 ? "…" : "") : "";
  const summaryHtml = summary ? `<div class="summary">${summary}</div>` : "";

  return `<div class="fundamentals-grid">${stats.join("")}</div>${headlinesHtml}${summaryHtml}`;
}

async function toggleFundamentals(tr, row) {
  const key = fundamentalsKey(row);

  if (expandedHoldings.has(key)) {
    expandedHoldings.delete(key);
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("detail-row")) next.remove();
    return;
  }

  expandedHoldings.add(key);
  const detailTr = document.createElement("tr");
  detailTr.className = "detail-row";
  detailTr.innerHTML = `<td colspan="10" class="detail-cell">loading…</td>`;
  tr.after(detailTr);

  let data = fundamentalsCache[key];
  if (!data) {
    const category = row.category || row.asset_type;
    const res = await fetch(`${API}/fundamentals/${encodeURIComponent(row.symbol)}?category=${category}`);
    data = await res.json();
    fundamentalsCache[key] = data;
  }
  const cell = detailTr.querySelector(".detail-cell");
  if (cell) cell.innerHTML = renderSignalsBreakdown(row) + renderFundamentals(data) + renderBacktestSection(row);
}

// After a re-render (e.g. the 60s dashboard poll), re-open any rows the user had
// expanded — using the client-side cache so this never triggers a new fetch.
function restoreExpandedFundamentals() {
  if (expandedHoldings.size === 0) return;
  document.querySelectorAll("#holdings-table tbody tr").forEach((tr) => {
    const cell = tr.querySelector(".expandable");
    if (!cell) return;
    const row = currentHoldings.find((h) => String(h.id) === cell.dataset.id);
    if (!row) return;
    const key = fundamentalsKey(row);
    if (!expandedHoldings.has(key)) return;

    const detailTr = document.createElement("tr");
    detailTr.className = "detail-row";
    const data = fundamentalsCache[key];
    const body = data ? renderSignalsBreakdown(row) + renderFundamentals(data) + renderBacktestSection(row) : "loading…";
    detailTr.innerHTML = `<td colspan="10" class="detail-cell">${body}</td>`;
    tr.after(detailTr);
  });
}

// Shows every individual indicator (RSI/MACD/MA-crossover/200-day trend), not just the
// combined confluence badge shown in the table — so it's clear *why* it fired.
function renderSignalsBreakdown(row) {
  const signals = (row.signals || []).filter((s) => s.signal !== "confluence");
  if (signals.length === 0) return "";
  const rows = signals.map((s) =>
    `<div class="signal-row">${badge(s.action)} <span class="signal-name">${s.signal}</span><span class="reason">${s.reason}</span></div>`
  ).join("");
  return `<div class="signals-breakdown"><span class="stat-label">Signals</span>${rows}</div>`;
}

function backtestContainerId(row) {
  return `backtest-${row.id}`;
}

// On-demand only — a full walk-forward backtest re-evaluates every signal once per
// historical day, too slow to run for every holding on every 60s poll.
function renderBacktestSection(row) {
  return `<div class="backtest-section">
    <button class="backtest-btn" data-id="${row.id}">Run backtest — confluence vs. buy &amp; hold</button>
    <div id="${backtestContainerId(row)}" class="backtest-result"></div>
  </div>`;
}

function renderBacktestResult(data) {
  if (!data.available) {
    return `<div class="fundamentals-empty">${data.note || "Backtest unavailable"}</div>`;
  }
  const stratClass = data.strategy_return_pct >= data.buy_hold_return_pct ? "gain-pos" : "gain-neg";
  const stats = [
    `<div class="stat"><span class="stat-label">Buy &amp; Hold</span><span class="stat-value">${fmtNum(data.buy_hold_return_pct)}%</span></div>`,
    `<div class="stat"><span class="stat-label">Confluence Strategy</span><span class="stat-value ${stratClass}">${fmtNum(data.strategy_return_pct)}%</span></div>`,
    `<div class="stat"><span class="stat-label">Trades</span><span class="stat-value">${data.trade_count}</span></div>`,
    `<div class="stat"><span class="stat-label">Win Rate</span><span class="stat-value">${data.win_rate_pct != null ? fmtNum(data.win_rate_pct) + "%" : "—"}</span></div>`,
  ].join("");
  const period = `<div class="reason">Backtested ${data.start_date} → ${data.end_date}, no fees/slippage modeled</div>`;
  const openPos = data.open_position
    ? `<div class="reason">Currently holding since ${data.open_position.entry_date} (${fmtNum(data.open_position.unrealized_return_pct)}% unrealized)</div>`
    : "";
  return `<div class="fundamentals-grid">${stats}</div>${period}${openPos}`;
}

async function runBacktest(btn, row) {
  btn.disabled = true;
  btn.textContent = "Running…";
  const container = document.getElementById(backtestContainerId(row));
  try {
    const category = row.category || row.asset_type;
    const res = await fetch(`${API}/backtest/${encodeURIComponent(row.symbol)}?category=${category}&days=365`);
    const data = await res.json();
    container.innerHTML = renderBacktestResult(data);
  } catch {
    container.innerHTML = `<div class="fundamentals-empty">Backtest failed — try again.</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Re-run backtest";
  }
}

function badge(action) {
  return `<span class="badge ${action}">${action.toUpperCase()}</span>`;
}

function topSignalOf(row) {
  const signals = row.signals || [];
  // Prefer the combined confluence verdict (see backend/signals/__init__.py) over any
  // single indicator — RSI/MACD/MA-crossover each fire on their own noise otherwise.
  return signals.find((s) => s.signal === "confluence")
    || signals.find((s) => s.action !== "hold")
    || signals[0];
}

const HOLDINGS_SORTERS = {
  symbol: (h) => h.symbol || "",
  category: (h) => h.category || h.asset_type || "",
  quantity: (h) => h.quantity ?? 0,
  avg_price: (h) => h.avg_price ?? 0,
  latest_price: (h) => (h.latest_price != null ? h.latest_price : -Infinity),
  value: (h) => (h.latest_price != null ? h.latest_price * h.quantity : -Infinity),
  gain: (h) => (h.latest_price != null ? (h.latest_price - h.avg_price) * h.quantity : -Infinity),
  signal: (h) => {
    const s = topSignalOf(h);
    return s ? ({ buy: 0, sell: 1, hold: 2 }[s.action] ?? 3) : 4;
  },
  reason: (h) => {
    const s = topSignalOf(h);
    return s ? s.reason : (h.note || "");
  },
};

const WATCHLIST_SORTERS = {
  symbol: (w) => w.symbol || "",
  asset_type: (w) => w.asset_type || "",
  latest_price: (w) => (w.latest_price != null ? w.latest_price : -Infinity),
  signal: (w) => {
    const s = topSignalOf(w);
    return s ? ({ buy: 0, sell: 1, hold: 2 }[s.action] ?? 3) : 4;
  },
  reason: (w) => {
    const s = topSignalOf(w);
    return s ? s.reason : (w.note || "");
  },
  note: (w) => w.note || "",
};

function sortRows(rows, sorters, state) {
  const getKey = sorters[state.key];
  if (!getKey) return rows;
  return [...rows].sort((a, b) => {
    const va = getKey(a), vb = getKey(b);
    if (typeof va === "string") return va.localeCompare(vb) * state.dir;
    return (va - vb) * state.dir;
  });
}

function sortHoldings() {
  currentHoldings = sortRows(currentHoldings, HOLDINGS_SORTERS, holdingsSort);
}

function sortWatchlist() {
  currentWatchlist = sortRows(currentWatchlist, WATCHLIST_SORTERS, watchlistSort);
}

// Click a column header to sort by it; click again to reverse.
function attachSortHandlers(tableId, state, onSort) {
  document.querySelectorAll(`#${tableId} th[data-sort]`).forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      state.dir = state.key === key ? state.dir * -1 : 1;
      state.key = key;
      document.querySelectorAll(`#${tableId} th[data-sort]`).forEach((t) => t.classList.remove("sort-asc", "sort-dsc"));
      th.classList.add(state.dir === 1 ? "sort-asc" : "sort-dsc");
      onSort();
    });
  });
}

function renderTable(tableId, rows, isHolding) {
  const tbody = document.querySelector(`#${tableId} tbody`);
  tbody.innerHTML = "";

  for (const row of rows) {
    const tr = document.createElement("tr");

    if (row.error) {
      const span = isHolding ? 8 : 5;
      tr.innerHTML = `<td>${row.symbol}</td><td>${row.category || row.asset_type}</td><td colspan="${span}" class="error">${row.error}</td>`;
      tbody.appendChild(tr);
      continue;
    }

    const topSignal = topSignalOf(row);
    const price = row.latest_price != null ? row.latest_price.toFixed(2) : "-";
    const reason = topSignal ? topSignal.reason : (row.note || "");
    const sig = topSignal ? badge(topSignal.action) : "-";

    if (isHolding) {
      const value = row.latest_price != null ? row.latest_price * row.quantity : null;
      const gain = row.latest_price != null ? (row.latest_price - row.avg_price) * row.quantity : null;
      const gainClass = gain == null ? "" : gain >= 0 ? "gain-pos" : "gain-neg";
      tr.innerHTML = `<td class="expandable" data-id="${row.id}" title="click for P/E, headlines, more">${row.symbol}</td><td>${row.category || row.asset_type}</td><td>${row.quantity}</td>
        <td>${row.avg_price}</td><td class="price">${price}</td>
        <td class="price">${value != null ? value.toLocaleString("no-NO", { maximumFractionDigits: 0 }) : "-"}</td>
        <td class="${gainClass}">${gain != null ? gain.toLocaleString("no-NO", { maximumFractionDigits: 0, signDisplay: "always" }) : "-"}</td>
        <td>${sig}</td>
        <td class="reason">${reason}</td><td><button data-id="${row.id}" data-kind="holdings">x</button></td>`;
    } else {
      tr.innerHTML = `<td>${row.symbol}</td><td>${row.asset_type}</td><td class="price">${price}</td>
        <td>${sig}</td><td class="reason">${reason}</td><td>${row.note || ""}</td>
        <td><button data-id="${row.id}" data-kind="watchlist">x</button></td>`;
    }
    tbody.appendChild(tr);
  }
}

async function loadAllocation() {
  const res = await fetch(`${API}/allocation`);
  const data = await res.json();

  // Update stats — this reflects the tradeable portfolio only (stock/fund/crypto);
  // real estate is shown in its own panel and rolled into Net Worth instead.
  const statsHtml = `<div><strong>Portfolio Value:</strong> ${data.total_value_nok.toLocaleString('no-NO', { maximumFractionDigits: 0 })} NOK</div>`;
  const categoryStats = Object.entries(data.by_category)
    .map(([cat, info]) => `<div><strong>${cat.replace("_", " ").toUpperCase()}:</strong> ${info.value.toLocaleString('no-NO', { maximumFractionDigits: 0 })} NOK (${info.percent.toFixed(1)}%) - ${info.count} assets</div>`)
    .join("");

  document.getElementById("allocation-stats").innerHTML = statsHtml + categoryStats;

  // Real estate panel: no charts here, just the numbers — real estate value,
  // the rest of the portfolio, how net worth splits between the two, the total,
  // and the predicted appreciation.
  const reStats = document.getElementById("real-estate-stats");
  if (data.real_estate && data.real_estate.count > 0) {
    const growth = data.real_estate.est_annual_growth_pct != null
      ? `${data.real_estate.est_annual_growth_pct >= 0 ? "+" : ""}${data.real_estate.est_annual_growth_pct.toFixed(1)}%/yr`
      : "-";
    const nok = (v) => v.toLocaleString('no-NO', { maximumFractionDigits: 0 });
    const rePct = data.net_worth_nok > 0 ? (data.real_estate.value / data.net_worth_nok * 100) : 0;
    reStats.innerHTML = `
      <div><strong>Real Estate:</strong> ${nok(data.real_estate.value)} NOK</div>
      <div><strong>Rest of Portfolio:</strong> ${nok(data.total_value_nok)} NOK</div>
      <div><strong>Split:</strong> ${rePct.toFixed(1)}% / ${(100 - rePct).toFixed(1)}%</div>
      <div><strong>Total Net Worth:</strong> ${nok(data.net_worth_nok)} NOK</div>
      <div><strong>Predicted Increase:</strong> ${growth}</div>
    `;
  } else {
    reStats.innerHTML = `<div class="reason">No real estate added yet — add one from the holdings form as "real estate".</div>`;
  }

  // Update chart
  const categories = Object.keys(data.by_category);
  const values = categories.map(cat => data.by_category[cat].value);
  const colors = { stock: "#00ff00", fund: "#0088ff", crypto: "#ff6600" };

  const ctx = document.getElementById("allocation-chart");
  if (allocationChart) allocationChart.destroy();

  allocationChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: categories.map(c => c.replace("_", " ").toUpperCase()),
      datasets: [{
        data: values,
        backgroundColor: categories.map(c => colors[c] || "#ff00ff"),
        borderColor: "#000",
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: "#00ff00", font: { family: "'Courier New'" } } },
      },
    },
  });
}

function renderRecommendation(data) {
  if (!data.pick) {
    return `<div class="fundamentals-empty">No scoreable candidates — your holdings/watchlist may be missing price data.</div>`;
  }

  const p = data.pick;
  const stats = [
    `<div class="stat"><span class="stat-label">Current Price</span><span class="stat-value">${fmtNum(p.current_price)} NOK</span></div>`,
  ];
  if (p.analyst_upside_pct != null) {
    stats.push(`<div class="stat"><span class="stat-label">Analyst Upside</span><span class="stat-value">${fmtNum(p.analyst_upside_pct)}%</span></div>`);
  }
  if (p.confluence_action) {
    stats.push(`<div class="stat"><span class="stat-label">Signal</span><span class="stat-value">${badge(p.confluence_action)}</span></div>`);
  }

  const reasons = p.reasons.map((r) => `<div class="reason">• ${r}</div>`).join("");
  const runnersUp = data.ranked.slice(1, 4)
    .map((r) => `<div class="reason">${r.symbol} (${r.category}) — score ${fmtNum(r.score)}</div>`)
    .join("");

  return `<div class="recommend-pick">
    <div class="recommend-symbol">${p.symbol} <span class="reason">(${p.category})</span></div>
    <div class="fundamentals-grid">${stats.join("")}</div>
    <div class="signals-breakdown">${reasons}</div>
    ${runnersUp ? `<div class="signals-breakdown"><span class="stat-label">Runners-up</span>${runnersUp}</div>` : ""}
    <div class="reason" style="margin-top: 10px;">${data.disclaimer}</div>
  </div>`;
}

async function loadRecommendation() {
  const btn = document.getElementById("recommend-btn");
  const result = document.getElementById("recommend-result");
  btn.disabled = true;
  btn.textContent = "Scoring your holdings + watchlist…";
  try {
    const res = await fetch(`${API}/recommend`);
    const data = await res.json();
    result.innerHTML = renderRecommendation(data);
  } catch {
    result.innerHTML = `<div class="fundamentals-empty">Couldn't compute a recommendation — try again.</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Re-run";
  }
}

document.getElementById("recommend-btn").addEventListener("click", loadRecommendation);

async function loadPortfolioValue() {
  const res = await fetch(`${API}/portfolio-history?days=${currentValueTimeframe}`);
  const data = await res.json();

  const container = document.getElementById("value-chart").parentElement;
  const empty = document.getElementById("value-empty");

  if (!data.points || data.points.length < 2) {
    if (valueChart) { valueChart.destroy(); valueChart = null; }
    container.style.display = "none";
    empty.style.display = "block";
    return;
  }
  container.style.display = "block";
  empty.style.display = "none";

  const ctx = document.getElementById("value-chart");
  if (valueChart) valueChart.destroy();

  valueChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.points.map(p => p.date),
      datasets: [{
        label: "Total value",
        data: data.points.map(p => p.total_value_nok),
        borderColor: "#00ff66",
        backgroundColor: "rgba(0, 255, 102, 0.1)",
        tension: 0.1,
        fill: true,
        pointRadius: 0,
      }],
    },
    options: {
      responsive: true,
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (c) => `${c.raw.toLocaleString("no-NO", { maximumFractionDigits: 0 })} NOK`,
          },
        },
      },
      scales: {
        x: { ticks: { color: "#00ff00", maxTicksLimit: 10 } },
        y: { ticks: { color: "#00ff00", callback: (v) => `${(v / 1000).toLocaleString("no-NO")}k` } },
      },
    },
  });
}

async function loadPerformance() {
  const res = await fetch(`${API}/performance?category=${currentCategory}&days=${currentTimeframe}`);
  const data = await res.json();

  const container = document.getElementById("performance-chart").parentElement;
  const empty = document.getElementById("performance-empty");

  if (!data.series || data.series.length === 0) {
    if (performanceChart) { performanceChart.destroy(); performanceChart = null; }
    container.style.display = "none";
    empty.style.display = "block";
    return;
  }
  container.style.display = "block";
  empty.style.display = "none";

  const currency = data.currency || "NOK";
  const note = document.getElementById("performance-currency-note");
  note.textContent = currentCategory === "crypto"
    ? `Prices shown in ${currency} (hover a point for the USD equivalent too)`
    : `Prices shown in ${currency}`;

  // Series may start on slightly different dates (holiday/market gaps); build one
  // shared date axis and let spanGaps fill the holes so lines stay comparable.
  const allDates = [...new Set(data.series.flatMap(s => s.points.map(p => p.date)))].sort();

  const datasets = data.series.map((s, i) => {
    const byDate = Object.fromEntries(s.points.map(p => [p.date, p]));
    const color = PERF_COLORS[i % PERF_COLORS.length];
    return {
      label: s.symbol,
      data: allDates.map(d => (d in byDate ? byDate[d].change_pct : null)),
      priceNok: allDates.map(d => (d in byDate ? byDate[d].price_nok : null)),
      priceUsd: allDates.map(d => (d in byDate ? byDate[d].price_usd : null)),
      borderColor: color,
      backgroundColor: color,
      spanGaps: true,
      tension: 0.1,
      pointRadius: 0,
    };
  });

  const ctx = document.getElementById("performance-chart");
  if (performanceChart) performanceChart.destroy();

  performanceChart = new Chart(ctx, {
    type: "line",
    data: { labels: allDates, datasets },
    options: {
      responsive: true,
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { labels: { color: "#00ff00", font: { family: "'Courier New'" } } },
        tooltip: {
          callbacks: {
            label: (c) => {
              const nok = c.dataset.priceNok?.[c.dataIndex];
              const usd = c.dataset.priceUsd?.[c.dataIndex];
              let price = nok != null ? ` — ${nok.toLocaleString("no-NO", { maximumFractionDigits: 0 })} NOK` : "";
              if (usd != null) price += ` (≈ $${usd.toLocaleString("en-US", { maximumFractionDigits: 0 })})`;
              return `${c.dataset.label}: ${c.formattedValue}%${price}`;
            },
          },
        },
      },
      scales: {
        x: { ticks: { color: "#00ff00", maxTicksLimit: 10 } },
        y: { ticks: { color: "#00ff00", callback: (v) => `${v}%` } },
      },
    },
  });
}

async function loadDashboard() {
  const res = await fetch(`${API}/dashboard`);
  const data = await res.json();
  currentHoldings = data.holdings;
  currentWatchlist = data.watchlist;
  sortHoldings();
  sortWatchlist();
  renderTable("holdings-table", currentHoldings, true);
  renderTable("watchlist-table", currentWatchlist, false);
  restoreExpandedFundamentals();
  loadAllocation();
}

// Event listeners for timeframe buttons
document.querySelectorAll(".timeframe-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".timeframe-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentTimeframe = parseInt(btn.dataset.timeframe);
    loadPerformance();
  });
});

document.querySelectorAll(".value-timeframe-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".value-timeframe-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentValueTimeframe = parseInt(btn.dataset.timeframe);
    loadPortfolioValue();
  });
});

// Event listeners for category tabs (stocks / funds / crypto performance)
document.querySelectorAll(".category-tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".category-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentCategory = btn.dataset.category;
    loadPerformance();
  });
});

attachSortHandlers("holdings-table", holdingsSort, () => {
  sortHoldings();
  renderTable("holdings-table", currentHoldings, true);
  restoreExpandedFundamentals();
});

attachSortHandlers("watchlist-table", watchlistSort, () => {
  sortWatchlist();
  renderTable("watchlist-table", currentWatchlist, false);
});

document.addEventListener("click", async (e) => {
  if (e.target.tagName === "BUTTON" && e.target.dataset.id) {
    const { id, kind } = e.target.dataset;
    await fetch(`${API}/${kind}/${id}`, { method: "DELETE" });
    loadDashboard();
    return;
  }

  const backtestBtn = e.target.closest(".backtest-btn");
  if (backtestBtn) {
    const row = currentHoldings.find((h) => String(h.id) === backtestBtn.dataset.id);
    if (row) runBacktest(backtestBtn, row);
    return;
  }

  const expandable = e.target.closest(".expandable");
  if (expandable) {
    const tr = expandable.closest("tr");
    const row = currentHoldings.find((h) => String(h.id) === expandable.dataset.id);
    if (row) toggleFundamentals(tr, row);
  }
});

document.getElementById("holding-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  await fetch(`${API}/holdings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: form.get("symbol"),
      asset_type: form.get("asset_type"),
      quantity: parseFloat(form.get("quantity")),
      avg_price: parseFloat(form.get("avg_price")),
      annual_growth_pct: form.get("annual_growth_pct") ? parseFloat(form.get("annual_growth_pct")) : null,
    }),
  });
  e.target.reset();
  loadDashboard();
});

document.getElementById("watchlist-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  await fetch(`${API}/watchlist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: form.get("symbol"),
      asset_type: form.get("asset_type"),
      note: form.get("note") || "",
    }),
  });
  e.target.reset();
  loadDashboard();
});

loadDashboard();
loadPerformance();
loadPortfolioValue();
loadRecommendation();
setInterval(loadDashboard, 60000);
setInterval(loadPerformance, 60000);
setInterval(loadPortfolioValue, 60000);
