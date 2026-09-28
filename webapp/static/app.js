/*
 * The page.
 *
 * It knows three things: how to ask the server for the state, how to
 * draw what comes back, and how to post one action (or one chat
 * line). Every label, every control, every colour and every sentence
 * is the server's, and so is the board: `state.board.layout` is the
 * position as `webapp/board.py` read it, and this file only lays it
 * out the way the bot's board PNG does. There is no rule of the game
 * in this file, and there must not be: the moment the web app has one
 * of its own, the model is being implemented twice (CLAUDE.md,
 * principle 10).
 */

const GAME_ID = location.pathname.split("/").pop();
const POLL_MS = 2500;

/* The width the board is laid out at; it is scaled to fit its box,
   so every proportion is the same on a phone and a monitor. */
const STAGE_WIDTH = 1200;

let latest = 0;
let chatLatest = 0;
let busy = false;
let shownPrompt = null;
let shownRematch = null;
let shownTable = null;
/* Whether this page has seen its game with no rematch yet: a page that
   was open when the rematch was made follows it there, and one opened
   on the finished game afterwards is offered the link instead. */
let sawNoRematch = false;
let shownBoard = null;
/* A chooser opened by clicking its object on the board (a space two
   teammates share): its one question is asked in the box. */
let openChooser = null;
/* What the prompt put to this viewer lights on the board, by object
   (`readLit`). */
let lit = null;
let current = null;
/* The Coaching Choice's part-made pick: the thing picked up first (a
   bench meeple coming on, a player changing zones or moving) as its
   key, and what it is called -- or null. The page's own state, like an
   open chooser: nothing is sent until the second thing is clicked. */
let picked = null;

const el = (id) => document.getElementById(id);
const phone = () => window.matchMedia("(max-width: 960px)").matches;
/* A phone held upright (step 11 of docs/web-app-redesign.md): the field
   is drawn narrow -- horizontal and whole at the screen's width, small
   meeples with no names -- and the move is a bottom sheet that repeats
   every lit thing large enough to tap. */
const UPRIGHT = window.matchMedia("(max-width: 960px) and (orientation: portrait)");
const upright = () => UPRIGHT.matches;
/* A touch screen on its side wider than a phone -- a tablet: the
   desktop field, and the phone's tabs in a column beside it. The same
   query as app.css's tablet block. */
const TABLET = window.matchMedia(
  "(min-width: 961px) and (max-width: 1400px) and (orientation: landscape) and (any-pointer: coarse)",
);
const finePointer = () => window.matchMedia("(pointer: fine)").matches;

/* One element: `h("div", {class: "x", onclick: fn}, child, ...)`. Text
   children are text, never markup; the only HTML this page sets is the
   server's rendered sentences, which `webapp/present.render_text` has
   already escaped. A chat line is never one of those. */
