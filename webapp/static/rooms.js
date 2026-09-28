/*
 * A room as a card, shared by the Master Lobby (index.js) and the
 * archive (archive.js): both draw the server's listing
 * (`WebApp._listing`) and decide nothing about it.
 */

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

/* One room as a card: its number and name, where it stands, both
   seats with their team's dot, the mode, the board and the clock --
   the whole card a link into the room. `extras` go at the end of its
   head: the Master Lobby's Name, Leave seat, Close and Abandon. */
function roomCard(room, extras = []) {
  const standing = room.abandoned ? "abandoned" : room.status;
  return h(
    "a",
    { class: `room-card${room.your_move ? " your-move" : ""}`, href: room.url },
    h("div", { class: "card-head" },
      h("span", { class: "card-number" }, h("span", { class: "hash" }, "#"), `pbw${room.number}`),
      h("span", { class: "card-topic" }, topic(room)),
      h("span", { class: "grow" }),
      h("span", { class: `status-chip ${standing}` },
        room.abandoned ? "Abandoned" : STANDING[room.status] || room.status),
      ...extras.filter(Boolean)),
    h("div", { class: "card-seats" },
      room.seats.map(seatLine),
      h("span", { class: "grow" }),
      h("span", { class: "card-facts" }, facts(room))),
  );
}
