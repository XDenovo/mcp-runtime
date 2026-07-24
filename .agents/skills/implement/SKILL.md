---
name: implement
description: Claim a GitHub issue published by to-issue, worktree its branch, and implement it test-first. Use when the user wants to start work on a specific filed issue — also the second stage of /ship.
---

# Implement

## 1. Claim

Resolve the target issue (from the argument, or ask which one). Check its assignees (`gh issue view <n> --json assignees`) — if someone other than the current user already holds it, stop and report the conflict rather than taking it over. Otherwise claim it: `gh issue edit <n> --add-assignee @me`.

## 2. Worktree the branch

Read the exact branch/worktree name from the issue's `## Branch` field (set by `to-issue`) — never invent one. If the field is missing, ask the user for the name instead of guessing.

In the owning repo:

```bash
git worktree add .worktrees/<name> -b <name>   # first run: branch doesn't exist yet
git worktree add .worktrees/<name> <name>      # resuming: branch already exists
```

If `.worktrees/<name>` already exists, this is a resumed session — reuse it. Move into that worktree; every step below runs there.

## 3. Read the repo

Before writing anything, read the target repo's own `AGENTS.md`, manifests, and CI configuration. Every command used in the steps below comes from what's actually there.

## 4. Build test-first

Use `/tdd` at the seams the issue names (or the seams you infer from its requirements). Run typechecking and the relevant test files regularly while building each seam; run the full test suite once, at the end, after the last seam lands.

## 5. Review and commit

Run `/code-review` against the issue as the spec. Apply its findings. Commit on the claimed branch with a Conventional Commits message referencing the issue number.

## Edge cases

No test tooling exists in the repo at all → proceed with whatever validation the repo does define.
