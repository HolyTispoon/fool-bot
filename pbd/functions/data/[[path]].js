// The site's one Pages Function (docs/design/pbd-site.md, "The Function"):
// GET /data/<key> answers the bucket's object at <key>, read through the R2
// binding PBD. It never writes and never lists, and it answers only the keys
// the bucket's layout names -- every other address is a 404, so the bucket
// cannot be walked from the web.
//
// The patterns are the one other place a key's shape is written besides
// cogs/codex_publish/keys.py; tests/test_pbd_site.py reads them out of this
// file as Python regexes and holds the two together. Keep each one a plain
// regex literal on a line of its own.
const KEYS = [
  /^codex\/index\.json$/,
  /^codex\/archive\.json$/,
  /^codex\/games\/[0-9a-f]{32}\/live\.json$/,
  /^codex\/games\/[0-9a-f]{32}\/history\.json$/,
  /^codex\/games\/[0-9a-f]{32}\/board-[0-9a-f]{64}\.webp$/,
  /^codex\/games\/[0-9a-f]{32}\/board-[0-9a-f]{64}\.json$/,
  /^codex\/emoji\/[A-Za-z0-9_]+\.png$/,
  /^codex\/cards\/[a-z0-9_]+\.(?:jpg|png)$/,
];

const PREFIX = "/data/";

// JSON and pictures carry no <meta> tag, so the noindex rides on every answer
// (docs/pbd-site.md, decision 2).
function answer(body, status, headers = new Headers()) {
  headers.set("X-Robots-Tag", "noindex");
  return new Response(body, { status, headers });
}

export async function onRequest({ request, env }) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return answer(null, 405, new Headers({ Allow: "GET, HEAD" }));
  }
  // The key is the address after /data/, as written: the patterns allow no
  // character a browser would encode, so nothing is decoded first.
  const key = new URL(request.url).pathname.slice(PREFIX.length);
  if (!KEYS.some((pattern) => pattern.test(key))) {
    return answer("Not found", 404);
  }
  const object = request.method === "HEAD"
    ? await env.PBD.head(key)
    : await env.PBD.get(key, { onlyIf: request.headers });
  if (object === null) {
    return answer("Not found", 404);
  }
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("ETag", object.httpEtag);
  if (request.method === "HEAD") {
    return answer(null, 200, headers);
  }
  // A get whose precondition failed hands back the object without a body:
  // an If-None-Match that matched, which the page's polls send.
  if (!("body" in object)) {
    return answer(null, request.headers.has("If-None-Match") ? 304 : 412, headers);
  }
  return answer(object.body, 200, headers);
}
