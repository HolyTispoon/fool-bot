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
  drawTable(state);
  drawRoom(state);
  followRematch(state);
  if (state.refusal) showRefusal(state.refusal);
  el("owed").hidden = !(state.owed && state.you.is_coach);
  const yours = Boolean(state.prompt && state.prompt.yours);
  document.title = `${yours ? "● " : ""}PBW${state.game.number} · D12 Ball`;
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

/* The field as the bot draws it: the visitors' cards over each zone,
   the spaces, the range bands, the home side's cards under it. The
   jumbotron has its own panel, and the benches open on demand. */
function stage(layout, { live }) {
  return h(
    "div",
    { class: "stage", onclick: live ? openBoardOnPhone : null },
    pitch(layout),
  );
}

function pitch(layout) {
  const count = layout.spaces.length;
  const grid = h("div", {
    class: "pitch",
    style: `grid-template-columns: 62px repeat(${count}, minmax(0, 1fr)) 62px`,
  });

  grid.append(
    h("div", { class: "field-frame", style: `grid-column: 2 / ${count + 2}` }),
    goal("home", layout.goals.home, 1),
    goal("visiting", layout.goals.visiting, count + 2),
  );

  let column = 2;
  let first = 0;
  for (const zone of layout.zones) {
    const span = `grid-column: ${column} / span ${zone.spaces}`;
    grid.append(
      h("div", { class: "cards-row visiting", style: `${span}; grid-row: 1` },
        zone.visiting.map((card) => playerCard(card))),
      h("div", { class: "cards-row home", style: `${span}; grid-row: 4` },
        zone.home.map((card) => playerCard(card))),
      h(
        "div",
        { class: "zone", style: `${span}; background: ${zone.fill}` },
        h("div", { class: "zone-label" }, zone.label),
        h(
          "div",
          {
            class: "spaces",
            style: `grid-template-columns: repeat(${zone.spaces}, minmax(0, 1fr))`,
          },
          layout.spaces.slice(first, first + zone.spaces).map((one) => space(one, layout)),
        ),
      ),
    );
    column += zone.spaces;
    first += zone.spaces;
  }

  for (const band of layout.bands) {
    grid.append(
      h(
        "div",
        {
          class: band.side ? "band side" : "band neutral",
          style: `grid-column: ${band.first + 2} / ${band.last + 3}`,
        },
        band.label || "",
      ),
    );
  }
  return grid;
}

/* An end zone, as the bot's board draws it (`render.draw_end_zone`). */
function goal(side, url, column) {
  return h(
    "div",
    { class: `goal ${side}`, style: `grid-column: ${column}` },
    h("img", { src: url, alt: "", draggable: "false" }),
  );
}

/* How wide a meeple is on the stage. Everything else about the piece
   -- its height, where its icon and letters sit, the ball beside it --
   is a share of this, in `render.py`'s own numbers
   (`webapp/board.py`, `meeple_geometry`). */
const MEEPLE_WIDTH = 42;

function space(one, layout) {
  const g = layout.meeple;
  const half = (side) => {
    const players = one[side];
    const holds = one.ball && one.ball.side === side;
    const ball = holds ? d12(String(one.ball.speed), g) : null;
    /* Each name under its own meeple, a line further down for each
       player along the row, as `draw_meeple_group` lists them. */
    const pieces = players.map((m, index) =>
      h(
        "div",
        { class: "piece" },
        meeple(m, layout),
        h("div", { class: "piece-name", style: `margin-top: ${index * 1.15}em` }, m.name),
      ));
    const row = side === "home" ? [...pieces, ball] : [ball, ...pieces];
    return h(
      "div",
      { class: `half ${side}${holds && !players.length ? " ball-only" : ""}` },
      row,
    );
  };
  return h(
    "div",
    { class: "space" },
    h("span", { class: "space-code" }, one.code),
    half("visiting"),
    half("home"),
  );
}

