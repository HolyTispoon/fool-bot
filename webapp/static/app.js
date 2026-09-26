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
let openMenu = null;
/* A chooser opened by clicking its object on the board (a space two
   teammates share): its one question is asked in the box. */
let openChooser = null;
/* What the prompt put to this viewer lights on the board, by object
   (`readLit`). */
let lit = null;
let current = null;
const openBenches = new Set();

const el = (id) => document.getElementById(id);
const phone = () => window.matchMedia("(max-width: 960px)").matches;
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

/* Somebody the server does not know yet is asked for a name first. */
async function whoAmI() {
  try {
    const response = await fetch("/api/me");
    if (response.ok && (await response.json())) return;
  } catch (error) {
    /* Asked for below, and the poll retries the rest. */
  }
  const dialog = el("name-dialog");
  dialog.showModal();
  dialog.addEventListener("cancel", (event) => event.preventDefault());
  await new Promise((resolve) => {
    el("name-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const response = await fetch("/api/me", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: el("name-input").value }),
      });
      if (response.ok) {
        dialog.close();
        resolve();
      } else {
        el("name-error").textContent = await response.text();
        el("name-error").hidden = false;
      }
    });
  });
}

function cursors() {
  return `since=${latest}&chat_since=${chatLatest}`;
}

async function poll() {
  try {
    const response = await api(`?${cursors()}`);
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
  current = state;
  latest = state.latest;
  drawHeader(state);
  drawJumbotron(state);
  drawBoard(state);
  drawJournal(state);
  drawChat(state);
  drawPrompt(state);
  drawRoll(state);
  drawHeadline(state);
  drawReveal(state);
  drawFullTime(state);
  drawTable(state);
  drawRoom(state);
  drawStats(state);
  followRematch(state);
  if (state.refusal) showRefusal(state.refusal);
  el("owed").hidden = !(state.owed && state.you.is_coach);
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

function drawHeader(state) {
  el("channel").textContent = `pbw${state.game.number}`;
  el("topic").textContent = state.game.title;
  const you = el("you");
  you.replaceChildren();
  const mine = state.room.seats.find((seat) => seat.yours);
  if (state.you.is_coach && mine && !state.game.coaches.some((one) => one.player_number === mine.number && one.team)) {
    /* No team picked yet: the seat is what this reader holds. */
    you.append("You hold ", h("strong", {}, mine.label));
  } else if (state.you.is_coach) {
    const coach = state.game.coaches.find((one) => one.player_number === state.you.player_number);
    const side = coach && coach.side ? ` (${coach.side === "home" ? "Home" : "Visitors"})` : "";
    you.append(
      "You coach ",
      teamEmoji(coach && coach.team_key, coach && coach.team) || "",
      h("strong", {}, coach ? coach.team || coach.name : "a side"),
      side,
    );
  } else {
    you.append("You are watching");
  }
  if (state.you.coach) you.prepend(h("strong", {}, state.you.coach.name), " · ");
}

// -- The room -------------------------------------------------------------

/* The two seats as the server names them -- Coach 1 and Coach 2 until
   the coin, then Home and Visitors -- with what this reader may do to
   each. Whether a move stands is the record's; a refused one comes
   back with its sentence. */
function drawRoom(state) {
  const room = state.room;
  el("room").hidden = false;
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
          onclick: () => {
            if (confirm(`Are you sure? ${seat.name} will lose ${seat.label}.`)) {
              roomMove("/seat/kick", { seat: seat.number });
            }
          },
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
        coach ? [" · coached by ", h("b", {}, coach.name)] : "",
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

/* A side's time-out tile: held (outlined in the team's colour, a
   referee's T), spent (dashed grey, struck through), or -- only with
   the control in hand -- lit gold, and pressing it answers the turn. */
function timeOutTile(team, control) {
  const t = s(
    "svg",
    { class: "ref-t", viewBox: "0 0 24 24", width: 22, height: 22, "aria-hidden": "true" },
    s("rect", { x: "2", y: "3", width: "20", height: "5", rx: "2" }),
    s("rect", { x: "9.5", y: "3", width: "5", height: "19", rx: "2" }),
  );
  if (control) {
    return h(
      "button",
      {
        type: "button",
        class: "timeout-tile lit",
        style: `--team: ${team.colour}`,
        onclick: () => act(control.action),
      },
      t,
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
    t,
    h("span", { class: "tile-words" },
      h("span", { class: "tile-title" }, "TIME OUT"), h("small", {}, team.name)),
  );
}

// -- The board -----------------------------------------------------------

function drawBoard(state) {
  const layout = state.board.layout;
  el("no-board").hidden = Boolean(layout);
  lit = readLit(state.prompt);
  const shape = JSON.stringify([layout, lit.shape]);
  if (shape === shownBoard) return;
  shownBoard = shape;
  const box = el("board");
  box.replaceChildren();
  el("benches").replaceChildren();
  if (!layout) return;
  box.append(stage(layout, { live: true }));
  watchFit(box);
  el("benches").append(...layout.team_boards.map(bench));
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
  };
  if (!prompt) return index;
  const add = (map, key, control) => { (map[key] = map[key] || []).push(control); };
  for (const group of prompt.controls) {
    for (const control of group.controls) {
      if (!control.place || control.disabled) continue;
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
  return index;
}

/* Whether a meeple is on the field, where a lit piece is drawn; a
   player lit who is not is answered from the question box instead. */
function onField(layout, playerId) {
  return Boolean(layout) && layout.spaces.some((one) =>
    one.home.some((m) => m.id === playerId) || one.visiting.some((m) => m.id === playerId));
}

/* Pressing a control: its answer, or -- for a chooser -- its question
   opened in the box, or for the rematch the room's own route. */
function press(control) {
  if (!control || control.disabled) return;
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
function chips(controls, { buttons = controls.length > 1 } = {}) {
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
   `webapp/board.py`'s; the jumbotron has its own panel, and the
   benches open on demand. */
function stage(layout, { live }) {
  return h(
    "div",
    { class: "stage", onclick: live ? openBoardOnPhone : null },
    pitch(layout),
  );
}

function pitch(layout) {
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
    goal("home", layout.jumbotron.home.colour),
    layout.spaces.map((one) => space(one, layout)),
    goal("visiting", layout.jumbotron.visiting.colour),
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
function goal(side, colour) {
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
      die("12", { size: 56, fill: "#0c141c", ink: colour, font: 24 }),
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

function space(one, layout) {
  const loose = one.ball && !one[one.ball.side].length;
  const controls = (lit && lit.space[`${one.zone}:${one.index}`]) || [];
  const on = controls.length > 0;
  const marks = lit ? lit.player : {};
  return h(
    "div",
    {
      class: `space${one.tint ? " tinted" : ""}${on ? " lit" : ""}`,
      style: one.tint ? `--tint: ${one.tint}` : null,
      title: on ? controls.map((c) => c.label).join(" · ") : null,
      /* A lit space is answered by clicking anywhere on it that is not
         a piece of its own (a meeple opens its card). */
      onclick: on ? (event) => { event.stopPropagation(); press(controls[0]); } : null,
    },
    h("span", { class: "space-code" }, one.code),
    one.kickoff ? h("span", { class: "kickoff-ring" }) : null,
    h("div", { class: "lane visiting" }, fanOf(one, "visiting", layout, marks)),
    h("div", { class: "lane home" }, fanOf(one, "home", layout, marks)),
    loose ? h("span", { class: "loose-ball" }, ball(one.ball.speed, 36, { lit: true })) : null,
    on ? h("span", { class: "space-chips" }, chips(controls)) : null,
  );
}

/* One team's meeples on a space, overlapped where `board.py` placed
   them, back to front, with each name on its own line under the fan
   (the front piece's first) and every badge and the ball drawn over
   the whole of it. `marks` is what a prompt lights: a piece's id to
   the chip saying what clicking it means. */
function fanOf(one, side, layout, marks = {}) {
  const drawn = one.fans[side];
  if (!drawn.pieces.length) return null;
  const g = layout.meeple;
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
        meeple(piece, layout, { controls: marks[piece.id] }),
      ),
    );
    if (piece.exhaustion) {
      over.push(h(
        "span",
        {
          class: "badge tokens",
          style: `left: ${piece.x + W * 0.62}px; top: ${piece.y + H * 0.68}px`,
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
          style: `left: ${piece.x - 8}px; top: ${piece.y + H - 14}px`,
          title: piece.condition[0].toUpperCase() + piece.condition.slice(1),
        },
        h("img", { src: `/emoji/${piece.condition}.png`, alt: piece.condition }),
      ));
    }
    if (one.ball && one.ball.holder === piece.id) {
      /* Off the top right of a home holder, almost touching the
         shoulder; off the bottom left of a visiting one, over the edge
         by the foot. */
      const place = side === "home"
        ? `left: ${piece.x + W * 0.66}px; top: ${piece.y - 22}px`
        : `left: ${piece.x - 18}px; top: ${piece.y + H - 30}px`;
      over.push(h("span", { class: "held-ball", style: place }, ball(one.ball.speed, 30, { lit: true })));
    }
  });
  /* Names front first, each centred under its own piece. */
  let line = tall + 4;
  const byId = Object.fromEntries(drawn.pieces.map((p) => [p.id, p]));
  for (const id of drawn.names) {
    const piece = byId[id];
    const lit = id in marks;
    over.push(h(
      "span",
      { class: `fan-name${lit ? " lit" : ""}`, style: `left: ${piece.x + W / 2}px; top: ${line}px` },
      piece.name,
    ));
    line += 16;
    if (lit) {
      over.push(h(
        "span",
        { class: "fan-chip-line", style: `left: ${piece.x + W / 2}px; top: ${line}px` },
        chips(marks[id]),
      ));
      line += 18;
    }
  }
  box.append(...over);
  box.style.height = `${line}px`;
  return box;
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
function meeple(m, layout, { controls = null } = {}) {
  const lit = Boolean(controls && controls.length);
  const g = layout.meeple;
  const [left, top, width, height] = g.box;
  const W = g.width;
  const H = (W * height) / width;
  const icon = layout.species_icons && m.species;
  const center = icon ? g.role_center : g.solo_center;
  const node = h(
    "button",
    {
      type: "button",
      class: `meeple${lit ? " lit" : ""}`,
      style: `width: ${W}px; height: ${H}px; color: ${m.ink}`,
      title: lit ? `${m.name} [${m.role}]: ${controls[0].chip || controls[0].label}` : `${m.name} [${m.role}]`,
      "aria-label": lit ? controls[0].label : `${m.name} [${m.role}]`,
      onclick: (event) => {
        event.stopPropagation();
        if (lit) press(controls[0]);
        else openCard(m.id);
      },
    },
    s(
      "svg",
      { viewBox: `${left} ${top} ${width} ${height}`, "aria-hidden": "true" },
      s("path", {
        d: g.path,
        fill: m.colour,
        stroke: lit ? GOLD : m.ink,
        "stroke-width": String(lit ? g.stroke * 1.5 : g.stroke),
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
  );
  hoverCard(node, cardUrl(m.id));
  return node;
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

/* A card as the bot's board draws it -- `render.draw_card`, the team's
   frame and the card's marks included, so the marks sit where the
   bot puts them. */
function playerCard(card) {
  const marks = [];
  if (card.exhaustion > 0) marks.push(`${card.exhaustion} ${card.cyborg ? "drain" : "exhaustion"}`);
  if (card.injured) marks.push(card.cyborg ? "damaged" : "injured");
  else if (card.exhausted) marks.push(card.cyborg ? "drained" : "exhausted");
  const said = `${card.name} [${card.role}], offense ${card.offense}, defense ${card.defense}`
    + (marks.length ? `, ${marks.join(", ")}` : "");
  const node = h(
    "button",
    {
      type: "button",
      class: "card",
      title: `${card.name} [${card.role}]`,
      onclick: (event) => { event.stopPropagation(); openCard(card.id); },
    },
    h("img", { src: card.image, alt: said }),
  );
  hoverCard(node, cardUrl(card.id));
  return node;
}

/* A team's bench and back bench, behind a button under the board:
   shown while the pointer is on it, and kept open by a click. Lit gold
   where a prompt names it -- the Coaching Offer -- and then a click
   answers it; the cards still show while the pointer is on it. */
function bench(board) {
  const count = board.bench.length + board.back_bench.length;
  const controls = (lit && lit.bench[board.side]) || [];
  const on = controls.length > 0;
  const toggle = h(
    "div",
    {
      class: `bench-toggle${openBenches.has(board.side) ? " open" : ""}${on ? " lit" : ""}`,
      style: `--team: ${board.colour}`,
    },
    h(
      "button",
      {
        type: "button",
        class: "bench-button",
        "aria-expanded": openBenches.has(board.side) ? "true" : "false",
        title: on ? controls[0].label : null,
        onclick: (event) => {
          event.stopPropagation();
          if (on) {
            press(controls[0]);
            return;
          }
          const open = toggle.classList.toggle("open");
          event.currentTarget.setAttribute("aria-expanded", String(open));
          if (open) openBenches.add(board.side);
          else openBenches.delete(board.side);
        },
      },
      teamEmoji(board.key, board.name),
      `${board.name} bench`,
      h("span", { class: "count" }, `(${count})`),
      on ? chips(controls, { buttons: false }) : null,
    ),
    h(
      "div",
      { class: "bench-pop" },
      h("div", { class: "bench-pop-name" }, board.name),
      h(
        "div",
        { class: "bench-pop-rows" },
        h("span", { class: "bench-label" }, "BENCH"),
        h(
          "div",
          { class: "bench" },
          board.bench.length
            ? board.bench.map((card) => playerCard(card))
            : h("span", { class: "bench-empty" }, "Empty"),
        ),
        h("span", { class: "bench-label" }, "BACK BENCH"),
        h(
          "div",
          { class: "bench" },
          board.back_bench.length
            ? board.back_bench.map((card) => playerCard(card))
            : h("span", { class: "bench-empty" }, "Empty"),
        ),
      ),
    ),
  );
  return toggle;
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
  const scale = Math.min(max, box.clientWidth / STAGE_WIDTH);
  const height = Math.ceil(inner.offsetHeight * scale);
  /* A ResizeObserver hears its own height change; answering that with
     the same numbers is what keeps it from looping. */
  const last = fitted.get(box);
  if (last && last.inner === inner && last.scale === scale && last.height === height) return;
  fitted.set(box, { inner, scale, height });
  inner.style.transform = `scale(${scale})`;
  box.style.height = `${height}px`;
}

// -- The game log -------------------------------------------------------------

function drawJournal(state) {
  if (!state.entries.length) return;
  news("log");
  const journal = el("journal");
  const empty = el("journal-empty");
  if (empty) empty.remove();
  const nearBottom = journal.scrollHeight - journal.scrollTop - journal.clientHeight < 80;
  for (const entry of state.entries) {
    const block = h("div", { class: entry.new_play ? "entry new-play" : "entry" });
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

// -- The divider between the log and the chat ---------------------------------

/* The share of the column the log takes, the chat the rest. Remembered
   in this browser only; a page with none stored, or with storage
   refused, opens at the default. */
const SPLIT_KEY = "d12ball.split";
const SPLIT_DEFAULT = 1.3 / 2.3;
const SPLIT_MIN_PX = 80;
let splitShare = SPLIT_DEFAULT;

function applySplit(share) {
  /* A panel read to its newest line stays on it as it is resized. */
  const pinned = ["journal", "chat"]
    .map(el)
    .filter((box) => box.scrollHeight - box.scrollTop - box.clientHeight < 8);
  splitShare = share;
  el("split").parentElement.style.gridTemplateRows =
    `minmax(0, ${share}fr) auto minmax(0, ${1 - share}fr)`;
  el("split").setAttribute("aria-valuenow", String(Math.round(share * 100)));
  for (const box of pinned) box.scrollTop = box.scrollHeight;
}

function keepSplit() {
  try {
    localStorage.setItem(SPLIT_KEY, String(splitShare));
  } catch (error) {
    /* Storage refused: the divider still moves, it is only forgotten. */
  }
}

/* The share a divider at `y` would give, kept so neither panel goes
   below SPLIT_MIN_PX. */
function shareAt(y) {
  const split = el("split");
  const top = split.previousElementSibling.getBoundingClientRect().top;
  const bottom = split.nextElementSibling.getBoundingClientRect().bottom;
  const room = bottom - top - split.offsetHeight;
  if (room <= 2 * SPLIT_MIN_PX) return splitShare;
  const log = Math.min(room - SPLIT_MIN_PX, Math.max(SPLIT_MIN_PX, y - top - split.offsetHeight / 2));
  return log / room;
}

(function setUpSplit() {
  const split = el("split");
  split.setAttribute("aria-valuemin", "0");
  split.setAttribute("aria-valuemax", "100");
  let stored = NaN;
  try {
    stored = Number(localStorage.getItem(SPLIT_KEY));
  } catch (error) {
    /* Nothing stored that can be read: the default. */
  }
  applySplit(stored > 0 && stored < 1 ? stored : SPLIT_DEFAULT);

  split.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    split.setPointerCapture(event.pointerId);
    split.classList.add("dragging");
  });
  split.addEventListener("pointermove", (event) => {
    if (split.hasPointerCapture(event.pointerId)) applySplit(shareAt(event.clientY));
  });
  const release = (event) => {
    if (!split.hasPointerCapture(event.pointerId)) return;
    split.releasePointerCapture(event.pointerId);
    split.classList.remove("dragging");
    keepSplit();
  };
  split.addEventListener("pointerup", release);
  split.addEventListener("pointercancel", release);
  split.addEventListener("dblclick", () => {
    applySplit(SPLIT_DEFAULT);
    keepSplit();
  });
  split.addEventListener("keydown", (event) => {
    const step = { ArrowUp: -0.05, ArrowDown: 0.05 }[event.key];
    if (step === undefined) return;
    event.preventDefault();
    const box = split.getBoundingClientRect();
    const middle = box.top + box.height / 2;
    const room = split.nextElementSibling.getBoundingClientRect().bottom
      - split.previousElementSibling.getBoundingClientRect().top;
    applySplit(shareAt(middle + step * room));
    keepSplit();
  });
})();

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

function drawPrompt(state) {
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
  const previous = shownPrompt ? JSON.parse(shownPrompt) : null;
  shownPrompt = shape;
  if (!previous || !state.prompt || previous.kind !== state.prompt.kind) openMenu = null;
  openChooser = null;
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
  el("prompt-state").textContent = BOX_STATES[state.prompt.state] || "";
  el("ask").innerHTML = state.prompt.ask;
  drawPicture(state.prompt);
  drawReference(state.prompt);
  drawControls(state.prompt);
}

/* The question box's four tags, by the state the server read. */
const BOX_STATES = {
  yours: "Your move",
  waiting: "Waiting on the other side",
  now: "Now",
  full_time: "Full time",
};

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

/* The maneuver pick's link to the hexagon, at the tier the server
   named (`maneuver_reference_tier`): never a picture inline, since the
   question box already carries the challenge over the hand. */
function drawReference(prompt) {
  const link = el("reference-link");
  el("reference").hidden = !prompt.reference;
  if (prompt.reference) link.href = prompt.reference;
  else link.removeAttribute("href");
}

/* The objects the question box draws, rather than the board: the die
   to roll, the faces of a speed to choose, the whistle, the note, the
   REMATCH mark, the hand's cards. */
const BOX_OBJECTS = new Set(["die", "face", "whistle", "note", "rematch", "card"]);

/* Whether a control is drawn in the question box: the neutral ones, the
   box's own objects, and a meeple lit that is not on the field to be
   clicked (a bench, say), which is answered from here instead. */
function inBox(control) {
  const place = control.place;
  if (!place) return true;
  if (BOX_OBJECTS.has(place.at)) return true;
  if (place.at === "player") {
    return !onField(current && current.board.layout, place.id);
  }
  if (place.at === "time_out_tile" || place.at === "out_of_play" || place.at === "bench") return false;
  /* A space, a goal or the ball are always drawn while there is a
     board; a disabled one is dark there and said in the lit line. */
  return !(current && current.board.layout);
}

function drawControls(prompt) {
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

  const groups = prompt.controls
    .map((group) => ({ ...group, controls: group.controls.filter(inBox) }))
    .filter((group) => group.controls.length);
  const menus = groups.filter((group) => group.label);

  /* Several named groups is the Coaching Choice: a neutral control per
     menu, and the menu opened in its place with a way back, as the
     Discord hub walks a coach through them. */
  if (menus.length >= 3) {
    const open = menus.find((group) => group.label === openMenu);
    if (open) {
      controls.append(
        h("div", { class: "group-label" }, open.label),
        drawGroup(open),
        h("div", { class: "row" }, neutral("Back", () => { openMenu = null; drawControls(prompt); })),
      );
      return;
    }
    const row = h("div", { class: "row" });
    for (const group of menus) {
      row.append(neutral(group.label, () => { openMenu = group.label; drawControls(prompt); }));
    }
    controls.append(row);
    for (const group of groups.filter((one) => !one.label)) controls.append(drawGroup(group));
    appendNotes(controls, groups);
    return;
  }

  for (const group of groups) {
    if (group.label) controls.append(h("div", { class: "group-label" }, group.label));
    controls.append(drawGroup(group));
  }
  appendNotes(controls, groups);
  const table = handTable(prompt);
  if (table) controls.append(table);
}

/* What is lit on the board and why, and -- muted -- what is dark:
   the server's reading of the controls it built (`present.lit_line`). */
function drawLitLine(prompt) {
  const line = el("lit");
  const items = prompt.lit || [];
  line.hidden = !items.length;
  line.replaceChildren(...items.map((item) =>
    h("span", { class: item.dark ? "lit-item dark" : "lit-item" }, item.text)));
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

/* The hands this viewer does not hold, face down (`present.hand_table`)
   -- whether or not they have been picked, so a back says nothing. The
   card this coach laid down is in their own hand, ringed. */
function handTable(prompt) {
  const table = prompt.hand;
  if (!table) return null;
  return h(
    "div",
    { class: "hand-table" },
    h("div", { class: "hand" }, table.backs.map((back) => h(
      "figure",
      { class: "table-card" },
      h("img", { src: `/api/game/${GAME_ID}/maneuver-back.png`, alt: `${back.team}'s card, face down` }),
      h("figcaption", {}, `${back.team} · face down`),
    ))),
    h("p", { class: "note-line" }, table.note),
  );
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

/* Before kickoff, in the prompt's place: the settings, both seats and
   their teams, the coin, home or visiting, and Start. Everything on it
   is `state.table` -- which setting is open, which team a seat may
   pick, who owes the toss and the choice are the game record's
   answers, and a press the record refuses comes back with its
   sentence. An observer is sent the same table with every control
   off. */
function drawTable(state) {
  const box = el("table");
  const table = state.table;
  const shape = JSON.stringify(table);
  if (shape === shownTable) return;
  shownTable = shape;
  if (!table) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const picking = table.seats.some((seat) => seat.teams.some((team) => team.open));
  const yours = table.start.may || table.coin.may || table.sides.may || picking;
  box.classList.toggle("yours", yours);
  if (yours) news("move", "yours");
  el("table-state").textContent = yours ? "Your move" : table.lobby ? "The lobby" : "Setting up";

  const body = el("table-body");
  body.replaceChildren(
    h("div", { class: "group-label" }, "Settings"),
    h("div", { class: "table-settings" }, table.settings.map(drawSetting)),
  );
  for (const seat of table.seats) {
    body.append(h("div", { class: "group-label" },
      `${seat.label}: `,
      seat.name || "Empty",
      seat.team ? " · " : "",
      seat.team ? teamEmoji(seat.team_key, seat.team) : null,
      seat.team ? ` ${seat.team}` : ""));
    if (seat.teams.length) body.append(drawTeams(seat));
  }

  const coin = table.coin;
  if (coin.flipped) {
    const winner = table.seats.find((seat) => seat.number === coin.winner);
    body.append(h("p", { class: "note-line" },
      `The coin came up ${coin.face === "fortune" ? "Fortune" : "Doom"}: `,
      h("strong", {}, winner ? winner.name || winner.label : "nobody"),
      " won the toss."));
  }
  const row = h("div", { class: "row" });
  if (coin.owed) {
    row.append(tableButton("Flip the coin", !coin.may, "/table/flip_coin"));
  }
  if (table.sides.owed_by) {
    for (const choice of table.sides.choices) {
      row.append(tableButton(choice.label, !(table.sides.may && choice.open),
        "/table/choose", { choice: choice.value }));
    }
  }
  if (table.may_close) {
    row.append(h("button", {
      type: "button",
      class: "btn",
      onclick: () => {
        if (confirm("Close this room? Nothing has been played in it.")) roomMove("", {}, "DELETE");
      },
    }, "Close this room"));
  }
  if (row.childElementCount) body.append(row);
  /* Start is the whistle: grey, with the record's own sentence under
     it, while `start_lobby` would refuse. */
  if (table.start.owed) {
    body.append(whistle({
      allowed: table.start.may && !table.start.refusal,
      label: "Start the game",
      note: table.start.refusal || "",
      onclick: () => roomMove("/table/start"),
    }));
  }
}

function tableButton(label, disabled, path, body) {
  return h("button", {
    type: "button",
    class: "btn",
    disabled,
    onclick: () => roomMove(path, body),
  }, label);
}

/* One setting: a row of its values as the Discord settings block draws
   them (the current one grey), a toggle, or the room's name. */
function drawSetting(setting) {
  const off = !setting.may_change;
  const configure = (value) => roomMove("/table/configure", { setting: setting.name, value });
  let control;
  if (setting.choices.length) {
    control = h("div", { class: "row" }, setting.choices.map((choice) => h("button", {
      type: "button",
      class: `btn${choice.value === setting.value ? " current" : ""}`,
      disabled: off || choice.value === setting.value,
      onclick: () => configure(choice.value),
    }, choice.label)));
  } else if (typeof setting.value === "boolean") {
    control = h("button", {
      type: "button",
      class: `btn${setting.value ? " current" : ""}`,
      disabled: off,
      onclick: () => configure(null),
    }, setting.value ? "On" : "Off");
  } else {
    const input = h("input", {
      class: "chat-input",
      maxlength: "80",
      value: setting.value,
      disabled: off,
      "aria-label": setting.label,
    });
    control = h("form", {
      class: "row",
      onsubmit: (event) => { event.preventDefault(); configure(input.value); },
    }, input, h("button", { type: "submit", class: "btn", disabled: off }, "Rename"));
  }
  return h("div", { class: "table-setting" },
    h("span", { class: "seat-label" }, setting.label), control);
}

/* A seat's picker: the colour teams and the species teams, a row each,
   every team the record does not offer greyed. */
function drawTeams(seat) {
  const rows = [0, 1].map((row) => h("div", { class: "row" },
    seat.teams.filter((team) => team.row === row).map((team) => h("button", {
      type: "button",
      class: "btn",
      disabled: !team.open,
      onclick: () => roomMove("/table/pick_team", { team: team.key, seat: seat.number }),
    }, teamEmoji(team.key, team.name), ` ${team.name}`))));
  return h("div", { class: "table-teams" }, rows);
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
function showRefusal(text) {
  const strip = el("refusal");
  el("refusal-text").textContent = text;
  if (!el("prompt").hidden) {
    el("prompt-state").parentElement.after(strip);
    strip.removeAttribute("data-tab");
  } else if (!el("table").hidden) {
    el("table-state").after(strip);
    strip.removeAttribute("data-tab");
  } else {
    el("prompt").before(strip);
    strip.dataset.tab = "move";
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

function hoverCard(node, url) {
  node.addEventListener("mouseenter", () => {
    if (!finePointer() || el("peek").classList.contains("pinned")) return;
    showPeek(url, node);
  });
  node.addEventListener("mouseleave", () => {
    if (!el("peek").classList.contains("pinned")) hidePeekSoon();
  });
  let hold = null;
  let from = null;
  const cancel = () => { clearTimeout(hold); hold = null; };
  node.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch") return;
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
   Esc backs out of a menu or a chooser, or puts a refusal away. */
document.addEventListener("keydown", (event) => {
  if (event.target.closest("input, textarea, select, dialog[open]")) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (/^[1-9]$/.test(event.key)) {
    const control = keyed[Number(event.key) - 1];
    if (control) { event.preventDefault(); press(control); }
  } else if (event.key === "Enter" && keyed.length === 1
             && !event.target.closest("button, a, [role=button]")) {
    event.preventDefault();
    press(keyed[0]);
  } else if (event.key === "Escape") {
    if (openChooser || openMenu) {
      openChooser = null;
      openMenu = null;
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
el("become-admin").addEventListener("click", () => {
  if (confirm("Take the admin role for this room?")) roomMove("/admin");
});
el("drop-admin").addEventListener("click", () => {
  if (confirm("Give up the admin role for this room?")) roomMove("/admin", {}, "DELETE");
});
el("copy-link").addEventListener("click", async () => {
  const link = `${location.origin}/room/${GAME_ID}`;
  try {
    await navigator.clipboard.writeText(link);
    el("copy-link").textContent = "Copied";
  } catch (error) {
    window.prompt("The room's link:", link);
  }
});
el("dismiss").addEventListener("click", () => { el("refusal").hidden = true; });
/* The reading room: what this game plays, as the state names it. */
el("open-aids").addEventListener("click", () => {
  if (current) window.D12Aids.open(current.aids);
});
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
/* A bench kept open by a click closes on a click anywhere else. */
document.addEventListener("click", (event) => {
  if (event.target.closest(".bench-toggle")) return;
  for (const open of document.querySelectorAll(".bench-toggle.open")) {
    open.classList.remove("open");
    open.firstElementChild.setAttribute("aria-expanded", "false");
  }
  openBenches.clear();
});
/* On a phone, which tab is showing, and a mark on the others when
   something new arrives there -- gold on Move when it is this coach's
   turn to answer. */
function news(tab, kind = "news") {
  if (document.body.dataset.show === tab) return;
  const button = document.querySelector(`.tab[data-show="${tab}"]`);
  if (button) button.classList.add(kind === "yours" ? "yours" : "news", "news");
}

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    document.body.dataset.show = tab.dataset.show;
    tab.classList.remove("news", "yours");
    if (tab.dataset.show === "log") el("journal").scrollTop = el("journal").scrollHeight;
    if (tab.dataset.show === "chat") el("chat").scrollTop = el("chat").scrollHeight;
  });
}

/* Names are measured in the board's face, so measure again once it
   has loaded. */
document.fonts.ready.then(() => {
  for (const stageNode of document.querySelectorAll(".stage")) clampNames(stageNode);
});
whoAmI().then(poll);
