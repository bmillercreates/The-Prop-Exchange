// The Prop Exchange: renders site/data.json (built by scripts/build_site.py)

const MARKET = {
  player_pass_yds: { short: "Pass Yds", tick: "PASS" },
  player_rush_yds: { short: "Rush Yds", tick: "RUSH" },
  player_reception_yds: { short: "Rec Yds", tick: "REC" },
  player_receptions: { short: "Receptions", tick: "CATCH" },
  player_anytime_td: { short: "Anytime TD", tick: "TD" },
};
const BOOKS = { draftkings: "DraftKings", fanduel: "FanDuel" };
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, digits = 1) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(digits)}%`;
const money = (p) => (p > 0 ? `+${p}` : `${p}`);
const isUnder = (p) => p.side === "Under";

function kickoffText(iso) {
  // kickoff is Eastern time without an offset, e.g. "2026-10-29T20:15"
  const [d, t] = iso.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const [hh, mm] = t.split(":").map(Number);
  const dow = DAYS[new Date(Date.UTC(y, m - 1, day)).getUTCDay()];
  const h12 = ((hh + 11) % 12) + 1;
  return `${dow} ${m}/${day} · ${h12}:${String(mm).padStart(2, "0")} ${hh < 12 ? "AM" : "PM"} ET`;
}

function nowEasternIso() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date());
  const get = (k) => parts.find((p) => p.type === k).value;
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

function sideBadge(p) {
  if (p.side === "Yes") return `<span class="side over">▲ TD</span>`;
  return isUnder(p) ? `<span class="side under">▼ UNDER</span>` : `<span class="side over">▲ OVER</span>`;
}

function lineText(p) {
  const m = MARKET[p.market]?.short ?? p.label;
  if (p.line == null) return m;
  return `${isUnder(p) ? "u" : "o"}${p.line} ${m}`;
}

function pickCard(p, game, data) {
  const node = $("#pick-tpl").content.firstElementChild.cloneNode(true);
  const side = node.querySelector(".side");
  side.outerHTML = sideBadge(p);
  node.querySelector(".pick-title").innerHTML = `${esc(p.player)} <span class="muted">${esc(lineText(p))}</span>`;
  const opp = game.away === p.team ? game.home : game.away;
  node.querySelector(".pick-sub").textContent =
    `${p.team} ${p.position} vs ${opp} · ${kickoffText(game.kickoff)} · ${game.status}`;
  const edge = node.querySelector(".edge");
  edge.textContent = pct(p.edge);
  edge.classList.add(isUnder(p) ? "down" : "up");
  node.querySelector(".price").textContent = `${money(p.price)} ${BOOKS[p.book] ?? p.book} · model ${Math.round(p.model_prob * 100)}% vs book ${Math.round(p.fair_prob * 100)}%`;
  const bar = node.querySelector(".probbar");
  if (isUnder(p)) bar.classList.add("under-bar");
  bar.querySelector(".model").style.width = `${p.model_prob * 100}%`;
  bar.querySelector(".book").style.width = `${p.fair_prob * 100}%`;
  bar.title = `Model ${Math.round(p.model_prob * 100)}% vs book ${Math.round(p.fair_prob * 100)}%`;
  node.querySelector(".why ul").innerHTML = p.why.map((w) => `<li>${esc(w)}</li>`).join("");
  return node;
}

function etfCard(e, game) {
  const div = document.createElement("article");
  div.className = "etf";
  div.innerHTML = `
    <div class="etf-head">
      <div>
        <div class="pick-title">${esc(game.away)} @ ${esc(game.home)} bundle</div>
        <div class="pick-sub muted">${kickoffText(game.kickoff)} · ${game.status} · model ${Math.round(e.model_prob * 100)}% to hit</div>
      </div>
      <div class="pick-nums">
        <div class="edge mono up">${pct(e.edge)}</div>
        <div class="price mono muted">about ${money(e.price)}</div>
      </div>
    </div>
    <div class="etf-legs">
      ${e.legs.map((l) => `<div class="etf-leg">${sideBadge(l)}<span><b>${esc(l.player)}</b> <span class="muted">${esc(lineText(l))}</span></span></div>`).join("")}
    </div>
    <details class="why"><summary>Why</summary><ul>${e.why.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>`;
  return div;
}

function fillList(el, items, empty) {
  el.innerHTML = "";
  if (!items.length) {
    el.innerHTML = `<div class="panel empty">${empty}</div>`;
    return;
  }
  items.forEach((n) => el.appendChild(n));
}

function weatherText(w) {
  if (!w || (!w.covered && w.wind_mph == null)) return "Forecast pending";
  if (w.covered) return "Indoors";
  let s = `${w.temp_f}°F · wind ${w.wind_mph} mph`;
  if (w.precip_chance >= 40) s += ` · ${w.precip_chance}% rain/snow`;
  return s;
}

function gameCard(g, data) {
  const T = data.teams;
  const div = document.createElement("article");
  div.className = "game";
  div.id = `game-${g.game_id}`;
  const fav = Object.entries(g.teams).find(([, t]) => t.margin > 0);
  const spread = fav ? `${fav[0]} −${fav[1].margin}` : "Pick'em";
  const total = Object.values(g.teams).reduce((s, t) => s + t.implied_pts, 0);
  const status = g.status === "FINAL" ? `<span class="pill pill-final">FINAL</span>` : `<span class="pill pill-prelim">PRELIMINARY</span>`;

  const picks = [
    ...g.blue_chips.map((p) => ({ ...p, tierName: "Blue Chip" })),
    ...g.penny_stocks.map((p) => ({ ...p, tierName: "Penny Stock" })),
  ];
  let body = "";
  if (!g.has_props) {
    body += `<div class="note">Prop lines open the morning of game day. Here's what the model projects so far:</div>`;
  } else if (!picks.length && !g.etfs.length) {
    body += `<div class="note">No pick cleared the bar for this game. Sitting out is a position too.</div>`;
  }
  body += picks.map((p) => `
    <div class="mini">
      ${sideBadge(p)}
      <span><b>${esc(p.player)}</b> <span class="muted">${esc(lineText(p))}</span><br><span class="tier">${p.tierName}</span></span>
      <span class="mono muted">${money(p.price)}</span>
      <span class="mono ${isUnder(p) ? "down" : "up"}"><b>${pct(p.edge)}</b></span>
    </div>`).join("");
  body += g.etfs.map((e) => `
    <div class="mini">
      <span class="side over">▲ ETF</span>
      <span>${e.legs.map((l) => `<b>${esc(l.player)}</b> <span class="muted">${esc(lineText(l))}</span>`).join(" + ")}</span>
      <span class="mono muted">${money(e.price)}</span>
      <span class="mono up"><b>${pct(e.edge)}</b></span>
    </div>`).join("");

  if (!g.has_props && g.projections.length) {
    const rows = g.projections.map((p) => {
      const main = p.position === "QB" ? `${Math.round(p.pass_yds)} pass` :
        p.position === "RB" ? `${Math.round(p.rush_yds)} rush` : `${Math.round(p.rec_yds ?? 0)} rec`;
      const second = p.position === "QB" ? `${Math.round(p.rush_yds)} rush` :
        p.position === "RB" ? `${Math.round(p.rec_yds ?? 0)} rec` : `${(p.receptions ?? 0).toFixed(1)} catches`;
      return `<tr><td>${esc(p.player)} <span class="muted">${p.team} ${p.position}</span></td><td class="num">${main}</td><td class="num muted also">${second}</td><td class="num muted">${Math.round((1 - Math.exp(-p.tds)) * 100)}% TD</td></tr>`;
    }).join("");
    body += `<table class="proj"><thead><tr><th>Player</th><th class="num">Yards</th><th class="num also">Also</th><th class="num">TD</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  div.innerHTML = `
    <div class="game-head">
      <div class="matchup">
        <div class="teams">
          <span class="dot" style="background:${T[g.away]?.color ?? "#888"}"></span>${esc(g.away)}
          <span class="at">@</span>
          <span class="dot" style="background:${T[g.home]?.color ?? "#888"}"></span>${esc(g.home)}
        </div>
        ${status}
      </div>
      <div class="meta">
        <span>${kickoffText(g.kickoff)}</span>
        <span>${esc(g.stadium)}</span>
      </div>
      <div class="meta">
        <span>Spread <b class="mono">${spread}</b></span>
        <span>Total <b class="mono">${total.toFixed(1)}</b></span>
        <span>Proj. <b class="mono">${g.away} ${g.teams[g.away].implied_pts} · ${g.home} ${g.teams[g.home].implied_pts}</b></span>
        <span>${weatherText(g.weather)}</span>
      </div>
    </div>
    <div class="game-body">${body}</div>`;
  return div;
}

function render(data) {
  const games = data.games;
  const now = nowEasternIso();
  const upcoming = games.filter((g) => g.kickoff > now);
  const all = (key) => games.flatMap((g) => g[key].map((p) => ({ p, g })));
  const blue = all("blue_chips").sort((a, b) => b.p.edge - a.p.edge);
  const penny = all("penny_stocks").sort((a, b) => b.p.edge - a.p.edge);
  const etfs = all("etfs").sort((a, b) => b.p.edge - a.p.edge);

  $("#headline").textContent = `NFL Week ${data.week ?? "—"}`;
  const gameDay = upcoming.some((g) => g.kickoff.slice(0, 10) === now.slice(0, 10));
  const ms = $("#market-status");
  ms.className = `pill ${gameDay ? "pill-live" : "pill-muted"}`;
  ms.textContent = gameDay ? "GAME DAY" : upcoming.length ? "PRE-MARKET" : "MARKET CLOSED";
  const upd = new Date(data.generated_at);
  $("#updated").textContent = `Updated ${upd.toLocaleString("en-US", { timeZone: "America/New_York", weekday: "short", hour: "numeric", minute: "2-digit" })} ET`;

  const avgEdge = blue.length ? blue.reduce((s, x) => s + x.p.edge, 0) / blue.length : 0;
  const overs = [...blue, ...penny].filter((x) => !isUnder(x.p)).length;
  const finals = games.filter((g) => g.status === "FINAL").length;
  $("#tiles").innerHTML = [
    ["Blue Chips", blue.length, blue.length ? `avg edge <span class="up">${pct(avgEdge)}</span>` : "lines open on game day"],
    ["Penny Stocks", penny.length, "plus-money upside"],
    ["ETFs", etfs.length, "correlated bundles"],
    ["Games", games.length, `${games.filter((g) => g.has_props).length} with lines · ${finals} final`],
  ].map(([l, v, s]) => `<div class="tile"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${s}</div></div>`).join("");

  fillList($("#blue-list"), blue.map(({ p, g }) => pickCard(p, g, data)), "No Blue Chips yet. Picks post on the morning of each game day.");
  fillList($("#penny-list"), penny.map(({ p, g }) => pickCard(p, g, data)), "No Penny Stocks right now.");
  fillList($("#etf-list"), etfs.map(({ p, g }) => etfCard(p, g)), "No ETF cleared the bar right now.");
  fillList($("#games"), games.map((g) => gameCard(g, data)), "No games on the board.");

  const tick = [...blue, ...penny].map(({ p }) => {
    const last = p.player.split(" ").slice(-1)[0].toUpperCase();
    const cls = isUnder(p) ? "down" : "up";
    const arrow = isUnder(p) ? "▼" : "▲";
    const line = p.line != null ? `${isUnder(p) ? "u" : "o"}${p.line}` : "";
    return `<span class="ticker-item"><b>${esc(last)}</b> ${MARKET[p.market]?.tick ?? ""} ${line} <span class="${cls}">${arrow} ${pct(p.edge)}</span></span>`;
  });
  const scores = games.map((g) => `<span class="ticker-item"><b>${g.away}</b> ${g.teams[g.away].implied_pts} <span class="muted">@</span> <b>${g.home}</b> ${g.teams[g.home].implied_pts}</span>`);
  // the strip is written twice so the scroll loops without a gap
  const strip = [...tick, ...scores].join("");
  $("#ticker-track").innerHTML = strip + strip;

  renderPortfolio(data.portfolio);
  renderStorylines(data);
}

// ---------- Portfolio Performance ----------

const units = (u) => `${u >= 0 ? "+" : "−"}${Math.abs(u).toFixed(2)}u`;
const record = (b) => `${b.wins}-${b.losses}${b.pushes ? `-${b.pushes}` : ""}`;

function curveChart(curve) {
  // Single series: cumulative units won over time. One y-axis, zero line dashed.
  const W = 800, H = 200, L = 44, R = 12, T = 10, B = 24;
  const pts = [{ date: "start", units: 0 }, ...curve];
  const ys = pts.map((p) => p.units);
  let lo = Math.min(0, ...ys), hi = Math.max(0, ...ys);
  if (hi - lo < 2) { hi += 1; lo -= 1; }
  const x = (i) => L + (i / Math.max(pts.length - 1, 1)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const step = Math.max(1, Math.ceil((hi - lo) / 4));
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) ticks.push(v);
  const last = ys[ys.length - 1];
  const path = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.units).toFixed(1)}`).join("");
  const label = (d) => (d === "start" ? "Start" : new Date(d + "T12:00").toLocaleDateString("en-US", { month: "short", day: "numeric" }));
  const xlabels = pts.length <= 8 ? pts.map((p, i) => i) : [0, Math.floor((pts.length - 1) / 2), pts.length - 1];
  return `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative units won: ${units(last)}">
      <g class="grid">${ticks.map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`).join("")}</g>
      <g class="axis">${ticks.map((v) => `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v > 0 ? "+" : ""}${v}u</text>`).join("")}
        ${xlabels.map((i) => `<text x="${x(i)}" y="${H - 4}" text-anchor="${i === 0 ? "start" : i === pts.length - 1 ? "end" : "middle"}">${label(pts[i].date)}</text>`).join("")}</g>
      <line class="zero" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>
      <path class="line ${last < 0 ? "neg" : ""}" d="${path}" vector-effect="non-scaling-stroke"/>
      <line class="cross" id="pf-cross" y1="${T}" y2="${H - B}" x1="-10" x2="-10" vector-effect="non-scaling-stroke"/>
      <rect class="hit" x="${L}" y="0" width="${W - L - R}" height="${H}"/>
    </svg>`;
}

function wireChartHover(panel, curve) {
  const svg = panel.querySelector("svg");
  const tip = panel.querySelector(".tip");
  const cross = panel.querySelector("#pf-cross");
  const pts = [{ date: "start", units: 0 }, ...curve];
  const W = 800, L = 44, R = 12;
  svg.addEventListener("pointermove", (ev) => {
    const box = svg.getBoundingClientRect();
    const fx = ((ev.clientX - box.left) / box.width) * W;
    const i = Math.round(((fx - L) / (W - L - R)) * (pts.length - 1));
    if (i < 0 || i >= pts.length) return;
    const px = L + (i / Math.max(pts.length - 1, 1)) * (W - L - R);
    cross.setAttribute("x1", px); cross.setAttribute("x2", px);
    const p = pts[i];
    const day = p.date === "start" ? "Start" : new Date(p.date + "T12:00").toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    tip.innerHTML = `${day}<br><b class="${p.units < 0 ? "down" : "up"}">${units(p.units)}</b> total`;
    tip.style.left = `${(px / W) * box.width + 14}px`;
    tip.style.top = `${ev.clientY - panel.getBoundingClientRect().top}px`;
    tip.hidden = false;
  });
  svg.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("x1", -10); cross.setAttribute("x2", -10); });
}

function renderPortfolio(pf) {
  const el = $("#portfolio-body");
  if (!pf || !pf.overall.bets) {
    el.innerHTML = `<div class="panel empty">Tracking starts after the first graded games. Picks are graded automatically once each game ends.</div>`;
    return;
  }
  const o = pf.overall;
  const roiCls = (v) => (v == null ? "" : v >= 0 ? "up" : "down");
  const tiles = [
    ["Record", record(o), `${o.bets} graded bets`],
    ["Units", `<span class="${roiCls(o.units)}">${units(o.units)}</span>`, "1 unit staked per pick"],
    ["ROI", `<span class="${roiCls(o.roi)}">${pct(o.roi)}</span>`, "return per unit risked"],
    ["Hit rate", o.hit_rate == null ? "—" : `${Math.round(o.hit_rate * 100)}%`, "wins ÷ (wins + losses)"],
  ].map(([l, v, sub]) => `<div class="tile"><div class="label">${l}</div><div class="value">${v}</div><div class="sub">${sub}</div></div>`).join("");

  const tierRows = Object.entries(pf.tiers).map(([t, b]) => `
    <tr><td><b>${t}s</b></td><td class="num">${b.bets ? record(b) : "—"}</td>
    <td class="num ${roiCls(b.units)}">${b.bets ? units(b.units) : "—"}</td>
    <td class="num ${roiCls(b.roi)}">${b.roi == null ? "—" : pct(b.roi)}</td>
    <td class="num hide-sm">${b.hit_rate == null ? "—" : Math.round(b.hit_rate * 100) + "%"}</td></tr>`).join("");

  const recent = pf.recent.slice(0, 12).map((r) => {
    const actual = Array.isArray(r.actual) ? r.actual.join(" / ") : r.actual ?? "DNP";
    return `<tr>
      <td class="hide-sm muted">${new Date(r.kickoff.slice(0, 10) + "T12:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}</td>
      <td>${esc(r.title)}<br><span class="muted" style="font-size:12px">${r.tier} · ${esc(r.matchup)} · actual ${esc(actual)}</span></td>
      <td class="num muted">${money(r.price)}</td>
      <td class="num"><span class="res ${r.result}">${r.result.toUpperCase()}</span></td>
      <td class="num ${r.units > 0 ? "up" : r.units < 0 ? "down" : "muted"}">${units(r.units)}</td></tr>`;
  }).join("");

  el.innerHTML = `
    <div class="pf-grid">
      <div class="tiles">${tiles}</div>
      <div class="chart-panel">
        <div class="chart-title"><span>Portfolio value: units won over time</span><b class="${roiCls(o.units)}">${units(o.units)}</b></div>
        <div class="chart">${curveChart(pf.curve)}</div>
        <div class="tip" hidden></div>
      </div>
      <div class="table-wrap"><table class="tbl">
        <thead><tr><th>Tier</th><th class="num">Record</th><th class="num">Units</th><th class="num">ROI</th><th class="num hide-sm">Hit rate</th></tr></thead>
        <tbody>${tierRows}</tbody></table></div>
      <div class="table-wrap"><table class="tbl">
        <thead><tr><th class="hide-sm">Date</th><th>Recent picks</th><th class="num">Price</th><th class="num">Result</th><th class="num">Units</th></tr></thead>
        <tbody>${recent}</tbody></table></div>
    </div>`;
  wireChartHover(el.querySelector(".chart-panel"), pf.curve);
}

// ---------- Storylines ----------

function renderStorylines(data) {
  const el = $("#storylines-body");
  const blocks = data.games.map((g) => {
    const items = data.storylines?.[g.game_id] ?? [];
    if (!items.length) return "";
    return `<div class="story-game"><h3>${esc(g.away)} @ ${esc(g.home)} <span class="muted" style="font-weight:500">· ${kickoffText(g.kickoff)}</span></h3>
      ${items.map((s) => `<div class="story"><span class="tag ${s.type.toLowerCase()}">${s.type.toUpperCase()}</span><span>${esc(s.text)}</span></div>`).join("")}</div>`;
  }).filter(Boolean);
  el.innerHTML = blocks.length ? blocks.join("") : `<div class="panel empty">No storylines this week.</div>`;
}

fetch(`data.json?v=${Date.now()}`)
  .then((r) => r.json())
  .then(render)
  .catch((err) => {
    $("#market-status").textContent = "OFFLINE";
    $("#games").innerHTML = `<div class="panel empty">Couldn't load the picks (${esc(err.message)}).</div>`;
  });
