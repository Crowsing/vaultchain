---
description: Clear blocked state on a brief after the operator fixed the input.
argument-hint: <brief-id>
---

# /unblock-brief $1

## Step 1: Verify currently blocked

```bash
python -c "
import yaml, frontmatter
m = yaml.safe_load(open('docs/briefs/manifest.yaml'))
b = next((x for x in m['briefs'] if x['id'] == '$1'), None)
if not b:
    print('ERROR: no brief named $1'); raise SystemExit(1)
if b['state'] != 'blocked':
    print(f'ERROR: $1 is in state {b[\"state\"]!r}, not blocked'); raise SystemExit(1)
print('OK')
"
```

## Step 2: Transition + remove blocked note

```bash
python scripts/transition_brief_state.py $1 ready
PHASE=$(echo $1 | cut -c1-6)
rm "${PHASE}-briefs/blocked/$1.md"
python scripts/gen_manifest.py
git add ${PHASE}-briefs/blocked/ ${PHASE}-briefs/$1.md docs/briefs/
git commit -m "chore: unblock $1"
git push origin main
```

## Step 3: Confirm

```bash
git log --oneline -1
```

The next `/loop /autonomous-build` cycle will pick up the brief.
