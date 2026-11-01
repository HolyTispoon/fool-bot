# D12 Ball 2.0's two-headed maneuver cards, filed away

D12 Ball 2.0 dealt each coach eighteen cards: twelve two-headed basic
cards -- an offensive maneuver on the top half and a defensive one upside
down on the bottom, four a rank -- and the six advanced maneuvers. They
came from the sheet's `maneuvers 2.0` tab (gid 1310773351).

**2.1 replaced them on 2026-10-31** (the author): that tab was renamed
`maneuvers 2.1` and rewritten in place, as twenty-four single-faced cards
whose specials are role interactions, and no advanced maneuvers. The bot
reads `d12ball/data/maneuver_cards.json`, written by
`scripts/import_d12ball_maneuver_cards.py`. 2.1's rules are filed in
[archive/rules-2.1/](../rules-2.1/), since **2.2 replaced 2.1 on
2026-11-01** with the same cards printed two to a card; the rules now
are [docs/rules-2.2.md](../../docs/rules-2.2.md).

What is here is the last 2.0 import, kept for the record:

- `maneuvers_2.json` -- the thirty rows of the 2.0 tab, as the bot read
  them until 2.1.
- `import_d12ball_maneuvers_2.py` -- the importer that wrote it. It no
  longer runs from here (it imports `scripts/import_d12ball_maneuvers.py`
  beside it), and the tab it read no longer exists in that shape.

Nothing in the bot reads either file. The 2.0 rules as they stood are
in the history of `docs/rules-2.0.md`, which 2.1 replaced.
