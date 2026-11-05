"""
The New Project (TNP): the model.

Held to the model's rules from its first commit (docs/tnp-bot.md,
decision 3): no `discord`, no `async def`, and Pillow only in
`tnp/render.py`, once step 3 adds it. Step 1 gives the data and the
readings over it: `catalog` (the units, facilities, upgrades, techs and
the map, keyed by slug), `formatting` (the reference text `/tnp unit`
posts) and `rules_doc` (docs/tnp-rules.md by section). The game itself
begins in step 2. See docs/design/tnp.md.
"""