function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (name === "class") node.className = value;
    else if (name === "html") node.innerHTML = value;
    else node.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs, ...children) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    node.setAttribute(name, value);
  }
  for (const child of children) {
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

// -- Talking to the server ---------------------------------------------

/* Who is reading is the cookie `POST /api/me` set
   (webapp/identity.py), which the browser sends with every request. */
function api(path, options) {
  return fetch(`/api/game/${GAME_ID}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
}

/* A move on the room rather than the game: a seat taken, left or
   kicked, or the admin role. The record refuses with its sentence. */
async function roomMove(path, body, method = "POST") {
  if (busy) return;
  busy = true;
  try {
    const response = await fetch(`/api/room/${GAME_ID}${path}?${cursors()}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const text = await response.text();
    let state = null;
    try { state = JSON.parse(text); } catch (error) { /* a plain refusal */ }
    if (state && state.game) draw(state);
    else if (state && state.url) location.href = state.url;
    else showRefusal(text || "That did not reach the room.");
  } catch (error) {
    showRefusal("That did not reach the room. Try again in a moment.");
  } finally {
    busy = false;
  }
}

/* Somebody the server does not know yet is given a name first
   (`GET /api/me`, webapp/identity.py's `guest_name`), so the room seats
   them under a cookie on their first sight of it. */
async function whoAmI() {
  try {
    await fetch("/api/me");
  } catch (error) {
    /* The poll retries the rest. */
  }
}

function cursors() {
  return `since=${latest}&chat_since=${chatLatest}`;
}

async function poll() {
  try {
    const response = await api(`?${cursors()}`);
    /* A game deleted under the page ("Delete all my games") is gone
       for everybody in it: back to the front door. */
    if (response.status === 404) {
      location.href = "/";
      return;
    }
    if (response.ok && !busy) draw(await response.json());
  } catch (error) {
    /* A dropped connection is weather; the next poll picks it up. */
  }
  setTimeout(poll, POLL_MS);
}

async function act(action) {
  if (busy) return;
  busy = true;
  hidePeek();
  el("prompt").classList.add("busy");
  try {
    const response = await api(`/action?${cursors()}`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    draw(await response.json());
  } catch (error) {
    showRefusal("That did not reach the game. Try again in a moment.");
  } finally {
    busy = false;
    el("prompt").classList.remove("busy");
  }
}

async function pickUp() {
  const response = await api(`/resume?${cursors()}`, { method: "POST" });
  if (response.ok) draw(await response.json());
}

/* A chat line is the room's, not the game's: it posts to the room. */
async function say(text) {
  const response = await fetch(`/api/room/${GAME_ID}/chat?${cursors()}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (response.ok) draw(await response.json());
  return response.ok;
}

// -- The whole page, from one state ------------------------------------

function draw(state) {
  /* A new question puts back whatever was picked up for the last. */
  if (picked && JSON.stringify(state.prompt) !== shownPrompt) picked = null;
  current = state;
  drawPickToast();
  latest = state.latest;
  /* Before kickoff the table is the whole of the play area: no
     jumbotron and no board until there is a match to draw. */
  document.body.classList.toggle("at-table", Boolean(state.table));
  drawHeader(state);
  drawJumbotron(state);
  drawBoard(state);
  drawJournal(state);
  drawChat(state);
  drawRosters(state);
  rulesTab.setAids(state.aids);
  drawPrompt(state);
  drawRoll(state);
  drawHeadline(state);
  drawReveal(state);
  drawFullTime(state);
  drawTable(state);
  drawRoom(state);
  drawStats(state);
  followRematch(state);
  if (state.refusal) showRefusal(state.refusal, state.refusal_law);
  el("owed").hidden = !(state.owed && state.you.is_coach);
  drawStrip();
  const yours = Boolean(state.prompt && state.prompt.yours);
  document.title = `${yours ? "● " : ""}PBW${state.game.number} · D12 Ball`;
  notifyTurn(state);
}

// -- Your turn, in a notification ---------------------------------------

/* The prompt this page last considered notifying about, by its kind and
   its ask: one notification per prompt, however many polls see it and
   however its controls change while it is up (the Coaching Choice
   redraws after every move in it). */
let consideredPrompt = null;

/* A notification when a question is this coach's -- the mark in the
   title, for a coach who is not looking at the tab. Permission is asked
   once, on the first control pressed (`askToNotify`), never on load: a
   browser asked before anybody has done anything refuses for good. A
   prompt that goes up while the page has the focus says nothing, since
   the coach is looking at it. */
function notifyTurn(state) {
  const prompt = state.prompt;
  if (!prompt || !prompt.yours) {
    consideredPrompt = null;
    return;
  }
  const key = `${prompt.kind}\n${prompt.ask}`;
  if (key === consideredPrompt) return;
  consideredPrompt = key;
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  if (document.hasFocus()) return;
  const ask = document.createElement("div");
  ask.innerHTML = prompt.ask;
  try {
    const notice = new Notification(`PBW${state.game.number}: your move`, {
      body: ask.textContent.trim(),
      tag: `d12ball-${GAME_ID}`,
    });
    notice.onclick = () => { window.focus(); notice.close(); };
  } catch (error) {
    /* A browser that only notifies through a service worker (Chrome on
       Android) throws here; the title's mark still says it. */
  }
}

let askedToNotify = false;

function askToNotify() {
  if (askedToNotify) return;
  askedToNotify = true;
  if (!("Notification" in window) || Notification.permission !== "default") return;
  try {
    Notification.requestPermission();
  } catch (error) {
    /* An older browser's callback-only form; not worth a second path. */
  }
}

for (const box of ["prompt", "table"]) {
  el(box).addEventListener("click", (event) => {
    if (event.target.closest("button")) askToNotify();
  }, true);
}

function teamEmoji(key, name) {
  if (!key) return null;
  return h("img", { class: "emoji", src: `/emoji/team_${key}.png`, alt: name, title: name });
}

/* The top bar: the room's number and its topic on one baseline, and
   who this reader is as one pill -- the seat before the toss (gold
   edge), the side and its team after it (the team's colour), or
   watching, with the free seat beside it when there is one. Which is
   which is the server's `room.role`, read off the record. */
/* The topic: the room's name, or who plays whom. Before kickoff, to
   whoever may change the name, it is the name's editor too -- click
   it, type, and it saves on Enter or when the field is left; Escape
   leaves it as it was (the author, 2026-09-27). Drawn again only when
   it changes, and never under the reader's typing. */
let shownTopic = null;
function drawTopic(state) {
  const box = el("topic");
  if (box.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  const setting = state.table && state.table.settings.find((one) => one.name === "name");
  const editable = Boolean(setting && setting.may_change);
  const shape = JSON.stringify([state.game.topic, editable, setting && setting.value]);
  if (shape === shownTopic) return;
  shownTopic = shape;
  if (!editable) {
    box.replaceChildren(state.game.topic);
    return;
  }
  const edit = () => {
    const input = h("input", {
      class: "name-field small topic-field",
      maxlength: "80",
      value: setting.value || "",
      placeholder: state.game.topic,
      "aria-label": "Rename this game",
    });
    let done = false;
    const finish = (save) => {
      if (done) return;
      done = true;
      const value = input.value;
      shownTopic = null;
      box.replaceChildren();
      drawTopic(current);
      if (save && value !== (setting.value || "")) {
        roomMove("/table/configure", { setting: "name", value });
      }
    };
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); finish(true); }
      else if (event.key === "Escape") finish(false);
    });
    input.addEventListener("blur", () => finish(true));
    box.replaceChildren(input);
    input.focus();
    input.select();
  };
  box.replaceChildren(h("button", {
    type: "button",
    class: "topic-edit",
    title: "Rename this game",
    onclick: edit,
  }, h("span", { class: "topic-text" }, state.game.topic), h("span", { class: "topic-pencil", "aria-hidden": "true" }, "✎")));
}

function drawHeader(state) {
  el("channel").textContent = `pbw${state.game.number}`;
  drawTopic(state);
  const you = el("you");
  const room = state.room;
  const mine = room.seats.find((seat) => seat.yours);
  you.style.removeProperty("--pill-edge");
  if (room.role === "home" || room.role === "visiting") {
    const coach = state.game.coaches.find((one) => one.player_number === mine.number);
    /* The lead words and the team's name are what a phone's top bar
       leaves out: the seat and the team's emoji say it. */
    you.replaceChildren(
      h("span", { class: "pill-lead" }, "You are the "),
      h("strong", {}, room.role === "home" ? "Home coach" : "Visitors coach"),
      coach && coach.team ? h("span", { class: "pill-lead" }, " · ") : "",
      coach && coach.team ? teamEmoji(coach.team_key, coach.team) : "",
      coach && coach.team ? h("strong", { class: "pill-team" }, coach.team) : "",
    );
    if (coach && coach.colour) you.style.setProperty("--pill-edge", coach.colour);
  } else if (mine) {
    you.replaceChildren(h("span", { class: "pill-lead" }, "You are "), h("strong", {}, mine.label));
    you.style.setProperty("--pill-edge", GOLD);
  } else {
    you.replaceChildren(h("span", { class: "pill-lead" }, "You are an "), "observer");
  }
  el("take-free-seat").hidden = Boolean(mine) || !room.seats.some((seat) => seat.free);
}

// -- The room -------------------------------------------------------------

/* The two seats as the server names them -- Coach 1 and Coach 2 until
   the coin, then Home and Visitors -- with what this reader may do to
   each. Whether a move stands is the record's; a refused one comes
   back with its sentence. */
function drawRoom(state) {
  const room = state.room;
  /* Before kickoff the table's seat cards and sideline are the room. */
  el("room").hidden = Boolean(state.table);
  const seated = room.seats.some((seat) => seat.yours);
  el("seats").replaceChildren(
    ...room.seats.map((seat) => {
      const buttons = [];
      if (seat.yours) {
        buttons.push(h("button", {
          type: "button", class: "btn",
          onclick: () => roomMove("/seat/leave"),
        }, "Leave"));
      } else if (seat.free && !seated) {
        buttons.push(h("button", {
          type: "button", class: "btn",
          onclick: () => roomMove("/seat/take", { seat: seat.number }),
        }, "Take"));
      } else if (seat.free && seated) {
        /* Anybody seated may hand the other side to the AI. */
        buttons.push(h("button", {
          type: "button", class: "btn",
          onclick: () => roomMove("/seat/ai", { seat: seat.number }),
        }, "Put Dinky in"));
      }
      if (room.admin && seat.name && !seat.yours) {
        buttons.push(h("button", {
          type: "button", class: "btn",
          onclick: () => kickSeat(seat),
        }, "Kick"));
      }
      return h("div", { class: `seat${seat.yours ? " yours" : ""}` },
        h("span", { class: "seat-label" }, seat.label),
        h("span", { class: `seat-name${seat.name ? "" : " empty"}` },
          seat.name || "Empty", seat.yours ? " (you)" : ""),
        ...buttons,
      );
    }),
  );
  el("watching").textContent =
    room.observers === 1 ? "1 watching" : `${room.observers} watching`;
  el("become-admin").hidden = room.admin;
  el("drop-admin").hidden = !room.admin;
  /* A seat may abandon a game that has kicked off and is not over (the
     record refuses one that is, and the route refuses anybody unseated,
     an admin included). Before kickoff the table's "Close this room" is
     the one way out, so the two are never offered together. */
  el("abandon").hidden = !(seated && state.scoreboard && state.game.status !== "finished");
}

// -- A finished game's numbers --------------------------------------------

/* Fetched once the game is over, and again only if something more has
   been said since; the tables are `d12ball/stats.py`'s, as the bot
   posts them in a code block, and set here as text. */
let statsFor = null;

async function drawStats(state) {
  const finished = state.game.status === "finished";
  el("stats").hidden = !finished;
  if (!finished || statsFor === state.latest) return;
  statsFor = state.latest;
  try {
    const response = await fetch(`/api/room/${GAME_ID}/stats`);
    if (!response.ok) return;
    const report = await response.json();
    el("stats-heading").textContent = report.heading;
    el("stats-tables").replaceChildren(
      ...(report.tables.length
        ? report.tables.map((lines) => h("pre", { class: "stats-table" }, lines.join("\n")))
        : [h("p", { class: "quiet" }, "Nothing was played in this game.")]),
    );
  } catch (error) {
    statsFor = null; /* tried again on the next poll */
  }
}

// -- The jumbotron bar ---------------------------------------------------

/* One bar across the top of the play area (docs/web-app-redesign.md,
   step 2): each team with its direction, its coach and the ball when
   it has it; the score; the clock with its track, last possession and
   the note between and after the halves; and a time-out tile per team.
   Every value is `layout.jumbotron`'s (webapp/board.py) or the game's
   coaches; a tile is lit only where the prompt this viewer is asked
   carries the time out for that side (`place` on its control, from
   webapp/present.py), and pressing it sends that control's answer. */
let shownJumbotron = null;

function drawJumbotron(state) {
  const layout = state.board.layout;
  const j = layout ? layout.jumbotron : null;
  const tile = timeOutControl(state.prompt);
  const shape = JSON.stringify([j, state.game.coaches, tile]);
  if (shape === shownJumbotron) return;
  shownJumbotron = shape;

  const coachOn = (side) => state.game.coaches.find((one) => one.side === side);
  const side = (where) => {
    const team = j ? j[where] : null;
    const coach = coachOn(where);
    const name = team ? team.name : coach && coach.team ? coach.team : "--";
    const arrow = where === "home" ? "▶" : "◀";
    return h(
      "div",
      { class: `jumbo-side ${where}` },
      h(
        "div",
        { class: "jumbo-team", style: team ? `color: ${team.colour}` : null },
        name, " ", h("span", { class: "jumbo-arrow" }, arrow),
      ),
      h(
        "div",
        { class: "jumbo-coach" },
        where === "home" ? "Home" : "Visitors",
        coach ? [" · ", h("b", {}, coach.name)] : "",
      ),
      team && team.possession
        ? h("div", { class: "jumbo-ball" },
          die(String(j.speed), { size: 18, fill: "#ffffff", ink: "#243347", font: 7 }), "BALL")
        : null,
    );
  };

  const parts = [
    h(
      "div",
      { class: "jumbo-teams" },
      side("home"),
      h(
        "div",
        { class: "jumbo-score" },
        h("div", { class: "jumbo-goals" }, j ? `${j.score.home} : ${j.score.visiting}` : "- : -"),
        h("div", { class: "jumbo-brand" }, "D12 BALL"),
      ),
      side("visiting"),
    ),
  ];
  if (j) {
    const tiles = h("div", { class: "jumbo-tiles" },
      ["home", "visiting"].map((where) => timeOutTile(j[where], tile && tile.place.side === where ? tile : null)));
    parts.push(h("div", { class: "jumbo-rule", "aria-hidden": "true" }), jumboClock(j, tiles));
  }
  el("jumbotron").replaceChildren(...parts);
}

/* The minute and the half, the track to the second half's last minute
   with the first half's marked, last possession, the note, and the
   time-out tiles under them. */
function jumboClock(j, tiles) {
  const { length, halftime, filled } = j.track;
  const segments = [];
  for (let i = 0; i < length; i += 1) {
    segments.push(h("span", {
      class: `seg${i < filled ? " filled" : ""}`,
    }));
  }
  return h(
    "div",
    { class: "jumbo-clock" },
    h(
      "div",
      { class: "jumbo-time" },
      h("span", { class: "jumbo-minute" }, `${j.minute}'`),
      h("span", { class: "jumbo-half" }, j.half),
      j.last_possession ? h("span", { class: "jumbo-last" }, "LAST POSSESSION") : null,
    ),
    h("div", {
      class: "jumbo-track",
      role: "img",
      "aria-label": `Minute ${j.minute} of ${length}`,
    }, segments),
    h(
      "div",
      { class: "jumbo-marks" },
      h("span", {}, "0"),
      h("span", {}, `${halftime} · halftime`),
      h("span", {}, String(length)),
    ),
    j.note ? h("div", { class: "jumbo-note" }, j.note) : null,
    tiles,
  );
}

/* The turn's time out, where the prompt put to this viewer carries it
   live: the control the question box would have drawn as a button. */
function timeOutControl(prompt) {
  if (!prompt) return null;
  for (const group of prompt.controls) {
    for (const control of group.controls) {
      if (control.place && control.place.at === "time_out_tile" && !control.disabled) {
        return control;
      }
    }
  }
  return null;
}

/* A side's time-out tile: held (outlined in the team's colour), spent
   (dashed grey, struck through), or -- only with the control in hand --
   lit gold, and pressing it answers the turn. The words are the whole
   of it; the referee's T that used to lead them went on 2026-09-26. */
function timeOutTile(team, control) {
  if (control) {
    return h(
      "button",
      {
        type: "button",
        class: "timeout-tile lit",
        style: `--team: ${team.colour}`,
        onclick: () => act(control.action),
      },
      h("span", { class: "tile-words" },
        h("span", { class: "tile-title" }, "TIME OUT"),
        h("small", {}, `${team.name} · click to call it`)),
    );
  }
  const spent = team.time_out === "spent";
  return h(
    "div",
    {
      class: `timeout-tile ${spent ? "spent" : "held"}`,
      style: `--team: ${team.colour}`,
      title: spent ? `${team.name} has had its time out this half`
        : `${team.name} still holds its time out this half`,
    },
    h("span", { class: "tile-words" },
      h("span", { class: "tile-title" }, "TIME OUT"), h("small", {}, team.name)),
  );
}

// -- The board -----------------------------------------------------------

function drawBoard(state) {
  const layout = state.board.layout;
  el("no-board").hidden = Boolean(layout);
  lit = readLit(state.prompt);
  const narrow = upright();
  const shape = JSON.stringify([layout, lit.shape, narrow]);
  if (shape === shownBoard) return;
  shownBoard = shape;
  const box = el("board");
  box.replaceChildren();
  /* The sideline is under the field, or -- held upright, where the
     field is too narrow for it -- in the sheet under the question. */
  const benches = narrow ? el("sheet-benches") : el("benches");
  el("benches").replaceChildren();
  el("sheet-benches").replaceChildren();
  el("sheet-benches").hidden = !(narrow && layout);
  drawLitRepeat(layout, state.prompt);
  if (!layout) return;
  box.append(stage(layout, { live: true, narrow }));
  watchFit(box);
  benches.append(...layout.team_boards.map((board) => sideline(board, layout)));
}

/* Turned between upright and on its side: the field is drawn again for
   the other shape. */
UPRIGHT.addEventListener("change", () => {
  shownBoard = null;
  if (current) drawBoard(current);
});

/* Held upright, the sheet repeats every thing the prompt lights on the
   board, at the desktop's size with its name and its chip, so nothing
   needs zooming to answer. It is `lit` read again -- the same controls
   the field lights, each pressed the same way -- so nothing is on it
   that is not lit on the field, and nothing lit is missing from it.
   Not in a Coaching Choice's hub, where every player is lit to pick
   up: it is answered by clicking the meeples on the field or dragging
   them between the field and the bench, and nine meeples repeated
   over its controls only pushed them down (the author, 2026-09-28). */
function drawLitRepeat(layout, prompt) {
  const box = el("lit-repeat");
  box.replaceChildren();
  const hub = Boolean(prompt && prompt.kind === "coaching_hub");
  const items = layout && lit && !hub ? litItems(layout) : [];
  box.hidden = !items.length;
  if (!items.length) return;
  box.append(h("span", { class: "repeat-label" }, "LIT ON THE FIELD"), ...items);
}

function litItems(layout) {
  const items = [];
  const item = (object, name, controls, { held = false } = {}) => {
    const said = chips(controls);
    return h(
      "div",
      { class: `repeat-item${held ? " held" : ""}` },
      object,
      name ? h("span", { class: "repeat-name" }, name) : null,
      said.length ? h("span", { class: "repeat-chips" }, said) : null,
    );
  };
  const thing = (label, controls, content, extra = "") => h(
    "button",
    {
      type: "button",
      class: `repeat-thing${extra}`,
      title: controls.map((c) => c.label).join(" · "),
      "aria-label": controls[0].label,
      onclick: () => press(controls[0]),
    },
    content,
  );
  const players = new Map();
  for (const one of layout.spaces) {
    for (const m of [...one.home, ...one.visiting]) players.set(m.id, m);
  }
  for (const board of layout.team_boards) {
    for (const entry of [...board.bench, ...board.back_bench]) players.set(entry.id, entry.meeple);
  }
  /* The thing picked up first, to put back; then every lit meeple. */
  if (picked && picked.first && picked.first.at === "player" && players.has(picked.first.id)) {
    const m = players.get(picked.first.id);
    items.push(item(meeple(m, layout), `${m.name} · picked up`, [], { held: true }));
  }
  for (const [id, controls] of Object.entries(lit.player)) {
    const m = players.get(id);
    if (!m) continue;
    items.push(item(meeple(m, layout, { controls }), m.name, controls));
  }
  for (const one of layout.spaces) {
    const controls = lit.space[`${one.zone}:${one.index}`];
    if (controls) {
      items.push(item(thing(one.code, controls, h("span", { class: "repeat-code" }, one.code), " space"),
        `Space ${one.code}`, controls));
    }
  }
  if (lit.ball.length) {
    const speed = (layout.spaces.find((one) => one.ball) || {}).ball;
    items.push(item(thing("ball", lit.ball, die(String(speed ? speed.speed : ""), {
      size: 40, fill: "#ffffff", ink: "#243347", font: 18, ring: true,
    }), " ball"), "The ball", lit.ball));
  }
  for (const side of ["home", "visiting"]) {
    const colour = layout.jumbotron[side].colour;
    const name = layout.jumbotron[side].name;
    const goals = lit.goal[side];
    if (goals) {
      items.push(item(thing("goal", goals, h("span", { class: "repeat-goal", style: `--team: ${colour}` }, "GOAL"), " goal"),
        `${name}'s goal`, goals));
    }
    const out = lit.out[side];
    if (out) items.push(item(thing("out", out, "✕", " out"), "Out of play", out));
    const tile = lit.tile[side];
    if (tile) {
      items.push(item(thing("tile", tile, h("span", { class: "repeat-tile", style: `--team: ${colour}` }, "TIME OUT"), " tile"),
        name, tile));
    }
    const bench = lit.bench[side];
    if (bench) {
      items.push(item(thing("bench", bench, h("span", { class: "repeat-tile", style: `--team: ${colour}` }, "BENCH"), " tile"),
        name, bench));
    }
  }
  return items;
}

/* Redraw what a pick changes: the board's lit things, and the box's
   line saying what is picked up. */
function redrawPick() {
  drawPickToast();
  if (!current) return;
  shownBoard = null;
  drawBoard(current);
  if (current.prompt) drawControls(current.prompt);
}

function drawPickToast() {
  const toast = el("pick-toast");
  const hint = picked ? pickHint(picked) : "";
  toast.hidden = !hint;
  toast.textContent = hint;
}

/* What may be done with the thing just picked up, said from the
   answers that start from it: another meeple to trade zones with, a
   lit space in its own zone, or the player a bench meeple replaces. */
function pickHint(entry) {
  const choices = new Set();
  for (const group of (current && current.prompt ? current.prompt.controls : [])) {
    for (const control of group.controls) {
      if (control.first && !control.disabled && placeKey(control.first) === entry.key) {
        choices.add(control.action.choice);
      }
    }
  }
  const ways = [];
  if (choices.has("substitute")) ways.push("click the player they replace");
  if (choices.has("swap")) ways.push("click another meeple to trade zones");
  if (choices.has("reposition")) ways.push(`${ways.length ? "" : "click "}a lit space to move within the zone`);
  if (!ways.length) return "";
  const said = ways.join(", or ");
  return `${entry.label}: ${said.charAt(0).toUpperCase()}${said.slice(1)}.`;
}

// -- Answering on the board ------------------------------------------------

/* What the prompt put to this viewer lights on the board: every live
   control whose `place` names a thing the field draws -- a meeple, a
   space, the ball, a goal, the out-of-play mark past an end, a
   time-out tile -- indexed by that thing. The control is the server's
   (webapp/present.py, off `PendingPrompt.options`); the page only
   finds the object and attaches the click. A control the prompt has
   greyed lights nothing: the question box says why it is dark. */
const BOARD_OBJECTS = new Set([
  "player", "space", "ball", "goal", "out_of_play", "time_out_tile", "bench",
]);

/* A control may light more than one thing (`also`): a Set Up's shot is
   the goal and the shooter, and clicking either sends it. */
function readLit(prompt) {
  const index = {
    player: {}, space: {}, ball: [], goal: {}, out: {}, tile: {}, bench: {}, shape: [],
    pickable: {}, picked,
  };
  if (!prompt) return index;
  const add = (map, key, control) => { (map[key] = map[key] || []).push(control); };
  index.shape.push(["picked", picked && picked.key]);
  for (const group of prompt.controls) {
    for (const control of group.controls) {
      if (!control.place || control.disabled) continue;
      /* An answer given with two things (`first`, then `place`): its
         first thing is lit until one is picked up, and then the second
         thing of every answer that starts from it. */
      if (control.first) {
        const key = placeKey(control.first);
        const picks = (index.pickable[key] = index.pickable[key] || []);
        if (!picks.some((one) => one.chip === control.first_chip)) {
          picks.push({
            type: "pick", key, first: control.first, chip: control.first_chip,
            label: pickName(control),
          });
        }
        if (!picked || picked.key !== key) continue;
      }
      for (const place of [control.place, ...(control.also || [])]) {
        if (!BOARD_OBJECTS.has(place.at)) continue;
        index.shape.push([place, control.chip, control.cost]);
        if (place.at === "player") add(index.player, place.id, control);
        else if (place.at === "space") add(index.space, `${place.zone}:${place.space_index}`, control);
        else if (place.at === "ball") index.ball.push(control);
        else if (place.at === "goal") add(index.goal, place.side, control);
        else if (place.at === "out_of_play") add(index.out, place.side, control);
        else if (place.at === "time_out_tile") add(index.tile, place.side, control);
        else if (place.at === "bench") add(index.bench, place.side, control);
      }
    }
  }
  /* Nothing picked up yet: what may be is what is lit. */
  if (!picked) {
    for (const picks of Object.values(index.pickable)) {
      const first = picks[0].first;
      if (first.at !== "player") continue;
      for (const one of picks) add(index.player, first.id, one);
      index.shape.push([first, picks.map((one) => one.chip)]);
    }
  }
  return index;
}

/* Whether a meeple is drawn -- on the field or on the sideline under
   it, where a lit piece is drawn; a player lit who is neither is
   answered from the question box instead. */
function onField(layout, playerId) {
  return Boolean(layout) && (
    layout.spaces.some((one) =>
      one.home.some((m) => m.id === playerId) || one.visiting.some((m) => m.id === playerId))
    || layout.team_boards.some((board) =>
      [...board.bench, ...board.back_bench].some((entry) => entry.id === playerId)));
}

/* A thing on the board as one string, to match a pick to the answers
   that start from it and a drop to the thing it landed on. */
function placeKey(place) {
  if (place.at === "player") return `player:${place.id}`;
  if (place.at === "space") return `space:${place.zone}:${place.space_index}`;
  return place.at;
}

/* What the thing picked up first is called: the control's own label up
   to where the second thing is named ("Voltus [DD]" of "Voltus [DD] on
   for ..."), which is the engine's spelling of the player. */
function pickName(control) {
  const match = /^(.*?\[[A-Z]+\])/.exec(control.label);
  return match ? match[1] : control.label;
}

/* Picking a thing up, or putting it back: the same thing twice, or
   Esc, lets go. */
function pick(entry) {
  picked = entry && (!picked || picked.key !== entry.key) ? entry : null;
  redrawPick();
}

/* A drag from a thing that may be picked up onto the thing it goes on:
   the same answer as clicking the two in turn. The drag picks it up as
   it starts, so what it may be dropped on lights; a drop on anything
   else leaves it picked up, to be clicked. */
let dragged = 0;
function dragPick(node, key) {
  const picks = lit && lit.pickable[key];
  if (!picks) return;
  node.style.touchAction = "none";
  node.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const start = { x: event.clientX, y: event.clientY };
    let ghost = null;
    const move = (moved) => {
      if (!ghost) {
        if (Math.hypot(moved.clientX - start.x, moved.clientY - start.y) < 8) return;
        ghost = node.cloneNode(true);
        ghost.classList.add("drag-ghost");
        document.body.append(ghost);
        if (!picked || picked.key !== key) pick(picks[0]);
      }
      ghost.style.left = `${moved.clientX}px`;
      ghost.style.top = `${moved.clientY}px`;
    };
    const up = (released) => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      if (!ghost) return;
      ghost.remove();
      dragged = Date.now();
      if (released.type !== "pointerup") return;
      const under = document.elementFromPoint(released.clientX, released.clientY);
      const target = under && under.closest("[data-place]");
      if (!target || !current || !current.prompt) return;
      const control = current.prompt.controls
        .flatMap((group) => group.controls)
        .find((one) => one.first && !one.disabled && placeKey(one.first) === key
          && placeKey(one.place) === target.dataset.place);
      if (control) press(control);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
  });
}

