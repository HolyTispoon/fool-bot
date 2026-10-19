// The board's viewer (docs/pbd-site.md, decision 6): zoom and pan by hand,
// with pointer events and a CSS transform. The wheel and a pinch zoom toward
// the pointer, a drag pans, a double click or a double tap switches between
// fit and full size, and the buttons zoom and fit. A new board keeps the
// viewer's zoom and position, so somebody zoomed into their patrol zone
// stays there while the opponent plays.
"use strict";

class BoardViewer {
  constructor(frame, image) {
    this.frame = frame;
    this.image = image;
    this.scale = 1;
    this.x = 0;
    this.y = 0;
    // Fitted until the viewer zooms or pans: then a resize refits, and a
    // new board of another size is fitted too.
    this.fitted = true;
    this.pointers = new Map();
    this.lastTap = null;
    this.wanted = null;
    // Where a mouse is over the frame, in the window's coordinates, or null:
    // what Space shows a card under (codex.js, GamePage.peek).
    this.hover = null;

    image.style.transformOrigin = "0 0";
    image.addEventListener("load", () => this.loaded());
    frame.addEventListener("wheel", (event) => this.wheel(event), { passive: false });
    frame.addEventListener("pointerdown", (event) => this.down(event));
    frame.addEventListener("pointermove", (event) => this.move(event));
    frame.addEventListener("pointerup", (event) => this.up(event));
    frame.addEventListener("pointercancel", (event) => this.up(event));
    frame.addEventListener("pointerleave", () => { this.hover = null; });
    // A double click on a zoom button is two zooms, never fit and full size.
    frame.addEventListener("dblclick", (event) => {
      if (event.target.closest("button")) return;
      this.toggle(this.point(event));
    });
    frame.addEventListener("keydown", (event) => this.key(event));
    new ResizeObserver(() => this.resized()).observe(frame);
  }

  // The board to show. The picture is loaded off screen first and swapped in
  // whole, so the viewer never shows half a board or a blank.
  show(src) {
    if (!src || src === this.wanted) return;
    this.wanted = src;
    const next = new Image();
    next.onload = () => {
      if (this.wanted !== src) return;
      // A board grows and shrinks in height with what is on the table, so
      // only a new width -- Swap view between stacked and side by side --
      // is a new picture to fit.
      this.keep = next.naturalWidth === this.image.naturalWidth && !this.fitted;
      this.image.src = src;
    };
    // A board that did not load is asked for again on the next poll.
    next.onerror = () => { if (this.wanted === src) this.wanted = null; };
    next.src = src;
  }

  loaded() {
    // A narrow screen sizes the frame to the board (codex.css).
    this.frame.style.setProperty("--board-aspect", `${this.image.naturalWidth} / ${this.image.naturalHeight}`);
    if (this.keep) this.clamp();
    else this.fit();
    this.keep = false;
    this.draw();
  }

  get ready() {
    return this.image.naturalWidth > 0;
  }

  fitScale() {
    if (!this.ready) return 1;
    return Math.min(this.frame.clientWidth / this.image.naturalWidth,
                    this.frame.clientHeight / this.image.naturalHeight);
  }

  // The picture's own pixels are the limit: sharp to about full size, so
  // twice that is as far as it goes, and out to the smaller of fit and full.
  limits() {
    const fit = this.fitScale();
    return [Math.min(fit, 1), Math.max(fit, 2)];
  }

  fit() {
    this.scale = this.fitScale();
    this.fitted = true;
    this.clamp();
  }

  resized() {
    if (this.fitted) this.fit();
    else this.clamp();
    this.draw();
  }

  // A point on the frame, from an event.
  point(event) {
    const box = this.frame.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }

  centre() {
    return { x: this.frame.clientWidth / 2, y: this.frame.clientHeight / 2 };
  }

  // A point in the window, as the board's own pixels: where it falls on the
  // picture as it is zoomed and panned now.
  boardPoint(at) {
    if (!this.ready) return null;
    const box = this.frame.getBoundingClientRect();
    return { x: (at.x - box.left - this.x) / this.scale, y: (at.y - box.top - this.y) / this.scale };
  }

