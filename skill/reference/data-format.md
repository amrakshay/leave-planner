# Data format

All files are JSON, UTF-8, dates as `YYYY-MM-DD`. Keys starting with `_` are comments.
Full working examples are in `examples/demo-data/`.

```
data/
  policy.json
  sync-state.json
  2026/
    holidays.json  festivals.json  sheet.json  leaves.json  team-cal.json  long-weekends.json
```

## policy.json

| Key | Meaning |
|---|---|
| `optional_per_year` | Optional holidays allowed per year |
| `cl_lapses_at_year_end` | Show the "CL may lapse" warning |
| `cl_rule_verified` | `false` adds "rule unverified" to the warning |
| `pl_carry_forward_max` | PL above this at year end shows in the lapse warning (`null` to skip) |
| `no_type_means` | Leave type assumed when an email names none (`PL`) |

## sync-state.json

`{"last_refresh": "2026-11-19T09:30:00+05:30", ...}` — the skill may add per-source
fingerprints here. The build reads only `last_refresh`.

## holidays.json

```json
{"source": "calendar", "updated": "<calendar updated time>",
 "holidays": [{"date": "2026-01-26", "name": "Republic Day", "kind": "company"},
              {"date": "2026-01-14", "name": "Makar Sankranti", "kind": "optional"}]}
```

## festivals.json

```json
{"verified": false, "festivals": [{"date": "2026-11-08", "name": "Lakshmi Pujan"}]}
```

## sheet.json

Your own row of the HR sheet only.

| Key | Meaning |
|---|---|
| `drive_id`, `modifiedTime` | Cache key: refetch only when `modifiedTime` changes |
| `as_on` | The sheet's "as on" date |
| `opening`, `accrued`, `available`, `used`, `closing` | `{"PL": n, "CL": n}` |
| `remarks` | Month → remark text, as written in the sheet |
| `exchange` | Exchange column text |
| `dates_in_sheet` | Every leave date the sheet records |

## leaves.json

```json
{"requests": [{"thread_id": "…", "subject": "…", "sent": "2026-11-13",
               "last_message": "2026-11-13", "message_count": 2,
               "dates": ["2026-11-26"], "half_days": [],
               "type": "CL", "status": "approved", "approved_on": "2026-11-13",
               "cancelled_by": "manager"}],
 "swaps": [{"worked": "2026-05-28", "off": "2026-04-03", "note": "…"}]}
```

- `type`: `PL`, `CL`, `Optional`, `Exchange`.
- `status`: `approved`, `pending`, `cancelled`, `declined`.
- The calendar shows approved dates found in `sheet.dates_in_sheet` as "in HR sheet", other
  approved dates as "not yet in HR sheet".

## team-cal.json

```json
{"updated": "…", "events": [{"id": "…", "from": "2026-11-06", "to": "2026-11-11"}]}
```
`to` is inclusive. Only your own events.

## long-weekends.json

```json
{"entries": [{"from": "2026-11-26", "to": "2026-11-29", "days": 4,
              "leaves_needed": ["2026-11-27"], "source": "auto", "kind": "sug", "note": "…"}]}
```

- `source: "auto"` entries are rewritten by every build. `kind` is `free` (no leave needed),
  `plan` (includes your leave) or `sug` (take `leaves_needed` to get it).
- `source: "you"` entries are yours and never changed by the build.

## How balances are worked out

- Projected PL/CL = sheet `closing` − approved leaves of that type not yet in the sheet
  (half days count 0.5).
- Optional used = approved `Optional` requests; pending ones are shown separately.
- Exchanged = number of `swaps`.
