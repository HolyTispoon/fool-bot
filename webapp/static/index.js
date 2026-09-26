/*
 * The front door: a name (webapp/identity.py), this reader's rooms and
 * the rooms with a seat free (`GET /api/rooms`), and a new room in its
 * lobby (`POST /api/rooms`) -- always a room of two, in its lobby; the
 * AI and the tutorial are the table's own choices from there, not
 * this form's. Nothing about the game is decided here.
 */

const input = document.getElementById("name-input");
const error = document.getElementById("name-error");

/* Where a room stands, as the list heads it. */
const STANDING = {
  lobby: "In the lobby",
  setup: "Setting up",
  in_progress: "Playing",
  finished: "Finished",
};

function refuse(text) {
  error.textContent = text;
  error.hidden = false;
}

function roomLine(room, { renamable = false } = {}) {
  const line = document.createElement("div");
  line.className = "seat room-line";
  line.tabIndex = 0;
  line.setAttribute("role", "link");
  const go = () => { location.href = room.url; };
  line.addEventListener("click", go);
  line.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); go(); }
  });
  const title = document.createElement("span");
  title.className = "room-line-title";
  title.textContent = `PBW${room.number}${room.name ? ` · ${room.name}` : ""}${room.tutorial ? " · tutorial" : ""}`;
  const seats = document.createElement("span");
  seats.className = "seat-name";
  seats.textContent = room.seats
    .map((seat) => `${seat.label}: ${seat.name || "free"}`)
    .join(" · ");
  const standing = document.createElement("span");
  standing.className = "seat-label";
  standing.textContent = room.abandoned ? "Abandoned" : STANDING[room.status] || room.status;
  line.append(title, seats, standing);
  if (renamable) {
    const rename = document.createElement("button");
    rename.type = "button";
    rename.className = "linkish";
    rename.textContent = "Name";
    rename.addEventListener("click", (event) => { event.stopPropagation(); renameRoom(room); });
    line.append(rename);
  }
  return line;
}

/* Naming a room is the table's `name` setting (d12ball/game.py's
   GAME_SETTINGS): the record judges when it is open (the lobby only)
   and refuses otherwise with its own sentence, which this shows
   rather than working the rule out here. */
async function renameRoom(room) {
  const name = window.prompt("Name this game:", room.name || "");
  if (name === null) return;
  try {
    const response = await fetch(`/api/room/${room.id}/table/configure`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ setting: "name", value: name }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      refuse((body && body.refusal) || "That name was refused.");
      return;
    }
    listRooms();
  } catch (failure) {
    refuse("That did not reach the server. Try again in a moment.");
  }
}

async function listRooms() {
  try {
    const response = await fetch("/api/rooms");
    if (!response.ok) return;
    const rooms = await response.json();
    const mine = Object.keys(STANDING).flatMap((status) => rooms.mine[status] || []);
    document.getElementById("mine-list").replaceChildren(
      ...mine.map((room) => roomLine(room, { renamable: true })),
    );
    document.getElementById("mine").hidden = !mine.length;
    document.getElementById("open-list").replaceChildren(...rooms.open.map((room) => roomLine(room)));
    document.getElementById("open").hidden = !rooms.open.length;
  } catch (failure) {
    /* The lists are a convenience; the buttons still work. */
  }
}

fetch("/api/me")
  .then((response) => (response.ok ? response.json() : null))
  .then((me) => { if (me) input.value = me.name; })
  .catch(() => {});
listRooms();

async function saveName() {
  const named = await fetch("/api/me", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: input.value }),
  });
  if (!named.ok) throw new Error(await named.text());
  error.hidden = true;
}

document.getElementById("open-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await saveName();
    const opened = await fetch("/api/rooms", { method: "POST" });
    if (!opened.ok) return refuse(await opened.text());
    location.href = (await opened.json()).url;
  } catch (failure) {
    refuse(failure.message || "That did not reach the server. Try again in a moment.");
  }
});

document.getElementById("save-name").addEventListener("click", async () => {
  try {
    await saveName();
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

/* The reading room, with no game to ask: every aid (/api/aids). */
document.getElementById("open-aids").addEventListener("click", () => window.D12Aids.openEverything());
