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

If the import fails, install dependencies:
```bash
pip install -r scripts/morning_briefing/requirements.txt
```

### 2. Check Google Auth Token

Check whether `~/.config/morning-briefing/token.json` exists:
```bash
ls ~/.config/morning-briefing/token.json 2>/dev/null && echo "EXISTS" || echo "MISSING"
```

If the file is MISSING, tell the user:

> Google authorization is not set up yet. Please run the one-time setup:
>
> ```bash
> python3 scripts/morning_briefing/setup_auth.py
> ```
>
> This will open your browser to authorize Gmail (read-only) and Calendar (read-only) access.
> After authorizing, re-run `/morning-briefing`.

Then stop — do not continue until the user re-invokes the skill after completing setup.

### 3. Run the Briefing Script

Run the fetch script. Accept an optional `--mononote <path>` argument if the user
specified a custom path to their MonoNote.md:

```bash
python3 scripts/morning_briefing/fetch_and_brief.py
```

If the user passed a path (e.g. `/morning-briefing ~/notes/MonoNote.md`), run:
```bash
python3 scripts/morning_briefing/fetch_and_brief.py --mononote <path>
```

### 4. Report Results

After the script finishes, read the first ~60 lines of MonoNote.md and show them
to the user so they can see the briefing that was prepended:

```bash
head -60 MonoNote.md    # or the custom path if provided
```

Summarize what was added:
- How many tasks were generated
- How many came from email vs. calendar
- Which file was updated and where it lives

### 5. Handle Errors

| Error | Action |
|-------|--------|
| `credentials.json not found` | Direct user to run `setup_auth.py` and follow the Cloud Console steps printed by the script |
| `Token expired` | The script auto-refreshes; if refresh fails, delete `~/.config/morning-briefing/token.json` and re-run `setup_auth.py` |
| `MonoNote.md` not found anywhere | The script creates it in the current working directory; tell the user where it was created |
| JSON parse error from Claude | Retry the script once with `--dry-run` to see raw output, then report |

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

The user may invoke with:

- `/morning-briefing` — auto-detects MonoNote.md
- `/morning-briefing ~/path/to/MonoNote.md` — uses specified path
- `/morning-briefing --dry-run` — prints briefing to chat without writing to file
