#!/usr/bin/env python3
"""Generate dated, verified content records; canonical deduplication only."""
import argparse
import copy
from datetime import date
import importlib
import json
import math
from pathlib import Path
import sys
import time

DEFAULT_TYPES = "sudoku:9,nonogram:5,maze:10"
SCOPE = ["exact", "D4", "sudoku_digit_relabeling"]


def _engine(publisher_dir):
    sibling = Path(__file__).resolve().parents[2] / "puzzle-publisher"
    root = Path(publisher_dir) if publisher_dir else (sibling if sibling.is_dir() else Path.home() / ".codex/skills/puzzle-publisher")
    runtime = (root / "runtime").resolve()
    if not (runtime / "puzzle_engine/api.py").is_file():
        raise ValueError(f"puzzle-publisher engine not found under {root}")
    sys.path.insert(0, str(runtime))
    api = importlib.import_module("puzzle_engine.api")
    if Path(api.__file__).resolve().parent.parent != runtime:
        raise ValueError("a different puzzle engine is already loaded; use a fresh process")
    return api, importlib.import_module("puzzle_engine.common"), importlib.import_module("puzzle_publisher.difficulty")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _choices(types, capabilities):
    if not isinstance(types, str) or not types:
        raise ValueError("types must be a comma-separated type:size list")
    choices = []
    for token in types.split(","):
        name, separator, number = token.strip().partition(":")
        if not separator or not number.isascii() or not number.isdigit():
            raise ValueError("types must use type:integer-size entries")
        size = int(number)
        if name not in capabilities or size not in capabilities[name]["sizes"]:
            raise ValueError(f"unsupported puzzle type or size: {token}")
        if (name, size) in choices:
            raise ValueError("duplicate type:size entry")
        choices.append((name, size))
    return choices


def _slots(plan):
    slots = plan.get("plan", {}).get("slots") if isinstance(plan, dict) and isinstance(plan.get("plan"), dict) else None
    if not isinstance(slots, list):
        raise ValueError("plan.plan.slots must be an array")
    ids, dates = set(), set()
    for slot in slots:
        if not isinstance(slot, dict) or type(slot.get("puzzles")) is not int or slot["puzzles"] != 1:
            raise ValueError("each slot must contain exactly one puzzle (puzzles=1)")
        sid, day = slot.get("slot_id"), slot.get("date")
        if not isinstance(sid, str) or not sid or sid in ids:
            raise ValueError("slot_id must be a unique nonempty string")
        try:
            if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("slot date must be a real ISO date") from exc
        if day in dates:
            raise ValueError("duplicate date cannot receive another global puzzle_id")
        ids.add(sid)
        dates.add(day)
    return slots


def _verified(report, check):
    if report.get("status") != "unique" or report.get("proof_complete") is not True or check.get("valid") is not True:
        return False
    if report.get("proof_method") == "tree":
        checks = report.get("proof_checks")
        return report.get("search_complete") is None and bool(checks) and all(v is True for v in checks.values())
    return report.get("proof_method") == "enumeration" and report.get("search_complete") is True


