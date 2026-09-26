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
let shownTable = null;
/* Whether this page has seen its game with no rematch yet: a page that
   was open when the rematch was made follows it there, and one opened
   on the finished game afterwards is offered the link instead. */
let sawNoRematch = false;
let shownBoard = null;
let openMenu = null;
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
          type: "button", class: "btn secondary",
          onclick: () => roomMove("/seat/leave"),
        }, "Leave"));
      } else if (seat.free && !seated) {
        buttons.push(h("button", {
          type: "button", class: "btn primary",
          onclick: () => roomMove("/seat/take", { seat: seat.number }),
        }, "Take"));
      } else if (seat.free && seated) {
        /* Anybody seated may hand the other side to the AI. */
        buttons.push(h("button", {
          type: "button", class: "btn secondary",
          onclick: () => roomMove("/seat/ai", { seat: seat.number }),
        }, "Put Dinky in"));
      }
      if (room.admin && seat.name && !seat.yours) {
        buttons.push(h("button", {
          type: "button", class: "btn danger",
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

// -- The jumbotron -------------------------------------------------------

/* The board's jumbotron, in its own place: both teams, the score, the
   clock and the half, with the coach behind each team under it. */
function drawJumbotron(state) {
  const layout = state.board.layout;
  const coachOn = (side) => state.game.coaches.find((one) => one.side === side);
  const side = (where) => {
    const team = layout ? layout.jumbotron[where] : null;
    const coach = coachOn(where);
    return h(
      "div",
      { class: `jumbo-side ${where}` },
      h("div", { class: "jumbo-where" }, where === "home" ? "Home" : "Visitors"),
      h(
        "div",
        { class: "jumbo-team", style: team ? `color: ${team.colour}` : null },
        team ? team.name : coach && coach.team ? coach.team : "--",
      ),
      h("div", { class: "jumbo-coach" }, coach ? coach.name : ""),
    );
  };
  const j = layout ? layout.jumbotron : null;
  el("jumbotron").replaceChildren(
    h(
      "div",
      { class: "jumbo-top" },
      h("span", { class: "jumbo-brand" }, "D12 BALL!"),
      h(
        "span",
        { class: "jumbo-clock" },
        h("span", { class: "jumbo-minute" }, j ? j.minute : "--"),
        h("span", { class: "jumbo-period" }, j ? j.period : ""),
      ),
    ),
    h(
      "div",
      { class: "jumbo-score" },
      side("home"),
      h("div", { class: "jumbo-goals" }, j ? `${j.score.home} : ${j.score.visiting}` : "- : -"),
      side("visiting"),
    ),
  );
}

// -- The board -----------------------------------------------------------

function drawBoard(state) {
  const layout = state.board.layout;
  el("no-board").hidden = Boolean(layout);
  const shape = JSON.stringify(layout);
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
   lit when a prompt names it (`lit`). */
function goal(side, colour, { lit = false } = {}) {
  return h(
    "div",
    {
      class: `goal ${side}${lit ? " lit" : ""}`,
      style: `--team: ${colour}`,
      role: "img",
      "aria-label": `The ${side === "home" ? "home" : "visitors'"} goal`,
    },
    h(
      "span",
      { class: "goal-word" },
      h("span", {}, "G"),
      die("12", { size: 56, fill: "#0c141c", ink: colour, font: 24 }),
      h("span", {}, "A"),
      h("span", {}, "L"),
    ),
  );
}

function space(one, layout) {
  const loose = one.ball && !one[one.ball.side].length;
  return h(
    "div",
    {
      class: one.tint ? "space tinted" : "space",
      style: one.tint ? `--tint: ${one.tint}` : null,
    },
    h("span", { class: "space-code" }, one.code),
    one.kickoff ? h("span", { class: "kickoff-ring" }) : null,
    h("div", { class: "lane visiting" }, fanOf(one, "visiting", layout)),
    h("div", { class: "lane home" }, fanOf(one, "home", layout)),
    loose ? h("span", { class: "loose-ball" }, ball(one.ball.speed, 36)) : null,
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
        meeple(piece, layout, { lit }),
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
      over.push(h("span", { class: "held-ball", style: place }, ball(one.ball.speed, 30)));
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
    if (lit && marks[id]) {
      over.push(h(
        "span",
        { class: "fan-chip-line", style: `left: ${piece.x + W / 2}px; top: ${line}px` },
        chip(marks[id]),
      ));
      line += 18;
    }
  }
  box.append(...over);
  box.style.height = `${line}px`;
  return box;
}

/* What clicking a lit piece means, with any cost as the token image
   and a count -- never the word "token". */
function chip(mark) {
  return h(
    "span",
    { class: "chip" },
    mark.label,
    mark.cost
      ? h("span", { class: "chip-cost" },
        h("img", { src: `/emoji/${mark.cost.emoji}.png`, alt: "" }),
        `×${mark.cost.count}`)
      : null,
  );
}

function meeple(m, layout, { lit = false } = {}) {
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
      title: `${m.name} [${m.role}]`,
      "aria-label": `${m.name} [${m.role}]`,
      onclick: (event) => { event.stopPropagation(); openCard(m.id); },
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

/* The ball: the d12 showing its speed, on a dark ring. */
function ball(speed, size) {
  return die(String(speed), {
    size, fill: "#ffffff", ink: "#243347", font: size * 0.44, ring: true,
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
   shown while the pointer is on it, and kept open by a click. */
function bench(board) {
  const count = board.bench.length + board.back_bench.length;
  const toggle = h(
    "div",
    {
      class: `bench-toggle${openBenches.has(board.side) ? " open" : ""}`,
      style: `--team: ${board.colour}`,
    },
    h(
      "button",
      {
        type: "button",
        class: "bench-button",
        "aria-expanded": openBenches.has(board.side) ? "true" : "false",
        onclick: (event) => {
          event.stopPropagation();
          const open = toggle.classList.toggle("open");
          event.currentTarget.setAttribute("aria-expanded", String(open));
          if (open) openBenches.add(board.side);
          else openBenches.delete(board.side);
        },
      },
      teamEmoji(board.key, board.name),
      `${board.name} bench`,
      h("span", { class: "count" }, `(${count})`),
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
    `auto minmax(0, ${share}fr) auto minmax(0, ${1 - share}fr)`;
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
  if (shape === shownPrompt) return;
  const previous = shownPrompt ? JSON.parse(shownPrompt) : null;
  shownPrompt = shape;
  if (!previous || !state.prompt || previous.kind !== state.prompt.kind) openMenu = null;
  if (!state.prompt) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const yours = state.prompt.yours;
  box.classList.toggle("yours", yours);
  if (yours) news("move", "yours");
  el("prompt-state").textContent = yours
    ? "Your move"
    : state.you.is_coach ? "Waiting on the other side" : "Now";
  el("ask").innerHTML = state.prompt.ask;
  drawPicture(state.prompt);
  drawReference(state.prompt);
  drawControls(state.prompt);
}

/* The dice just rolled, at the top of the question box: on Discord the
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
    return;
  }
  if (image.getAttribute("src") !== state.roll.url) image.src = state.roll.url;
  image.hidden = false;
}

/* The picture the prompt is asked over, where the cog posts one with
   the same question -- the shot, or the challenge over the maneuver
   pick -- or none. Its URL changes when the position or the question does,
   so an unchanged one is left alone rather than reloaded. */
function drawPicture(prompt) {
  const image = el("prompt-picture");
  if (!prompt.picture) {
    image.hidden = true;
    image.removeAttribute("src");
    return;
  }
  if (image.getAttribute("src") !== prompt.picture) image.src = prompt.picture;
  image.alt = prompt.kind === "score_attempt" ? "The shot" : "The challenge";
  image.hidden = false;
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

function drawControls(prompt) {
  const controls = el("controls");
  controls.replaceChildren();
  const groups = prompt.controls;
  const menus = groups.filter((group) => group.label);

  /* Several named groups is the Coaching Choice: a button per menu,
     and the menu opened in its place with a way back, as the Discord
     hub walks a coach through them. */
  if (menus.length >= 3) {
    const open = menus.find((group) => group.label === openMenu);
    if (open) {
      controls.append(
        h("div", { class: "group-label" }, open.label),
        drawGroup(open),
        h("div", { class: "row" },
          h("button", {
            type: "button",
            class: "btn secondary",
            onclick: () => { openMenu = null; drawControls(prompt); },
          }, "Back")),
      );
      return;
    }
    const row = h("div", { class: "row" });
    for (const group of menus) {
      row.append(h("button", {
        type: "button",
        class: "btn primary",
        onclick: () => { openMenu = group.label; drawControls(prompt); },
      }, group.label));
    }
    for (const group of groups.filter((one) => !one.label)) {
      for (const control of group.controls) row.append(drawControl(control));
    }
    controls.append(row);
    appendNotes(controls, groups);
    return;
  }

  for (const group of groups) {
    if (group.label) controls.append(h("div", { class: "group-label" }, group.label));
    controls.append(drawGroup(group));
  }
  appendNotes(controls, groups);
}

/* A dead button's reason, said under the buttons -- the Done a
   kickoff space holds back is the one a coach most needs to read. */
function appendNotes(controls, groups) {
  for (const group of groups) {
    for (const control of group.controls) {
      if (control.type === "button" && control.disabled && control.note
          && !control.card && !group.label) {
        controls.append(h("p", { class: "note-line" }, control.note));
      }
    }
  }
}

function drawGroup(group) {
  if (group.controls.length && group.controls.every((one) => one.card)) {
    return h("div", { class: "hand" }, group.controls.map(handCard));
  }
  return h("div", { class: "row" }, group.controls.map(drawControl));
}

function drawControl(control) {
  return control.type === "chooser" ? drawChooser(control) : drawButton(control);
}

function drawButton(control) {
  const button = h(
    "button",
    {
      type: "button",
      class: `btn ${control.style || "primary"}`,
      disabled: control.disabled,
      title: control.note || null,
      /* A press that is not an answer to this game (the rematch) goes
         to the room's own route rather than to the game. */
      onclick: () => (control.post ? roomMove(control.post) : act(control.action)),
    },
    control.label,
  );
  if (control.player) hoverCard(button, cardUrl(control.player));
  return button;
}

function handCard(control) {
  const { key, side } = control.card;
  const url = `/api/game/${GAME_ID}/maneuver/${encodeURIComponent(key)}.png?side=${side}`;
  const button = h(
    "button",
    {
      type: "button",
      class: `hand-card ${control.style}`,
      disabled: control.disabled,
      title: control.note || control.label,
      onclick: () => act(control.action),
    },
    h("img", { src: url, alt: control.label }),
  );
  hoverCard(button, `${url}&size=full`);
  return button;
}

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
  row.append(h("button", {
    type: "button",
    class: "btn primary",
    onclick: () => {
      const args = { ...control.action.arguments };
      for (const [name, select] of Object.entries(selects)) args[name] = select.value;
      act({ ...control.action, arguments: args });
    },
  }, control.submit));
  return row;
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
  if (table.start.owed) {
    row.append(tableButton("Start the game", "success", !table.start.may, "/table/start"));
  }
  if (coin.owed) {
    row.append(tableButton("Flip the coin", "primary", !coin.may, "/table/flip_coin"));
  }
  if (table.sides.owed_by) {
    for (const choice of table.sides.choices) {
      row.append(tableButton(choice.label, "primary", !(table.sides.may && choice.open),
        "/table/choose", { choice: choice.value }));
    }
  }
  if (table.may_close) {
    row.append(h("button", {
      type: "button",
      class: "btn secondary",
      onclick: () => {
        if (confirm("Close this room? Nothing has been played in it.")) roomMove("", {}, "DELETE");
      },
    }, "Close this room"));
  }
  if (row.childElementCount) body.append(row);
}

function tableButton(label, style, disabled, path, body) {
  return h("button", {
    type: "button",
    class: `btn ${style}`,
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
      class: `btn ${choice.value === setting.value ? "secondary" : "primary"}`,
      disabled: off || choice.value === setting.value,
      onclick: () => configure(choice.value),
    }, choice.label)));
  } else if (typeof setting.value === "boolean") {
    control = h("button", {
      type: "button",
      class: `btn ${setting.value ? "success" : "secondary"}`,
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
    }, input, h("button", { type: "submit", class: "btn primary", disabled: off }, "Rename"));
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
      class: `btn ${team.open ? "primary" : "secondary"}`,
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

function showRefusal(text) {
  el("refusal-text").textContent = text;
  el("refusal").hidden = false;
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
  peekFor = { url, cardId: decodeURIComponent(url.split("/card/")[1].split(".png")[0]) };
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

el("pick-up").addEventListener("click", pickUp);
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
