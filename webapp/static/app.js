/*
 * The page.
 *
 * It knows three things: how to ask the server for the state, how to
 * draw what comes back, and how to post one action. Every label, every
 * control and every sentence is the server's -- there is no rule of the
 * game in this file, and there must not be: the moment the web app has
 * one of its own, the model is being implemented twice (CLAUDE.md,
 * principle 10).
 */

const GAME_ID = location.pathname.split("/").pop();
const KEY = new URLSearchParams(location.search).get("key") || "";
const POLL_MS = 2500;

let latest = 0;
let boardVersion = 0;
let drawing = false;
let shownPrompt = null;

const el = (id) => document.getElementById(id);

function api(path, options) {
  const join = path.includes("?") ? "&" : "?";
  return fetch(`/api/game/${GAME_ID}${path}${KEY ? join + "key=" + KEY : ""}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
}

async function poll() {
  try {
    const response = await api(`?since=${latest}`);
    if (response.ok) {
      draw(await response.json());
    }
  } catch (error) {
    /* A dropped connection is weather; the next poll picks it up. */
  }
  setTimeout(poll, POLL_MS);
}

async function act(action) {
  if (drawing) return;
  drawing = true;
  try {
    const response = await api(`/action?since=${latest}`, {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    const state = await response.json();
    draw(state);
  } finally {
    drawing = false;
  }
}

async function pickUp() {
  const response = await api(`/resume?since=${latest}`, { method: "POST" });
  if (response.ok) draw(await response.json());
}

function draw(state) {
  latest = state.latest;
  drawScoreboard(state);
  drawBoard(state);
  drawEntries(state);
  drawPrompt(state);
  drawRefusal(state.refusal);
  el("owed").hidden = !state.owed;
  el("who").textContent = state.you.is_coach
    ? `You are ${coachName(state, state.you.player_number)}.`
    : "You are watching.";
}

function coachName(state, number) {
  const coach = state.game.coaches.find((one) => one.player_number === number);
  return coach ? coach.name : "somebody";
}

function drawScoreboard(state) {
  const sides = { home: el("home"), visiting: el("visiting") };
  for (const coach of state.game.coaches) {
    const box = sides[coach.side];
    if (!box) continue;
    box.replaceChildren();
    if (coach.colour) {
      const ring = document.createElement("span");
      ring.className = "ring";
      ring.style.background = coach.colour;
      box.append(ring);
    }
    box.append(`${coach.name}${coach.team ? " (" + coach.team + ")" : ""}`);
  }
  if (!state.scoreboard) return;
  el("score").textContent =
    `${state.scoreboard.home} - ${state.scoreboard.visiting}`;
  el("clock").textContent =
    `${state.scoreboard.period}, minute ${state.scoreboard.minute}`;
}

function drawBoard(state) {
  if (!state.board.url || state.board.version === boardVersion) return;
  boardVersion = state.board.version;
  el("board-image").src = state.board.url;
}

function drawEntries(state) {
  for (const entry of state.entries) {
    const block = document.createElement("div");
    block.className = entry.new_play ? "entry new-play" : "entry";
    for (const line of entry.lines) {
      const paragraph = document.createElement("p");
      paragraph.innerHTML = line;
      block.append(paragraph);
    }
    if (entry.board) {
      const picture = document.createElement("img");
      picture.src = `/api/game/${GAME_ID}/board.png?entry=${entry.id}`;
      picture.alt = "The board";
      block.append(picture);
    }
    el("journal").append(block);
  }
  if (state.entries.length) {
    el("journal").lastElementChild.scrollIntoView({ block: "nearest" });
  }
}

function drawPrompt(state) {
  const box = el("prompt");
  const controls = el("controls");
  /*
   * Only when it has actually changed. The page re-reads the whole
   * state every couple of seconds, and rebuilding the controls each
   * time would throw away a menu somebody is halfway through
   * choosing from.
   */
  const shape = JSON.stringify(state.prompt);
  if (shape === shownPrompt) return;
  shownPrompt = shape;
  controls.replaceChildren();
  if (!state.prompt) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  el("ask").innerHTML = state.prompt.ask;
  el("waiting").hidden = state.prompt.yours;
  el("waiting").textContent = "Waiting on the other side.";
  for (const group of state.prompt.controls) {
    controls.append(drawGroup(group));
  }
}

function drawGroup(group) {
  const box = document.createElement("div");
  box.className = "group";
  if (group.label) {
    const heading = document.createElement("h3");
    heading.textContent = group.label;
    box.append(heading);
  }
  for (const control of group.controls) {
    box.append(
      control.type === "chooser" ? drawChooser(control) : drawButton(control),
    );
  }
  return box;
}

function drawButton(control) {
  const button = document.createElement("button");
  button.textContent = control.label;
  button.disabled = control.disabled;
  button.title = control.note || "";
  button.addEventListener("click", () => act(control.action));
  return button;
}

function drawChooser(control) {
  const row = document.createElement("div");
  row.className = "chooser";
  if (control.label) {
    const said = document.createElement("span");
    said.textContent = control.label;
    row.append(said);
  }
  const selects = {};
  for (const field of control.fields) {
    if (field.label) {
      const label = document.createElement("label");
      label.textContent = field.label;
      row.append(label);
    }
    const select = document.createElement("select");
    for (const choice of field.choices) {
      const option = document.createElement("option");
      option.value = choice.value;
      option.textContent = choice.label;
      select.append(option);
    }
    selects[field.name] = select;
    row.append(select);
  }
  const button = document.createElement("button");
  button.textContent = control.submit;
  button.addEventListener("click", () => {
    const args = { ...control.action.arguments };
    for (const [name, select] of Object.entries(selects)) {
      args[name] = select.value;
    }
    act({ ...control.action, arguments: args });
  });
  row.append(button);
  return row;
}

function drawRefusal(refusal) {
  const box = el("refusal");
  box.hidden = !refusal;
  box.textContent = refusal || "";
}

el("pick-up").addEventListener("click", pickUp);
poll();
