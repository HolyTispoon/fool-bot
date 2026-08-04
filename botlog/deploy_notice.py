"""
The "I am back up, and here is what changed" post.

The bot is deployed by pulling into a live checkout and restarting the
process (scripts/update-main-bot.sh, then scripts/update_main_bot.ps1 on
the Windows host), so HEAD is the honest answer to "which code is this
running". This module reads that answer, formats the notice, and
remembers what it has already announced.

The remembering is the whole design. on_ready fires again on every
gateway reconnect, and either of us may restart the bot repeatedly while
testing, none of which is a deploy. So the notice is keyed on the
commit: the sha last announced is persisted next to the saved games and
a build that has already been announced says nothing. New code posts
once; everything else is quiet.

Nothing here imports discord and nothing here raises. Every git call
degrades to None, so a checkout without git in PATH, or a copy of the
tree that is not a repository at all, costs the notice and nothing else.
The caller owns the send and only records the sha once the post has
landed, so a failed post retries on the next start instead of being
swallowed.
"""

import json
import os
import re
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# The repository the running code was imported from; botlog/ lives one
# level under it.
REPO_DIR = Path(__file__).resolve().parents[1]

# Beside data/d12ball_games.json, and untracked for the same reason: it
# is runtime state, and each machine's is its own.
STATE_FILE = REPO_DIR / "data" / "bot_state.json"

# The key in that file holding the sha of the build already announced.
LAST_SHA_KEY = "deploy_notice_sha"

# A local git log is milliseconds; this is only here so a hung git can
# never hold up startup.
GIT_TIMEOUT = 10.0

# Longer catch-ups collapse to "...and N more".
MAX_LISTED_COMMITS = 10
# Per-line clip, so one long subject cannot crowd out the rest.
MAX_SUBJECT_LENGTH = 120
# Enough for a machine name; the override is not a place for prose.
MAX_HOST_LENGTH = 40
# Discord's limit is 2000; leave room rather than lose the tail.
MAX_MESSAGE_LENGTH = 1900

# Separates commits in a git format that carries a multi-line field, so
# the records can be split apart before the fields are. Not \x1e, the
# ASCII record separator, which would read better: Python counts it as
# whitespace, so the str.strip() in _git would eat it off the ends.
RECORD_SEPARATOR = "\x01"

# "Merge pull request #25 from HolyTispoon/additional-tweaks" -- what
# GitHub writes for a merge made through the web UI, which is how work
# lands on main here.
PULL_REQUEST_SUBJECT = re.compile(r"^Merge pull request #(\d+) ")


@dataclass(frozen=True)
class Build:
    """
    One commit: the full sha, which is the dedup key, plus the short sha
    and subject the notice shows.
    """

    sha: str
    short: str
    subject: str


@dataclass(frozen=True)
class Commit:
    """A line in the change list."""

    short: str
    subject: str


@dataclass(frozen=True)
class Changes:
    """
    What one deploy brought in.

    commits are the lines to list. pull_requests are the numbers of the
    pull requests whose merge commits were left out of those lines,
    which the notice names instead: several usually land between one
    restart and the next, and a flat list of their commits does not show
    that they were pull requests at all. previous_short is the near end
    of the range, so a list too long to print can still say where to
    look.
    """

    commits: tuple[Commit, ...]
    pull_requests: tuple[int, ...] = ()
    previous_short: str = ""


def notices_enabled() -> bool:
    """
    False when FOOLBOT_DEPLOY_NOTICE is set to an off-ish value, the
    same escape hatch FOOLBOT_LOG_CHANNEL_LEVEL has. On by default.
    """
    raw = os.environ.get("FOOLBOT_DEPLOY_NOTICE", "").strip().lower()

    return raw not in ("0", "off", "no", "none", "false", "disabled")


