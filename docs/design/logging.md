# Logging and the #logs channel

Design notes for fool-bot; the map is [CLAUDE.md](../../CLAUDE.md), the rules are [living-rules.md](../living-rules.md).

## Logging and the #logs channel

**Use `logging`, not `print`.** Every module gets its own logger
(`LOGGER = logging.getLogger(__name__)`) and `botlog.configure_logging()`
in `foolbot.py` sets the root logger up once, before anything logs. That is
also why `bot.run` is called with `log_handler=None`: discord.py otherwise
configures its own logger inside `run`, and with a root handler already
attached every library line would print twice.

Records at ERROR and above are mirrored into a Discord channel, so a crash
shows up in the server instead of only on the console of whoever is hosting
the bot. A bot told to post (`FOOLBOT_LOG_MIRROR=on` — see below; the
default is console only) finds or creates a channel called `#logs` on
startup, posts the record with its traceback in a code fence, and posts a
one-line notice naming the build it is running whenever that build changes.

Everything is optional and lives in `.env` next to `DISCORD_TOKEN`:

| Variable | Default | What it does |
| --- | --- | --- |
| `FOOLBOT_LOG_MIRROR` | off | `on` lets this bot post to the channel at all |
| `FOOLBOT_LOG_LEVEL` | `INFO` | Console threshold |
| `FOOLBOT_LOG_CHANNEL_LEVEL` | `ERROR` | Discord threshold; `off` disables the mirror |
| `FOOLBOT_LOG_CHANNEL_ID` | — | Mirror into exactly this channel |
| `FOOLBOT_LOG_CHANNEL_NAME` | `logs` | Channel to find or create, when no id is set |
| `FOOLBOT_LOG_GUILD_ID` | first server | Which server hosts the channel |
| `FOOLBOT_DEPLOY_NOTICE` | on | `off` stops the "now running this build" notice |
| `FOOLBOT_HOST_NAME` | machine name | What the deploy notice calls this host |

Things to know before changing any of it:

- **Posting to the channel is opt-in, per bot.** `FOOLBOT_LOG_MIRROR`
  is off unless a checkout's own `.env` sets it, and nothing reaches
  `#logs` without it — neither an error nor a deploy notice. The same
  repository is run by more than one bot: the real one on its host, and
  a test bot on a developer's machine out of a clone or a worktree of
  the same code. Both used to bind the channel and both posted, so it
  carried a test bot's tracebacks beside the ones somebody could act
  on. `.env` is untracked and per checkout, so a clone starts silent —
  which is the right way round: a real bot gone quiet after a redeploy
  is one line in a file its host already needs, where a test bot
  posting is noise in the one channel that is supposed to be
  actionable, and nobody running it has any reason to notice.
  `mirror_enabled()` in `botlog/channel.py` is the switch, read in
  exactly two places (`install_mirror` and `announce_startup`, the two
  entry points that reach the channel) rather than inside
  `ensure_log_channel`, so a bot that is not posting attaches no sink,
  lowers no log level and shells out to no git.
  An unrecognised value is **off**, unlike `FOOLBOT_LOG_CHANNEL_LEVEL`,
  which falls back to `ERROR`: the level's failure mode should be
  saying too much, and this one's should be saying nothing.
- **The level you log at decides who sees it.** ERROR reaches the server;
  WARNING and INFO are console-only. So an error means "someone needs to
  fix this", not "something unexpected happened" — a missing application
  emoji is an INFO, a game whose channel the bot is not allowed to move is
  an ERROR. The test is whether anyone can act on it: a finished game whose
  channel was deleted, or whose server the bot has left, is an INFO however
  much it looks like a failure, because there is nothing to fix and the
  startup sweep would repeat it on every reconnect. Not every ERROR is
  ours to level: discord.py's reconnect line is one somebody else logs,
  and it is filtered out of the mirror instead -- see below.
- **The sink must never log its own failures.** A failed send that logged
  would hand itself the record it just failed to send. `botlog/handler.py`
  prints those to stderr, deliberately.
- **The build notice is keyed on the commit sha**, remembered in the
  untracked `data/bot_state.json`. `on_ready` fires again on every gateway
  reconnect and either of us restarts the bot constantly while testing;
  keying on the commit is what keeps that from being a stream of identical
  "restarted" posts. It reads HEAD out of the checkout with `git log`, so
  the notice is only as accurate as the deployed tree — and degrades to
  saying nothing at all if git is not on PATH.
