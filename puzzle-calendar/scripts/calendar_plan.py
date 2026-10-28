#!/usr/bin/env python3
"""Plan dates and page ownership; this script does not generate puzzles.

Weekday numbers follow datetime: Monday=0, Sunday=6. ``weekdays`` is an
optional event filter; cadence=weekdays defaults to Monday through Friday
and does not infer public holidays or compensatory working days.
"""
import argparse
import calendar
import copy
from datetime import date, timedelta
import json
from pathlib import Path
import sys


def _date(value, field):
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != value:
        raise ValueError(f"{field} must be a real ISO date (YYYY-MM-DD)")
    return parsed


def _dates(request, name, start, end):
    values = request.get(name, [])
    if not isinstance(values, list):
        raise ValueError(f"{name} must be an array of ISO dates")
    result = {_date(value, name) for value in values}
    if any(day < start or day > end for day in result):
        raise ValueError(f"{name} contains a date outside date_range")
    return result


def _shift(day, offset):
    try:
        return day + timedelta(days=offset)
    except OverflowError as exc:
        raise ValueError("calendar display extends beyond supported ISO dates") from exc


def _week_start(day, first):
    return _shift(day, -((day.weekday() - first) % 7))


def _unit(day, form, first):
    if form == "monthly":
        return day.isoformat()[:7]
    if form == "weekly":
        return _week_start(day, first).isoformat()
    return day.isoformat()


def _record(day, form, first):
    return {"date": day.isoformat(), "weekday": day.weekday(),
            "month": day.isoformat()[:7], "unit_key": _unit(day, form, first)}


def plan_calendar(request):
    """Return a deterministic JSON-compatible plan, or raise ValueError.

    Page dates own only dates in the requested range. Adjacent dates are
    display context and never acquire a second slot on another page.
    """
    if not isinstance(request, dict) or not isinstance(request.get("date_range"), dict):
        raise ValueError("request.date_range must be an object with start and end")
    span = request["date_range"]
    start, end = _date(span.get("start"), "start"), _date(span.get("end"), "end")
    count = (end - start).days + 1
    if count <= 0:
        raise ValueError("date_range.start must not be after date_range.end")
    if count > 3660:
        raise ValueError("date_range must contain at most 3660 days")
    form, cadence = request.get("calendar_form"), request.get("cadence")
    if form not in ("daily", "weekly", "monthly"):
        raise ValueError("calendar_form must be daily, weekly, or monthly")
    if cadence not in ("daily", "weekly", "monthly", "weekdays", "custom"):
        raise ValueError("cadence must be daily, weekly, monthly, weekdays, or custom")
    first, puzzles = request.get("week_start", 0), request.get("puzzles_per_slot", 1)
    if type(first) is not int or first not in (0, 6):
        raise ValueError("week_start must be integer 0 (Monday) or 6 (Sunday)")
    if type(puzzles) is not int or puzzles <= 0:
        raise ValueError("puzzles_per_slot must be a positive integer")
    weekdays = request.get("weekdays", list(range(5)) if cadence == "weekdays" else None)
    if (weekdays is not None or "weekdays" in request) and (
            not isinstance(weekdays, list) or any(type(n) is not int or n not in range(7) for n in weekdays)):
        raise ValueError("weekdays must be an array of integer weekday numbers 0..6")
    custom = _dates(request, "dates", start, end)
    included = _dates(request, "include_dates", start, end)
    excluded = _dates(request, "exclude_dates", start, end)
    if included & excluded:
        raise ValueError("include_dates and exclude_dates must not overlap")
    days = [_shift(start, n) for n in range(count)]
    if cadence == "custom":
        selected = custom
    elif cadence in ("weekly", "monthly"):
        seen, selected = set(), set()
        for day in days:
            key = _unit(day, cadence, first)
            if key not in seen:
                selected.add(day)
                seen.add(key)
    else:
        selected = set(days)
    if weekdays is not None:
        selected = {day for day in selected if day.weekday() in weekdays}
    selected = (selected | included) - excluded
    dates = [_record(day, form, first) for day in days]
    slots = [dict(_record(day, form, first), slot_id=f"slot-{day.isoformat()}", puzzles=puzzles)
             for day in sorted(selected)]
    groups = {}
    for record in dates:
        groups.setdefault(record["unit_key"], []).append(record["date"])
    slot_groups = {}
    for slot in slots:
        slot_groups.setdefault(slot["unit_key"], []).append(slot["slot_id"])
    pages = []
    for key, owned in groups.items():
        anchor = _date(owned[0], "page date")
        if form == "monthly":
            month_first = anchor.replace(day=1)
            month_days = calendar.monthrange(anchor.year, anchor.month)[1]
            offset = (month_first.weekday() - first) % 7
            rows = (offset + month_days + 6) // 7
            display_start, display_count = _shift(month_first, -offset), rows * 7
        elif form == "weekly":
            rows, display_start, display_count = 1, _week_start(anchor, first), 7
        else:
            rows, display_start, display_count = 1, anchor, 1
        display = []
        for n in range(display_count):
            day = _shift(display_start, n)
            display.append({"date": day.isoformat(), "weekday": day.weekday(),
                            "in_unit": _unit(day, form, first) == key,
                            "in_range": start <= day <= end})
        pages.append({"page_id": f"page-{form}-{key}", "unit_key": key,
                      "dates": owned, "slot_ids": slot_groups.get(key, []),
                      "row_count": rows, "display_dates": display})
    plan = {"dates": dates, "slots": slots, "pages": pages,
            "totals": {"dates": count, "events": len(slots),
                       "puzzles": len(slots) * puzzles, "content_pages": len(pages)}}
    return {"spec_version": "1.0", "request": copy.deepcopy(request), "plan": plan}


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument("--request", required=True, help="input JSON request")
    parser.add_argument("--out", required=True, help="new output JSON path; never overwritten")
    try:
        args = parser.parse_args(argv)
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        result = plan_calendar(request)
        payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        with Path(args.out).open("x", encoding="utf-8") as target:
            target.write(payload)
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
