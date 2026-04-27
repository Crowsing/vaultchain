---
description: Print snapshot of current loop state.
---

# /status

```bash
python -c "
import yaml, subprocess
m = yaml.safe_load(open('docs/briefs/manifest.yaml'))
print(f'Current phase: {m[\"current_phase\"]} ({m[\"phase_state\"]})')
counts = m['counts']['by_state']
print(f'Briefs: {m[\"counts\"][\"total\"]} total · ' + ' · '.join(f'{c} {s}' for s,c in sorted(counts.items())))
"

echo ''
echo 'Last 5 progress log entries:'
for f in docs/progress/phase*-log.md; do
  if [ -f \"\$f\" ]; then
    echo \"-- \$(basename \$f) --\"
    tail -5 \"\$f\"
  fi
done

echo ''
BRANCH=\$(git rev-parse --abbrev-ref HEAD)
echo \"Active branch: \$BRANCH\"

echo ''
echo 'Last CI status:'
gh run list --limit 1 --json conclusion,status,headBranch,name | python -c \"
import json, sys
runs = json.load(sys.stdin)
if not runs: print('(no runs)')
else:
    r = runs[0]
    print(f'  {r[\\\"status\\\"]} / {r[\\\"conclusion\\\"]} on {r[\\\"headBranch\\\"]} ({r[\\\"name\\\"]})')
\"
```
