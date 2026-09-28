/*
 * The rules in the page: the Rules tab in a room's sidebar and the
 * Reading Room at /rules (step 10 of docs/web-app-redesign.md).
 *
 * What is in them is the server's. The Charter is `/api/rules/charter`
 * -- the living rules as `rules_doc` reads them, grouped by the Laws
 * the Charter's build numbers -- the Learn to Play is
 * `/api/rules/learn`, the book's own markdown with its figures, and
 * the References are the room's `aids` (the cards, the roles and the
 * species the game plays, each chosen by the model) or, in the Reading
 * Room, `/api/aids`. The search is `/api/rules?q=`, the answer
 * `/d12ball rules_search` offers. Nothing here decides which Law says
 * what, nothing here goes in the game log, and there is no PDF.
 */

(function () {
  function h(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
      else if (name === "class") node.className = value;
      /* Only ever the server's HTML: the rules as `webapp/aids.py`
         set them, escaped before they were marked up. */
      else if (name === "html") node.innerHTML = value;
      else node.setAttribute(name, value === true ? "" : value);
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : String(child));
    }
    return node;
  }

  const loaded = {};
  function load(url) {
    if (!loaded[url]) {
      loaded[url] = fetch(url).then(async (response) => {
        if (!response.ok) throw new Error(await response.text());
        return response.json();
      });
      loaded[url].catch(() => { delete loaded[url]; });
    }
    return loaded[url];
  }

  /* `RulesDocument.search`, and the Charter's own numbers: a coach may
     type "Law 12" or "6.4" and be taken there. */
  async function search(query, charter) {
    const number = /^\s*(?:law\s*)?(\d+(?:\.\d+)?)\s*$/i.exec(query);
    if (number && charter) {
      for (const law of charter.laws) {
        for (const one of [law, ...law.sections]) {
          if (one.number === number[1]) return [{ slug: one.slug, number: one.number, label: one.title, html: true }];
        }
      }
    }
    const response = await fetch(`/api/rules?q=${encodeURIComponent(query)}`);
    if (!response.ok) throw new Error(await response.text());
    return (await response.json()).sections;
  }

  function resultList(found, onOpen) {
    if (!found.length) return [h("li", { class: "quiet" }, "Nothing in the rules says that.")];
    return found.map((one) =>
      h("li", {},
        h("a", {
          href: `/rules#${one.slug}`,
          class: "rules-hit",
          onclick: (event) => { event.preventDefault(); onOpen(one.slug); },
        },
        one.number ? h("span", { class: "rules-number" }, one.number) : null,
        one.html ? h("span", { html: one.label }) : h("span", {}, one.label))));
  }

  /* A search box over the rules, typed into as it goes. */
  function attachSearch(input, list, onOpen, charterOf) {
    let asked = 0;
    let timer = null;
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
        found = await search(query, charterOf());
      } catch (error) {
        if (mine !== asked) return;
        list.replaceChildren(h("li", { class: "quiet" }, "The rules could not be read."));
        list.hidden = false;
        return;
      }
      if (mine !== asked) return;
      list.replaceChildren(...resultList(found, (slug) => {
        input.value = "";
        list.hidden = true;
        onOpen(slug);
      }));
      list.hidden = false;
    }
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(ask, 200);
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        clearTimeout(timer);
        ask();
      } else if (event.key === "Escape") {
        input.value = "";
        list.hidden = true;
      }
    });
  }

  /* A link inside the rules text, to a heading: opened where the
     reader is rather than followed. */
  function ruleLink(event) {
    const link = event.target.closest("a[data-rule], a[href^='#']");
    if (!link) return null;
    const slug = link.dataset.rule || link.getAttribute("href").slice(1);
    return slug || null;
  }

  // -- The References ----------------------------------------------------

  /* The maneuvers table, the roles table and the species table -- the
     same three the Reading Room's right column sets. */
  function references(aids) {
    if (!aids) return [h("p", { class: "quiet" }, "The references are read once the room is.")];
    const maneuvers = (aids.maneuver_rows || []).map((table) =>
      h("table", { class: "ref-table maneuver-table" },
        h("tr", {}, h("th", {}, "Die"), h("th", {}, table.name), h("th", {}, "Beats"), h("th", {}, "Effect")),
        table.rows.map((one) =>
          h("tr", {},
            h("td", { class: "num die" }, one.dice),
            h("td", {},
              h("span", { class: "ability-name" }, one.name),
              one.gambit ? h("span", { class: "tier-tag" }, "Gambit") : null,
              h("span", { class: "maneuver-time" }, one.time)),
            h("td", { class: "beats" }, one.beats),
            h("td", { class: "ability" }, one.effect)))));
    const roles = h("table", { class: "ref-table" },
      h("tr", {}, h("th", {}), h("th", {}, "Role"), h("th", {}, "OFF"), h("th", {}, "DEF"), h("th", {}, "Ability")),
      (aids.role_rows || []).map((one) =>
        h("tr", {},
          h("td", {}, h("img", { class: "emoji", src: one.badge, alt: one.letters })),
          h("td", {}, one.name),
          h("td", { class: "num" }, String(one.offense)),
          h("td", { class: "num" }, String(one.defense)),
          h("td", { class: "ability" }, one.ability))));
    const species = (aids.species_rows || []).length
      ? h("table", { class: "ref-table" },
        h("tr", {}, h("th", {}), h("th", {}, "Species"), h("th", {}, "Ability")),
        aids.species_rows.map((one) =>
          h("tr", {},
            h("td", {}, h("img", { class: "emoji", src: one.icon, alt: "" })),
            h("td", {},
              h("span", { class: "species-team", style: `color: ${one.colour}` }, one.team),
              h("span", { class: "ability-name" }, one.name)),
            h("td", { class: "ability" }, one.ability))))
      : null;
    return [
      h("div", { class: "panel-label" }, "Maneuvers"),
      ...maneuvers,
      h("div", { class: "panel-label" }, "Roles"),
      roles,
      species ? h("div", { class: "panel-label" }, "Species") : null,
      species,
    ];
  }

  // -- The Learn to Play -------------------------------------------------

  function learnView(book, onOpen) {
    const body = h("div", { class: "learn rules", html: book.html });
    const contents = h("nav", { class: "learn-contents", "aria-label": "Chapters" },
      book.contents.map((one) =>
        h("button", {
          type: "button",
          class: "chip-tab small",
          onclick: () => {
            const target = body.querySelector(`[id="${CSS.escape(one.slug)}"]`);
            if (target) target.scrollIntoView({ block: "start", behavior: "smooth" });
          },
          html: one.title,
        })));
    body.addEventListener("click", (event) => {
      const link = event.target.closest("a[data-rule]");
      if (!link) return;
      event.preventDefault();
      onOpen(link.dataset.rule);
    });
    return [h("h2", { class: "learn-title", html: book.title }), contents, body];
  }

  // -- The Rules tab -------------------------------------------------------

  /* The tab: a search box, three chips, and under them the Laws by
     their headings -- one opened to its text -- the Learn to Play, or
     the References. */
  function mountTab(root) {
    let view = "charter";
    let charter = null;
    let aids = null;
    let openLaw = null;
    let flash = null;

    const input = h("input", {
      type: "search",
      class: "search-input",
      placeholder: "Search the Charter: High Pass, own goal, Law 12…",
      "aria-label": "Search the Charter",
      autocomplete: "off",
    });
    const hits = h("ol", { class: "rules-results", hidden: true });
    const chips = h("div", { class: "chips" });
    const body = h("div", { class: "rules-body" });
    root.replaceChildren(
      h("div", { class: "rules-search" }, input, hits),
      chips,
      body,
    );
    attachSearch(input, hits, (slug) => open(slug), () => charter);
    body.addEventListener("click", (event) => {
      if (view !== "charter") return;
      const slug = ruleLink(event);
      if (!slug) return;
      event.preventDefault();
      open(slug);
    });

    function drawChips() {
      chips.replaceChildren(
        ...[["charter", "The Charter"], ["learn", "Learn to Play"], ["references", "References"]].map(([name, words]) =>
          h("button", {
            type: "button",
            class: `chip-tab${view === name ? " current" : ""}`,
            "aria-pressed": view === name ? "true" : "false",
            onclick: () => { view = name; draw(); },
          }, words)),
        h("a", { class: "reading-link", href: "/rules", target: "_blank", rel: "noopener" }, "The Reading Room ↗"),
      );
    }

    function lawEntry(law) {
      const opened = openLaw === law.slug;
      const head = h("button", {
        type: "button",
        class: `law-row${opened ? " open" : ""}`,
        "aria-expanded": opened ? "true" : "false",
        onclick: () => {
          openLaw = opened ? null : law.slug;
          draw();
          if (!opened) scrollTo(law.slug);
        },
      },
      h("span", { class: "toc-number" }, law.number || ""),
      h("span", { html: law.title }));
      if (!opened) return [head];
      const names = law.sections.length
        ? h("div", { class: "law-sections" },
          law.sections.flatMap((one, index) => [
            index ? " · " : null,
            h("a", { href: `#${one.slug}`, "data-rule": one.slug, html: one.title }),
          ]))
        : null;
      const text = h("div", { class: "law-text rules", id: `r-${law.slug}` },
        law.part ? h("div", { class: "law-part", html: law.part }) : null,
        names,
        h("div", { html: law.html }),
        law.sections.map((one) =>
          h("section", { class: "rules-section", id: `r-${one.slug}` },
            h("h4", {},
              one.number ? h("span", { class: "rules-number" }, one.number) : null,
              h("span", { html: one.title })),
            h("div", { html: one.html }))));
      return [head, text];
    }

    function scrollTo(slug) {
      requestAnimationFrame(() => {
        const target = body.querySelector(`[id="r-${CSS.escape(slug)}"]`);
        if (!target) return;
        target.scrollIntoView({ block: "start", behavior: "smooth" });
        if (flash) flash.classList.remove("flash");
        target.classList.add("flash");
        flash = target;
      });
    }

    async function draw() {
      drawChips();
      if (view === "references") {
        body.replaceChildren(h("div", { class: "references" }, references(aids)));
        return;
      }
      if (view === "learn") {
        body.replaceChildren(h("p", { class: "quiet" }, "Opening the Learn to Play…"));
        try {
          const book = await load("/api/rules/learn");
          if (view === "learn") body.replaceChildren(...learnView(book, open));
        } catch (error) {
          if (view === "learn") body.replaceChildren(h("p", { class: "quiet" }, "The Learn to Play could not be read."));
        }
        return;
      }
      if (!charter) {
        body.replaceChildren(h("p", { class: "quiet" }, "Opening the Charter…"));
        try {
          charter = await load("/api/rules/charter");
        } catch (error) {
          body.replaceChildren(h("p", { class: "quiet" }, "The rules could not be read."));
          return;
        }
        if (view !== "charter") return;
      }
      body.replaceChildren(
        h("div", { class: "law-list" },
          charter.laws.flatMap(lawEntry),
          charter.appendices.length ? h("div", { class: "panel-label appendices" }, "Appendices") : null,
          charter.appendices.flatMap(lawEntry)),
      );
    }

    /* Open the Law a slug is in -- a Law, a section, or a heading
       under one -- at that heading. */
    async function open(slug) {
      view = "charter";
      if (!charter) {
        try { charter = await load("/api/rules/charter"); } catch (error) { draw(); return; }
      }
      for (const law of [...charter.laws, ...charter.appendices, ...charter.front]) {
        const inside = law.slug === slug
          || law.sections.some((one) => one.slug === slug || one.html.includes(`id="${slug}"`))
          || law.html.includes(`id="${slug}"`);
        if (inside) {
          openLaw = law.slug;
          break;
        }
      }
      await draw();
      const section = charter
        && [...charter.laws, ...charter.appendices].flatMap((law) => law.sections)
          .find((one) => one.slug === slug || one.html.includes(`id="${slug}"`));
      scrollTo(section ? section.slug : openLaw || slug);
    }

    draw();
    return {
      open,
      /* The room's references, as its state carries them: redrawn only
         when they change and the tab is showing them. */
      setAids(next) {
        const changed = JSON.stringify(next) !== JSON.stringify(aids);
        aids = next;
        if (changed && view === "references") draw();
      },
    };
  }

  // -- The Reading Room ----------------------------------------------------

  function mountRoom() {
    const page = document.body;
    const text = document.querySelector(".reading-text");
    const views = {};
    for (const node of document.querySelectorAll(".reading-view")) views[node.dataset.for] = node;
    let team = 0;
    let face = 0;
    let everything = null;

    function show(view) {
      if (view === "references") {
        page.dataset.view = "references";
        document.getElementById("references").scrollIntoView({ block: "start", behavior: "smooth" });
      } else {
        page.dataset.view = view;
        for (const [name, node] of Object.entries(views)) node.hidden = name !== view;
      }
      for (const chip of document.querySelectorAll(".chip-tab[data-view]")) {
        chip.classList.toggle("current", chip.dataset.view === page.dataset.view);
      }
      if (view === "learn" && !views.learn.dataset.drawn) drawLearn();
      if (view === "rosters" && !views.rosters.dataset.drawn) drawRosters();
    }

    function toRule(slug) {
      show("charter");
      const target = document.getElementById(slug);
      if (target) {
        target.scrollIntoView({ block: "start" });
        history.replaceState(null, "", `#${slug}`);
        mark(slug);
      }
    }

    async function drawLearn() {
      views.learn.replaceChildren(h("p", { class: "quiet" }, "Opening the Learn to Play…"));
      try {
        const book = await load("/api/rules/learn");
        views.learn.replaceChildren(...learnView(book, toRule));
        views.learn.dataset.drawn = "1";
      } catch (error) {
        views.learn.replaceChildren(h("p", { class: "quiet" }, "The Learn to Play could not be read."));
      }
    }

    /* Every team's cards, a tab a team and a tab a face, the faces the
       Reading Room offers with no game to ask (`/api/aids`). */
    async function drawRosters() {
      if (!everything) {
        try {
          everything = await load("/api/aids");
        } catch (error) {
          views.rosters.replaceChildren(h("p", { class: "quiet" }, "The rosters could not be read."));
          return;
        }
      }
      const teams = everything.teams;
      const chosen = teams[team];
      views.rosters.replaceChildren(
        h("h2", {}, "Rosters"),
        h("div", { class: "chips" },
          teams.map((one, index) =>
            h("button", {
              type: "button",
              class: `chip-tab${index === team ? " current" : ""}`,
              style: `border-color: ${one.colour}`,
              onclick: () => { team = index; face = 0; drawRosters(); },
            }, one.name))),
        h("div", { class: "chips" },
          chosen.faces.map((one, index) =>
            h("button", {
              type: "button",
              class: `chip-tab small${index === face ? " current" : ""}`,
              onclick: () => { face = index; drawRosters(); },
            }, one.name))),
        h("div", { class: "roster-cards" },
          chosen.faces[face].cards.map((url) =>
            h("a", { href: url, target: "_blank", rel: "noopener" },
              h("img", { src: url, alt: "A player card", loading: "lazy" })))),
      );
      views.rosters.dataset.drawn = "1";
    }

    /* The Law being read, lit in the contents. */
    function mark(slug) {
      const law = document.getElementById(slug);
      const article = law && law.closest(".law");
      for (const link of document.querySelectorAll(".reading-contents a")) {
        link.classList.toggle("current", Boolean(article) && link.dataset.rule === article.id);
      }
    }

    for (const chip of document.querySelectorAll(".chip-tab[data-view]")) {
      chip.addEventListener("click", () => show(chip.dataset.view));
    }
    text.addEventListener("click", (event) => {
      if (page.dataset.view !== "charter") return;
      const slug = ruleLink(event);
      if (!slug) return;
      event.preventDefault();
      toRule(slug);
    });
    for (const link of document.querySelectorAll(".reading-contents a")) {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        toRule(link.dataset.rule);
      });
    }
    const form = document.querySelector("[data-rules-search]");
    if (form) {
      form.addEventListener("submit", (event) => event.preventDefault());
      attachSearch(form.querySelector("input"), form.querySelector(".rules-results"), toRule, () => null);
    }
    if ("IntersectionObserver" in window) {
      const seen = new IntersectionObserver((records) => {
        for (const record of records) {
          if (record.isIntersecting) mark(record.target.id);
        }
      }, { root: text, rootMargin: "0px 0px -70% 0px" });
      for (const law of document.querySelectorAll(".law")) seen.observe(law);
    }
    /* A room's back link: back to where the reader came from. */
    const back = document.querySelector("[data-back]");
    if (back && document.referrer && new URL(document.referrer).origin === location.origin) {
      back.href = document.referrer;
      back.textContent = "‹ Back";
    }
    show("charter");
    if (location.hash) toRule(decodeURIComponent(location.hash.slice(1)));
  }

  window.D12Rules = { mountTab };

  if (document.body.classList.contains("reading-room")) mountRoom();
})();
