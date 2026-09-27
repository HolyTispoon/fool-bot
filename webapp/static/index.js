/*
 * The front door: who is reading, as `@name` in the top bar -- a name
 * the server made up on the first visit (webapp/identity.py,
 * `guest_name`) and nobody else holds (webapp/names.py), and a click on
 * it the menu to rename or delete every game you sit in -- this
 * reader's rooms and
 * the rooms with a seat free as cards (`GET /api/rooms`), and a new
 * room in its lobby (`POST /api/rooms`) -- always a room of two. The
 * two ticks under it are the table's own moves, made in sequence
 * straight after: Dinky put in seat 2 (`POST /api/room/{id}/seat/ai`,
 * `seat_ai`) and the tutorial setting (`POST /api/room/{id}/table/
 * configure`, `configure`). The record refuses either with its own
 * sentence, which the room then shows; nothing about the game is
 * decided here.
 */

const input = document.getElementById("name-input");
const error = document.getElementById("name-error");

/* Where a room stands, as its card's chip says it. */
const STANDING = {
  lobby: "In the lobby",
  setup: "Setting up",
  in_progress: "Playing",
  finished: "Finished",
};

function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (name === "class") node.className = value;
    else node.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : String(child));
  }
  return node;
}

function refuse(text) {
  error.textContent = text;
  error.hidden = false;
}

/* A seat on a card: the team's dot (a dashed ring before a team is
   picked), the seat's name and who holds it. */
function seatLine(seat) {
  const dot = seat.colour
    ? h("span", { class: "team-dot", style: `background: ${seat.colour}`, title: seat.team })
    : h("span", { class: "team-dot none" });
  return h("span", { class: "card-seat" }, dot, `${seat.label}: `,
    seat.name ? h("b", {}, seat.name) : h("b", { class: "free" }, "free"));
}

/* What the room is called on its card: its name, or the two teams
   once both are picked. */
function topic(room) {
  if (room.name) return room.name;
  const teams = room.seats.map((seat) => seat.team).filter(Boolean);
  return teams.length === 2 ? `${teams[0]} v ${teams[1]}` : "";
}

/* The card's right-hand line: the mode and the board, the clock (or
   the result) once there is a match, and who is watching. */
function facts(room) {
  const parts = [room.mode, `${room.board_size} spaces`];
  if (room.tutorial) parts.push("tutorial");
  if (room.clock) parts.push(room.clock);
  else if (room.observers) parts.push(`${room.observers} watching`);
  return parts.join(" · ");
}

function roomCard(room, { renamable = false } = {}) {
  const standing = room.abandoned ? "abandoned" : room.status;
  const card = h(
    "a",
    { class: `room-card${room.your_move ? " your-move" : ""}`, href: room.url },
    h("div", { class: "card-head" },
      h("span", { class: "card-number" }, h("span", { class: "hash" }, "#"), `pbw${room.number}`),
      h("span", { class: "card-topic" }, topic(room)),
      h("span", { class: "grow" }),
      h("span", { class: `status-chip ${standing}` },
        room.abandoned ? "Abandoned" : STANDING[room.status] || room.status)),
    h("div", { class: "card-seats" },
      room.seats.map(seatLine),
      h("span", { class: "grow" }),
      h("span", { class: "card-facts" }, facts(room))),
  );
  if (renamable && room.status === "lobby") {
    card.querySelector(".card-head").append(h("button", {
      type: "button",
      class: "linkish",
      title: "Name this room",
      onclick: (event) => { event.preventDefault(); event.stopPropagation(); renameRoom(room); },
    }, "Name"));
  }
  const out = wayOut(room);
  if (out) card.querySelector(".card-head").append(out);
  return card;
}

/* A dead room cleared from the list without opening it: Close for a
   room nothing was played in (it is gone), Abandon for a game under
   way (it stays, over, and counts as abandoned). The server says
   which a card is offered (`may_close`, `may_abandon`) and judges the
   click again; the room's own page asks the same two routes. */
function wayOut(room) {
  const [label, question, method, path] = room.may_close
    ? ["Close", "Close this room? Nothing has been played in it.", "DELETE", ""]
    : room.may_abandon
      ? ["Abandon", "Abandon this game? It ends with no result.", "POST", "/abandon"]
      : [];
  if (!label) return null;
  return h("button", {
    type: "button",
    class: "linkish danger-link",
    title: label === "Close" ? "Close this room" : "Abandon this game",
    onclick: async (event) => {
      event.preventDefault();
      event.stopPropagation();
      /* Closing asks only when somebody else is sitting in the room
         (`close_asks`); abandoning a game always does. */
      if ((label !== "Close" || room.close_asks) && !confirm(question)) return;
      try {
        const response = await fetch(`/api/room/${room.id}${path}`, { method });
        if (!response.ok) refuse(await response.text());
      } catch (failure) {
        refuse("That did not reach the server. Try again in a moment.");
      }
      listRooms();
    },
  }, label);
}

/* Naming a room is the table's `name` setting (d12ball/game.py's
   GAME_SETTINGS): the record judges when it is open (the lobby only)
   and refuses otherwise with its own sentence, which this shows
   rather than working the rule out here. */
