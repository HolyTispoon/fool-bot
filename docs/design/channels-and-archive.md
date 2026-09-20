# Game channels, and freeing up the PBD Archive

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Game channels

Every game gets its own private channel, named by `build_game_channel_name` in
`cogs/d12ball_helpers.py`: `d12ball-pbd<number>`, then the game's name if
`/d12ball create_game` was given one (`game_name`, carried on the game record
and reused by the rematch button), or the two sides otherwise —
`d12ball-pbd12-the-cup-final`, `d12ball-pbd12-username-vs-dinky-ai`.

- **The number stays immediately after the `d12ball-pbd` prefix.** It is the
  only part read back off a channel, by `CHANNEL_NAME_PATTERN`, and the suffix
  in that pattern is optional so channels created before names existed still
  match. Anything that changes the shape of the name has to keep both true.
- **Names are slugged, not passed through.** Discord lowercases a channel name
  and rewrites spaces itself, so `slugify_channel_part` does it first and the
  saved name matches what the server shows. Punctuation is dropped, letters
  outside ASCII are kept (they are legal, and a wholly non-Latin display name
  would otherwise slug to nothing), and the whole name is cut to Discord's
  100-character limit without ending on a dash.
- **Archiving moves the channel between categories and never renames it**, so
  a game's channel keeps the name it was created with for the rest of its life.
  Nothing renames a channel when a player's display name changes.
