// The two pages (docs/design/pbd-site.md, "The page"): the lists of
// games, and one game -- its board in the viewer, its log beside it and
// its history turn by turn. Everything comes from /data/, the bucket as
// the Function answers it; every key the JSON hands over is whole, so
// nothing here builds a key of its own. Every line is built with
// textContent, never innerHTML, so a display name is never markup.
"use strict";

const Codex = (() => {
  const LIVE_POLL = 15 * 1000;   // decision 7: about every 15 seconds
  const LIST_POLL = 60 * 1000;   // and the lists every minute
  const LOG_KEY = "pbd.log";

  const data = (key) => `/data/${key}`;
  const $ = (id) => document.getElementById(id);

  function element(tag, className, text) {
    const made = document.createElement(tag);
    if (className) made.className = className;
    if (text !== undefined) made.textContent = text;
    return made;
  }

  async function fetchJson(key) {
    // no-cache: the browser asks again every time, with the ETag it
    // holds, and a 304 costs no body.
    const response = await fetch(data(key), { cache: "no-cache" });
    if (!response.ok) {
      const error = new Error(`${key}: ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  // Run `step` now and every `interval` while the tab is visible; a
  // step that returns false stops for good.
  function poll(step, interval) {
    let timer = null;
    let stopped = false;
    const run = async () => {
      clearTimeout(timer);
      if (stopped || document.hidden) return;
      if ((await step()) === false) {
        stopped = true;
        return;
      }
      timer = setTimeout(run, interval);
    };
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) run();
      else clearTimeout(timer);
    });
    run();
  }

  function say(text) {
    $("status").textContent = text || "";
  }

  // -- A line ---------------------------------------------------------------

  // One segment (docs/design/pbd-site.md, "A line is segments"): text, a
  // seat's name, a card's name, or a glyph's picture.
  function segment(piece) {
    let made;
    if ("player" in piece) {
      made = element("span", "player", piece.name);
    } else if ("card" in piece) {
      made = element("span", piece.hero ? "card hero" : "card", piece.name);
      made.dataset.card = piece.card;
    } else if ("glyph" in piece) {
      made = element("span", `glyph glyph-${piece.glyph}`);
      const picture = element("img");
      picture.src = data(piece.key);
      picture.alt = piece.alt;
      picture.title = piece.alt;
      made.append(picture);
      if ("n" in piece) made.append(document.createTextNode(String(piece.n)));
    } else {
      made = document.createTextNode(piece.text || "");
    }
    if (piece.italic) made = wrap("em", made);
    if (piece.bold) made = wrap("strong", made);
    return made;
  }

  function wrap(tag, inner) {
    const made = element(tag);
    made.append(inner);
    return made;
  }

  function line(pieces, tag = "p") {
    const made = element(tag, "line");
    for (const piece of pieces) made.append(segment(piece));
    return made;
  }

  // -- A game as the lists name it -----------------------------------------

  function seatName(game, seat) {
    const found = game.seats.find((held) => held.seat === seat);
    return found ? found.name : `Player ${seat}`;
  }

  // "basher vs fencer"; a dragon's "ann and bo vs cy and di"; a
  // free-for-all's seats in a row.
  function players(game) {
    const sides = game.sides && game.sides.length ? game.sides : game.seats.map((held) => [held.seat]);
    const names = sides.map((side) => side.map((seat) => seatName(game, seat)).join(" and "));
    return names.join(game.variant === "free_for_all" ? ", " : " vs ");
  }

  function kind(game) {
    const mode = game.mode ? `${game.mode[0].toUpperCase()}${game.mode.slice(1)} game` : "";
    return [mode, game.variant_label || game.variant].filter(Boolean).join(" · ");
  }

  function names(game, list) {
    return (list || []).map((seat) => seatName(game, seat)).join(" and ");
  }

  // Where the game stands, in a few words.
  function standing(game) {
    if (game.status === "finished") {
      return game.winner && game.winner.length ? `${names(game, game.winner)} won on turn ${game.turn}` : "Finished";
    }
    if (game.status === "abandoned") return game.turn ? `Abandoned on turn ${game.turn}` : "Abandoned";
    if (!game.turn) return "Starting";
    const whose = names(game, game.turn_seats);
    return whose ? `Turn ${game.turn} · ${whose} to play` : `Turn ${game.turn}`;
  }

  function when(stamp) {
    if (!stamp) return "";
    const then = new Date(stamp);
    if (Number.isNaN(then.getTime())) return "";
    const minutes = Math.round((Date.now() - then.getTime()) / 60000);
    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours} h ago`;
    return then.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  }

  // -- The lists --------------------------------------------------------------

  function card(game) {
    const item = element("li");
    const link = element("a", "game-card");
    link.href = `/game/${encodeURIComponent(game.id)}`;
    const top = element("div", "card-top");
    top.append(element("span", "number", `Game ${game.number}`), element("span", "kind", kind(game)));
    link.append(top, element("div", "players", players(game)));
    const teams = element("ul", "teams");
    for (const held of game.seats) {
      const row = element("li");
      row.append(element("span", "player", held.name));
      if (held.team) row.append(document.createTextNode(" "), element("span", "team", held.team));
      teams.append(row);
    }
    link.append(teams);
    const foot = element("div", "card-foot");
    foot.append(element("span", "standing", standing(game)), element("span", "when", when(game.updated)));
    link.append(foot);
    item.append(link);
    return item;
  }

  function fill(listId, games) {
    const list = $(listId);
    list.replaceChildren(...games.map(card));
    $(`${listId}-empty`).hidden = games.length > 0;
  }

  function lists() {
    poll(async () => {
      try {
        const [playing, archive] = await Promise.all([fetchJson("codex/index.json"), fetchJson("codex/archive.json")]);
        fill("playing", playing.games || []);
        fill("finished", archive.finished || []);
        fill("abandoned", archive.abandoned || []);
        say("");
      } catch (error) {
        say(error.status === 404 ? "Nothing has been published yet." : "The list could not be read; trying again.");
      }
    }, LIST_POLL);
  }

  // -- One game ---------------------------------------------------------------

  function gameId() {
    const match = location.pathname.match(/^\/game\/([0-9a-f]{32})\/?$/);
    return match ? match[1] : null;
  }

  function turnSection(turn, { board, current }) {
    const section = element("section", "turn");
    if (turn.heading && turn.heading.length) section.append(line(turn.heading, "h3"));
    const body = element("div", "lines");
    for (const pieces of turn.lines || []) body.append(line(pieces));
    if (!body.childElementCount) body.append(element("p", "quiet", current ? "Nothing yet this turn." : "Nothing was said."));
    section.append(body);
    if (board) section.append(board);
    return section;
  }

  function logShown(shown) {
    document.body.classList.toggle("log-hidden", !shown);
    $("log-toggle").setAttribute("aria-pressed", String(shown));
    try { localStorage.setItem(LOG_KEY, shown ? "open" : "closed"); } catch (error) { /* private window */ }
  }

  function game() {
    const id = gameId();
    if (!id) {
      say("There is no game at this address.");
      return;
    }
    const viewer = new Viewer($("viewer"), $("board"));
    const state = { board: null, historyVersion: null, looking: null, title: null };

    let saved = null;
    try { saved = localStorage.getItem(LOG_KEY); } catch (error) { /* private window */ }
    logShown(saved !== "closed");
    $("log-toggle").addEventListener("click", () => logShown(document.body.classList.contains("log-hidden")));
    $("zoom-in").addEventListener("click", () => viewer.zoom(1.25));
    $("zoom-out").addEventListener("click", () => viewer.zoom(0.8));
    $("zoom-fit").addEventListener("click", () => viewer.fit());
    $("looking-back").addEventListener("click", () => look(null));

    // An earlier turn's board in the viewer, or the current one again.
    function look(turn) {
      state.looking = turn;
      $("looking").hidden = !turn;
      if (turn) {
        $("looking-text").textContent = `Turn ${turn.turn}'s last board`;
        viewer.show(data(turn.board));
      } else if (state.board) {
        viewer.show(data(state.board));
      }
    }

    function thumbnail(turn) {
      const button = element("button", "thumb");
      button.type = "button";
      button.setAttribute("aria-label", `Show turn ${turn.turn}'s board`);
      const picture = element("img");
      picture.loading = "lazy";
      picture.src = data(turn.board);
      picture.alt = `Turn ${turn.turn}'s last board`;
      button.append(picture);
      button.addEventListener("click", () => look(turn));
      return button;
    }

    async function history(key) {
      const found = await fetchJson(key);
      const turns = (found.turns || []).slice().reverse();
      $("history").replaceChildren(...turns.map((turn) => turnSection(turn, { board: turn.board ? thumbnail(turn) : null })));
      $("earlier-title").hidden = turns.length === 0;
      return found.version;
    }

    async function step() {
      let live;
      try {
        live = await fetchJson(`codex/games/${id}/live.json`);
      } catch (error) {
        say(error.status === 404 ? "This game is not on the site." : "The game could not be read; trying again.");
        return error.status !== 404;
      }
      const title = `Game ${live.number}: ${players(live)}`;
      if (title !== state.title) {
        state.title = title;
        $("title").textContent = title;
        document.title = `${title} · Codex`;
      }
      $("summary").textContent = `${kind(live)} · ${standing(live)}`;
      $("current").replaceChildren(...turnSection(live, { current: true }).childNodes);
      if (live.board && live.board !== state.board) {
        state.board = live.board;
        if (!state.looking) viewer.show(data(live.board));
      }
      if (live.history_version !== state.historyVersion && live.history) {
        try {
          await history(live.history);
          state.historyVersion = live.history_version;
        } catch (error) { /* the next poll asks again */ }
      }
      const over = live.status !== "playing";
      say(over ? "This game is over." : "");
      return !over;
    }

    poll(step, LIVE_POLL);
  }

  document.addEventListener("DOMContentLoaded", () => {
    const page = document.body.dataset.page;
    if (page === "lists") lists();
    else if (page === "game") game();
  });

  return { lists, game };
})();
