<command-name>discussion-worthy</command-name>

# Discussion Worthy Skill

Fetches all emails from the Gmail "Discussion Worthy" label, extracts non-repetitive
actionable insights grouped by topic (Health, Fitness, Nutrition, Finance, etc.),
and prepends them to DiscussionWorthy.md.

---

## Instructions

When this skill is invoked, do the following in order:

### 1. Check Dependencies

```bash
python3 -c "import google.auth, googleapiclient, anthropic" 2>&1
```

If the import fails, install:
```bash
pip install -r scripts/morning_briefing/requirements.txt
```

### 2. Check for Google Auth

```bash
python3 -c "
import os, json
from pathlib import Path
token_env = os.environ.get('GOOGLE_TOKEN_JSON', '').strip()
token_file = Path.home() / '.config' / 'morning-briefing' / 'token.json'
if token_env:
    print('ENV_VAR')
elif token_file.exists():
    print('FILE')
else:
    print('MISSING')
"
```

If MISSING, tell the user to run `python3 scripts/morning_briefing/setup_auth.py` and
set `GOOGLE_CREDENTIALS_JSON` / `GOOGLE_TOKEN_JSON` env vars. Then stop.

### 3. Run the Script

```bash
python3 scripts/morning_briefing/discussion_worthy.py
```

With a custom output path:
```bash
python3 scripts/morning_briefing/discussion_worthy.py --note ~/path/to/DiscussionWorthy.md
```

Dry run (prints to chat, does not write):
```bash
python3 scripts/morning_briefing/discussion_worthy.py --dry-run
```

### 4. Report Results

After the script finishes, show the top ~80 lines of DiscussionWorthy.md:
```bash
head -80 DiscussionWorthy.md
```

Summarize:
- How many emails were processed
- How many insights were extracted
- Which categories were found
- Which file was updated

### 5. Commit the output file

After a successful run, commit and push DiscussionWorthy.md:
```bash
git add DiscussionWorthy.md
git commit -m "Update Discussion Worthy insights — $(date +%Y-%m-%d)"
git push
```

### 6. Handle Errors

| Error | Action |
|-------|--------|
| `No Google credentials found` | Set `GOOGLE_CREDENTIALS_JSON` or run `setup_auth.py` |
| `Label 'Discussion Worthy' not found` | Check spelling in Gmail; the label is case-insensitive |
| `Token expired` | Delete `~/.config/morning-briefing/token.json`, clear `GOOGLE_TOKEN_JSON`, re-run `setup_auth.py` |
| JSON parse error | Re-run with `--dry-run` to inspect raw Claude output |

---

## Output Format in DiscussionWorthy.md

```markdown
## Discussion Worthy — 2026-05-28

### Health

- Stay in Zone 2 cardio for base-building; only spike intensity 1–2x/week
- Nasal breathing during low-intensity exercise improves CO2 tolerance over time

### Fitness

- Progressive overload matters more than program variety
- Sleep 7–9 hrs; it's when adaptation actually happens

### Finance

- Keep 6 months of expenses liquid before deploying into illiquid assets
- Dollar-cost averaging beats timing for most non-professional investors

---
```

---

## Optional Arguments

- `/discussion-worthy` — auto-detects or creates DiscussionWorthy.md in cwd
- `/discussion-worthy --note ~/path/to/file.md` — uses specified path
- `/discussion-worthy --dry-run` — prints to chat, does not write
