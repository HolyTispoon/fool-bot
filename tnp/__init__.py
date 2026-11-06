"""
The New Project (TNP): the model.

Held to the model's rules from its first commit (docs/tnp-bot.md,
decision 3): no `discord`, no `async def`, and Pillow only in
`tnp/render.py`. Step 1 gives the data and the
readings over it: `catalog` (the units, facilities, upgrades, techs and
the map, keyed by slug), `formatting` (the reference text `/tnp unit`
posts) and `rules_doc` (docs/tnp-rules.md by section). Step 2 gives the
battle (TNP 6): `engine` (the catalog and `rng`), `battle` (the saved
state and its readings), `components` (`MatchState`), `prompts`
(`pending`, the one reading), `flow` (the steps and `driver.apply`),
`tokens`, `wire` and `game` (`RuleRefusal`). Step 3 gives the pictures:
`briefs` (what the map and a board are drawn from, filtered for whoever
sees them) and `render` (the map, a seat's board and the battle). See
docs/design/tnp.md.
"""
