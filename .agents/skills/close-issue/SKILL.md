---
name: close-issue
description: Merge the ready PR opened by open-pr, synchronize the local main checkout, and clean up its worktree and branch, only after explicit confirmation since merging is externally visible. Use when the user wants to merge or land a reviewed PR — also the final stage of /ship.
---

# Close Issue

## 1. Confirm

State what's about to happen — which PR, which issue it closes, which local `main` checkout will be
fast-forwarded, and which worktree and branch get removed — and wait for the user's explicit
confirmation. Do not merge without it.

## 2. Verify it's ready

Check the PR isn't in draft (`gh pr view --json isDraft`). If it still is, stop: it needs `open-pr`'s ready step first.

## 3. Merge

`gh pr merge`. Confirm the linked issue actually closed as a result — if it didn't (e.g. the PR never carried a `Closes #`), flag this instead of treating it as closed.

## 4. Verify Project status

Poll `gh project item-list 1 --owner XDenovo --limit 1000 --format json` by exact content URL for
the merged PR and completed Issue. Check at most 12 times with 5 seconds between attempts. Both
items must reach `Status` exactly `Done`.

Do not update Project fields manually. If either item misses the bounded postcondition, stop after
the successful merge, leave the worktree and branch in place, and report both URLs plus their last
observed statuses.

## 5. Synchronize local main

Resolve the worktree that has `refs/heads/main` checked out from
`git worktree list --porcelain`; do not assume its filesystem path. Before changing it, verify its
working tree is clean with `git status --short`.

Fetch `origin`, fast-forward that checkout with
`git -C <main-worktree> merge --ff-only origin/main`, then verify its `HEAD` equals
`origin/main` and its working tree remains clean.

Never stash, reset, rebase, discard changes, or force the update. If the local `main` worktree is
missing or dirty, the fetch fails, the fast-forward is impossible, or the final verification
fails, stop and report the exact local state. Leave the implementation worktree and branch in
place so the synchronization and cleanup can be resumed safely.

## 6. Clean up

Only once the merge succeeded, the issue is confirmed closed, step 4 reached `Done`, and the local
`main` checkout was synchronized in step 5: remove the implementation worktree
(`git worktree remove .worktrees/<name>`) and delete the branch — local, and remote if the merge
didn't already delete it.

## Edge cases

The merge fails partway → stop; leave the worktree and branch in place rather than cleaning up a change that never landed.
