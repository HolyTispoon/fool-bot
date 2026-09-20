# The screentop.gg module

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## The screentop.gg module

D12 Ball is also played on [screentop.gg](https://screentop.gg), a browser
tabletop. The game there is built in screentop's own editor and lives on
screentop; nothing about it is checked in here, and nothing here can reach
into it. **What the repo owns is every picture on that table** -- the cards,
the boards, the meeples, the dice, the tokens -- and
`scripts/export_screentop_assets.py` writes them all, cut the way a virtual
tabletop wants them. Updating the module is running the script and uploading
what changed.

```bash
python3 scripts/export_screentop_assets.py                 # ./screentop/
python3 scripts/export_screentop_assets.py --zip           # and screentop.zip
python3 scripts/export_screentop_assets.py --max-side 2048
```

- **`d12ball/screentop.py` is the cut, and the script is only the command
  line round it.** The module follows `player_cards.py` and
  `species_cards.py`: print-only code under `d12ball/`, no Discord, nothing
  async, so it sits under the purity ratchet like the rest of the model.
- **It draws nothing the game already draws.** A card is
  `cards.render_maneuver_card`, `player_cards.render_player_card` or
  `species_cards.render_species_card`; a board is one of `boards.py`'s
  three; a condition token is the PNG `render.py` itself thumbnails to 26px.
  So a rules change, an import or an art fix reaches the screentop module
  the way it reaches the print kit -- by re-running -- and there is nothing
  here for a future rule to drift out of step with. The two things drawn
  here are the two that have no standalone image anywhere else:
  - **A meeple as a token on its own.** The board only ever draws one in
    place, at 76px, with fonts sized for that. `render_meeple_token` is
    `render.draw_meeple_face`'s recipe -- the team's colour inside an ink
    ring, the species icon over the role initials, or the initials alone
    when the game does not play species abilities -- with every measurement
    read from `render.py`'s constants and font objects and scaled by
    `size / MEEPLE_SIZE`. Both cuts are exported, `meeples/` and
    `meeples-basic/`, because which one a table wants is the game's setting
    (see the note by `MEEPLE_SIZE`) and not the export's to guess.
  - **A d12's twelve faces.** The board draws one face showing one value;
    a die on a table needs all twelve. `render_die_face` is the board's
    polygon (`render.polygon_points`) in a team's colour with the board's
    own ink rule (`high_contrast_ink`), and the ball's die is white with
    the outline the board draws the ball in. One die per colour team serves
    its species team too, since a pair shares a hex (see "Team colors" in
    [teams-and-players.md](teams-and-players.md)).
- **A tabletop's cut is not a printer's, in four ways**, each of them a
  reason the print kit could not simply be uploaded:
  - **Sheets are gapless.** `cards.print_sheet` centres every card in a cell
    with a margin, because a print is cut by hand and a margin is where the
    knife wanders. A tabletop cuts a sheet by dividing it into exactly
    `columns` x `rows`, so a cell *is* a card, edge to edge. `tabletop_sheet`
    is that grid; it refuses a mixed-size set rather than stretching one
    card to fit, since a sheet whose cells lie about a card is the whole
    failure.
  - **Backs are in reading order, never `duplex_order`.** The print kit
    reverses every row of the player backs because a duplex printer flips the
    sheet. A tabletop pairs cell *n* of the fronts with cell *n* of the backs,
    and the reversal would land every back behind the wrong player -- which is
    the one thing `D12BallScreentopTests` most wants to catch.
  - **No bleed.** An eighth of an inch a trimmer takes off is, on a screen, a
    border round every card.
  - **Nothing over `MAX_SIDE` (4096px) a side.** A 300dpi tabloid board is
    3300 x 5100, which a web canvas has no use for and some renderers refuse
    as a texture. Images are only ever scaled *down*, and a sheet is capped as
    a whole with its cell kept integer, so the grid still divides exactly.
    `--max-side` changes the cap for a table that wants lighter uploads.
- **The manifest is the contract.** `manifest.json` lists every file the
  export wrote -- and only those; a token whose art is missing is left out
  rather than failing the export, like the silent loaders in `render.py` --
  with its kind, its size and, for a sheet, the grid and the order of its
  cells. Those are the numbers a person types into the editor, and reading
  them off the file is what keeps a 3 x 3 from being typed as a 3 x 4. The
  suite holds every sheet's grid to its own pixels and every cell name to a
  file of the cell's size.
- **The coin is the bot's coin.** `COIN_FACE_ART` names the two emoji PNGs
  the toss is shown with. The names are the cog's `COIN_EMOJI_NAMES`,
  restated because the model may not import a cog; the suite holds the two
  to the same files, so a change to which coin the bot flips fails a test
  until the table flips it too.
- **One team board panel per team**, not the print sheet's two-up: a
  tabletop places a board a side, and `render_team_board_panel` is already
  the one panel `render_team_board` pastes twice. An uncoloured panel is
  written too, for a table that wants both boards alike.
- **`screentop/` is generated output and gitignored**, like `print-and-play/`.
  Run the script again rather than trusting an old copy after the rules move.
- **What screentop itself needs is not written down here on purpose.** The
  editor's own dialogs are screentop's to change; the export gives it
  gapless grids with the grid stated, single images beside every sheet for a
  component the editor would rather take one at a time, and PNGs with
  transparency for the tokens and dice. If the editor comes to want something
  the manifest does not carry, the manifest grows a field and the README the
  script writes says so.
