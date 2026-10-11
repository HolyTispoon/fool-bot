"""The Tethys deck, drawn by code.

Six suits of twelve -- the numbers 1 to 10, Left and Right -- half of
them Fortune and half Doom, six and six in every suit. `deck.py` is the
rule: which card is which fate, and how a card's value is made of
denominations the way the studio's coins make a sum. `icons.py` draws
each suit's symbol flat, in colour, whole for Fortune and broken for
Doom; `relief.py` lights those drawings as embossed metal; `cards.py`
sets the pieces on a white card; `back.py` draws the one back; and
`print_sheets.py` lays the deck out for a printer. `sets.py` reads a
hand of six as poker reads five and counts every hand by its set, and
`sets_aid.py` draws that as a player aid and a chart. `strips.py` keeps
the faces at screen size and lays a row of them out as one picture.
Nothing here imports `discord`; the bot's `cogs/tethysdeck.py` deals the
same 72 names and shows them through `strips.py`.

See docs/design/tethys-deck.md.
"""
