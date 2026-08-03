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
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


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
# Discord's limit is 2000; leave room rather than lose the tail.
MAX_MESSAGE_LENGTH = 1900


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
) -> Optional[list[Commit]]:
    """
    The commits in previous_sha..HEAD, newest first.

    None rather than [] when the range cannot be resolved, which happens
    when the announced build is not in this checkout at all (a rewritten
    history, a fresh shallow clone), so the caller can say so instead of
    claiming nothing changed.

    Merge commits drop out: work arrives here as merged pull requests,
    so a raw range is half "Merge pull request #18 from ..." lines that
    say less than the commits underneath them. The parent list is what
    identifies one. A range that is nothing but merges keeps them, so a
    deploy is never reported as empty when it was not.
    """
    out = _git(
        repo_dir,
        "log", "--no-color", "--format=%h%x00%s%x00%p",
        f"{previous_sha}..HEAD",
    )

    if out is None:
        return None

    if not out:
        return []

    commits: list[Commit] = []
    merges: list[Commit] = []

    for line in out.split("\n"):
        short, _, rest = line.partition("\x00")
        subject, _, parents = rest.partition("\x00")
        commit = Commit(short=short, subject=subject)

        if len(parents.split()) > 1:
            merges.append(commit)
        else:
            commits.append(commit)

    return commits or merges


def _clean(subject: str) -> str:
    """
    A commit subject safe to drop into a Discord message: backticks
    stripped, since they would break the code span around the sha, and
    clipped to a sane length.
    """
    text = subject.replace("`", "'").strip()

    if len(text) > MAX_SUBJECT_LENGTH:
        text = text[:MAX_SUBJECT_LENGTH - 3].rstrip() + "..."

    return text or "(no subject)"


def deploy_message(
    build: Build,
    commits: Optional[Sequence[Commit]],
    first_run: bool = False,
) -> str:
    """
    The posted text: what is running now, then what changed.

    commits is None when the range could not be read, and [] when the
    recorded build is not an ancestor of HEAD (a rollback, a
    force-push). Both say so rather than implying an empty deploy.
    first_run is the no-previous-build case -- the very deploy that
    ships this feature -- where a change list would be the whole
    history.
    """
    lines = [
        f"**Bot restarted** -- now running `{build.short}` "
        f"{_clean(build.subject)}"
    ]

    if first_run:
        lines.append(
            "(First build on record, so there is no change list yet; the "
            "next deploy will list its commits.)"
        )
    elif commits is None:
        lines.append(
            "(Could not read the change list: the previously announced "
            "build is not in this checkout's history.)"
        )
    elif not commits:
        lines.append(
            "(No commits between the last announced build and this one "
            "-- a rollback or a force-push?)"
        )
    else:
        shown = list(commits[:MAX_LISTED_COMMITS])
        total = len(commits)
        label = "commit" if total == 1 else "commits"
        lines.append(f"Changes in this deploy ({total} {label}):")
        lines.extend(f"- `{c.short}` {_clean(c.subject)}" for c in shown)

        if total > len(shown):
            lines.append(f"- ...and {total - len(shown)} more.")

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

    commits = None if previous is None else commits_since(previous, repo_dir)

    return build.sha, deploy_message(
        build, commits, first_run=previous is None,
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