- **The notices are one stream per machine, not one per repository.** That
  state file is local, so when two opted-in hosts deploy into the same
  `#logs` the posts interleave: the same commit gets announced once by each,
  and neither stream is the repository's history. Each notice names its host
  so they can be told apart. Don't read the channel as a changelog — and
  don't read a host's absence from it as that host being behind, since a
  checkout without `FOOLBOT_LOG_MIRROR` announces nothing at all.
- **A merge is listed only when it resolved a conflict.** A clean merge
  repeats commits the notice already lists, so it is dropped and its pull
  request named in the heading instead; a conflict resolution exists in the
  merge commit and nowhere else, so dropping it would drop work. The test
  for which is an empty combined diff — `--name-only` and `--stat` both
  report a clean merge of two branches that touched one file as if it
  carried changes, so `merges_with_content` reads the patch.

The channel is created with whatever permissions the server's defaults give
it. Tracebacks name game ids, channel names and command arguments, so lock
the channel down server-side if that matters.

### Gateway reconnects are weather, until they are not

`botlog/gateway.py` is the one thing that decides a record is *not* worth
mirroring, and it exists for a single line discord.py logs:

```
ERROR discord.client: Attempting a reconnect in 14.13s
... aiohttp.client_exceptions.WSServerHandshakeError: 503 ...
```

`Client.connect` catches every dropped connection -- a gateway node
restarting, a 503 off the handshake, the host's wifi blinking -- waits out an
exponential backoff and tries again, announcing each attempt with
`_log.exception`. **That is ERROR with a traceback, so under the rule above
it landed in #logs**, and nothing about it is actionable: the library has
already dealt with it, and by the time anyone reads the post the bot is back.
A channel carrying Discord's weather is a channel people stop reading, which
costs the one record in it that did need somebody.

- **The filter is on the sink and on nothing else**, attached in
  `install_mirror`. The console keeps every one, which is the right way round:
  the traceback names the actual cause, and the person who wants it is sitting
  at the host with the bot in front of them. On the root logger it would take
  the record off the console too.
- **What survives is the run that has stopped being weather.** Past
  `ESCALATE_AFTER_SECONDS` of unbroken retrying the bot is, for practical
  purposes, off the server, and that is worth saying; `ESCALATION_INTERVAL_SECONDS`
  is how long the same run goes quiet for before saying it again, so an
  outage neither floods the channel nor comes to look resolved.
- **The escalated record is the library's own**, traceback and all -- by then
  the cause is the useful half -- carrying a note that says how long it has
  been going on. **The note rides on an attribute, not on the message**
  (`OUTAGE_NOTE_ATTRIBUTE`, prepended by `DiscordLogChannelHandler.format`),
  because the console handler is holding the same record object and its
  formatter neither knows nor asks about it. Mutating the message would edit
  what the console prints, and which handler got there first.
- **An escalation is followed up when it clears**, by
  `announce_gateway_recovery` off `on_ready` **and `on_resumed`** -- two
  events because discord.py resumes the session where it can and only
  re-identifies when the gateway refuses, so a hook on `on_ready` alone would
  miss most reconnects and leave the outage standing in the channel. A
  recovery nobody was told about says nothing, which is the same rule as
  "a move that costs nothing says nothing"; an escalation left unresolved is
  the one thing worse than never having posted it. It goes out through
  `post_notice`, since it is not an error.
- **A run can end on its own** (`RUN_RESET_AFTER_SECONDS`), so correctness
  does not rest on the recovery hook being called. Without it two blips a
  month apart would read as a month-long outage and escalate on the spot.
  The reset is comfortably past discord.py's own ceiling on the backoff.
- **The match is on discord.py's wording**, `record.msg` starting with
  "Attempting a reconnect" on a `discord.` logger -- the format string rather
  than the formatted message, since `getMessage()` can raise and a filter may
  not. That is the part that can rot: reworded upstream, the filter stops
  recognising the record and #logs carries it again, which is the old
  behaviour and not a new failure.
- **A bad token or missing privileged intents is not affected.** Those close
  with a code discord.py re-raises rather than retrying, so they never reach
  this line -- suppressing reconnect noise hides no configuration error.
- **Delivery is best-effort, which is not new.** The mirror posts over REST
  rather than the gateway, so it usually works while the gateway is down; when
  it does not, the sink already prints to stderr and drops the record.
