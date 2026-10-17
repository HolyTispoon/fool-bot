// The board viewer (docs/pbd-site.md, decision 6): the wheel and a
// pinch zoom toward the pointer, a drag pans, a double click or a double
// tap switches between fit and full size, and Fit resets. A new board
// swaps in under the viewer's zoom and position, so somebody zoomed into
// their patrol zone stays there while the opponent plays. Plain pointer
// events and a CSS transform, no library.
"use strict";

class Viewer {
  constructor(frame, image) {
    this.frame = frame;
    this.image = image;
    this.scale = 1;
    this.x = 0;
    this.y = 0;
    // Until somebody zooms or pans, the board follows the window's size.
    this.fitted = true;
    this.pointers = new Map();
    this.lastTap = null;
    this.loading = null;
    this.pressed = null;

    frame.addEventListener("wheel", (event) => this.wheel(event), { passive: false });
    frame.addEventListener("pointerdown", (event) => this.down(event));
    frame.addEventListener("pointermove", (event) => this.move(event));
    frame.addEventListener("pointerup", (event) => this.up(event));
    frame.addEventListener("pointercancel", (event) => this.up(event));
    frame.addEventListener("dblclick", (event) => this.toggle(this.point(event)));
    image.addEventListener("dragstart", (event) => event.preventDefault());
    new ResizeObserver(() => (this.fitted ? this.fit() : this.place())).observe(frame);
  }

  get width() { return this.image.naturalWidth || 1; }
  get height() { return this.image.naturalHeight || 1; }

  fitScale() {
    return Math.min(this.frame.clientWidth / this.width, this.frame.clientHeight / this.height);
  }

  // Full size is the picture's own pixels, which is as sharp as it gets;
  // a little past it is allowed, and never smaller than half of fit.
  limits() {
    const fit = this.fitScale();
    return [Math.min(fit, 1) / 2, Math.max(fit, 1) * 2];
  }

  // Where an event is, in the frame's own pixels.
  point(event) {
    const box = this.frame.getBoundingClientRect();
    return { x: event.clientX - box.left, y: event.clientY - box.top };
  }

  // Show `src`. The new picture is loaded before it replaces the old
  // one, so nothing flashes, and the zoom and position are kept.
  show(src) {
    if (this.image.getAttribute("src") === src) return Promise.resolve();
    const next = new Image();
    next.src = src;
    this.loading = src;
    return next.decode().catch(() => {}).then(() => {
      if (this.loading !== src) return;
      const first = !this.image.naturalWidth;
      this.image.src = src;
      // The board's shape, for a layout that sizes the frame to it
      // (the phone's, in codex.css).
      this.frame.style.setProperty("--board-ratio", String(next.naturalWidth / next.naturalHeight || 1));
      if (first || this.fitted) this.fit();
      else this.place();
    });
  }

  fit() {
    this.fitted = true;
    this.scale = this.fitScale();
    this.x = (this.frame.clientWidth - this.width * this.scale) / 2;
    this.y = (this.frame.clientHeight - this.height * this.scale) / 2;
    this.draw();
  }

  // Zoom by `factor` about `at`, a point in the frame.
  zoom(factor, at) {
    const [low, high] = this.limits();
    const scale = Math.min(high, Math.max(low, this.scale * factor));
    at = at || { x: this.frame.clientWidth / 2, y: this.frame.clientHeight / 2 };
    this.x = at.x - (at.x - this.x) * (scale / this.scale);
    this.y = at.y - (at.y - this.y) * (scale / this.scale);
    this.scale = scale;
    this.fitted = false;
    this.place();
  }

  // Between fit and full size, about the point clicked.
  toggle(at) {
    if (Math.abs(this.scale - 1) < 0.01 && Math.abs(this.fitScale() - 1) >= 0.01) this.fit();
    else this.zoom(1 / this.scale, at);
  }

  // Keep the board in the frame: centred along an axis it does not
  // fill, and with no gap at an edge along one it does.
  place() {
    const spare = (size, extent, at) =>
      extent <= size ? (size - extent) / 2 : Math.min(0, Math.max(size - extent, at));
    this.x = spare(this.frame.clientWidth, this.width * this.scale, this.x);
    this.y = spare(this.frame.clientHeight, this.height * this.scale, this.y);
    this.draw();
  }

  draw() {
    this.image.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.scale})`;
  }

  wheel(event) {
    event.preventDefault();
    const step = event.deltaMode === 1 ? event.deltaY * 16 : event.deltaY;
    this.zoom(Math.exp(-step * 0.0015), this.point(event));
  }

  down(event) {
    this.frame.setPointerCapture(event.pointerId);
    this.pointers.set(event.pointerId, this.point(event));
    this.pressed = this.pointers.size === 1 ? this.point(event) : null;
  }

  move(event) {
    const before = this.pointers.get(event.pointerId);
    if (!before) return;
    const now = this.point(event);
    if (this.pointers.size === 1) {
      this.x += now.x - before.x;
      this.y += now.y - before.y;
      this.fitted = false;
      this.place();
    } else if (this.pointers.size === 2) {
      const other = [...this.pointers].find(([id]) => id !== event.pointerId)[1];
      const apart = (a, b) => Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const middle = { x: (now.x + other.x) / 2, y: (now.y + other.y) / 2 };
      this.x += middle.x - (before.x + other.x) / 2;
      this.y += middle.y - (before.y + other.y) / 2;
      this.zoom(apart(now, other) / apart(before, other), middle);
    }
    this.pointers.set(event.pointerId, now);
  }

  up(event) {
    if (!this.pointers.delete(event.pointerId)) return;
    // A double tap: dblclick does not reach a frame whose touches are
    // its own (touch-action: none).
    if (event.type !== "pointerup" || event.pointerType !== "touch" || this.pointers.size) return;
    const at = this.point(event);
    // A drag is not a tap.
    if (!this.pressed || Math.hypot(at.x - this.pressed.x, at.y - this.pressed.y) > 10) return;
    const last = this.lastTap;
    if (last && event.timeStamp - last.time < 300 && Math.hypot(at.x - last.x, at.y - last.y) < 30) {
      this.lastTap = null;
      this.toggle(at);
    } else {
      this.lastTap = { ...at, time: event.timeStamp };
    }
  }
}

window.Viewer = Viewer;