  // Zoom to `scale`, keeping the board's point under `at` where it is.
  zoomTo(scale, at) {
    if (!this.ready) return;
    const [least, most] = this.limits();
    const next = Math.min(most, Math.max(least, scale));
    this.x = at.x - (at.x - this.x) * (next / this.scale);
    this.y = at.y - (at.y - this.y) * (next / this.scale);
    this.scale = next;
    this.fitted = false;
    this.clamp();
    this.draw();
  }

  zoomBy(factor, at = this.centre()) {
    this.zoomTo(this.scale * factor, at);
  }

  // Fit and full size, one from the other, about the point clicked.
  toggle(at) {
    if (!this.ready) return;
    if (this.fitted || Math.abs(this.scale - this.fitScale()) < 0.01) {
      this.zoomTo(1, at);
    } else {
      this.fit();
      this.draw();
    }
  }

  // A board narrower than the frame sits in its middle; a wider one may not
  // be dragged past its own edge.
  clamp() {
    if (!this.ready) return;
    const width = this.image.naturalWidth * this.scale;
    const height = this.image.naturalHeight * this.scale;
    const frameWidth = this.frame.clientWidth;
    const frameHeight = this.frame.clientHeight;
    this.x = width <= frameWidth ? (frameWidth - width) / 2
      : Math.min(0, Math.max(frameWidth - width, this.x));
    this.y = height <= frameHeight ? (frameHeight - height) / 2
      : Math.min(0, Math.max(frameHeight - height, this.y));
  }

  draw() {
    this.image.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.scale})`;
    this.frame.classList.toggle("zoomed", !this.fitted);
  }

  wheel(event) {
    event.preventDefault();
    // A trackpad's pinch arrives as a wheel with ctrlKey and small steps.
    const step = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
    this.zoomBy(Math.exp(-step * (event.ctrlKey ? 0.01 : 0.002)), this.point(event));
  }

  down(event) {
    if (event.target.closest("button")) return;
    this.frame.setPointerCapture(event.pointerId);
    this.pointers.set(event.pointerId, this.point(event));
    this.moved = false;
    this.pinch = null;
  }

  move(event) {
    if (event.pointerType === "mouse") this.hover = { x: event.clientX, y: event.clientY };
    const before = this.pointers.get(event.pointerId);
    if (!before) return;
    const now = this.point(event);
    this.pointers.set(event.pointerId, now);
    if (this.pointers.size === 2) {
      const [one, two] = [...this.pointers.values()];
      const distance = Math.hypot(one.x - two.x, one.y - two.y);
      const middle = { x: (one.x + two.x) / 2, y: (one.y + two.y) / 2 };
      if (this.pinch) {
        this.x += middle.x - this.pinch.middle.x;
        this.y += middle.y - this.pinch.middle.y;
        this.zoomTo(this.scale * distance / this.pinch.distance, middle);
      }
      this.pinch = { distance, middle };
      this.moved = true;
      return;
    }
    if (this.pointers.size !== 1) return;
    const dx = now.x - before.x;
    const dy = now.y - before.y;
    if (!this.moved && Math.hypot(dx, dy) < 2) {
      this.pointers.set(event.pointerId, before);
      return;
    }
    this.moved = true;
    this.x += dx;
    this.y += dy;
    this.fitted = false;
    this.clamp();
    this.draw();
  }

  up(event) {
    if (!this.pointers.has(event.pointerId)) return;
    this.pointers.delete(event.pointerId);
    this.pinch = null;
    // A mouse has dblclick; a finger's double tap is counted here.
    if (event.type !== "pointerup" || event.pointerType === "mouse" || this.moved) return;
    const at = this.point(event);
    const tap = this.lastTap;
    if (tap && event.timeStamp - tap.time < 350 && Math.hypot(at.x - tap.x, at.y - tap.y) < 30) {
      this.lastTap = null;
      this.toggle(at);
    } else {
      this.lastTap = { x: at.x, y: at.y, time: event.timeStamp };
    }
  }

  key(event) {
    if (event.key === "+" || event.key === "=") this.zoomBy(1.25);
    else if (event.key === "-") this.zoomBy(0.8);
    else if (event.key === "0") { this.fit(); this.draw(); }
    else return;
    event.preventDefault();
  }
}

window.BoardViewer = BoardViewer;
