---
name: autonomous-build
description: Use when /loop /autonomous-build fires. Processes ONE brief per invocation; self-paces via ScheduleWakeup; halts at phase boundaries.
---

# Autonomous Build (main loop)

You are inside the autonomous build loop. ONE invocation = ONE brief processed (or one halt-decision).

## Algorithm

1. Run `/sync-architecture` (loads ADR + last 3 progress entries into working memory).

2. Read `docs/briefs/manifest.yaml`:

   ```bash
   python -c "import yaml,sys; print(yaml.safe_dump(yaml.safe_load(open('docs/briefs/manifest.yaml'))))"
   ```

3. Branch on `phase_state`:
   - `awaiting_N_approval` → `ScheduleWakeup(1800, "phase-gate awaits user")`; halt cycle.
   - `complete` → halt loop permanently. Do NOT call ScheduleWakeup.
   - `in_progress` → continue.

4. Compute ready briefs:
   ```python
   ready = [b for b in briefs
            if b.phase == manifest.current_phase
            and b.state == "ready"
            and all(d.state == "merged" for d in b.depends_on)]
   ```

   - If `ready == []`:
     - If any brief in current phase is `blocked` → `ScheduleWakeup(1800, "blockers")`; halt cycle.
     - If all briefs in current phase are `merged` → execute phase-gate flow (step 12) then halt.

5. Sort `ready` by `(complexity_rank, id)` — `S < M < L`. Pick `brief = ready[0]`.

6. Claim:
   ```bash
   git checkout -b feature/<brief.id>
   python scripts/transition_brief_state.py <brief.id> in_progress
   git add phase{N}-briefs/<brief.id>.md docs/briefs/manifest.yaml docs/briefs/dependency-graph.mmd
   git commit -m "chore: claim <brief.id>"
   git push -u origin feature/<brief.id>
   ```

7. Invoke `/work-on-brief <brief.id>` and capture outcome.

8. Outcome routing:
   - `success` → state already `review` (auto-merge will fire). `ScheduleWakeup(120, "CI running on <brief.id>")`. Halt cycle.
   - `needs-iteration` → `/handle-ci-failure` (max 2 iterations).
     - After 2nd failure → `/enter-blocked-state` then halt.
   - `blocked` → `/enter-blocked-state` then halt.

9. After auto-merge fires (next cycle picks up the merged state — `manifest-on-merge.yml` workflow updates frontmatter to `state: merged`).

10. `ScheduleWakeup(60, "next brief")`. Halt cycle.

11. (Phase-gate flow, used in step 4 when current phase is fully merged):

    ```bash
    python scripts/phase_summary.py <current_phase>
    # writes docs/progress/phase{N}-summary.md

    # update phase pointer
    python -c "
    import yaml
    p = yaml.safe_load(open('docs/briefs/phase_pointer.yaml'))
    next_phase = p['current_phase'] + 1
    if next_phase > 4:
        p['phase_state'] = 'complete'
    else:
        p['phase_state'] = f'awaiting_{next_phase}_approval'
    open('docs/briefs/phase_pointer.yaml','w').write(yaml.safe_dump(p, sort_keys=False))
    "
    python scripts/gen_manifest.py
    git add docs/briefs/phase_pointer.yaml docs/briefs/manifest.yaml docs/progress/
    git commit -m "chore: phase ${current_phase} complete; awaiting approval"
    git push origin main || (git checkout -b chore/phase${current_phase}-complete && git push -u origin chore/phase${current_phase}-complete && gh pr create --fill && gh pr merge --auto --squash)
    ```

    The `notify-phase-complete.yml` workflow handles Telegram. Halt loop here — wait for `/approve-phase <N+1>`.

## Throughout the cycle

- Never call ScheduleWakeup with delaySeconds < 60 or > 3600.
- Always pass the same `/loop /autonomous-build` prompt back to ScheduleWakeup so the next firing re-enters this skill.
- If you discover an unrecoverable error not covered above, write a Telegram-style entry to `phase{N}-briefs/blocked/<brief.id>.md` (or `_LOOP_FAULT.md` if no current brief) and halt.

## Output discipline

Print a short status line at the start and end of each cycle:
```
[autonomous-build] cycle N: claimed phase2-custody-001
[autonomous-build] cycle N: success → review; sleeping 120s for CI
```
