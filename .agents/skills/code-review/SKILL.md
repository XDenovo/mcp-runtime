---
name: code-review
description: Review a PR, branch, fixed-point diff, or worktree against its originating Issue or spec and repository engineering constraints. Use for standalone code review and as the ship gate reached by implement or open-pr; keep fixes and full validation with the caller.
---

# Code Review

## 1. Lock the scope

Operate as a read-only reviewer: preserve source and external state. Read the target repository's `AGENTS.md`, relevant manifests, scripts, and CI configuration, then resolve the requested target:

- **Pull request**: use its recorded base, head, and provider diff. Limit the review to that PR snapshot.
- **Fixed point, tag, or branch**: verify the ref, pin its merge-base with the requested head (`HEAD` by default), and review that range.
- **Issue and current worktree**: read the Issue's `## Branch` field and confirm the worktree is on that branch. Prefer an existing PR's base; otherwise use the repository's default branch.
- **No explicit target**: use the current worktree only when it represents one coherent change with an unambiguous base; otherwise ask for the target or fixed point.

For a worktree review, inspect the complete snapshot:

```bash
git log <merge-base>..HEAD --oneline
git diff <merge-base>
git status --short
```

The diff covers committed, staged, and unstaged tracked changes. Read every relevant untracked file from the status output as part of the same snapshot.

Return `BLOCKED` for an ambiguous base, unresolved ref, branch mismatch, or empty change set.

Scope is locked when the base, head or worktree snapshot, commit list, and every changed path are accounted for.

## 2. Lock the spec

Select the first authoritative source available:

1. An Issue, PRD, or spec supplied by the caller.
2. The Issue linked from the PR body.
3. Issue references in the branch name or commit messages.
4. A matching repository-local spec explicitly associated with the change.

For a PR, read its body and linked Issue together; use the linked Issue as the requirements source unless the caller names another authority. Return `BLOCKED` when candidate specs conflict and none has precedence.

When no spec exists, continue the engineering-risk pass and mark the Spec axis `NOT EVALUATED` with the reason. Derive requirements only from the selected source.

Spec is locked when one source is named and every requirement and success criterion has been enumerated for review, or when `NOT EVALUATED` records why no source exists.

## 3. Review two independent axes

Run the passes independently and finish both evaluated axes before setting the decision.

### Spec

Trace every requirement and success criterion to changed behavior and tests. Check for:

- missing, partial, or incorrectly implemented requirements;
- unrequested behavior or scope that creates concrete risk;
- uncovered edge cases and acceptance criteria;
- tests that contradict the required behavior or only appear to prove it.

### Engineering risk

Inspect surrounding code, callers, contracts, and tests wherever they can change the interpretation of a diff hunk. Check for:

- correctness and failure paths;
- security, privacy, authorization, and data integrity;
- concurrency, retries, idempotency, and resource handling where relevant;
- compatibility, migrations, public contracts, and operational behavior;
- concrete regression gaps in tests;
- documented repository standards and maintainability risks outside configured tooling.

Account for deleted, generated, and binary files through their consumers, source, or operational impact. Use a narrow repository-defined check only to confirm or reject a suspected finding; leave full lint/test and fixes to the caller.

An axis is complete when every changed path has been evaluated against that axis, each candidate finding has been checked against relevant repository context, and file types that cannot be read directly have had their impact traced.

## 4. Apply the finding gate

Admit a finding only when all of these are true:

- the change introduces the problem or materially worsens it;
- it can affect required behavior, users, security, operations, or safe delivery;
- the diff and surrounding context support the claim;
- the smallest useful changed line or hunk can anchor the report;
- a concrete fix direction exists.

Treat pre-existing defects and unsupported speculation as out of scope, and let configured tooling own formatting and style. Admit a test gap only when a specific changed behavior can regress undetected. Group multiple symptoms of one root cause into one finding.

Assign the lowest accurate priority:

- **P0**: catastrophic data loss, security compromise, or widespread outage risk; stop delivery.
- **P1**: broken requirement or serious, likely correctness or operational failure; fix before delivery.
- **P2**: bounded but real defect, compatibility risk, or concrete regression gap; fix before delivery.

The finding gate is complete when every candidate is either admitted at one priority or discarded, and duplicate symptoms share one root finding.

## 5. Return the ship decision

Use this structure:

```markdown
## Decision

PASS | CHANGES REQUESTED | BLOCKED

Scope: <reviewed base/head, PR, or worktree snapshot>
Spec: <source> | NOT EVALUATED — <reason>
Checks: <targeted commands run, or "None">
Findings: Spec <count>; Engineering risk <count>

## Spec findings

<numbered findings, "No findings.", or "Not evaluated: <reason>.">

## Engineering risk findings

<numbered findings or "No findings.">

## Residual risks

<intentionally unevaluated behavior or unavailable environment, or "None.">
```

Format each finding once:

```markdown
1. [P1] <imperative summary> — `path/to/file:line`
   - Impact: <what fails and for whom>
   - Evidence: <why the changed code causes it>
   - Direction: <smallest credible fix>
```

Any P0-P2 finding yields `CHANGES REQUESTED`. Zero findings across all evaluated axes yields `PASS`; when Spec is `NOT EVALUATED`, the pass applies only to engineering risk and the residual-risks section carries that limitation. A missing spec permits this engineering-only pass. An unsafe scope or unresolved spec conflict yields `BLOCKED`.

The review is complete when the decision matches the finding counts, both axes are explicit, every finding is anchored to a changed line or hunk, and residual risks name all validation intentionally left to the caller.
