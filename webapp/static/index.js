/*
 * The front door: a name (webapp/identity.py), this reader's rooms and
 * the rooms with a seat free (`GET /api/rooms`), and a new room
 * (`POST /api/rooms`) -- a room of two, or one against the AI, either
 * of them the tutorial. Nothing about the game is decided here.
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

function roomLine(room) {
  const line = document.createElement("div");
  line.className = "seat";
  const link = document.createElement("a");
  link.href = room.url;
  link.textContent = `PBD${room.number}${room.name ? ` · ${room.name}` : ""}${room.tutorial ? " · tutorial" : ""}`;
  const seats = document.createElement("span");
  seats.className = "seat-name";
  seats.textContent = room.seats
    .map((seat) => `${seat.label}: ${seat.name || "free"}`)
    .join(" · ");
  const standing = document.createElement("span");
  standing.className = "seat-label";
  standing.textContent = STANDING[room.status] || room.status;
  line.append(link, seats, standing);
  return line;
}

async function listRooms() {
  try {
    const response = await fetch("/api/rooms");
    if (!response.ok) return;
    const rooms = await response.json();
    const mine = Object.keys(STANDING).flatMap((status) => rooms.mine[status] || []);
    document.getElementById("mine-list").replaceChildren(...mine.map(roomLine));
    document.getElementById("mine").hidden = !mine.length;
    document.getElementById("open-list").replaceChildren(...rooms.open.map(roomLine));
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

document.getElementById("open-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const againstAi = event.submitter && event.submitter.dataset.ai === "1";
  try {
    const named = await fetch("/api/me", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: input.value }),
    });
    if (!named.ok) return refuse(await named.text());
    const opened = await fetch("/api/rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ai: againstAi,
        tutorial: document.getElementById("tutorial").checked,
      }),
    });
    if (!opened.ok) return refuse(await opened.text());
    location.href = (await opened.json()).url;
  } catch (failure) {
    refuse("That did not reach the server. Try again in a moment.");
  }
});
