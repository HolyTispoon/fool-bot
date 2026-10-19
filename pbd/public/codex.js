// The Codex games' pages (docs/design/pbd-site.md, "The page"): the lists on
// index.html and one game on game.html, read from /data/, which the Function
// answers from the bucket. Every line is built with textContent from its
// segments, never as markup, so nothing a player is called can be a tag.
"use strict";

const DATA = "/data/";
const INDEX = "codex/index.json";
const ARCHIVE = "codex/archive.json";
// A game's page polls its live.json this often, the lists their two files
// this often, and neither while the tab is hidden (docs/pbd-site.md,
// decision 7).
const GAME_POLL = 15 * 1000;
const LIST_POLL = 60 * 1000;
const LOG_HIDDEN = "codex-pbd-log-hidden";
const LOG_WIDTH = "codex-pbd-log-width";
// The log is never narrower than this, and never leaves the board less.
const LOG_MIN = 240;
const BOARD_MIN = 240;

// What a game's mode and variant are called: cogs/codex_views/lobby.py's
// MODE_LABELS and codex/game.py's VARIANT_LABELS, held to both by
// tests/test_pbd_site.py.
const MODE_LABELS = { basic: "Basic game", standard: "Standard game" };
const VARIANT_LABELS = {
  duel: "Duel",
  free_for_all: "Free-for-all",
  two_headed_dragon: "Two-headed dragon",
};

function element(tag, className, text) {
  const made = document.createElement(tag);
  if (className) made.className = className;
  if (text !== undefined) made.textContent = text;
  return made;
}

