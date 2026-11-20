#!/usr/bin/env python3
"""Build the leave dashboard HTML from local JSON files.

No network access and no third-party packages: the skill fetches data with
Claude's connectors and saves it as JSON; this script only reads that JSON,
works out balances, long weekends and attention items, and writes one
self-contained HTML page.

Usage:
  python3 build.py                      # repo defaults (config.json, data/, leave-dashboard.html)
  python3 build.py --today 2026-11-19   # pretend today is another day
  python3 build.py --where              # print the paths it would use
  python3 build.py --config examples/config.example.json --data examples/demo-data \
                   --out docs/demo.html --today 2026-11-19
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
ROOT = SKILL_DIR.parent
TEMPLATE = SKILL_DIR / "template.html"

APPROVED = {"approved"}
OFF_STATUSES = {"approved", "pending"}  # count as days off when looking for long weekends
MAX_BRIDGE = 2  # suggest at most this many leave days to join two off-blocks
PENDING_NUDGE_DAYS = 5


# ---------- small helpers ----------

def d(s):
    return dt.date.fromisoformat(s)


def iso(x):
    return x.isoformat()


def short(x):
    return f"{x.day} {x.strftime('%b')}"


def dow(x):
    return x.strftime("%a")


def r1(v):
    return round(v + 1e-9, 1)


def load(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with p.open() as f:
        return json.load(f)


def save(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def days(a, b):
    """Inclusive range of dates."""
    x = a
    while x <= b:
        yield x
        x += dt.timedelta(days=1)


def ranges_text(dates):
    """['2026-11-10','2026-11-11','2026-12-04'] -> '10–11 Nov, 4 Dec'."""
    ds = sorted({d(x) if isinstance(x, str) else x for x in dates})
    out, i = [], 0
    while i < len(ds):
        j = i
        while j + 1 < len(ds) and ds[j + 1] - ds[j] == dt.timedelta(days=1):
            j += 1
        a, b = ds[i], ds[j]
        if a == b:
            out.append(short(a))
        elif a.month == b.month:
            out.append(f"{a.day}–{b.day} {b.strftime('%b')}")
        else:
            out.append(f"{short(a)} – {short(b)}")
        i = j + 1
    return ", ".join(out)


# ---------- loading ----------

def load_year(data_dir, year):
    y = Path(data_dir) / str(year)
    return {
        "holidays": load(y / "holidays.json", {"holidays": []}),
        "festivals": load(y / "festivals.json", {"festivals": []}),
        "sheet": load(y / "sheet.json", None),
        "leaves": load(y / "leaves.json", {"requests": [], "swaps": []}),
        "team_cal": load(y / "team-cal.json", {"events": []}),
        "long_weekends": load(y / "long-weekends.json", {"entries": []}),
        "dir": y,
    }


# ---------- core model ----------

class Model:
    def __init__(self, cfg, policy, yd, next_yd, today):
        self.cfg, self.policy, self.today = cfg, policy, today
        self.year = today.year
        self.hol = {h["date"]: h for h in yd["holidays"].get("holidays", [])}
        self.next_hol = {h["date"]: h for h in next_yd["holidays"].get("holidays", [])}
        self.fest = {f["date"]: f["name"] for f in yd["festivals"].get("festivals", [])}
        self.sheet = yd["sheet"]
        self.requests = yd["leaves"].get("requests", [])
        self.swaps = yd["leaves"].get("swaps", [])
        self.events = yd["team_cal"].get("events", [])
        self.lw_file = yd["long_weekends"]
        self.in_sheet = set((self.sheet or {}).get("dates_in_sheet", []))
        self.sheet_as_on = d(self.sheet["as_on"]) if self.sheet and self.sheet.get("as_on") else None

        self.worked = {s["worked"]: s for s in self.swaps}   # company holiday you worked
        self.day = {}       # date -> leave info for the calendar
        for r in self.requests:
            half = set(r.get("half_days", []))
            for x in r.get("dates", []):
                prev = self.day.get(x)
                # a later or stronger request wins over a cancelled one on the same date
                if prev and prev["status"] in ("approved", "pending") and r["status"] not in ("approved", "pending"):
                    continue
                self.day[x] = {"type": r.get("type") or "PL", "status": r["status"], "half": x in half,
                               "req": r}
        self.tc = set()
        for e in self.events:
            for x in days(d(e["from"]), d(e.get("to", e["from"]))):
                self.tc.add(iso(x))

    # -- day classification --
    def company_holiday(self, x):
        k = iso(x)
        h = self.hol.get(k) or self.next_hol.get(k)
        return bool(h and h["kind"] == "company" and k not in self.worked)

    def leave_off(self, x):
        v = self.day.get(iso(x))
        return bool(v and v["status"] in OFF_STATUSES and not v["half"])

    def off(self, x):
        return x.weekday() >= 5 or self.company_holiday(x) or self.leave_off(x)

    def amount(self, x):
        return 0.5 if self.day.get(x, {}).get("half") else 1.0

    def code(self, k):
        v = self.day.get(k)
        if not v:
            return None
        s = v["status"]
        if s == "approved":
            return "rec" if k in self.in_sheet else "app"
        return {"pending": "pen", "cancelled": "can", "declined": "dec"}.get(s, "pen")

    def note(self, k):
        v = self.day[k]
        c = self.code(k)
        mgr = self.cfg.get("manager", {}).get("name", "your manager")
        if c == "rec":
            return "Approved, in HR sheet"
        if c == "app":
            return "Approved, not yet in HR sheet"
        if c == "pen":
            sent = v["req"].get("sent")
            return f"Pending, no reply since {short(d(sent))}" if sent else "Pending"
        if c == "can":
            return f"Cancelled by {mgr}" if v["req"].get("cancelled_by") == "manager" else "Cancelled"
        if c == "dec":
            return f"Declined by {mgr}"
        return v["status"]

    # -- balances --
    def balances(self):
        s = self.sheet or {}
        closing = s.get("closing", {})
        avail = s.get("available", {})
        out = {}
        for t in ("PL", "CL"):
            not_in_sheet = [k for k, v in self.day.items()
                            if v["status"] == "approved" and v["type"] == t and k not in self.in_sheet
                            and k.startswith(str(self.year))]
            sheet_val = float(closing.get(t, 0))
            out[t] = {
                "sheet": r1(sheet_val),
                "proj": r1(sheet_val - sum(self.amount(k) for k in not_in_sheet)),
                "max": float(avail.get(t) or max(sheet_val, 1)),
                "not_in_sheet": len(not_in_sheet),
                "pending": len([k for k, v in self.day.items() if v["status"] == "pending" and v["type"] == t]),
            }
        allowed = int(self.policy.get("optional_per_year", 2))
        opt_used = len([k for k, v in self.day.items() if v["type"] == "Optional" and v["status"] == "approved"])
        opt_pen = len([k for k, v in self.day.items() if v["type"] == "Optional" and v["status"] == "pending"])
        out["Optional"] = {"allowed": allowed, "used": opt_used, "pending": opt_pen}
        sw = [s for s in self.swaps]
        out["Exchanged"] = {"used": len(sw),
                            "note": ", ".join(f"{short(d(s['worked']))} ↔ {short(d(s['off']))}" for s in sw)}
        return out

    # -- long weekends --
    def blocks(self, start, end):
        res, cur = [], []
        for x in days(start, end):
            if self.off(x):
                cur.append(x)
            elif cur:
                res.append(cur)
                cur = []
        if cur:
            res.append(cur)
        return res

    def special(self, block):
        """Holidays and leave days inside an off-block."""
        hs = [self.hol.get(iso(x)) or self.next_hol.get(iso(x)) for x in block if self.company_holiday(x)]
        ls = [x for x in block if self.leave_off(x)]
        return [h for h in hs if h], ls

    def auto_long_weekends(self):
        start = dt.date(self.year, 1, 1) - dt.timedelta(days=3)
        end = dt.date(self.year + 1, 1, 31)
        bl = self.blocks(start, end)
        out = []

        for b in bl:
            hs, ls = self.special(b)
            if len(b) >= 3 and (hs or ls):
                if ls:
                    lv = ranges_text(ls)
                    one = f"on {dow(ls[0])} {lv}" if len(ls) == 1 else lv
                    note = (" + ".join(h["name"] for h in hs) + f" + your leave {lv}") if hs else f"Your leave {one}"
                    kind = "plan"
                else:
                    kind = "free"
                    note = f"{hs[0]['name']} on {d(hs[0]['date']).strftime('%A')}"
                out.append({"from": iso(b[0]), "to": iso(b[-1]), "leaves_needed": [], "kind": kind, "note": note})
        # bridge suggestions: join neighbouring off-blocks with up to MAX_BRIDGE leave days
        for i in range(len(bl) - 1):
            a, b = bl[i], bl[i + 1]
            gap = [x for x in days(a[-1] + dt.timedelta(days=1), b[0] - dt.timedelta(days=1))]
            if not gap or len(gap) > MAX_BRIDGE:
                continue
            ha, la = self.special(a)
            hb, lb = self.special(b)
            if not (ha or la or hb or lb):
                continue
            if a[-1] + dt.timedelta(days=1) < self.today:
                continue  # past: nothing left to plan
            if not (ha or hb) and len(gap) > 1:
                continue  # joining only your own leave: suggest single-day bridges only
            total = len(a) + len(gap) + len(b)
            if total < 4:
                continue
            anchor = (ha + hb)
            why = f"join {anchor[0]['name']}" if anchor else f"join your leave on {ranges_text(la + lb)}"
            out.append({"from": iso(a[0]), "to": iso(b[-1]), "leaves_needed": [iso(x) for x in gap],
                        "kind": "sug", "note": f"Take {', '.join(dow(x) + ' ' + short(x) for x in gap)} to {why}"})
        # only keep ones that touch this year
        out = [x for x in out if x["to"] >= f"{self.year}-01-01" and x["from"] <= f"{self.year}-12-31"
               or x["from"].startswith(str(self.year + 1) + "-01")]
        return out

    def long_weekends(self):
        mine = [e for e in self.lw_file.get("entries", []) if e.get("source") == "you"]
        auto = self.auto_long_weekends()
        keys = {(e["from"], e["to"]) for e in mine}
        auto = [a for a in auto if (a["from"], a["to"]) not in keys]
        stored = []
        for a in auto:
            stored.append({"from": a["from"], "to": a["to"], "days": (d(a["to"]) - d(a["from"])).days + 1,
                           "leaves_needed": a["leaves_needed"], "source": "auto", "kind": a["kind"], "note": a["note"]})
        for e in mine:
            e = dict(e)
            e["days"] = (d(e["to"]) - d(e["from"])).days + 1
            e["kind"] = "you"
            stored.append(e)
        stored.sort(key=lambda e: (e["from"], e["to"]))
        return stored

    # -- attention --
    def attention(self):
        items = []
        mgr = self.cfg.get("manager", {}).get("name", "your manager")
        horizon = iso(self.today.replace(day=1))
        approved = sorted(k for k, v in self.day.items() if v["status"] == "approved" and k >= horizon)
        missing_tc = [k for k in approved if k not in self.tc]
        if missing_tc:
            items.append({"icon": "ti-calendar-plus", "tone": "accent",
                          "text": f"{ranges_text(missing_tc)} approved but not on team calendar",
                          "button": "Copy sync command", "cmd": "/leave-dashboard sync-calendar"})
        stray = {}
        for k in sorted(self.tc):
            x = d(k)
            if x.weekday() >= 5 or self.company_holiday(x) or k < horizon:
                continue
            v = self.day.get(k)
            st = v["status"] if v else "none"
            if st != "approved":
                stray.setdefault(st, []).append(k)
        for st, ks in stray.items():
            what = {"pending": "still pending", "cancelled": "but it was cancelled",
                    "declined": "but it was declined", "none": "but there is no leave request"}[st]
            items.append({"icon": "ti-alert-triangle", "tone": "warn",
                          "text": f"Team calendar shows you off {ranges_text(ks)}, {what}",
                          "button": "Copy sync command" if st != "pending" else None,
                          "cmd": "/leave-dashboard sync-calendar"})
        for r in self.requests:
            if r["status"] != "pending":
                continue
            last = r.get("last_message") or r.get("sent")
            if not last:
                continue
            age = (self.today - d(last[:10])).days
            if age >= PENDING_NUDGE_DAYS:
                items.append({"icon": "ti-clock", "tone": "accent",
                              "text": f"No reply from {mgr} on {ranges_text(r['dates'])} for {age} days"})
        not_in = [k for k in approved if k not in self.in_sheet]
        if self.sheet_as_on is not None:
            late = [k for k in not_in if d(k) <= self.sheet_as_on]
            early = [k for k in not_in if d(k) > self.sheet_as_on]
            if late:
                items.append({"icon": "ti-file-alert", "tone": "warn",
                              "text": f"{ranges_text(late)} approved but missing from HR sheet (sheet as on {short(self.sheet_as_on)})"})
            if early:
                items.append({"icon": "ti-file-time", "tone": "muted",
                              "text": f"{ranges_text(early)} not in HR sheet yet (expected)"})
        no_mail = sorted(k for k in self.in_sheet if self.day.get(k, {}).get("status") != "approved")
        if no_mail:
            items.append({"icon": "ti-mail-question", "tone": "warn",
                          "text": f"{ranges_text(no_mail)} in HR sheet but no approval email found"})
        return items

    # -- misc --
    def next_off(self):
        ks = sorted(k for k, v in self.day.items() if v["status"] == "approved" and k >= iso(self.today))
        return ks[0] if ks else None


# ---------- page data ----------

def page_data(m, cfg, policy, synced_at):
    H = {k: ["c" if h["kind"] == "company" else "o", h["name"]] for k, h in {**m.hol, **m.next_hol}.items()}
    L, N = {}, {}
    for k, v in m.day.items():
        L[k] = [("½ " if v["half"] else "") + v["type"], m.code(k)]
        N[k] = m.note(k)
    for k, s in m.worked.items():
        L[k] = ["Working", "swap"]
        N[k] = f"Working day, swapped for {short(d(s['off']))}"
    lw = m.long_weekends()
    b = m.balances()
    lapse = None
    if policy.get("cl_lapses_at_year_end", True):
        lapse = {"date": f"{m.year}-12-31", "verified": bool(policy.get("cl_rule_verified"))}
    nxt = m.next_off()
    return {
        "year": m.year,
        "today": iso(m.today),
        "title": cfg.get("dashboard_title", "Leave planner"),
        "manager": cfg.get("manager", {}).get("name", "your manager"),
        "H": H, "F": m.fest, "L": L, "N": N,
        "TC": sorted(m.tc),
        "LW": [{"f": e["from"], "t": e["to"], "lv": e.get("leaves_needed", []), "k": e["kind"],
                "n": e.get("note", ""), "d": e["days"]} for e in lw],
        "bal": b,
        "lapse": lapse,
        "att": m.attention(),
        "next_off": nxt,
        "sheet_as_on": iso(m.sheet_as_on) if m.sheet_as_on else None,
        "synced_at": synced_at,
        "next_year_holidays": bool(m.next_hol),
    }, lw


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.json"))
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--out", default=str(ROOT / "leave-dashboard.html"))
    ap.add_argument("--today", help="YYYY-MM-DD (default: today)")
    ap.add_argument("--no-write-weekends", action="store_true",
                    help="do not write the recalculated long-weekends.json back")
    ap.add_argument("--where", action="store_true", help="print paths and exit")
    a = ap.parse_args()

    if a.where:
        print(json.dumps({"repo": str(ROOT), "config": a.config, "data": a.data, "out": a.out}, indent=2))
        return 0

    cfg = load(a.config)
    if cfg is None:
        sys.exit(f"Missing config: {a.config}\nCopy examples/config.example.json to config.json and fill it in.")
    today = d(a.today) if a.today else dt.date.today()
    policy = load(Path(a.data) / "policy.json", {})
    yd = load_year(a.data, today.year)
    nyd = load_year(a.data, today.year + 1)
    if yd["sheet"] is None:
        print(f"warning: no sheet.json for {today.year}; balances show 0", file=sys.stderr)

    m = Model(cfg, policy, yd, nyd, today)
    sync = load(Path(a.data) / "sync-state.json", {}) or {}
    data, lw = page_data(m, cfg, policy, sync.get("last_refresh"))

    if not a.no_write_weekends:
        save(yd["dir"] / "long-weekends.json",
             {"_note": "Entries with source 'auto' are recalculated on every build; "
                       "entries with source 'you' are never touched.",
              "entries": [{k: v for k, v in e.items() if k != "kind"} | ({"kind": e["kind"]} if e["source"] == "auto" else {})
                          for e in lw]})

    html = TEMPLATE.read_text().replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(html)
    b = data["bal"]
    print(json.dumps({
        "out": a.out,
        "PL": b["PL"]["proj"], "CL": b["CL"]["proj"],
        "optional": f"{b['Optional']['used']}/{b['Optional']['allowed']} used, {b['Optional']['pending']} pending",
        "attention": [x["text"] for x in data["att"]],
        "long_weekends": len(data["LW"]),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
