/* GOAT Hockey: one page, no libraries. Every NHL game, the standings, team stats and player cards. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var data = null, state = { week: null, team: null };

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    for (var k in attrs || {}) {
      if (attrs[k] == null || attrs[k] === false) continue;
      if (k === "text") n.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), attrs[k]);
      else n.setAttribute(k, attrs[k] === true ? "" : attrs[k]);
    }
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }

  // ---- dates. A day is "YYYY-MM-DD", the league's own date for a game; weeks run Monday to Sunday. ----
  function iso(d) { return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }
  function day(s) { var p = s.split("-"); return new Date(+p[0], +p[1] - 1, +p[2], 12); }
  function addDays(s, n) { var d = day(s); d.setDate(d.getDate() + n); return iso(d); }
  function monday(s) { var d = day(s); return addDays(s, -((d.getDay() + 6) % 7)); }
  function short(s) { return day(s).toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
  function long(s) { return day(s).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }); }
  function clockTime(t) { return t.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }); }
  var today = iso(new Date());

  // The site's wording, from words.txt (see the top of that file). {name} is filled from `vars`.
  function W(key, vars) {
    var s = ((data && data.words) || {})[key];
    if (s == null) return "";
    vars = vars || {};
    if (vars.league == null && data) vars.league = data.league;
    return s.replace(/\{(\w+)\}/g, function (m, k) { return vars[k] != null ? String(vars[k]) : m; });
  }
  var teamsById = {};
  function T(id) { return teamsById[id] || null; }
  function ordinal(n) { var s = ["th", "st", "nd", "rd"], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }

  // A team's logo, shown from the NHL's own site. With `name`, the logo stands in
  // for the team's name, so it carries the name for screen readers and on hover.
  function logo(teamId, cls, name) {
    if (!data.logo || !teamId) return name ? el("span", { text: name }) : null;
    var img = el("img", { src: data.logo.replace("{team}", encodeURIComponent(teamId)), alt: name || "", title: name || null, loading: "lazy", decoding: "async" });
    var pic = el("span", { "class": "logo " + (cls || "") }, [img]);
    img.addEventListener("error", function () {       // no logo: show the team's short code instead
      pic.className = "logo badge " + (cls || ""); pic.textContent = ""; pic.appendChild(el("span", { text: teamId }));
      if (name) { pic.title = name; pic.setAttribute("aria-label", name); }
    });
    return pic;
  }
  // A player's photo, shown from the NHL's own site. His initials appear only when
  // there is no photo, or it cannot be loaded (the photos have see-through backgrounds).
  function face(p, cls) {
    var initials = p.name.split(/\s+/).map(function (w) { return w.charAt(0); }).join("").slice(0, 2).toUpperCase();
    var box = el("span", { "class": "face " + (cls || ""), "aria-hidden": "true" });
    function letters() { box.classList.remove("has"); box.textContent = ""; box.appendChild(el("span", { text: initials })); }
    if (p.photo) {
      var img = el("img", { src: p.photo, alt: "", loading: "lazy", decoding: "async", referrerpolicy: "no-referrer" });
      img.addEventListener("error", letters);
      box.classList.add("has");
      box.appendChild(img);
    } else letters();
    return box;
  }
  // A team's name as a link to its page.
  function teamA(id, name, cls) {
    return id && T(id) ? el("a", { "class": "tlink " + (cls || ""), href: "#/team/" + encodeURIComponent(id), text: name })
      : el("span", { "class": cls || "", text: name });
  }
  // A team's number: its place in the league standings.
  function rankTag(rank) {
    return el("span", { "class": "rk" + (rank ? "" : " nr"), text: rank ? String(rank) : "–",
      "aria-label": rank ? ordinal(rank) + " in the standings" : null, title: rank ? ordinal(rank) + " in the league standings" : null });
  }
  function record(t) { return t.w + "-" + t.l + "-" + t.otl; }

  // ---- the standings page ----
  var standView = "division";
  var SCOLS = [   // heading, meaning, value, class
    ["GP", "Games played", function (t) { return t.gp; }], ["W", "Wins", function (t) { return t.w; }], ["L", "Losses in regulation", function (t) { return t.l; }],
    ["OTL", "Losses in overtime or a shootout, worth one point", function (t) { return t.otl; }],
    ["PTS", "Points: 2 for a win, 1 for an overtime or shootout loss", function (t) { return t.pts; }, "strong"],
    ["P%", "Share of the possible points won", function (t) { return t.gp ? t.pct.toFixed(3).replace(/^0/, "") : "–"; }],
    ["RW", "Wins in regulation, the first tie-breaker", function (t) { return t.rw; }],
    ["GF", "Goals for", function (t) { return t.gf; }], ["GA", "Goals against", function (t) { return t.ga; }],
    ["Diff", "Goals for minus goals against", function (t) { return (t.diff > 0 ? "+" : t.diff < 0 ? "−" : "") + Math.abs(t.diff); }],
    ["Home", "Record at home", function (t) { return t.home; }], ["Away", "Record on the road", function (t) { return t.away; }],
    ["L10", "Record in the last ten games", function (t) { return t.l10; }], ["Streak", "W wins, L losses, OT overtime losses in a row", function (t) { return t.streak || "–"; }]
  ];
  function standTable(rows, label, numberOf, cutAfter) {
    var thead = el("thead", {}, [el("tr", {}, [el("th", { scope: "col", text: "#" }), el("th", { scope: "col", "class": "l", text: label })]
      .concat(SCOLS.map(function (c) { return el("th", { scope: "col", title: c[1], text: c[0] }); })))]);
    var body = el("tbody", {}, rows.map(function (t, i) {
      return el("tr", { "class": cutAfter && i === cutAfter - 1 ? "cut" : "" }, [el("td", {}, [el("span", { "class": "rk", text: String(numberOf ? numberOf(t, i) : i + 1) })]),
        el("td", { "class": "l" }, [el("span", { "class": "tcell" }, [logo(t.id), teamA(t.id, t.name), t.clinch ? el("small", { "class": "clinch", text: " " + t.clinch }) : null])])]
        .concat(SCOLS.map(function (c) { return el("td", { "class": c[3] || "", text: String(c[2](t)) }); })));
    }));
    return el("div", { "class": "tablewrap", tabindex: "0", role: "region", "aria-label": label + " standings, scrolls sideways" }, [el("table", { "class": "ptable stand" }, [thead, body])]);
  }
  // A team's results against the GOAT top ten: "Beat 3 Stars x2. Lost to 1 Avalanche."
  function versus(t) {
    function box(label, rows, cls) {
      var opps = rows.map(function (r) {
        return el("a", { "class": "opp", href: "#/team/" + encodeURIComponent(r[3]), title: r[1] }, [el("span", { "class": "n", text: String(r[0]) }), logo(r[3], "sm", r[1]), r[2] > 1 ? el("span", { "class": "x", text: "x" + r[2] }) : null]);
      });
      return el("span", { "class": "vsbox " + cls }, [el("b", { text: label }),
        el("span", { "class": "opps" }, opps.length ? opps : [el("span", { "class": "nil", text: W("standings.none_yet") })])]);
    }
    return el("span", { "class": "vs" }, [box(W("standings.beat"), t.beat || [], "beat"), box(W("standings.lost_to"), t.lost || [], "lostto")]);
  }
  function by(key) { return function (a, b) { return a[key] - b[key]; }; }
  function groups(key) { var seen = []; data.teams.forEach(function (t) { if (seen.indexOf(t[key]) < 0) seen.push(t[key]); }); return seen.sort(); }
  function drawStandings() {
    var holder = $("stand"), bar = $("rank-sort");
    holder.innerHTML = ""; bar.innerHTML = "";
    [["division", W("standings.button_division")], ["wildcard", W("standings.button_wildcard")], ["conference", W("standings.button_conference")],
      ["league", W("standings.button_league")], ["goat", W("standings.button_goat")]].forEach(function (o) {
      bar.appendChild(el("button", { type: "button", "aria-pressed": String(standView === o[0]), text: o[1], onclick: function () { standView = o[0]; drawStandings(); } }));
    });
    var teams = data.teams.slice(), G = data.goat || {};
    var read = data.standings_read ? new Date(data.standings_read) : null;
    $("rank-lede").textContent = standView === "goat" ? W("standings.lede_goat") : W("standings.lede", { date: read && !isNaN(read) ? read.toLocaleDateString(undefined, { month: "long", day: "numeric" }) : "" });
    $("goat-note").textContent = "";
    if (standView === "goat") {
      var head = el("div", { "class": "ranks-head", "aria-hidden": "true" });
      ["GOAT", "Team", "Record", "League"].forEach(function (h) { head.appendChild(el("span", { text: h })); });
      head.appendChild(el("span", { "class": "wide beat", text: W("standings.beat") }));
      head.appendChild(el("span", { "class": "wide lostto", text: W("standings.lost_to") }));
      var ol = el("ol", { "class": "ranks" }, teams.sort(by("goat")).map(function (t) {
        return el("li", {}, [el("span", { "class": "rk", text: String(t.goat) }), el("span", { "class": "who" }, [logo(t.id), teamA(t.id, t.name, "nm")]),
          el("span", { "class": "rec", text: record(t) }),
          el("span", { "class": "mv", text: String(t.rank), "aria-label": ordinal(t.rank) + " in the league standings" }), versus(t)]);
      }));
      holder.appendChild(head); holder.appendChild(ol);
      $("rank-note").textContent = W("standings.note_goat", { n: G.top });
      $("goat-note").textContent = W("standings.note_goat_how", { standings: G.standings_wrong, goat: G.goat_wrong });
      return;
    }
    if (standView === "league") holder.appendChild(standTable(teams.sort(by("rank")), "League"));
    else if (standView === "conference") groups("conf").forEach(function (c) {
      holder.appendChild(el("h3", { "class": "day", text: c + " Conference" }));
      holder.appendChild(standTable(teams.filter(function (t) { return t.conf === c; }).sort(by("conf_rank")), c));
    });
    else if (standView === "division") groups("conf").forEach(function (c) {
      groups("div").filter(function (d) { return teams.some(function (t) { return t.conf === c && t.div === d; }); }).forEach(function (d) {
        holder.appendChild(el("h3", { "class": "day", text: d + " Division" }));
        holder.appendChild(standTable(teams.filter(function (t) { return t.div === d; }).sort(by("div_rank")), d, null, 3));
      });
    });
    else groups("conf").forEach(function (c) {       // the playoff picture: three from each division, then two wild cards
      holder.appendChild(el("h2", { "class": "confhead", text: c + " Conference" }));
      var mine = teams.filter(function (t) { return t.conf === c; });
      groups("div").filter(function (d) { return mine.some(function (t) { return t.div === d; }); }).forEach(function (d) {
        holder.appendChild(el("h3", { "class": "day", text: d + " Division, top three" }));
        holder.appendChild(standTable(mine.filter(function (t) { return t.div === d && t.div_rank <= 3; }).sort(by("div_rank")), d));
      });
      var rest = mine.filter(function (t) { return t.div_rank > 3; }).sort(function (a, b) { return (a.wc || 99) - (b.wc || 99) || a.conf_rank - b.conf_rank; });
      holder.appendChild(el("h3", { "class": "day", text: "Wild card" }));
      holder.appendChild(standTable(rest, "Wild card", null, 2));
    });
    $("rank-note").textContent = W("standings.note") + (standView === "wildcard" || standView === "division" ? " " + W("standings.note_line") : "");
  }

  // ---- one game ----
  // [away, home] chances as whole percentages that add up to 100; never shown as 0 or 100
  function pct(home) { var n = Math.min(99, Math.max(1, Math.round(home * 100))); return [(100 - n) + "%", n + "%"]; }
  function oddsNote() {
    var t = data.odds_tested;
    return " " + W("games.odds_note") + (t ? " Tested on " + t.games.toLocaleString("en-US") + " past games, the favorite won " + Math.round(t.favorite_won * 100) + "% of the time." : "");
  }
  function liveTag() { return el("span", { "class": "livetag" }, [el("span", { "class": "dot", "aria-hidden": "true" }), W("games.live")]); }
  function periodName(n, type) { return type === "SO" ? "Shootout" : type === "OT" ? (n > 4 ? (n - 3) + "OT" : "OT") : ordinal(n); }
  // what is known about a game right now: the stored result, or the live score read from ESPN
  function now(g) {
    var L = g.live, fin = L ? L.state === "post" : g.state === "final", live = L ? L.state === "in" : g.state === "live";
    var as = L ? L.away : g.away.score, hs = L ? L.home : g.home.score;
    var end = fin ? (L && L.end) || g.end || "REG" : null;
    return { fin: fin, live: live, as: as, hs: hs, scored: (fin || live) && as != null && hs != null, end: end,
      detail: live ? (L && L.detail) || (g.period ? periodName(g.period[0], g.period[1]) + (g.period[1] === "REG" ? " period" : "") : "In progress") : "" };
  }
  function finalWord(end) { return "Final" + (end && end !== "REG" ? "/" + end : ""); }
  // `dated` puts the game's date above its time, for lists that are not grouped by day
  function row(g, dated) {
    var s = now(g), fin = s.fin, live = s.live;
    var awayWon = fin && s.scored && s.as > s.hs, homeWon = fin && s.scored && s.hs > s.as;
    var t = g.start ? new Date(g.start * 1000) : null;
    var note = !g.live && g.state === "other" ? (g.note || "Not played") : "";
    var when = fin ? finalWord(s.end) : live ? s.detail : note ? note : t && !isNaN(t) ? clockTime(t) : "Time not set";
    function team(side, x, lost, won) {
      var kids = [logo(x.id), teamA(x.id, x.name, "name"), rankTag(x.rank)];
      if (side === "home") kids.reverse();
      return el("span", { "class": "team " + side + (lost ? " lost" : "") + (won ? " won" : "") }, kids);
    }
    var mid = s.scored
      ? el("span", { "class": "mid", "aria-label": g.away.name + " " + s.as + ", " + g.home.name + " " + s.hs }, [
          el("span", { "class": "sa " + (homeWon ? "l" : "w"), text: String(s.as) }), el("span", { "class": "dash", text: "–" }),
          el("span", { "class": "sh " + (awayWon ? "l" : "w"), text: String(s.hs) })])
      : g.p != null && !fin && !note
        // not started: each team's chance of winning, the favorite in bold
        ? el("span", { "class": "mid odds", "aria-label": g.away.name + " " + pct(g.p)[0] + ", " + g.home.name + " " + pct(g.p)[1] + " chance of winning" }, [
            el("span", { "class": "sa " + (g.p > 0.5 ? "l" : "w"), text: pct(g.p)[0] }), el("span", { "class": "dash", text: "at" }),
            el("span", { "class": "sh " + (g.p < 0.5 ? "l" : "w"), text: pct(g.p)[1] })])
        : el("span", { "class": "mid at", text: "at" });
    var more = [];
    if (g.round) more.push(el("span", { "class": "round", text: g.round }));
    if (!fin && !note) {
      if (g.tv && g.tv.length) more.push(el("span", { "class": "watch" }, [el("span", { "class": "sr", text: "Watch on " }), g.tv.join(", ")]));
      else if (g.date <= addDays(today, 14)) more.push(el("span", { "class": "watch none", text: W("games.no_broadcast") }));
    }
    if (fin || live) more.push(el("a", { href: "#/game/" + g.id, text: live ? W("games.live_box_score") : W("games.box_score") }));
    var unplayed = !fin && !live && !note;
    var date = dated === true || dated === "1" ? el("span", { "class": "d", text: day(g.date).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) }) : null;
    return el("li", { "class": "game" + (live ? " on" : "") + (unplayed ? " ahead" : ""), "data-id": g.id, "data-dated": date ? "1" : null }, [
      live ? el("span", { "class": "when live" }, [date, liveTag(), " " + (when === "In progress" ? "" : when)]) : el("span", { "class": "when" }, [date, when]),
      team("away", g.away, homeWon, awayWon), mid, team("home", g.home, awayWon, homeWon),
      el("span", { "class": "more" }, more)]);
  }

  // ---- live scores ----
  // The site is rebuilt a few times a day (and every few minutes on game nights),
  // so while a game is on, the page reads ESPN's public scoreboard itself and
  // updates that game's row in place.
  var liveTimer = null, liveHooks = [];
  function ymd(g) { return g.date.replace(/-/g, ""); }
  function couldBeOn(g, t) { return g.start && g.state !== "final" && g.state !== "other" && !(g.live && g.live.state === "post") && t >= g.start - 900 && t <= g.start + 5 * 3600; }
  function nhlAbbr(a) { return (data.espn_abbr || {})[a] || a; }
  function readLive(e) {       // one ESPN event -> { key: "AWAY@HOME", state, detail, away, home, lines, end }
    var c = (e.competitions || [{}])[0], st = e.status || {}, type = st.type || {}, out = { state: type.state, detail: type.shortDetail || type.detail || "", lines: [[], []] };
    (c.competitors || []).forEach(function (x) {
      var side = x.homeAway === "home" ? "home" : "away";
      out[side] = x.score === "" || x.score == null ? null : +x.score;
      out[side + "Id"] = nhlAbbr((x.team || {}).abbreviation || "");
      out.lines[side === "home" ? 1 : 0] = (x.linescores || []).map(function (l) { return Math.round(l.value); });
    });
    if (out.state === "post") out.end = /SO/i.test(out.detail) ? "SO" : /OT/i.test(out.detail) ? "OT" : "REG";
    out.key = out.awayId + "@" + out.homeId;
    return out;
  }
  function pollLive() {
    clearTimeout(liveTimer);
    if (!data.live_feed) return;
    var t = Date.now() / 1000, due = data.games.filter(function (g) { return couldBeOn(g, t); }), every = (data.live_seconds || 20) * 1000;
    if (document.hidden) return;                       // picks up again when the tab is shown
    if (!due.length) {                                 // nothing on: look again when the next game is close
      var next = data.games.filter(function (g) { return g.start && g.state !== "final" && g.state !== "other" && g.start - 900 > t; })
        .map(function (g) { return g.start - 900; }).sort(function (a, b) { return a - b; })[0];
      if (next) liveTimer = setTimeout(pollLive, Math.min(Math.max((next - t) * 1000, every), 6 * 3600 * 1000));
      showLiveNote(false);
      return;
    }
    var dates = {};
    due.forEach(function (g) { dates[ymd(g)] = 1; });
    Promise.all(Object.keys(dates).map(function (d) {
      return fetch(data.live_feed + d, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : { events: [] }; })
        .then(function (doc) { return (doc.events || []).map(function (e) { var r = readLive(e); r.day = d; return r; }); }).catch(function () { return []; });
    })).then(function (lists) {
      var found = {};
      lists.forEach(function (list) { list.forEach(function (r) { found[r.day + " " + r.key] = r; }); });
      var anyLive = false;
      due.forEach(function (g) {
        var r = found[ymd(g) + " " + g.away.id + "@" + g.home.id];
        if (!r || (r.state !== "in" && r.state !== "post")) return;        // not started yet
        var live = { state: r.state, detail: r.detail, away: r.away, home: r.home, lines: r.lines, end: r.end };
        if (live.state === "in") anyLive = true;
        if (JSON.stringify(live) === JSON.stringify(g.live)) return;
        g.live = live;
        Array.prototype.forEach.call(document.querySelectorAll('.game[data-id="' + g.id + '"]'), function (li) { li.parentNode.replaceChild(row(g, li.getAttribute("data-dated")), li); });
        liveHooks.forEach(function (fn) { fn(g); });
      });
      showLiveNote(anyLive);
    }).then(function () { liveTimer = setTimeout(pollLive, every); });
  }
  function showLiveNote(on) {
    var n = $("live-note");
    n.hidden = !on;
    if (on) n.textContent = W("games.live_note", { seconds: data.live_seconds || 20 });
  }
  document.addEventListener("visibilitychange", function () { if (data && !document.hidden) pollLive(); });

  function listInto(holder, games, newestFirst) {
    var days = {}, order = [];
    games.forEach(function (g) { if (!days[g.date]) { days[g.date] = []; order.push(g.date); } days[g.date].push(g); });
    if (newestFirst) order.reverse();
    else if (order.indexOf(today) > 0) { order.splice(order.indexOf(today), 1); order.unshift(today); }   // today's games first
    order.forEach(function (d) {
      holder.appendChild(el("h3", { "class": "day" + (d === today ? " today" : ""), text: (d === today ? "Today, " : "") + long(d) }));
      holder.appendChild(el("ol", { "class": "games" }, days[d].map(function (g) { return row(g); })));
    });
  }

  // ---- the games page ----
  function draw() {
    var holder = $("list"), nav = $("nav"), head = $("h-list");
    holder.innerHTML = ""; nav.innerHTML = "";
    var teamsHere = data.teams.slice().sort(function (a, b) { return a.name.localeCompare(b.name); });
    if (state.team && !T(state.team)) state.team = null;
    // which side is which: over the columns on a wide screen, beside the two lines on a phone
    holder.appendChild(el("div", { "class": "hahead", "aria-hidden": "true" }, [el("span"), el("span", { "class": "ha away", text: W("games.away") }),
      el("span"), el("span", { "class": "ha home", text: W("games.home") }), el("span")]));
    var weeks = {};
    data.games.forEach(function (g) { weeks[monday(g.date)] = 1; });
    var first = Object.keys(weeks).sort()[0], last = Object.keys(weeks).sort().pop();
    var pick = el("select", { id: "f-team", "aria-label": "Show one team", onchange: function () { state.team = pick.value || null; draw(); } },
      [el("option", { value: "", text: W("games.all_teams") })].concat(teamsHere.map(function (x) {
        return el("option", { value: x.id, text: x.name, selected: x.id === state.team });
      })));
    nav.appendChild(pick);

    if (state.team) {
      var t = T(state.team);
      var mine = data.games.filter(function (g) { return g.away.id === t.id || g.home.id === t.id; });
      head.innerHTML = "";
      head.appendChild(logo(t.id));
      head.appendChild(document.createTextNode(" " + t.name + ", whole season"));
      var next = mine.filter(function (g) { return g.state !== "final" && g.date >= today; }), done = mine.filter(function (g) { return g.state === "final" || g.date < today; });
      if (next.length) { holder.appendChild(el("p", { "class": "note", text: next.length + " still to play, " + done.length + " played." + oddsNote() })); listInto(holder, next); }
      if (done.length) { holder.appendChild(el("h3", { "class": "day", text: "Already played, newest first" })); listInto(holder, done, true); }
      if (!mine.length) holder.appendChild(el("p", { "class": "empty", text: "No games are listed for " + t.name + " this season." }));
      return;
    }

    if (!state.week) {       // open on this week, or the nearest week that has games
      var nowWeek = monday(today);
      state.week = !first ? nowWeek : nowWeek < first ? first : nowWeek > last ? last : nowWeek;
    }
    var w = state.week, end = addDays(w, 6), thisWeek = monday(today);
    var games = data.games.filter(function (g) { return g.date >= w && g.date <= end; });
    head.textContent = (w === thisWeek ? "This week, " : "Week of ") + short(w) + " to " + short(end);
    nav.appendChild(el("button", { type: "button", text: W("games.earlier"), disabled: !first || w <= first, onclick: function () { state.week = addDays(w, -7); draw(); } }));
    if (w !== thisWeek && first && thisWeek >= first && thisWeek <= last) nav.appendChild(el("button", { type: "button", text: W("games.this_week"), onclick: function () { state.week = thisWeek; draw(); } }));
    nav.appendChild(el("button", { type: "button", text: W("games.later"), disabled: !last || w >= last, onclick: function () { state.week = addDays(w, 7); draw(); } }));
    if (!games.length) {
      holder.appendChild(el("p", { "class": "empty", text: "No games this week. Try an earlier or later week." }));
      return;
    }
    listInto(holder, games);
    holder.appendChild(el("p", { "class": "note", text: games.length + " games this week. " + W("games.note") }));
    if (games.some(function (g) { return g.p != null && g.state !== "final"; })) holder.appendChild(el("p", { "class": "note", text: oddsNote().trim() }));
  }

  // ---- players ----
  var roster = null, pstate = { grp: "sk", team: "", q: "", all: false, sort: "impact_gp", dir: -1, limit: 200 };
  var POS_ONE = { C: "Center", L: "Left Wing", R: "Right Wing", D: "Defenseman", G: "Goalie" };
  var GRP_MANY = { F: "forwards", D: "defensemen", G: "goalies" };
  var fmt = {
    n: function (v) { return String(v); },
    d1: function (v) { return v.toFixed(1); }, d2: function (v) { return v.toFixed(2); },
    s1: function (v) { var t = Math.abs(v).toFixed(1); return (+t === 0 ? "" : v > 0 ? "+" : "−") + t; },
    s2: function (v) { var t = Math.abs(v).toFixed(2); return (+t === 0 ? "" : v > 0 ? "+" : "−") + t; },
    pm: function (v) { return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v); },
    pct: function (v) { return v.toFixed(1) + "%"; },
    sv: function (v) { return (v / 100).toFixed(3).replace(/^0/, ""); },
    min: function (v) { var s = Math.round(v * 60); return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2); }
  };
  function mmss(sec) { return Math.floor(sec / 60) + ":" + ("0" + (sec % 60)).slice(-2); }
  // key, label, what it means, format
  var CARD_SK = [
    ["Impact, in points added per game", [
      ["impact_gp", "All of it", "Everything below added together", fmt.s2],
      ["goals", "Goals", "Goals, at 0.75 each, beyond what an average player at his position scores in the same ice time", fmt.s2],
      ["assists", "Assists", "First assists at 0.70 and second assists at 0.55, beyond the average in the same ice time", fmt.s2],
      ["shots", "Shots", "Shots on goal, at 0.075 each, beyond the average in the same ice time", fmt.s2],
      ["defense", "Defense", "Blocked shots at 0.05, takeaways at 0.03 and giveaways at minus 0.03, beyond the average in the same ice time", fmt.s2],
      ["discipline", "Discipline", "Minor penalties drawn minus minor penalties taken, at 0.15 each, beyond the average", fmt.s2],
      ["onice", "On the ice", "Plus-minus: goals for minus goals against while he is on the ice, power plays aside, at 0.15 each", fmt.s2]]],
    ["Scoring, per 60 minutes", [
      ["g60", "Goals", "Goals per 60 minutes of ice time", fmt.d2], ["a160", "First assists", "The last pass before a goal, per 60 minutes", fmt.d2],
      ["p60", "Points", "Goals and assists per 60 minutes", fmt.d2], ["sog60", "Shots on goal", "Per 60 minutes", fmt.d1],
      ["shp", "Shooting percentage", "Share of his shots on goal that went in; only with at least 10 shots", fmt.pct]]],
    ["Ice time, defense and discipline", [
      ["toi_gp", "Ice time per game", "Minutes and seconds", fmt.min], ["hits60", "Hits", "Per 60 minutes", fmt.d1],
      ["blk60", "Blocked shots", "Per 60 minutes", fmt.d1], ["tk60", "Takeaways", "Per 60 minutes", fmt.d1],
      ["gv60", "Giveaways", "Per 60 minutes. Fewer is better, so a long bar means few giveaways", fmt.d1],
      ["pd60", "Penalties drawn", "Minor penalties drawn per 60 minutes", fmt.d2],
      ["pim60", "Penalty minutes", "Per 60 minutes. Fewer is better, so a long bar means few minutes", fmt.d1]]]
  ];
  var CARD_G = [
    ["Impact, in points added per game", [
      ["impact_gp", "All of it", "Goals saved beyond an average goalie on the same shots, at 0.75 a goal", fmt.s2],
      ["g_ev", "At even strength", "Goals saved beyond average on even-strength shots", fmt.s2],
      ["g_pk", "Against the power play", "Goals saved beyond average while his team is shorthanded", fmt.s2],
      ["g_sh", "On his team's power play", "Goals saved beyond average on shorthanded shots against", fmt.s2]]],
    ["Goaltending", [
      ["svp", "Save percentage", "Share of shots on goal saved", fmt.sv], ["gaa", "Goals against average", "Goals allowed per 60 minutes. Fewer is better, so a long bar means few goals", fmt.d2],
      ["gsaa60", "Goals saved above average", "Per 60 minutes, against an average goalie on the same shots", fmt.s2],
      ["es_svp", "Even-strength save percentage", "", fmt.sv], ["pk_svp", "Save percentage against the power play", "", fmt.sv],
      ["sa60", "Shots faced", "Per 60 minutes: how busy he is", fmt.d1]]]
  ];
  function val(p, key) { return p.v[roster.metrics.indexOf(key)]; }
  function pctOf(p, key) { return p.pct[roster.metrics.indexOf(key)]; }
  function loadRoster() {
    if (roster) return Promise.resolve(roster);
    return fetch("players.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { roster = d; return d; });
  }

  var PCOLS = [   // key, heading, meaning, getter, format, sorts high to low first
    ["rank", "#", "Rank by Impact per game among regular skaters", function (p) { return p.rank; }, fmt.n, 0],
    ["name", "Player", "", function (p) { return p.name; }, null, 0],
    ["team", "Team", "", function (p) { return p.team; }, null, 0],
    ["pos", "Pos", "C Center, L Left Wing, R Right Wing, D Defenseman", function (p) { return p.pos; }, fmt.n, 0],
    ["gp", "GP", "Games played", function (p) { return p.gp; }, fmt.n, 1],
    ["toi_gp", "TOI", "Ice time per game", function (p) { return val(p, "toi_gp"); }, fmt.min, 1],
    ["impact", "Impact", "Points added this season over an average player at his position", function (p) { return p.impact; }, fmt.s1, 1],
    ["impact_gp", "Per game", "Impact per game played", function (p) { return val(p, "impact_gp"); }, fmt.s2, 1],
    ["g", "G", "Goals", function (p) { return p.tot.g; }, fmt.n, 1],
    ["a", "A", "Assists", function (p) { return p.tot.a; }, fmt.n, 1],
    ["pts", "PTS", "Points: goals plus assists", function (p) { return p.tot.pts; }, fmt.n, 1],
    ["pm", "+/−", "Plus-minus", function (p) { return p.tot.pm; }, fmt.pm, 1],
    ["sog", "SOG", "Shots on goal", function (p) { return p.tot.sog; }, fmt.n, 1],
    ["hits", "Hits", "", function (p) { return p.tot.hits; }, fmt.n, 1],
    ["blk", "BLK", "Blocked shots", function (p) { return p.tot.blk; }, fmt.n, 1],
    ["pim", "PIM", "Penalty minutes", function (p) { return p.tot.pim; }, fmt.n, 1]
  ];
  var GCOLS = [
    ["rank", "#", "Rank by Impact per game among regular goalies", function (p) { return p.rank; }, fmt.n, 0],
    ["name", "Player", "", function (p) { return p.name; }, null, 0],
    ["team", "Team", "", function (p) { return p.team; }, null, 0],
    ["gp", "GP", "Games played", function (p) { return p.gp; }, fmt.n, 1],
    ["gs", "GS", "Games started", function (p) { return p.tot.gs; }, fmt.n, 1],
    ["rec", "W-L-OT", "Wins, losses and overtime losses", function (p) { return p.tot.w - p.tot.l; }, null, 1],
    ["impact", "Impact", "Points added this season over an average goalie", function (p) { return p.impact; }, fmt.s1, 1],
    ["impact_gp", "Per game", "Impact per game played", function (p) { return val(p, "impact_gp"); }, fmt.s2, 1],
    ["sa", "SA", "Shots against", function (p) { return p.tot.sa; }, fmt.n, 1],
    ["ga", "GA", "Goals against", function (p) { return p.tot.ga; }, fmt.n, 0],
    ["svp", "Sv%", "Save percentage", function (p) { return val(p, "svp"); }, fmt.sv, 1],
    ["gaa", "GAA", "Goals against per 60 minutes", function (p) { return val(p, "gaa"); }, fmt.d2, 0],
    ["gsaa", "GSAA", "Goals saved above an average goalie on the same shots", function (p) { return p.tot.gsaa; }, fmt.s1, 1],
    ["so", "SO", "Shutouts", function (p) { return p.tot.so; }, fmt.n, 1]
  ];
  function playerCell(p, c, sortKey, withFace) {
    if (c[0] === "name") return el("td", { "class": "l nm" }, [el("a", { href: "#/player/" + p.id }, [withFace ? face(p) : null, el("span", { text: p.name })])]);
    if (c[0] === "team") return el("td", { "class": "l" }, [el("span", { "class": "tcell tm" }, [logo(p.team_id), teamA(p.team_id, (T(p.team_id) || {}).short || p.team)])]);
    if (c[0] === "rec") return el("td", { "class": sortKey === c[0] ? "sorted" : "", text: p.tot.w + "-" + p.tot.l + "-" + p.tot.otl });
    var v = c[3](p);
    return el("td", { "class": (c[0] === "impact_gp" ? "strong " : "") + (sortKey === c[0] ? "sorted" : ""), text: v == null ? (c[0] === "rank" ? "–" : "") : c[4](v) });
  }
  function drawPlayers() {
    var bar = $("p-filters"), holder = $("p-list");
    bar.innerHTML = ""; holder.innerHTML = "";
    holder.appendChild(el("p", { "class": "empty", text: "Loading the players…" }));
    loadRoster().then(function () {
      function pick(label, value, options, set) {
        var s = el("select", { "aria-label": label, onchange: function () { set(s.value); pstate.limit = 200; table(); } },
          options.map(function (o) { return el("option", { value: o[0], text: o[1], selected: o[0] === value }); }));
        return s;
      }
      bar.appendChild(pick("Position", pstate.grp, [["sk", "All skaters"], ["F", "Forwards"], ["C", "Centers"], ["W", "Wingers"], ["D", "Defensemen"], ["G", "Goalies"]], function (v) {
        if ((v === "G") !== (pstate.grp === "G")) { pstate.sort = "impact_gp"; pstate.dir = -1; }
        pstate.grp = v;
      }));
      bar.appendChild(pick("Team", pstate.team, [["", W("games.all_teams")]].concat(data.teams.slice().sort(function (a, b) { return a.name.localeCompare(b.name); })
        .map(function (t) { return [t.id, t.name]; })), function (v) { pstate.team = v; }));
      var q = el("input", { type: "search", placeholder: "Find a player", "aria-label": "Find a player", value: pstate.q, oninput: function () { pstate.q = q.value; pstate.limit = 200; table(); } });
      bar.appendChild(q);
      var chk = el("input", { type: "checkbox", id: "p-all", checked: pstate.all, onchange: function () { pstate.all = chk.checked; table(); } });
      bar.appendChild(el("label", { "class": "check", "for": "p-all" }, [chk, " Include part-time players"]));

      function table() {
        holder.innerHTML = "";
        var goalies = pstate.grp === "G", cols = goalies ? GCOLS : PCOLS;
        var needle = pstate.q.trim().toLowerCase(), col = cols.filter(function (c) { return c[0] === pstate.sort; })[0] || cols[0];
        var want = { sk: function (p) { return p.grp !== "G"; }, F: function (p) { return p.grp === "F"; }, C: function (p) { return p.pos === "C"; },
          W: function (p) { return p.pos === "L" || p.pos === "R"; }, D: function (p) { return p.grp === "D"; }, G: function (p) { return p.grp === "G"; } }[pstate.grp];
        var rows = roster.players.filter(function (p) {
          return want(p) && (pstate.all || p.regular) && (!pstate.team || p.team_id === pstate.team) && (!needle || p.name.toLowerCase().indexOf(needle) >= 0);
        }).sort(function (a, b) {
          var x = col[3](a), y = col[3](b);
          if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
          return (typeof x === "string" ? pstate.dir * x.localeCompare(y) : pstate.dir * (x - y)) || (a.rank || 1e6) - (b.rank || 1e6);
        });
        if (!rows.length) {
          holder.appendChild(el("p", { "class": "empty", text: roster.players.length ? "No player matches. Clear the search, choose all teams, or include part-time players." : "No games have a box score yet. Players appear here after the first games of the season." }));
          return;
        }
        var head = el("tr", {}, cols.map(function (c) {
          var on = col[0] === c[0];
          return el("th", { scope: "col", "class": c[0] === "name" || c[0] === "team" ? "l" : "", "aria-sort": on ? (pstate.dir > 0 ? "ascending" : "descending") : null }, [
            el("button", { type: "button", title: c[2] || null, text: c[1] + (on ? (pstate.dir > 0 ? " ▲" : " ▼") : ""),
              onclick: function () { if (on) pstate.dir = -pstate.dir; else { pstate.sort = c[0]; pstate.dir = c[5] ? -1 : 1; } table(); } })]);
        }));
        var total = rows.length, limit = pstate.limit || 200;
        rows = rows.slice(0, limit);
        var body = el("tbody", {}, rows.map(function (p) { return el("tr", { "class": p.regular ? "" : "part" }, cols.map(function (c) { return playerCell(p, c, col[0]); })); }));
        holder.appendChild(el("div", { "class": "tablewrap", tabindex: "0", role: "region", "aria-label": "Players table, scrolls sideways" }, [
          el("table", { "class": "ptable pltable tptable" }, [el("thead", {}, [head]), body])]));
        if (total > rows.length) holder.appendChild(el("p", { "class": "more" }, [el("button", { type: "button", "class": "morebtn", text: "Show " + Math.min(400, total - rows.length) + " more of " + total,
          onclick: function () { pstate.limit = limit + 400; table(); } })]));
        var share = Math.round(100 * (goalies ? roster.weights.regular_goalie : roster.weights.regular_share));
        holder.appendChild(el("p", { "class": "note", text: total + (goalies ? " goalies" : " skaters") + (roster.through ? ", through games of " + short(roster.through) : "") +
          ". A regular has played at least " + share + "% of his team's games; only regulars are ranked. Choose a name for his card, or a column heading to sort." }));
        holder.appendChild(el("p", { "class": "note", text: goalies ? W("players.note_goalies") : W("players.note") }));
      }
      table();
    }).catch(function () {
      holder.innerHTML = "";
      holder.appendChild(el("p", { "class": "empty", text: "The players could not be loaded. Reload the page to try again." }));
    });
  }

  // His height, weight, hand, age and birthplace, from his team's roster.
  function bioLine(p) {
    var b = p.bio;
    if (!b) return null;
    var bits = [];
    if (b.ht) bits.push(Math.floor(b.ht / 12) + "′" + (b.ht % 12) + "″");
    if (b.wt) bits.push(b.wt + " lb");
    if (b.sh) bits.push((p.grp === "G" ? "Catches " : "Shoots ") + (b.sh === "L" ? "left" : b.sh === "R" ? "right" : b.sh));
    if (b.born) {
      var d = new Date(b.born + "T12:00:00"), nowD = new Date(), age = nowD.getFullYear() - d.getFullYear();
      if (nowD.getMonth() < d.getMonth() || (nowD.getMonth() === d.getMonth() && nowD.getDate() < d.getDate())) age--;
      if (age > 15 && age < 55) bits.push("Age " + age);
    }
    if (b.from) bits.push(b.from);
    return bits.length ? el("p", { "class": "pc-bio", text: bits.join(" · ") }) : null;
  }

  function drawCard(id) {
    var holder = $("card");
    holder.innerHTML = "";
    loadRoster().then(function () {
      var p = roster.players.filter(function (x) { return String(x.id) === String(id); })[0];
      if (!p) { holder.appendChild(el("p", { "class": "empty", text: "There is no card for that player. He may not have played a game yet this season." })); return; }
      document.title = p.name + " | " + data.site;
      var goalie = p.grp === "G", many = GRP_MANY[p.grp], nPos = roster.pos_regulars[p.grp] || 0, tot = p.tot;
      var pool = goalie ? nPos : roster.regulars;
      var art = el("article", { "class": "pcard" });
      art.appendChild(el("header", { "class": "pc-head" }, [
        face(p, "big"),
        el("div", { "class": "pc-id" }, [
          el("h1", { text: p.name }),
          el("p", { "class": "pc-team" }, [logo(p.team_id), teamA(p.team_id, p.team), p.team_rank ? el("span", { text: " (" + ordinal(p.team_rank) + " in the standings)" }) : null]),
          el("p", { text: (p.num != null ? "No. " + p.num + ", " : "") + (POS_ONE[p.pos] || p.pos) }),
          bioLine(p),
          el("p", { "class": "pc-sub", text: goalie ? p.gp + " games, " + tot.gs + " starts, " + tot.w + "-" + tot.l + "-" + tot.otl
            : p.gp + " games, " + fmt.min(val(p, "toi_gp")) + " of ice time a game" })]),
        el("div", { "class": "pc-rank" }, p.regular ? [
          el("b", { text: ordinal(p.rank) }), el("span", { text: "of " + pool + " regular " + (goalie ? "goalies" : "skaters") }),
          goalie ? null : el("span", { text: ordinal(p.pos_rank) + " of " + nPos + " " + many })] : [
          el("b", { text: "–" }), el("span", { text: "Not ranked: too few games" })])
      ]));
      art.appendChild(el("p", { "class": "pc-impact" }, [el("b", { text: fmt.s1(p.impact) }), " points added this season, ", el("b", { text: fmt.s2(val(p, "impact_gp")) }), " per game."]));
      var CARD = goalie ? CARD_G : CARD_SK;
      CARD.forEach(function (sec, i) {
        var rows = sec[1].filter(function (m) { return pctOf(p, m[0]) != null; });
        if (!rows.length) return;
        var box = el("section", { "class": "pc-sec" }, [el("h2", { text: sec[0] })]);
        if (i === 0) box.appendChild(el("p", { "class": "pc-secnote", text: goalie ? "Against an average NHL goalie facing the same shots." : "Against an average NHL " + (p.grp === "D" ? "defenseman" : "forward") + " in the same ice time." }));
        rows.forEach(function (m) {
          var pc = pctOf(p, m[0]), v = val(p, m[0]);
          box.appendChild(el("div", { "class": "prow", title: m[2] || null }, [
            el("span", { "class": "plabel", text: m[1] }),
            el("span", { "class": "ptrack", role: "img", "aria-label": m[1] + ": " + ordinal(pc) + " percentile" }, [
              el("i", { "class": pc >= 67 ? "hi" : pc >= 34 ? "mid" : "lo", style: "width:" + Math.max(pc, 2) + "%" })]),
            el("b", { "class": "ppct", text: String(pc) }),
            el("span", { "class": "pval", text: v == null ? "" : m[3](v) })]));
        });
        art.appendChild(box);
      });
      if (!p.regular) art.appendChild(el("p", { "class": "note", text: "Percentiles are given only to regulars: players with at least " + Math.round(100 * (goalie ? roster.weights.regular_goalie : roster.weights.regular_share)) + "% of their team's games." }));
      else if (pctOf(p, "impact_gp") == null) art.appendChild(el("p", { "class": "note", text: "Percentiles appear once enough " + many + " have played regularly to compare him with." }));
      var totals = goalie ? [["Games", p.gp], ["Starts", tot.gs], ["Wins", tot.w], ["Losses", tot.l], ["Overtime losses", tot.otl], ["Shots against", tot.sa], ["Saves", tot.sv],
          ["Goals against", tot.ga], ["Shutouts", tot.so], ["Goals saved above average", fmt.s1(tot.gsaa)], ["Minutes", Math.round(tot.toi / 60)]]
        : [["Games", p.gp], ["Goals", tot.g], ["Assists", tot.a], ["First assists", tot.a1], ["Points", tot.pts], ["Plus-minus", fmt.pm(tot.pm)], ["Shots on goal", tot.sog],
          ["Power-play goals", tot.ppg], ["Hits", tot.hits], ["Blocked shots", tot.blk], ["Takeaways", tot.tk], ["Giveaways", tot.gv], ["Penalty minutes", tot.pim],
          ["Penalties drawn", tot.pd], ["Minutes", Math.round(tot.toi / 60)]];
      art.appendChild(el("section", { "class": "pc-sec" }, [el("h2", { text: "Season totals" }),
        el("dl", { "class": "totals" }, totals.map(function (x) { return el("div", {}, [el("dt", { text: x[0] }), el("dd", { text: String(x[1]) })]); }))]));
      art.appendChild(el("p", { "class": "note" }, ["The number beside each bar is his percentile among " + many + " who play regularly: 90 means better than 90% of them. The tick marks the middle." +
        (roster.through ? " Regular season, through games of " + short(roster.through) + ". " : " "),
        data.player_page ? el("a", { href: data.player_page + p.id, rel: "noopener", text: W("players.nhl_link") }) : null]));
      var defs = [];
      CARD.forEach(function (sec) { sec[1].forEach(function (m) { if (m[2] && pctOf(p, m[0]) != null) defs.push(el("div", {}, [el("dt", { text: m[1] }), el("dd", { text: m[2] + "." })])); }); });
      if (defs.length) art.appendChild(el("details", { "class": "defs" }, [el("summary", { text: "What each line measures" }), el("dl", {}, defs)]));
      holder.appendChild(art);
    }).catch(function () {
      holder.appendChild(el("p", { "class": "empty", text: "The card could not be loaded. Reload the page to try again." }));
    });
  }

  // ---- the teams page: each team's stats, from box scores ----
  var tstate = { sort: "rank", dir: 1 };
  var teamStats = null;
  function loadTeams() {
    if (teamStats) return Promise.resolve(teamStats);
    return fetch("teams.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { teamStats = d; return d; });
  }
  var TCOLS = [   // key, heading, meaning, getter, format, sorts high to low first
    ["rank", "Rank", "Place in the league standings", function (t) { return t.rank; }, String, 0],
    ["name", "Team", "", function (t) { return t.name; }, null, 0],
    ["rec", "W-L-OT", "Wins, regulation losses and overtime or shootout losses", function (t) { return t.pct; }, null, 1],
    ["pts", "PTS", "Points", function (t) { return t.pts; }, String, 1],
    ["gf_gp", "GF/G", "Goals per game, shootout goals aside", function (t) { return t.gf_gp; }, fmt.d2, 1],
    ["ga_gp", "GA/G", "Goals against per game. Lower is better", function (t) { return t.ga_gp; }, fmt.d2, 0],
    ["sf_gp", "SF/G", "Shots on goal per game", function (t) { return t.sf_gp; }, fmt.d1, 1],
    ["sa_gp", "SA/G", "Shots on goal against per game. Lower is better", function (t) { return t.sa_gp; }, fmt.d1, 0],
    ["sh_pct", "Sh%", "Share of the team's shots on goal that went in", function (t) { return t.sh_pct; }, fmt.d1, 1],
    ["sv_pct", "Sv%", "Share of opponents' shots on goal kept out, empty-net goals included", function (t) { return t.sv_pct; }, function (v) { return v.toFixed(3).replace(/^0/, ""); }, 1],
    ["pp_pct", "PP%", "Power plays that ended in a goal", function (t) { return t.pp_pct; }, fmt.d1, 1],
    ["pk_pct", "PK%", "Opponents' power plays killed off", function (t) { return t.pk_pct; }, fmt.d1, 1],
    ["fo_pct", "FO%", "Faceoffs won", function (t) { return t.fo_pct; }, fmt.d1, 1],
    ["hits_gp", "Hits/G", "Hits per game", function (t) { return t.hits_gp; }, fmt.d1, 1],
    ["blk_gp", "BLK/G", "Blocked shots per game", function (t) { return t.blk_gp; }, fmt.d1, 1],
    ["pim_gp", "PIM/G", "Penalty minutes per game. Lower is better", function (t) { return t.pim_gp; }, fmt.d1, 0],
    ["power", "Rating", "Where this site's rating (the one behind the odds) places the team", function (t) { return t.power; }, String, 0],
    ["sos_rank", "SOS", "Strength of schedule: 1 is the hardest, by the average rating of the teams played", function (t) { return t.sos_rank; }, String, 0]
  ];
  function drawTeams() {
    var holder = $("t-list");
    holder.innerHTML = "";
    holder.appendChild(el("p", { "class": "empty", text: "Loading the team stats…" }));
    loadTeams().then(function (d) {
      function table() {
        holder.innerHTML = "";
        var col = TCOLS.filter(function (c) { return c[0] === tstate.sort; })[0];
        var rows = d.teams.slice().sort(function (a, b) {
          var x = col[3](a), y = col[3](b);
          if (x == null && y == null) return a.rank - b.rank; if (x == null) return 1; if (y == null) return -1;
          return (typeof x === "string" ? tstate.dir * x.localeCompare(y) : tstate.dir * (x - y)) || a.rank - b.rank;
        });
        var head = el("tr", {}, TCOLS.map(function (c) {
          var on = tstate.sort === c[0];
          return el("th", { scope: "col", "class": c[0] === "name" ? "l" : "", "aria-sort": on ? (tstate.dir > 0 ? "ascending" : "descending") : null }, [
            el("button", { type: "button", title: c[2] || null, text: c[1] + (on ? (tstate.dir > 0 ? " ▲" : " ▼") : ""),
              onclick: function () { if (on) tstate.dir = -tstate.dir; else { tstate.sort = c[0]; tstate.dir = c[5] ? -1 : 1; } table(); } })]);
        }));
        var body = el("tbody", {}, rows.map(function (t) {
          return el("tr", {}, TCOLS.map(function (c) {
            var cls = tstate.sort === c[0] ? "sorted" : "";
            if (c[0] === "rank") return el("td", { "class": cls }, [rankTag(t.rank)]);
            if (c[0] === "name") return el("td", { "class": "l " + cls }, [el("span", { "class": "tcell" }, [logo(t.id), teamA(t.id, t.name)])]);
            if (c[0] === "rec") return el("td", { "class": cls, text: record(t) });
            var v = c[3](t);
            return el("td", { "class": cls + (c[0] === "pts" ? " strong" : ""), text: v == null ? "" : c[4](v) });
          }));
        }));
        holder.appendChild(el("div", { "class": "tablewrap", tabindex: "0", role: "region", "aria-label": "Team stats table, scrolls sideways" }, [
          el("table", { "class": "ptable ttable" }, [el("thead", {}, [head]), body])]));
        holder.appendChild(el("p", { "class": "note", text: (d.through ? "Regular season, through games of " + short(d.through) + ". " : "") + W("teams.note") }));
      }
      table();
    }).catch(function () {
      holder.innerHTML = "";
      holder.appendChild(el("p", { "class": "empty", text: "The team stats could not be loaded. Reload the page to try again." }));
    });
  }

  // ---- a game's own page: the score by period, the goals, the three stars and both teams' box scores ----
  var gameTimers = [];
  function stopGame() { gameTimers.forEach(clearTimeout); gameTimers = []; liveHooks = []; }
  // a skater's row in a game file: [id, num, name, pos, g, a, pm, sog, hits, blk, pim, toi, shifts, gv, tk, fo, ppg, photo]
  var BCOLS = [
    ["G", "Goals", function (r) { return r[4]; }], ["A", "Assists", function (r) { return r[5]; }], ["PTS", "Points", function (r) { return r[4] + r[5]; }],
    ["+/−", "Plus-minus", function (r) { return r[6] == null ? "" : fmt.pm(r[6]); }], ["SOG", "Shots on goal", function (r) { return r[7]; }],
    ["Hits", "Hits", function (r) { return r[8]; }], ["BLK", "Blocked shots", function (r) { return r[9]; }], ["PIM", "Penalty minutes", function (r) { return r[10]; }],
    ["GV", "Giveaways", function (r) { return r[13]; }], ["TK", "Takeaways", function (r) { return r[14]; }],
    ["FO%", "Faceoffs won, for players who took any", function (r) { return r[15] ? r[15] + "%" : ""; }],
    ["Shifts", "Shifts", function (r) { return r[12]; }], ["TOI", "Time on ice", function (r) { return r[11] == null ? "" : mmss(r[11]); }]
  ];
  function who(id, name, photo) {
    var known = roster && roster.players.some(function (p) { return p.id === id; });
    return el(known || !roster ? "a" : "span", { href: known || !roster ? "#/player/" + id : null, "class": known || !roster ? null : "plain" }, [face({ name: name, photo: photo }), el("span", { text: name })]);
  }
  function boxTable(rows, name) {
    var tot = [null, null, "Team", "", 0, 0, null, 0, 0, 0, 0, null, null, 0, 0, null];
    rows.forEach(function (r) { [4, 5, 7, 8, 9, 10, 13, 14].forEach(function (i) { tot[i] += r[i] || 0; }); });
    var head = el("tr", {}, [el("th", { scope: "col", "class": "l", text: "#" }), el("th", { scope: "col", "class": "l", text: name + " skaters" }), el("th", { scope: "col", title: "Position", text: "Pos" })]
      .concat(BCOLS.map(function (c) { return el("th", { scope: "col", title: c[1], text: c[0] }); })));
    rows = rows.slice().sort(function (a, b) { return ((a[3] === "D") - (b[3] === "D")) || (b[11] - a[11]); });   // forwards first, then by ice time
    var body = el("tbody", {}, rows.map(function (r) {
      return el("tr", { "class": r[3] === "D" ? "dman" : "" }, [el("td", { "class": "l", text: r[1] == null ? "" : String(r[1]) }), el("td", { "class": "l nm" }, [who(r[0], r[2], r[17])]), el("td", { text: r[3] })]
        .concat(BCOLS.map(function (c) { return el("td", { "class": c[0] === "PTS" && r[4] + r[5] > 0 ? "strong" : "", text: String(c[2](r)) }); })));
    }));
    var foot = el("tfoot", {}, [el("tr", {}, [el("td", {}), el("td", { "class": "l", text: "Team" }), el("td", {})].concat(BCOLS.map(function (c) { var v = c[2](tot); return el("td", { text: v == null || (typeof v === "number" && isNaN(v)) ? "" : String(v) }); })))]);
    return el("div", { "class": "tablewrap", tabindex: "0", role: "region", "aria-label": name + " skaters, scrolls sideways" }, [
      el("table", { "class": "ptable btable" }, [el("thead", {}, [head]), body, foot])]);
  }
  // a goalie's row: [id, num, name, sa, sv, ga, toi, start, dec, photo]
  function goalieTable(rows, name) {
    var cols = [["SA", "Shots against", function (r) { return r[3]; }], ["SV", "Saves", function (r) { return r[4]; }], ["GA", "Goals against", function (r) { return r[5]; }],
      ["Sv%", "Save percentage", function (r) { return r[3] ? (r[4] / r[3]).toFixed(3).replace(/^0/, "") : ""; }], ["TOI", "Time on ice", function (r) { return mmss(r[6]); }],
      ["Dec", "Decision: W win, L loss, O overtime or shootout loss", function (r) { return r[8] || ""; }]];
    var head = el("tr", {}, [el("th", { scope: "col", "class": "l", text: "#" }), el("th", { scope: "col", "class": "l", text: name + " goalies" })]
      .concat(cols.map(function (c) { return el("th", { scope: "col", title: c[1], text: c[0] }); })));
    var body = el("tbody", {}, rows.slice().sort(function (a, b) { return b[7] - a[7]; }).map(function (r) {
      return el("tr", {}, [el("td", { "class": "l", text: r[1] == null ? "" : String(r[1]) }), el("td", { "class": "l nm" }, [who(r[0], r[2], r[9])])]
        .concat(cols.map(function (c) { return el("td", { text: String(c[2](r)) }); })));
    }));
    return el("div", { "class": "tablewrap gtable", tabindex: "0", role: "region", "aria-label": name + " goalies" }, [el("table", { "class": "ptable btable" }, [el("thead", {}, [head]), body])]);
  }
  // ---- the score card at the top of a game's page ----
  function scoreLine(g) {
    var s = now(g), t = g.start ? new Date(g.start * 1000) : null;
    function team(x, n, other) {
      var won = s.fin && n != null && n > other, lost = s.fin && n != null && n < other;
      return el("div", { "class": "gc-team" + (won ? " won" : "") + (lost ? " lost" : "") }, [logo(x.id, "gc"),
        el("div", { "class": "gc-name" }, [rankTag(x.rank), teamA(x.id, (T(x.id) || {}).name || x.name)]),
        el("b", { "class": "gc-sets", text: !s.scored || n == null ? "–" : String(n) })]);
    }
    var mid = s.fin ? finalWord(s.end) : s.live ? "" : (t && !isNaN(t) ? clockTime(t) : "");
    return el("div", { "class": "gc-score" }, [team(g.away, s.as, s.hs), el("div", { "class": "gc-mid" }, s.live ? [liveTag(), el("span", { "class": "gc-clock", text: s.detail })] : [el("span", { text: mid })]), team(g.home, s.hs, s.as)]);
  }
  function oddsLine(g) {
    var p = g.p != null ? g.p : g.p0;
    if (p == null) return null;
    var two = pct(p);
    return el("div", { "class": "gc-odds" }, [
      el("span", { "class": "gc-lab", text: g.p != null && !(g.start && Date.now() / 1000 > g.start) ? "Chance of winning" : "Chance of winning before the game" }),
      el("div", { "class": "gc-bar" }, [el("span", { "class": "a", style: "width:" + two[0], text: g.away.name + " " + two[0] }),
        el("span", { "class": "h", style: "width:" + two[1], text: two[1] + " " + g.home.name })])]);
  }
  function periodTable(holder, g, lines) {      // lines: [[number, type, away, home], ...]
    holder.innerHTML = "";
    if (!lines || !lines.length) return;
    var s = now(g), head = el("tr", {}, [el("th", { scope: "col", "class": "l", text: "Period" })]);
    lines.forEach(function (p) { head.appendChild(el("th", { scope: "col", title: p[1] === "SO" ? "Shootout: one goal to the winner" : null, text: p[1] === "SO" ? "SO" : periodName(p[0], p[1]) })); });
    if (s.end === "SO" && !lines.some(function (p) { return p[1] === "SO"; })) head.appendChild(el("th", { scope: "col", title: "Shootout", text: "SO" }));
    head.appendChild(el("th", { scope: "col", text: s.fin ? "Final" : "Total" }));
    function line(i, x, total, other) {
      var cells = lines.map(function (p) { return el("td", { "class": p[i] > p[i === 2 ? 3 : 2] ? "won" : "", text: String(p[i]) }); });
      if (s.end === "SO" && !lines.some(function (p) { return p[1] === "SO"; })) cells.push(el("td", { "class": total > other ? "won" : "", text: total > other ? "1" : "0" }));
      return el("tr", {}, [el("th", { scope: "row", "class": "l" }, [el("span", { "class": "stm" }, [rankTag(x.rank), logo(x.id, "sm"), teamA(x.id, x.name, "full"), el("span", { "class": "abbr", "aria-hidden": "true", text: x.id })])])].concat(cells)
        .concat([el("td", { "class": "tot", text: total == null ? "0" : String(total) })]));
    }
    holder.appendChild(el("div", { "class": "tablewrap" }, [el("table", { "class": "ptable stable" }, [el("thead", {}, [head]), el("tbody", {}, [line(2, g.away, s.as, s.hs), line(3, g.home, s.hs, s.as)])])]));
  }
  function fillCompare(cmp, g, d) {
    var A = (d.tstats || {}).away || {}, H = (d.tstats || {}).home || {};
    function share(t) { return t.fot ? 100 * t.fow / t.fot : null; }
    var rows = [["Shots on goal", A.sog, H.sog, String, 1], ["Faceoffs won", share(A), share(H), function (v) { return Math.round(v) + "%"; }, 1],
      ["Power play", A.ppo == null ? null : A.ppg, H.ppo == null ? null : H.ppg, null, 1], ["Hits", A.hits, H.hits, String, 1], ["Blocked shots", A.blk, H.blk, String, 1],
      ["Takeaways", A.tk, H.tk, String, 1], ["Giveaways", A.gv, H.gv, String, 0], ["Penalty minutes", A.pim, H.pim, String, 0]];
    cmp.innerHTML = "";
    if (!rows.some(function (c) { return c[1] != null && c[2] != null; })) return;
    cmp.appendChild(el("h3", { "class": "gc-h", text: "Team comparison" }));
    rows.forEach(function (c) {
      var a = c[1], h = c[2];
      if (a == null || h == null) return;
      var sum = a + h || 1, aw = a + h ? 100 * a / sum : 50;
      var aBetter = c[4] ? a > h : a < h, hBetter = c[4] ? h > a : h < a;
      var show = c[3] || function (v, t) { return v + " for " + t.ppo; };
      cmp.appendChild(el("div", { "class": "gc-row" }, [
        el("span", { "class": "v" + (aBetter ? " best" : ""), text: show(a, A) }),
        el("div", { "class": "gc-track", "aria-hidden": "true" }, [el("span", { "class": "a" + (aBetter ? " best" : ""), style: "width:" + aw + "%" }), el("span", { "class": "h" + (hBetter ? " best" : ""), style: "width:" + (100 - aw) + "%" })]),
        el("span", { "class": "v h" + (hBetter ? " best" : ""), text: show(h, H) }),
        el("span", { "class": "l", text: c[0] })]));
    });
  }
  // a goal in a game file: [period, type, time, side (0 away, 1 home), scorer id, scorer, [[id, name], ...], strength, modifier, away score, home score]
  function goalList(g, d) {
    if (!d.goals || !d.goals.length) return null;
    var sec = el("section", { "class": "tsec" }, [el("h2", { text: "Scoring" })]), per = null, ol = null;
    d.goals.forEach(function (x) {
      var key = x[0] + x[1];
      if (key !== per) { per = key; sec.appendChild(el("h3", { "class": "day", text: periodName(x[0], x[1]) + (x[1] === "REG" ? " period" : "") })); ol = el("ol", { "class": "goals" }); sec.appendChild(ol); }
      var side = x[3] ? g.home : g.away, tags = [];
      if (x[7] === "pp") tags.push("Power play"); else if (x[7] === "sh") tags.push("Shorthanded");
      if (/empty/.test(x[8])) tags.push("Empty net"); if (/penalty/.test(x[8])) tags.push("Penalty shot");
      ol.appendChild(el("li", {}, [el("span", { "class": "gtime", text: x[2] }), logo(side.id, "sm", side.name),
        el("span", { "class": "gwho" }, [el("a", { href: "#/player/" + x[4], text: x[5] }),
          el("small", { text: x[6].length ? " from " + x[6].map(function (a) { return a[1]; }).join(" and ") : " unassisted" }),
          tags.length ? el("span", { "class": "gtag", text: tags.join(", ") }) : null]),
        el("b", { "class": "gscore", text: x[9] + "–" + x[10] })]));
    });
    return sec;
  }
  function starList(g, d) {
    if (!d.stars || !d.stars.length) return null;
    return el("section", { "class": "tsec" }, [el("h2", { text: "Three stars" }), el("ol", { "class": "stars" }, d.stars.map(function (s, i) {
      return el("li", {}, [el("span", { "class": "rk", text: String(i + 1) }), el("a", { "class": "starwho", href: "#/player/" + s[0] }, [face({ name: s[2], photo: s[3] }), el("span", { text: s[2] })]), logo(s[1], "sm", (T(s[1]) || {}).name)]);
    }))]);
  }
  function drawGame(id) {
    stopGame();
    var box = $("game"), g = data.games.filter(function (x) { return String(x.id) === String(id); })[0];
    box.innerHTML = "";
    if (!g) { box.appendChild(el("p", { "class": "empty", text: "That game is not on this season's schedule." })); return; }
    var t = g.start ? new Date(g.start * 1000) : null, doc = null;
    function side(x) { return el("span", { "class": "mside" }, [rankTag(x.rank), logo(x.id), teamA(x.id, x.name)]); }
    var title = el("h1", { "class": "mtitle" }, [side(g.away), el("span", { "class": "mv", text: " at " }), side(g.home)]);
    var status = el("p", { "class": "mstatus" }), scoreBox = el("div"), sets = el("div", { "class": "msets" }), boxes = el("div", { "class": "mboxes" }), cmp = el("div", { "class": "gc-cmp" });
    var card = el("section", { "class": "gcard", "aria-label": "Game summary" }, [scoreBox, sets, oddsLine(g), cmp]);
    function top() {       // the parts that change while a game is on
      var s = now(g);
      status.innerHTML = "";
      if (s.live) status.appendChild(liveTag());
      status.appendChild(el("span", { text: (s.live ? " " : "") + (g.round ? g.round + " · " : "") + long(g.date) + (t && !isNaN(t) ? ", " + clockTime(t) : "") + (s.fin ? " · " + finalWord(s.end) : "") }));
      scoreBox.innerHTML = ""; scoreBox.appendChild(scoreLine(g));
      var L = g.live;
      if (L && L.lines && L.lines[0].length) periodTable(sets, g, L.lines[0].map(function (a, i) { return [i + 1, i < 3 ? "REG" : (L.end === "SO" || /SO/.test(L.detail)) && i === L.lines[0].length - 1 && i > 3 ? "SO" : "OT", a, L.lines[1][i] || 0]; }));
      else if (doc) periodTable(sets, g, doc.line);
    }
    box.appendChild(title); box.appendChild(status); box.appendChild(card); box.appendChild(boxes);
    box.appendChild(el("p", { "class": "note" }, [W("game.note") + " ", data.game_page ? el("a", { href: data.game_page + g.id, rel: "noopener", text: W("game.nhl_link") }) : null, data.game_page ? "." : null]));
    top();
    liveHooks.push(function (x) { if (x === g) top(); });
    function readBox() {
      var s = now(g);
      return Promise.all([fetch("game/" + g.id + ".json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }), loadRoster().catch(function () {})]).then(function (both) {
        var d = both[0];
        doc = d;
        top();
        fillCompare(cmp, g, d);
        boxes.innerHTML = "";
        [goalList(g, d), starList(g, d)].forEach(function (x) { if (x) boxes.appendChild(x); });
        [["away", g.away], ["home", g.home]].forEach(function (p) {
          var x = p[1], rows = d[p[0]] || {};
          boxes.appendChild(el("h2", { "class": "mteam" }, [rankTag(x.rank), logo(x.id), teamA(x.id, (T(x.id) || {}).name || x.name)]));
          boxes.appendChild(boxTable(rows.sk || [], x.name));
          boxes.appendChild(goalieTable(rows.g || [], x.name));
        });
        if (d.status !== "F" && (s.live || !s.fin)) gameTimers.push(setTimeout(readBox, 60 * 1000));
      }).catch(function () {
        boxes.innerHTML = "";
        boxes.appendChild(el("p", { "class": "empty", text: s.live ? "Player stats appear here within a few minutes of the opening faceoff." :
          s.fin ? "The box score has not come in yet. It usually arrives within a few minutes." : "Player stats appear here once the game starts." }));
        if (s.live || s.fin || couldBeOn(g, Date.now() / 1000)) gameTimers.push(setTimeout(readBox, 60 * 1000));
      });
    }
    readBox();
  }

  // ---- a team's page: its games, its stats and its players ----
  var TSTATS = [   // key, label, format, higher is better
    ["gf_gp", "Goals per game", fmt.d2, 1], ["ga_gp", "Goals against per game", fmt.d2, 0], ["sf_gp", "Shots per game", fmt.d1, 1],
    ["sa_gp", "Shots against per game", fmt.d1, 0], ["sh_pct", "Shooting", fmt.pct, 1], ["sv_pct", "Save percentage", function (v) { return v.toFixed(3).replace(/^0/, ""); }, 1],
    ["pp_pct", "Power play", fmt.pct, 1], ["pk_pct", "Penalty kill", fmt.pct, 1], ["fo_pct", "Faceoffs won", fmt.pct, 1],
    ["hits_gp", "Hits per game", fmt.d1, 1], ["blk_gp", "Blocked shots per game", fmt.d1, 1], ["pim_gp", "Penalty minutes per game", fmt.d1, 0]
  ];
  var TPCOLS = ["rank", "name", "pos", "gp", "toi_gp", "impact_gp", "g", "a", "pts", "pm", "sog", "hits", "blk", "pim"];
  var TGCOLS = ["rank", "name", "gp", "gs", "rec", "impact_gp", "sa", "svp", "gaa", "gsaa", "so"];
  function drawTeam(id) {
    var box = $("team"), t = T(id);
    box.innerHTML = "";
    if (!t) { box.appendChild(el("p", { "class": "empty", text: "There is no team with that name." })); return; }
    document.title = t.name + " | " + data.site;
    var mine = data.games.filter(function (g) { return g.away.id === id || g.home.id === id; });
    var bits = [record(t), t.pts + " points", ordinal(t.div_rank) + " in the " + t.div, ordinal(t.conf_rank) + " in the " + t.conf.replace(/ern$/, ""), ordinal(t.rank) + " in the league",
      "No. " + t.goat + " in the GOAT ranking"];
    box.appendChild(el("div", { "class": "thead" }, [logo(id, "big"), el("div", {}, [el("h1", { text: t.name }), el("p", { "class": "tsub", text: bits.join(" · ") })])]));
    box.appendChild(el("div", { "class": "tvs" }, [versus(t)]));
    box.appendChild(el("p", { "class": "note vsnote", text: W("team.versus_note", { n: (data.goat || {}).top }) }));

    // games: the latest results and what is next
    var next = mine.filter(function (g) { return g.state !== "final" && g.state !== "other" && g.date >= today; }).slice(0, 5);
    var done = mine.filter(function (g) { return g.state === "final"; }).slice(-5);
    var m = el("section", { "class": "tsec" }, [el("h2", { text: W("team.games") })]);
    if (next.length) { m.appendChild(el("h3", { "class": "day", text: W("team.coming_up") })); m.appendChild(el("ol", { "class": "games" }, next.map(function (g) { return row(g, true); }))); }
    if (done.length) { m.appendChild(el("h3", { "class": "day", text: W("team.latest_results") })); m.appendChild(el("ol", { "class": "games" }, done.slice().reverse().map(function (g) { return row(g, true); }))); }
    if (!mine.length) m.appendChild(el("p", { "class": "empty", text: "No games are listed for " + t.name + "." }));
    if (mine.length) m.appendChild(el("p", { "class": "note" }, [el("a", { href: "#/", onclick: function () { state.team = id; }, text: "All " + t.short + " games this season" })]));
    box.appendChild(m);

    var stats = el("section", { "class": "tsec" }, [el("h2", { text: W("team.stats") }), el("p", { "class": "empty", text: "Loading…" })]);
    var people = el("section", { "class": "tsec" }, [el("h2", { text: W("team.players") }), el("p", { "class": "empty", text: "Loading…" })]);
    box.appendChild(stats); box.appendChild(people);
    loadTeams().then(function (d) {
      var row1 = d.teams.filter(function (x) { return x.id === id; })[0];
      stats.removeChild(stats.lastChild);
      if (!row1 || !row1.gp) { stats.appendChild(el("p", { "class": "empty", text: "No games played yet." })); return; }
      var tiles = TSTATS.map(function (c) {
        var v = row1[c[0]];
        var vals = d.teams.map(function (x) { return x[c[0]]; }).filter(function (x) { return x != null; });
        var place = v == null ? null : 1 + vals.filter(function (x) { return c[3] ? x > v : x < v; }).length;
        return el("div", { "class": "tile" + (place && place <= 5 ? " top" : "") }, [el("span", { "class": "lab", text: c[1] }),
          el("b", { text: v == null ? "–" : c[2](v) }), el("span", { "class": "plc", text: place ? ordinal(place) + " of " + vals.length : "" })]);
      });
      tiles.push(el("div", { "class": "tile" }, [el("span", { "class": "lab", text: "Rating" }), el("b", { text: row1.power ? ordinal(row1.power) : "–" }), el("span", { "class": "plc", text: "in the NHL, by this site's rating" })]));
      tiles.push(el("div", { "class": "tile" }, [el("span", { "class": "lab", text: "Schedule strength" }), el("b", { text: row1.sos_rank ? ordinal(row1.sos_rank) : "–" }), el("span", { "class": "plc", text: "hardest of " + d.teams.length })]));
      stats.appendChild(el("div", { "class": "tiles" }, tiles));
      stats.appendChild(el("p", { "class": "note", text: "Regular season. Per-game stats from " + row1.games + " box scores; places are among the " + d.teams.length + " NHL teams. " }));
      stats.lastChild.appendChild(el("a", { href: "#/teams", text: "All team stats" }));
    }).catch(function () {});
    loadRoster().then(function () {
      var list = roster.players.filter(function (p) { return p.team_id === id; });
      people.removeChild(people.lastChild);
      if (!list.length) { people.appendChild(el("p", { "class": "empty", text: "No box scores yet." })); return; }
      [[false, PCOLS, TPCOLS, "skaters"], [true, GCOLS, TGCOLS, "goalies"]].forEach(function (o) {
        var rows = list.filter(function (p) { return (p.grp === "G") === o[0]; }).sort(function (a, b) {
          return (a.rank || 1e6) - (b.rank || 1e6) || (val(b, "impact_gp") || 0) - (val(a, "impact_gp") || 0);
        });
        if (!rows.length) return;
        var cols = o[2].map(function (k) { return o[1].filter(function (c) { return c[0] === k; })[0]; });
        var head = el("tr", {}, cols.map(function (c) { return el("th", { scope: "col", "class": c[0] === "name" ? "l" : "", title: c[2] || null }, [el("span", { "class": "th", text: c[0] === "name" ? (o[0] ? "Goalie" : "Skater") : c[1] })]); }));
        var body = el("tbody", {}, rows.map(function (p) { return el("tr", { "class": p.regular ? "" : "part" }, cols.map(function (c) { return playerCell(p, c, null, true); })); }));
        people.appendChild(el("div", { "class": "tablewrap", tabindex: "0", role: "region", "aria-label": t.name + " " + o[3] + ", scrolls sideways" }, [
          el("table", { "class": "ptable tptable" }, [el("thead", {}, [head]), body])]));
      });
      people.appendChild(el("p", { "class": "note", text: W("team.players_note") }));
    }).catch(function () {});
  }

  function route() {
    var h = location.hash, card = /^#\/?player\/(\d+)/.exec(h), game = /^#\/?game\/(\d+)/.exec(h), tm = /^#\/?team\/(.+)$/.exec(h);
    stopGame();
    var page = tm ? "team" : game ? "game" : card ? "card" : /^#\/?players/.test(h) ? "players" : /^#\/?standings/.test(h) ? "standings" : /^#\/?teams/.test(h) ? "teams" : "games";
    ["games", "standings", "teams", "players", "card", "game", "team"].forEach(function (p) { $("page-" + p).hidden = p !== page; });
    Array.prototype.forEach.call(document.querySelectorAll(".pages a"), function (a) {
      if (a.dataset.page === (page === "card" ? "players" : page === "game" ? "games" : page === "team" ? "teams" : page)) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    document.title = ({ standings: W("standings.title"), teams: W("teams.title"), players: W("players.title"), game: W("games.box_score"), team: "Team", card: "Player card" }[page] || W("games.title")) + " | " + data.site;
    if (page === "team") drawTeam(decodeURIComponent(tm[1])); else if (page === "game") drawGame(game[1]); else if (page === "standings") drawStandings(); else if (page === "teams") drawTeams(); else if (page === "players") drawPlayers(); else if (page === "card") drawCard(card[1]); else draw();
    window.scrollTo(0, 0);
  }

  fetch("data.json", { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }).then(function (d) {
    data = d;
    d.teams.forEach(function (t) { teamsById[t.id] = t; });
    $("brand").textContent = d.site;
    Array.prototype.forEach.call(document.querySelectorAll("[data-w]"), function (n) { var s = W(n.getAttribute("data-w")); if (s) n.textContent = s; });
    var u = new Date(d.updated);
    $("foot-updated").textContent = "Scores, schedule and standings updated " + (isNaN(u) ? d.updated : u.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })) + ".";
    window.addEventListener("hashchange", route);
    route();
    pollLive();
  }).catch(function () {
    $("h-list").textContent = "The games could not be loaded";
    $("list").appendChild(el("p", { "class": "empty", text: "Reload the page to try again. If this keeps happening, the nightly update may not have run yet." }));
  });
})();