/* Pressing a control: its answer, or -- for a chooser -- its question
   opened in the box, or for the rematch the room's own route. */
function press(control) {
  if (!control || control.disabled) return;
  if (control.action && control.action.kind === "shootout_order") {
    pressOrder(control);
    return;
  }
  if (control.type === "pick") {
    pick(control);
    return;
  }
  if (control.type === "chooser") {
    openChooser = control;
    if (current && current.prompt) drawControls(current.prompt);
    return;
  }
  if (control.post) roomMove(control.post);
  else act(control.action);
}

/* A lit thing's chips: what clicking it means, one per control on it,
   each its own button where there are several (Overdrive and Boost on
   one meeple, a pass and a run onto it on one space). */
function chips(all, { buttons } = {}) {
  /* A thing to pick up with no chip of its own (a player in the
     Coaching Choice) is lit and says nothing. */
  const controls = all.filter((control) => control.type !== "pick" || control.chip);
  if (buttons === undefined) buttons = controls.length > 1;
  return controls.map((control) => {
    const content = chip(control);
    if (!buttons) return content;
    return h("button", {
      type: "button",
      class: "chip-button",
      title: control.label,
      onclick: (event) => { event.stopPropagation(); press(control); },
    }, content);
  });
}

/* The field, drawn from scratch (docs/web-app-redesign.md, step 1): a
   dark stage with the zone names over a row of spaces between the two
   goals, and the shooting ranges under it. Every value on it is
   `webapp/board.py`'s; the jumbotron has its own bar, and the benches
   are the sideline under it. */
function stage(layout, { live, narrow = false }) {
  return h(
    "div",
    { class: `stage${narrow ? " narrow" : ""}`, onclick: live ? openBoardOnPhone : null },
    pitch(layout, narrow),
  );
}

function pitch(layout, narrow = false) {
  const zones = h(
    "div",
    { class: "field-row zone-names" },
    layout.zones.map((zone) =>
      h(
        "div",
        {
          class: "zone-name",
          style: `flex: ${zone.spaces}${zone.colour ? `; color: ${zone.colour}` : ""}`,
        },
        zone.label,
      )),
  );
  const spaces = h(
    "div",
    { class: "field-spaces" },
    goal("home", layout.jumbotron.home.colour, narrow),
    layout.spaces.map((one) => space(one, layout, narrow)),
    goal("visiting", layout.jumbotron.visiting.colour, narrow),
  );
  const bands = h(
    "div",
    { class: "field-row bands" },
    layout.bands.map((band) =>
      h(
        "div",
        {
          class: `band${band.lit ? " lit" : ""}`,
          style: `flex: ${band.last - band.first + 1}${band.colour ? `; --team: ${band.colour}` : ""}`,
        },
        band.label,
      )),
  );
  return h("div", { class: "pitch" }, zones, spaces, bands);
}

/* A goal: a slab in the defending side's colour with GOAL along it,
   the d12 showing 12 for its O, turned to read along the goal. It is
   lit when a prompt names it -- the shot -- and pressing it answers;
   past it, the ✕ a pass is put out of play at, when one is offered. */
function goal(side, colour, narrow = false) {
  const controls = (lit && lit.goal[side]) || [];
  const out = (lit && lit.out[side]) || [];
  const on = controls.length > 0;
  const said = `The ${side === "home" ? "home" : "visitors'"} goal`;
  return h(
    on ? "button" : "div",
    {
      type: on ? "button" : null,
      class: `goal ${side}${on ? " lit" : ""}${out.length ? " out-lit" : ""}`,
      style: `--team: ${colour}`,
      role: on ? null : "img",
      "aria-label": on ? `${said}: ${controls[0].label}` : said,
      title: on ? controls[0].label : null,
      "data-goal": side,
      onclick: on ? (event) => { event.stopPropagation(); press(controls[0]); } : null,
    },
    h(
      "span",
      { class: "goal-word" },
      h("span", {}, "G"),
      narrow
        ? die("12", { size: 18, fill: "#0c141c", ink: colour, font: 7 })
        : die("12", { size: 56, fill: "#0c141c", ink: colour, font: 24 }),
      h("span", {}, "A"),
      h("span", {}, "L"),
    ),
    on ? h("span", { class: "goal-chips" }, chips(controls, { buttons: false })) : null,
    out.length
      ? h("span", {
        class: "out-mark",
        role: "button",
        tabindex: "0",
        title: `${out[0].label}: drag the ball here, or click`,
        "aria-label": out[0].label,
        "data-out": side,
        onclick: (event) => { event.stopPropagation(); press(out[0]); },
        onkeydown: (event) => { if (event.key === "Enter") press(out[0]); },
      }, "✕", h("span", { class: "out-chip" }, chip(out[0])))
      : null,
  );
}

function space(one, layout, narrow = false) {
  const loose = one.ball && !one[one.ball.side].length;
  const controls = (lit && lit.space[`${one.zone}:${one.index}`]) || [];
  const on = controls.length > 0;
  const marks = lit ? lit.player : {};
  return h(
    "div",
    {
      class: `space${one.tint ? " tinted" : ""}${on ? " lit" : ""}`,
      style: one.tint ? `--tint: ${one.tint}` : null,
      "data-place": `space:${one.zone}:${one.index}`,
      title: on ? controls.map((c) => c.label).join(" · ") : null,
      /* A lit space is answered by clicking anywhere on it that is not
         a piece of its own (a meeple opens its card). */
      onclick: on ? (event) => { event.stopPropagation(); press(controls[0]); } : null,
    },
    h("span", { class: "space-code" }, one.code),
    one.kickoff ? h("span", { class: "kickoff-ring" }) : null,
    h("div", { class: "lane visiting" }, fanOf(one, "visiting", layout, marks, narrow)),
    h("div", { class: "lane home" }, fanOf(one, "home", layout, marks, narrow)),
    loose ? h("span", { class: "loose-ball" }, ball(one.ball.speed, narrow ? 22 : 36, { lit: true })) : null,
    on ? h("span", { class: "space-chips" }, chips(controls)) : null,
  );
}

/* One team's meeples on a space, overlapped where `board.py` placed
   them, back to front, with each name on its own line under the fan
   (the front piece's first) and every badge and the ball drawn over
   the whole of it. `marks` is what a prompt lights: a piece's id to
   the chip saying what clicking it means. */
function fanOf(one, side, layout, marks = {}, narrow = false) {
  /* Held upright, the narrow fan at the phone's own steps, and no
     names under it: the sheet names whatever is lit, and a hold on a
     piece opens its card. */
  const drawn = narrow ? one.narrow_fans[side] : one.fans[side];
  if (!drawn.pieces.length) return null;
  const g = narrow ? layout.narrow_meeple : layout.meeple;
  const W = g.width;
  const H = (W * g.box[3]) / g.box[2];
  const tall = Math.max(...drawn.pieces.map((p) => p.y)) + H;
  const box = h("span", { class: "fan", style: `width: ${drawn.width}px` });
  const over = [];
  drawn.pieces.forEach((piece, index) => {
    const lit = piece.id in marks;
    box.append(
      h(
        "span",
        {
          class: "fan-piece",
          style: `left: ${piece.x}px; top: ${piece.y}px; z-index: ${index + 1}`,
        },
        meeple(piece, layout, { controls: marks[piece.id], narrow }),
      ),
    );
    over.push(...badges(piece, piece.x, piece.y, W, H));
    if (one.ball && one.ball.holder === piece.id) {
      /* Off the top right of a home holder, almost touching the
         shoulder; off the bottom left of a visiting one, over the edge
         by the foot. */
      /* Narrow, the space has no room beside the piece: the ball sits
         on its shoulder, inside the space, rather than off it. */
      const size = narrow ? 16 : 30;
      const place = narrow
        ? side === "home"
          ? `left: ${piece.x + W - size}px; top: ${piece.y - size * 0.5}px`
          : `left: ${piece.x}px; top: ${piece.y + H - size}px`
        : side === "home"
          ? `left: ${piece.x + W * 0.66}px; top: ${piece.y - 22}px`
          : `left: ${piece.x - 18}px; top: ${piece.y + H - 30}px`;
      over.push(h("span", { class: "held-ball", style: place }, ball(one.ball.speed, size, { lit: true })));
    }
  });
  if (narrow) {
    box.append(...over);
    box.style.height = `${tall}px`;
    return box;
  }
  /* Names front first, each centred under its own piece. */
  let line = tall + 4;
  const byId = Object.fromEntries(drawn.pieces.map((p) => [p.id, p]));
  for (const id of drawn.names) {
    const piece = byId[id];
    const lit = id in marks;
    const held = Boolean(picked && picked.key === `player:${id}`);
    over.push(h(
      "span",
      { class: `fan-name${lit || held ? " lit" : ""}`, style: `left: ${piece.x + W / 2}px; top: ${line}px` },
      piece.name,
    ));
    line += 24;
    const said = lit ? chips(marks[id]) : [];
    if (said.length) {
      over.push(h(
        "span",
        { class: "fan-chip-line", style: `left: ${piece.x + W / 2}px; top: ${line}px` },
        said,
      ));
      line += 32;
    }
  }
  box.append(...over);
  box.style.height = `${line}px`;
  return box;
}

/* A piece's badges, over it wherever it stands (a fan on a space, the
   sideline): the exhaustion token and its count off the bottom right,
   the condition off the bottom left -- the emoji `board.py` names. */
function badges(piece, x, y, W, H) {
  const over = [];
  if (piece.exhaustion) {
    over.push(h(
      "span",
      {
        class: "badge tokens",
        style: `left: ${x + W * 0.62}px; top: ${y + H * 0.68}px`,
        title: `${piece.exhaustion.count} ${piece.exhaustion.emoji === "exhaust" ? "exhaustion" : "drain"}`,
      },
      h("img", { src: `/emoji/${piece.exhaustion.emoji}.png`, alt: "" }),
      String(piece.exhaustion.count),
    ));
  }
  if (piece.condition) {
    over.push(h(
      "span",
      {
        class: "badge condition",
        style: `left: ${x - 8}px; top: ${y + H - 14}px`,
        title: piece.condition[0].toUpperCase() + piece.condition.slice(1),
      },
      h("img", { src: `/emoji/${piece.condition}.png`, alt: piece.condition }),
    ));
  }
  return over;
}

/* What clicking a lit thing means (the control's `chip`), with any
   cost as the token image and a count -- never the word "token". */
function chip(control) {
  return h(
    "span",
    { class: "chip" },
    control.chip || control.label,
    control.cost
      ? h("span", { class: "chip-cost" },
        h("img", { src: `/emoji/${control.cost.emoji}.png`, alt: "" }),
        `×${control.cost.count}`)
      : null,
  );
}

/* A meeple, lit gold where a control names it: clicking a lit one
   answers, clicking any other opens its card. */
function meeple(m, layout, { controls = null, narrow = false } = {}) {
  const on = Boolean(controls && controls.length);
  const key = `player:${m.id}`;
  const held = Boolean(picked && picked.key === key);
  const picks = !on && lit && lit.pickable[key];
  const g = narrow ? layout.narrow_meeple : layout.meeple;
  const node = litMeeple(m, layout, controls, on, held, picks, g);
  if (lit && lit.pickable[key]) dragPick(node, key);
  return node;
}

function litMeeple(m, layout, controls, lit, held, picks, g = layout.meeple) {
  const [, , width, height] = g.box;
  const W = g.width;
  const H = (W * height) / width;
  const node = h(
    "button",
    {
      type: "button",
      class: `meeple${lit ? " lit" : ""}${held ? " picked" : ""}${picks ? " pickable" : ""}`,
      style: `width: ${W}px; height: ${H}px; color: ${m.ink}`,
      "data-place": `player:${m.id}`,
      title: lit ? `${m.name} [${m.role}]: ${controls[0].chip || controls[0].label}`
        : held ? `${m.name} [${m.role}]: picked up -- click again or Esc to put it back`
          : `${m.name} [${m.role}]`,
      "aria-label": lit ? controls[0].label
        : held ? `${m.name} [${m.role}], picked up: put it back`
          : picks ? `${m.name} [${m.role}]: pick up` : `${m.name} [${m.role}]`,
      "aria-pressed": held ? "true" : null,
      onclick: (event) => {
        event.stopPropagation();
        if (Date.now() - dragged < 300) return;
        if (lit) press(controls[0]);
        else if (held || picks) pick(held ? picked : picks[0]);
        else openCard(m.id);
      },
    },
    meepleArt(m, layout, { ring: lit || held, dashed: held, g }),
  );
  /* Not while a Coaching Choice is open: a card over the meeple being
     picked up and dropped confuses more than it tells, and the Teams
     tab is up instead (the author, 2026-09-26). */
  hoverCard(node, cardUrl(m.id), { when: () => !coaching(current && current.prompt) });
  return node;
}

/* A meeple's own drawing, for whatever holds it: the Screentop piece in
   the team's colour, edged gold where it is lit, the species icon and
   the role badge. */
function meepleArt(m, layout, { ring = false, dashed = false, g = layout.meeple } = {}) {
  const [left, top, width, height] = g.box;
  const W = g.width;
  const icon = layout.species_icons && m.species;
  const center = icon ? g.role_center : g.solo_center;
  return [
    s(
      "svg",
      { viewBox: `${left} ${top} ${width} ${height}`, "aria-hidden": "true" },
      s("path", {
        d: g.path,
        fill: m.colour,
        stroke: ring ? GOLD : m.ink,
        "stroke-width": String(ring ? g.stroke * 1.5 : g.stroke),
        "stroke-dasharray": dashed ? String(g.stroke * 2.2) : null,
        "stroke-linejoin": "round",
      }),
    ),
    icon
      ? h("span", {
        class: "species-icon",
        style: `--icon: url("/species/${m.species}.png"); top: ${g.icon_center * 100}%; `
          + `width: ${g.icon_size * W}px; height: ${g.icon_size * W}px`,
      })
      : null,
    h(
      "span",
      {
        class: "meeple-role",
        style: `top: ${center * 100}%; font-size: ${(icon ? g.role_font : g.solo_font) * W}px`,
      },
      m.role,
    ),
  ];
}

const GOLD = "#f0b232";

/* The ball: the d12 showing its speed, on a dark ring. On the field
   (`lit: true` asks) it is lit where a control names it -- the
   maneuver, or sending nobody -- and it may be dragged off the end to
   the ✕ where a pass may be put out of play. */
function ball(speed, size, { lit: onField = false } = {}) {
  const face = die(String(speed), {
    size, fill: "#ffffff", ink: "#243347", font: size * 0.44, ring: true,
  });
  const controls = onField && lit ? lit.ball : [];
  const out = onField && lit ? Object.values(lit.out).flat() : [];
  if (!controls.length && !out.length) return face;
  const node = h(
    "button",
    {
      type: "button",
      class: `ball-button${controls.length ? " lit" : ""}${out.length ? " draggable" : ""}`,
      title: controls.length ? controls.map((c) => c.label).join(" · ") : "Drag the ball off the end to put it out of play",
      "aria-label": controls.length ? controls[0].label : "The ball",
      onclick: (event) => {
        event.stopPropagation();
        if (controls.length) press(controls[0]);
      },
    },
    face,
    controls.length ? h("span", { class: "ball-chips" }, chips(controls, { buttons: false })) : null,
  );
  if (out.length) dragOff(node, out);
  return node;
}

