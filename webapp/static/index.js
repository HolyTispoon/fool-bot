/*
 * The front door: a name (webapp/identity.py), then a room
 * (`POST /api/rooms`), then its page. Nothing about the game is here.
 */

const input = document.getElementById("name-input");
const error = document.getElementById("name-error");

function refuse(text) {
  error.textContent = text;
  error.hidden = false;
}

fetch("/api/me")
  .then((response) => (response.ok ? response.json() : null))
  .then((me) => { if (me) input.value = me.name; })
  .catch(() => {});

document.getElementById("open-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const named = await fetch("/api/me", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: input.value }),
    });
    if (!named.ok) return refuse(await named.text());
    const opened = await fetch("/api/rooms", { method: "POST" });
    if (!opened.ok) return refuse(await opened.text());
    location.href = (await opened.json()).url;
  } catch (failure) {
    refuse("That did not reach the server. Try again in a moment.");
  }
});
