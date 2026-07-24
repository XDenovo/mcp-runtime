---
name: open-pr
description: Lint, test, and open a draft PR for the current branch, then review it once, fix, and flip it ready. Use when the user wants to open a PR for finished work — also the third stage of /ship.
---

# Open PR

## 1. Discover and run lint/test

Find the repo's own lint/test commands — `package.json` scripts, a `Taskfile`, the CI workflow — never invent one that isn't defined there. Run them. Do not open a PR on a failing state; fix and re-run first.

## 2. Open the draft PR

Use the repo's own PR template if it has one, else the `dot-github` org default. Title it with Conventional Commits. Body: the template's `Related issue` (or equivalent) section gets `Closes #<issue>`. Open it as **draft** (`gh pr create --draft`).

Poll `gh project item-list 1 --owner XDenovo --limit 1000 --format json` by exact content URL for
the Draft PR and its same-repository closing Issue. Check at most 12 times with 5 seconds between
attempts. Both items must reach `Status` exactly `In Progress`. Do not update Project fields
manually; if either item misses the bounded postcondition, stop and report both URLs and their last
observed statuses.

## 3. Review once

Run `/code-review` against the draft PR's diff.

- Findings → apply them, re-run lint/test from step 1, commit, and push the fix commit to the same branch.
- No findings → nothing to push.

## 4. Ready it

`gh pr ready` — only after any fixes from step 3 are pushed and re-verified.

After marking it ready, repeat the same bounded Project query for the exact PR and Issue URLs.
Both items must reach `Status` exactly `In Review`. If they do not, stop and report the last
observed statuses instead of treating the stage as complete.
