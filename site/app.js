/* GOAT Hockey: a small single-page site. No build step, no libraries.
   Pages: #/ (home), #/games, #/goalies, #/skaters, #/teams, #/about        */
(function () {
  "use strict";

  var main = document.getElementById("main");
  var tip = document.getElementById("tip");
  var cache = {};
  var meta = null;
  var state = { season: null, type: "regular", tables: {} };

  // ------------------------------------------------------------ helpers --
  function el(tag, attrs, kids) {
    var n = document.createElementNS(
      /^(svg|path|circle|line|rect|g|text|polyline)$/.test(tag) ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml", tag);
    for (var k in attrs || {}) {
      if (attrs[k] == null || attrs[k] === false) continue;
      if (k === "text") n.textContent = attrs[k];
      else if (k === "html") n.innerHTML = attrs[k];
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
      else n.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function load(name) {
    if (cache[name]) return cache[name];
    var inline = window.__DATA__ && window.__DATA__[name];
    cache[name] = inline !== undefined ? Promise.resolve(inline)
      : fetch("data/" + name + ".json", { cache: "no-cache" })
          .then(function (r) { if (!r.ok) throw new Error(name + " " + r.status); return r.json(); });
    cache[name].catch(function () { delete cache[name]; });
    return cache[name];
  }

  var MINUS = "−";
  var F = {
    int: function (v) { return v == null ? "" : Math.round(v).toLocaleString("en-US"); },
    d1: function (v) { return v == null ? "" : v.toFixed(1).replace("-", MINUS); },
    d2: function (v) { return v == null ? "" : v.toFixed(2).replace("-", MINUS); },
    pct: function (v) { return v == null ? "" : v.toFixed(1); },
    sv: function (v) { return v == null ? "" : v.toFixed(3).replace(/^0/, ""); },
    s1: function (v) { return v == null ? "" : (v > 0 ? "+" : "") + v.toFixed(1).replace("-", MINUS); },
    s2: function (v) { return v == null ? "" : (v > 0 ? "+" : "") + v.toFixed(2).replace("-", MINUS); },
    txt: function (v) { return v == null ? "" : String(v); }
  };
  function niceDate(iso, withYear) {
    if (!iso) return "";
    var p = iso.split("-"), m = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+p[1] - 1];
    return m + " " + (+p[2]) + (withYear ? ", " + p[0] : "");
  }
  function seasonInfo(id) { return meta.seasons.filter(function (s) { return s.id === id; })[0]; }
  function typeInfo(season, type) { var s = seasonInfo(season); return s && s.types.filter(function (t) { return t.id === type; })[0]; }

  // ------------------------------------------------------------ tooltip --
  function showTip(html, x, y) {
    tip.innerHTML = html; tip.hidden = false;
    var w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(6, Math.min(window.innerWidth - w - 6, x + 12)) + "px";
    tip.style.top = (y + h + 24 > window.innerHeight ? y - h - 10 : y + 14) + "px";
  }
  function hideTip() { tip.hidden = true; }

  // ------------------------------------------------------- column specs --
  // key, header, plain-English meaning, formatter, options
  var COLS = {
    goalies: [
      ["name", "Goalie", "", F.txt, { name: 1, link: 1 }],
      ["team", "Team", "Most recent team first", F.txt, { left: 1 }],
      ["gp", "GP", "Games played", F.int],
      ["w", "W", "Wins", F.int],
      ["sa", "SA", "Shots on goal against", F.int],
      ["ga", "GA", "Goals against (empty-net goals are not counted)", F.int],
      ["sv", "Sv%", "Save percentage: saves divided by shots on goal", F.sv],
      ["xga", "xGA", "Expected goals against: how many goals an average goalie would allow on the same shots", F.d1, { grp: 1 }],
      ["gsax", "GSAx", "Goals saved above expected: xGA minus goals against. Positive means better than average", F.s1, { bar: 1 }],
      ["gsax60", "GSAx/60", "Goals saved above expected per 60 minutes played", F.s2, { sign: 1 }],
      ["gsax100", "GSAx/100", "Goals saved above expected per 100 unblocked shots faced", F.s2, { sign: 1 }],
      ["hd_sa", "HD SA", "High-danger shots on goal faced (chances worth 15% or more)", F.int, { grp: 1 }],
      ["hd_sv", "HD Sv%", "Save percentage on high-danger shots", F.sv],
      ["hd_gsax", "HD GSAx", "Goals saved above expected on high-danger shots", F.s1, { sign: 1 }],
      ["gsax_5v5", "5v5 GSAx", "Goals saved above expected at five-on-five", F.s1, { sign: 1 }]
    ],
    skaters: [
      ["name", "Skater", "", F.txt, { name: 1, link: 1 }],
      ["team", "Team", "Most recent team first", F.txt, { left: 1 }],
      ["pos", "Pos", "Forward or defenseman", F.txt, { left: 1 }],
      ["gp", "GP", "Games played", F.int],
      ["toi_gp", "TOI/GP", "Average ice time per game, in minutes", F.d1],
      ["g", "G", "Goals", F.int, { grp: 1 }],
      ["a1", "A1", "Primary assists (the last pass before the goal)", F.int],
      ["a2", "A2", "Secondary assists", F.int],
      ["p", "P", "Points", F.int],
      ["sog", "SOG", "Shots on goal", F.int, { grp: 1 }],
      ["ixg", "ixG", "Individual expected goals: the goals an average shooter would score on this player's shots", F.d1],
      ["gax", "G−xG", "Goals above expected: goals minus ixG. Positive means finishing better than the chances suggest", F.s1, { bar: 1 }],
      ["sh_pct", "Sh%", "Shooting percentage: goals divided by shots on goal", F.pct],
      ["hd", "HD", "High-danger shot attempts (chances worth 15% or more)", F.int],
      ["ixg60", "ixG/60", "Individual expected goals per 60 minutes of ice time", F.d2, { grp: 1 }],
      ["p60", "P/60", "Points per 60 minutes of ice time", F.d2],
      ["ixg5", "5v5 ixG", "Individual expected goals at five-on-five", F.d1],
      ["ixgpp", "PP ixG", "Individual expected goals on the power play", F.d1]
    ],
    teams: [
      ["team", "Team", "", F.txt, { name: 1 }],
      ["gp", "GP", "Games played", F.int],
      ["w", "W", "Wins", F.int],
      ["l", "L", "Regulation losses", F.int],
      ["otl", "OTL", "Overtime and shootout losses", F.int],
      ["pts", "PTS", "Standings points", F.int],
      ["gf", "GF", "Goals for (shootout goals not counted)", F.int, { grp: 1 }],
      ["ga", "GA", "Goals against", F.int],
      ["xgf", "xGF", "Expected goals for, all situations", F.d1],
      ["xga", "xGA", "Expected goals against, all situations", F.d1],
      ["xg_pct", "xG%", "Share of expected goals: xGF divided by xGF plus xGA. Above 50 means out-chancing opponents", F.pct, { bar: 50 }],
      ["xg5_pct", "5v5 xG%", "Share of expected goals at five-on-five", F.pct, { grp: 1, mid: 50 }],
      ["cf5_pct", "5v5 CF%", "Corsi: share of all shot attempts at five-on-five, including blocked shots", F.pct, { mid: 50 }],
      ["sh5", "5v5 Sh%", "Team shooting percentage at five-on-five", F.pct],
      ["sv5", "5v5 Sv%", "Team save percentage at five-on-five", F.pct],
      ["pdo", "PDO", "Shooting % plus save % at five-on-five. Far from 100 usually means luck that will not last", F.pct, { mid: 100 }],
      ["finish", "Finishing", "Goals scored minus expected goals: how much the shooters beat the chances", F.s1, { grp: 1, sign: 1 }],
      ["goaltending", "Goaltending", "Goals saved above expected by the team's goalies", F.s1, { sign: 1 }]
    ],
    war: [
      ["name", "Player", "", F.txt, { name: 1, link: 1 }],
      ["team", "Team", "Most recent team first", F.txt, { left: 1 }],
      ["pos", "Pos", "Forward, defenseman or goalie", F.txt, { left: 1 }],
      ["gp", "GP", "Games played", F.int],
      ["toi", "TOI", "Minutes played, all situations", F.int],
      ["war", "WAR", "Wins above replacement: the extra wins he gave his team compared with a fill-in player in the same ice time", F.d2, { grp: 1, bar: 1 }],
      ["war82", "WAR/82", "WAR at this pace over an 82-game season (skaters only)", F.d2, { sign: 1 }],
      ["ev_off", "EV Off", "Wins from his effect on his team's chances at five-on-five, with linemates, opponents, score and shift starts accounted for", F.d2, { grp: 1, sign: 1 }],
      ["ev_def", "EV Def", "Wins from his effect on the opponent's chances at five-on-five. Positive means he suppresses chances", F.d2, { sign: 1 }],
      ["pp", "PP", "Wins from his effect on his team's power-play chances", F.d2, { sign: 1 }],
      ["pk", "PK", "Wins from his effect on opposing power-play chances while killing penalties", F.d2, { sign: 1 }],
      ["fin", "Finishing", "Wins from scoring more goals than his shots were worth. Only part of the gap is credited, because one season of finishing is mostly luck", F.d2, { sign: 1 }],
      ["pen", "Penalties", "Wins from drawing more penalties than he takes", F.d2, { sign: 1 }],
      ["goalie", "Goaltending", "Goalies only: wins from goals saved above expected", F.d2, { grp: 1, sign: 1 }],
      ["gar", "GAR", "Goals above replacement: WAR before goals are converted to wins", F.d1, { sign: 1 }]
    ],
    onice: [
      ["name", "Skater", "", F.txt, { name: 1, link: 1 }],
      ["team", "Team", "Most recent team first", F.txt, { left: 1 }],
      ["pos", "Pos", "Forward or defenseman", F.txt, { left: 1 }],
      ["gp", "GP", "Games played", F.int],
      ["toi", "TOI", "Minutes played at five-on-five", F.int],
      ["toi_gp", "TOI/GP", "Five-on-five minutes per game", F.d1],
      ["xg_pct", "xG%", "Share of expected goals while he is on the ice. Above 50 means his team gets the better chances", F.pct, { grp: 1, bar: 50 }],
      ["xg_rel", "xG% Rel", "On-ice xG% minus the team's xG% in the same games when he is on the bench. Positive means the team does better with him out there", F.s1, { sign: 1 }],
      ["cf_pct", "CF%", "Corsi: share of all shot attempts while he is on the ice, including blocked shots", F.pct, { mid: 50 }],
      ["cf_rel", "CF% Rel", "On-ice CF% minus the team's CF% when he is on the bench", F.s1, { sign: 1 }],
      ["xgf60", "xGF/60", "Team expected goals per 60 minutes with him on the ice", F.d2, { grp: 1 }],
      ["xga60", "xGA/60", "Opponent expected goals per 60 minutes with him on the ice. Lower is better", F.d2],
      ["gf", "GF", "Team goals with him on the ice", F.int, { grp: 1 }],
      ["ga", "GA", "Opponent goals with him on the ice", F.int],
      ["gf_pct", "GF%", "Share of goals while he is on the ice", F.pct, { mid: 50 }],
      ["osh", "oiSh%", "On-ice shooting percentage: his team's goals divided by its shots on goal while he is out", F.pct],
      ["osv", "oiSv%", "On-ice save percentage: his goalie's save percentage while he is out", F.pct],
      ["pdo", "PDO", "oiSh% plus oiSv%. Far from 100 usually means luck that will not last", F.pct, { mid: 100 }]
    ],
    lines: [
      ["name", "Line", "Left wing, center, right wing where the positions are known", F.txt, { name: 1 }],
      ["team", "Team", "", F.txt, { left: 1 }],
      ["gp", "GP", "Games in which the three played together", F.int],
      ["toi", "TOI", "Minutes together at five-on-five", F.int],
      ["xg_pct", "xG%", "Share of expected goals with this line on the ice", F.pct, { grp: 1, bar: 50 }],
      ["cf_pct", "CF%", "Share of all shot attempts with this line on the ice", F.pct, { mid: 50 }],
      ["xgf60", "xGF/60", "Expected goals for per 60 minutes", F.d2, { grp: 1 }],
      ["xga60", "xGA/60", "Expected goals against per 60 minutes. Lower is better", F.d2],
      ["xgf", "xGF", "Expected goals for", F.d1],
      ["xga", "xGA", "Expected goals against", F.d1],
      ["gf", "GF", "Goals for", F.int, { grp: 1 }],
      ["ga", "GA", "Goals against", F.int]
    ],
    games: [
      ["date", "Date", "", function (v) { return niceDate(v, true); }, { name: 1 }],
      ["away", "Away", "", F.txt, { left: 1 }],
      ["as", "G", "Away goals (a shootout win counts as one goal)", F.int],
      ["axg", "xG", "Away expected goals", F.d2],
      ["asog", "SOG", "Away shots on goal", F.int],
      ["home", "Home", "", F.txt, { left: 1, grp: 1 }],
      ["hs", "G", "Home goals", F.int],
      ["hxg", "xG", "Home expected goals", F.d2],
      ["hsog", "SOG", "Home shots on goal", F.int],
      ["end", "Ended", "REG = regulation, OT = overtime, SO = shootout", F.txt, { left: 1, grp: 1 }],
      ["xgd", "Home xG edge", "Home expected goals minus away expected goals", F.s2, { bar: 1 }]
    ]
  };
  COLS.pairs = COLS.lines.map(function (c) { return c.slice(); });
  COLS.pairs[0] = ["name", "Pair", "", F.txt, { name: 1 }];
  COLS.pairs[2] = ["gp", "GP", "Games in which the two played together", F.int];
  var SKATER_TABS = [["skaters", "Individual"], ["onice", "On-ice at 5v5"]];
  var LINE_TABS = [["lines", "Forward lines"], ["pairs", "Defense pairs"], ["wowy", "With or without"]];
  var PAGES = {
    war: { title: "Wins above replacement", sort: "war", regularOnly: 1, lede: "One number for a player's total contribution: how many more wins he was worth than a fill-in would have been. Regular season only.",
      min: { key: "gp", label: "Minimum games played", steps: [0, 5, 10, 20, 40, 60], share: 0.12 }, search: "name", pos: "all", noun: "players" },
    onice: { title: "Skaters", nav: "skaters", tabs: SKATER_TABS, sort: "xg_pct", lede: "What happens at five-on-five while each skater is on the ice, and how that compares with the same team when he sits.",
      min: { key: "toi", label: "Minimum 5v5 minutes", steps: [0, 10, 25, 50, 100, 200, 400, 600, 800], share: 0.5 }, search: "name", pos: 1, noun: "skaters" },
    lines: { title: "Lines and pairs", nav: "lines", tabs: LINE_TABS, sort: "toi", lede: "Forward trios at five-on-five: how much they play together and who gets the better of the chances when they do.",
      min: { key: "toi", label: "Minimum minutes together", steps: [0, 10, 25, 50, 100, 200, 300], share: 0.3 }, search: "full", noun: "lines" },
    pairs: { title: "Lines and pairs", nav: "lines", tabs: LINE_TABS, sort: "toi", lede: "Defense pairs at five-on-five: how much they play together and who gets the better of the chances when they do.",
      min: { key: "toi", label: "Minimum minutes together", steps: [0, 10, 25, 50, 100, 200, 400], share: 0.15 }, search: "full", noun: "pairs" },
    goalies: { title: "Goalies", sort: "gsax", lede: "Who is stopping more than they should? Goals saved above expected compares each goalie with an average one facing the same shots.",
      min: { key: "fa", label: "Minimum unblocked shots faced", steps: [0, 25, 50, 100, 250, 500, 1000] }, search: "name", noun: "goalies" },
    skaters: { title: "Skaters", tabs: SKATER_TABS, sort: "ixg", lede: "Shot volume and shot quality for every skater, and whether the goals have kept up with the chances.",
      min: { key: "gp", label: "Minimum games played", steps: [0, 5, 10, 20, 40, 60] }, search: "name", pos: 1, noun: "skaters" },
    teams: { title: "Teams", sort: "xg_pct", lede: "Which teams are creating better chances than they give up, and which are riding the percentages.", noun: "teams" },
    games: { title: "Games", sort: "date", lede: "Every game with the final score next to what the chances said it should have been.", search: "_teams", noun: "games" }
  };

  // -------------------------------------------------------------- pages --
  function seasonControls(onChange, regularOnly) {
    var sel = el("select", { id: "f-season", onchange: function () { state.season = +sel.value; fixType(); onChange(); } },
      meta.seasons.map(function (s) { return el("option", { value: s.id, text: s.label, selected: s.id === state.season }); }));
    var seg = el("div", { "class": "seg", role: "group", "aria-label": "Game type" }, ["regular", "playoffs"].map(function (t) {
      var has = !!typeInfo(state.season, t);
      return el("button", { type: "button", "aria-pressed": String(state.type === t), disabled: !has,
        text: t === "regular" ? "Regular season" : "Playoffs", onclick: function () { state.type = t; onChange(); } });
    }));
    return regularOnly ? [el("label", { "class": "field" }, ["Season", sel])] : [el("label", { "class": "field" }, ["Season", sel]), seg];
  }
  function fixType() { if (!typeInfo(state.season, state.type)) state.type = "regular"; }

  function tabBar(tabs, current) {
    return el("nav", { "class": "tabs", "aria-label": "Views" }, tabs.map(function (t) {
      return el("a", { href: "#/" + t[0], text: t[1], "aria-current": t[0] === current ? "page" : null });
    }));
  }

  function tablePage(kind) {
    var page = PAGES[kind], cols = COLS[kind];
    var st = state.tables[kind] || (state.tables[kind] = { sort: page.sort, dir: -1, q: "", pos: "", min: null });
    fixType();
    main.innerHTML = "";
    main.appendChild(el("h1", { text: page.title }));
    if (page.tabs) main.appendChild(tabBar(page.tabs, kind));
    main.appendChild(el("p", { "class": "lede", text: page.lede }));
    var controls = el("div", { "class": "controls" });
    var holder = el("div");
    main.appendChild(controls); main.appendChild(holder);
    function rerender() { tablePage(kind); }

    seasonControls(function () { st.min = null; rerender(); }, page.regularOnly).forEach(function (c) { controls.appendChild(c); });
    var gameType = page.regularOnly ? "regular" : state.type;
    holder.appendChild(el("p", { "class": "loading", text: "Loading…" }));

    load(kind + "_" + state.season + "_" + gameType).then(function (rows) {
      if (kind === "games") rows.forEach(function (r) { r.xgd = Math.round((r.hxg - r.axg) * 100) / 100; r._teams = r.home + " " + r.away; });
      if (page.min) {
        var top = Math.max.apply(null, rows.map(function (r) { return r[page.min.key] || 0; }).concat([0]));
        if (st.min == null) {
          st.min = 0;
          page.min.steps.forEach(function (s) { if (s <= top * (page.min.share || 0.25)) st.min = s; });
        }
        var msel = el("select", { onchange: function () { st.min = +msel.value; draw(); } },
          page.min.steps.map(function (s) { return el("option", { value: s, text: s === 0 ? "No minimum" : s + "+", selected: s === st.min }); }));
        controls.appendChild(el("label", { "class": "field" }, [page.min.label, msel]));
      }
      if (page.pos) {
        var psel = el("select", { onchange: function () { st.pos = psel.value; draw(); } },
          (page.pos === "all" ? [["", "Everyone"], ["S", "Skaters"], ["F", "Forwards"], ["D", "Defensemen"], ["G", "Goalies"]]
            : [["", "All skaters"], ["F", "Forwards"], ["D", "Defensemen"]]).map(function (o) { return el("option", { value: o[0], text: o[1], selected: o[0] === st.pos }); }));
        controls.appendChild(el("label", { "class": "field" }, ["Position", psel]));
      }
      if (page.search) {
        var q = el("input", { type: "search", value: st.q, placeholder: kind === "games" ? "Team, e.g. COL" : "Name", oninput: function () { st.q = q.value; draw(); } });
        controls.appendChild(el("label", { "class": "field" }, ["Search", q]));
      }
      function draw() {
        var needle = st.q.trim().toLowerCase();
        var shown = rows.filter(function (r) {
          if (page.min && (r[page.min.key] || 0) < st.min) return false;
          if (page.pos && st.pos && (st.pos === "S" ? r.pos === "G" : r.pos !== st.pos)) return false;
          if (needle && String(r[page.search] || "").toLowerCase().indexOf(needle) < 0 && String(r.team || "").toLowerCase().indexOf(needle) < 0) return false;
          return true;
        });
        holder.innerHTML = "";
        if (!shown.length) {
          holder.appendChild(el("p", { "class": "empty", text: rows.length ? "No " + page.noun + " match these filters. Lower the minimum or clear the search." : "No games have been played yet." }));
          return;
        }
        holder.appendChild(statsTable(cols, shown, st, draw));
        var ti = typeInfo(state.season, gameType);
        holder.appendChild(el("p", { "class": "note", text: "Showing " + shown.length.toLocaleString("en-US") + " of " + rows.length.toLocaleString("en-US") + " " + page.noun +
          (ti ? ", through " + niceDate(ti.through, true) + " (" + ti.games.toLocaleString("en-US") + " games)" : "") + ". Select a column heading to sort; hover it for what it means." }));
      }
      draw();
    }).catch(function () {
      holder.innerHTML = "";
      holder.appendChild(el("p", { "class": "empty", text: "This table could not be loaded. Reload the page to try again." }));
    });
  }

  function statsTable(cols, rows, st, redraw) {
    var sorted = rows.slice().sort(function (a, b) {
      var x = a[st.sort], y = b[st.sort];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      if (typeof x === "string") return st.dir * x.localeCompare(y);
      return st.dir * (y - x) * -1;
    });
    var extent = {};
    cols.forEach(function (c) {
      var o = c[4] || {};
      if (o.bar) {
        var mid = o.bar === 1 ? 0 : o.bar;
        extent[c[0]] = Math.max.apply(null, rows.map(function (r) { return Math.abs((r[c[0]] == null ? mid : r[c[0]]) - mid); })) || 1;
      }
    });
    var head = el("tr", {}, [el("th", { "class": "rk", scope: "col", text: "#" })].concat(cols.map(function (c) {
      var o = c[4] || {}, active = st.sort === c[0];
      var th = el("th", { scope: "col", "class": (o.name ? "name " : "") + (o.left ? "l " : "") + (o.grp ? "grp" : ""),
        "aria-sort": active ? (st.dir < 0 ? "descending" : "ascending") : null });
      var b = el("button", { type: "button", text: c[1], "aria-label": c[1] + (c[2] ? ": " + c[2] : "") + ". Sort.",
        onclick: function () {
          if (st.sort === c[0]) st.dir = -st.dir; else { st.sort = c[0]; st.dir = (o.name || o.left) && c[0] !== "date" ? 1 : -1; }
          redraw();
        } });
      if (c[2]) {
        b.addEventListener("mouseenter", function (e) { showTip("<b>" + esc(c[1]) + "</b><br>" + esc(c[2]), e.clientX, e.clientY); });
        b.addEventListener("mouseleave", hideTip);
        b.addEventListener("focus", function () { var r = b.getBoundingClientRect(); showTip("<b>" + esc(c[1]) + "</b><br>" + esc(c[2]), r.left, r.bottom - 10); });
        b.addEventListener("blur", hideTip);
      }
      th.appendChild(b);
      return th;
    })));
    var body = el("tbody");
    var html = [];
    sorted.forEach(function (r, i) {
      var tds = '<td class="rk">' + (i + 1) + "</td>";
      cols.forEach(function (c) {
        var o = c[4] || {}, v = r[c[0]], cls = [], inner = esc(c[3](v));
        if (o.name) cls.push("name"); if (o.left) cls.push("l"); if (o.grp) cls.push("grp");
        if (o.link && r.id) inner = '<a href="#/player-' + r.id + '">' + inner + "</a>";
        if (st.sort === c[0]) cls.push("sorted");
        var mid = o.bar ? (o.bar === 1 ? 0 : o.bar) : (o.mid || 0);
        if ((o.bar || o.sign || o.mid) && v != null && v !== mid) inner = '<span class="' + (v > mid ? "pos" : "neg") + '">' + inner + "</span>";
        if (o.bar && v != null) {
          var w = Math.min(100, Math.abs(v - mid) / extent[c[0]] * 100).toFixed(0);
          inner += '<span class="bar" aria-hidden="true">' + (v < mid ? '<i class="n" style="width:' + w + '%"></i>' : '<i class="p" style="width:' + w + '%"></i>') + "</span>";
        }
        tds += "<td" + (cls.length ? ' class="' + cls.join(" ") + '"' : "") + (o.name && r.full ? ' title="' + esc(r.full) + '"' : "") + ">" + inner + "</td>";
      });
      html.push("<tr>" + tds + "</tr>");
    });
    body.innerHTML = html.join("");
    return el("div", { "class": "tablewrap", tabindex: "0", role: "region", "aria-label": "Stats table, scrolls sideways" },
      [el("table", { "class": "stats" }, [el("thead", {}, [head]), body])]);
  }

  // --------------------------------------------------------------- rink --
  function rinkSvg(game) {
    var svg = el("svg", { "class": "rink", viewBox: "-102 -44.5 204 89", role: "img",
      "aria-label": "Shot map: " + game.away + " at " + game.home + ". Each circle is a shot; bigger circles are better chances." });
    svg.appendChild(el("rect", { "class": "ice", x: -100, y: -42.5, width: 200, height: 85, rx: 28, ry: 28 }));
    svg.appendChild(el("line", { "class": "redline", x1: 0, y1: -42.5, x2: 0, y2: 42.5, "stroke-width": 1 }));
    [-25, 25].forEach(function (x) { svg.appendChild(el("line", { "class": "blueline", x1: x, y1: -42.5, x2: x, y2: 42.5, "stroke-width": 1 })); });
    svg.appendChild(el("circle", { "class": "thin", cx: 0, cy: 0, r: 15 }));
    [-1, 1].forEach(function (s) {
      // goal line is drawn inside the rounded corner: it is shorter than the rink is wide
      svg.appendChild(el("line", { "class": "thin", x1: s * 89, y1: -36.8, x2: s * 89, y2: 36.8 }));
      svg.appendChild(el("path", { "class": "crease", d: "M" + s * 89 + " -6 A6 6 0 0 " + (s > 0 ? 0 : 1) + " " + s * 89 + " 6 Z" }));
      [-22, 22].forEach(function (y) { svg.appendChild(el("circle", { "class": "thin", cx: s * 69, cy: y, r: 15 })); });
    });
    svg.appendChild(el("text", { "class": "lbl", x: -62, y: -36, "text-anchor": "middle", text: game.away + " shoots this way" }));
    svg.appendChild(el("text", { "class": "lbl", x: 62, y: -36, "text-anchor": "middle", text: game.home + " shoots this way" }));
    // biggest first so small shots stay clickable on top
    game.shots.slice().sort(function (a, b) { return b[2] - a[2]; }).forEach(function (s) {
      var c = el("circle", { "class": "shot " + (s[4] ? "h" : "a") + (s[3] ? " goal" : " miss"), cx: s[0], cy: -s[1],
        r: (0.9 + Math.sqrt(s[2]) * 4.6).toFixed(2), tabindex: "0" });
      var label = "<b>" + esc(s[6] || "Unknown") + "</b> (" + (s[4] ? game.home : game.away) + ")<br>" +
        (s[3] ? "Goal" : "No goal") + ", " + (s[7] ? esc(s[7]) + " shot, " : "") + "period " + s[5] + "<br>" + (s[2] * 100).toFixed(0) + "% chance of scoring";
      c.addEventListener("mousemove", function (e) { showTip(label, e.clientX, e.clientY); });
      c.addEventListener("mouseleave", hideTip);
      c.addEventListener("focus", function () { var r = c.getBoundingClientRect(); showTip(label, r.right, r.top); });
      c.addEventListener("blur", hideTip);
      svg.appendChild(c);
    });
    return svg;
  }

  function scoreCard(g) {
    var tot = (g.axg + g.hxg) || 1;
    var hd = function (home) { return g.shots.filter(function (s) { return s[4] === home && s[2] >= meta.danger.high; }).length; };
    var card = el("div", { "class": "scorecard" });
    card.appendChild(el("div", { "class": "scoreline" }, [
      el("span", { "class": "t" }, [el("i", { "class": "dot a" }), g.away]), el("span", { "class": "s", text: String(g.as) }),
      el("span", { "class": "t" }, [el("i", { "class": "dot h" }), g.home]), el("span", { "class": "s", text: String(g.hs) })
    ]));
    card.appendChild(el("p", { "class": "note", style: "margin:0", text: niceDate(g.date, true) + (g.end === "OT" ? ", decided in overtime" : g.end === "SO" ? ", decided in a shootout" : "") }));
    card.appendChild(el("div", { "class": "xgbar", role: "img", "aria-label": "Expected goals: " + g.away + " " + g.axg.toFixed(2) + ", " + g.home + " " + g.hxg.toFixed(2) },
      [el("i", { "class": "a", style: "width:" + (100 * g.axg / tot).toFixed(1) + "%" }), el("i", { "class": "h", style: "width:" + (100 * g.hxg / tot).toFixed(1) + "%" })]));
    card.appendChild(el("dl", { "class": "kv" }, [
      el("dt", { text: "" }), el("dd", { text: g.away }), el("dd", { text: g.home }),
      el("dt", { text: "Expected goals" }), el("dd", { text: g.axg.toFixed(2) }), el("dd", { text: g.hxg.toFixed(2) }),
      el("dt", { text: "Shots on goal" }), el("dd", { text: String(g.asog) }), el("dd", { text: String(g.hsog) }),
      el("dt", { text: "High-danger chances" }), el("dd", { text: String(hd(0)) }), el("dd", { text: String(hd(1)) })
    ]));
    var verdict = Math.abs(g.hxg - g.axg) < 0.35 ? "The chances were close to even."
      : ((g.hxg > g.axg) === (g.hs > g.as) ? "The team with the better chances won." : "The team with the better chances lost.");
    card.appendChild(el("p", { style: "margin:0", text: verdict }));
    return card;
  }

  // ------------------------------------------------------ player cards --
  var CARD_ROWS = {
    skater: [
      ["Value", [
        ["war", "WAR", "everything below added up"],
        ["ev_off", "Even-strength offense", "his effect on his team's chances at five-on-five"],
        ["ev_def", "Even-strength defense", "his effect on the opponent's chances at five-on-five"],
        ["pp", "Power play", "his effect on his team's power-play chances"],
        ["pk", "Penalty kill", "his effect on opposing power-play chances"],
        ["fin", "Finishing", "goals beyond what his shots were worth"],
        ["pen", "Penalties", "penalties drawn minus penalties taken"]]],
      ["Production", [
        ["g", "Goals per 60", "goals per 60 minutes, all situations"],
        ["a1", "Primary assists per 60", "last pass before a goal, per 60 minutes"],
        ["ixg", "Expected goals per 60", "the quality and volume of his own shots"],
        ["xg_pct", "On-ice xG share", "his team's share of expected goals at five-on-five while he is out"]]]],
    goalie: [
      ["Value", [
        ["war", "WAR", "wins above a replacement goalie"],
        ["gsax", "Goals saved above expected", "per 100 unblocked shots faced"],
        ["gsax_5v5", "At five-on-five", "goals saved above expected at five-on-five, per 100 shots faced"],
        ["hd_gsax", "On high-danger shots", "goals saved above expected per 100 high-danger shots"],
        ["sv", "Save percentage", "saves divided by shots on goal"]]]]
  };
  function cardValue(key, v, single, goalie) {
    if (v == null) return "";
    if (key === "xg_pct") return v.toFixed(1) + "%";
    if (key === "sv") return v.toFixed(3).replace(/^0/, "");
    if (key === "g" || key === "a1" || key === "ixg") return v.toFixed(2);
    if (key === "gsax" || key === "gsax_5v5" || key === "hd_gsax") return F.s2(v) + " per 100";
    return F.s2(v) + (single ? " WAR" : (goalie ? " per 50 GP" : " per 82 GP"));
  }
  function ordinal(n) { var s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
  function seasonLabel(id) { id = String(id); return id.slice(0, 4) + "-" + id.slice(6); }

  function cardPage(wanted) {
    main.innerHTML = "";
    main.appendChild(el("h1", { text: "Player cards" }));
    main.appendChild(el("p", { "class": "lede", text: "Where a player ranks at his position in each part of his game. A bar at 90 means he was better than 90% of regulars at that position." }));
    var controls = el("div", { "class": "controls" }), holder = el("div");
    main.appendChild(controls); main.appendChild(holder);
    holder.appendChild(el("p", { "class": "loading", text: "Loading\u2026" }));
    var cs = state.card || (state.card = { id: null, season: null, single: false });

    load("cards").then(function (doc) {
      var P = doc.players, ids = Object.keys(P);
      if (wanted && P[wanted]) { if (cs.id !== wanted) cs.season = null; cs.id = wanted; }
      if (!cs.id || !P[cs.id]) {      // start on last full season's best skater
        var ref = String(doc.seasons[Math.max(0, doc.seasons.length - 2)]), best = null;
        ids.forEach(function (id) { var y = P[id].y[ref]; if (y && P[id].p !== "G" && (!best || y.war > P[best].y[ref].war)) best = id; });
        cs.id = best || ids[0];
      }
      var pl = P[cs.id], goalie = pl.p === "G", years = Object.keys(pl.y).sort();
      if (!cs.season || !pl.y[cs.season]) cs.season = years[years.length - 1];
      var y = pl.y[cs.season], metrics = goalie ? doc.goalie_metrics : doc.skater_metrics;
      var pct = cs.single ? y.p1 : y.p3, val = cs.single ? y.v1 : y.v3;
      var group = goalie ? "goalies" : pl.p === "D" ? "defensemen" : "forwards";

      // ---- controls: search, season, window
      var box = el("input", { type: "search", id: "f-card-search", placeholder: "Type a name", autocomplete: "off" });
      var hits = el("div", { "class": "hits", role: "listbox" });
      box.addEventListener("input", function () {
        var q = box.value.trim().toLowerCase(); hits.innerHTML = "";
        if (q.length < 2) return;
        ids.filter(function (id) { return (P[id].n || "").toLowerCase().indexOf(q) >= 0; })
          .sort(function (a, b) { return Object.keys(P[b].y).length - Object.keys(P[a].y).length || P[a].n.localeCompare(P[b].n); })
          .slice(0, 8).forEach(function (id) {
            hits.appendChild(el("a", { href: "#/player-" + id, role: "option", text: P[id].n + ", " + (P[id].p === "G" ? "G" : P[id].p) + ", " + (P[id].t || "") }));
          });
        if (!hits.children.length) hits.appendChild(el("span", { text: "No player by that name in these seasons." }));
      });
      controls.appendChild(el("label", { "class": "field search" }, ["Find a player", box, hits]));
      var ysel = el("select", { id: "f-card-season", onchange: function () { cs.season = ysel.value; cardPage(cs.id); } },
        years.slice().reverse().map(function (s) { return el("option", { value: s, text: seasonLabel(s), selected: s === cs.season }); }));
      controls.appendChild(el("label", { "class": "field" }, ["Season", ysel]));
      controls.appendChild(el("div", { "class": "seg", role: "group", "aria-label": "Sample" }, [[false, "3-year weighted"], [true, "This season only"]].map(function (o) {
        return el("button", { type: "button", "aria-pressed": String(cs.single === o[0]), text: o[1], onclick: function () { cs.single = o[0]; cardPage(cs.id); } });
      })));

      // ---- the card
      holder.innerHTML = "";
      var card = el("article", { "class": "pcard" });
      var span = cs.single ? seasonLabel(cs.season) + " regular season"
        : (y.n3 > 1 ? "Regular seasons through " + seasonLabel(cs.season) + ", last " + y.n3 + " weighted toward the most recent" : seasonLabel(cs.season) + " regular season (his only one in this span)");
      var warPct = pct[0];
      card.appendChild(el("header", { "class": "pcard-head" }, [
        el("div", {}, [el("h2", { text: pl.n }),
          el("p", { text: (goalie ? "Goalie" : pl.p === "D" ? "Defenseman" : "Forward") + ", " + (y.t || pl.t || "") + ". " + span + "." })]),
        el("div", { "class": "pcard-war" }, [el("b", { text: warPct == null ? "\u2013" : String(warPct) }),
          el("span", { text: warPct == null ? "Not enough ice time to rank" : "WAR percentile among " + group })])
      ]));
      var body = el("div", { "class": "pcard-body" + (goalie ? " one" : "") });
      CARD_ROWS[goalie ? "goalie" : "skater"].forEach(function (g) {
        var sec = el("section", {}, [el("h3", { text: g[0] })]);
        g[1].forEach(function (m) {
          var j = metrics.indexOf(m[0]), p = pct[j], v = val[j];
          var row = el("div", { "class": "prow", tabindex: "0" });
          row.appendChild(el("span", { "class": "plabel", text: m[1] }));
          var track = el("span", { "class": "ptrack", role: "img", "aria-label": p == null ? m[1] + ": not enough ice time" : m[1] + ": " + ordinal(p) + " percentile" });
          if (p != null) {
            var strength = Math.round(30 + Math.abs(p - 50) * 1.4);
            track.appendChild(el("i", { style: "width:" + Math.max(p, 2) + "%;background:color-mix(in srgb, var(--" + (p >= 50 ? "blue" : "red") + ") " + strength + "%, var(--mid))" }));
          }
          row.appendChild(track);
          row.appendChild(el("b", { "class": "ppct", text: p == null ? "" : String(p) }));
          row.appendChild(el("span", { "class": "pval", text: p == null ? "Too little ice time" : cardValue(m[0], v, cs.single, goalie) }));
          var tipText = "<b>" + esc(m[1]) + "</b><br>" + esc(m[2].charAt(0).toUpperCase() + m[2].slice(1)) + "." +
            (p == null ? "<br>Not enough ice time of this kind to rank him." : "<br>Better than " + p + "% of " + group + " with regular ice time.");
          row.addEventListener("mousemove", function (e) { showTip(tipText, e.clientX, e.clientY); });
          row.addEventListener("mouseleave", hideTip);
          row.addEventListener("focus", function () { var r = row.getBoundingClientRect(); showTip(tipText, r.left + 40, r.bottom - 6); });
          row.addEventListener("blur", hideTip);
          sec.appendChild(row);
        });
        body.appendChild(sec);
      });
      card.appendChild(body);
      card.appendChild(el("p", { "class": "pcard-foot", text: "Bars run from 0 (worst) to 100 (best); the tick marks the middle of the league. " + meta.site + "." }));
      holder.appendChild(card);

      // ---- season by season
      holder.appendChild(el("h2", { text: "Season by season", style: "margin-top:32px" }));
      var maxAbs = Math.max.apply(null, years.map(function (s) { return Math.abs(pl.y[s].war); }).concat([1]));
      var cols = goalie ? [["Season", "l"], ["Team", "l"], ["GP"], ["W"], ["SA"], ["Sv%"], ["GSAx"], ["WAR"], ["", "l"]]
        : [["Season", "l"], ["Team", "l"], ["GP"], ["TOI"], ["G"], ["A"], ["P"], ["WAR"], ["", "l"]];
      var tb = el("tbody");
      years.slice().reverse().forEach(function (s) {
        var r = pl.y[s], w = Math.round(Math.abs(r.war) / maxAbs * 100);
        var bar = '<span class="bar wide" aria-hidden="true">' + (r.war < 0 ? '<i class="n" style="width:' + w + '%"></i>' : '<i class="p" style="width:' + w + '%"></i>') + "</span>";
        var cells = goalie ? [r.gp, F.int(r.w), F.int(r.sa), F.sv(r.sv), F.s1(r.gsax)] : [r.gp, F.int(r.toi), r.g, r.a, r.g + r.a];
        var tr = el("tr", { "class": s === cs.season ? "current" : "" });
        tr.innerHTML = '<td class="l"><a href="#/player-' + cs.id + '" data-season="' + s + '">' + seasonLabel(s) + '</a></td><td class="l">' + esc(r.t || "") + "</td>" +
          cells.map(function (c) { return "<td>" + esc(c) + "</td>"; }).join("") + "<td><b>" + F.d2(r.war) + '</b></td><td class="l">' + bar + "</td>";
        tr.querySelector("a").addEventListener("click", function (e) { e.preventDefault(); cs.season = s; cardPage(cs.id); });
        tb.appendChild(tr);
      });
      holder.appendChild(el("div", { "class": "tablewrap fit" }, [el("table", { "class": "stats plain" }, [
        el("thead", {}, [el("tr", {}, cols.map(function (c) { return el("th", { scope: "col", "class": c[1] || "", text: c[0] }); }))]), tb])]));
      holder.appendChild(el("p", { "class": "note", text: "Regular seasons only. Select a season to see its card." }));
      document.title = pl.n + " | " + meta.site;
    }).catch(function () {
      holder.innerHTML = "";
      holder.appendChild(el("p", { "class": "empty", text: "Player cards could not be loaded. Reload the page to try again." }));
    });
  }

  // ------------------------------------------------- with or without --
  function share(f, a) { return f + a > 0 ? 100 * f / (f + a) : null; }
  function wowyPage() {
    fixType();
    var st = state.wowy || (state.wowy = { player: null, team: null, sort: "toi", dir: -1 });
    main.innerHTML = "";
    main.appendChild(el("h1", { text: "Lines and pairs" }));
    main.appendChild(tabBar(LINE_TABS, "wowy"));
    main.appendChild(el("p", { "class": "lede", text: "Pick a skater to see how he does at five-on-five with each teammate, and how each of them does without the other." }));
    var controls = el("div", { "class": "controls" }), holder = el("div");
    main.appendChild(controls); main.appendChild(holder);
    seasonControls(function () { wowyPage(); }).forEach(function (c) { controls.appendChild(c); });
    holder.appendChild(el("p", { "class": "loading", text: "Loading\u2026" }));

    load("wowy_" + state.season + "_" + state.type).then(function (w) {
      var ids = Object.keys(w.players);
      if (!ids.length) { holder.innerHTML = ""; holder.appendChild(el("p", { "class": "empty", text: "No shift data for these games yet." })); return; }
      // one entry per skater per team
      var options = [];
      ids.forEach(function (id) { w.players[id][2].forEach(function (tm) {
        var tot = w.totals[id + "|" + tm]; if (tot) options.push({ id: +id, team: tm, name: w.players[id][0] || ("Player " + id), toi: tot[0] });
      }); });
      options.sort(function (a, b) { return a.name.localeCompare(b.name) || b.toi - a.toi; });
      var teams = options.map(function (o) { return o.team; }).filter(function (v, i, a) { return a.indexOf(v) === i; }).sort();
      var found = options.filter(function (o) { return o.id === st.player && o.team === st.team; })[0];
      if (!found) { found = options.slice().sort(function (a, b) { return b.toi - a.toi; })[0]; st.player = found.id; st.team = found.team; }
      var teamFilter = state.wowyTeam && teams.indexOf(state.wowyTeam) >= 0 ? state.wowyTeam : found.team;

      var tsel = el("select", { id: "f-wteam", onchange: function () {
        state.wowyTeam = tsel.value;
        var first = options.filter(function (o) { return o.team === tsel.value; }).sort(function (a, b) { return b.toi - a.toi; })[0];
        st.player = first.id; st.team = first.team; wowyPage();
      } }, teams.map(function (tm) { return el("option", { value: tm, text: tm, selected: tm === teamFilter }); }));
      var psel = el("select", { id: "f-wplayer", onchange: function () { st.player = +psel.value; st.team = teamFilter; wowyPage(); } },
        options.filter(function (o) { return o.team === teamFilter; }).map(function (o) {
          return el("option", { value: o.id, text: o.name, selected: o.id === st.player });
        }));
      controls.appendChild(el("label", { "class": "field" }, ["Team", tsel]));
      controls.appendChild(el("label", { "class": "field" }, ["Skater", psel]));

      var me = w.totals[st.player + "|" + st.team], myName = w.players[st.player][0];
      var rows = [];
      w.pairs.forEach(function (p) {
        if (p[2] !== st.team || (p[0] !== st.player && p[1] !== st.player)) return;
        var other = p[0] === st.player ? p[1] : p[0], ot = w.totals[other + "|" + st.team];
        if (!ot) return;
        var tog = share(p[6], p[7]), meW = share(me[3] - p[6], me[4] - p[7]), otW = share(ot[3] - p[6], ot[4] - p[7]);
        rows.push({ name: w.players[other][0], pos: w.players[other][1], toi: p[3] / 60, toi_me: (me[0] - p[3]) / 60, toi_ot: (ot[0] - p[3]) / 60,
          tog: tog, me: meW, ot: otW, cf: share(p[4], p[5]), gf: p[8], ga: p[9],
          lift: tog != null && otW != null ? tog - otW : null });
      });
      var cols = [
        ["name", "Teammate", "", F.txt, { name: 1 }],
        ["pos", "Pos", "Forward or defenseman", F.txt, { left: 1 }],
        ["toi", "TOI together", "Five-on-five minutes the two shared the ice", F.int],
        ["tog", "xG% together", "Share of expected goals when both are on the ice", F.pct, { grp: 1, bar: 50 }],
        ["me", "xG% " + myName.split(" ").slice(-1)[0] + " alone", "Share of expected goals when " + myName + " is on the ice without this teammate", F.pct, { mid: 50 }],
        ["ot", "xG% teammate alone", "Share of expected goals when the teammate is on the ice without " + myName, F.pct, { mid: 50 }],
        ["lift", "Teammate's change", "The teammate's xG% with " + myName + " minus his xG% without him. Positive means the teammate does better alongside " + myName, F.s1, { sign: 1 }],
        ["cf", "CF% together", "Share of all shot attempts when both are on the ice", F.pct, { grp: 1, mid: 50 }],
        ["gf", "GF", "Goals for when both are on the ice", F.int],
        ["ga", "GA", "Goals against when both are on the ice", F.int],
        ["toi_me", "TOI apart", myName + "'s five-on-five minutes without this teammate", F.int, { grp: 1 }]
      ];
      function draw() {
        holder.innerHTML = "";
        holder.appendChild(el("h2", { text: myName + ", " + st.team }));
        holder.appendChild(el("p", { "class": "note", style: "margin:0 0 12px", text: Math.round(me[0] / 60).toLocaleString("en-US") + " minutes at five-on-five, " +
          F.pct(share(me[3], me[4])) + "% of expected goals, " + me[5] + " goals for and " + me[6] + " against." }));
        if (!rows.length) { holder.appendChild(el("p", { "class": "empty", text: "No teammate has shared 10 minutes with him yet." })); return; }
        holder.appendChild(statsTable(cols, rows, st, draw));
        holder.appendChild(el("p", { "class": "note", text: "Teammates with at least 10 minutes together. Small samples swing wildly: 50 minutes is only about four games' worth of shifts." }));
      }
      draw();
    }).catch(function () {
      holder.innerHTML = "";
      holder.appendChild(el("p", { "class": "empty", text: "This table could not be loaded. Reload the page to try again." }));
    });
  }

  function home() {
    main.innerHTML = "";
    var hero = el("section", { "class": "hero" });
    hero.appendChild(el("h1", { text: "Every shot, weighed." }));
    hero.appendChild(el("p", { "class": "lede", text: "A shot from the slot is not a shot from the boards. Each circle below is one shot from a recent NHL game, sized by how often a shot like it goes in." }));
    main.appendChild(hero);
    var strip = el("div", { "class": "gamestrip", role: "group", "aria-label": "Recent games" });
    var grid = el("div", { "class": "rinkgrid" });
    hero.appendChild(strip); hero.appendChild(grid);
    var leaders = el("section", { "class": "leaders", "aria-label": "Season leaders" });
    main.appendChild(leaders);

    load("recent").then(function (games) {
      if (!games.length) { grid.appendChild(el("p", { "class": "empty", text: "No games yet this season." })); return; }
      var current = state.game && games.filter(function (g) { return g.id === state.game; })[0] || games[0];
      function pick(g) {
        current = g; state.game = g.id;
        Array.prototype.forEach.call(strip.children, function (b) { b.setAttribute("aria-pressed", String(+b.dataset.id === g.id)); });
        grid.innerHTML = "";
        var box = el("div", { "class": "rinkbox" }, [rinkSvg(g)]);
        box.appendChild(el("div", { "class": "legend", html:
          '<span><svg width="14" height="14"><circle cx="7" cy="7" r="5.5" fill="var(--ink-2)" stroke="var(--ink)" stroke-width="1.5"/></svg> Goal</span>' +
          '<span><svg width="14" height="14"><circle cx="7" cy="7" r="5.5" fill="var(--ink-2)" fill-opacity=".18" stroke="var(--ink-2)"/></svg> Saved or missed</span>' +
          '<span><svg width="34" height="14"><circle cx="5" cy="7" r="2" fill="var(--ink-2)"/><circle cx="16" cy="7" r="4" fill="var(--ink-2)"/><circle cx="28" cy="7" r="6" fill="var(--ink-2)"/></svg> Bigger means a better chance</span>' +
          "<span>Blocked shots are not shown</span>" }));
        grid.appendChild(box);
        grid.appendChild(scoreCard(g));
      }
      games.forEach(function (g) {
        var hw = g.hs > g.as;
        strip.appendChild(el("button", { type: "button", "class": "gamechip", "data-id": g.id, "aria-pressed": "false",
          "aria-label": g.away + " " + g.as + ", " + g.home + " " + g.hs + ", " + niceDate(g.date), onclick: function () { pick(g); } }, [
          el("span", { "class": "d", text: niceDate(g.date) }),
          el("span", { "class": hw ? "" : "w", text: g.away }), el("span", { "class": "n " + (hw ? "" : "w"), text: String(g.as) }),
          el("span", { "class": hw ? "w" : "", text: g.home }), el("span", { "class": "n " + (hw ? "w" : ""), text: String(g.hs) })
        ]));
      });
      pick(current);
    }).catch(function () { grid.appendChild(el("p", { "class": "empty", text: "The shot map could not be loaded. Reload the page to try again." })); });

    var latest = meta.seasons[0], lt = latest.types[latest.types.length - 1];
    var sfx = "_" + latest.id + "_" + lt.id;
    Promise.all([load("goalies" + sfx), load("war_" + latest.id + "_regular").catch(function () { return []; }), load("teams" + sfx)]).then(function (d) {
      function block(title, rows, val, fmt, route, sub, linkText) {
        var ol = el("ol", {}, rows.slice(0, 5).map(function (r, i) {
          return el("li", {}, [el("span", { "class": "rk", text: String(i + 1) }),
            el("span", { "class": "who" }, [r.name || r.team, r.name ? el("small", { text: r.team || "" }) : null]),
            el("span", { "class": "val", text: fmt(r[val]) })]);
        }));
        return el("div", {}, [el("h2", { text: title }), el("p", { "class": "note", style: "margin:0 0 8px", text: sub }), ol,
          el("p", {}, [el("a", { href: "#/" + route, text: linkText || "All " + route })])]);
      }
      var by = function (rows, k) { return rows.slice().sort(function (a, b) { return (b[k] || 0) - (a[k] || 0); }); };
      var when = latest.label + (lt.id === "playoffs" ? " playoffs" : "") + ", through " + niceDate(lt.through);
      var whenReg = latest.label + ", through " + niceDate((typeInfo(latest.id, "regular") || lt).through);
      var sk = d[1].filter(function (r) { return r.pos !== "G"; });
      if (sk.length) leaders.appendChild(block("Wins above replacement, skaters", by(sk, "war"), "war", F.d2, "war", whenReg, "Full WAR table"));
      leaders.appendChild(block("Goals saved above expected", by(d[0], "gsax"), "gsax", F.s1, "goalies", when));
      leaders.appendChild(block("Share of expected goals", by(d[2], "xg_pct"), "xg_pct", function (v) { return F.pct(v) + "%"; }, "teams", when));
    }).catch(function () {});
  }

  function about() {
    main.innerHTML = "";
    var p = el("div", { "class": "prose" });
    main.appendChild(el("h1", { text: "How the numbers work" }));
    main.appendChild(p);
    p.innerHTML =
      "<p class='lede'>Goals are rare and noisy. Shots are common. So instead of waiting for goals, this site measures the quality of every shot.</p>" +
      "<h2>Expected goals</h2>" +
      "<p>Every unblocked shot gets a value between 0 and 1: the share of similar shots that have gone in. A rebound from the top of the crease might be worth 0.35. A wrist shot from the point is closer to 0.02. That value is the shot's expected goals, or xG.</p>" +
      "<p>The value comes from a model trained on <span id='ab-shots'>hundreds of thousands of</span> shots. It looks at where the shot was taken, the shot type, the manpower on the ice, the score, and what happened just before: a rebound, a rush up ice, a turnover, a faceoff win.</p>" +
      "<p>Add the values up and you get the goals a team, skater or goalie would be expected to have, given the chances that happened.</p>" +
      "<h2>How well the model predicts</h2>" +
      "<p id='ab-test'></p><div class='facts' id='ab-facts'></div><div id='ab-chart'></div>" +
      "<p id='ab-scale'></p>" +
      "<p class='note'>If the model is honest, shots it rates at 10% go in about 10% of the time. Each point is a tenth of the test shots, grouped from worst chances to best. Points on the dashed line are perfect.</p>" +
      "<h2>What the model cannot see</h2>" +
      "<p>The public feed records where a shot was taken, not what led up to it in detail. The model does not know about screens, passes across the slot, or where the goalie was standing. Shot locations are entered by hand at each arena and differ a little from rink to rink. Treat small differences between players as noise, especially early in a season.</p>" +
      "<h2>Wins above replacement</h2>" +
      "<p>WAR rolls a player's whole contribution into one number: the wins he added compared with a replacement player, meaning the kind of fill-in a team can call up or sign for the minimum.</p>" +
      "<p>For skaters it adds six parts. Four come from a regression that looks at every stretch of play and works out each skater's own effect on chances, with his linemates, opponents, the score and where his shifts started taken into account: five-on-five offense, five-on-five defense, power play and penalty kill. The other two are counted directly: finishing (goals beyond what his shots were worth) and penalties drawn minus taken. Goalies are rated on goals saved above expected.</p>" +
      "<p id='ab-war'></p>" +
      "<p>A few choices are worth knowing about. Forwards and defensemen are each rated against their own position. A skater's rating starts each season from a faded copy of last season's and from the typical level for his role on the team, then moves as evidence comes in, so early-season numbers lean on last year. Only part of a hot or cold shooting season is credited, because finishing mostly does not repeat. And the regression cannot fully separate players who are always on the ice together, so it splits their credit.</p>" +
      "<h2>Player cards</h2>" +
      "<p>A card ranks a player against others at his position, on rates rather than totals so missed games do not count against him. By default it blends three seasons, with the newest counting three times as much as the oldest, because one season is a small sample for most of these measures. Players without regular ice time of a given kind (the power play, say) are not ranked on it.</p>" +
      "<h2>On-ice numbers</h2>" +
      "<p>The league publishes when every player steps on and off the ice. Laid over the shot data, that shows which ten skaters were out for each shot. On-ice numbers, lines, pairs and the with-or-without tables all come from that, and all are at five-on-five: five skaters and a goalie on each side.</p>" +
      "<p id='ab-shifts'></p>" +
      "<h2>Glossary</h2><dl class='gloss' id='ab-gloss'></dl>" +
      "<h2>Data</h2><p>Games come from the NHL's public play-by-play feed and are refreshed every night. Games from the last three days are re-checked for the league's stat corrections. Shootouts are left out of every table.</p>";
    var seen = {}, gl = document.getElementById("ab-gloss");
    [["xG", "Expected goals: the chance a shot goes in, added up."]].concat(
      ["war", "goalies", "skaters", "onice", "teams"].reduce(function (acc, k) { return acc.concat(COLS[k].map(function (c) { return [c[1], c[2]]; })); }, [])
    ).forEach(function (g) {
      if (!g[1] || seen[g[0]] || /^(GP|W|L|G|P|Team|Pos)$/.test(g[0])) return;
      seen[g[0]] = 1; gl.appendChild(el("dt", { text: g[0] })); gl.appendChild(el("dd", { text: g[1] }));
    });
    var cov = meta.shift_coverage || {}, total = 0, have = 0, gaps = [];
    Object.keys(cov).forEach(function (s) { total += cov[s].games; have += cov[s].with_shifts;
      if (cov[s].with_shifts < cov[s].games) gaps.push((cov[s].games - cov[s].with_shifts) + " in " + s.slice(0, 4) + "-" + s.slice(6)); });
    if (total) document.getElementById("ab-shifts").textContent = "Shift records are available for " + have.toLocaleString("en-US") + " of " + total.toLocaleString("en-US") + " games" +
      (gaps.length ? ". The missing games (" + gaps.join(", ") + ") are left out of the on-ice tables." : ".") +
      " Ice time added up from them matches the league's official totals to within half a percent for nearly every skater.";
    var wm = meta.war || {};
    if (wm.goals_per_win) {
      var tc = wm.team_check, done = Object.keys(wm.seasons || {}).sort(), ref = wm.seasons[done[Math.max(0, done.length - 2)]] || {};
      document.getElementById("ab-war").textContent = "Goals become wins at " + wm.goals_per_win.toFixed(1) + " goals per win, measured from team results. A drawn penalty is worth about " + wm.penalty_value.toFixed(2) + " goals. " +
        "A full season adds up to roughly " + Math.round(ref.total || 0) + " WAR across the league, about " + Math.round((ref.total || 0) / 32) + " per team." +
        (tc ? " As a check, adding up each team's player WAR and comparing it with the standings over " + tc.team_seasons + " team-seasons gives a correlation of " + tc.corr.toFixed(2) + ", and a team made only of replacement players would be expected to finish with about " + Math.round(tc.replacement_team_points) + " points." : "");
    }
    load("model").then(function (m) {
      if (!m || !m.overall) return;
      var o = m.overall, label = String(m.test_season).slice(0, 4) + "-" + String(m.test_season).slice(6);
      document.getElementById("ab-shots").textContent = m.train_shots.toLocaleString("en-US");
      document.getElementById("ab-test").textContent = "Before the final version was trained, an earlier copy was tested on a full season it had never seen (" + label + "), to check that it predicts new games and has not just memorised old ones.";
      var facts = [[o.goals.toLocaleString("en-US"), "goals scored in the test season"], [Math.round(o.xg).toLocaleString("en-US"), "goals the model expected"],
        [o.auc.toFixed(3), "AUC: how well it ranks chances (0.5 is a coin flip, 1 is perfect)"],
        [(100 * (1 - o.log_loss / o.baseline_log_loss)).toFixed(1) + "%", "better than treating every shot the same (log loss)"]];
      var f = document.getElementById("ab-facts");
      facts.forEach(function (x) { f.appendChild(el("div", {}, [el("b", { text: x[0] }), el("span", { text: x[1] })])); });
      document.getElementById("ab-chart").appendChild(calibration(m.calibration));
      var off = 100 * (o.xg / o.goals - 1);
      document.getElementById("ab-scale").textContent = "It ran " + Math.abs(off).toFixed(1) + "% " + (off > 0 ? "high" : "low") +
        " for that season. Scoring and record-keeping shift a little every year, so each season's values are scaled until the league's expected goals at a goalie equal the goals actually scored. That makes an exactly average goalie worth zero goals saved above expected. To keep the tables fair, every past game is also scored by a copy of the model that was never shown that game.";
    }).catch(function () {});
  }

  function calibration(bins) {
    var W = 480, H = 320, L = 46, B = 36, T = 10, R = 12;
    var max = Math.max.apply(null, bins.map(function (b) { return Math.max(b.avg_xg, b.goal_rate); })) * 1.08;
    var x = function (v) { return L + (W - L - R) * v / max; }, y = function (v) { return H - B - (H - B - T) * v / max; };
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Calibration chart: predicted chance against how often shots went in" });
    for (var i = 0; i <= 4; i++) {
      var v = max * i / 4;
      svg.appendChild(el("line", { "class": "axis", x1: L, x2: W - R, y1: y(v), y2: y(v) }));
      svg.appendChild(el("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end", text: (v * 100).toFixed(0) + "%" }));
      svg.appendChild(el("text", { x: x(v), y: H - B + 16, "text-anchor": "middle", text: (v * 100).toFixed(0) + "%" }));
    }
    svg.appendChild(el("line", { "class": "ideal", x1: x(0), y1: y(0), x2: x(max), y2: y(max) }));
    svg.appendChild(el("polyline", { "class": "ln", points: bins.map(function (b) { return x(b.avg_xg).toFixed(1) + "," + y(b.goal_rate).toFixed(1); }).join(" ") }));
    bins.forEach(function (b) { svg.appendChild(el("circle", { "class": "pt", cx: x(b.avg_xg), cy: y(b.goal_rate), r: 4 })); });
    svg.appendChild(el("text", { x: (L + W - R) / 2, y: H - 4, "text-anchor": "middle", text: "What the model predicted" }));
    svg.appendChild(el("text", { x: 12, y: (H - B) / 2, "text-anchor": "middle", transform: "rotate(-90 12 " + (H - B) / 2 + ")", text: "How often shots went in" }));
    return el("div", { "class": "chart" }, [svg]);
  }

  // ------------------------------------------------------------- router --
  function route() {
    hideTip();
    var r = (location.hash.replace(/^#\/?/, "").split("?")[0] || "home").toLowerCase();
    Array.prototype.forEach.call(document.querySelectorAll(".nav a"), function (a) {
      var player = /^player-(\d+)$/.exec(r);
      var navKey = r === "wowy" ? "lines" : player ? "cards" : (PAGES[r] && PAGES[r].nav) || r;
      if (a.dataset.route === navKey) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    var pm = /^player-(\d+)$/.exec(r);
    if (pm || r === "cards") { cardPage(pm ? pm[1] : null); window.scrollTo(0, 0); return; }
    if (PAGES[r]) tablePage(r); else if (r === "wowy") wowyPage(); else if (r === "about") about(); else home();
    document.title = (r === "war" ? "WAR | " : PAGES[r] ? PAGES[r].title + " | " : r === "wowy" ? "With or without | " : r === "about" ? "About | " : "") + meta.site;
    window.scrollTo(0, 0);
  }

  load("meta").then(function (m) {
    meta = m; delete cache.meta;
    state.season = m.seasons[0].id;
    state.type = m.seasons[0].types[m.seasons[0].types.length - 1].id;
    document.getElementById("brand-name").textContent = m.site;
    var d = new Date(m.updated_utc);
    document.getElementById("foot-updated").textContent = "Updated " + (isNaN(d) ? m.updated_utc : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })) + ".";
    window.addEventListener("hashchange", route);
    route();
  }).catch(function () {
    main.innerHTML = "";
    main.appendChild(el("p", { "class": "empty", text: "The stats have not been published yet. Check back after tonight's update." }));
  });
})();
