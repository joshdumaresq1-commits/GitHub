<command-name>morning-briefing</command-name>

# Morning Briefing Skill

Fetches today's Gmail primary inbox and Google Calendar, prioritizes all action items
from high to low, and prepends the result to MonoNote.md under today's date.

Each task gets feedback checkboxes (Priority, Relevance) and status checkboxes
(Done, Bump, Cancelled).

---

## Instructions

When this skill is invoked, do the following in order:

### 1. Check Dependencies

Run:
```bash
python3 -c "import google.auth, googleapiclient" 2>&1
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

### 3. Fetch Data

Run the fetch script in JSON mode (status messages go to stderr, JSON to stdout):

```bash
python3 scripts/morning_briefing/fetch_and_brief.py --json 2>&1 >/tmp/morning-briefing-data.json; cat /tmp/morning-briefing-data.json
```

If the script exits non-zero, report the error and stop.

### 4. Prioritize

Read `/tmp/morning-briefing-data.json`. It contains:
```json
{"today": "YYYY-MM-DD", "emails": [...], "events": [...]}
```

Analyze the emails and events yourself. Apply these rules:

**Actor check — do this first for every item:**
- Read the email carefully to determine who needs to take action.
- Josh's email is josh.dumaresq1@gmail.com. Only include an item as a Josh action if Josh is the one who needs to act.
- If someone else is the actor (e.g. a lawyer sending a DocuSign to a third party, a family member handling something, a colleague managing a deal), mark it as a monitor/FYI item instead:
  - Use the title format: `Monitor — <what's happening> (<who is handling it>)`
  - Set source_type to "email" and due_hint to "whenever" unless there's a specific date Josh needs to check in by
- Forwarded emails often mean Josh is being kept in the loop, not asked to act — treat these as monitors unless the forward explicitly asks Josh to do something.

**Inclusion rules:**
- Only include items where Josh needs to act OR monitor progress on something he cares about
- Calendar events count as tasks only if they need prep, a reply, or represent a commitment
- Emails that are purely FYI with no needed response should be omitted entirely
- Older unarchived emails imply they still need attention — include them

**Priority rubric:**
  - **HIGH** = deadline today/tomorrow, waiting on Josh, meeting prep needed, financial/legal/urgent
  - **MEDIUM** = needs a response this week, meeting in next few days, follow-up needed
  - **LOW** = can wait, informational but needs acknowledgement, low-stakes, monitoring only

### 5. Write to MonoNote.md

Find the MonoNote.md file (check `./MonoNote.md` first, then `~/MonoNote.md`).

Prepend a section in this exact format:

```markdown
## YYYY-MM-DD

### Morning Briefing

#### High Priority

- [ ] <concise imperative action — Josh is the actor>
  - Source: Email — <subject> (<sender>)
  - Due: today
  - Priority:   [ ] High  [ ] Medium  [ ] Low
  - Relevance:  [ ] Relevant  [ ] Skip
  - Status:     [ ] Done  [ ] Bump  [ ] Cancelled

#### Medium Priority

- [ ] <concise imperative action>
  - Source: Calendar — <event name>
  - Due: this week
  - Priority:   [ ] High  [ ] Medium  [ ] Low
  - Relevance:  [ ] Relevant  [ ] Skip
  - Status:     [ ] Done  [ ] Bump  [ ] Cancelled

#### Low Priority

- [ ] Monitor — <what's happening> (<who is handling it>)
  - Source: Email — <subject> (<sender>)
  - Note: <one sentence on what to watch for or when to follow up>
  - Due: whenever
  - Priority:   [ ] High  [ ] Medium  [ ] Low
  - Relevance:  [ ] Relevant  [ ] Skip
  - Status:     [ ] Done  [ ] Bump  [ ] Cancelled

---

```

Only include sections that have tasks. Use the Edit or Write tool to prepend this block
to MonoNote.md (insert after line 1, which is the `# MonoNote` header and the comment line).

### 6. Report Results

Show the top 80 lines of MonoNote.md:
```bash
head -80 MonoNote.md
```

Summarize:
- How many tasks were generated
- How many came from email vs. calendar
- Which file was updated

### 7. Handle Errors

| Error | Action |
|-------|--------|
| `No Google credentials found` | Tell user to set `GOOGLE_CREDENTIALS_JSON` env var or run `setup_auth.py` |
| `Token expired` / refresh fails | Delete `~/.config/morning-briefing/token.json`, clear `GOOGLE_TOKEN_JSON` env var, re-run `setup_auth.py` |
| `MonoNote.md` not found | Create it in cwd; tell user where |
| SSL error | Already patched in the script; if it recurs, re-run the script once to repatch certifi |

---

## Optional Arguments

- `/morning-briefing` — auto-detects MonoNote.md
- `/morning-briefing --dry-run` — prints briefing to chat, does not write to file