function meeple(m, layout) {
  const g = layout.meeple;
  const [left, top, width, height] = g.box;
  const W = MEEPLE_WIDTH;
  const H = (W * height) / width;
  const icon = layout.species_icons && m.species;
  const center = icon ? g.role_center : g.solo_center;
  const node = h(
    "div",
    {
      class: "meeple",
      style: `width: ${W}px; height: ${H}px; color: ${m.ink}`,
      title: `${m.name} [${m.role}]`,
      onclick: (event) => { event.stopPropagation(); openCard(m.id); },
    },
    s(
      "svg",
      { viewBox: `${left} ${top} ${width} ${height}`, "aria-hidden": "true" },
      s("path", {
        d: g.path,
        fill: m.colour,
        stroke: m.ink,
        "stroke-width": String(g.stroke),
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

/* The ball: a white d12 the size `BALL_RADIUS` makes it beside a
   meeple, its speed in the board's small regular face, both in the
   bot's dark blue. */
function d12(label, g) {
  const size = g.ball * MEEPLE_WIDTH;
  /* Centred on the meeples' height, as `ball_y` centres it on theirs. */
  const tall = (MEEPLE_WIDTH * g.box[3]) / g.box[2];
  const points = [];
  for (let i = 0; i < 12; i += 1) {
    const angle = (Math.PI / 6) * i - Math.PI / 2;
    points.push(`${(Math.cos(angle) * 50).toFixed(2)},${(Math.sin(angle) * 50).toFixed(2)}`);
  }
  return s(
    "svg",
    {
      class: "ball",
      viewBox: "-53 -53 106 106",
      width: size,
      height: size,
      style: `margin-top: ${(tall - size) / 2}px`,
      "aria-label": `ball, speed ${label}`,
    },
    s("polygon", {
      points: points.join(" "),
      fill: "#ffffff",
      stroke: "#243347",
      "stroke-width": String((3 / 27) * 50),
    }),
    s(
      "text",
      {
        x: "0",
        y: "0",
        "text-anchor": "middle",
        "dominant-baseline": "central",
        "font-size": String(g.ball_font * 100),
        "font-family": "Board, sans-serif",
        fill: "#243347",
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

/* A name is centred under its meeple and kept inside the space's own
   border, as `draw_meeple_group` keeps it (10px in on a 2200px board). */
function clampNames(root) {
  for (const name of root.querySelectorAll(".piece-name")) {
    name.style.setProperty("--nudge", "0px");
    const piece = name.parentElement;
    const space = piece.closest(".space");
    if (!space || !name.offsetWidth) continue;
    const left = piece.offsetLeft + piece.offsetWidth / 2 - name.offsetWidth / 2;
    const least = 5;
    const most = space.clientWidth - 5 - name.offsetWidth;
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
  drawControls(state.prompt);
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

/* The printed card under the pointer, where there is a pointer. */
function hoverCard(node, url) {
  node.addEventListener("mouseenter", (event) => {
    if (finePointer()) showPeek(url, event);
  });
  node.addEventListener("mousemove", movePeek);
  node.addEventListener("mouseleave", hidePeek);
}

function showPeek(url, event) {
  const peek = el("peek");
  const image = peek.firstElementChild;
  if (image.getAttribute("src") !== url) image.src = url;
  peek.hidden = false;
  movePeek(event);
}

function movePeek(event) {
  const peek = el("peek");
  if (peek.hidden) return;
  const width = 260;
  const height = 364;
  let x = event.clientX + 18;
  let y = event.clientY - height / 2;
  if (x + width > window.innerWidth - 8) x = event.clientX - width - 18;
  y = Math.max(8, Math.min(y, window.innerHeight - height - 8));
  peek.style.left = `${x}px`;
  peek.style.top = `${y}px`;
}

function hidePeek() {
  el("peek").hidden = true;
}

// -- Wiring ------------------------------------------------------------------

el("pick-up").addEventListener("click", pickUp);
el("become-admin").addEventListener("click", () => {
  if (confirm("Take the admin role for this room?")) roomMove("/admin");
});
el("drop-admin").addEventListener("click", () => {
  if (confirm("Give up the admin role for this room?")) roomMove("/admin", {}, "DELETE");
});
el("change-name").addEventListener("click", async () => {
  const known = current && current.you && current.you.coach;
  const name = window.prompt("What should the table call you?", known ? known.name : "");
  if (name === null) return;
  const response = await fetch("/api/me", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (response.ok) location.reload();
  else window.alert(await response.text());
});
el("leave-app").addEventListener("click", async () => {
  if (!confirm("Leave the app? You will be asked for a name again next time.")) return;
  await fetch("/api/me", { method: "DELETE" });
  location.href = "/";
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