// `cache`, "default" for an object named by its bytes -- a board's map --
// which never changes.
async function fetchData(key, cache = "no-cache") {
  const response = await fetch(DATA + key, { cache });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${key}: ${response.status}`);
  return response.json();
}

function say(text) {
  const status = document.getElementById("status");
  if (status) status.textContent = text;
}

// -- A line, from its segments ------------------------------------------------

function segmentNode(segment) {
  let node;
  if (segment.glyph !== undefined) {
    node = element("span", "glyph");
    const picture = element("img");
    picture.alt = segment.alt || segment.glyph;
    picture.title = segment.alt || segment.glyph;
    picture.src = DATA + segment.key;
    // Where the picture does not load, the word it stands for.
    picture.addEventListener("error", () => picture.replaceWith(document.createTextNode(picture.alt)), { once: true });
    node.append(picture);
    if (segment.n !== undefined && segment.glyph === "gold") {
      node.append(element("span", "glyph-n", String(segment.n)));
    }
  } else if (segment.player !== undefined) {
    node = element("span", "player", segment.name);
  } else if (segment.card !== undefined) {
    node = element("span", segment.hero ? "card hero" : "card", segment.name);
    node.dataset.card = segment.card;
    // Its picture, shown on hover (GamePage.cardNames).
    if (segment.key) node.dataset.key = segment.key;
  } else {
    node = document.createTextNode(segment.text || "");
  }
  if (segment.italic) {
    const wrapped = element("em");
    wrapped.append(node);
    node = wrapped;
  }
  if (segment.bold) {
    const wrapped = element("strong");
    wrapped.append(node);
    node = wrapped;
  }
  return node;
}

function lineNode(tag, segments) {
  const line = element(tag, "line");
  for (const segment of segments || []) line.append(segmentNode(segment));
  return line;
}

function fillLines(list, lines) {
  list.replaceChildren(...(lines || []).map((segments) => lineNode("li", segments)));
}

// -- What a list entry says ---------------------------------------------------

function seatNames(entry, seats) {
  const bySeat = new Map(entry.seats.map((seat) => [seat.seat, seat]));
  return seats.map((seat) => bySeat.get(seat)).filter(Boolean);
}

function sidesNode(entry) {
  const node = element("span", "sides");
  const sides = entry.sides && entry.sides.length ? entry.sides : entry.seats.map((seat) => [seat.seat]);
  sides.forEach((side, index) => {
    // A free-for-all's seats are a list, as /codex games names them; a duel's
    // and a dragon's two sides are one against the other.
    if (index > 0) {
      node.append(entry.variant === "free_for_all" ? ", " : element("span", "versus", " vs "));
    }
    seatNames(entry, side).forEach((seat, at) => {
      if (at > 0) node.append(" and ");
      node.append(element("span", "player", seat.name));
      if (seat.team) node.append(element("span", "team", ` (${seat.team})`));
    });
  });
  return node;
}

function names(entry, seats) {
  return seatNames(entry, seats || []).map((seat) => seat.name).join(" and ");
}

function kind(entry) {
  return [MODE_LABELS[entry.mode] || entry.mode, VARIANT_LABELS[entry.variant] || entry.variant]
    .filter(Boolean).join(", ");
}

function when(updated) {
  if (!updated) return "";
  const then = new Date(updated);
  if (Number.isNaN(then.getTime())) return "";
  // A clock a little ahead of this one is "now", never "in 2 minutes".
  const minutes = Math.max(0, Math.round((Date.now() - then.getTime()) / 60000));
  const words = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  if (Math.abs(minutes) < 60) return words.format(-minutes, "minute");
  if (Math.abs(minutes) < 60 * 24) return words.format(-Math.round(minutes / 60), "hour");
  if (Math.abs(minutes) < 60 * 24 * 7) return words.format(-Math.round(minutes / 1440), "day");
  return then.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

// Where a game stands, as one line: whose turn, who won, or that it stopped.
function standing(entry) {
  const turn = entry.turn ? `Turn ${entry.turn}` : "";
  if (entry.status === "finished") {
    const won = names(entry, entry.winner);
    return [won ? `Won by ${won}` : "Finished", turn ? `on turn ${entry.turn}` : ""].filter(Boolean).join(" ");
  }
  if (entry.status === "abandoned") {
    return turn ? `Abandoned on turn ${entry.turn}` : "Abandoned";
  }
  const playing = names(entry, entry.turn_seats);
  return [turn, playing ? `${playing} to play` : ""].filter(Boolean).join(" · ");
}

function entryNode(entry) {
  const item = element("li", "entry");
  const link = element("a");
  link.href = `/game/${entry.id}`;
  const head = element("span", "entry-head");
  head.append(element("span", "number", `Game ${entry.number}`), element("span", "kind", kind(entry)));
  const foot = element("span", "entry-foot");
  foot.append(element("span", "standing", standing(entry)));
  const ago = when(entry.updated);
  if (ago) foot.append(element("span", "updated", ago));
  link.append(head, sidesNode(entry), foot);
  item.append(link);
  return item;
}

function fillGames(id, games) {
  const list = document.getElementById(id);
  list.replaceChildren(...(games || []).map(entryNode));
  document.getElementById(`${id}-empty`).hidden = Boolean(games && games.length);
}

// -- Polling while the tab is visible -----------------------------------------

function poll(every, run) {
  let timer = null;
  let stopped = false;
  const tick = async () => {
    timer = null;
    let again = true;
    try {
      again = (await run()) !== false;
    } catch (error) {
      say("Could not reach the site's data; trying again shortly.");
      console.warn(error);
    }
    if (!again) stopped = true;
    if (!stopped && !document.hidden) timer = setTimeout(tick, every);
  };
  document.addEventListener("visibilitychange", () => {
    if (stopped) return;
    if (document.hidden) {
      clearTimeout(timer);
      timer = null;
    } else if (timer === null) {
      tick();
    }
  });
  tick();
}

// -- The lists ------------------------------------------------------------------

async function showLists() {
  const [index, archive] = await Promise.all([fetchData(INDEX), fetchData(ARCHIVE)]);
  fillGames("playing", index ? index.games : []);
  fillGames("finished", archive ? archive.finished : []);
  fillGames("abandoned", archive ? archive.abandoned : []);
  say("");
}

// -- One game -------------------------------------------------------------------

const GAME_ADDRESS = /^\/game\/([0-9a-f]{32})\/?$/;

class GamePage {
  constructor(id) {
    this.id = id;
    this.live = null;
    this.historyVersion = null;
    this.historyTurns = [];
    // The board in the viewer when it is not the current one: a finished
    // turn's, opened from the log.
    this.looking = null;
    this.viewer = new BoardViewer(document.getElementById("viewer"), document.getElementById("board"));
    this.preview = new CardPreview(DATA);
    // Each board's map by its key (null where it has none), and which map
    // goes with which board's address in the viewer.
    this.maps = new Map();
    this.mapOf = new Map();
    // The board region the preview shows, while it shows one.
    this.peeking = null;
    this.cardNames();
    this.peek();
    document.getElementById("zoom-in").addEventListener("click", () => this.viewer.zoomBy(1.25));
    document.getElementById("zoom-out").addEventListener("click", () => this.viewer.zoomBy(0.8));
    document.getElementById("zoom-fit").addEventListener("click", () => { this.viewer.fit(); this.viewer.draw(); });
    document.getElementById("back-to-current").addEventListener("click", () => this.lookAt(null));
    this.logToggle();
    this.splitter();
  }

  logToggle() {
    const button = document.getElementById("log-toggle");
    const main = document.getElementById("game-main");
    const set = (hidden) => {
      main.classList.toggle("log-hidden", hidden);
      document.getElementById("log").hidden = hidden;
      button.textContent = hidden ? "Show log" : "Hide log";
      button.setAttribute("aria-expanded", String(!hidden));
    };
    let hidden = false;
    try { hidden = localStorage.getItem(LOG_HIDDEN) === "1"; } catch (error) { /* no storage */ }
    set(hidden);
    button.addEventListener("click", () => {
      hidden = !hidden;
      set(hidden);
      try { localStorage.setItem(LOG_HIDDEN, hidden ? "1" : "0"); } catch (error) { /* no storage */ }
    });
  }

  // The divider between the board and the log: dragged, or moved with the
  // arrow keys, it sets the log's width, remembered like the toggle;
  // double-clicked, it puts the width back. The viewer refits itself, since
  // it watches its own size.
  splitter() {
    const handle = document.getElementById("splitter");
    const main = document.getElementById("game-main");
    const log = document.getElementById("log");
    const clamp = (width) => Math.round(Math.max(LOG_MIN, Math.min(width, main.clientWidth - BOARD_MIN)));
    const set = (width) => {
      if (width === null) main.style.removeProperty("--log-width");
      else main.style.setProperty("--log-width", `${clamp(width)}px`);
    };
    const save = () => {
      const width = main.style.getPropertyValue("--log-width");
      try {
        if (width) localStorage.setItem(LOG_WIDTH, width);
        else localStorage.removeItem(LOG_WIDTH);
      } catch (error) { /* no storage */ }
    };
    let stored = null;
    try { stored = localStorage.getItem(LOG_WIDTH); } catch (error) { /* no storage */ }
    if (stored && /^\d+px$/.test(stored)) set(parseInt(stored, 10));

    let dragging = false;
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      dragging = true;
      handle.setPointerCapture(event.pointerId);
      handle.classList.add("dragging");
      document.body.classList.add("resizing");
      event.preventDefault();
    });
    handle.addEventListener("pointermove", (event) => {
      if (dragging) set(main.getBoundingClientRect().right - event.clientX);
    });
    const stop = () => {
      if (!dragging) return;
      dragging = false;
      handle.classList.remove("dragging");
      document.body.classList.remove("resizing");
      save();
    };
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
    handle.addEventListener("dblclick", () => { set(null); save(); });
    handle.addEventListener("keydown", (event) => {
      const step = event.shiftKey ? 96 : 24;
      if (event.key === "ArrowLeft") set(log.offsetWidth + step);
      else if (event.key === "ArrowRight") set(log.offsetWidth - step);
      else return;
      event.preventDefault();
      save();
    });
  }

  // A card named in the log shows its picture while the mouse is over it, and
  // on a tap or a click, for a finger, until the next.
  cardNames() {
    const log = document.getElementById("log");
    const named = (event) => {
      const found = event.target.closest(".card[data-key]");
      return found && log.contains(found) ? found : null;
    };
    const cardOf = (node) => [{ slug: node.dataset.card, name: node.textContent, key: node.dataset.key }];
    const at = (event) => ({ x: event.clientX, y: event.clientY });
    log.addEventListener("pointerover", (event) => {
      if (event.pointerType !== "mouse") return;
      const node = named(event);
      if (node) this.preview.show(cardOf(node), null, at(event), node);
    });
    log.addEventListener("pointermove", (event) => {
      if (event.pointerType === "mouse" && this.preview.showing === named(event)) this.preview.place(at(event));
    });
    log.addEventListener("pointerout", (event) => {
      if (event.pointerType !== "mouse") return;
      const node = named(event);
      if (node && !node.contains(event.relatedTarget) && this.preview.showing === node) this.preview.hide();
    });
    document.addEventListener("click", (event) => {
      const node = named(event);
      // A click that is not a PointerEvent says no pointer type: a mouse
      // where the device hovers.
      const mouse = event.pointerType ? event.pointerType === "mouse" : matchMedia("(hover: hover)").matches;
      if (mouse && node) return;
      if (node && this.preview.showing !== node) this.preview.show(cardOf(node), null, at(event), node);
      else if (!this.peeking) this.preview.hide();
    });
    // It stays where it was put, so a scroll -- the log's, or the page's
    // on a phone -- takes it away.
    const scrolled = () => { if (!this.peeking) this.preview.hide(); };
    log.addEventListener("scroll", scrolled);
    window.addEventListener("scroll", scrolled, { passive: true });
  }

  // Space over the board shows what the board's map says is under the mouse:
  // a card, or the codex cards a tech building opens. It stays until Space
  // again, Escape, or the mouse leaving that card.
  peek() {
    const frame = document.getElementById("viewer");
    const stop = () => {
      if (this.peeking) this.preview.hide();
      this.peeking = null;
    };
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") { stop(); return; }
      if (event.key !== " " || event.ctrlKey || event.metaKey || event.altKey) return;
      if (this.viewer.hover === null) return;
      event.preventDefault();
      if (event.repeat) return;
      const region = this.regionUnder(this.viewer.hover);
      if (!region || region === this.peeking) { stop(); return; }
      this.peeking = region;
      this.preview.show(region.cards, region.title || null, this.viewer.hover, region);
    });
    frame.addEventListener("pointermove", (event) => {
      if (!this.peeking || event.pointerType !== "mouse") return;
      const at = { x: event.clientX, y: event.clientY };
      if (this.regionUnder(at) === this.peeking) this.preview.place(at);
      else stop();
    });
    frame.addEventListener("pointerleave", stop);
    frame.addEventListener("pointerdown", stop);
    this.viewer.image.addEventListener("load", stop);
  }

  // The board's map's region under a point in the window, for the board the
  // viewer shows now -- none while its map is not loaded, or does not fit it.
  regionUnder(at) {
    const map = this.maps.get(this.mapOf.get(this.viewer.image.getAttribute("src")));
    if (!map || map.width !== this.viewer.image.naturalWidth) return null;
    const point = this.viewer.boardPoint(at);
    return point ? regionAt(map, point.x, point.y) : null;
  }

  // `board` in the viewer, and its map, `mapKey`, fetched once.
  showBoard(board, mapKey) {
    this.mapOf.set(DATA + board, mapKey || null);
    if (mapKey && !this.maps.has(mapKey)) {
      this.maps.set(mapKey, null);
      fetchData(mapKey, "default").then((map) => this.maps.set(mapKey, map), (error) => {
        // Asked for again the next time the board is shown.
        this.maps.delete(mapKey);
        console.warn(error);
      });
    }
    this.viewer.show(DATA + board);
  }

  async refresh() {
    const live = await fetchData(`codex/games/${this.id}/live.json`);
    // Not final: a list can name a game before its first live.json is up,
    // and a deploy can miss a poll. So the page keeps asking.
    if (live === null) {
      say("This game is not on the site (yet).");
      return true;
    }
    this.live = live;
    this.showGame(live);
    if (live.history_version !== this.historyVersion) {
      const history = await fetchData(live.history);
      this.historyVersion = live.history_version;
      this.historyTurns = history ? history.turns : [];
      this.showHistory();
    }
    say("");
    // A game that is over changes no more.
    return live.status === "playing";
  }

  showGame(live) {
    const title = `Game ${live.number}`;
    document.title = `${title} · Codex`;
    const heading = document.getElementById("title");
    heading.replaceChildren(element("span", "number", title), " ", sidesNode(live));
    const over = document.getElementById("over");
    over.hidden = live.status === "playing";
    over.textContent = live.status === "playing" ? "" : `${standing(live)}. This game is over.`;
    const turnHeading = document.getElementById("heading");
    turnHeading.replaceChildren(...lineNode("span", live.heading).childNodes);
    fillLines(document.getElementById("lines"), live.lines);
    if (this.looking === null && live.board) this.showBoard(live.board, live.board_map);
  }

  showHistory() {
    const list = document.getElementById("turns");
    const turns = [...this.historyTurns].reverse();
    list.replaceChildren(...turns.map((turn) => {
      const item = element("li", "turn");
      const head = element("div", "turn-head");
      head.append(lineNode("h3", turn.heading));
      if (turn.board) {
        const open = element("button", "thumb");
        open.type = "button";
        open.title = `Turn ${turn.turn}'s last board`;
        const picture = element("img");
        picture.loading = "lazy";
        picture.alt = `Turn ${turn.turn}'s last board`;
        picture.src = DATA + turn.board;
        open.append(picture);
        open.addEventListener("click", () => this.lookAt(turn));
        head.append(open);
      }
      const lines = element("ol", "lines");
      fillLines(lines, turn.lines);
      item.append(head, lines);
      return item;
    }));
    document.getElementById("turns-empty").hidden = turns.length > 0;
  }

  // A finished turn's board in the viewer, or (null) the current one again.
  lookAt(turn) {
    this.looking = turn;
    const caption = document.getElementById("viewer-caption");
    caption.hidden = turn === null;
    if (turn !== null) {
      document.getElementById("viewer-caption-text").textContent = `Turn ${turn.turn}'s last board`;
      this.showBoard(turn.board, turn.board_map);
    } else if (this.live && this.live.board) {
      this.showBoard(this.live.board, this.live.board_map);
    }
  }
}

function start() {
  if (document.body.classList.contains("lists")) {
    poll(LIST_POLL, showLists);
    return;
  }
  const found = GAME_ADDRESS.exec(location.pathname);
  if (!found) {
    say("This address names no game.");
    return;
  }
  const page = new GamePage(found[1]);
  poll(GAME_POLL, () => page.refresh());
}

start();
