/* SpectraLedger frontend - plain DOM, fetch() and native WebSocket. No framework, no build step.
   Backend URLs come ONLY from config.js. */
(() => {
  "use strict";
  const CFG = window.SPECTRA_CONFIG;
  const LEDGER = CFG.LEDGER_URL.replace(/\/+$/, "");
  const AI = CFG.AI_ENGINE_URL.replace(/\/+$/, "");
  const WS_URL = AI.replace(/^http/, "ws") + "/ws/stream";

  // ---------------------------------------------------------------- helpers
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function el(tag, props, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(props || {})) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "style") n.setAttribute("style", v);
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid !== null && kid !== undefined) n.append(kid);
    return n;
  }
  const usd = (n, d = 2) => "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const num = (n, d = 0) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (x) => Math.round(x * 100) + "%";
  const clock = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); };
  const shortSlice = (id) => String(id || "").replace(/^slice-/, "");
  const flash = (node, cls = "flash") => { node.classList.add(cls); setTimeout(() => node.classList.remove(cls), 1800); };

  // Calm live numbers: tween from the old value to the new one instead of jumping.
  function tween(node, to, fmt) {
    const from = Number(node.dataset.v || 0);
    node.dataset.v = to;
    if (from === to) { node.firstChild ? (node.firstChild.textContent = fmt(to)) : (node.textContent = fmt(to)); return; }
    const t0 = performance.now(), dur = 700;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      const txt = fmt(from + (to - from) * e);
      node.firstChild && node.firstChild.nodeType === 3 ? (node.firstChild.textContent = txt) : (node.textContent = txt);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ---------------------------------------------------------------- service status dots
  const svcOk = { ai: null, ledger: null };
  function setSvc(name, ok) {
    if (svcOk[name] === ok) return;
    svcOk[name] = ok;
    $$(`.dot[data-svc="${name}"]`).forEach((d) => { d.classList.toggle("ok", ok); d.classList.toggle("down", !ok); d.title = ok ? "reachable" : "not reachable"; });
  }

  async function api(base, path, opts = {}) {
    const svc = base === LEDGER ? "ledger" : "ai";
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 6000);
    try {
      const init = { signal: ctl.signal, headers: {} };
      if (opts.method) init.method = opts.method;
      if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
      const res = await fetch(base + path, init);
      setSvc(svc, true);
      let data = null;
      try { data = await res.json(); } catch (_) { /* empty body */ }
      if (!res.ok) { const err = new Error((data && (data.message || data.detail)) || ("HTTP " + res.status)); err.status = res.status; throw err; }
      return data;
    } catch (e) {
      if (e.status === undefined) setSvc(svc, false);   // network failure / timeout, not an HTTP error
      throw e;
    } finally { clearTimeout(timer); }
  }

  // ---------------------------------------------------------------- tabs
  $$(".tab").forEach((t) => t.addEventListener("click", () => {
    $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
    $$(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + t.dataset.tab));
    if (t.dataset.tab === "market") redrawAllSparks();
    if (t.dataset.tab === "book") pollBook();
  }));

  // ---------------------------------------------------------------- slice directory (from the AI engine)
  let slices = [];
  const sliceMap = {};
  const sliceName = (id) => (sliceMap[id] ? sliceMap[id].enterprise : shortSlice(id));

  async function loadSlices() {
    try {
      slices = await api(AI, "/slices");
      slices.forEach((s) => (sliceMap[s.id] = s));
      const opts = (sel, pick) => { const n = $(sel); n.replaceChildren(...slices.map((s) => el("option", { value: s.id, text: `${s.enterprise} · ${s.id}` }))); if (pick) n.value = pick; };
      opts("#order-slice", "slice-ai-01"); opts("#neg-seller", "slice-mmtc-01"); opts("#neg-buyer", "slice-ai-01");
      $("#slice-list").replaceChildren(...slices.map((s) => el("option", { value: s.id })));
      buildSliceGrid();
    } catch (e) { setTimeout(loadSlices, 3000); }
  }

  // ================================================================ PANEL 1: LEDGER
  let page = 0, knownTrades = null, lookupSlice = null;
  const PAGE = 12;

  async function pollLedger() {
    try {
      const s = await api(LEDGER, "/api/revenue/summary");
      tween($("#kpi-fees"), Number(s.total_platform_fees), (v) => usd(v, 2));
      tween($("#kpi-count"), Number(s.trade_count), (v) => num(v));
      tween($("#kpi-volume"), Number(s.total_volume), (v) => usd(v, 2));
      tween($("#kpi-mbps").firstChild ? $("#kpi-mbps") : $("#kpi-mbps"), Number(s.total_quantity_mbps), (v) => num(v) + " ");
      $("#kpi-fee-note").textContent = `${(Number(s.fee_rate) * 100).toFixed(0)}% of every settled trade — how the marketplace earns.`;
      const t = await api(LEDGER, `/api/trades?page=${page}&size=${PAGE}`);
      renderTrades(t);
    } catch (e) { /* dot already shows the outage */ }
  }

  function renderTrades(t) {
    const body = $("#trades-body");
    const fresh = new Set();
    if (knownTrades === null) knownTrades = new Set(); else t.content.forEach((x) => { if (!knownTrades.has(x.trade_id)) fresh.add(x.trade_id); });
    t.content.forEach((x) => knownTrades.add(x.trade_id));
    if (!t.content.length) { body.replaceChildren(el("tr", null, el("td", { colspan: 8, class: "empty", text: "Waiting for the first settled trade…" }))); }
    else {
      const open = body.querySelector("tr.detail");
      const openId = open ? open.dataset.for : null;
      body.replaceChildren(...t.content.map((x) => {
        const tr = el("tr", { class: "clickable" + (fresh.has(x.trade_id) ? " flash" : ""), "data-id": x.trade_id, title: "Click for the journal entries", onclick: () => toggleDetail(tr, x.trade_id) },
          el("td", { text: clock(x.settled_at), class: "muted" }),
          el("td", { class: "mono", text: x.trade_id }),
          el("td", null, el("span", { text: shortSlice(x.buyer_slice_id) }), el("span", { class: "arrow", text: "←" }), el("span", { text: shortSlice(x.seller_slice_id) })),
          el("td", { class: "num", text: num(x.quantity_mbps, 1) }),
          el("td", { class: "num", text: usd(x.price, 4) }),
          el("td", { class: "num", text: usd(x.gross_amount, 4) }),
          el("td", { class: "num fee", text: usd(x.platform_fee, 4) }),
          el("td", { class: "num", text: usd(x.net_to_seller, 4) }));
        return tr;
      }));
      if (openId) { const r = body.querySelector(`tr[data-id="${openId}"]`); if (r) toggleDetail(r, openId); }
    }
    $("#trades-meta").textContent = `${t.total_elements} total`;
    $("#pg-info").textContent = t.total_pages ? `Page ${t.page + 1} of ${t.total_pages}` : "";
    $("#pg-prev").disabled = t.page <= 0;
    $("#pg-next").disabled = t.page + 1 >= t.total_pages;
  }

  async function toggleDetail(tr, id) {
    const next = tr.nextElementSibling;
    if (next && next.classList.contains("detail")) { next.remove(); return; }
    $$("#trades-body tr.detail").forEach((r) => r.remove());
    try {
      const d = await api(LEDGER, "/api/trades/" + encodeURIComponent(id));
      const cell = el("td", { colspan: 8 }, el("div", { class: "small muted", text: "Double-entry journal for this trade" }),
        ...d.ledger_entries.map((e) => el("div", { class: "entry-line" },
          el("span", { class: "entry-type " + e.entry_type, text: e.entry_type }),
          el("span", { text: shortSlice(e.slice_id) }), el("span", { class: "num", text: usd(e.amount, 4) }))));
      tr.after(el("tr", { class: "detail", "data-for": id }, cell));
    } catch (e) { /* ignore */ }
  }
  $("#pg-prev").addEventListener("click", () => { page = Math.max(0, page - 1); pollLedger(); });
  $("#pg-next").addEventListener("click", () => { page += 1; pollLedger(); });

  async function pollIntegrity() {
    const b = $("#integrity");
    try {
      const r = await api(LEDGER, "/api/ledger/verify");
      b.className = "badge " + (r.ok ? "badge-ok" : "badge-bad");
      b.textContent = r.ok ? `Ledger verified · ${r.accounts_checked} accounts reconcile to the journal` : "Ledger mismatch detected";
    } catch (e) { b.className = "badge badge-bad"; b.textContent = "Ledger unreachable"; }
  }

  async function doLookup() {
    const box = $("#lookup-result");
    if (!lookupSlice) return;
    try {
      const [a, h] = await Promise.all([
        api(LEDGER, `/api/accounts/${encodeURIComponent(lookupSlice)}/balance`),
        api(LEDGER, `/api/accounts/${encodeURIComponent(lookupSlice)}/history?limit=30`)]);
      box.className = "lookup-result";
      box.replaceChildren(
        el("div", { class: "small muted", text: `${a.enterprise} · ${a.slice_id}` }),
        el("div", { class: "balance-line", text: usd(a.balance, 2) }),
        el("div", { class: "small muted", text: `Opening balance is credited on the first settled trade · ${h.length} recent journal entries` }),
        el("div", { class: "hist" }, el("table", { class: "data" },
          el("thead", null, el("tr", null, el("th", { text: "Type" }), el("th", { text: "Trade" }), el("th", { class: "num", text: "Amount" }), el("th", { text: "Time" }))),
          el("tbody", null, ...h.map((e) => el("tr", null,
            el("td", null, el("span", { class: "entry-type " + e.entry_type, text: e.entry_type })),
            el("td", { class: "mono", text: e.trade_id }),
            el("td", { class: "num", text: usd(e.amount, 4) }),
            el("td", { class: "muted", text: clock(e.created_at) })))))));
    } catch (e) {
      box.className = "lookup-result muted";
      box.textContent = e.status === 404 ? "No account yet — a slice gets one when its first trade settles." : "Could not reach the ledger.";
    }
  }
  $("#lookup-form").addEventListener("submit", (ev) => { ev.preventDefault(); lookupSlice = $("#lookup-input").value.trim(); if (lookupSlice) doLookup(); });

  // ================================================================ PANEL 2: LIVE MARKET
  const series = {};       // slice_id -> [utilization...]
  const cards = {};        // slice_id -> DOM refs
  const feedMax = 40;

  function buildSliceGrid() {
    const grid = $("#slice-grid");
    grid.replaceChildren();
    slices.forEach((s) => {
      const c = {
        util: el("div", { class: "util", text: "—" }), sub: el("div", { class: "util-sub", text: "waiting for telemetry" }),
        bar: el("i", { style: "width:0%" }), spark: el("canvas", { class: "spark" }), state: el("div", { class: "slice-state", text: "Evaluating…" })
      };
      cards[s.id] = c;
      grid.append(el("div", { class: "card slice" },
        el("div", { class: "slice-top" }, el("div", null, el("div", { class: "slice-name", text: s.enterprise }), el("div", { class: "slice-id", text: s.id })), el("span", { class: "type-chip", text: s.type })),
        el("div", { class: "slice-mid" }, el("div", null, c.util, c.sub), c.spark),
        el("div", { class: "bar" }, c.bar), c.state));
      series[s.id] = series[s.id] || [];
    });
    redrawAllSparks();
  }

  function drawSpark(canvas, data) {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h || data.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = w * dpr; canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
    const css = getComputedStyle(document.documentElement);
    const hot = data[data.length - 1] > 0.8;
    const color = (hot ? css.getPropertyValue("--neg") : css.getPropertyValue("--pos")).trim();
    const x = (i) => (i / (data.length - 1)) * (w - 6) + 3, y = (v) => h - 4 - v * (h - 8);
    ctx.beginPath(); data.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
    ctx.lineJoin = "round"; ctx.lineWidth = 2; ctx.strokeStyle = color; ctx.stroke();
    ctx.lineTo(x(data.length - 1), h); ctx.lineTo(x(0), h); ctx.closePath();
    const g = ctx.createLinearGradient(0, 0, 0, h); g.addColorStop(0, color + "33"); g.addColorStop(1, color + "00");
    ctx.fillStyle = g; ctx.fill();
    ctx.beginPath(); ctx.arc(x(data.length - 1), y(data[data.length - 1]), 3.2, 0, 7); ctx.fillStyle = color; ctx.fill();
  }
  const redrawAllSparks = () => Object.keys(cards).forEach((id) => drawSpark(cards[id].spark, series[id] || []));
  window.addEventListener("resize", redrawAllSparks);

  function onTelemetry(d) {
    const s = (series[d.slice_id] = series[d.slice_id] || []);
    s.push(d.utilization); if (s.length > 48) s.shift();
    const c = cards[d.slice_id]; if (!c) return;
    const hot = d.utilization > 0.8;
    c.util.textContent = pct(d.utilization); c.util.classList.toggle("hot", hot);
    c.sub.textContent = `${num(d.throughput_mbps)} / ${num(d.capacity_mbps)} Mbps · ${d.latency_ms} ms`;
    c.bar.style.width = pct(d.utilization); c.bar.classList.toggle("hot", hot);
    drawSpark(c.spark, s);
  }

  const ACTION_TEXT = { LIST_ASK: "Listing idle capacity", POST_BID: "Bidding for burst capacity", REFUSE_SLA: "SLA gate: refusing to list", NO_SURPLUS: "No safe surplus", NEGOTIATED: "Negotiated a deal", NO_DEMAND: "No burst needed" };

  function onDecision(d, isReplay) {
    const feed = $("#decision-feed");
    if (feed.firstChild && feed.firstChild.classList && feed.firstChild.classList.contains("empty")) feed.replaceChildren();
    const price = d.price ? ` @ ${usd(d.price, 4)}` : "";
    const row = el("div", { class: "decision" + (isReplay ? "" : " flash") },
      el("div", { class: "decision-top" },
        el("span", { class: "action-chip " + d.action, text: (ACTION_TEXT[d.action] || d.action).toUpperCase() }),
        el("strong", { text: d.enterprise }), el("span", { class: "muted small", text: d.role }),
        d.quantity_mbps ? el("span", { class: "small", text: `${num(d.quantity_mbps, 1)} Mbps${price}` }) : null,
        d.matched ? el("span", { class: "action-chip POST_BID", text: "MATCHED" }) : null,
        el("span", { class: "decision-time", text: clock(new Date().toISOString()) })),
      el("div", { class: "decision-reason", text: d.reason }));
    feed.prepend(row);
    while (feed.children.length > feedMax) feed.lastChild.remove();
    const c = cards[d.slice_id];
    if (c) {
      const cls = d.action === "LIST_ASK" ? "ask" : d.action === "POST_BID" ? "bid" : d.action === "REFUSE_SLA" ? "refuse" : "";
      c.state.className = "slice-state " + cls;
      c.state.textContent = d.quantity_mbps ? `${ACTION_TEXT[d.action]} · ${num(d.quantity_mbps)} Mbps${price}` : ACTION_TEXT[d.action] || d.action;
    }
  }

  let lastManual = null;   // remember a human-submitted order so we can celebrate when the engine matches it
  function onTrade(t, isReplay) {
    const feed = $("#trade-ticker");
    if (feed.firstChild && feed.firstChild.classList && feed.firstChild.classList.contains("empty")) feed.replaceChildren();
    const row = el("div", { class: "tick" + (isReplay ? "" : " flash") },
      el("div", { class: "tick-main" },
        el("div", null, el("span", { class: "tick-qty", text: `${num(t.quantity_mbps, 1)} Mbps` }), el("span", { class: "muted", text: `  ${shortSlice(t.seller_slice_id)} → ${shortSlice(t.buyer_slice_id)}` })),
        el("div", { class: "mono", text: `${t.trade_id} · ${clock(t.timestamp)}` })),
      el("div", null, el("div", { class: "tick-price", text: usd(t.price, 4) + "/Mbps" }), el("div", { class: "muted small num", text: usd(t.gross_amount, 2) + " gross" })));
    feed.prepend(row);
    while (feed.children.length > feedMax) feed.lastChild.remove();
    if (!isReplay && lastManual && (t.buyer_slice_id === lastManual.slice || t.seller_slice_id === lastManual.slice)) {
      $("#order-msg").textContent = `✓ Matched autonomously: ${num(t.quantity_mbps, 1)} Mbps at ${usd(t.price, 4)} (trade ${t.trade_id}).`;
      lastManual = null; pollBook();
    }
  }

  // ---- event stream: WebSocket first, polling fallback ----
  const lastId = {};
  let ws = null, retry = 0, wsFailures = 0, pollTimer = null;
  const wsBadge = $("#ws-status");
  const setWs = (text, cls) => { wsBadge.textContent = text; wsBadge.className = "badge " + cls; };

  function dispatch(evt, isReplay) {
    if (!evt || !evt.topic || evt.topic === "hello") return;
    if (evt.id <= (lastId[evt.topic] || 0)) return;   // de-dupe replays and overlapping polls
    lastId[evt.topic] = evt.id;
    if (evt.topic === "telemetry.raw") onTelemetry(evt.data);
    else if (evt.topic === "agent.decision") onDecision(evt.data, isReplay);
    else if (evt.topic === "trade.executed") onTrade(evt.data, isReplay);
  }

  function connectWs() {
    setWs(retry ? "reconnecting…" : "connecting…", "badge-warn");
    try { ws = new WebSocket(WS_URL); } catch (e) { return scheduleReconnect(); }
    let replaying = true;
    ws.onopen = () => {
      retry = 0; wsFailures = 0; setSvc("ai", true); stopPolling();
      setWs("live · WebSocket", "badge-ok");
      Object.keys(lastId).forEach((k) => delete lastId[k]);                 // server may have restarted: accept its ids afresh
      $("#decision-feed").replaceChildren(); $("#trade-ticker").replaceChildren();
      Object.keys(series).forEach((k) => (series[k] = []));
      setTimeout(() => (replaying = false), 1200);                          // the server replays recent history right after connect
    };
    ws.onmessage = (m) => { try { dispatch(JSON.parse(m.data), replaying); } catch (e) { /* ignore malformed frame */ } };
    ws.onclose = () => scheduleReconnect();
    ws.onerror = () => { try { ws.close(); } catch (e) { /* noop */ } };
  }
  function scheduleReconnect() {
    if (ws) { ws.onclose = null; ws = null; }
    wsFailures++;
    setWs(wsFailures >= 3 ? "polling · WebSocket unavailable" : "reconnecting…", "badge-warn");
    if (wsFailures >= 3) startPolling();
    setTimeout(connectWs, Math.min(1000 * Math.pow(2, retry++), 8000));
  }
  function startPolling() { if (!pollTimer) { pollEvents(); pollTimer = setInterval(pollEvents, 2000); } }
  function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
  async function pollEvents() {
    for (const topic of ["telemetry.raw", "agent.decision", "trade.executed"]) {
      try {
        const evts = await api(AI, `/events/${topic}?limit=100&after=${lastId[topic] || 0}`);
        evts.forEach((e) => dispatch(e, !lastId[topic]));
      } catch (e) { setWs("AI engine unreachable · retrying", "badge-bad"); return; }
    }
  }

  // ================================================================ PANEL 3: ORDER BOOK
  async function pollBook() {
    try { renderBook(await api(AI, "/orderbook")); } catch (e) { /* dot shows outage */ }
  }

  function renderBook(book) {
    const maxQty = Math.max(1, ...book.bids.map((o) => o.quantity_mbps), ...book.asks.map((o) => o.quantity_mbps));
    const cancel = (o) => o.source === "manual" ? el("span", null, el("span", { class: "src-manual", text: "YOU" }), " ",
      el("button", { class: "btn ghost tiny", title: "Cancel order", onclick: async () => { try { await api(AI, "/orderbook/orders/" + o.id, { method: "DELETE" }); pollBook(); } catch (e) { /* ignore */ } }, text: "cancel" })) : null;
    const bar = (o) => `--w:${Math.max(6, (o.quantity_mbps / maxQty) * 100)}%`;
    const empty = (cols, txt) => el("tr", null, el("td", { colspan: cols, class: "empty", text: txt }));
    $("#bids-body").replaceChildren(...(book.bids.length ? book.bids.slice(0, 12).map((o) => el("tr", null,
      el("td", { class: "num depthbar", style: bar(o), text: num(o.quantity_mbps, 1) }),
      el("td", null, sliceName(o.slice_id), cancel(o)), el("td", { class: "num price", text: usd(o.price, 4) }))) : [empty(3, "No bids resting")]));
    $("#asks-body").replaceChildren(...(book.asks.length ? book.asks.slice(0, 12).map((o) => el("tr", null,
      el("td", { class: "num price", text: usd(o.price, 4) }), el("td", null, sliceName(o.slice_id), cancel(o)),
      el("td", { class: "num depthbar", style: bar(o), text: num(o.quantity_mbps, 1) }))) : [empty(3, "No asks resting")]));
    const sp = $("#book-spread");
    if (book.bids.length && book.asks.length) {
      const d = book.asks[0].price - book.bids[0].price;
      sp.textContent = d > 0 ? `Spread ${usd(d, 4)}` : "Crossed — clearing on the next tick";
      sp.className = "badge " + (d > 0 ? "badge-muted" : "badge-ok");
    } else { sp.textContent = `${book.bids.length} bids · ${book.asks.length} asks`; sp.className = "badge badge-muted"; }
  }

  $("#order-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const msg = $("#order-msg");
    const body = { slice_id: $("#order-slice").value, side: $("#order-side").value, price: parseFloat($("#order-price").value), quantity_mbps: parseFloat($("#order-qty").value) };
    try {
      const o = await api(AI, "/orderbook/orders", { method: "POST", body });
      lastManual = { slice: o.slice_id, id: o.id };
      msg.textContent = `Order ${o.id} is resting in the book. The autonomous engine sweeps for matches every ~8 seconds…`;
      pollBook();
    } catch (e) { msg.textContent = "Could not submit: " + e.message; }
  });

  // ================================================================ PANEL 4: NEGOTIATION
  $("#neg-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const btn = $("#neg-run"), msg = $("#neg-msg");
    const seller = $("#neg-seller").value, buyer = $("#neg-buyer").value;
    if (seller === buyer) { msg.textContent = "Pick two different slices."; return; }
    const qty = parseFloat($("#neg-qty").value);
    btn.disabled = true; msg.textContent = "Agents are forecasting and pricing…";
    try {
      const r = await api(AI, "/agent/negotiate", { method: "POST", body: { seller_slice_id: seller, buyer_slice_id: buyer, quantity_mbps: qty > 0 ? qty : null, execute: $("#neg-exec").checked } });
      msg.textContent = "";
      await playNegotiation(r);
    } catch (e) { msg.textContent = "Negotiation failed: " + e.message; }
    btn.disabled = false;
  });

  async function playNegotiation(r) {
    const prices = r.rounds.flatMap((x) => [x.seller_ask, x.buyer_bid]);
    const span = Math.max(...prices) - Math.min(...prices) || Math.max(...prices) * 0.2;
    const lo = Math.min(...prices) - span * 0.12, hi = Math.max(...prices) + span * 0.12;   // zoom on where the haggling happens
    const pos = (p) => ((p - lo) / (hi - lo)) * 100 + "%";
    const mk = { ask: $("#mk-ask"), bid: $("#mk-bid"), deal: $("#mk-deal") };
    Object.values(mk).forEach((m) => m.classList.remove("show"));
    $("#neg-body").replaceChildren(); $("#neg-notes").textContent = "";
    const out = $("#neg-outcome"); out.className = "neg-outcome muted"; out.textContent = `Negotiating ${num(r.quantity_mbps, 0)} Mbps…`;
    const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
    for (const x of r.rounds) {
      mk.ask.style.left = pos(x.seller_ask); mk.bid.style.left = pos(x.buyer_bid);
      mk.ask.firstChild.textContent = usd(x.seller_ask, 4); mk.bid.firstChild.textContent = usd(x.buyer_bid, 4);
      mk.ask.classList.add("show"); mk.bid.classList.add("show");
      $("#neg-body").append(el("tr", { class: "flash" }, el("td", { text: x.round === 0 ? "Open" : "Round " + x.round }),
        el("td", { class: "num ask-text", text: usd(x.seller_ask, 4) }), el("td", { class: "num bid-text", text: usd(x.buyer_bid, 4) }),
        el("td", { class: "num", text: usd(Math.max(0, x.gap), 4) }), el("td", { class: "muted", text: x.note })));
      await sleep(950);
    }
    if (r.outcome === "deal") {
      mk.deal.style.left = pos(r.agreed_price); mk.deal.firstChild.textContent = usd(r.agreed_price, 4); mk.deal.classList.add("show");
      out.className = "neg-outcome deal";
      out.textContent = `Deal at ${usd(r.agreed_price, 4)} per Mbps · ${usd(r.agreed_price * r.quantity_mbps, 2)} for ${num(r.quantity_mbps, 0)} Mbps` + (r.trade ? ` · settled as ${r.trade.trade_id}` : "");
    } else { out.className = "neg-outcome nodeal"; out.textContent = "No deal — the agents' reservation prices do not overlap."; }
    $("#neg-notes").textContent = (r.notes || []).join(" ");
  }

  // ================================================================ boot
  loadSlices();
  connectWs();
  pollLedger(); pollIntegrity(); pollBook();
  setInterval(pollLedger, 3000);
  setInterval(() => { pollIntegrity(); if (lookupSlice) doLookup(); }, 8000);
  setInterval(pollBook, 3000);
})();
