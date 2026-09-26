"""
Claim a step of docs/web-app-next.md before starting work on it.

    python3 scripts/claim_web_step.py 3
    python3 scripts/claim_web_step.py 3 --who "Tomer"
    python3 scripts/claim_web_step.py 3 --release

A claim is the branch `web-step-<n>` on origin, holding one empty commit
on top of origin/main that names who claimed it. It is created with
`--force-with-lease=refs/heads/web-step-<n>:` -- an empty expected value,
which git reads as "this ref must not exist yet" -- so two people (or a
person and the cloud routine) claiming the same step at once cannot both
win: the second push is rejected. It is a create, never an overwrite.

The claim is also the branch to work on: this leaves a local
`web-step-<n>` tracking it and touches nothing in the working tree. Work,
push, and open the PR titled `Web app step <n>: ...` from it.

`--release` deletes the claim branch, for a step somebody started and
stopped; do it only for your own claim. See "Claiming a step" in
docs/web-app-next.md for what else counts as a claim.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

REMOTE = "origin"
WORKSHEET = "docs/web-app-next.md"


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=check,
    )


def claims_on_remote(step: int) -> list[str]:
    """Every branch on origin that claims this step: `web-step-<n>` and
    `web-step-<n>-<anything>`."""
    listing = git("ls-remote", "--heads", REMOTE).stdout
    pattern = re.compile(rf"refs/heads/(web-step-{step}(?:-[^\s]*)?)$")
    return [
        match.group(1)
        for line in listing.splitlines()
        if (match := pattern.search(line))
    ]


def describe(branch: str) -> str:
    git("fetch", "-q", REMOTE, branch, check=False)
    shown = git(
        "log", "-1", "--format=%an, %ar: %s", "FETCH_HEAD", check=False,
    )
    return f"{branch} ({shown.stdout.strip() or 'unreadable'})"


def open_pull_requests(step: int) -> list[str]:
    """Open PRs (drafts included) titled for this step, via `gh` if it is
    installed; an empty list with a note if it is not."""
    try:
        listing = subprocess.run(
            [
                "gh", "pr", "list", "--state", "open",
                "--search", f'"Web app step {step}:" in:title',
                "--json", "number,title,author",
                "--template",
                "{{range .}}#{{.number}} {{.title}} ({{.author.login}})\n{{end}}",
            ],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        print("(gh is not available, so open PRs were not checked.)")
        return []
    return [line for line in listing.splitlines() if line.strip()]


def step_has_landed(step: int) -> bool:
    worksheet = git("show", f"{REMOTE}/main:{WORKSHEET}").stdout
    return re.search(rf"^\|\s*~~{step}~~\s*\|", worksheet, re.M) is not None


def claim(step: int, who: str) -> int:
    git("fetch", "-q", REMOTE, "main")
    if step_has_landed(step):
        print(f"Step {step} is struck in {WORKSHEET}: it has landed.")
        return 1

    taken = [describe(branch) for branch in claims_on_remote(step)]
    taken += open_pull_requests(step)
    if taken:
        print(f"Step {step} is already claimed:")
        for claim_by in taken:
            print(f"  {claim_by}")
        return 1

    branch = f"web-step-{step}"
    tree = git("rev-parse", f"{REMOTE}/main^{{tree}}").stdout.strip()
    commit = git(
        "commit-tree", tree, "-p", f"{REMOTE}/main",
        "-m", f"Claim web app step {step} ({who})",
    ).stdout.strip()
    pushed = git(
        "push", f"--force-with-lease=refs/heads/{branch}:",
        REMOTE, f"{commit}:refs/heads/{branch}",
        check=False,
    )
    remote_now = git("ls-remote", "--heads", REMOTE, branch).stdout.split()
    if pushed.returncode != 0 or not remote_now or remote_now[0] != commit:
        print(f"Somebody claimed step {step} first: {describe(branch)}")
        return 1

    git("branch", branch, commit, check=False)
    git("branch", f"--set-upstream-to={REMOTE}/{branch}", branch, check=False)
    print(
        f"Claimed step {step} as {who}. Work on it with:\n"
        f"  git checkout {branch}",
    )
    return 0


def release(step: int) -> int:
    branch = f"web-step-{step}"
    deleted = git("push", REMOTE, "--delete", branch, check=False)
    if deleted.returncode != 0:
        print(deleted.stderr.strip())
        return 1
    print(f"Released step {step}: {branch} is gone from {REMOTE}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("step", type=int)
    parser.add_argument("--who", help="who is claiming (git user.name)")
    parser.add_argument("--release", action="store_true")
    options = parser.parse_args()

    if options.release:
        return release(options.step)
    who = options.who or git(
        "config", "user.name", check=False,
    ).stdout.strip() or "unnamed"
    return claim(options.step, who)


if __name__ == "__main__":
    sys.exit(main())
