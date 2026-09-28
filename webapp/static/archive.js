/*
 * The archive: every web game that is over, newest first, as the
 * Master Lobby's cards (rooms.js), filtered here by what the listing
 * already says -- played to the end or abandoned, and whether the
 * reader coached it. Nothing is decided here.
 */

const FILTERS = [
  ["all", "All", () => true],
  ["played", "Played to the end", (game) => !game.abandoned],
  ["abandoned", "Abandoned", (game) => game.abandoned],
  ["yours", "Yours", (game) => game.yours],
];

let games = [];
let shown = "all";

function draw() {
  const [, , keep] = FILTERS.find(([key]) => key === shown);
  const listed = games.filter(keep);
  document.getElementById("filters").replaceChildren(...FILTERS.map(([key, label, test]) => h("button", {
    type: "button",
    class: `pill${key === shown ? " current" : ""}`,
    "aria-pressed": key === shown ? "true" : "false",
    onclick: () => { shown = key; draw(); },
  }, `${label} · ${games.filter(test).length}`)));
  document.getElementById("archive-list").replaceChildren(...listed.map((game) => roomCard(game, [
    game.yours ? h("span", { class: "tag-chip you" }, "YOU PLAYED") : null,
  ])));
  document.getElementById("nothing").hidden = Boolean(listed.length);
}

/* Who is reading first, so "Yours" is theirs. */
fetch("/api/me")
  .catch(() => null)
  .then(() => fetch("/api/archive"))
  .then((response) => (response.ok ? response.json() : { games: [] }))
  .then((archive) => { games = archive.games; draw(); })
  .catch(() => { document.getElementById("nothing").hidden = false; });
