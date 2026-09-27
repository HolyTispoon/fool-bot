/*
 * The front door: a name (webapp/identity.py), this reader's rooms and
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
  return card;
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

function showName(name) {
  document.getElementById("named").textContent = name || "";
}

fetch("/api/me")
  .then((response) => (response.ok ? response.json() : null))
  .then((me) => {
    if (me) input.value = me.name;
    showName(me && me.name);
  })
  .catch(() => {});
listRooms();

let savedName = null;

async function saveName() {
  const name = input.value.trim();
  if (!name) throw new Error("Say what the table should call you first.");
  if (name === savedName) return;
  const named = await fetch("/api/me", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!named.ok) throw new Error(await named.text());
  savedName = name;
  error.hidden = true;
  showName(name);
}

/* The name is edited in place: it saves when the field is left, or on
   Enter. */
async function saveNameQuietly() {
  try {
    await saveName();
  } catch (failure) {
    refuse(failure.message || "That did not reach the server. Try again in a moment.");
  }
}
input.addEventListener("change", saveNameQuietly);
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); input.blur(); }
});

/* A new room, then the ticks in order: Dinky first, since the tutorial
   pins a game for one and the record refuses to seat the AI in it
   after -- while the tutorial toggle is still open with the AI seated,
   because nobody has joined. A refusal is shown and the room still
   opens, where the table offers both again. */
document.getElementById("new-room").addEventListener("click", async () => {
  try {
    await saveName();
    const opened = await fetch("/api/rooms", { method: "POST" });
    if (!opened.ok) return refuse(await opened.text());
    const room = await opened.json();
    if (document.getElementById("tick-ai").checked) {
      await tableMove(room.id, "/seat/ai", { seat: 2 });
    }
    if (document.getElementById("tick-tutorial").checked) {
      await tableMove(room.id, "/table/configure", { setting: "tutorial" });
    }
    location.href = room.url;
  } catch (failure) {
    refuse(failure.message || "That did not reach the server. Try again in a moment.");
  }
});

document.getElementById("leave-app").addEventListener("click", async () => {
  if (!window.confirm("Leave the app? You will be asked for a name again next time.")) return;
  try {
    await fetch("/api/me", { method: "DELETE" });
  } catch (failure) {
    /* Leaving is local either way; the cookie is what mattered. */
  }
  location.reload();
});
