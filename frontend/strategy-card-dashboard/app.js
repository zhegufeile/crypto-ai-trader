const state = {
  account: null,
  cards: [],
  leaderboard: [],
  diagnostics: [],
  positions: [],
  journal: [],
  activeView: "overview",
  diagnosticMode: "core+candidate",
  strategyTier: "all",
  strategyPage: 1,
  strategyPageSize: 6,
  selectedStrategyName: null,
  isRefreshing: false,
};

const DASHBOARD_REFRESH_MS = 15000;
let refreshTimer = null;
let refreshCountdownTimer = null;
let nextRefreshAt = null;

const els = {
  runtimeStatus: document.getElementById("runtime-status"),
  runtimeMode: document.getElementById("runtime-mode"),
  runtimeUpdated: document.getElementById("runtime-updated"),
  runtimeRefresh: document.getElementById("runtime-refresh"),
  heroEquity: document.getElementById("hero-equity"),
  heroAvailable: document.getElementById("hero-available"),
  heroPnl24h: document.getElementById("hero-pnl-24h"),
  heroOpenPending: document.getElementById("hero-open-pending"),
  heroWinRate: document.getElementById("hero-win-rate"),
  heroFees: document.getElementById("hero-fees"),
  overviewCapitalInUse: document.getElementById("overview-capital-in-use"),
  overviewRealized: document.getElementById("overview-realized"),
  overviewUnrealized: document.getElementById("overview-unrealized"),
  overviewClosed: document.getElementById("overview-closed"),
  overviewCardCount: document.getElementById("overview-card-count"),
  overviewLeaderboard: document.getElementById("overview-leaderboard"),
  overviewJournal: document.getElementById("overview-journal"),
  equityChart: document.getElementById("equity-chart"),
  equityLog: document.getElementById("equity-log"),
  positions: document.getElementById("positions"),
  diagnostics: document.getElementById("diagnostics"),
  journal: document.getElementById("journal"),
  cards: document.getElementById("cards"),
  strategyPagination: document.getElementById("strategy-pagination"),
  strategyDetailName: document.getElementById("strategy-detail-name"),
  strategyDetailTier: document.getElementById("strategy-detail-tier"),
  strategyDetailBody: document.getElementById("strategy-detail-body"),
  search: document.getElementById("search"),
  sort: document.getElementById("sort"),
  diagModeCoreCandidate: document.getElementById("diag-mode-core-candidate"),
  diagModeCoreOnly: document.getElementById("diag-mode-core-only"),
  diagModeAll: document.getElementById("diag-mode-all"),
  posActive: document.getElementById("pos-active"),
  posPending: document.getElementById("pos-pending"),
  posRealized: document.getElementById("pos-realized"),
  posUnrealized: document.getElementById("pos-unrealized"),
  diagTradeable: document.getElementById("diag-tradeable"),
  diagBlocked: document.getElementById("diag-blocked"),
  diagOnchain: document.getElementById("diag-onchain"),
  diagHoneypot: document.getElementById("diag-honeypot"),
  journalCount: document.getElementById("journal-count"),
  journalWarnings: document.getElementById("journal-warnings"),
  journalClosed: document.getElementById("journal-closed"),
  journalCircuits: document.getElementById("journal-circuits"),
  tabButtons: Array.from(document.querySelectorAll(".tab-button")),
  views: Array.from(document.querySelectorAll(".view")),
  tierButtons: Array.from(document.querySelectorAll(".subtab-button")),
};

function fmtNum(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return Number(0).toFixed(digits);
  return Number(value).toFixed(digits);
}

function fmtPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "0%";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function fmtTime(value) {
  if (!value) return "-";
  return String(value).slice(0, 19).replace("T", " ");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pnlClass(value) {
  if (Number(value) > 0) return "pnl-positive";
  if (Number(value) < 0) return "pnl-negative";
  return "pnl-flat";
}

function badgeClassByTier(tier) {
  if (tier === "core") return "good";
  if (tier === "candidate") return "warn";
  return "bad";
}

function badgeClassByTradeable(item) {
  if (item.tradeable) return "good";
  if (item.snapshot?.onchain_honeypot) return "bad";
  return "warn";
}

function scoreCard(card) {
  const win = card.historical_win_rate || 0;
  const rr = card.historical_rr || 0;
  const sample = card.sample_size || 0;
  const tp2 = card.tp2_hit_rate || 0;
  const drawdownPenalty = Math.abs(Math.min(card.max_drawdown_rr || 0, 0));
  return win * 100 + rr * 12 + tp2 * 20 + Math.min(sample, 50) * 0.8 - drawdownPenalty * 4;
}

async function fetchJson(path) {
  const separator = path.includes("?") ? "&" : "?";
  const cacheBustPath = `${path}${separator}_ts=${Date.now()}`;
  const response = await fetch(cacheBustPath, {
    cache: "no-store",
    headers: {
      "Cache-Control": "no-cache, no-store, max-age=0",
      Pragma: "no-cache",
    },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${path}`);
  return response.json();
}

async function loadAccount() {
  state.account = await fetchJson("/account/summary");
  renderAccount();
}

async function loadCards() {
  state.cards = await fetchJson("/strategy-cards");
  state.leaderboard = await fetchJson("/strategy-cards/leaderboard?limit=8");
  if (!state.selectedStrategyName && state.cards.length) {
    state.selectedStrategyName = state.cards[0].name;
  }
  renderStrategies();
  renderOverview();
}

async function loadDiagnostics() {
  state.diagnostics = await fetchJson(`/diagnostics/candidates?limit=10&tier_mode=${encodeURIComponent(state.diagnosticMode)}`);
  renderDiagnosticStats(state.diagnostics);
  renderDiagnostics(state.diagnostics);
}

async function loadPositions() {
  state.positions = await fetchJson("/positions?include_closed=true");
  renderPositionStats(state.positions);
  renderPositions(state.positions);
}

async function loadJournal() {
  state.journal = await fetchJson("/positions/journal?limit=50");
  renderJournalStats(state.journal);
  renderJournal(state.journal);
  renderOverview();
}

function renderAccount() {
  const account = state.account || {};
  els.runtimeStatus.textContent = "Simulation runtime online";
  els.runtimeMode.textContent = `Mode ${account.mode || "simulation"}`;
  els.runtimeUpdated.textContent = `Updated ${fmtTime(account.updated_at)}`;
  els.heroEquity.textContent = fmtNum(account.equity_usdt);
  els.heroEquity.className = pnlClass(account.total_pnl_usdt);
  els.heroAvailable.textContent = fmtNum(account.available_balance_usdt);
  els.heroPnl24h.textContent = fmtNum(account.realized_pnl_24h_usdt);
  els.heroPnl24h.className = pnlClass(account.realized_pnl_24h_usdt);
  els.heroOpenPending.textContent = `${account.open_positions || 0} / ${account.pending_positions || 0}`;
  els.heroWinRate.textContent = fmtPct(account.win_rate || 0);
  els.heroFees.textContent = `${fmtNum(account.fees_24h_usdt)} / ${fmtNum(account.total_fees_usdt)}`;
  els.overviewCapitalInUse.textContent = fmtNum(account.capital_in_use_usdt);
  els.overviewRealized.textContent = fmtNum(account.realized_pnl_usdt);
  els.overviewRealized.className = pnlClass(account.realized_pnl_usdt);
  els.overviewUnrealized.textContent = fmtNum(account.unrealized_pnl_usdt);
  els.overviewUnrealized.className = pnlClass(account.unrealized_pnl_usdt);
  els.overviewClosed.textContent = String(account.closed_trades || 0);
  renderEquityChart(account.equity_curve || []);
}

function renderEquityChart(points) {
  if (!points.length) {
    els.equityChart.innerHTML = '<div class="empty">No equity data yet.</div>';
    return;
  }
  const values = points.map((point) => Number(point.equity || 0));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(max - min, 1);
  const width = 760;
  const height = 240;
  const path = points.map((point, index) => {
    const x = (index / Math.max(points.length - 1, 1)) * width;
    const y = height - ((Number(point.equity || 0) - min) / spread) * height;
    return `${x},${y}`;
  }).join(" ");
  const latest = points[points.length - 1];

  els.equityChart.innerHTML = `
    <div>
      <div class="chart-canvas">
        <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
          <defs>
            <linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stop-color="rgba(121,168,255,0.38)"></stop>
              <stop offset="100%" stop-color="rgba(121,168,255,0.02)"></stop>
            </linearGradient>
          </defs>
          <polyline fill="none" stroke="#7cf2d2" stroke-width="3" points="${path}"></polyline>
          <polygon fill="url(#equityFill)" points="0,${height} ${path} ${width},${height}"></polygon>
        </svg>
      </div>
      <div class="chart-caption">Latest equity ${fmtNum(latest.equity)} at ${fmtTime(latest.time)}</div>
    </div>
  `;
}

function renderOverview() {
  els.overviewCardCount.textContent = String(state.cards.length);
  const attribution = (state.account?.strategy_attribution || []);
  els.overviewLeaderboard.innerHTML = attribution.length
    ? attribution.slice(0, 4).map((item, index) => `
        <div class="mini-item">
          <strong>#${index + 1} ${escapeHtml(item.strategy_name)}</strong>
          <span>PnL ${fmtNum(item.total_pnl_usdt)} | win ${fmtPct(item.win_rate || 0)} | closed ${item.closed_trades || 0}</span>
        </div>
      `).join("")
    : '<div class="empty">No strategy attribution yet.</div>';

  els.overviewJournal.innerHTML = state.journal.length
    ? state.journal.slice(0, 4).map((item) => `
        <div class="mini-item">
          <strong>${escapeHtml(item.event_type)}</strong>
          <span>${escapeHtml(item.symbol)} | ${fmtTime(item.created_at)}</span>
        </div>
      `).join("")
    : '<div class="empty">No journal data yet.</div>';

  els.equityLog.innerHTML = state.journal.length
    ? state.journal.slice(0, 20).map((item) => `
        <div class="equity-log-item">
          <strong>${escapeHtml(item.event_type)} · ${escapeHtml(item.symbol)}</strong>
          <span>${fmtTime(item.created_at)} | ${escapeHtml(item.message || "No message")}</span>
        </div>
      `).join("")
    : '<div class="empty">No runtime log yet.</div>';
}

function getFilteredStrategyCards() {
  const query = els.search.value.trim().toLowerCase();
  const sortKey = els.sort.value;
  const filtered = state.cards.filter((card) => {
    if (state.strategyTier !== "all" && card.strategy_tier !== state.strategyTier) return false;
    if (!query) return true;
    const blob = [
      card.name,
      card.description,
      card.market,
      card.timeframe,
      card.creator,
      ...(card.tags || []),
      ...(card.preferred_symbols || []),
      ...(card.entry_conditions || []),
    ].join(" ").toLowerCase();
    return blob.includes(query);
  });

  filtered.sort((a, b) => {
    if (sortKey === "win_rate") return (b.historical_win_rate || 0) - (a.historical_win_rate || 0);
    if (sortKey === "sample_size") return (b.sample_size || 0) - (a.sample_size || 0);
    if (sortKey === "rr") return (b.historical_rr || 0) - (a.historical_rr || 0);
    return scoreCard(b) - scoreCard(a);
  });
  return filtered;
}

function renderStrategies() {
  const filtered = getFilteredStrategyCards();
  const totalPages = Math.max(Math.ceil(filtered.length / state.strategyPageSize), 1);
  state.strategyPage = Math.min(state.strategyPage, totalPages);
  const start = (state.strategyPage - 1) * state.strategyPageSize;
  const pageCards = filtered.slice(start, start + state.strategyPageSize);

  els.strategyPagination.innerHTML = Array.from({ length: totalPages }, (_, index) => `
    <button class="page-button ${state.strategyPage === index + 1 ? "active" : ""}" data-page="${index + 1}" type="button">Page ${index + 1}</button>
  `).join("");
  Array.from(els.strategyPagination.querySelectorAll(".page-button")).forEach((button) => {
    button.addEventListener("click", () => {
      state.strategyPage = Number(button.dataset.page);
      renderStrategies();
    });
  });

  if (!pageCards.length) {
    els.cards.innerHTML = '<div class="empty">No strategy cards match this filter.</div>';
  } else {
    els.cards.innerHTML = pageCards.map((card) => {
      const selected = state.selectedStrategyName === card.name;
      const chips = [card.market, card.timeframe, card.creator, ...(card.tags || []).slice(0, 2)]
        .filter(Boolean)
        .map((item) => `<span class="badge">${escapeHtml(item)}</span>`)
        .join("");
      return `
        <article class="card card-clickable ${selected ? "card-selected" : ""}" data-card-name="${escapeHtml(card.name)}">
          <div class="card-top">
            <div>
              <p class="name">${escapeHtml(card.name)}</p>
              <div class="meta">${escapeHtml(card.description || "No description")}</div>
            </div>
            <span class="badge ${badgeClassByTier(card.strategy_tier)}">${escapeHtml(card.strategy_tier)}</span>
          </div>
          <div class="badge-row">${chips}</div>
          <div class="metrics">
            <div class="metric">
              <span class="metric-label">Win Rate</span>
              <span class="metric-value">${fmtPct(card.historical_win_rate || 0)}</span>
            </div>
            <div class="metric">
              <span class="metric-label">Average RR</span>
              <span class="metric-value">${fmtNum(card.historical_rr || 0)}</span>
            </div>
            <div class="metric">
              <span class="metric-label">Samples</span>
              <span class="metric-value">${card.sample_size || 0}</span>
            </div>
          </div>
          <div class="progress"><span style="width:${Math.min(100, Math.max(0, (card.historical_win_rate || 0) * 100))}%"></span></div>
        </article>
      `;
    }).join("");
    Array.from(els.cards.querySelectorAll("[data-card-name]")).forEach((node) => {
      node.addEventListener("click", () => {
        state.selectedStrategyName = node.dataset.cardName;
        renderStrategies();
      });
    });
  }

  const selected = state.cards.find((item) => item.name === state.selectedStrategyName) || filtered[0];
  if (selected) {
    state.selectedStrategyName = selected.name;
    renderStrategyDetail(selected);
  }
}

function renderStrategyDetail(card) {
  els.strategyDetailName.textContent = card.name;
  els.strategyDetailTier.textContent = card.strategy_tier || "watchlist";
  els.strategyDetailTier.className = `badge ${badgeClassByTier(card.strategy_tier)}`;
  els.strategyDetailBody.innerHTML = `
    <div class="detail-block">
      <strong>Description</strong>
      <div>${escapeHtml(card.description || "No description")}</div>
    </div>
    <div class="detail-block">
      <strong>Execution Metrics</strong>
      <div>Win rate ${fmtPct(card.historical_win_rate || 0)} | Average RR ${fmtNum(card.historical_rr || 0)} | Samples ${card.sample_size || 0}</div>
      <div>Avg hold ${fmtNum(card.avg_hold_hours || 0)} h | TP1 ${fmtPct(card.tp1_hit_rate || 0)} | TP2 ${fmtPct(card.tp2_hit_rate || 0)}</div>
    </div>
    <div class="detail-block">
      <strong>Preferred Symbols</strong>
      <div>${escapeHtml((card.preferred_symbols || []).join(", ") || "None")}</div>
    </div>
    <div class="detail-block">
      <strong>Entry Conditions</strong>
      <div>${escapeHtml((card.entry_conditions || []).join(" | ") || "manual review")}</div>
    </div>
    <div class="detail-block">
      <strong>Tier Rationale</strong>
      <div>${escapeHtml((card.tier_rationale || []).join(" | ") || "No rationale yet")}</div>
    </div>
    <div class="detail-block">
      <strong>Risk Notes</strong>
      <div>${escapeHtml((card.risk_notes || []).join(" | ") || "None")}</div>
    </div>
  `;
}

function renderDiagnosticStats(items) {
  const tradeable = items.filter((item) => item.tradeable).length;
  const blocked = items.length - tradeable;
  const avgOnchain = items.length
    ? items.reduce((sum, item) => sum + (item.snapshot?.onchain_signal_score || 0), 0) / items.length
    : 0;
  const honeypot = items.filter((item) => item.snapshot?.onchain_honeypot).length;
  els.diagTradeable.textContent = String(tradeable);
  els.diagBlocked.textContent = String(blocked);
  els.diagOnchain.textContent = fmtNum(avgOnchain);
  els.diagHoneypot.textContent = String(honeypot);
}

function renderDiagnostics(items) {
  if (!items.length) {
    els.diagnostics.innerHTML = '<div class="empty">No diagnostics yet.</div>';
    return;
  }
  els.diagnostics.innerHTML = items.map((item) => {
    const snapshot = item.snapshot || {};
    const signal = item.signal;
    const risk = item.risk || {};
    const strategyMatches = (item.strategy_matches || []).slice(0, 3).map((match) => `
      <li>
        <strong>${escapeHtml(match.name)}</strong>
        <span class="badge ${badgeClassByTier(match.tier)}">${escapeHtml(match.tier)}</span><br>
        Bonus ${fmtNum(match.applied_bonus)} | Weight x${fmtNum(match.weight_multiplier)} | Tier score ${fmtNum(match.tier_score)}
      </li>
    `).join("");
    return `
      <article class="card">
        <div class="card-top">
          <div>
            <p class="name">${escapeHtml(item.symbol)}</p>
            <div class="meta">Structure ${escapeHtml(item.analysis?.structure || "unknown")} | Direction ${escapeHtml(item.analysis?.direction || "neutral")} | Score ${fmtNum(item.hard_score)}</div>
          </div>
          <span class="badge ${badgeClassByTradeable(item)}">${item.tradeable ? "Tradeable" : (snapshot.onchain_honeypot ? "Blocked" : "Rejected")}</span>
        </div>
        <div class="diagnostic-grid">
          <div class="diagnostic-box">
            <strong>Structure</strong>
            Regime ${escapeHtml(snapshot.market_regime || "unknown")}<br>
            RS ${fmtNum(snapshot.relative_strength_score || 0)}<br>
            Retest ${fmtNum(snapshot.retest_quality_score || 0)}<br>
            Follow-through ${fmtNum(snapshot.follow_through_score || 0)}
          </div>
          <div class="diagnostic-box">
            <strong>Onchain</strong>
            Signal ${fmtNum(snapshot.onchain_signal_score || 0)}<br>
            Wallets ${snapshot.onchain_wallet_count || 0}<br>
            Buy ${fmtNum(snapshot.onchain_buy_amount_usd || 0)} USD<br>
            Sold ${snapshot.onchain_sold_ratio_percent == null ? "-" : `${fmtNum(snapshot.onchain_sold_ratio_percent)}%`}
          </div>
          <div class="diagnostic-box">
            <strong>Security</strong>
            Level ${escapeHtml(snapshot.onchain_risk_level || "unknown")}<br>
            Honeypot ${snapshot.onchain_honeypot ? "Yes" : "No"}<br>
            Safe buy ${snapshot.onchain_is_safe_buy === false ? "No" : snapshot.onchain_is_safe_buy === true ? "Yes" : "-"}<br>
            Liquidity ${snapshot.onchain_liquidity_usd == null ? "-" : `${fmtNum(snapshot.onchain_liquidity_usd)} USD`}
          </div>
          <div class="diagnostic-box">
            <strong>Trade Plan</strong>
            ${signal ? `Entry ${fmtNum(signal.entry, 4)} | Stop ${fmtNum(signal.stop_loss, 4)} | TP ${fmtNum(signal.take_profit, 4)}` : "No executable signal now"}
          </div>
        </div>
        <div class="diagnostic-box">
          <strong>Strategy Weighting (${escapeHtml(item.strategy_tier_mode || state.diagnosticMode)})</strong>
          ${strategyMatches ? `<ul class="reason-list">${strategyMatches}</ul>` : "No matched cards under this mode."}
        </div>
        <ul class="reason-list">${(risk.reasons || item.reasons || []).slice(0, 4).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("") || "<li>No reasons recorded.</li>"}</ul>
      </article>
    `;
  }).join("");
}

function renderPositionStats(items) {
  const active = items.filter((item) => ["pending_entry", "open", "partial"].includes(item.status)).length;
  const pending = items.filter((item) => item.status === "pending_entry").length;
  const realized = items.reduce((sum, item) => sum + (item.realized_pnl_usdt || 0), 0);
  const unrealized = items.filter((item) => ["pending_entry", "open", "partial"].includes(item.status))
    .reduce((sum, item) => sum + (item.unrealized_pnl_usdt || 0), 0);
  els.posActive.textContent = String(active);
  els.posPending.textContent = String(pending);
  els.posRealized.textContent = fmtNum(realized);
  els.posRealized.className = pnlClass(realized);
  els.posUnrealized.textContent = fmtNum(unrealized);
  els.posUnrealized.className = pnlClass(unrealized);
}

function renderPositions(items) {
  if (!items.length) {
    els.positions.innerHTML = '<div class="empty">No positions yet.</div>';
    return;
  }
  els.positions.innerHTML = items.map((item) => `
    <article class="card">
      <div class="card-top">
        <div>
          <p class="name">${escapeHtml(item.symbol)}</p>
          <div class="meta">${escapeHtml(item.direction)} | ${escapeHtml(item.structure)} | ${escapeHtml(item.entry_mode)}</div>
        </div>
        <span class="badge position-status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
      </div>
      <div class="metrics">
        <div class="metric"><span class="metric-label">Entry</span><span class="metric-value">${fmtNum(item.entry, 4)}</span></div>
        <div class="metric"><span class="metric-label">Notional</span><span class="metric-value">${fmtNum(item.notional_usdt || 0)} USDT</span></div>
        <div class="metric"><span class="metric-label">Quantity</span><span class="metric-value">${fmtNum(item.quantity || 0, 6)}</span></div>
        <div class="metric"><span class="metric-label">Current Stop</span><span class="metric-value">${fmtNum(item.current_stop_loss, 4)}</span></div>
        <div class="metric"><span class="metric-label">Target</span><span class="metric-value">${fmtNum(item.take_profit, 4)}</span></div>
      </div>
      <div class="diagnostic-grid">
        <div class="diagnostic-box">
          <strong>Status</strong>
          Confirmed ${item.entry_confirmed ? "Yes" : "No"}<br>
          TP1 / TP2 ${item.tp1_hit ? "hit" : "pending"} / ${item.tp2_hit ? "hit" : "pending"}<br>
          Updated ${fmtTime(item.updated_at)}
        </div>
          <div class="diagnostic-box">
            <strong>PnL</strong>
            <span class="${pnlClass(item.realized_pnl_usdt || 0)}">Realized ${fmtNum(item.realized_pnl_usdt || 0)} USDT</span><br>
            <span class="${pnlClass(item.unrealized_pnl_usdt || 0)}">Unrealized ${fmtNum(item.unrealized_pnl_usdt || 0)} USDT</span><br>
            <span class="${pnlClass(item.pnl_usdt || 0)}">Total ${fmtNum(item.pnl_usdt || 0)} USDT</span><br>
            Exit ${escapeHtml(item.exit_reason || "Still active")}<br>
            Strategy ${escapeHtml(item.primary_strategy_name || "unattributed")}
          </div>
        </div>
        ${(item.matched_strategy_names || []).length ? `<div class="detail-block"><strong>Matched Cards</strong><div>${escapeHtml(item.matched_strategy_names.join(" | "))}</div></div>` : ""}
        ${(item.management_plan || []).length ? `<ul class="plan-list">${item.management_plan.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}</ul>` : ""}
      </article>
  `).join("");
}

function renderJournalStats(items) {
  const warnings = items.filter((item) => item.status === "warning").length;
  const closed = items.filter((item) => item.event_type === "trade_closed").length;
  const circuits = items.filter((item) => item.event_type === "trade_loop_circuit_breaker").length;
  els.journalCount.textContent = String(items.length);
  els.journalWarnings.textContent = String(warnings);
  els.journalClosed.textContent = String(closed);
  els.journalCircuits.textContent = String(circuits);
}

function renderJournal(items) {
  if (!items.length) {
    els.journal.innerHTML = '<div class="empty">No journal events yet.</div>';
    return;
  }
  els.journal.innerHTML = items.map((item) => {
    let details = {};
    try {
      details = item.details ? JSON.parse(item.details) : {};
    } catch {
      details = {};
    }
    const preferredKeys = ["entry", "quantity", "notional_usdt", "stop_loss", "take_profit", "primary_strategy_name"];
    const orderedEntries = [
      ...preferredKeys.filter((key) => key in details).map((key) => [key, details[key]]),
      ...Object.entries(details).filter(([key]) => !preferredKeys.includes(key)),
    ];
    const detailLines = orderedEntries.slice(0, 6).map(([key, value]) =>
      `${escapeHtml(key)}: ${escapeHtml(Array.isArray(value) ? value.join(" | ") : value)}`
    ).join("<br>");
    const badgeClass = item.status === "warning" ? "bad" : item.event_type.includes("closed") || item.event_type.includes("cancelled") ? "warn" : "good";
    return `
      <article class="card">
        <div class="card-top">
          <div>
            <p class="name">${escapeHtml(item.symbol)}</p>
            <div class="meta">${escapeHtml(item.event_type)} | ${fmtTime(item.created_at)}</div>
          </div>
          <span class="badge ${badgeClass}">${escapeHtml(item.status || "info")}</span>
        </div>
        <div class="diagnostic-grid">
          <div class="diagnostic-box">
            <strong>Event</strong>
            ${escapeHtml(item.message || "No message")}
          </div>
          <div class="diagnostic-box">
          <strong>Details</strong>
          Trade ID ${escapeHtml(item.trade_id || "-")}<br>
          ${detailLines || "No extra details"}
          </div>
        </div>
      </article>
    `;
  }).join("");
}

function setView(view) {
  state.activeView = view;
  els.tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === view);
  });
  els.views.forEach((section) => {
    section.classList.toggle("active", section.id === `view-${view}`);
  });
}

function setStrategyTier(tier) {
  state.strategyTier = tier;
  state.strategyPage = 1;
  els.tierButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.tier === tier);
  });
  renderStrategies();
}

function setDiagnosticMode(mode) {
  state.diagnosticMode = mode;
  els.diagModeCoreCandidate.classList.toggle("active", mode === "core+candidate");
  els.diagModeCoreOnly.classList.toggle("active", mode === "core-only");
  els.diagModeAll.classList.toggle("active", mode === "all");
  loadDiagnostics();
}

async function loadDashboard() {
  if (state.isRefreshing) {
    return;
  }
  state.isRefreshing = true;
  els.runtimeRefresh.textContent = "Refreshing now";
  try {
    await Promise.all([loadAccount(), loadCards(), loadDiagnostics(), loadPositions(), loadJournal()]);
  } catch (error) {
    els.runtimeStatus.textContent = "Dashboard load failed";
    console.error(error);
  } finally {
    state.isRefreshing = false;
    scheduleNextRefreshLabel();
  }
}

function startAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
  }
  if (refreshCountdownTimer) {
    clearInterval(refreshCountdownTimer);
  }
  nextRefreshAt = Date.now() + DASHBOARD_REFRESH_MS;
  refreshTimer = setInterval(() => {
    if (document.visibilityState !== "visible") {
      return;
    }
    nextRefreshAt = Date.now() + DASHBOARD_REFRESH_MS;
    loadDashboard();
  }, DASHBOARD_REFRESH_MS);
  refreshCountdownTimer = setInterval(updateRefreshLabel, 1000);
  updateRefreshLabel();
}

function updateRefreshLabel() {
  if (state.isRefreshing) {
    els.runtimeRefresh.textContent = "Refreshing now";
    return;
  }
  if (!nextRefreshAt) {
    els.runtimeRefresh.textContent = `Auto refresh every ${Math.round(DASHBOARD_REFRESH_MS / 1000)}s`;
    return;
  }
  const remainingMs = Math.max(nextRefreshAt - Date.now(), 0);
  const remainingSeconds = Math.ceil(remainingMs / 1000);
  els.runtimeRefresh.textContent = `Next refresh in ${remainingSeconds}s`;
}

function scheduleNextRefreshLabel() {
  nextRefreshAt = Date.now() + DASHBOARD_REFRESH_MS;
  updateRefreshLabel();
}

els.tabButtons.forEach((button) => button.addEventListener("click", () => setView(button.dataset.tab)));
els.tierButtons.forEach((button) => button.addEventListener("click", () => setStrategyTier(button.dataset.tier)));
els.search.addEventListener("input", () => {
  state.strategyPage = 1;
  renderStrategies();
});
els.sort.addEventListener("change", renderStrategies);
els.diagModeCoreCandidate.addEventListener("click", () => setDiagnosticMode("core+candidate"));
els.diagModeCoreOnly.addEventListener("click", () => setDiagnosticMode("core-only"));
els.diagModeAll.addEventListener("click", () => setDiagnosticMode("all"));

setView("overview");
loadDashboard();
startAutoRefresh();

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    scheduleNextRefreshLabel();
    loadDashboard();
  }
});
