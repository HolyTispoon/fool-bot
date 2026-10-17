// The site's one Function (docs/pbd-site.md, decision 1;
// docs/design/pbd-site.md, "The page"): GET /data/<key> answers the
// object <key> from the private R2 bucket bound as PBD -- the whole key,
// "codex/" and all, as the JSON hands it to the page. It reads and never
// writes, never lists, and answers only the keys the bucket's layout
// names -- anything else is a 404, so the bucket cannot be walked from
// the web.

// The bucket's layout (cogs/codex_publish/keys.py writes them). One
// pattern a line, plain enough that tests/test_pbd_site.py and
// scripts/serve_pbd.py compile these same lines as Python regexes, so
// the three cannot drift.
// KEYS BEGIN
const KEYS = [
  /^codex\/index\.json$/,
  /^codex\/archive\.json$/,
  /^codex\/games\/[0-9a-f]{32}\/live\.json$/,
  /^codex\/games\/[0-9a-f]{32}\/history\.json$/,
  /^codex\/games\/[0-9a-f]{32}\/board-[0-9a-f]{64}\.webp$/,
  /^codex\/emoji\/[A-Za-z0-9_]+\.png$/,
];
// KEYS END

function answer(status, extra = {}) {
  // Unlisted, not private: JSON and pictures carry no meta tag, so
  // every answer says noindex in a header (decision 2).
  return new Response(null, { status, headers: { "X-Robots-Tag": "noindex", ...extra } });
}

export async function onRequest({ request, env, params }) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return answer(405, { Allow: "GET, HEAD" });
  }
  const key = Array.isArray(params.path) ? params.path.join("/") : params.path || "";
  if (!KEYS.some((pattern) => pattern.test(key))) {
    return answer(404);
  }
  const object = await env.PBD.get(key, { onlyIf: request.headers });
  if (object === null) {
    return answer(404);
  }
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("ETag", object.httpEtag);
  headers.set("X-Robots-Tag", "noindex");
  // A failed precondition hands back the object without its body: the
  // page's If-None-Match matched, so the copy it holds is current.
  if (!("body" in object)) {
    return new Response(null, { status: 304, headers });
  }
  return new Response(request.method === "HEAD" ? null : object.body, { headers });
}