/* Putting a pass out of play by dragging the ball past the end: let go
   over the ✕ (or the goal it is drawn on) and it is the same answer as
   clicking the ✕. */
function dragOff(node, out) {
  let dragging = null;
  node.addEventListener("pointerdown", (event) => {
    dragging = { x: event.clientX, y: event.clientY, id: event.pointerId };
    node.setPointerCapture(event.pointerId);
  });
  node.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    node.style.transform = `translate(${event.clientX - dragging.x}px, ${event.clientY - dragging.y}px)`;
    node.classList.add("dragging");
  });
  const drop = (event) => {
    if (!dragging) return;
    const moved = Math.hypot(event.clientX - dragging.x, event.clientY - dragging.y);
    dragging = null;
    node.style.transform = "";
    node.classList.remove("dragging");
    if (moved < 8) return;
    node.style.visibility = "hidden";
    const under = document.elementFromPoint(event.clientX, event.clientY);
    node.style.visibility = "";
    const end = under && under.closest("[data-out], [data-goal]");
    const side = end && (end.dataset.out || end.dataset.goal);
    const control = out.find((one) => one.place.side === side);
    if (control) press(control);
  };
  node.addEventListener("pointerup", drop);
  node.addEventListener("pointercancel", () => {
    dragging = null;
    node.style.transform = "";
    node.classList.remove("dragging");
  });
}

/* A d12 face-on: the ten-sided outline the design draws, a number on it. */
function die(label, { size, fill, ink, font, ring = false }) {
  const points = [];
  for (let i = 0; i < 10; i += 1) {
    const angle = (Math.PI / 5) * i - Math.PI / 2;
    points.push(`${(Math.cos(angle) * 50).toFixed(2)},${(Math.sin(angle) * 50).toFixed(2)}`);
  }
  return s(
    "svg",
    {
      class: ring ? "die ringed" : "die",
      viewBox: "-52 -52 104 104",
      width: size,
      height: size,
      role: "img",
      "aria-label": `d12 showing ${label}`,
    },
    s("polygon", {
      points: points.join(" "),
      fill,
      stroke: ink,
      "stroke-width": String((2 / size) * 100),
    }),
    s(
      "text",
      {
        x: "0",
        y: "0",
        "text-anchor": "middle",
        "dominant-baseline": "central",
        "font-size": String((font / size) * 100),
        "font-weight": "800",
        fill: ink,
      },
      label,
    ),
  );
}

/* The sideline under the field (docs/web-app-redesign.md, step 6): a
   team's bench ("may come on") and back bench ("off for the game"), the
   record's own two rows, each a box edged in the team's colour holding
   the meeples as the field draws them, badges and all, with the hover
   card. Home's on the left and the visitors' on the right, under their
   own ends. Lit gold as a whole where a prompt names the bench -- the
   Coaching Offer -- and then a click on it answers; a meeple on it is
   lit where a prompt names that player -- the Coaching Choice's
   substitutes. */
function sideline(board, layout) {
  const controls = (lit && lit.bench[board.side]) || [];
  const on = controls.length > 0;
  /* Lit, a click anywhere on it that is not a meeple answers (a meeple
     still opens its card), and the chip is the answer as a real button,
     for the keyboard -- the meeples are buttons, so the side is not. */
  return h(
    "div",
    {
      class: `sideline-team ${board.side}${on ? " lit" : ""}`,
      style: `--team: ${board.colour}`,
      title: on ? controls[0].label : null,
      onclick: on ? (event) => {
        if (event.target.closest(".meeple, .chip-button")) return;
        press(controls[0]);
      } : null,
    },
    benchBox(board, `${board.name.toUpperCase()} BENCH`, "may come on", board.bench, layout),
    benchBox(board, "BACK BENCH", "off for the game", board.back_bench, layout),
    on ? h("span", { class: "sideline-chips" }, chips(controls, { buttons: true })) : null,
  );
}

function benchBox(board, title, said, entries, layout) {
  return h(
    "div",
    { class: "bench-box", role: "group", "aria-label": `${board.name} ${title.toLowerCase()}` },
    h("div", { class: "bench-head" },
      h("span", { class: "bench-title" }, title),
      h("span", { class: "bench-said" }, said)),
    h(
      "div",
      { class: "bench-pieces" },
      entries.length
        ? entries.map((entry) => benchPiece(entry.meeple, layout))
        : h("span", { class: "bench-empty" }, "Empty"),
    ),
  );
}

/* One benched meeple: the piece, its badges over it as on the field,
   its name under it, and -- lit -- what clicking it means. */
function benchPiece(m, layout) {
  const marks = (lit && lit.player[m.id]) || null;
  const on = Boolean(marks && marks.length);
  const said = on ? chips(marks) : [];
  const g = layout.meeple;
  const W = g.width;
  const H = (W * g.box[3]) / g.box[2];
  const body = h("span", { class: "bench-body", style: `width: ${W}px; height: ${H}px` },
    meeple(m, layout, { controls: marks }), ...badges(m, 0, 0, W, H));
  return h(
    "span",
    { class: "bench-piece" },
    body,
    h("span", { class: `bench-name${on || (picked && picked.key === `player:${m.id}`) ? " lit" : ""}` }, m.name),
    said.length ? h("span", { class: "bench-chip-line" }, said) : null,
  );
}

// -- Fitting a board to its box ----------------------------------------

const fitted = new WeakMap();
const fitter = new ResizeObserver((records) => {
  for (const record of records) {
    const box = record.target.classList.contains("board-fit")
      ? record.target
      : record.target.parentElement;
    if (box) fit(box);
  }
});

function watchFit(box) {
  const inner = box.firstElementChild;
  if (!inner) return;
  fitter.observe(box);
  fitter.observe(inner);
  clampNames(inner);
  fit(box);
}

/* A name is centred under its own piece and kept inside its space,
   which clips whatever is left over: nothing on the field leaves the
   space it stands on. Measured in layout pixels, before the stage's
   scale, so it is the same on every screen. */
function clampNames(root) {
  for (const name of root.querySelectorAll(".fan-name, .fan-chip-line")) {
    name.style.setProperty("--nudge", "0px");
    const fan = name.offsetParent;
    const space = name.closest(".space");
    if (!fan || !space || !name.offsetWidth) continue;
    const left = fan.offsetLeft + name.offsetLeft - name.offsetWidth / 2;
    const least = 4;
    const most = space.clientWidth - 4 - name.offsetWidth;
    const nudge = Math.max(least, Math.min(left, most)) - left;
    name.style.setProperty("--nudge", `${nudge}px`);
  }
}

function fit(box) {
  const inner = box.firstElementChild;
  if (!inner) return;
  const max = Number(box.dataset.max || 1.35);
  /* The narrow field is laid out at the box's own width, unscaled. */
  const scale = inner.classList.contains("narrow")
    ? 1 : Math.min(max, box.clientWidth / STAGE_WIDTH);
  const height = Math.ceil(inner.offsetHeight * scale);
  /* A ResizeObserver hears its own height change; answering that with
     the same numbers is what keeps it from looping. */
  const last = fitted.get(box);
  if (last && last.inner === inner && last.scale === scale && last.height === height) return;
  fitted.set(box, { inner, scale, height });
  inner.style.transform = scale === 1 ? "" : `scale(${scale})`;
  box.style.height = `${height}px`;
}

// -- The game log -------------------------------------------------------------

/* The minute the log last put a heading over, so a heading goes up
   only when it changes. */
let journalMinute = null;

function drawJournal(state) {
  if (!state.entries.length) return;
  news("log");
  const journal = el("journal");
  const empty = el("journal-empty");
  if (empty) empty.remove();
  const nearBottom = journal.scrollHeight - journal.scrollTop - journal.clientHeight < 80;
  for (const entry of state.entries) {
    /* The minute as a small heading when it changes: the clock the
       result left, as the journal kept it. */
    if (entry.minute !== null && entry.minute !== undefined) {
      const minute = `${entry.minute}' · ${entry.half}`;
      if (minute !== journalMinute) {
        journal.append(h("div", { class: "log-minute" }, minute));
        journalMinute = minute;
      }
    }
    /* The edge is the entry's kind (`Entry.kind`): a goal, a new play,
       a roll, the clock or a line -- the model's facts, never the
       words read for them. */
    const block = h("div", { class: `entry kind-${entry.kind || "line"}` });
    /* Words only: the log draws no picture (2026-09-26, the author).
       A question's picture is in the question area, and goes with it. */
    for (const line of entry.lines) block.append(h("p", { html: line }));
    journal.append(block);
  }
  if (nearBottom || !journal.dataset.scrolled) {
    journal.scrollTop = journal.scrollHeight;
    journal.dataset.scrolled = "1";
  }
}

// -- The chat -----------------------------------------------------------------

