---
description: Open the next phase for autonomous work. Run after reviewing the previous phase summary.
argument-hint: <phase-number>
---

# /approve-phase $1

User intent: "approve transition INTO phase $1." Run this after the loop reports `awaiting_${1}_approval`.

## Step 1: Validate state

```bash
python -c "
import yaml
p = yaml.safe_load(open('docs/briefs/phase_pointer.yaml'))
target = $1
expected = f'awaiting_{target}_approval'
if p['phase_state'] != expected:
    print(f'ERROR: phase_state is {p[\"phase_state\"]!r}, expected {expected!r}')
    raise SystemExit(1)
print(f'OK: ready to enter phase {target}')
"
```

If validation fails → tell the operator the actual state and stop.

## Step 2: Confirm previous phase fully merged

```bash
python -c "
import yaml
m = yaml.safe_load(open('docs/briefs/manifest.yaml'))
prev = $1 - 1
unmerged = [b for b in m['briefs'] if b['phase'] == prev and b['state'] != 'merged']
if unmerged:
    print('ERROR: unmerged briefs in phase', prev, ':', [b['id'] for b in unmerged])
    raise SystemExit(1)
print('OK')
"
```

## Step 3: Update phase pointer

```bash
python -c "
import yaml
p = yaml.safe_load(open('docs/briefs/phase_pointer.yaml'))
p['current_phase'] = $1
p['phase_state'] = 'in_progress'
open('docs/briefs/phase_pointer.yaml','w').write(yaml.safe_dump(p, sort_keys=False))
"
python scripts/gen_manifest.py
git add docs/briefs/phase_pointer.yaml docs/briefs/manifest.yaml docs/briefs/dependency-graph.mmd
git commit -m "chore: approve phase $1"
git push origin main
```

## Step 4: Resume the loop

If `/loop` is still active in this session, the next tick picks up the new state. Otherwise, ask the operator to run `/loop /autonomous-build`.
