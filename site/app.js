/* The Slot: a small single-page site. No build step, no libraries.
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
      : fetch("data/" + name + ".json" + (meta ? "?v=" + encodeURIComponent(meta.updated_utc) : ""), { cache: meta ? "default" : "no-cache" })
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
      ["name", "Goalie", "", F.txt, { name: 1 }],
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
      ["name", "Skater", "", F.txt, { name: 1 }],
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
  var PAGES = {
    goalies: { title: "Goalies", sort: "gsax", lede: "Who is stopping more than they should? Goals saved above expected compares each goalie with an average one facing the same shots.",
      min: { key: "fa", label: "Minimum unblocked shots faced", steps: [0, 25, 50, 100, 250, 500, 1000] }, search: "name", noun: "goalies" },
    skaters: { title: "Skaters", sort: "ixg", lede: "Shot volume and shot quality for every skater, and whether the goals have kept up with the chances.",
      min: { key: "gp", label: "Minimum games played", steps: [0, 5, 10, 20, 40, 60] }, search: "name", pos: 1, noun: "skaters" },
    teams: { title: "Teams", sort: "xg_pct", lede: "Which teams are creating better chances than they give up, and which are riding the percentages.", noun: "teams" },
    games: { title: "Games", sort: "date", lede: "Every game with the final score next to what the chances said it should have been.", search: "_teams", noun: "games" }
  };

  // -------------------------------------------------------------- pages --
  function seasonControls(onChange) {
    var sel = el("select", { id: "f-season", onchange: function () { state.season = +sel.value; fixType(); onChange(); } },
      meta.seasons.map(function (s) { return el("option", { value: s.id, text: s.label, selected: s.id === state.season }); }));
    var seg = el("div", { "class": "seg", role: "group", "aria-label": "Game type" }, ["regular", "playoffs"].map(function (t) {
      var has = !!typeInfo(state.season, t);
      return el("button", { type: "button", "aria-pressed": String(state.type === t), disabled: !has,
        text: t === "regular" ? "Regular season" : "Playoffs", onclick: function () { state.type = t; onChange(); } });
    }));
    return [el("label", { "class": "field" }, ["Season", sel]), seg];
  }
  function fixType() { if (!typeInfo(state.season, state.type)) state.type = "regular"; }

  function tablePage(kind) {
    var page = PAGES[kind], cols = COLS[kind];
    var st = state.tables[kind] || (state.tables[kind] = { sort: page.sort, dir: -1, q: "", pos: "", min: null });
    fixType();
    main.innerHTML = "";
    main.appendChild(el("h1", { text: page.title }));
    main.appendChild(el("p", { "class": "lede", text: page.lede }));
    var controls = el("div", { "class": "controls" });
    var holder = el("div");
    main.appendChild(controls); main.appendChild(holder);
    function rerender() { tablePage(kind); }

    seasonControls(function () { st.min = null; rerender(); }).forEach(function (c) { controls.appendChild(c); });
    holder.appendChild(el("p", { "class": "loading", text: "Loading…" }));

    load(kind + "_" + state.season + "_" + state.type).then(function (rows) {
      if (kind === "games") rows.forEach(function (r) { r.xgd = Math.round((r.hxg - r.axg) * 100) / 100; r._teams = r.home + " " + r.away; });
      if (page.min) {
        var top = Math.max.apply(null, rows.map(function (r) { return r[page.min.key] || 0; }).concat([0]));
        if (st.min == null) {
          st.min = 0;
          page.min.steps.forEach(function (s) { if (s <= top * 0.25) st.min = s; });
        }
        var msel = el("select", { onchange: function () { st.min = +msel.value; draw(); } },
          page.min.steps.map(function (s) { return el("option", { value: s, text: s === 0 ? "No minimum" : s + "+", selected: s === st.min }); }));
        controls.appendChild(el("label", { "class": "field" }, [page.min.label, msel]));
      }
      if (page.pos) {
        var psel = el("select", { onchange: function () { st.pos = psel.value; draw(); } },
          [["", "All skaters"], ["F", "Forwards"], ["D", "Defensemen"]].map(function (o) { return el("option", { value: o[0], text: o[1], selected: o[0] === st.pos }); }));
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
          if (page.pos && st.pos && r.pos !== st.pos) return false;
          if (needle && String(r[page.search] || "").toLowerCase().indexOf(needle) < 0 && String(r.team || "").toLowerCase().indexOf(needle) < 0) return false;
          return true;
        });
        holder.innerHTML = "";
        if (!shown.length) {
          holder.appendChild(el("p", { "class": "empty", text: rows.length ? "No " + page.noun + " match these filters. Lower the minimum or clear the search." : "No games have been played yet." }));
          return;
        }
        holder.appendChild(statsTable(cols, shown, st, draw));
        var ti = typeInfo(state.season, state.type);
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
        if (st.sort === c[0]) cls.push("sorted");
        var mid = o.bar ? (o.bar === 1 ? 0 : o.bar) : (o.mid || 0);
        if ((o.bar || o.sign || o.mid) && v != null && v !== mid) inner = '<span class="' + (v > mid ? "pos" : "neg") + '">' + inner + "</span>";
        if (o.bar && v != null) {
          var w = Math.min(100, Math.abs(v - mid) / extent[c[0]] * 100).toFixed(0);
          inner += '<span class="bar" aria-hidden="true">' + (v < mid ? '<i class="n" style="width:' + w + '%"></i>' : '<i class="p" style="width:' + w + '%"></i>') + "</span>";
        }
        tds += "<td" + (cls.length ? ' class="' + cls.join(" ") + '"' : "") + ">" + inner + "</td>";
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
      svg.appendChild(el("path", { "class": "crease", d: "M" + s * 89 + " -4 h" + (-s * 4.5) + " a6 6 0 0 " + (s > 0 ? 0 : 1) + " 0 8 h" + (s * 4.5) + " z" }));
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
    Promise.all([load("goalies" + sfx), load("skaters" + sfx), load("teams" + sfx)]).then(function (d) {
      function block(title, rows, val, fmt, route, sub) {
        var ol = el("ol", {}, rows.slice(0, 5).map(function (r, i) {
          return el("li", {}, [el("span", { "class": "rk", text: String(i + 1) }),
            el("span", { "class": "who" }, [r.name || r.team, r.name ? el("small", { text: r.team || "" }) : null]),
            el("span", { "class": "val", text: fmt(r[val]) })]);
        }));
        return el("div", {}, [el("h2", { text: title }), el("p", { "class": "note", style: "margin:0 0 8px", text: sub }), ol,
          el("p", {}, [el("a", { href: "#/" + route, text: "All " + route })])]);
      }
      var by = function (rows, k) { return rows.slice().sort(function (a, b) { return (b[k] || 0) - (a[k] || 0); }); };
      var when = latest.label + (lt.id === "playoffs" ? " playoffs" : "") + ", through " + niceDate(lt.through);
      leaders.appendChild(block("Goals saved above expected", by(d[0], "gsax"), "gsax", F.s1, "goalies", when));
      leaders.appendChild(block("Expected goals, skaters", by(d[1], "ixg"), "ixg", F.d1, "skaters", when));
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
      "<p class='note'>If the model is honest, shots it rates at 10% go in about 10% of the time. Each point is a tenth of the test shots, grouped from worst chances to best. Points on the dashed line are perfect.</p>" +
      "<h2>What the model cannot see</h2>" +
      "<p>The public feed records where a shot was taken, not what led up to it in detail. The model does not know about screens, passes across the slot, or where the goalie was standing. Shot locations are entered by hand at each arena and differ a little from rink to rink. Treat small differences between players as noise, especially early in a season.</p>" +
      "<h2>Glossary</h2><dl class='gloss' id='ab-gloss'></dl>" +
      "<h2>Data</h2><p>Games come from the NHL's public play-by-play feed and are refreshed every night. Games from the last three days are re-checked for the league's stat corrections. Shootouts are left out of every table.</p>";
    var seen = {}, gl = document.getElementById("ab-gloss");
    [["xG", "Expected goals: the chance a shot goes in, added up."]].concat(
      ["goalies", "skaters", "teams"].reduce(function (acc, k) { return acc.concat(COLS[k].map(function (c) { return [c[1], c[2]]; })); }, [])
    ).forEach(function (g) {
      if (!g[1] || seen[g[0]] || /^(GP|W|L|G|P|Team|Pos)$/.test(g[0])) return;
      seen[g[0]] = 1; gl.appendChild(el("dt", { text: g[0] })); gl.appendChild(el("dd", { text: g[1] }));
    });
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
      if (a.dataset.route === r) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    if (PAGES[r]) tablePage(r); else if (r === "about") about(); else home();
    document.title = (PAGES[r] ? PAGES[r].title + " | " : r === "about" ? "About | " : "") + meta.site;
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
