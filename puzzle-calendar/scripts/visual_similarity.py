"""Deterministic structural-distance heuristic for three known puzzle rulesets.

Sudoku compares occupied clue cells, Nonograms compare the actual 0/1 answer,
and mazes compare the complete internal passage set, ignoring outside openings
and the solution route. Distance is the minimum normalized Hamming distance
over all eight square rotations/reflections (D4). Mask denominators are n*n;
maze denominators count all 2*n*(n-1) possible internal undirected grid edges.

This is a configurable product heuristic, not exhaustive visual equivalence,
human perception, or a proof of puzzle validity/uniqueness. In particular it
does not compare Sudoku digit patterns, Nonogram clue typography, or maze path
experience. Callers must independently verify puzzles and answers first.
The stdlib shape checks here prevent malformed feature data being silently
compared; they do not replace the installed engine's input/rule validation.
Other type/ruleset combinations and different sizes return None (uncovered).
"""
from __future__ import annotations

import math


RULESETS = {"sudoku": "sudoku_classic_v1", "nonogram": "nonogram_bw_v1",
            "maze": "maze_perfect_v1"}


def _signature(puzzle):
    if not isinstance(puzzle, dict):
        raise ValueError("puzzle must be an object")
    kind = puzzle.get("type_id")
    if not isinstance(kind, str) or kind not in RULESETS:
        return None
    rules = puzzle.get("ruleset_version")
    if rules != RULESETS[kind]:
        return None
    params = puzzle.get("params")
    if not isinstance(params, dict):
        raise ValueError("puzzle.params must be an object")
    if kind == "sudoku":
        n = params.get("size")
    else:
        n = params.get("rows")
        if type(params.get("cols")) is not int or params["cols"] != n:
            raise ValueError("structural comparison requires a square grid")
    if type(n) is not int or n < 2:
        raise ValueError("grid size must be an integer of at least 2")
    return kind, rules, n


def _mask(matrix, n, maximum, field):
    if not isinstance(matrix, list) or len(matrix) != n:
        raise ValueError(f"{field} must contain {n} rows")
    result = set()
    for r, row in enumerate(matrix):
        if not isinstance(row, list) or len(row) != n:
            raise ValueError(f"{field} must be a square {n} by {n} list")
        for c, value in enumerate(row):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f"{field} cells must be integers from 0 to {maximum}")
            if value:
                result.add((r, c))
    return frozenset(result)


def _cell(value, n):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(v) is not int or not 0 <= v < n for v in value)):
        raise ValueError("passage endpoints must be in-bounds integer [row, column] lists")
    return tuple(value)


def _passages(puzzle, n):
    clues = puzzle.get("clues")
    if not isinstance(clues, dict) or not isinstance(clues.get("passages"), list):
        raise ValueError("maze clues.passages must be a list")
    result = set()
    for edge in clues["passages"]:
        if not isinstance(edge, dict) or set(edge) != {"from", "to"}:
            raise ValueError("each passage must contain only from and to")
        a, b = _cell(edge["from"], n), _cell(edge["to"], n)
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            raise ValueError("passages must join orthogonally adjacent cells")
        key = tuple(sorted((a, b)))
        if key in result:
            raise ValueError("duplicate undirected passage")
        result.add(key)
    return frozenset(result)


def _feature(puzzle, solution, signature):
    kind, _, n = signature
    if kind == "sudoku":
        return _mask(puzzle.get("clues"), n, n, "sudoku clues")
    if kind == "nonogram":
        return _mask(solution, n, 1, "nonogram solution")
    return _passages(puzzle, n)


def _transform(cell, n, turns, mirrored):
    r, c = cell
    if mirrored:
        c = n - 1 - c
    for _ in range(turns):
        r, c = c, n - 1 - r
    return r, c


def _distance(a, b, signature):
    kind, _, n = signature
    denominator = 2 * n * (n - 1) if kind == "maze" else n * n
    best = denominator
    for mirrored in (False, True):
        for turns in range(4):
            if kind == "maze":
                transformed = {tuple(sorted((_transform(x, n, turns, mirrored),
                                              _transform(y, n, turns, mirrored))))
                               for x, y in b}
            else:
                transformed = {_transform(cell, n, turns, mirrored) for cell in b}
            best = min(best, len(a.symmetric_difference(transformed)))
            if best == 0:
                return 0.0
    return best / denominator


def structural_distance(puzzle_a, solution_a, puzzle_b, solution_b) -> float | None:
    """Return D4-minimized feature distance, or None for uncovered comparisons.

    Malformed supported input raises ValueError. The solutions are used only
    for Nonograms; Sudoku and maze distances deliberately ignore them.
    """
    sa, sb = _signature(puzzle_a), _signature(puzzle_b)
    if sa is None or sb is None or sa != sb:
        return None
    return _distance(_feature(puzzle_a, solution_a, sa),
                     _feature(puzzle_b, solution_b, sb), sa)


def similarity_conflicts(candidate, solution, records, threshold=.10) -> list[dict]:
    """Return all record IDs whose covered distance is strictly below threshold.

    Records are the complete global ledger, not merely the current batch or
    adjacent pages. A finite 0 < threshold <= 1 is required, so exact-zero
    structure is always rejected when this optional check is enabled. None
    distances are uncovered and skipped; callers must report that coverage.
    """
    if (type(threshold) not in (int, float) or not math.isfinite(threshold)
            or not 0 < threshold <= 1):
        raise ValueError("threshold must be a finite number with 0 < threshold <= 1")
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    signature = _signature(candidate)
    feature = None if signature is None else _feature(candidate, solution, signature)
    conflicts = []
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get("puzzle_id"), str)
                or not record["puzzle_id"] or "puzzle" not in record or "solution" not in record):
            raise ValueError("each record requires puzzle_id, puzzle and solution")
        other_signature = _signature(record["puzzle"])
        if signature is None or signature != other_signature:
            continue
        distance = _distance(feature, _feature(record["puzzle"], record["solution"], signature), signature)
        if distance < threshold:
            conflicts.append({"puzzle_id": record["puzzle_id"], "distance": distance})
    return conflicts
