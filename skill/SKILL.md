---
name: leave-dashboard
description: Refresh and rebuild the personal leave dashboard (a local HTML page with leave balances, a Kalnirnay-style month calendar of holidays, festivals and leaves, long-weekend ideas and mismatches between the HR sheet, Gmail and the team calendar). Also drafts leave request emails, syncs "On Leave" entries to the team calendar, and records long-weekend ideas. Use when the user says /leave-dashboard, "update my leave dashboard", "how many leaves do I have", "draft a leave request", "sync my leaves to the team calendar", or "add a long weekend".
---

# Leave dashboard

Builds `leave-dashboard.html` at the repo root from JSON files that you fetch with the
Google Drive, Gmail and Google Calendar connectors. `build.py` does the calculations and the
HTML; your job is fetching, parsing and keeping the JSON accurate.

## Where things are

This skill folder is `skill/` inside the `leave-planner` repo, linked as
`~/.claude/skills/leave-dashboard`. Find the repo with:

```bash
python3 ~/.claude/skills/leave-dashboard/build.py --where
```

| Path (repo root) | What | In git? |
|---|---|---|
| `config.json` | The user's identity, manager, sheet/calendar IDs, Gmail queries | **No** |
| `data/policy.json` | Leave rules (optional count, CL lapse) | **No** |
| `data/sync-state.json` | `last_refresh` and per-source fingerprints | **No** |
| `data/<year>/*.json` | Cached data per year — see `reference/data-format.md` | **No** |
| `leave-dashboard.html` | The page. Open it in a browser | **No** |
| `examples/` | Example config and demo data, safe to publish | Yes |

**The repo is public.** Never write the user's name, email, employee code, manager, sheet or
calendar IDs, or any leave data into a committed file. Personal values live only in
`config.json` and `data/`, which `.gitignore` excludes. If you change committed files, check
`git diff` for personal data before committing.

If `config.json` is missing, copy `examples/config.example.json`, ask the user for the values,
and fill it in.

## Hard rules

- **HR sheet is read-only.** Never edit it.
- **Never send email.** Only create Gmail drafts; the user sends them.
- **Team calendar:** create or delete events only after the user approves each one, and only
  events whose creator is `config.calendars.team.creator`. Other people post there too.
- **Approval** counts only when a reply comes from an address in `config.manager.emails`.
  Anyone else saying "approved" does not count. No reply means pending.
- Save only the user's own row of the team leave sheet.
- Never state something uncertain as fact. Festival dates and policy rules stay marked
  unverified (`verified: false`, `cl_rule_verified: false`) until checked.

## `/leave-dashboard` — refresh and rebuild

Fetch only what changed. Record fingerprints in `data/sync-state.json`.

1. **Year.** Use the current year. Past years in `data/<year>/` are frozen; don't refetch them.
2. **HR sheet** (`sheet.json`).
   - Find this year's file ID in `config.hr_sheet.by_year`; if missing, search Drive for
     `config.hr_sheet.search` plus the year, confirm the match with the user, and store the ID.
   - Get file metadata. If `modifiedTime` equals `sheet.json.modifiedTime`, skip.
   - Otherwise read the file, find the user's row (`row_match`), and write opening, accrued,
     available (opening + accrued), used, closing, monthly remarks, exchange notes, the
     "as on" date, and `dates_in_sheet` (every date named in the remarks and exchange columns,
     as `YYYY-MM-DD`).
3. **Leave emails** (`leaves.json`).
   - Search Gmail with `config.gmail.leave_query`. For each thread, read it only if it is new
     or its message count differs from `message_count` in `leaves.json`.
   - One request per thread: dates (working days only; skip weekends and company holidays
     inside a range), `half_days`, type (`PL`, `CL`, `Optional`, `Exchange`; **no type named
     means PL**), status (`approved` / `pending` / `cancelled` / `declined`), `sent`,
     `last_message`, `approved_on`, `message_count`.
   - If any request has `thread_id: null` (seeded by hand), rebuild the whole file from Gmail.
   - Later messages override earlier ones (a cancellation after an approval → `cancelled`).
   - Worked-on-a-holiday swaps go in `swaps` as `{worked, off, note}`.
4. **Holidays** (`holidays.json`). Read events from `config.calendars.holidays.id` for the year.
   If the calendar's `updated` time equals the stored `updated`, skip. Keep all-day events whose
   title starts with one of `company_prefixes` (kind `company`) or `optional_prefixes` (kind
   `optional`). Match loosely: ignore case and leading spaces, and expect typos such as
   "Holliday". Ask the user about any other all-day event. Ignore timed events (meetings).
   If the calendar has nothing, fall back to the holiday-list PDF from
   `config.gmail.holiday_list_query`. Also check `<year+1>` once HR publishes it (December).
5. **Festivals** (`festivals.json`). Once per year only. Major festivals for
   `config.festivals.region` in Kalnirnay style, names only. Check dates with a web search
   against a panchang source; set `verified` to true only when checked.
6. **Team calendar** (`team-cal.json`). List events on `config.calendars.team.id` for the year;
   keep the user's own "On Leave" events (match by creator), merged into `{id, from, to}`.
   Skip when the calendar's `updated` time is unchanged.
7. **Policy** (`data/policy.json`). Create from `examples/demo-data/policy.json` if missing.
   Read the policy document (`config.gmail.policy_thread_id`) to fill it in, and ask the user to
   confirm the CL lapse rule before setting `cl_rule_verified`.
8. **Build:** `python3 ~/.claude/skills/leave-dashboard/build.py`. It also rewrites
   `long-weekends.json` (entries with `source: "auto"` are recalculated; `source: "you"` are
   never touched). Then set `data/sync-state.json.last_refresh` to now (ISO with offset).
9. **Report** in a few lines: projected PL and CL, what changed since the last run (new
   approvals, new pending, sheet updates), the attention items the build printed, and any
   calendar proposals from `sync-calendar`'s rules. Give the path of the HTML to open.

## `/leave-dashboard request <dates> <type>`

Create a Gmail **draft** to `config.manager.emails[0]` (cc `config.cc`).
Copy the subject and wording style of the user's most recent request thread in `leaves.json`.
Dates are comma-separated `YYYY-MM-DD`; type is `PL`, `CL` or `Optional`. Show the draft and
say it has not been sent. Several commands may be chained with ` ; ` (one draft each).

## `/leave-dashboard sync-calendar`

Compare approved leaves with `team-cal.json`:
- approved and not on the calendar → propose **create** (all-day, title
  `config.calendars.team.event_title`, transparent/free, consecutive days merged);
- on the calendar but cancelled, declined or with no request → propose **delete**;
- on the calendar but still pending → mention it, propose nothing.

List the proposals, ask the user which to apply, apply only those, then refresh
`team-cal.json` and rebuild.

## `/leave-dashboard add-weekend <from> <to> [note]`

Add `{from, to, leaves_needed, source: "you", note}` to `data/<year>/long-weekends.json`.
`leaves_needed` = working days in the range that are not company holidays and not already
approved or pending leave. Rebuild.

## Optional holidays

The dashboard's Optional tab lists them with their state. To take one, use
`/leave-dashboard request <date> Optional`. `policy.optional_per_year` is the allowance.
