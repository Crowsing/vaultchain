---
name: sync-architecture
description: Load ADR + progress log into working memory at the start of every autonomous-build cycle.
---

# Sync Architecture

Read these files into working memory:

1. `docs/architecture-decisions.md` — full file. Pay attention to invariants in the intro, the 13 contexts, and the ADR-001..011 decisions.
2. `.claude/CLAUDE.md` — full file (invariants reminder, loop discipline, taboos).
3. `docs/progress/phase{current}-log.md` — last 30 lines (recent merges, CI failures).

Then proceed back to whatever skill called this one.

If any of these files are missing, halt the cycle with a `_LOOP_FAULT.md` write and Telegram via blocked-state.
