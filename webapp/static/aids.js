/*
 * The reading room: the rules, the two rulebooks and the player aids
 * (step 11 of docs/web-app-next.md).
 *
 * One panel, opened from a room's header and from the front door, and
 * the search box on /rules. What is in it is the server's: a room's
 * state carries `aids` -- the hexagon at the game's tier, the species
 * card only where the game plays it, the team cards in the face it
 * holds, each chosen by the model -- and the front door asks
 * /api/aids for all of them. Nothing here decides which, and nothing
 * here goes in the game log or touches the game.
 */

(function () {
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

  /* A search box over /api/rules: `RulesDocument.search`, the answer
     /d12ball rules_search offers. `base` is where a result points --
     "" on /rules itself, "/rules" from the panel, which opens it in a
     tab of its own. */
  function attachSearch(form, base) {
    const input = form.querySelector("input");
    const list = form.querySelector(".rules-results");
    let asked = 0;
    let timer = null;
    const target = base ? { target: "_blank", rel: "noopener" } : {};
    async function ask() {
      const query = input.value.trim();
      const mine = ++asked;
      if (!query) {
        list.hidden = true;
        list.replaceChildren();
        return;
      }
      let found;
      try {
        const response = await fetch(`/api/rules?q=${encodeURIComponent(query)}`);
        if (!response.ok) throw new Error(await response.text());
        found = (await response.json()).sections;
      } catch (error) {
        if (mine !== asked) return;
        list.replaceChildren(h("li", { class: "quiet" }, "The rules could not be read."));
        list.hidden = false;
        return;
      }
      if (mine !== asked) return;
      list.replaceChildren(
        ...(found.length
          ? found.map((one) =>
              h("li", {},
                h("a", { href: `${base}#${one.slug}`, class: "linkish", ...target },
                  one.number ? h("span", { class: "rules-number" }, one.number) : null,
                  one.number ? " " : null,
                  one.label)))
          : [h("li", { class: "quiet" }, "Nothing in the rules says that.")]),
      );
      list.hidden = false;
    }
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(ask, 200);
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      clearTimeout(timer);
      ask();
    });
  }

  let dialog = null;
  let shown = null;
  let team = 0;
  let face = 0;

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = h("dialog", { class: "viewer aids", "aria-label": "Rules and aids" });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    document.body.append(dialog);
    return dialog;
  }

  /* One picture, full size, in place of the panel -- like the board --
     with the way back to the panel. */
  function openImage(url, alt) {
    const box = ensureDialog();
    box.replaceChildren(
      h("button", { type: "button", class: "viewer-close", "aria-label": "Close", onclick: () => box.close() }, "×"),
      h("div", { class: "viewer-body" },
        h("p", {}, h("button", { type: "button", class: "linkish", onclick: () => draw() }, "‹ Back to the rules and aids")),
        h("a", { href: url, target: "_blank", rel: "noopener" }, h("img", { src: url, alt: alt || "" }))),
    );
    if (!box.open) box.showModal();
  }

  function picture(url, name) {
    return h("figure", { class: "aid" },
      h("button", { type: "button", class: "aid-open", onclick: () => openImage(url, name) },
        h("img", { src: url, alt: name || "A card", loading: "lazy" })),
      name ? h("figcaption", { class: "quiet" }, name) : null);
  }

  function heading(text) {
    return h("div", { class: "panel-label" }, text);
  }

  function draw() {
    const aids = shown;
    const box = ensureDialog();
    const search = h("form", { class: "rules-search", role: "search" },
      h("input", { class: "chat-input", type: "search", placeholder: "Search the rules", "aria-label": "Search the rules", autocomplete: "off" }),
      h("ol", { class: "rules-results", hidden: true }));
    attachSearch(search, aids.rules);

    const teams = aids.teams || [];
    if (team >= teams.length) team = 0;
    box.replaceChildren(
      h("button", { type: "button", class: "viewer-close", "aria-label": "Close", onclick: () => box.close() }, "×"),
      h("div", { class: "viewer-body aids-body" },
        h("section", {},
          heading("The rules"),
          search,
          h("p", {},
            h("a", { href: aids.rules, class: "linkish", target: "_blank", rel: "noopener" }, "Read the Charter"),
            ...aids.books.flatMap((book) => [" · ",
              h("a", { href: book.url, class: "linkish", target: "_blank", rel: "noopener" }, `${book.title} (PDF)`)]))),
        h("section", {},
          heading("Maneuvers"),
          h("div", { class: "aid-row" }, aids.maneuvers.map((one) => picture(one.url, one.name)))),
        h("section", {},
          heading("Roles"),
          h("div", { class: "aid-row" }, picture(aids.roles, "The role abilities"))),
        aids.species.length
          ? h("section", {},
              heading("Species"),
              h("div", { class: "aid-row" }, aids.species.map((one) => picture(one.url, one.name))))
          : null,
        teams.length ? teamSection(teams) : null,
      ),
    );
    if (!box.open) box.showModal();
    box.querySelector(".viewer-body").scrollTop = 0;
    search.querySelector("input").focus({ preventScroll: true });
  }

  /* A team's cards, a tab a team -- the seat's own first -- and, where
     more than one face is offered (the front door), a face a tab.
     Redrawn in place, so the panel keeps where it was scrolled to. */
  function teamSection(teams) {
    const chosen = teams[team];
    if (face >= chosen.faces.length) face = 0;
    const section = h("section", {},
      heading("Teams"),
      h("div", { class: "aid-tabs", role: "tablist" },
        teams.map((one, index) =>
          h("button", {
            type: "button",
            role: "tab",
            class: `btn ${index === team ? "primary" : "secondary"}`,
            "aria-selected": index === team ? "true" : "false",
            onclick: () => { team = index; section.replaceWith(teamSection(teams)); },
          }, one.name, one.yours ? " (yours)" : ""))),
      chosen.faces.length > 1
        ? h("div", { class: "aid-tabs" },
            chosen.faces.map((one, index) =>
              h("button", {
                type: "button",
                class: `linkish${index === face ? " chosen" : ""}`,
                onclick: () => { face = index; section.replaceWith(teamSection(teams)); },
              }, one.name)))
        : null,
      h("div", { class: "aid-row cards" },
        chosen.faces[face].cards.map((url) => picture(url, ""))));
    return section;
  }

  /* The panel, from what the server handed over. A room's aids come
     with its state; the front door's from /api/aids. */
  function open(aids) {
    if (!aids) return;
    if (JSON.stringify(aids) !== JSON.stringify(shown)) {
      team = 0;
      face = 0;
    }
    shown = aids;
    draw();
  }

  async function openEverything() {
    try {
      const response = await fetch("/api/aids");
      if (!response.ok) throw new Error(await response.text());
      open(await response.json());
    } catch (error) {
      alert("The rules and aids could not be opened.");
    }
  }

  window.D12Aids = { open, openEverything, attachSearch };

  for (const form of document.querySelectorAll("[data-rules-search]")) attachSearch(form, "");
})();
