// A card's picture, or a codex of them, floating beside the pointer
// (docs/design/pbd-site.md, "Showing a card"): a card named in the log on
// hover, and on the board whatever the board's map says is under the pointer
// when Space is pressed. Built with textContent and image sources alone, like
// every line, so a name is never markup.
"use strict";

// How far from the pointer the preview sits, and how close to the window's
// edge it may come.
const PREVIEW_OFFSET = 18;
const PREVIEW_MARGIN = 8;

class CardPreview {
  constructor(data) {
    this.data = data;
    this.node = document.createElement("div");
    this.node.className = "card-preview";
    this.node.hidden = true;
    this.node.setAttribute("role", "tooltip");
    document.body.append(this.node);
    // What is shown, so the same thing asked for again is not rebuilt.
    this.showing = null;
  }

  // `cards`, each {slug, name, key}; `title`, a codex's heading or null;
  // `at`, the pointer in the window's coordinates. A card with no picture
  // is its name.
  show(cards, title, at, what = cards) {
    if (this.showing !== what) {
      this.showing = what;
      const parts = [];
      if (title) {
        const heading = document.createElement("p");
        heading.className = "card-preview-title";
        heading.textContent = title;
        parts.push(heading);
      }
      const grid = document.createElement("div");
      grid.className = cards.length > 1 ? "card-preview-grid" : "card-preview-one";
      for (const card of cards) grid.append(this.face(card));
      parts.push(grid);
      this.node.replaceChildren(...parts);
      this.node.hidden = false;
    }
    this.place(at);
  }

  face(card) {
    if (!card.key) {
      const named = document.createElement("span");
      named.className = "card-preview-name";
      named.textContent = card.name;
      return named;
    }
    const picture = document.createElement("img");
    picture.alt = card.name;
    picture.src = this.data + card.key;
    picture.addEventListener("load", () => this.place(this.at), { once: true });
    picture.addEventListener("error", () => {
      const named = document.createElement("span");
      named.className = "card-preview-name";
      named.textContent = card.name;
      picture.replaceWith(named);
    }, { once: true });
    return picture;
  }

  // Beside the pointer, below and right of it where it fits, else on the
  // other side, and never past the window's edge.
  place(at) {
    if (!at || this.node.hidden) return;
    this.at = at;
    const width = this.node.offsetWidth;
    const height = this.node.offsetHeight;
    const room = { x: window.innerWidth, y: window.innerHeight };
    let x = at.x + PREVIEW_OFFSET;
    if (x + width > room.x - PREVIEW_MARGIN) x = at.x - PREVIEW_OFFSET - width;
    let y = at.y + PREVIEW_OFFSET;
    if (y + height > room.y - PREVIEW_MARGIN) y = at.y - PREVIEW_OFFSET - height;
    x = Math.max(PREVIEW_MARGIN, Math.min(x, room.x - PREVIEW_MARGIN - width));
    y = Math.max(PREVIEW_MARGIN, Math.min(y, room.y - PREVIEW_MARGIN - height));
    this.node.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }

  hide() {
    this.showing = null;
    this.node.hidden = true;
    this.node.replaceChildren();
  }
}

// The region of a board's map under a point of the board's own pixels: the
// last drawn, since a later box lies over an earlier one.
function regionAt(map, x, y) {
  if (!map || !map.regions) return null;
  for (let index = map.regions.length - 1; index >= 0; index -= 1) {
    const [left, top, right, bottom] = map.regions[index].box;
    if (x >= left && x < right && y >= top && y < bottom) return map.regions[index];
  }
  return null;
}

window.CardPreview = CardPreview;
window.regionAt = regionAt;
