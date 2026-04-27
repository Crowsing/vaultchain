---
name: enter-blocked-state
description: Mark the current brief blocked, write a structured blocked-note, push, halt the loop.
---

# Enter Blocked State

Argument: `<brief-id>` (defaults to current branch's brief).

## Step 1: Write the blocked note

File path: `phase{N}-briefs/blocked/<brief-id>.md` (canonical location per spec §5.2).

Content template:

```markdown
# BLOCKED: <brief-id>

**Blocked at:** <UTC ISO timestamp>
**Branch:** <current branch>
**Last commit:** <git rev-parse --short HEAD>

## What was tried
<bullet list of attempts>

## What failed
<CI log excerpt OR ADR contradiction OR error trace; max 60 lines>

## What input is needed from the human
<specific question — keep first line under 100 chars; the notify-blocked workflow uses this as the Telegram body>

## Suggested next step
<your best guess at the resolution path>
```

## Step 2: Mutate state

```bash
python scripts/transition_brief_state.py <brief-id> blocked
git add phase{N}-briefs/blocked/<brief-id>.md \
        phase{N}-briefs/<brief-id>.md \
        docs/briefs/manifest.yaml docs/briefs/dependency-graph.mmd
git commit -m "chore: block <brief-id> [BLOCKED]"
git push
```

## Step 3: Halt the loop

Do NOT call ScheduleWakeup. The loop terminates. `notify-blocked.yml` triggers via path filter and pings Telegram.

## When NOT to use this skill

- For recoverable CI failures → use `/handle-ci-failure` first (max 2 iterations).
- For ADR conflicts that require ADR amendments → still use this; the operator amends the ADR offline, then `/unblock-brief`.
