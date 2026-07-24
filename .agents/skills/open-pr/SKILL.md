---
name: open-pr
description: Lint, test, and open a draft PR for the current branch, then review it once, fix, and flip it ready. Use when the user wants to open a PR for finished work — also the third stage of /ship.
---

# Open PR

## 1. Discover and run lint/test

Find the repo's own lint/test commands — `package.json` scripts, a `Taskfile`, the CI workflow — never invent one that isn't defined there. Run them. Do not open a PR on a failing state; fix and re-run first.

## 2. Open the draft PR

Use the repo's own PR template if it has one, else the `dot-github` org default. Title it with Conventional Commits. Body: the template's `Related issue` (or equivalent) section gets `Closes #<issue>`. Open it as **draft** (`gh pr create --draft`).

## 3. Review once

Run `/code-review` against the draft PR's diff.

- Findings → apply them, re-run lint/test from step 1, commit, and push the fix commit to the same branch.
- No findings → nothing to push.

## 4. Ready it

`gh pr ready` — only after any fixes from step 3 are pushed and re-verified.