function clock(seconds) {
  return new Date(seconds * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function drawChat(state) {
  /* A post's answer and a poll can cross: a line already drawn is not
     drawn twice. */
  const drawn = chatLatest;
  chatLatest = Math.max(chatLatest, state.chat_latest);
  const fresh = state.chat.filter((message) => message.id > drawn);
  if (!fresh.length) return;
  news("chat");
  const chat = el("chat");
  const empty = el("chat-empty");
  if (empty) empty.remove();
  const nearBottom = chat.scrollHeight - chat.scrollTop - chat.clientHeight < 60;
  for (const message of fresh) {
    /* Everything here goes in as text (`h` appends a string as a text
       node): a chat line is never markdown, a token or markup. */
    chat.append(
      h(
        "p",
        { class: message.yours ? "chat-line yours" : "chat-line" },
        h("time", {}, clock(message.at)),
        h("span", { class: "chat-who", style: message.colour ? `color: ${message.colour}` : null },
          message.name),
        message.text,
      ),
    );
  }
  if (nearBottom || !chat.dataset.scrolled) {
    chat.scrollTop = chat.scrollHeight;
    chat.dataset.scrolled = "1";
  }
}

// -- The prompt --------------------------------------------------------------

/* The two questions of a Coaching Choice: whether to take one, and
   the window itself. */
const COACHING_KINDS = new Set(["coaching_offer", "coaching_hub"]);
function coaching(prompt) {
  return Boolean(prompt && COACHING_KINDS.has(prompt.kind));
}

/* A Coaching Choice opening brings up the Teams tab, whose rosters are
   what a coach decides it from (the author, 2026-09-26) -- once, as it
   opens, so a coach who goes back to the log is left there. */
let wasCoaching = false;
function teamsOnCoaching(prompt) {
  const now = coaching(prompt);
  if (now && !wasCoaching) showPane("teams");
  wasCoaching = now;
}

function drawPrompt(state) {
  teamsOnCoaching(state.prompt);
  const box = el("prompt");
  /*
   * Only when it has actually changed. The page re-reads the whole
   * state every couple of seconds, and rebuilding the controls each
   * time would throw away a menu somebody is halfway through
   * choosing from.
   */
  const shape = JSON.stringify(state.prompt);
  /* The REMATCH mark turns into a link once the rematch is made, which
     is the room's news and not the prompt's. */
  const rematch = state.rematch ? state.rematch.url : null;
  if (shape === shownPrompt && rematch === shownRematch) return;
  shownRematch = rematch;
  shownPrompt = shape;
  openChooser = null;
  picked = null;
  if (!state.prompt) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const yours = state.prompt.yours;
  if (yours) news("move", "yours");
  /* The tag is the server's reading of whose question this is
     (`_box_state`, off `asked_sides`); the page only names it. */
  box.dataset.state = state.prompt.state;
  el("prompt-state").textContent = boxTag(state.prompt);
  el("ask").innerHTML = state.prompt.ask;
  drawPicture(state.prompt);
  drawReference(state.prompt);
  drawControls(state.prompt);
}

/* A phone's tag and ask where the question box is not in sight: the
   slim strip under the field on its side, and the sheet's gold edge
   held upright. Copied from whichever box is up -- the question, or
   the table before kickoff -- so it says nothing the box does not. */
function drawStrip() {
  const box = !el("prompt").hidden ? el("prompt") : !el("table").hidden ? el("table-box") : null;
  const tag = el("strip-state");
  const said = box === el("prompt") ? el("prompt-state") : el("table-state");
  const state = box === el("prompt") ? box.dataset.state : box ? el("table-box").dataset.state : null;
  tag.hidden = !box || !said.textContent;
  tag.textContent = box ? said.textContent : "";
  tag.className = said.className;
  const ask = box === el("prompt") ? el("ask") : el("table-ask");
  el("strip-ask").innerHTML = box ? ask.innerHTML : "";
  el("move-pane").dataset.state = state || "";
  el("strip").dataset.state = state || "";
}

/* The question box's four tags, by the state the server read. */
const BOX_STATES = {
  yours: "Your move",
  waiting: "Waiting on the other side",
  now: "Now",
  full_time: "Full time",
};

/* The tag's words: WAITING names who, as the server read them off
   the record (`present.waiting_on`) -- "the other side" is only
   somebody's from a seat, and an observer has none. */
function boxTag(prompt) {
  const names = prompt.waiting_on || [];
  if (prompt.state === "waiting" && names.length) {
    return `Waiting on ${names.join(" and ")}`;
  }
  return BOX_STATES[prompt.state] || "";
}

/* The dice just rolled, in the outcome at the top of the question box: on Discord the
   prompt a coach pressed becomes the dice, so this is where they are
   read. They stay until the next thing happens in the game -- the
   server says which roll, if any, is still showing -- and the log
   keeps the words. Apart from `drawPrompt`, since a tie can hand back
   the same question with a new roll behind it. */
function drawRoll(state) {
  const image = el("roll-picture");
  if (!state.roll) {
    image.hidden = true;
    image.removeAttribute("src");
    drawOutcome();
    return;
  }
  if (image.getAttribute("src") !== state.roll.url) image.src = state.roll.url;
  image.hidden = false;
  drawOutcome();
}

/* The outcome's words, large and first: the model's own headline and
   the line it wrote under it, in the colour of the side whose outcome
   it is -- up until the next thing happens, as the dice are. The page
   words none of it ("The outcome banner", docs/design/web-app.md). */
function drawHeadline(state) {
  const headline = el("outcome-headline");
  const under = el("outcome-detail");
  const working = el("outcome-working");
  const outcome = state.outcome;
  headline.hidden = !outcome;
  under.hidden = !(outcome && outcome.under);
  working.hidden = !(outcome && outcome.working);
  if (outcome) {
    headline.innerHTML = outcome.headline;
    under.innerHTML = outcome.under || "";
    working.innerHTML = outcome.working || "";
    el("outcome").style.setProperty("--outcome", outcome.colour || "var(--gold)");
  }
  drawOutcome();
}

/* The outcome block is up while anything in it is. */
function drawOutcome() {
  el("outcome").hidden = el("roll-picture").hidden
    && el("outcome-headline").hidden;
}

/* The picture the prompt is asked over, where the cog posts one with
   the same question -- the shot, or the challenge over the maneuver
   pick -- or none. Its URL changes when the position or the question does,
   so an unchanged one is left alone rather than reloaded. */
function drawPicture(prompt) {
  const image = el("prompt-picture");
  const aside = el("prompt-aside");
  if (!prompt.picture) {
    aside.hidden = true;
    image.removeAttribute("src");
    return;
  }
  if (image.getAttribute("src") !== prompt.picture) image.src = prompt.picture;
  image.alt = prompt.kind === "score_attempt" ? "The shot" : "The challenge";
  aside.hidden = false;
}

/* The words under the maneuver pick's hand: the cards' shared back at
   the game's tier (the server's `reference`), as the hover card, while
   the pointer is on them or after a press and hold (the author,
   2026-09-27). The back is one picture a game, so the hover card is
   put on once; the hexagon is the Rules tab's References. */
let referenceHover = false;
function drawReference(prompt) {
  el("reference").hidden = !prompt.reference;
  if (!prompt.reference || referenceHover) return;
  const words = el("reference-words");
  hoverCard(words, prompt.reference);
  words.addEventListener("focus", () => showPeek(prompt.reference, words));
  words.addEventListener("blur", () => hidePeekSoon());
  referenceHover = true;
}

/* The objects the question box draws, rather than the board: the die
   to roll, the faces of a speed to choose, the whistle, the note, the
   REMATCH mark, the hand's cards. */
const BOX_OBJECTS = new Set(["die", "face", "whistle", "note", "rematch", "card", "formation"]);

/* Whether a control is drawn in the question box: the neutral ones, the
   box's own objects, and a meeple lit that is not on the field to be
   clicked (a bench, say), which is answered from here instead. */
function inBox(control) {
  const place = control.place;
  if (!place) return true;
  if (BOX_OBJECTS.has(place.at)) return true;
  /* An answer given with two things is made on the board, the two
     picked in turn -- or dragged -- and the keyboard list has it too. */
  if (control.first) return !(current && current.board.layout);
  if (place.at === "player") {
    return !onField(current && current.board.layout, place.id);
  }
  if (place.at === "time_out_tile" || place.at === "out_of_play" || place.at === "bench") return false;
  /* A space, a goal or the ball are always drawn while there is a
     board; a disabled one is dark there and said in the lit line. */
  return !(current && current.board.layout);
}

function drawControls(prompt) {
  drawPickToast();
  const controls = el("controls");
  controls.replaceChildren();
  drawLitLine(prompt);
  drawKeys(prompt);
  el("prompt").classList.toggle("note-lit", Boolean(noteControl(prompt)));

  /* A chooser opened from the board: its one question, a neutral
     control per answer, and a way back. */
  if (openChooser) {
    controls.append(drawOpenChooser(openChooser));
    return;
  }

  /* A thing picked up on the board (the Coaching Choice): what it is,
     and how to put it back. */
  if (picked) {
    controls.append(h("div", { class: "row picked-line" },
      h("span", {}, h("b", {}, picked.label), " is picked up: click where it goes, or drag it there."),
      neutral("Put it back", () => pick(null), { title: "Esc" })));
  }

  for (const group of prompt.controls.filter((one) => one.order)) {
    controls.append(drawOrder(group));
  }
  const groups = prompt.controls
    .filter((group) => !group.order)
    .map((group) => ({ ...group, controls: group.controls.filter(inBox) }))
    .filter((group) => group.controls.length);

  /* The groups answered on the board say how, once each, first: a
     line per move the board answers, then a row of tiles for the
     things the box draws (the formations), all above the whistle and
     set off from it by a rule (the author, 2026-09-26). */
  const how = prompt.controls.filter((group) => group.how);
  if (how.length) {
    const block = h("div", { class: "how" });
    const rows = [];
    for (const group of how) {
      const here = group.controls.filter(inBox);
      if (here.length) {
        rows.push(h("div", { class: "how-row" },
          h("span", { class: "how-label" }, `${group.label.toUpperCase()} · ${group.how}`),
          drawGroup({ ...group, controls: here })));
      } else {
        block.append(h("p", { class: "how-line" }, h("b", {}, `${group.label}:`), ` ${group.how}.`));
      }
    }
    block.append(...rows);
    controls.append(block);
  }

  for (const group of groups.filter((one) => !one.how)) {
    if (group.label) controls.append(h("div", { class: "group-label" }, group.label));
    controls.append(drawGroup(group));
  }
  appendNotes(controls, groups);
  const table = handTable(prompt);
  if (table) controls.append(table);
  const sides = shootoutSides(prompt);
  if (sides) controls.append(sides);

  /* A Coaching Choice says its lit line -- the window's allowance --
     under the whistle rather than under the ask (the author,
     2026-09-26); `drawLitLine` leaves the usual place empty for it. */
  if (coaching(prompt)) {
    const items = litItemsOf(prompt);
    if (items.length) controls.append(h("p", { class: "lit-line" }, ...items));
  }

  /* The Spreadable reminder, under the whistle rather than the title
     (`present.split_footnote`). */
  if (prompt.footnote) {
    controls.append(h("p", { class: "footnote", html: prompt.footnote }));
  }
}

/* What is lit on the board and why, and -- muted -- what is dark:
   the server's reading of the controls it built (`present.lit_line`). */
function drawLitLine(prompt) {
  const line = el("lit");
  const items = coaching(prompt) ? [] : litItemsOf(prompt);
  line.hidden = !items.length;
  line.replaceChildren(...items);
}

function litItemsOf(prompt) {
  /* With a thing picked up, the box says that instead: what was lit
     before it was picked up is not what is lit now. */
  const items = picked ? [] : prompt.lit || [];
  return items.map((item) =>
    h("span", { class: item.dark ? "lit-item dark" : "lit-item" }, item.text));
}

/* The same controls as a list for the keyboard: a number key presses
   the control of that number, in the order the options give, Enter
   the only one there is, and Esc backs out of an open menu. Hidden
   until it has the focus. */
let keyed = [];
function drawKeys(prompt) {
  keyed = prompt.controls.flatMap((group) => group.controls)
    .filter((control) => !control.disabled);
  el("keys").replaceChildren(...keyed.map((control, index) =>
    h("li", {}, h("button", {
      type: "button",
      onclick: () => press(control),
    }, `${index + 1}. ${control.label}${control.chip && control.chip !== control.label ? ` (${control.chip})` : ""}`))));
}

function noteControl(prompt) {
  for (const group of prompt.controls) {
    for (const control of group.controls) {
      if (control.place && control.place.at === "note" && !control.disabled) return control;
    }
  }
  return null;
}

/* A dead control's reason, said under the controls -- the Done a
   kickoff space holds back is said under the whistle itself. */
function appendNotes(controls, groups) {
  for (const group of groups) {
    for (const control of group.controls) {
      if (control.type === "button" && control.disabled && control.note
          && !control.place && !group.label) {
        controls.append(h("p", { class: "note-line" }, control.note));
      }
    }
  }
}

function drawGroup(group) {
  if (group.controls.length && group.controls.every((one) => one.card)) {
    return handRows(group.controls);
  }
  if (group.controls.length && group.controls.every((one) => one.place && one.place.at === "face")) {
    return h("div", { class: "faces" }, group.controls.map(face));
  }
  if (group.controls.length && group.controls.every((one) => one.place && one.place.at === "formation")) {
    return h("div", { class: "formations" }, group.controls.map(formationTile));
  }
  return h("div", { class: "row" }, group.controls.map(drawControl));
}

function drawControl(control) {
  if (control.type === "chooser") return drawChooser(control);
  const at = control.place && control.place.at;
  if (at === "die") return bigDie(control);
  if (at === "whistle") {
    return whistle({
      allowed: !control.disabled,
      label: control.label,
      note: control.disabled ? control.note : "",
      onclick: () => press(control),
    });
  }
  if (at === "rematch") return rematchMark(control);
  if (at === "note") {
    return h("span", { class: "note-chip" }, chip({ ...control, chip: "click the note to go on" }));
  }
  if (at === "face") return face(control);
  if (at === "card") return handCard(control);
  /* The neutral control, and a meeple answered from the box. */
  const button = neutral(control.label, () => press(control), {
    disabled: control.disabled,
    title: control.note || null,
  });
  if (control.player) hoverCard(button, cardUrl(control.player));
  return button;
}

/* A formation's tile: its shape as dots per zone, left to right as the
   field is, in the side's colour -- the counts are the server's
   (`control.shape`, off the ruleset), the page draws them. The shape a
   side stands in is dead and marked "now". */
function formationTile(control) {
  const side = control.action.arguments.side;
  const layout = current && current.board.layout;
  const colour = layout ? layout.jumbotron[side].colour : GOLD;
  const now = control.disabled;
  return h(
    "button",
    {
      type: "button",
      class: `formation${now ? " now" : ""}`,
      disabled: now,
      title: now ? control.note : `Set up in ${control.label}`,
      "aria-label": now ? `${control.label}: ${control.note}` : `Formation ${control.label}`,
      onclick: () => press(control),
    },
    h("span", { class: "formation-dots" },
      (control.shape || []).map((count) => h("span", { class: "formation-zone" },
        Array.from({ length: count }, () => h("span", { class: "dot", style: `background: ${colour}` }))))),
    h("span", { class: "formation-name" }, now ? `${control.label} · now` : control.label),
  );
}

/* The one neutral control: outlined, no fill, no colour. */
function neutral(label, onclick, { disabled = false, title = null } = {}) {
  return h("button", { type: "button", class: "btn", disabled, title, onclick }, label);
}

/* The die: large, lit, and clicking it rolls. */
function bigDie(control) {
  return h(
    "button",
    {
      type: "button",
      class: "big-die",
      title: control.label,
      "aria-label": control.label,
      onclick: () => press(control),
    },
    h("span", { class: "big-die-ring" },
      die("?", { size: 72, fill: "#1e1f22", ink: GOLD, font: 31 })),
    h("span", { class: "big-die-word" }, control.chip || control.label),
  );
}

/* One face of a speed to choose: a d12 showing it, lit. */
function face(control) {
  return h(
    "button",
    {
      type: "button",
      class: "face",
      disabled: control.disabled,
      title: control.note || control.label,
      "aria-label": control.label,
      onclick: () => press(control),
    },
    die(String(control.place.value), { size: 52, fill: "#ffffff", ink: "#243347", font: 24 }),
  );
}

/* The whistle: Done, Start the game, Pick it up. A pea-whistle, gold
   on a dark disc when the position allows it and grey when it does
   not, with the reason under it. */
function whistle({ allowed, label, note = "", onclick }) {
  const colour = allowed ? GOLD : "#6d6f78";
  return h(
    "div",
    { class: "whistle-wrap" },
    h(
      "button",
      {
        type: "button",
        class: `whistle${allowed ? " lit" : ""}`,
        disabled: !allowed,
        title: note || label,
        onclick,
      },
      h("span", { class: "whistle-disc" },
        s(
          "svg",
          { width: "38", height: "38", viewBox: "0 0 40 40", "aria-hidden": "true" },
          s(
            "g",
            { transform: "rotate(-14 20 20)" },
            s("path", {
              d: "M16.5 10.8 H33 a2.9 2.9 0 0 1 2.9 2.9 v0.8 a2.9 2.9 0 0 1 -2.9 2.9 H23.2 L22 20.5 A8.6 8.6 0 1 1 13.2 12.7 a3.4 3.4 0 0 1 3.3 -1.9 Z",
              fill: colour,
            }),
            s("rect", { x: "17.2", y: "12.1", width: "4.6", height: "2.1", rx: "0.6", fill: "#1e1f22" }),
            s("circle", { cx: "13.6", cy: "21.2", r: "2.7", fill: "#1e1f22" }),
          ),
          s("circle", { cx: "6.6", cy: "31.4", r: "3.1", fill: "none", stroke: colour, "stroke-width": "1.9" }),
        )),
      h("span", { class: "whistle-label" }, label),
    ),
    note ? h("p", { class: "note-line whistle-note" }, note) : null,
  );
}

/* The REMATCH mark: a new room with this one's settings and seats --
   and once somebody has made it, a link to that room. */
function rematchMark(control) {
  const made = current && current.rematch;
  const mark = made
    ? h("a", { class: "rematch-mark", href: made.url, title: "This game's rematch" }, "REMATCH")
    : h("button", {
      type: "button",
      class: "rematch-mark",
      title: "A new room with this game's settings and seats",
      onclick: () => press(control),
    }, "REMATCH");
  return h("div", { class: "rematch-wrap" }, mark,
    h("p", { class: "note-line" },
      "A rematch is a room of its own with the same seats, and this room keeps pointing at it."));
}

/* The hand as the printed cards (docs/web-app-redesign.md, step 5): the
   basic three in a row and the gambits in a row under them, a gambit
   the side does not hold dimmed with the reason -- which cards are which
   is the server's (`card.gambit`, `card.withheld`); the page counts
   nothing. */
function handRows(controls) {
  const basic = controls.filter((one) => !one.card.gambit);
  const gambits = controls.filter((one) => one.card.gambit);
  const rows = h("div", { class: "hand-rows" });
  if (basic.length) rows.append(h("div", { class: "hand" }, basic.map(handCard)));
  if (gambits.length) {
    const withheld = gambits.find((one) => one.card.withheld);
    rows.append(
      h("div", { class: "hand-label" },
        "Gambits",
        withheld ? h("span", { class: "quiet" }, ` · ${withheld.note.replace(/\.$/, "").toLowerCase()}`) : null),
      h("div", { class: "hand" }, gambits.map(handCard)),
    );
  }
  return rows;
}

function maneuverUrl(key, side, size = "small") {
  const url = `/api/game/${GAME_ID}/maneuver/${encodeURIComponent(key)}.png?side=${side}`;
  return size === "full" ? `${url}&size=full` : url;
}

function handCard(control) {
  const { key, side } = control.card;
  const url = maneuverUrl(key, side);
  const button = h(
    "button",
    {
      type: "button",
      class: `hand-card${control.card.withheld ? " withheld" : ""}${control.card.picked ? " picked" : ""}`,
      disabled: control.disabled,
      title: control.note || control.label,
      "aria-label": control.note ? `${control.label}: ${control.note}` : control.label,
      onclick: () => press(control),
    },
    h("img", { src: url, alt: control.label }),
    control.card.picked ? h("span", { class: "hand-card-chip" }, control.chip) : null,
  );
  hoverCard(button, maneuverUrl(key, side, "full"));
  return button;
}

/* The hands this viewer does not hold (`present.hand_table`): only the
   line that says they are turned over together. Their face-down backs
   are not drawn in the question box (the author, 2026-09-27); the card
   this coach laid down is in their own hand, ringed. */
function handTable(prompt) {
  const table = prompt.hand;
  if (!table) return null;
  return h(
    "div",
    { class: "hand-table" },
    h("p", { class: "note-line" }, table.note),
  );
}

/* The shootout's secret order (docs/web-app-redesign.md, step 7): a
   slot per shooter, the order already sent in the first of them
   (`group.order.placed`, the record's, sent to this seat alone) and the
   rest filled here, in the page's own draft, from the players still to
   place -- which are the options' `send` controls and nothing else. A
   meeple goes into a slot by a drag or a click (the next empty one), a
   drag between slots swaps them, a drag or a click back takes it out,
   and the whistle sends each name in slot order: the `send` a Discord
   menu sends a click at a time, each one offered as it goes. The draft
   is never posted until then, so nobody else can see it. */
const orderDrafts = new Map();

function orderSends(group) {
  return group.controls.filter((one) => one.action.choice === "send");
}

/* This side's draft: as many slots as are still to fill, kept across
   redraws while the players to place are the same ones -- the other
   side setting its order changes the prompt, not this draft. */
function orderDraft(group) {
  const order = group.order;
  const pool = orderSends(group).map((one) => one.player).sort();
  const key = JSON.stringify([order.placed.map((one) => one.id), pool]);
  let draft = orderDrafts.get(order.side);
  if (!draft || draft.key !== key) {
    draft = { key, side: order.side, slots: Array(order.slots - order.placed.length).fill(null) };
    orderDrafts.set(order.side, draft);
  }
  return draft;
}

function orderGroups() {
  return current && current.prompt
    ? current.prompt.controls.filter((group) => group.order)
    : [];
}

/* The order section for one side, as the page now holds it: a poll
   replaces the state without redrawing a prompt that has not changed,
   so a control a key or a click holds is matched by its side rather
   than by being the same object. */
function orderGroup(side) {
  return orderGroups().find((group) => group.order.side === side) || null;
}

/* The order section whose draft is full, ready to lock, or null. */
function fullOrder() {
  return orderGroups().find((group) => orderDraft(group).slots.every(Boolean)) || null;
}

function draftedAny() {
  return orderGroups().some((group) => orderDraft(group).slots.some(Boolean));
}

function clearDrafts() {
  for (const group of orderGroups()) orderDraft(group).slots.fill(null);
  redrawOrder();
}

/* The panel is drawn again after every move in it, so the card a
   hover opened over the piece that moved is put away with it. */
function redrawOrder() {
  hidePeek();
  if (current && current.prompt) drawControls(current.prompt);
}

/* A number key, or anything else that presses one of the order's
   controls: a player goes into the next empty slot, or back out of the
   one they are in; Start again empties the draft, and takes back what
   was already sent where anything was. */
function pressOrder(control) {
  const group = orderGroup(control.action.arguments.side);
  if (!group) return;
  const draft = orderDraft(group);
  if (control.action.choice === "restart") {
    draft.slots.fill(null);
    if (group.order.placed.length) act(control.action);
    else redrawOrder();
    return;
  }
  const at = draft.slots.indexOf(control.player);
  if (at >= 0) draft.slots[at] = null;
  else {
    const empty = draft.slots.indexOf(null);
    if (empty < 0) return;
    draft.slots[empty] = control.player;
  }
  redrawOrder();
}

/* Where a drag ends: a slot (by its index in the draft), or the pool. */
function dropOrder(draft, playerId, target) {
  const from = draft.slots.indexOf(playerId);
  if (target.dataset.slot !== undefined) {
    const to = Number(target.dataset.slot);
    if (from >= 0) draft.slots[from] = draft.slots[to];
    draft.slots[to] = playerId;
  } else if (target.dataset.pool !== undefined && from >= 0) {
    draft.slots[from] = null;
  }
  redrawOrder();
}

function dragOrder(node, draft, playerId) {
  node.style.touchAction = "none";
  node.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const start = { x: event.clientX, y: event.clientY };
    let ghost = null;
    const move = (moved) => {
      if (!ghost) {
        if (Math.hypot(moved.clientX - start.x, moved.clientY - start.y) < 8) return;
        ghost = node.cloneNode(true);
        ghost.classList.add("drag-ghost");
        document.body.append(ghost);
        hidePeek();
      }
      ghost.style.left = `${moved.clientX}px`;
      ghost.style.top = `${moved.clientY}px`;
    };
    const up = (released) => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      if (!ghost) return;
      ghost.remove();
      dragged = Date.now();
      if (released.type !== "pointerup") return;
      hidePeek();
      const under = document.elementFromPoint(released.clientX, released.clientY);
      const target = under && under.closest("[data-slot], [data-pool]");
      if (target) dropOrder(draft, playerId, target);
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
  });
}