def _git(repo_dir: Path, *args: str) -> Optional[str]:
    """
    The stdout of `git -C repo_dir <args>`, or None for any failure at
    all -- git missing, not a repository, a bad revision, a hang. Never
    raises: the notice is a nicety and must not be able to break
    startup.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None

    return completed.stdout.strip()


def display_subject(subject: str, body: str) -> str:
    """
    What to show for a commit. Normally its subject, except for a GitHub
    merge commit, whose subject is "Merge pull request #18 from
    HolyTispoon/claude/some-branch" and whose body starts with the pull
    request title. Since work lands here by merged pull request, that
    title is the answer to "what changed" and the subject is routing
    noise.

    Only the "Merge pull request" form is remapped: a hand-written
    merge's body is prose, not a title.
    """
    if not subject.startswith("Merge pull request "):
        return subject

    for line in body.split("\n"):
        if line.strip():
            return line.strip()

    return subject


def host_name() -> str:
    """
    The machine this build is running on, raw -- deploy_message is what
    makes it fit for Discord, the way it is what cleans a subject.

    Both of us deploy the same repository from our own machines into the
    same #logs channel, so the notices there are two independent streams
    rather than one history: each machine keeps its own record of what
    it has announced, and the same commit gets a post from each. Naming
    the host is what makes that readable instead of looking like a
    changelog that repeats itself and skips things.

    FOOLBOT_HOST_NAME overrides, because the name a Windows box gives
    itself ("DESKTOP-4F8K2L1") identifies nothing to a reader.

    Empty string, never a raise, if the host cannot be named: the notice
    goes without it.
    """
    override = os.environ.get("FOOLBOT_HOST_NAME", "").strip()

    if override:
        return override

    try:
        return socket.gethostname()
    except OSError:
        return ""


def pull_request_number(subject: str) -> Optional[int]:
    """
    The number in a GitHub merge commit's subject, or None for any other
    subject -- a hand-written merge, or an ordinary commit.
    """
    match = PULL_REQUEST_SUBJECT.match(subject)

    return int(match.group(1)) if match else None


def merges_with_content(
    previous_sha: str,
    repo_dir: Path = REPO_DIR,
) -> frozenset[str]:
    """
    The short shas of the merges in previous_sha..HEAD that resolved a
    conflict.

    A clean merge holds no work of its own: every hunk of its result
    came from one side or the other, and both sides are in the range
    already, so listing it would only repeat them. A conflict
    resolution is different. It is written while merging and lives in
    the merge commit and nowhere else, so dropping that merge drops
    work that no other line of the notice mentions.

    An empty combined diff is what tells the two apart, and only the
    patch gives it. --name-only and --stat both name a file that
    differs from every parent, which is true of a clean merge of two
    branches that touched the same file -- checked against 0bfc5e9,
    a clean merge those two report as if it carried changes. Hence a
    real patch, at --unified=0 since only its emptiness is read.

    An empty set for any failure, which lands the caller back on
    dropping every merge -- what it did before this existed.
    """
    out = _git(
        repo_dir,
        "log", "--merges", "--no-color", "--cc", "--unified=0",
        f"--format={RECORD_SEPARATOR}%h",
        f"{previous_sha}..HEAD",
    )

    if not out:
        return frozenset()

    carrying = set()

    for record in out.split(RECORD_SEPARATOR):
        short, _, diff = record.partition("\n")

        if short.strip() and diff.strip():
            carrying.add(short.strip())

    return frozenset(carrying)


def head_build(repo_dir: Path = REPO_DIR) -> Optional[Build]:
    """
    The commit HEAD points at, or None if this is not a readable
    checkout. NUL-separated so an empty subject or body still parses
    into four fields.
    """
    line = _git(
        repo_dir,
        "log", "-1", "--no-color", "--format=%H%x00%h%x00%s%x00%b",
    )

    if not line:
        return None

    parts = line.split("\x00")

    if len(parts) != 4:
        return None

    return Build(
        sha=parts[0],
        short=parts[1],
        subject=display_subject(parts[2], parts[3]),
    )


def commits_since(
    previous_sha: str,
    repo_dir: Path = REPO_DIR,
) -> Optional[Changes]:
    """
    What previous_sha..HEAD brought in, newest first.

    None rather than empty Changes when the range cannot be resolved,
    which happens when the announced build is not in this checkout at
    all (a rewritten history, a fresh shallow clone), so the caller can
    say so instead of claiming nothing changed.

    A clean merge does not become a line. Work arrives here as merged
    pull requests, so a raw range is half "Merge pull request #18 from
    ..." routing that says less than the commits underneath it, which
    are listed. Its number comes back in pull_requests instead, so the
    notice can still say which pull requests landed -- dropping the
    merges outright is what made a catch-up over several of them read as
    a loose pile of commits.

    A merge that resolved a conflict is listed like any other commit;
    see merges_with_content for why that one is not routing. A range
    that is nothing but clean merges keeps them, so a deploy is never
    reported as empty when it was not.
    """
    out = _git(
        repo_dir,
        "log", "--no-color",
        f"--format={RECORD_SEPARATOR}%h%x00%s%x00%p%x00%b",
        f"{previous_sha}..HEAD",
    )

    if out is None:
        return None

    previous_short = previous_sha[:7]

    if not out:
        return Changes(commits=(), previous_short=previous_short)

    parsed: list[tuple[Commit, str, bool]] = []

    for record in out.split(RECORD_SEPARATOR):
        if not record.strip():
            continue

        short, _, rest = record.partition("\x00")
        subject, _, rest = rest.partition("\x00")
        parents, _, body = rest.partition("\x00")

        parsed.append((
            Commit(short=short, subject=display_subject(subject, body)),
            subject,
            len(parents.split()) > 1,
        ))

    # A second git call, and the expensive one -- skipped entirely when
    # the range holds no merge for it to classify.
    carrying = (
        merges_with_content(previous_sha, repo_dir)
        if any(is_merge for _, _, is_merge in parsed)
        else frozenset()
    )

    listed: list[Commit] = []
    dropped: list[Commit] = []
    pull_requests: list[int] = []

    for commit, raw_subject, is_merge in parsed:
        if not is_merge or commit.short in carrying:
            listed.append(commit)
            continue

        dropped.append(commit)
        number = pull_request_number(raw_subject)

        if number is not None:
            pull_requests.append(number)

    if not listed:
        # Nothing but clean merges. They are the whole deploy, so they
        # are the list, and naming them again above it would only say
        # the same thing twice.
        return Changes(
            commits=tuple(dropped), previous_short=previous_short,
        )

    return Changes(
        commits=tuple(listed),
        pull_requests=tuple(sorted(set(pull_requests))),
        previous_short=previous_short,
    )


def _inline(text: str, limit: int) -> str:
    """
    Text safe to drop into a Discord message: backticks stripped, since
    they would break the code span around it, and clipped to `limit`.
    """
    text = text.replace("`", "'").strip()

    if len(text) > limit:
        text = text[:limit - 3].rstrip() + "..."

    return text


def _clean(subject: str) -> str:
    """A commit subject fit for the notice, never empty."""
    return _inline(subject, MAX_SUBJECT_LENGTH) or "(no subject)"


def _heading(changes: Changes) -> str:
    """
    The line above the change list: how much landed, and which pull
    requests it came from when the merges themselves were left out.
    """
    total = len(changes.commits)
    label = "commit" if total == 1 else "commits"
    heading = f"Changes in this deploy ({total} {label}"

    if changes.pull_requests:
        numbers = ", ".join(f"#{number}" for number in changes.pull_requests)
        word = (
            "pull request" if len(changes.pull_requests) == 1
            else "pull requests"
        )
        heading += f", from {word} {numbers}"

    return heading + "):"


def deploy_message(
    build: Build,
    changes: Optional[Changes],
    first_run: bool = False,
    host: str = "",
) -> str:
    """
    The posted text: what is running now, then what changed.

    changes is None when the range could not be read, and carries no
    commits when the recorded build is not an ancestor of HEAD (a
    rollback, a force-push). Both say so rather than implying an empty
    deploy. first_run is the no-previous-build case -- the very deploy
    that ships this feature -- where a change list would be the whole
    history. host names the machine, and is left out when empty.
    """
    where = _inline(host, MAX_HOST_LENGTH)
    lines = [
        f"**Bot restarted**{f' on `{where}`' if where else ''} -- now "
        f"running `{build.short}` {_clean(build.subject)}"
    ]

    if first_run:
        lines.append(
            "(First build on record, so there is no change list yet; the "
            "next deploy will list its commits.)"
        )
    elif changes is None:
        lines.append(
            "(Could not read the change list: the previously announced "
            "build is not in this checkout's history.)"
        )
    elif not changes.commits:
        lines.append(
            "(No commits between the last announced build and this one "
            "-- a rollback or a force-push?)"
        )
    else:
        shown = list(changes.commits[:MAX_LISTED_COMMITS])
        total = len(changes.commits)
        lines.append(_heading(changes))
        lines.extend(f"- `{c.short}` {_clean(c.subject)}" for c in shown)

        if total > len(shown):
            # Name the range rather than only the count: a deploy this
            # far behind is exactly when someone wants the rest.
            rest = f"- ...and {total - len(shown)} more"

            if changes.previous_short:
                rest += (
                    f" -- `git log {changes.previous_short}..{build.short}`"
                )

            lines.append(rest + ".")

    return "\n".join(lines)[:MAX_MESSAGE_LENGTH]


def notice_for(
    previous: Optional[str],
    repo_dir: Path = REPO_DIR,
) -> Optional[tuple[str, str]]:
    """
    (sha, message) when the running build is not `previous` -- the sha
    last announced, or None if none ever was -- and None otherwise.

    None covers every silent case: the feature switched off, an
    unreadable checkout, and the common one, a restart on the same
    commit. The caller posts the message and only then records the sha.

    This is the half that shells out to git, so it is meant to be run in
    a worker thread; it takes the previous sha as an argument rather
    than reading it, to keep that decision at the call site.
    """
    if not notices_enabled():
        return None

    build = head_build(repo_dir)

    if build is None:
        return None

    if previous == build.sha:
        return None

    changes = None if previous is None else commits_since(previous, repo_dir)

    return build.sha, deploy_message(
        build, changes, first_run=previous is None, host=host_name(),
    )


def last_announced(state_file: Path = STATE_FILE) -> Optional[str]:
    """
    The sha already announced, or None if this machine has never posted
    a notice. A missing or unreadable state file is a first run, not an
    error: the cost of being wrong is one extra notice.
    """
    try:
        with state_file.open("r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(state, dict):
        return None

    sha = state.get(LAST_SHA_KEY)

    return sha if isinstance(sha, str) else None


def mark_announced(sha: str, state_file: Path = STATE_FILE) -> None:
    """
    Record `sha` as announced, so the next restart on it says nothing.
    Written through a temporary file, the way the saved games are, so an
    interrupted write cannot leave a truncated file behind.
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)

    state: dict[str, object] = {}

    try:
        with state_file.open("r", encoding="utf-8") as file:
            loaded = json.load(file)

        if isinstance(loaded, dict):
            state = loaded
    except (OSError, json.JSONDecodeError):
        state = {}

    state[LAST_SHA_KEY] = sha
    temporary_file = state_file.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    temporary_file.replace(state_file)
