const state = {
  cards: [],
  filtered: [],
  leaderboard: [],
  diagnostics: [],
  positions: [],
  journal: [],
  diagnosticMode: "core+candidate",
};

const els = {
  cards: document.getElementById("cards"),
  leaderboard: document.getElementById("leaderboard"),
  diagnostics: document.getElementById("diagnostics"),
  positions: document.getElementById("positions"),
  journal: document.getElementById("journal"),
  search: document.getElementById("search"),
  sort: document.getElementById("sort"),
  sourceStatus: document.getElementById("source-status"),
  leaderboardStatus: document.getElementById("leaderboard-status"),
  diagnosticStatus: document.getElementById("diagnostic-status"),
  positionStatus: document.getElementById("position-status"),
  journalStatus: document.getElementById("journal-status"),
  statCards: document.getElementById("stat-cards"),
  statSamples: document.getElementById("stat-samples"),
  statWinrate: document.getElementById("stat-winrate"),
  statRr: document.getElementById("stat-rr"),
  statHoldHours: document.getElementById("stat-hold-hours"),
  statTp1: document.getElementById("stat-tp1"),
  statTp2: document.getElementById("stat-tp2"),
  statDrawdown: document.getElementById("stat-drawdown"),
  diagTradeable: document.getElementById("diag-tradeable"),
  diagBlocked: document.getElementById("diag-blocked"),
  diagOnchain: document.getElementById("diag-onchain"),
  diagHoneypot: document.getElementById("diag-honeypot"),
  diagModeCoreCandidate: document.getElementById("diag-mode-core-candidate"),
  diagModeCoreOnly: document.getElementById("diag-mode-core-only"),
  diagModeAll: document.getElementById("diag-mode-all"),
  posActive: document.getElementById("pos-active"),
  posPending: document.getElementById("pos-pending"),
  posRealized: document.getElementById("pos-realized"),
  posUnrealized: document.getElementById("pos-unrealized"),
  journalCount: document.getElementById("journal-count"),
  journalWarnings: document.getElementById("journal-warnings"),
  journalClosed: document.getElementById("journal-closed"),
  journalCircuits: document.getElementById("journal-circuits"),
};

function fmtPct(value) {
  if (value == null || Number.isNaN(value)) return "0%";
  return `${(value * 100).toFixed(1)}%`;
}

function fmtNum(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return Number(0).toFixed(digits);
  return Number(value).toFixed(digits);
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
  if (value > 0) return "pnl-positive";
  if (value < 0) return "pnl-negative";
  return "pnl-flat";
}

function badgeClassByTradeable(item) {
  if (item.tradeable) return "good";
  if (item.snapshot?.onchain_honeypot) return "bad";
  return "warn";
}

function badgeClassByTier(tier) {
  if (tier === "core") return "good";
  if (tier === "candidate") return "warn";
  return "bad";
}

function scoreCard(card) {
  const win = card.historical_win_rate || 0;
  const rr = card.historical_rr || 0;
  const sample = card.sample_size || 0;
  const tp2 = card.tp2_hit_rate || 0;
  const drawdownPenalty = Math.abs(Math.min(card.max_drawdown_rr || 0, 0));
  return win * 100 + rr * 12 + tp2 * 20 + Math.min(sample, 50) * 0.8 - drawdownPenalty * 4;
}