/* A player as the order panel draws them: the meeple the field draws,
   found by id on the layout, and the name under it. */
function layoutMeeple(layout, playerId) {
  if (!layout) return null;
  for (const one of layout.spaces) {
    for (const m of [...one.home, ...one.visiting]) if (m.id === playerId) return m;
  }
  for (const board of layout.team_boards) {
    for (const entry of [...board.bench, ...board.back_bench]) {
      if (entry.id === playerId) return entry.meeple;
    }
  }
  return null;
}

function orderPiece(playerId, label, { lit = false, onclick = null, title = null } = {}) {
  const layout = current && current.board.layout;
  const m = layoutMeeple(layout, playerId);
  const g = layout && layout.meeple;
  const art = m
    ? h("span", {
      class: "order-meeple",
      style: `width: ${g.width}px; height: ${(g.width * g.box[3]) / g.box[2]}px; color: ${m.ink}`,
    }, meepleArt(m, layout, { ring: lit }))
    : null;
  const piece = h(
    onclick ? "button" : "span",
    {
      type: onclick ? "button" : null,
      class: `order-piece${lit ? " lit" : ""}`,
      title: title || label,
      "aria-label": title || label,
      onclick: onclick ? (event) => {
        event.stopPropagation();
        if (Date.now() - dragged < 300) return;
        onclick();
      } : null,
    },
    art,
    h("span", { class: "order-name" }, m ? m.name : label),
  );
  hoverCard(piece, cardUrl(playerId));
  return piece;
}

function drawOrder(group) {
  const order = group.order;
  const draft = orderDraft(group);
  const sends = orderSends(group);
  const byPlayer = new Map(sends.map((one) => [one.player, one]));
  const restart = group.controls.find((one) => one.action.choice === "restart");
  const full = draft.slots.every(Boolean);

  const slots = [
    ...order.placed.map((one, index) => h(
      "div",
      { class: "order-slot sent", title: `${index + 1}. ${one.label}: sent` },
      h("span", { class: "order-number" }, String(index + 1)),
      orderPiece(one.id, one.label),
    )),
    ...draft.slots.map((playerId, index) => {
      const number = order.placed.length + index + 1;
      const control = playerId && byPlayer.get(playerId);
      const piece = control ? orderPiece(playerId, control.label, {
        onclick: () => pressOrder(control),
        title: `${number}. ${control.label}: click to take out, or drag to another slot`,
      }) : null;
      if (piece) dragOrder(piece, draft, playerId);
      return h(
        "div",
        { class: `order-slot${piece ? "" : " empty"}`, "data-slot": String(index), "aria-label": `Slot ${number}` },
        h("span", { class: "order-number" }, String(number)),
        piece,
      );
    }),
  ];

  const pool = sends.filter((one) => !draft.slots.includes(one.player));
  const poolRow = h(
    "div",
    { class: "order-pool", "data-pool": "" },
    pool.length
      ? pool.map((control) => {
        const piece = orderPiece(control.player, control.label, {
          lit: true,
          onclick: () => pressOrder(control),
          title: `${control.label}: into the next slot, or drag to a slot`,
        });
        dragOrder(piece, draft, control.player);
        return piece;
      })
      : h("span", { class: "order-empty" }, "Everybody is placed."),
  );

  return h(
    "div",
    { class: "order-panel" },
    h("div", { class: "order-main" },
      h("div", { class: "order-column" },
        h("span", { class: "group-label" }, "Your order"),
        h("span", { class: "how-line" }, "drag each meeple into a slot, or click them in the order they shoot; drag between slots to reorder"),
        h("div", { class: "order-slots" }, slots)),
      h("div", { class: "order-column" },
        h("span", { class: "group-label" }, "Still to place"),
        poolRow)),
    h("div", { class: "order-foot" },
      restart ? neutral("Start again", () => pressOrder(restart), { title: "Esc" }) : null,
      whistle({
        allowed: full,
        label: "Lock the order",
        note: full ? "" : "The whistle lights when the last slot is filled.",
        onclick: () => lockOrder(orderGroup(order.side)),
      })),
    h("p", { class: "note-line" }, "Only your seat sees this panel, and nothing of it is sent until the whistle."),
  );
}

/* The whistle: each name in slot order, as the options offer it. A
   refusal stops it where it is, and the page shows the order as the
   game then holds it. */
async function lockOrder(group) {
  if (busy || !group) return;
  const draft = orderDraft(group);
  if (!draft.slots.every(Boolean)) return;
  const byPlayer = new Map(orderSends(group).map((one) => [one.player, one]));
  const actions = draft.slots.map((playerId) => byPlayer.get(playerId).action);
  busy = true;
  hidePeek();
  el("prompt").classList.add("busy");
  let state = null;
  try {
    for (const action of actions) {
      const response = await api(`/action?${cursors()}`, {
        method: "POST",
        body: JSON.stringify({ action }),
      });
      state = await response.json();
      /* The cursor is left where it was, so the last answer brings
         every line the others said. */
      if (!response.ok || state.refusal) break;
    }
  } catch (error) {
    showRefusal("That did not reach the game. Try again in a moment.");
  } finally {
    busy = false;
    el("prompt").classList.remove("busy");
  }
  if (state) draw(state);
}

/* Whether each side has answered the shootout's secret question, and
   nothing else about it (`present.shootout_sides`): the same for both
   coaches and every observer. */
function shootoutSides(prompt) {
  const said = prompt.shootout;
  if (!said) return null;
  return h(
    "div",
    { class: "shootout-sides" },
    h("div", { class: "row" }, said.sides.map((one) => h(
      "span",
      { class: `side-tag${one.done ? " done" : ""}`, style: `--team: ${teamColour(one.team_side)}` },
      `${one.team} ${one.said}`.toUpperCase(),
    ))),
    h("p", { class: "note-line" }, said.note),
  );
}

function teamColour(side) {
  const layout = current && current.board.layout;
  return layout ? layout.jumbotron[side].colour : "var(--muted)";
}

/* Both cards face up, once both are in, until the maneuver is over:
   what the cards said between them -- TIE, or BEATS pointing at the
   card beaten, the engine's reading (`present.reveal`). What the
   maneuver came to is the outcome's headline, above it. */
let shownReveal = null;
function drawReveal(state) {
  const box = el("reveal");
  const shape = JSON.stringify(state.reveal);
  if (shape === shownReveal) return;
  shownReveal = shape;
  const reveal = state.reveal;
  box.hidden = !reveal;
  if (!reveal) {
    box.replaceChildren();
    return;
  }
  const card = (one) => {
    const node = h(
      "figure",
      { class: `reveal-card${reveal.winner === one.side ? " won" : ""}` },
      h("img", { src: maneuverUrl(one.key, one.side), alt: one.name }),
    );
    hoverCard(node, maneuverUrl(one.key, one.side, "full"));
    return node;
  };
  const word = reveal.winner === "offense" ? `${reveal.between} ▶`
    : reveal.winner === "defense" ? `◀ ${reveal.between}` : reveal.between;
  box.replaceChildren(
    card(reveal.cards[0]),
    h("div", { class: `reveal-between${reveal.winner === "tie" ? " tie" : ""}` }, word),
    ...reveal.cards.slice(1).map(card),
  );
}

/* Full time, beside the result: each side's numbers, read by
   `d12ball/stats.py` (`present.full_time`) and drawn in the team's
   colour, then the ways on -- the rooms, and the whole log as text.
   The REMATCH mark is the prompt's own control. */
let shownFullTime = null;
function drawFullTime(state) {
  const box = el("full-time");
  const shape = JSON.stringify(state.full_time);
  if (shape === shownFullTime) return;
  shownFullTime = shape;
  const block = state.full_time;
  box.hidden = !block;
  if (!block) {
    box.replaceChildren();
    return;
  }
  const side = (colour, text) => h("td", { class: "ft-number", style: `color: ${colour}` }, text);
  box.replaceChildren(
    h(
      "table",
      { class: "ft-stats" },
      h("thead", {}, h("tr", {},
        h("th", { style: `color: ${block.home_colour}` }, block.home),
        h("th", {}, ""),
        h("th", { style: `color: ${block.visiting_colour}` }, block.visiting))),
      h("tbody", {}, ...block.rows.map((row) => h("tr", {},
        side(block.home_colour, row.home),
        h("td", { class: "ft-label" }, row.label),
        side(block.visiting_colour, row.visiting)))),
    ),
    h("p", { class: "note-line" },
      "The numbers are the statistics the bot's /d12ball stats reports, read the same way."),
    h("div", { class: "row ft-links" },
      h("a", { class: "btn", href: "/" }, "Back to the rooms"),
      h("a", { class: "linkish", href: block.log, target: "_blank", rel: "noopener" }, "the whole log as text")),
  );
}

/* A chooser in the box: its sentence, a menu per field, and a neutral
   control that sends them (the hub's substitution and swaps). */
function drawChooser(control) {
  const row = h("div", { class: "chooser" });
  if (control.label) row.append(h("span", { class: "chooser-label" }, control.label));
  const selects = {};
  for (const field of control.fields) {
    if (field.label) row.append(h("label", {}, field.label));
    const select = h(
      "select",
      { "aria-label": field.label || control.label || field.name },
      field.choices.map((choice) => h("option", { value: choice.value }, choice.label)),
    );
    selects[field.name] = select;
    row.append(select);
  }
  row.append(neutral(control.submit, () => {
    const args = { ...control.action.arguments };
    for (const [name, select] of Object.entries(selects)) args[name] = select.value;
    act({ ...control.action, arguments: args });
  }));
  return row;
}

/* A chooser opened from its object on the board: its one question, a
   neutral control per answer, and Back. */
function drawOpenChooser(control) {
  const field = control.fields[0];
  const answer = (value) => {
    openChooser = null;
    act({ ...control.action, arguments: { ...control.action.arguments, [field.name]: value } });
  };
  return h(
    "div",
    { class: "controls" },
    h("div", { class: "chooser-label" }, control.label),
    h("div", { class: "row" },
      field.choices.map((choice) => {
        const button = neutral(choice.label, () => answer(choice.value));
        hoverCard(button, cardUrl(choice.value));
        return button;
      }),
      neutral("Back", () => { openChooser = null; drawControls(current.prompt); })),
  );
}

// -- The table ---------------------------------------------------------------

/* Before kickoff, in the prompt's place (row 1 of the design canvas):
   the two seat cards with their teams, the settings as pills, the
   question box -- the whistle, the coin, the goal to defend -- and the
   sideline. Everything on it is `state.table` and `state.room`: which
   setting is open and what the record says of the rest, which team a
   seat is offered, who owes the toss and the choice, where the AI may
   sit, are the game record's answers, and a press the record refuses
   comes back with its sentence. An observer is sent the same table
   with every control off. */
function drawTable(state) {
  const box = el("table");
  const table = state.table;
  const shape = JSON.stringify([table, state.room]);
  if (shape === shownTable) return;
  shownTable = shape;
  if (!table) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  if (table.yours) news("move", "yours");
  el("seat-cards").replaceChildren(...table.seats.map((seat) => seatCard(seat, state.room)));
  drawSettings(table);
  drawTableBox(table);
  drawSideline(table, state.room);
}

/* What a drag carries: yourself or Dinky off the sideline, or a name
   out of a seat. The drop is the same move the click beside it makes. */
function seatDrag(event, what) {
  event.dataTransfer.setData("text/plain", what);
  event.dataTransfer.effectAllowed = "move";
  document.body.classList.add("dragging-seat");
}
document.addEventListener("dragend", () => document.body.classList.remove("dragging-seat"));

function seatDropTarget(node, accept) {
  node.addEventListener("dragover", (event) => {
    event.preventDefault();
    node.classList.add("drop-over");
  });
  node.addEventListener("dragleave", () => node.classList.remove("drop-over"));
  node.addEventListener("drop", (event) => {
    event.preventDefault();
    node.classList.remove("drop-over");
    accept(event.dataTransfer.getData("text/plain"));
  });
}

/* A seat's holder taken out: yourself, which is leaving it; the AI,
   by anybody seated, as putting it in is; or -- an admin's --
   somebody else. The last two are a kick and are asked first. Every
   way out of a seat (the ✕, a drag to the sideline) comes through
   here. */
function seatOut(seat, room) {
  if (seat.yours) {
    roomMove("/seat/leave");
  } else if (mayKick(seat, room)) {
    kickSeat(seat);
  }
}

function mayKick(seat, room) {
  if (!seat.name) return false;
  return room.admin || (seat.ai && room.seats.some((one) => one.yours));
}

