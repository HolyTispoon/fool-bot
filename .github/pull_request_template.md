<!--
Write the body as prose. The reviewer is the other developer, and what they
need is the reasoning the diff cannot show them: why this shape and not the
obvious one, what it costs, what it deliberately leaves alone.

Delete any heading below that has nothing to say. Keep the checklist.
-->

## What this changes

<!--
One or two paragraphs. Lead with the problem, not the patch.
-->

## Why it is built this way

<!--
The decisions worth arguing about, and the ones already settled so nobody
re-opens them in review: what was tried and dropped, what is deliberate
rather than incidental, what a later change must not undo.

Rules questions go to the author as inline comments on the diff rather than
in this body — they get answered where they can be versioned.
-->

## Testing

<!--
`python3 -m unittest discover -s tests` — say how many pass, and list the new
coverage. Say what you checked by hand, and what you did not.
-->

---

- [ ] `python3 -m unittest discover -s tests` passes
- [ ] **Rules change?** `docs/living-rules.md` and a dated `docs/rules-log.md`
      entry are in their own commit, so the rules move as a reviewable diff.
- [ ] **Architecture change?** CLAUDE.md updated in the same commit — a new
      module, a responsibility moving, a new persisted field, a new
      environment variable. Record the reasoning, not just the fact.
- [ ] **Board image change?** A sample rendered and looked at
      (`python3 scripts/render_sample.py`). The suite only asserts a PNG of
      the right dimensions, so it cannot see this.
- [ ] **New persisted field, or a renamed key?** A game saved before this
      change still loads — both of us run the bot from our own tree against
      our own saves, and a half-finished game outlives the change.
- [ ] **More Discord requests per click?** Say how many, and which bucket.
      Fewer requests, never slower ones — see "Discord's rate limits".
- [ ] No runtime state (`data/`) and no one-off diagnostic scripts in the diff.