function renderStats(cards) {
  const samples = cards.reduce((sum, card) => sum + (card.sample_size || 0), 0);
  const avgWin = cards.length ? cards.reduce((sum, card) => sum + (card.historical_win_rate || 0), 0) / cards.length : 0;
  const avgRr = cards.length ? cards.reduce((sum, card) => sum + (card.historical_rr || 0), 0) / cards.length : 0;
  const avgHoldHours = cards.length ? cards.reduce((sum, card) => sum + (card.avg_hold_hours || 0), 0) / cards.length : 0;
  const avgTp1 = cards.length ? cards.reduce((sum, card) => sum + (card.tp1_hit_rate || 0), 0) / cards.length : 0;
  const avgTp2 = cards.length ? cards.reduce((sum, card) => sum + (card.tp2_hit_rate || 0), 0) / cards.length : 0;
  const avgDrawdown = cards.length ? cards.reduce((sum, card) => sum + (card.max_drawdown_rr || 0), 0) / cards.length : 0;

  els.statCards.textContent = String(cards.length);
  els.statSamples.textContent = String(samples);
  els.statWinrate.textContent = fmtPct(avgWin);
  els.statRr.textContent = fmtNum(avgRr);
  els.statHoldHours.textContent = fmtNum(avgHoldHours);
  els.statTp1.textContent = fmtPct(avgTp1);
  els.statTp2.textContent = fmtPct(avgTp2);
  els.statDrawdown.textContent = fmtNum(avgDrawdown);
  els.statDrawdown.className = pnlClass(avgDrawdown);
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

function renderPositionStats(items) {
  const active = items.filter((item) => ["pending_entry", "open", "partial"].includes(item.status)).length;
  const pending = items.filter((item) => item.status === "pending_entry").length;
  const realized = items.reduce((sum, item) => sum + (item.realized_pnl_usdt || 0), 0);
  const unrealized = items
    .filter((item) => ["pending_entry", "open", "partial"].includes(item.status))
    .reduce((sum, item) => sum + (item.unrealized_pnl_usdt || 0), 0);

  els.posActive.textContent = String(active);
  els.posPending.textContent = String(pending);
  els.posRealized.textContent = fmtNum(realized);
  els.posRealized.className = pnlClass(realized);
  els.posUnrealized.textContent = fmtNum(unrealized);
  els.posUnrealized.className = pnlClass(unrealized);
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

function renderLeaderboard(items) {
  if (!items.length) {
    els.leaderboard.innerHTML = '<div class="empty">No leaderboard data yet.</div>';
    return;
  }

  els.leaderboard.innerHTML = items.map((item, index) => {
    const rationale = (item.rationale || []).map((reason) => `<li>${escapeHtml(reason)}</li>`).join("");
    return `
      <article class="card">
        <div class="card-top">
          <div>
            <p class="name">#${index + 1} ${escapeHtml(item.name)}</p>
            <div class="meta">${escapeHtml(item.creator)} | ${escapeHtml(item.market)} | ${escapeHtml(item.timeframe)}</div>
          </div>
          <span class="badge ${badgeClassByTier(item.tier)}">${escapeHtml(item.tier)}</span>
        </div>
        <div class="metrics">
          <div class="metric">
            <span class="metric-label">Rank Score</span>
            <span class="metric-value">${fmtNum(item.rank_score)}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Win Rate</span>
            <span class="metric-value">${fmtPct(item.historical_win_rate || 0)}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Tier Tag</span>
            <span class="metric-value">${escapeHtml(item.strategy_tier || item.tier)}</span>
          </div>
        </div>
        <div class="diagnostic-grid">
          <div class="diagnostic-box">
            <strong>Execution Quality</strong>
            Samples ${item.sample_size || 0}<br>
            TP1 hit ${fmtPct(item.tp1_hit_rate || 0)}<br>
            TP2 hit ${fmtPct(item.tp2_hit_rate || 0)}<br>
            Hold ${fmtNum(item.avg_hold_hours || 0)} h
          </div>
          <div class="diagnostic-box">
            <strong>Risk Shape</strong>
            Drawdown <span class="${pnlClass(item.max_drawdown_rr || 0)}">${fmtNum(item.max_drawdown_rr || 0)} RR</span><br>
            Breakeven exits ${fmtPct(item.breakeven_exit_rate || 0)}<br>
            Wins / losses ${(item.wins || 0)} / ${(item.losses || 0)}<br>
            Total RR ${fmtNum(item.total_rr || 0)}
          </div>
        </div>
        <ul class="reason-list">${rationale}</ul>
      </article>
    `;
  }).join("");
}

function renderCards(cards) {
  if (!cards.length) {
    els.cards.innerHTML = '<div class="empty">No matching strategy cards yet.</div>';
    return;
  }

  els.cards.innerHTML = cards.map((card) => {
    const winRate = card.historical_win_rate || 0;
    const sample = card.sample_size || 0;
    const progressWidth = Math.min(100, Math.max(0, winRate * 100));
    const chips = [
      card.market,
      card.timeframe,
      card.creator,
      ...((card.tags || []).slice(0, 3)),
    ]
      .filter(Boolean)
      .map((item) => `<span class="badge">${escapeHtml(item)}</span>`)
      .join("");
    const symbols = (card.preferred_symbols || []).slice(0, 4).join(", ") || "none";
    const entry = (card.entry_conditions || []).slice(0, 3).join(" | ") || "manual_review_required";
    const risk = (card.risk_notes || []).slice(0, 2).join(" | ") || "none";
    const updatedAt = card.updated_at ? card.updated_at.slice(0, 19).replace("T", " ") : "-";

    return `
      <article class="card">
        <div class="card-top">
          <div>
            <p class="name">${escapeHtml(card.name)}</p>
            <div class="meta">${escapeHtml(card.description || "No description")}</div>
          </div>
          <span class="badge ${badgeClassByTier(card.strategy_tier)}">${escapeHtml(card.strategy_tier || "watchlist")}</span>
        </div>
        <div class="badge-row">${chips}</div>
        <div class="metrics">
          <div class="metric">
            <span class="metric-label">Samples</span>
            <span class="metric-value">${sample}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Average RR</span>
            <span class="metric-value">${fmtNum(card.historical_rr || 0)}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Tier Score</span>
            <span class="metric-value">${fmtNum(card.tier_score || 0)}</span>
          </div>
        </div>
        <div class="diagnostic-grid">
          <div class="diagnostic-box">
            <strong>Execution Metrics</strong>
            Avg hold ${fmtNum(card.avg_hold_hours || 0)} h<br>
            TP1 hit ${fmtPct(card.tp1_hit_rate || 0)}<br>
            TP2 hit ${fmtPct(card.tp2_hit_rate || 0)}<br>
            Breakeven exits ${fmtPct(card.breakeven_exit_rate || 0)}
          </div>
          <div class="diagnostic-box">
            <strong>Risk Profile</strong>
            Max drawdown <span class="${pnlClass(card.max_drawdown_rr || 0)}">${fmtNum(card.max_drawdown_rr || 0)} RR</span><br>
            Wins / losses ${(card.wins || 0)} / ${(card.losses || 0)}<br>
            Total RR ${fmtNum(card.total_rr || 0)}<br>
            Bias ${fmtNum(card.confidence_bias || 0)}
          </div>
        </div>
        <div class="progress" aria-label="win-rate">
          <span style="width:${progressWidth}%"></span>
        </div>
        <div class="details">
          <div><strong>Symbols</strong><br>${escapeHtml(symbols)}</div>
          <div><strong>Entry</strong><br>${escapeHtml(entry)}</div>
          <div><strong>Rationale</strong><br>${escapeHtml((card.tier_rationale || []).slice(0, 2).join(" | ") || risk)}</div>
          <div><strong>Updated</strong><br>${escapeHtml(updatedAt)}</div>
        </div>
      </article>
    `;
  }).join("");
}

function renderDiagnostics(items) {
  if (!items.length) {
    els.diagnostics.innerHTML = '<div class="empty">No candidate diagnostics yet. Trigger a scan first.</div>';
    return;
  }

  els.diagnostics.innerHTML = items.map((item) => {
    const snapshot = item.snapshot || {};
    const signal = item.signal;
    const risk = item.risk || {};
    const statusText = item.tradeable ? "Tradeable" : (snapshot.onchain_honeypot ? "Blocked" : "Rejected");
    const topReasons = (risk.reasons || item.reasons || []).slice(0, 4)
      .map((reason) => `<li>${escapeHtml(reason)}</li>`)
      .join("");
    const plan = (signal?.management_plan || item.analysis?.management_plan || []).slice(0, 3)
      .map((step) => `<li>${escapeHtml(step)}</li>`)
      .join("");
    const chips = [
      snapshot.market_regime && `regime:${snapshot.market_regime}`,
      snapshot.reversal_stage && `reversal:${snapshot.reversal_stage}`,
      ...(item.tags || []).slice(0, 4),
    ]
      .filter(Boolean)
      .map((tag) => `<span class="badge">${escapeHtml(tag)}</span>`)
      .join("");
    const liquidity = snapshot.onchain_liquidity_usd == null ? "-" : `${fmtNum(snapshot.onchain_liquidity_usd)} USD`;
    const soldRatio = snapshot.onchain_sold_ratio_percent == null ? "-" : `${fmtNum(snapshot.onchain_sold_ratio_percent)}%`;
    const safeBuy = snapshot.onchain_is_safe_buy === false ? "No" : snapshot.onchain_is_safe_buy === true ? "Yes" : "-";
    const tradePlan = signal
      ? `Entry ${fmtNum(signal.entry, 4)} | Stop ${fmtNum(signal.stop_loss, 4)} | Take Profit ${fmtNum(signal.take_profit, 4)}`
      : "No executable signal right now";
    const strategyMatches = (item.strategy_matches || []).slice(0, 4)
      .map((match) => {
        const notes = (match.notes || []).slice(0, 2).join(" | ") || "no extra notes";
        return `
          <li>
            <strong>${escapeHtml(match.name)}</strong>
            <span class="badge ${badgeClassByTier(match.tier)}">${escapeHtml(match.tier)}</span><br>
            Bonus ${fmtNum(match.applied_bonus)} | Weight x${fmtNum(match.weight_multiplier)} | Tier score ${fmtNum(match.tier_score)}<br>
            ${escapeHtml(notes)}
          </li>
        `;
      })
      .join("");

    return `
      <article class="card">
        <div class="card-top">
          <div>
            <p class="name">${escapeHtml(item.symbol)}</p>
            <div class="meta">Structure ${escapeHtml(item.analysis?.structure || "unknown")} | Direction ${escapeHtml(item.analysis?.direction || "neutral")} | Score ${fmtNum(item.hard_score)}</div>
          </div>
          <span class="badge ${badgeClassByTradeable(item)} signal-status">${statusText}</span>
        </div>
        <div class="badge-row">${chips}</div>
        <div class="diagnostic-grid">
          <div class="diagnostic-box">
            <strong>Binance Structure</strong>
            BTC backdrop ${escapeHtml(snapshot.btc_trend || "unknown")}<br>
            Relative strength ${fmtNum(snapshot.relative_strength_score || 0)}<br>
            Retest quality ${fmtNum(snapshot.retest_quality_score || 0)}<br>
            Follow-through ${fmtNum(snapshot.follow_through_score || 0)}
          </div>
          <div class="diagnostic-box">
            <strong>Onchain Signal</strong>
            Signal score ${fmtNum(snapshot.onchain_signal_score || 0)}<br>
            Wallet count ${snapshot.onchain_wallet_count || 0}<br>
            Buy amount ${fmtNum(snapshot.onchain_buy_amount_usd || 0)} USD<br>
            Sold ratio ${soldRatio}
          </div>
          <div class="diagnostic-box">
            <strong>Security Risk</strong>
            Risk level ${escapeHtml(snapshot.onchain_risk_level || "unknown")}<br>
            Honeypot ${snapshot.onchain_honeypot ? "Yes" : "No"}<br>
            Safe to buy ${safeBuy}<br>
            Onchain liquidity ${escapeHtml(liquidity)}
          </div>
          <div class="diagnostic-box">
            <strong>Trade Plan</strong>
            ${escapeHtml(tradePlan)}
          </div>
        </div>
        <div class="diagnostic-box">
          <strong>Strategy Weighting (${escapeHtml(item.strategy_tier_mode || state.diagnosticMode)})</strong>
          ${strategyMatches ? `<ul class="reason-list">${strategyMatches}</ul>` : "No strategy card matched under this tier mode."}
        </div>
        <ul class="reason-list">${topReasons || "<li>No reasons recorded.</li>"}</ul>
        ${plan ? `<ul class="plan-list">${plan}</ul>` : ""}
      </article>
    `;
  }).join("");
}

function renderPositions(items) {
  if (!items.length) {
    els.positions.innerHTML = '<div class="empty">No positions yet. Run a scan and let the simulation open or manage trades.</div>';
    return;
  }

  els.positions.innerHTML = items.map((item) => {
    const realized = item.realized_pnl_usdt || 0;
    const unrealized = item.unrealized_pnl_usdt || 0;
    const totalPnl = item.pnl_usdt || 0;
    const managementPlan = (item.management_plan || []).slice(0, 3)
      .map((step) => `<li>${escapeHtml(step)}</li>`)
      .join("");
    const exitReason = item.exit_reason ? escapeHtml(item.exit_reason) : "Still active";
    const updatedAt = item.updated_at ? item.updated_at.slice(0, 19).replace("T", " ") : "-";

    return `
      <article class="card">
        <div class="card-top">
          <div>
            <p class="name">${escapeHtml(item.symbol)}</p>
            <div class="meta">${escapeHtml(item.direction)} | ${escapeHtml(item.structure)} | ${escapeHtml(item.entry_mode)}</div>
          </div>
          <span class="badge position-status-${escapeHtml(item.status)}">${escapeHtml(item.status)}</span>
        </div>
        <div class="metrics">
          <div class="metric">
            <span class="metric-label">Entry</span>
            <span class="metric-value">${fmtNum(item.entry, 4)}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Current Stop</span>
            <span class="metric-value">${fmtNum(item.current_stop_loss, 4)}</span>
          </div>
          <div class="metric">
            <span class="metric-label">Target</span>
            <span class="metric-value">${fmtNum(item.take_profit, 4)}</span>
          </div>
        </div>
        <div class="diagnostic-grid">
          <div class="diagnostic-box">
            <strong>Position State</strong>
            Confirmed ${item.entry_confirmed ? "Yes" : "No"}<br>
            Remaining ${fmtNum(item.remaining_notional_usdt)} USDT<br>
            TP1 / TP2 ${item.tp1_hit ? "hit" : "pending"} / ${item.tp2_hit ? "hit" : "pending"}<br>
            Updated ${escapeHtml(updatedAt)}
          </div>
          <div class="diagnostic-box">
            <strong>PnL</strong>
            <span class="${pnlClass(realized)}">Realized ${fmtNum(realized)} USDT</span><br>
            <span class="${pnlClass(unrealized)}">Unrealized ${fmtNum(unrealized)} USDT</span><br>
            <span class="${pnlClass(totalPnl)}">Total ${fmtNum(totalPnl)} USDT</span><br>
            Exit ${exitReason}
          </div>
          <div class="diagnostic-box">
            <strong>Levels</strong>
            Initial stop ${fmtNum(item.initial_stop_loss, 4)}<br>
            TP1 ${fmtNum(item.tp1_price, 4)}<br>
            TP2 ${fmtNum(item.tp2_price, 4)}<br>
            Last price ${item.last_price == null ? "-" : fmtNum(item.last_price, 4)}
          </div>
          <div class="diagnostic-box">
            <strong>Flags</strong>
            Break-even ${item.break_even_armed ? "armed" : "idle"}<br>
            Trail ${item.trail_active ? "active" : "idle"}<br>
            Max seen ${item.max_price_seen == null ? "-" : fmtNum(item.max_price_seen, 4)}<br>
            Min seen ${item.min_price_seen == null ? "-" : fmtNum(item.min_price_seen, 4)}
          </div>
        </div>
        ${managementPlan ? `<ul class="plan-list">${managementPlan}</ul>` : ""}
      </article>
    `;
  }).join("");
}

function renderJournal(items) {
  if (!items.length) {
    els.journal.innerHTML = '<div class="empty">No journal events yet. Run scans and manage positions to build the review trail.</div>';
    return;
  }

  els.journal.innerHTML = items.map((item) => {
    let details = {};
    try {
      details = item.details ? JSON.parse(item.details) : {};
    } catch {
      details = {};
    }
    const createdAt = item.created_at ? item.created_at.slice(0, 19).replace("T", " ") : "-";
    const detailLines = Object.entries(details)
      .slice(0, 4)
      .map(([key, value]) => `${escapeHtml(key)}: ${escapeHtml(Array.isArray(value) ? value.join(" | ") : value)}`)
      .join("<br>");
    const badgeClass = item.status === "warning"
      ? "bad"
      : item.event_type.includes("closed") || item.event_type.includes("cancelled")
        ? "warn"
        : "good";

    return `
      <article class="card">
        <div class="card-top">
          <div>
            <p class="name">${escapeHtml(item.symbol)}</p>
            <div class="meta">${escapeHtml(item.event_type)} | ${escapeHtml(createdAt)}</div>
          </div>
          <span class="badge ${badgeClass}">${escapeHtml(item.status || "info")}</span>
        </div>
        <div class="diagnostic-grid">
          <div class="diagnostic-box">
            <strong>Event</strong>
            ${escapeHtml(item.message || "No message")}
          </div>
          <div class="diagnostic-box">
            <strong>Trade Context</strong>
            Trade ID ${escapeHtml(item.trade_id || "-")}<br>
            ${detailLines || "No extra details"}
          </div>
        </div>
      </article>
    `;
  }).join("");
}

function applyFilters() {
  const query = els.search.value.trim().toLowerCase();
  const sorted = [...state.cards].filter((card) => {
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

  const sortKey = els.sort.value;
  sorted.sort((a, b) => {
    if (sortKey === "win_rate") return (b.historical_win_rate || 0) - (a.historical_win_rate || 0);
    if (sortKey === "sample_size") return (b.sample_size || 0) - (a.sample_size || 0);
    if (sortKey === "rr") return (b.historical_rr || 0) - (a.historical_rr || 0);
    return scoreCard(b) - scoreCard(a);
  });

  state.filtered = sorted;
  renderStats(sorted);
  renderCards(sorted);
}

async function loadCards() {
  try {
    const response = await fetch("/strategy-cards");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.cards = await response.json();
    applyFilters();
    return state.cards.length;
  } catch (error) {
    els.cards.innerHTML = '<div class="empty">Unable to load /strategy-cards.</div>';
    console.error(error);
    return 0;
  }
}

async function loadLeaderboard() {
  try {
    const response = await fetch("/strategy-cards/leaderboard?limit=8");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.leaderboard = await response.json();
    renderLeaderboard(state.leaderboard);
    return state.leaderboard.length;
  } catch (error) {
    els.leaderboard.innerHTML = '<div class="empty">Unable to load /strategy-cards/leaderboard.</div>';
    console.error(error);
    return 0;
  }
}

async function loadDiagnostics() {
  try {
    const response = await fetch(`/diagnostics/candidates?limit=10&tier_mode=${encodeURIComponent(state.diagnosticMode)}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.diagnostics = await response.json();
    renderDiagnosticStats(state.diagnostics);
    renderDiagnostics(state.diagnostics);
    return state.diagnostics.length;
  } catch (error) {
    els.diagnostics.innerHTML = '<div class="empty">Unable to load /diagnostics/candidates.</div>';
    console.error(error);
    return 0;
  }
}

async function loadPositions() {
  try {
    const response = await fetch("/positions?include_closed=true");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.positions = await response.json();
    renderPositionStats(state.positions);
    renderPositions(state.positions);
    return state.positions.length;
  } catch (error) {
    els.positions.innerHTML = '<div class="empty">Unable to load /positions.</div>';
    console.error(error);
    return 0;
  }
}

async function loadJournal() {
  try {
    const response = await fetch("/positions/journal?limit=20");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.journal = await response.json();
    renderJournalStats(state.journal);
    renderJournal(state.journal);
    return state.journal.length;
  } catch (error) {
    els.journal.innerHTML = '<div class="empty">Unable to load /positions/journal.</div>';
    console.error(error);
    return 0;
  }
}

async function loadDashboard() {
  els.sourceStatus.textContent = "Loading";
  els.leaderboardStatus.textContent = "Loading";
  els.diagnosticStatus.textContent = "Loading";
  els.positionStatus.textContent = "Loading";
  els.journalStatus.textContent = "Loading";

  const [cardCount, leaderboardCount, diagnosticCount, positionCount, journalCount] = await Promise.all([
    loadCards(),
    loadLeaderboard(),
    loadDiagnostics(),
    loadPositions(),
    loadJournal(),
  ]);

  els.sourceStatus.textContent = `Loaded ${cardCount} cards`;
  els.leaderboardStatus.textContent = `Loaded top ${leaderboardCount}`;
  els.diagnosticStatus.textContent = `Loaded ${diagnosticCount} coins (${state.diagnosticMode})`;
  els.positionStatus.textContent = `Loaded ${positionCount} positions`;
  els.journalStatus.textContent = `Loaded ${journalCount} events`;
}

function setDiagnosticMode(mode) {
  state.diagnosticMode = mode;
  els.diagModeCoreCandidate.classList.toggle("active", mode === "core+candidate");
  els.diagModeCoreOnly.classList.toggle("active", mode === "core-only");
  els.diagModeAll.classList.toggle("active", mode === "all");
  loadDiagnostics().then((count) => {
    els.diagnosticStatus.textContent = `Loaded ${count} coins (${state.diagnosticMode})`;
  });
}

els.search.addEventListener("input", applyFilters);
els.sort.addEventListener("change", applyFilters);
els.diagModeCoreCandidate.addEventListener("click", () => setDiagnosticMode("core+candidate"));
els.diagModeCoreOnly.addEventListener("click", () => setDiagnosticMode("core-only"));
els.diagModeAll.addEventListener("click", () => setDiagnosticMode("all"));

loadDashboard();