function kickSeat(seat) {
  if (confirm(`Are you sure? ${seat.name} will lose ${seat.label}.`)) {
    roomMove("/seat/kick", { seat: seat.number });
  }
}

function seatCard(seat, room) {
  const seated = room.seats.some((one) => one.yours);
  const mayOut = seat.yours || mayKick(seat, room);
  const chips = [];
  if (seat.yours) chips.push(h("span", { class: "tag-chip you" }, "YOU"));
  if (seat.ai) chips.push(h("span", { class: "tag-chip ai" }, "AI"));

  let holder;
  if (seat.name) {
    holder = h("div", {
      class: `seat-holder${mayOut ? " draggable" : ""}`,
      draggable: mayOut ? "true" : null,
      title: mayOut ? (seat.yours ? "Drag out of the seat to leave it" : "Drag out to free the seat") : null,
      ondragstart: mayOut ? (event) => seatDrag(event, `seat:${seat.number}`) : null,
    }, seat.name);
  } else if (seat.free && !seated && current.you.coach) {
    holder = h("button", {
      type: "button",
      class: "seat-holder empty",
      onclick: () => roomMove("/seat/take", { seat: seat.number }),
    }, "Empty seat · click to sit");
  } else {
    holder = h("div", { class: "seat-holder empty" }, "Empty seat");
  }

  const card = h(
    "div",
    { class: `seat-card${seat.yours ? " yours" : ""}${seat.free ? " open" : ""}`, "data-seat": seat.number },
    h("div", { class: "seat-card-head" },
      h("span", { class: "field-label" }, seat.label.toUpperCase()),
      h("span", { class: "grow" }),
      chips,
      mayOut
        ? h("button", {
          type: "button",
          class: "seat-out",
          title: seat.yours ? "Leave this seat" : `Take ${seat.name} out of ${seat.label}`,
          "aria-label": seat.yours ? "Leave this seat" : `Take ${seat.name} out of ${seat.label}`,
          onclick: () => seatOut(seat, room),
        }, "✕")
        : null),
    holder,
    // The team pick opens once somebody holds the seat (the author,
    // 2026-09-27).
    seat.free ? null : seatTeamLine(seat),
    seat.teams.length && !seat.free ? drawTeams(seat) : null,
    seatHint(seat, room, seated),
  );
  if (seat.free) {
    seatDropTarget(card, (what) => {
      if (what === "me") roomMove("/seat/take", { seat: seat.number });
      else if (what === "dinky") roomMove("/seat/ai", { seat: seat.number });
    });
  }
  return card;
}

function seatTeamLine(seat) {
  if (seat.team) {
    return h("div", { class: "seat-team" },
      h("span", { class: "team-dot big", style: `background: ${seat.colour}` }),
      teamEmoji(seat.team_key, seat.team), h("b", {}, seat.team));
  }
  const mayPick = seat.teams.some((team) => team.open);
  if (seat.picks_itself) {
    return h("div", { class: `seat-team${mayPick ? " owed" : ""}` },
      mayPick
        ? `Pick a team for ${seat.name}, or ${seat.name} picks when the coin is flipped`
        : `${seat.name} picks a team when the coin is flipped`);
  }
  if (seat.teams.length) {
    return h("div", { class: `seat-team${mayPick ? " owed" : ""}` },
      mayPick ? "Pick a team" : "Still to pick a team");
  }
  return null;
}

function seatHint(seat, room, seated) {
  let hint = null;
  if (seat.name && !seat.yours && room.admin) hint = `Drag ${seat.name} out, or click ✕, to free the seat`;
  else if (seat.free && seated && room.ai_seats.includes(seat.number)) {
    return h("div", { class: "seat-hint" },
      h("span", {}, "Invite your friends to play with this "),
      h("a", {
        class: "linkish",
        href: roomLink(),
        title: "Copy the room's link",
        "data-copied": "room link (copied)",
        onclick: (event) => { event.preventDefault(); copyLink(event); },
      }, "room link"),
      h("span", {}, " or "),
      h("button", {
        type: "button",
        class: "linkish",
        onclick: () => roomMove("/seat/ai", { seat: seat.number }),
      }, "play against AI"));
  } else if (seat.free && !seated) hint = "Drag your name in from the sideline, or click the seat";
  return hint ? h("div", { class: "seat-hint" }, hint) : null;
}

/* A seat's swatches: the colour teams and the species teams, a row
   each. Greyed where the record's `teams_open_to` does not offer the
   team, gold-edged on the seat's own pick, and pressable only in the
   reader's own seat. */
function drawTeams(seat) {
  const row = (number, label) => [
    h("span", { class: "swatch-label" }, label),
    h("div", { class: "swatches" },
      seat.teams.filter((team) => team.row === number).map((team) => h("button", {
        type: "button",
        class: `swatch${team.picked ? " picked" : ""}${team.offered ? "" : " greyed"}`,
        style: `background: ${team.colour}`,
        title: team.name,
        "aria-label": team.picked ? `${team.name} (picked)` : team.name,
        disabled: !team.open,
        onclick: () => roomMove("/table/pick_team", { team: team.key, seat: seat.number }),
      }, number === 1 ? teamEmoji(team.key, team.name) : null))),
  ];
  return h("div", { class: "table-teams" },
    row(0, "Color teams"),
    row(1, "Species teams"));
}

/* The settings: a row of gold pills per setting, the current value
   gold and the rest outlined, with the record's note -- why a value
   is dark -- beside it; the room's name edited in place. */
function drawSettings(table) {
  el("table-settings").replaceChildren(
    h("div", { class: "settings-head" },
      h("span", { class: "field-label" }, "SETTINGS"),
      h("span", { class: "quiet faint" },
        "the gold pill is how it stands; click another to change it, either coach may")),
    // The name is changed in the top bar's topic, not here (the
    // author, 2026-09-27).
    ...table.settings.filter((setting) => setting.name !== "name").map(drawSetting),
  );
}

function pill(label, { current = false, disabled = false, onclick = null, title = null } = {}) {
  return h("button", {
    type: "button",
    class: `pill${current ? " current" : ""}`,
    disabled: disabled || current,
    "aria-pressed": current ? "true" : "false",
    title,
    onclick,
  }, label);
}

function drawSetting(setting) {
  const off = !setting.may_change;
  /* A change that takes something away (the model's `warning`: a test
     game kicks Dinky) is confirmed first. */
  const configure = (value) => {
    if (setting.warning && !confirm(setting.warning)) return;
    roomMove("/table/configure", { setting: setting.name, value });
  };
  let control;
  if (setting.choices.length) {
    control = h("div", { class: "pills" }, setting.choices.map((choice) => pill(choice.label, {
      current: choice.value === setting.value,
      disabled: off || !choice.open,
      title: choice.definition || null,
      onclick: () => configure(choice.value),
    })));
  } else {
    control = h("div", { class: "pills" }, [false, true].map((value) => pill(value ? "On" : "Off", {
      current: setting.value === value,
      disabled: off || !setting.toggle_open,
      onclick: () => configure(null),
    })));
  }
  /* What the setting is (the model's definition), then why a value is
     dark (the record's refusal), when there is one of each. */
  const said = [setting.definition, setting.note].filter(Boolean);
  return h("div", { class: "table-setting" },
    h("span", { class: "setting-label" }, setting.label), control,
    said.length
      ? h("span", { class: "setting-note" },
        setting.definition ? h("span", { class: "setting-definition" }, setting.definition) : null,
        setting.definition && setting.note ? " · " : null,
        setting.note || null)
      : null);
}

/* The question box at the table: one question at a time, each the
   record's -- Start while the lobby is open, then the teams, the coin,
   and the goal the toss's winner defends. */
function drawTableBox(table) {
  const qbox = el("table-box");
  qbox.dataset.state = table.yours ? "yours" : "waiting";
  el("table-state").textContent = table.yours ? "Your move" : table.lobby ? "The lobby" : "Setting up";
  const ask = el("table-ask");
  const body = el("table-body");
  const coin = table.coin;
  const nameOf = (number) => {
    const seat = table.seats.find((one) => one.number === number);
    return seat ? seat.name || seat.label : "nobody";
  };

  if (table.start.owed) {
    /* The coin starts the game (the author, 2026-09-27: no whistle):
       dark, with the record's own sentence under it, while
       `start_lobby` would refuse; flipped, it leaves the lobby and
       tosses in one request. */
    const allowed = table.start.may && !table.start.refusal;
    ask.textContent = table.start.refusal
      ? "Once both seats are filled and teams are picked: flip a coin to start the game!"
      : table.start.may
        ? "Flip the coin to start the game!"
        : "Either coach flips the coin to start the game.";
    body.replaceChildren(h("div", { class: "row table-row" },
      coinSides(coin, {
        allowed,
        title: table.start.refusal || "Flip the coin to start the game",
        label: "Flip the coin to start the game",
      }),
      // What the toss decides (the author, 2026-09-27); why the coin is
      // dark is the ask above it, and the record's sentence its title.
      h("span", { class: "quiet faint" },
        "The winner of the coin toss chooses whether to play as the home or visiting team.")));
    return;
  }

  if (!coin.flipped && !coin.owed) {
    const waiting = table.seats.filter((seat) => !seat.team);
    ask.textContent = waiting.some((seat) => seat.yours)
      ? "Pick your team in your seat."
      : `Waiting for ${waiting.map((seat) => seat.name || seat.label).join(" and ")} to pick a team.`;
    body.replaceChildren(h("span", { class: "coin-later" },
      h("img", { src: coin.faces.fortune, alt: "", class: "coin small" }),
      "then the coin"));
    return;
  }

  if (coin.owed) {
    ask.textContent = coin.may ? "Click the coin to flip it." : "Waiting for a coach to flip the coin.";
    body.replaceChildren(coinSides(coin, {
      allowed: coin.may, title: "Flip the coin", label: "Flip the coin",
    }));
    return;
  }

  /* The toss is in: the face it came up large, the other small and
     dim, and -- while the winner still owes it -- the goal to defend,
     on a miniature field whose two ends are the two answers. */
  const face = coin.face === "fortune" ? "Fortune" : "Doom";
  const other = coin.face === "fortune" ? "doom" : "fortune";
  const sides = table.sides;
  ask.replaceChildren(
    "The coin came up ", h("b", { class: "gold" }, face), ": ",
    h("b", {}, nameOf(coin.winner)), " won the toss.",
    sides.owed_by
      ? (sides.may ? " Click the goal you want to defend." : ` Waiting for ${nameOf(sides.owed_by)} to choose an end.`)
      : "");
  body.replaceChildren(h("div", { class: "toss" },
    h("div", { class: "coin-faces" },
      h("figure", { class: "coin-face" },
        h("img", { src: coin.faces[coin.face], alt: `The coin, ${face} side up`, class: "coin big" }),
        h("figcaption", { class: "gold" }, face.toUpperCase())),
      h("figure", { class: "coin-face dim" },
        h("img", { src: coin.faces[other], alt: "", class: "coin small" }),
        h("figcaption", {}, other.toUpperCase()))),
    sides.owed_by ? miniField(sides) : null));
}

/* The coin before the toss: both its faces side by side, Fortune and
   Doom, so a coach sees what it can come up (the author, 2026-09-27)
   -- the pair one button, lit gold while it may be flipped. */
function coinSides(coin, { allowed, title, label }) {
  const side = (face) => h("figure", { class: "coin-face" },
    h("img", { src: coin.faces[face], alt: "", class: "coin mid" }),
    h("figcaption", {}, face.toUpperCase()));
  return h("button", {
    type: "button",
    class: `coin-button coin-pair${allowed ? " lit" : ""}`,
    disabled: !allowed,
    title,
    "aria-label": label,
    onclick: () => roomMove("/table/flip_coin"),
  }, h("div", { class: "coin-faces" }, side("fortune"), side("doom")));
}

/* The miniature field: a goal at each end -- the goal the board draws
   there (`end`, off `webapp/board.py`) -- and the spaces between. A
   goal is the answer: pressing it defends it. */
function miniField(sides) {
  const end = (where) => {
    const choice = sides.choices.find((one) => one.end === where);
    const may = sides.may && choice.open;
    return h(may ? "button" : "div", {
      type: may ? "button" : null,
      class: `mini-goal${may ? " lit" : ""}`,
      title: may ? `Defend this goal: ${choice.label}` : choice.label,
      "aria-label": `Defend the ${where} goal: ${choice.label}`,
      onclick: may ? () => roomMove("/table/choose", { choice: choice.value }) : null,
    },
    h("span", { class: "mini-goal-word" }, "G",
      die("12", { size: 20, fill: "#0c141c", ink: may ? GOLD : "#6d6f78", font: 8 }), "AL"),
    h("span", { class: "mini-goal-side" }, choice.label));
  };
  const spaces = Array.from({ length: sides.board_size }, (_, index) =>
    h("span", { class: "mini-space" }, String(index + 1)));
  return h("div", { class: "mini-field" }, end("left"), spaces, end("right"));
}

/* The sideline: who is watching, Dinky waiting to be dragged into an
   empty seat, and the room's own neutral controls. A name dragged out
   of a seat is dropped here. */
function drawSideline(table, room) {
  const strip = el("sideline-strip");
  const seated = room.seats.some((one) => one.yours);
  const freeSeat = room.seats.some((one) => one.free);
  const people = room.watching.map((one) => {
    const mine = one.yours && freeSeat && !seated;
    return h("span", {
      class: `sideline-chip${mine ? " draggable" : ""}`,
      draggable: mine ? "true" : null,
      title: mine ? "Drag into an empty seat to sit" : null,
      ondragstart: mine ? (event) => seatDrag(event, "me") : null,
    }, h("span", { class: "presence" }), one.name, one.yours ? " (you)" : "");
  });
  const dinky = room.ai_seats.length
    ? h("span", {
      class: "sideline-chip dinky draggable",
      draggable: "true",
      role: "button",
      tabindex: "0",
      title: "Drag Dinky into an empty seat, or click",
      ondragstart: (event) => seatDrag(event, "dinky"),
      onclick: () => roomMove("/seat/ai", { seat: room.ai_seats[0] }),
      onkeydown: (event) => { if (event.key === "Enter") roomMove("/seat/ai", { seat: room.ai_seats[0] }); },
    }, h("span", { class: "tag-chip ai" }, "AI"), " Dinky")
    : null;
  strip.replaceChildren(...[
    h("span", { class: "field-label" },
      freeSeat ? "SIDELINE · drag a name into a seat" : "SIDELINE"),
    ...people,
    dinky,
    people.length || dinky ? null : h("span", { class: "quiet" }, "Nobody is watching."),
    h("span", { class: "grow" }),
    neutral("Copy the room's link", copyLink),
    room.admin ? neutral("Give up admin", dropAdmin) : neutral("Become admin", becomeAdmin),
    table.may_close
      ? neutral("Close this room", () => {
        /* Asked only when somebody else holds a seat (`close_asks`). */
        if (!table.close_asks || confirm("Close this room? Nothing has been played in it.")) roomMove("", {}, "DELETE");
      })
      : null,
  ].filter(Boolean));
  if (!strip.dataset.dropping) {
    strip.dataset.dropping = "1";
    seatDropTarget(strip, (what) => {
      const number = Number((what.match(/^seat:(\d)$/) || [])[1]);
      const seat = current && current.room.seats.find((one) => one.number === number);
      if (seat) seatOut(seat, current.room);
    });
  }
}

/* The rematch, followed: every page in the room when it is made goes
   to the new room, and a page opened on the finished game later is
   offered the link. */
function followRematch(state) {
  const note = el("rematch-note");
  if (!state.rematch) {
    sawNoRematch = true;
    note.hidden = true;
    return;
  }
  if (sawNoRematch) {
    location.href = state.rematch.url;
    return;
  }
  note.replaceChildren("This game has a rematch: ",
    h("a", { href: state.rematch.url }, "go to its room"), ".");
  note.hidden = false;
}