async function renameRoom(room) {
  const name = window.prompt("Name this room:", room.name || "");
  if (name === null) return;
  const refused = await tableMove(room.id, "/table/configure", { setting: "name", value: name });
  if (refused) refuse(refused);
  listRooms();
}

/* One move on a room's table or seats; the record's refusal, or null. */
async function tableMove(id, path, body) {
  try {
    const response = await fetch(`/api/room/${id}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (response.ok) return null;
    const text = await response.text();
    try { return JSON.parse(text).refusal || text; } catch (failure) { return text; }
  } catch (failure) {
    return "That did not reach the server. Try again in a moment.";
  }
}

async function listRooms() {
  try {
    const response = await fetch("/api/rooms");
    if (!response.ok) return;
    const rooms = await response.json();
    const mine = Object.keys(STANDING).flatMap((status) => rooms.mine[status] || []);
    mineCount = mine.length;
    document.getElementById("mine-list").replaceChildren(
      ...mine.map((room) => roomCard(room, { renamable: true })),
    );
    document.getElementById("mine").hidden = !mine.length;
    document.getElementById("open-list").replaceChildren(...rooms.open.map((room) => roomCard(room)));
    document.getElementById("open").hidden = !rooms.open.length;
    document.getElementById("no-rooms").hidden = Boolean(mine.length || rooms.open.length);
  } catch (failure) {
    /* The lists are a convenience; the new room still works. */
  }
}

const named = document.getElementById("named");
const menu = document.getElementById("me-menu");
const nameRefusal = document.getElementById("name-refusal");
let savedName = "";
let mineCount = 0;

function showName(name) {
  savedName = name || "";
  named.textContent = savedName ? `@${savedName}` : "";
}

/* Who is reading. `GET /api/me` names somebody new when the cookie
   names nobody, so every move below waits on it: a room is opened
   under the cookie it sets. */
const me = fetch("/api/me")
  .then((response) => (response.ok ? response.json() : null))
  .then((coach) => showName(coach && coach.name))
  .catch(() => {});
listRooms();

/* The menu under `@name`: the name, edited and saved, and deleting
   every game this reader sits in. Escape or a click outside closes it. */
function openMenu() {
  input.value = savedName;
  nameRefusal.hidden = true;
  menu.hidden = false;
  named.setAttribute("aria-expanded", "true");
  input.focus();
  input.select();
}

function closeMenu() {
  menu.hidden = true;
  named.setAttribute("aria-expanded", "false");
}

named.addEventListener("click", () => (menu.hidden ? openMenu() : closeMenu()));
document.addEventListener("click", (event) => {
  if (!menu.hidden && !menu.contains(event.target) && event.target !== named) closeMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !menu.hidden) { closeMenu(); named.focus(); }
});

/* A rename the server refuses -- empty, too long, or somebody else's
   name (webapp/names.py) -- says why in the menu and leaves it open. */
document.getElementById("name-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = input.value.trim();
  if (name === savedName) return closeMenu();
  try {
    const response = await fetch("/api/me", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!response.ok) {
      nameRefusal.textContent = await response.text();
      nameRefusal.hidden = false;
      return;
    }
    showName((await response.json()).name);
    closeMenu();
    listRooms();
  } catch (failure) {
    nameRefusal.textContent = "That did not reach the server. Try again in a moment.";
    nameRefusal.hidden = false;
  }
});

/* Every game this reader holds a seat in -- "Your rooms" -- erased for
   everybody in it, and a new made-up name; asked once more first. */
document.getElementById("delete-games").addEventListener("click", async () => {
  const count = mineCount === 1 ? "your 1 game" : `all ${mineCount} of your games`;
  if (!window.confirm(
    `Are you sure? This deletes ${count} — every game you hold a seat in, `
    + "for everyone in it, finished ones included — and gives you a new "
    + "random name. It cannot be undone.",
  )) return;
  try {
    const response = await fetch("/api/me/games", { method: "DELETE" });
    if (!response.ok) return refuse(await response.text());
    showName((await response.json()).coach.name);
    closeMenu();
    listRooms();
  } catch (failure) {
    refuse("That did not reach the server. Try again in a moment.");
  }
});

/* A new room, then the ticks in order: Dinky first, since the tutorial
   pins a game for one and the record refuses to seat the AI in it
   after -- while the tutorial toggle is still open with the AI seated,
   because nobody has joined. A refusal is shown and the room still
   opens, where the table offers both again. */
async function openRoom({ ai = false, tutorial = false } = {}) {
  try {
    await me;
    const opened = await fetch("/api/rooms", { method: "POST" });
    if (!opened.ok) return refuse(await opened.text());
    const room = await opened.json();
    if (ai) await tableMove(room.id, "/seat/ai", { seat: 2 });
    if (tutorial) await tableMove(room.id, "/table/configure", { setting: "tutorial" });
    location.href = room.url;
  } catch (failure) {
    refuse(failure.message || "That did not reach the server. Try again in a moment.");
  }
}

document.getElementById("new-room").addEventListener("click", () => openRoom({
  ai: document.getElementById("tick-ai").checked,
  tutorial: document.getElementById("tick-tutorial").checked,
}));

/* "New to the game?": a room of one with the tutorial set, the same as
   ticking only "the tutorial" under a new room. */
document.getElementById("tutorial").addEventListener("click", () => openRoom({ tutorial: true }));