def generate_records(plan, *, publisher_dir=None, seed="calendar-v1", types=DEFAULT_TYPES,
                     difficulty="easy", max_attempts_per_slot=30, total_timeout=600, reuse=None, limits=None):
    """Return complete records or an incomplete checkpoint; never write files.

    Attempts count calls to generate_batch(count=1), whose own bounded internal
    work is included in the cumulative wall time. Reuse never resets budgets.
    """
    started = time.monotonic()
    api, common, rating = _engine(publisher_dir)
    slots = _slots(plan)
    choices = _choices(types, api.capabilities()["puzzle_types"])
    if type(seed) not in (str, int) or type(max_attempts_per_slot) is not int or max_attempts_per_slot <= 0:
        raise ValueError("seed must be string/integer and max_attempts_per_slot a positive integer")
    if not _finite(total_timeout) or difficulty not in ("easy", "normal", "mixed"):
        raise ValueError("total_timeout must be finite nonnegative; difficulty must be easy, normal, or mixed")
    limits = common.Limits() if limits is None else limits
    if not isinstance(limits, common.Limits):
        raise ValueError("limits must be an engine Limits instance")
    by_id = {s["slot_id"]: s for s in slots}
    attempts = {sid: 0 for sid in by_id}
    spent, rejected, records, hashes, puzzle_ids = 0.0, {}, {}, set(), set()
    if reuse is not None:
        if not isinstance(reuse, dict) or reuse.get("state") not in ("complete", "incomplete") or not isinstance(reuse.get("records"), list):
            raise ValueError("reuse must be complete/incomplete JSON content records")
        old = reuse.get("metrics", {})
        if not isinstance(old, dict) or not _finite(old.get("elapsed_seconds")):
            raise ValueError("reuse metrics must preserve elapsed_seconds")
        spent = old["elapsed_seconds"]
        prior = old.get("attempts_by_slot")
        if not isinstance(prior, dict) or set(prior) - set(by_id):
            raise ValueError("reuse has unexpected slot attempts")
        if any(type(v) is not int or v < 0 for v in prior.values()) or type(old.get("attempts")) is not int or sum(prior.values()) != old["attempts"]:
            raise ValueError("reuse attempts metrics are inconsistent")
        attempts.update(prior)
        rejected = copy.deepcopy(old.get("rejections", {}))
        if not isinstance(rejected, dict) or any(type(v) is not int or v < 0 for v in rejected.values()):
            raise ValueError("reuse rejection metrics are invalid")

    def remaining():
        return total_timeout - spent - (time.monotonic() - started)

    def bounded():
        return common.Limits(limits.max_nodes, min(limits.timeout_seconds, max(0, remaining())))

    def reject(reason):
        rejected[reason] = rejected.get(reason, 0) + 1

    for original in reuse["records"] if reuse else []:
        if not isinstance(original, dict) or original.get("slot_id") not in by_id:
            raise ValueError("reuse contains an unexpected slot")
        record = copy.deepcopy(original)
        sid = record["slot_id"]
        if sid in records:
            raise ValueError("duplicate reused slot")
        if remaining() <= 0:
            raise ValueError("remaining total budget cannot fresh-validate reuse; increase total_timeout explicitly")
        if any(k not in record for k in ("puzzle_id", "puzzle", "solution", "seed", "canonical_hash")):
            raise ValueError("reuse record is missing content identity fields")
        if record.get("date", by_id[sid]["date"]) != by_id[sid]["date"]:
            raise ValueError("reuse date does not match planned slot")
        report = api.solve_puzzle(record["puzzle"], limits=bounded())
        check = api.validate_answer(record["puzzle"], record["solution"])
        if not _verified(report, check) or report.get("solutions") != [record["solution"]]:
            raise ValueError("reused solution/answer failed fresh unique verification")
        digest = api.canonical_hash(record["puzzle"])
        if digest != record["canonical_hash"]:
            raise ValueError("reused canonical_hash does not match public puzzle")
        pid = record["puzzle_id"]
        if not isinstance(pid, str) or not pid or pid in puzzle_ids or digest in hashes:
            raise ValueError("duplicate reused puzzle identity or canonical puzzle")
        level = rating.evaluate_difficulty(record["puzzle"], record["solution"])
        if level["status"] != "rated" or level["label"] not in (("easy", "normal") if difficulty == "mixed" else (difficulty,)):
            raise ValueError("reused puzzle does not match requested difficulty")
        record.update(validation={k: v for k, v in report.items() if k != "solutions"}, difficulty=level)
        record["validation"].update(answer_check=check, puzzle_id=pid, canonical_hash=digest)
        records[sid], hashes, puzzle_ids = record, hashes | {digest}, puzzle_ids | {pid}

    for index, slot in enumerate(slots):
        sid = slot["slot_id"]
        if sid in records:
            continue
        kind, size = choices[index % len(choices)]
        while attempts[sid] < max_attempts_per_slot and remaining() > 0:
            attempt = attempts[sid]
            attempts[sid] += 1
            local_seed = str(common.derived_seed(api.__version__, seed, sid, kind, size, 0, attempt))
            try:
                batch = api.generate_batch(kind, size, 1, local_seed, limits=bounded(), total_timeout_seconds=max(0, remaining()))
            except common.GenerationError:
                reject("generation_error")
                continue
            puzzle = {k: batch["puzzles"][0][k] for k in ("type_id", "ruleset_version", "params", "clues")}
            solution, report = batch["answers"][0]["solution"], copy.deepcopy(batch["validation"][0])
            if not _verified(report, report.get("answer_check", {})):
                reject("verification")
                continue
            level = rating.evaluate_difficulty(puzzle, solution)
            if level["status"] != "rated" or level["label"] not in (("easy", "normal") if difficulty == "mixed" else (difficulty,)):
                reject("difficulty")
                continue
            digest = api.canonical_hash(puzzle)
            if digest in hashes:
                reject("canonical_duplicate")
                continue
            if remaining() <= 0:
                break
            pid = "P" + slot["date"].replace("-", "")
            if pid in puzzle_ids:
                raise ValueError("duplicate global puzzle_id")
            report.update(puzzle_id=pid, canonical_hash=digest)
            records[sid] = dict(slot_id=sid, date=slot["date"], puzzle_id=pid, puzzle=puzzle,
                                solution=solution, validation=report, difficulty=level,
                                canonical_hash=digest, seed=local_seed, regeneration_index=0)
            hashes.add(digest)
            puzzle_ids.add(pid)
            break
        if sid not in records:
            break
    missing = [s["slot_id"] for s in slots if s["slot_id"] not in records]
    result = {"state": "incomplete" if missing else "complete", "engine_version": api.__version__,
              "records": [records[s["slot_id"]] for s in slots if s["slot_id"] in records],
              "deduplication_scope": SCOPE[:], "metrics": {
                  "elapsed_seconds": spent + time.monotonic() - started, "attempts": sum(attempts.values()),
                  "attempts_by_slot": attempts, "rejections": rejected,
                  "solver_limits": {"max_nodes": limits.max_nodes, "timeout_seconds": limits.timeout_seconds},
                  "max_attempts_per_slot": max_attempts_per_slot, "total_timeout_seconds": total_timeout}}
    if missing:
        result["missing_slot_ids"] = missing
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = _Parser(description=__doc__)
    for option in ("plan", "out"):
        parser.add_argument("--" + option, required=True)
    parser.add_argument("--publisher-dir")
    parser.add_argument("--seed", default="calendar-v1")
    parser.add_argument("--types", default=DEFAULT_TYPES)
    parser.add_argument("--difficulty", choices=("easy", "normal", "mixed"), default="easy")
    parser.add_argument("--max-attempts-per-slot", type=int, default=30)
    parser.add_argument("--total-timeout", type=float, default=600)
    parser.add_argument("--reuse")
    try:
        args = parser.parse_args(argv)
        out = Path(args.out)
        checkpoint = out.with_name(out.stem + ".checkpoint.json")
        if out.exists() or out.is_symlink() or checkpoint.exists() or checkpoint.is_symlink():
            raise ValueError("out and checkpoint paths must both be new; existing files are never overwritten")
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        reuse = json.loads(Path(args.reuse).read_text(encoding="utf-8")) if args.reuse else None
        result = generate_records(plan, publisher_dir=args.publisher_dir, seed=args.seed, types=args.types,
                                  difficulty=args.difficulty, max_attempts_per_slot=args.max_attempts_per_slot,
                                  total_timeout=args.total_timeout, reuse=reuse)
        destination = out if result["state"] == "complete" else checkpoint
        with destination.open("x", encoding="utf-8") as target:
            json.dump(result, target, ensure_ascii=False, indent=2, allow_nan=False)
            target.write("\n")
        return 0 if result["state"] == "complete" else 5
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