- **Four things archive a channel, and only one of them is a person asking.**
  The startup sweep in `on_ready` files away every finished game it can reach,
  `start_rematch` files the old game away on its way out, `/d12ball
  abandon_game` files away a game nobody is going to finish, and the
  **Archive button** beside Rematch on the full-time message is the pair who
  are not playing again saying so. That button is why the sweep is no longer
  the only way a finished game reaches the archive without someone abandoning
  a game that had already ended. Its gate is `may_administer_game` -- either
  player, or a game helper. The Rematch button beside it now shares that gate
  rather than being players-only: it used to be narrower on the grounds that
  a rematch opens a game two people have to play, and getting two people back
  into a game is exactly what a helper is for. See
  [Who may act on a game](permissions.md#who-may-act-on-a-game).
  - **A view rebuilt straight after a move must be *told* it was archived.**
    `RematchView` takes an `archived` override for exactly this:
    discord.py's `TextChannel.edit` returns a **new** channel object and
    leaves the cached one alone, so `bot.get_channel(...).category` is only
    corrected when the `GUILD_CHANNEL_UPDATE` event lands. Both of
    `refresh_buttons`' callers rebuild in the same breath as the move, so
    reading the state back off the cache drew the button live again. Don't
    replace the override with a cache read -- the tests in
    `tests/test_d12ball_full_time.py` hold the cache at the pre-move category
    on purpose, which is what the live client does for that moment.
    `game_channel_is_archived` is still the right question everywhere else
    (the first post, and the startup re-arm), and answers False for a channel
    it cannot see: the move is idempotent, so a button offered needlessly
    costs a no-op where one withheld leaves a pair with no way to archive.

## Freeing up the PBD Archive

A category holds at most 50 channels, and PBD Archive only ever grows --
nothing un-archives a game -- so a long-lived server eventually hits
`400 Bad Request ... Maximum number of channels in category reached (50)`
the moment the next game tries to archive. `/debug export_archived_games`
is the way out: write everything a finished game and its channel know to
local disk, then delete the channel, which is the only thing that actually
frees a slot in the category.

- **Exported, not merely archived.** Archiving moves a channel and keeps it
  forever, on the theory that the channel *is* the record -- see "Game
  channels" above. Freeing a category slot needs the channel gone, so this
  command is a deliberate exception to "abandoning archives, it does not
  delete" (see [recovery.md](recovery.md)): it deletes on purpose, and
  only after writing the record down somewhere else first.
- **The export has to land before the channel dies, never after.**
  `gamesaves/d12ball/archive_export.write_game_export` is called and
  checked for success before `channel.delete()` is even attempted; an
  `OSError` there leaves that game's channel and save record completely
  untouched; a game moves on to `save_games` only once its channel is
  actually gone. Losing a channel Discord will never give back over a
  write that could be retried is the one failure mode this whole feature
  exists to avoid.
- **`transcript.html` is the file a person opens, and the only reason the
  rest are readable.** JSONL is lossless and unreadable without a tool, and
  `game.json` is the whole `MatchState`; neither answers "how did that game
  go?". The page carries the summary (`summarise_game`), the goal log
  (`describe_goals`), the final board and every message in order with its
  images **shown** rather than named. It is written from the same list in
  the same call as the JSONL, so the two cannot come to disagree.
  - **The folder is the unit.** Attachments are referenced by relative
    path, because inlining them as data URIs puts a hundred board renders
    -- close to a megabyte each -- into one file no browser opens happily,
    and the images are the whole reason the page is worth having.
  - **Escape first, then markdown.** The bot writes `**bold**` in nearly
    every message and a page printing the asterisks reads worse than the
    channel it replaced, so `render_message_content` turns a small subset
    into tags -- *after* `html.escape`, so a `<script>` somebody typed is
    already `&lt;script&gt;` and no pattern can put back what the escape
    took out. This page is opened straight off disk with nothing
    sandboxing it.
  - **`plain()` is not decoration.** `game.to_dict()` is
    `dataclasses.asdict`, which leaves enum *members* in place: `json.dump`
    writes a `str, Enum` as its value, so the file says "finished", but
    `str()` on the member says `GameStatus.FINISHED` -- and this page is
    built from the dict, not the file. The first version shipped reading
    `Home: Tomer (Team.ORANGE)` with a green suite behind it, because the
    fixture had honest strings in it. `RealSaveDataTests` carries the
    enums a real save carries.
  - **Player ids are prettified textually, never looked up.**
    `prettify_player_id` is a string transform, so an export cannot fail
    because the roster was reshuffled after it was written -- which is
    exactly the failure this whole file exists to avoid. The exact ids are
    in `game.json` and the JSONL either way.
- **Five files a game, mirroring what a coach could have looked up while
  the channel was alive**: `game.json` is the exact record `save_games`
  already writes for it (`game.to_dict()`, so it carries the whole
  `MatchState` too); `board.png` is the final position, rendered the same
  way `render_match_png` always has -- best-effort, since a game abandoned
  before it ever had match state has no board to draw, and a render
  failure there costs the picture and nothing else; `transcript.jsonl` is
  every message the channel ever held, oldest first, one JSON object a
  line; `attachments/` is every file any of those messages carried,
  downloaded there and then rather than left as a URL. Discord's
  attachment links are signed and expire (see "The 'View full image'
  button dies after 24 hours" in [gotchas.md](gotchas.md)) -- a transcript that only
  recorded the URL would go quietly unreadable long before anyone opened
  the export.
- **No Google Drive API call exists anywhere in this bot.** "Export to
  Google Drive" means `FOOLBOT_D12BALL_ARCHIVE_EXPORT_DIR` points at a
  folder Google Drive is already syncing -- on the live host, a folder
  inside the mounted `K:\` letter the whole checkout already runs from
  (see "Two of those machines"). `archive_export_dir()` reads it the same
  opt-in-by-`.env` way `FOOLBOT_LOG_MIRROR` does: unset means the command
  refuses outright rather than deleting anybody's channels with nowhere to
  put what it took from them, which is also what keeps a fresh clone or a
  developer's own test checkout from ever running this by accident.
- **Both ends of a run are announced in #logs, through
  `botlog.post_notice`.** A full run walks fifty channels' histories and
  every attachment in them, which outlives the fifteen-minute interaction
  token -- so the summary the command replies with is exactly what is lost
  on the runs that matter most. Neither line is an error, so neither may
  go through the logger to get there: an ERROR in that channel means
  somebody has to fix something. `post_notice` is the third thing that
  reaches the channel deliberately, after the sink and the deploy notice,
  and the third place `FOOLBOT_LOG_MIRROR` is read -- a bot that posts
  nothing exports exactly as it did before. It never raises, and it sends
  prose rather than going through `chunk_log_message`, which wraps a
  record in a code fence.
  - **The start notice sits after every refusal**, so a missing confirm or
    an empty archive puts nothing in the channel. One that announces work
    nobody asked for is one people stop reading.
- **A manual command that clears the whole category, oldest game first.**
  `limit` is 1 to 50, defaulting to 50, because **50 is what fills the
  category** -- a command whose entire purpose is making room in a full
  one should be able to empty it in a single run. Oldest `game_number`
  first, because any archived channel freed makes the same room and there
  is no other reason to prefer one over another.
  - **It was capped at 20, defaulting to 5, on a misreading of the delete
    limit.** Deleting a channel is two per ten minutes and **per
    channel**: `channel_id` is one of the four major rate-limit
    parameters (`discord.http.Route.major_parameters`), so fifty
    different channels are fifty separate buckets, not one queue two
    deep. Only a repeat against the *same* channel is rationed, which is
    what `CHANNEL_DELETE_RETRY_DELAYS` is for. This is the mirror of the
    board-edit bucket, where `message_id` is **not** major and so every
    message in a channel shares one -- the same table read for two
    different ids, which is why "check `discord.http.Route`" is the
    standing instruction rather than "remember which".
  - **What a full run does cost is time**, and it is unbounded by
    anything here: a channel's whole history plus every attachment in it,
    fifty times over, where a single board is close to a megabyte. It
    outlives the fifteen-minute interaction token, which is why the
    summary already falls back to the console -- and why
    `write_game_export` logs a line per game, so a long run is legible
    while it is still running.
- **Gated to Administrator, narrower than `/debug reset_channels`'s
  `manage_channels`.** Both delete channels, but this one also downloads
  and holds a copy of everything the channel ever said before it does --
  more is riding on trusting whoever is allowed to run it, so it gets the
  narrower default. Either gate is only Discord's *default*; a server can
  widen or narrow it per-role in Integrations settings.
  - **A permission gate belongs on the `debug` group, not on a
    subcommand, and a subcommand that wants a narrower one has to check
    it in its own body.** Discord carries
    `default_member_permissions` and `dm_permission`/`contexts` on a
    top-level command only, and discord.py's `Command.to_dict` fills
    those keys in `if self.parent is None` -- so
    `@app_commands.default_permissions(...)` and
    `@app_commands.guild_only()` on a `@debug.command` set the
    attributes, read correctly from Python, and are left out of the
    payload entirely. Both of these commands shipped that way for two
    releases and were runnable by every member of the server. The group
    now carries `manage_channels` for the pair, and
    `export_archived_games` re-checks `guild_permissions.administrator`
    itself. `test_the_permission_gate_rides_on_the_group` reads the
    payload rather than the attribute, which is the only way to see it.
  - **The Administrator check is the one refusal ahead of `confirm`.**
    Somebody who may not run this command should be told that and
    nothing else -- not walked through what it would have done, and not
    handed the export path. Every *operational* refusal still comes
    after confirm.
- **A dead interaction diagnoses itself, in `defer_or_report`.** Both
  commands here acknowledge through it rather than calling
  `interaction.response.defer` directly. Discord discards an
  interaction nothing has acknowledged within three seconds, and the
  defer is then a 404 (10062, "Unknown interaction") raised out of the
  command's **first line** -- which reads as a bug in the command and
  cannot be one, since nothing of ours has run yet. Deferring earlier
  cannot fix it; the defer is the thing that fails. Only two states
  put a dead token there, and they want opposite fixes: the bot took
  over three seconds to reach that line, or **a second process is
  signed in on the same token** and answered first. The interaction's
  own age tells them apart -- Discord stamps the id with its creation
  time, so `utcnow() - snowflake_time(interaction.id)` is exactly how
  long it waited -- so the ERROR that reaches #logs carries the number
  and says which reading it supports. Nothing runs afterwards: a
  refusal sent on a dead token is a second traceback for one cause.
- **An unexpected exception reports back, through
  `Debug.cog_app_command_error`.** Both commands here defer first, so
  without it a crash below the defer leaves the caller watching an
  ephemeral spinner that never resolves while the traceback goes only to
  the console and #logs -- which are on the machine hosting the bot,
  not in front of whoever pressed the button. Unlike the coach-facing
  `D12Ball.cog_app_command_error`, this one **names the exception**: the
  audience is whoever is allowed to delete channels, the reason is the
  whole of what they need, and there is no `/d12ball resume` to point
  them at.
- **`confirm` is checked before anything else that can refuse**, including
  whether an export directory is even configured. Typing the command wrong
  should be told exactly that, not some unrelated reason it wouldn't have
  worked anyway.
  - **The refusal names the field and stops.** It used to restate the whole
    operation -- how many games, out of where, to which directory, and that
    the channels would not survive it -- which is a briefing, delivered to
    somebody who has just been told their command did not run. What they
    need is which field was wrong. The warning belongs on `confirm`'s own
    description, where it is read *before* the command is sent rather than
    after it has failed. That is also what stops the message having to cope
    with an export directory it was never given.
- **Only channels the bot can already see are candidates.** The category
  is re-checked at call time the same way `/debug reset_channels` checks
  it -- a channel matching `CHANNEL_NAME_PATTERN`, currently sitting in
  PBD Archive, whose `channel_id` names a saved game with
  `GameStatus.FINISHED` -- so a game whose channel already vanished (the
  case the `on_ready` sweep already prunes, see "Startup drops finished
  games whose channel was deleted" in [gotchas.md](gotchas.md)) is left for that sweep
  rather than picked up here with nothing left to export.
- **The pure write and the Discord fetching are two different modules on
  purpose.** `gamesaves/d12ball/archive_export.py` knows nothing about
  `discord` -- it takes plain bytes and dicts and writes them down,
  raising `OSError` outright rather than swallowing it the way
  `save_games` does, because this caller has to know the write actually
  landed before it does something `save_games` never has to contend with:
  an action Discord cannot undo. `cogs/debug.py` does every bit of
  fetching (the channel, its history, each attachment's bytes) and only
  hands this module data once it has all of it for one game. That
  render-transcript-write-delete sequence for one game is
  `export_one_game`, over `collect_export_candidates` (the candidate list)
  and `read_channel_transcript` (the history walk); `export_archived_games`
  itself is just the refusals, the two notices, and a fold over the
  per-game results. `delete_channel_with_retries` is the retry loop, and
  is the one piece `reset_channels` shares with it.
- **A folder exported before `transcript.html` existed can get one without
  the bot, `scripts/backfill_archive_html.py`.** It is precisely because
  `render_transcript_html` needs nothing but `game.json` and
  `transcript.jsonl` off disk -- no catalog, no `discord.Client`, no live
  channel (see "Player ids are prettified textually" above) -- that this
  is a standalone script and not another cog command: it walks an export
  directory's folders and (re)writes `transcript.html` for any that lack
  one. It runs `migrate_legacy_game_data` on each `game.json` first, the
  same on-load remap `load_games` applies, so a pre-reshuffle goal log
  reads with today's player names rather than `prettify_player_id`'s guess
  at a retired id. **A game against the Dinky AI is skipped by default**
  (`ai_opponent == "dinky"`, or the legacy tell -- no `player_2_id` and
  `coin_winner == "the Dinky AI"`, the same fallback
  `D12BallGame.__post_init__` reads); `--include-dinky` overrides it, and
  `--force` rebuilds a folder that already has a page.
