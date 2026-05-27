<command-name>morning-briefing</command-name>

# Morning Briefing Skill

Fetches today's Gmail primary inbox and Google Calendar, prioritizes all action items
from high to low using Claude, and prepends the result to MonoNote.md under today's date.

Each task gets feedback checkboxes (Priority, Relevance) and status checkboxes
(Done, Bump, Cancelled).

---

## Instructions

When this skill is invoked, do the following in order:

### 1. Check Dependencies

Run:
```bash
python3 -c "import google.auth, googleapiclient, anthropic" 2>&1
```

If the import fails, install:
```bash
pip install -r scripts/morning_briefing/requirements.txt
```

### 2. Check for Google Auth

Check whether a token exists — either the env var or the token file:
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

If the result is MISSING, tell the user:

> Google authorization is not set up yet. Run the one-time setup:
>
> ```bash
> python3 scripts/morning_briefing/setup_auth.py
> ```
>
> **Web/cloud users:** You also need to set two environment variables that survive
> across sessions. In your Claude Code web environment settings, add:
>
> - `GOOGLE_CREDENTIALS_JSON` — the full contents of your credentials JSON file
> - `GOOGLE_TOKEN_JSON` — printed at the end of the setup script above
>
> After setup, re-run `/morning-briefing`.

Then stop until the user re-invokes the skill.

### 3. Run the Briefing Script

```bash
python3 scripts/morning_briefing/fetch_and_brief.py
```

If the user passed a path (e.g. `/morning-briefing ~/notes/MonoNote.md`):
```bash
python3 scripts/morning_briefing/fetch_and_brief.py --mononote <path>
```

If the user passed `--dry-run`:
```bash
python3 scripts/morning_briefing/fetch_and_brief.py --dry-run
```

### 4. Report Results

After the script finishes, show the top ~60 lines of MonoNote.md:
```bash
head -60 MonoNote.md
```

Summarize:
- How many tasks were generated
- How many came from email vs. calendar
- Which file was updated

### 5. Handle Errors

| Error | Action |
|-------|--------|
| `No Google credentials found` | Tell user to set `GOOGLE_CREDENTIALS_JSON` env var or run `setup_auth.py` |
| `Token expired` / refresh fails | Delete `~/.config/morning-briefing/token.json`, clear `GOOGLE_TOKEN_JSON` env var, re-run `setup_auth.py` |
| `MonoNote.md` not found | Script creates it in cwd; tell user where |
| JSON parse error | Re-run with `--dry-run` to inspect raw Claude output, then report |

---

## Output Format in MonoNote.md

```markdown
## 2026-05-27

### Morning Briefing

#### High Priority

- [ ] Reply to Sarah — Q2 budget approval needed by EOD
  - Source: Email — "Q2 Budget Review" (sarah@company.com)
  - Due: today
  - Priority:   [ ] High  [ ] Medium  [ ] Low
  - Relevance:  [ ] Relevant  [ ] Skip
  - Status:     [ ] Done  [ ] Bump  [ ] Cancelled

#### Medium Priority

- [ ] Prepare slides for Thursday design review
  - Source: Calendar — Design Review (Thu 10am)
  - Due: this week
  - Priority:   [ ] High  [ ] Medium  [ ] Low
  - Relevance:  [ ] Relevant  [ ] Skip
  - Status:     [ ] Done  [ ] Bump  [ ] Cancelled

#### Low Priority

...

---
```

---

## Optional Arguments

- `/morning-briefing` — auto-detects MonoNote.md
- `/morning-briefing ~/path/to/MonoNote.md` — uses specified path
- `/morning-briefing --dry-run` — prints briefing to chat, does not write to file