/* A refusal rides on the question it refused: a strip inside whichever
   box is asking -- the question box, or the table before kickoff --
   under its tag, and above the question box where neither is up. */
function showRefusal(text, law = null) {
  const strip = el("refusal");
  el("refusal-text").textContent = text;
  /* The Law it comes from, where the model named one: a link that
     opens it in the Rules tab. The page maps no sentence to a Law. */
  const cite = el("refusal-law");
  if (law) {
    cite.replaceChildren(
      "See ",
      h("a", {
        href: `/rules#${law.slug}`,
        class: "linkish",
        onclick: (event) => { event.preventDefault(); openRule(law.slug); },
      },
      `Law ${law.number || law.law_number || ""}`.trim(), " · ", h("span", { html: law.title })),
    );
    cite.hidden = false;
  } else {
    cite.replaceChildren();
    cite.hidden = true;
  }
  if (!el("prompt").hidden) {
    el("prompt-state").parentElement.after(strip);
  } else if (!el("table").hidden) {
    el("table-state").parentElement.after(strip);
  } else {
    el("prompt").before(strip);
  }
  strip.hidden = false;
}

// -- Cards and boards, big -------------------------------------------------

function cardUrl(cardId) {
  return `/api/game/${GAME_ID}/card/${encodeURIComponent(cardId)}.png?face=full`;
}

function openCard(cardId) {
  hidePeek();
  const body = el("viewer-body");
  body.className = "viewer-body";
  body.replaceChildren(h("img", { src: cardUrl(cardId), alt: "The card" }));
  el("viewer").showModal();
}

/* A board, big -- and, as the bot's "View full image" button does, the
   PNG the bot itself posts of the same position. */
function openBoard(layout, png) {
  hidePeek();
  const body = el("viewer-body");
  body.className = "viewer-body board";
  const box = h("div", { class: "board-fit", "data-max": "2" }, stage(layout, { live: false }));
  body.replaceChildren(
    h("div", {},
      box,
      png
        ? h("p", { class: "viewer-caption" },
          h("a", { href: png, target: "_blank", rel: "noopener" }, "View full image"))
        : null),
  );
  el("viewer").showModal();
  watchFit(box);
}

function openBoardOnPhone() {
  if (phone() && current && current.board.layout) {
    openBoard(current.board.layout, current.board.url);
  }
}

/* The player's card beside a meeple (or a bench card): shown while
   the pointer is on it, or after a press and hold on a touch screen.
   Clicking the card pins it where it is; clicking a pinned card opens
   it full size, as clicking the meeple does. Esc, or a click anywhere
   else, puts it away. The picture is the model's own, in the face the
   game's mode plays (`pictures.player_card_png`). */
const HOLD_MS = 450;
let peekHide = null;
let peekFor = null;
let heldOpen = false;

function hoverCard(node, url, { when = () => true } = {}) {
  node.addEventListener("mouseenter", () => {
    if (!finePointer() || el("peek").classList.contains("pinned") || !when()) return;
    showPeek(url, node);
  });
  node.addEventListener("mouseleave", () => {
    if (!el("peek").classList.contains("pinned")) hidePeekSoon();
  });
  let hold = null;
  let from = null;
  const cancel = () => { clearTimeout(hold); hold = null; };
  node.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch" || !when()) return;
    from = [event.clientX, event.clientY];
    cancel();
    hold = setTimeout(() => {
      hold = null;
      heldOpen = true;
      showPeek(url, node, { pinned: true });
    }, HOLD_MS);
  });
  node.addEventListener("pointermove", (event) => {
    if (hold && from && Math.hypot(event.clientX - from[0], event.clientY - from[1]) > 8) cancel();
  });
  node.addEventListener("pointerup", () => {
    cancel();
    /* A long press may or may not end in a click; either way the
       next tap is a tap. */
    if (heldOpen) setTimeout(() => { heldOpen = false; }, 400);
  });
  node.addEventListener("pointercancel", cancel);
  node.addEventListener("contextmenu", (event) => {
    if (heldOpen) event.preventDefault();
  });
  /* The click a hold ends in only opens the card; it is not a tap. */
  node.addEventListener("click", (event) => {
    if (!heldOpen) return;
    heldOpen = false;
    event.stopImmediatePropagation();
    event.preventDefault();
  }, true);
}

function showPeek(url, anchor, { pinned = false } = {}) {
  clearTimeout(peekHide);
  const peek = el("peek");
  const image = peek.firstElementChild;
  if (image.getAttribute("src") !== url) image.src = url;
  peekFor = url.includes("/card/")
    ? { url, cardId: decodeURIComponent(url.split("/card/")[1].split(".png")[0]) }
    : null;
  peek.classList.toggle("pinned", pinned);
  peek.hidden = false;
  placePeek(anchor);
}

/* Beside what it belongs to: to the right, or the left where the
   right has no room, and kept on the screen. */
function placePeek(anchor) {
  const peek = el("peek");
  const box = anchor.getBoundingClientRect();
  const width = Math.min(260, window.innerWidth - 16);
  const height = width * (364 / 260);
  let x = box.right + 12;
  if (x + width > window.innerWidth - 8) x = box.left - width - 12;
  x = Math.max(8, Math.min(x, window.innerWidth - width - 8));
  let y = box.top + box.height / 2 - height / 2;
  y = Math.max(8, Math.min(y, window.innerHeight - height - 8));
  peek.style.left = `${x}px`;
  peek.style.top = `${y}px`;
}

function hidePeekSoon() {
  clearTimeout(peekHide);
  peekHide = setTimeout(hidePeek, 160);
}

function hidePeek() {
  clearTimeout(peekHide);
  const peek = el("peek");
  peek.hidden = true;
  peek.classList.remove("pinned");
  peekFor = null;
}

el("peek").addEventListener("mouseenter", () => clearTimeout(peekHide));
el("peek").addEventListener("mouseleave", () => {
  if (!el("peek").classList.contains("pinned")) hidePeekSoon();
});
el("peek").addEventListener("click", (event) => {
  event.stopPropagation();
  const peek = el("peek");
  if (!peek.classList.contains("pinned")) {
    peek.classList.add("pinned");
    return;
  }
  if (peekFor) openCard(peekFor.cardId);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !el("peek").hidden) hidePeek();
});
document.addEventListener("pointerdown", (event) => {
  if (el("peek").hidden || event.target.closest("#peek")) return;
  if (el("peek").classList.contains("pinned")) hidePeek();
});

// -- Wiring ------------------------------------------------------------------

/* The owed step's control is the whistle. */
el("pick-up").replaceChildren(whistle({ allowed: true, label: "Pick it up", onclick: pickUp }));
/* The tutorial's note is answered by clicking anywhere on it. */
el("prompt").addEventListener("click", (event) => {
  if (!current || !current.prompt || event.target.closest("button, a, select, input")) return;
  const control = noteControl(current.prompt);
  if (control) press(control);
});
/* The keyboard: a number presses that control, Enter the only one,
   Esc puts back what is picked up, backs out of a chooser, or puts a
   refusal away. */
document.addEventListener("keydown", (event) => {
  if (event.target.closest("input, textarea, select, dialog[open]")) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (/^[1-9]$/.test(event.key)) {
    const control = keyed[Number(event.key) - 1];
    if (control) { event.preventDefault(); press(control); }
  } else if (event.key === "Enter" && fullOrder()
             && !event.target.closest("button, a, [role=button]")) {
    event.preventDefault();
    lockOrder(fullOrder());
  } else if (event.key === "Enter" && keyed.length === 1
             && !event.target.closest("button, a, [role=button]")) {
    event.preventDefault();
    press(keyed[0]);
  } else if (event.key === "Escape") {
    if (draftedAny()) {
      clearDrafts();
    } else if (picked) {
      pick(null);
    } else if (openChooser) {
      openChooser = null;
      if (current && current.prompt) drawControls(current.prompt);
    } else if (!el("refusal").hidden) {
      el("refusal").hidden = true;
    }
  }
});
el("abandon").addEventListener("click", () => {
  if (confirm("Are you sure? The game ends here with no result. The room, its board and its log are kept.")) {
    roomMove("/abandon");
  }
});
function becomeAdmin() {
  if (confirm("Take the admin role for this room?")) roomMove("/admin");
}
function dropAdmin() {
  if (confirm("Give up the admin role for this room?")) roomMove("/admin", {}, "DELETE");
}
function roomLink() {
  return `${location.origin}/room/${GAME_ID}`;
}
async function copyLink(event) {
  const link = roomLink();
  const button = event && event.currentTarget;
  try {
    await navigator.clipboard.writeText(link);
    if (button) button.textContent = button.dataset.copied || "Copied";
  } catch (error) {
    window.prompt("The room's link:", link);
  }
}
el("become-admin").addEventListener("click", becomeAdmin);
el("drop-admin").addEventListener("click", dropAdmin);
el("copy-link").addEventListener("click", copyLink);
el("take-free-seat").addEventListener("click", () => roomMove("/seat/take"));
el("dismiss").addEventListener("click", () => { el("refusal").hidden = true; });
el("viewer-close").addEventListener("click", () => el("viewer").close());
el("viewer").addEventListener("click", (event) => {
  if (event.target === el("viewer") || event.target === el("viewer-body")) el("viewer").close();
});
el("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = el("chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  say(text).then((ok) => {
    if (!ok && !input.value) input.value = text;
  });
});
/* Which tab is showing, and a dot on the others when something new
   arrives there: red for news, gold on Move when it is this coach's
   turn to answer. A phone switches the whole screen (`body[data-show]`,
   Move / Log / Chat / Teams / Rules); a wider screen switches the
   sidebar's four (`#sidebar[data-pane]`). */
function news(tab, kind = "news") {
  const marks = kind === "yours" ? ["yours", "news"] : ["news"];
  if (document.body.dataset.show !== tab) {
    const button = document.querySelector(`.tab[data-show="${tab}"]`);
    if (button) button.classList.add(...marks);
  }
  if (el("sidebar").dataset.pane !== tab) {
    const button = document.querySelector(`.side-tab[data-pane="${tab}"]`);
    if (button) button.classList.add(...marks);
  }
}

function showing(tab) {
  if (tab === "log") el("journal").scrollTop = el("journal").scrollHeight;
  if (tab === "chat") el("chat").scrollTop = el("chat").scrollHeight;
}

/* On its side the tabs' panes are under the field: the strip's ask
   brings the question's answers up, and a tab pressed brings up what
   it shows (Move, pressed while it is showing, the question). */
function toThePane(tab) {
  if (!phone() || upright()) return;
  const pane = tab === "move" ? el("move-pane") : document.querySelector(`.pane[data-tab="${tab}"]`);
  if (pane) pane.scrollIntoView({ behavior: "smooth", block: "start" });
}
el("strip-ask").addEventListener("click", () => toThePane("move"));

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    if (tab.dataset.show !== "move" || document.body.dataset.show === "move") {
      requestAnimationFrame(() => toThePane(tab.dataset.show));
    }
    document.body.dataset.show = tab.dataset.show;
    tab.classList.remove("news", "yours");
    if (["log", "chat", "teams", "rules"].includes(tab.dataset.show)) {
      el("sidebar").dataset.pane = tab.dataset.show;
      const side = document.querySelector(`.side-tab[data-pane="${tab.dataset.show}"]`);
      if (side) side.classList.remove("news", "yours");
    }
    showing(tab.dataset.show);
  });
}

function showPane(pane) {
  el("sidebar").dataset.pane = pane;
  for (const button of document.querySelectorAll(".side-tab")) {
    const on = button.dataset.pane === pane;
    button.setAttribute("aria-selected", on ? "true" : "false");
    if (on) button.classList.remove("news", "yours");
  }
  showing(pane);
}

for (const tab of document.querySelectorAll(".side-tab")) {
  tab.addEventListener("click", () => showPane(tab.dataset.pane));
}
showPane(el("sidebar").dataset.pane);

// -- The Teams tab -------------------------------------------------------------

let shownRosters = null;

/* Both rosters as tables, `board.py`'s rows as they come: the role and
   the name, the two skills the card prints, the exhaustion as one token
   a point, the condition, and the space or the bench. Hover a row for
   the card; click it (or Enter) to open it. */
function drawRosters(state) {
  const layout = state.board && state.board.layout;
  const rosters = layout && layout.rosters;
  const key = JSON.stringify(rosters || null);
  if (key === shownRosters) return;
  shownRosters = key;
  if (!rosters) {
    el("rosters").replaceChildren(h("p", { class: "quiet" }, "The teams are drawn here once the game kicks off."));
    return;
  }
  el("rosters").replaceChildren(...rosters.map((team) =>
    h("section", { class: "roster" },
      h("div", { class: "roster-head" },
        h("span", { class: "roster-team", style: `color: ${team.colour}` }, team.name),
        h("span", { class: "quiet" }, "exhaustion · condition · space")),
      h("table", { class: "roster-table" },
        h("thead", {},
          h("tr", {},
            h("th", {}, "Player"), h("th", {}, "OFF"), h("th", {}, "DEF"),
            h("th", {}, "Exhaustion"), h("th", {}, h("span", { class: "sr" }, "Condition")),
            h("th", {}, h("span", { class: "sr" }, "Where")))),
        h("tbody", {}, team.rows.map(rosterRow))))));
}

function rosterRow(row) {
  const marks = row.marks || {};
  const tokens = marks.exhaustion
    ? Array.from({ length: marks.exhaustion.count }, () =>
      h("img", { class: "token", src: `/emoji/${marks.exhaustion.emoji}.png`, alt: "" }))
    : [];
  const condition = marks.condition
    ? h("img", {
      class: "emoji",
      src: `/emoji/${marks.condition}.png`,
      alt: marks.condition,
      title: marks.condition[0].toUpperCase() + marks.condition.slice(1),
    })
    : null;
  const tr = h("tr", {
    class: row.where === "bench" || row.where === "back bench" ? "benched" : "",
    tabindex: "0",
    onclick: () => openCard(row.id),
    onkeydown: (event) => { if (event.key === "Enter") openCard(row.id); },
  },
  h("td", { class: "who" },
    h("span", { class: "role-dot", style: `background: ${row.colour}` }, row.role),
    row.name),
  h("td", { class: "num" }, String(row.offense)),
  h("td", { class: "num" }, String(row.defense)),
  h("td", {
    class: "tokens",
    title: marks.exhaustion
      ? `${marks.exhaustion.count} ${marks.exhaustion.emoji === "exhaust" ? "exhaustion" : "drain"}`
      : null,
  }, tokens),
  h("td", {}, condition),
  h("td", { class: "where" }, row.ball ? `${row.where} · ball` : row.where));
  hoverCard(tr, cardUrl(row.id));
  return tr;
}

// -- The Rules tab -------------------------------------------------------------

/* The Charter, the Learn to Play and the References
   (webapp/static/aids.js), with the room's hover card for a card. */
const rulesTab = window.D12Rules.mountTab(el("rules-tab"), {
  hover: (node, url) => hoverCard(node, url),
});

/* A refusal's Law, opened where the reader is: the Rules tab. */
function openRule(slug) {
  if (phone() || TABLET.matches) {
    document.body.dataset.show = "rules";
    const tab = document.querySelector('.tab[data-show="rules"]');
    if (tab) tab.classList.remove("news", "yours");
  }
  showPane("rules");
  rulesTab.open(slug);
}

/* Names are measured in the board's face, so measure again once it
   has loaded. */
document.fonts.ready.then(() => {
  for (const stageNode of document.querySelectorAll(".stage")) clampNames(stageNode);
});
whoAmI().then(poll);
