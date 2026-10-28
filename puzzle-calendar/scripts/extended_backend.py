#!/usr/bin/env python3
"""Read-only bridge to optional local puzzle sources; prove every new instance.

Registry readiness means prerequisites exist, never annual generation stability.
Workers have a process-group wall budget; generated evidence stays in a new job.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys

sys.dont_write_bytecode = True
UPSTREAM = ("slitherlink", "hashi", "hitori", "masyu", "tents", "fillomino", "slant", "futoshiki",
            "net", "rect", "dominosa", "lightup", "map", "galaxies", "keen", "towers", "magnets",
            "signpost", "range", "unruly", "tracks", "palisade", "undead", "mosaic")
EIGHT = ("star_battle", "nurikabe", "lits", "heyawake", "nurimisaki", "kakuro", "battleship", "numberlink")
MAPPING = dict(slitherlink="loopy", hashi="bridges", hitori="singles", masyu="pearl", fillomino="filling", futoshiki="unequal")
# These exact variants use an actual Hard level in the bundled upstream C
# sources. They are candidate specifications, not human difficulty calibration.
# Preserve the legacy defaults; opt in for a particular production job only.
CHALLENGE_VARIANTS = {
    "slitherlink": "10x10t0dh", "hashi": "7x7i30e10m2d2",
    "slant": "8x8dh", "lightup": "7x7b20s4d2", "towers": "5dh",
    "dominosa": "6dh", "tracks": "8x8dh", "keen": "5dh",
}

def profile_catalog():
    path = Path(__file__).resolve().parents[1] / 'data/puzzle-profiles.json'
    return {row['type_id']: row for row in json.loads(path.read_text())['profiles']}


def difficulty_metadata(type_id, actual_variant):
    row = profile_catalog().get(type_id, {})
    reviewed = row.get('reviewed_variants', [row.get('variant')])
    configured = actual_variant is not None and actual_variant in reviewed
    result = {'label': 'unrated', 'source_params': actual_variant,
              'upstream_difficulty': row.get('upstream_difficulty') if configured else
                  'Hard' if actual_variant == CHALLENGE_VARIANTS.get(type_id) and type_id in CHALLENGE_VARIANTS else None,
              'human_calibration': 'pending'}
    if configured:
        result['profile_variant'] = actual_variant
    return result


def select_profiles(source_project, *, difficulty='challenge', max_types=None):
    if difficulty not in ('challenge', 'mixed'):
        raise ValueError('difficulty must be challenge or mixed')
    if max_types is not None and (type(max_types) is not int or max_types < 1):
        raise ValueError('max_types must be positive')
    available = {row['type_id']: row for row in list_capabilities(source_project)}
    selected, excluded = [], []
    for row in profile_catalog().values():
        reason = None
        review = row['source_review']
        source_file = Path(source_project).resolve() / review['source_path']
        if not source_file.is_file() or _sha(source_file) != review['sha256']:
            reason = 'reviewed source changed or missing'
        elif not available[row['type_id']]['prerequisites_available']:
            reason = 'missing prerequisites'
        elif not row['enabled']:
            reason = row.get('disabled_reason', 'bounded probe failed')
        elif difficulty == 'challenge' and not row['challenge_candidate']:
            reason = 'difficulty remains uncalibrated; available for explicit selection'
        if reason:
            excluded.append({'type_id': row['type_id'], 'reason': reason})
        else:
            selected.append(copy.deepcopy(row))
    # Interleave play families rather than repeat only numeric or path puzzles.
    buckets = {family: [r for r in selected if r['family'] == family]
               for family in dict.fromkeys(r['family'] for r in selected)}
    ordered = []
    while any(buckets.values()):
        for bucket in buckets.values():
            if bucket:
                ordered.append(bucket.pop(0))
    if max_types is not None:
        for row in ordered[max_types:]:
            excluded.append({'type_id': row['type_id'], 'reason': 'requested maximum type count'})
        ordered = ordered[:max_types]
    if not ordered:
        raise ValueError('no eligible profiles: ' + json.dumps(excluded, ensure_ascii=False))
    return {'types': [r['type_id'] for r in ordered],
            'variants': {r['type_id']: r['variant'] for r in ordered if r['variant'] is not None},
            'selected_profiles': ordered, 'excluded': excluded,
            'difficulty': difficulty, 'human_calibration': 'pending',
            'scope': 'candidate profiles; each generated instance still requires fresh proof and page fit'}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _dump(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog(root):
    path = root / "outputs/Puzzle-Paper-Capabilities.json"
    return {row["type_id"]: row for row in json.loads(path.read_text())["types"]} if path.is_file() else {}


def resolve_variant(type_id, variant, source_project):
    """Return a known rules-compatible spec, refusing unreviewed overrides."""
    profile = profile_catalog().get(type_id, {})
    reviewed = profile.get('reviewed_variants', [profile.get('variant')])
    if variant is not None and variant in reviewed:
        review = profile['source_review']
        reviewed_file = Path(source_project).resolve() / review['source_path']
        if not reviewed_file.is_file() or _sha(reviewed_file) != review['sha256']:
            raise ValueError('reviewed parameter source changed; re-review this profile')
    if type_id not in UPSTREAM:
        if variant is not None and (variant not in reviewed or type_id not in EIGHT[:5]):
            raise ValueError('unsupported expanded variant; use a reviewed size')
        return variant
    default = "5x5" if type_id == "fillomino" else _catalog(Path(source_project).resolve()).get(type_id, {}).get("tested_variant")
    if variant is None:
        return default
    allowed = {value for value in [default, CHALLENGE_VARIANTS.get(type_id), *reviewed] if isinstance(value, str)}
    if not isinstance(variant, str) or variant not in allowed:
        raise ValueError("unsupported variant for " + type_id + "; use a reviewed exact specification")
    return variant


def list_capabilities(source_project):
    root = Path(source_project).resolve()
    catalog = _catalog(root)
    common = [root / "scripts/sample35/upstream.py", root / "scripts/sample35/eight.py",
              root / "scripts/sample35/verify_upstream.py", root / "outputs/Puzzle-Paper-Capabilities.json",
              root / "work/cspuz-deps/venv/lib/python3.12/site-packages/z3/__init__.py"]
    rows = []
    for kind in UPSTREAM + EIGHT:
        needed = list(common)
        if kind in UPSTREAM:
            game = MAPPING.get(kind, kind)
            needed += [root / "work/paper-probe/build" / game,
                       root / "work/tatham-source/puzzles-20260923.616da16" / (game + ".c")]
        else:
            needed += [root / "work/cspuz-deps/venv/bin/python",
                       root / ("work/cspuz-probe/smoke_one.py" if kind in EIGHT[:5] else "work/gap-three-probe/probe.py")]
        missing = [str(path) for path in needed if not path.is_file()]
        if kind in UPSTREAM and kind not in ("range", "undead", "mosaic", "fillomino") and not shutil.which("gs"):
            missing.append("Ghostscript executable: gs")
        for package in ("pypdf", "reportlab"):
            if importlib.util.find_spec(package) is None:
                missing.append("Python package: " + package)
        rows.append({"type_id": kind, "name_zh": catalog.get(kind, {}).get("name_zh", kind),
                     "backend": "upstream" if kind in UPSTREAM else "expanded",
                     "candidate": True, "prerequisites_available": not missing,
                     "missing_prerequisites": missing, "fresh_verification_mechanism": True,
                     "support_scope": "candidate_variant_requires_fresh_instance_proof",
                     "variant": "5x5" if kind == "fillomino" else catalog.get(kind, {}).get("tested_variant"),
                     "challenge_variant": CHALLENGE_VARIANTS.get(kind),
                     "challenge_upstream_difficulty": "Hard" if kind in CHALLENGE_VARIANTS else None,
                     "difficulty": "unrated", "physical_print_test": "pending"})
    for row in rows:
        row['profile'] = copy.deepcopy(profile_catalog().get(row['type_id']))
    return rows


def _run_worker(action, payload, timeout):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "__worker", action],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, env=env, start_new_session=True)
    try:
        stdout, stderr = proc.communicate(json.dumps(payload), timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = proc.communicate()
        raise TimeoutError(f"extended {action} exceeded {timeout}s wall budget; {stderr[-500:]}") from exc
    if proc.returncode:
        raise RuntimeError(f"extended {action} failed: {stderr[-3000:] or stdout[-3000:]}")
    return json.loads(stdout.splitlines()[-1])


def generate_extended(type_id, seed, output_dir, source_project, timeout_seconds=120, *, variant=None):
    if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    if type(seed) not in (str, int):
        raise ValueError("seed must be a string or integer")
    root, destination = Path(source_project).resolve(), Path(output_dir).resolve()
    if destination == root or root in destination.parents:
        raise ValueError("output_dir must be outside the read-only source project")
    capabilities = {row["type_id"]: row for row in list_capabilities(root)}
    if type_id not in capabilities or not capabilities[type_id]["prerequisites_available"]:
        raise ValueError("unsupported type or missing prerequisites: " + str(capabilities.get(type_id, type_id)))
    resolve_variant(type_id, variant, root)
    if destination.exists():
        raise ValueError("output_dir must be new; existing jobs are never overwritten")
    destination.mkdir(parents=True, exist_ok=False)
    payload = dict(type_id=type_id, seed=seed, output_dir=str(destination), source_project=str(root), timeout_seconds=timeout_seconds)
    if variant is not None:
        payload["variant"] = variant
    _dump(destination / "request.json", payload)
    try:
        record = _run_worker("generate", payload, timeout_seconds)
        _dump(destination / "record.json", record)
        return record
    except (RuntimeError, TimeoutError, ValueError) as exc:
        _dump(destination / "failure.json", {"state": "failed", "error": str(exc), "request": payload})
        raise


def verify_extended(record, source_project, timeout_seconds=120):
    try:
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        return _run_worker("verify", {"record": record, "source_project": str(Path(source_project).resolve()), "timeout_seconds": timeout_seconds}, timeout_seconds)
    except (RuntimeError, TimeoutError, ValueError) as exc:
        return {"unique_verified": False, "answer_rule_checked": False, "method": "fresh verification failed",
                "evidence": {}, "errors": [str(exc)]}


def _modules(root):
    return (_load("calendar_upstream", root / "scripts/sample35/upstream.py"),
            _load("calendar_eight", root / "scripts/sample35/eight.py"),
            _load("calendar_verifier", root / "scripts/sample35/verify_upstream.py"))


def _eight_model(kind, raw, eight):
    """Rebuild public-clue constraints without running any generator."""
    import z3 as Z
    if kind in EIGHT[5:]:
        gap = _load("calendar_gap", eight.GAP)
        p, answer = raw["puzzle"], raw["answer"]
        if kind == "kakuro":
            solver, variables = gap.kakuro_model(p["row_run_sums"], p["column_run_sums"])
            values = sum(answer, [])
        elif kind == "battleship":
            n = p["grid"][0]
            givens = {g["cell"][0] * n + g["cell"][1]: g["occupied"] for g in p["givens"]}
            solver, variables = gap.battleship_model(n, p["fleet"], p["row_counts"], p["column_counts"], givens)
            values = sum(answer, [])
        else:
            n = p["grid"][0]
            pairs = [(u[0] * n + u[1], v[0] * n + v[1]) for u, v in p["pairs"]]
            solver, variables, edges = gap.numberlink_model(n, pairs)
            chosen = {tuple(sorted((u[0] * n + u[1], v[0] * n + v[1]))) for u, v in answer["undirected_edges"]}
            values = [edge in chosen for edge in edges]
        return solver, variables, values
    source = next((eight.ROOT / "work/cspuz-probe").glob("semiexp-cspuz-*/cspuz")).parent
    sys.path.insert(0, str(source))
    os.environ.update(CSPUZ_DEFAULT_BACKEND="z3", CSPUZ_USE_GRAPH_PRIMITIVE="0")
    import importlib
    from cspuz import Solver
    from cspuz.backend.z3 import Z3Backend
    from cspuz.expr import IntVar
    module = importlib.import_module("cspuz.puzzle." + kind)
    captured, original = [], Solver.solve
    def capture(instance, *args, **kwargs):
        captured.append(instance)
        return False
    Solver.solve = capture
    n = raw["size"][0]
    problem = raw["problem"]
    if kind == "lits":
        # JSON preserves coordinates as arrays; cspuz's indexing API requires
        # coordinate tuples. Restore representation, never clues or rules.
        problem = [[tuple(cell) for cell in room] for room in problem]
    try:
        args = (n, problem, 1) if kind == "star_battle" else (n, n, problem)
        _, answer_vars = getattr(module, "solve_" + kind)(*args)
    finally:
        Solver.solve = original
    cs = captured[-1]
    backend = Z3Backend(cs.variables)
    backend.add_constraint(cs.constraints)
    solver = Z.Solver()
    for variable in cs.variables:
        if isinstance(variable, IntVar):
            zv = backend.variables_dict[variable.id]
            solver.add(variable.lo <= zv, zv <= variable.hi)
    solver.add(backend.converted_constraints)
    return solver, [backend.variables_dict[answer_vars[y, x].id] for y in range(n) for x in range(n)], sum(raw["answer"], [])


def _validation(kind, raw, eight, verifier, timeout):
    verifier.TIMEOUT = min(5000, max(1, int(timeout * 1000 / 4)))
    if kind in UPSTREAM:
        original = verifier.expand
        try:
            if kind == "hashi":
                # bridges.c new_game_sub consumes one digit per island. Scope
                # this correction to this freshly loaded bridge checker only.
                verifier.expand = lambda text, multi=True, empty=None: original(text, False, empty)
            evidence = verifier.MODELS[kind](raw)
            if kind == "hashi":
                evidence["decoder_policy"] = "scoped single-character island digits; bridges.c new_game_sub; original source unchanged"
        finally:
            verifier.expand = original
        good = evidence.get("rules_checked") is True and evidence.get("unique_verified") is True and evidence.get("first_status") == "sat" and evidence.get("second_status") == "unsat"
        return {"unique_verified": good, "answer_rule_checked": evidence.get("rules_checked") is True,
                "method": "fresh independent public-clue Z3 model; supplied answer SAT then alternate answer UNSAT", "evidence": evidence}
    import z3 as Z
    _answer_shape(kind, raw)
    checked = eight.independent_check(kind, raw)
    solver, variables, values = _eight_model(kind, raw, eight)
    if len(variables) != len(values):
        raise ValueError("answer shape differs from the player-answer projection")
    solver.set(timeout=verifier.TIMEOUT)
    solver.push()
    solver.add(*[v == a for v, a in zip(variables, values)])
    first = solver.check()
    solver.pop()
    second = None
    if first == Z.sat:
        solver.add(Z.Or([v != a for v, a in zip(variables, values)]))
        second = solver.check()
    good = checked and first == Z.sat and second == Z.unsat
    return {"unique_verified": bool(good), "answer_rule_checked": bool(checked and first == Z.sat),
            "method": "fresh rebuilt public-clue constraints; supplied player answer SAT then blocking UNSAT; independent rule predicates",
            "evidence": {"first_status": str(first), "second_status": str(second), "independent_rule_check": checked,
                         "player_answer_variables": len(variables), "solver_timeout_ms_per_check": verifier.TIMEOUT}}


def _answer_shape(kind, raw):
    """Predicates inherited from samples may ignore trailing rows/edges."""
    answer = raw["answer"]
    if kind == "numberlink":
        n = raw["puzzle"]["grid"][0]
        edges, seen = answer["undirected_edges"], set()
        for edge in edges:
            if not isinstance(edge, list) or len(edge) != 2 or any(
                    not isinstance(point, list) or len(point) != 2 or
                    any(type(c) is not int or not 0 <= c < n for c in point) for point in edge):
                raise ValueError("malformed answer edge coordinate")
            u, v = edge
            key = tuple(sorted((tuple(u), tuple(v))))
            if sum(abs(a - b) for a, b in zip(u, v)) != 1 or key in seen:
                raise ValueError("answer edges must be distinct orthogonal grid edges")
            seen.add(key)
        return
    shape = raw["puzzle"]["white_area"] if kind == "kakuro" else raw.get("size", raw.get("puzzle", {}).get("grid"))
    rows, columns = shape
    if not isinstance(answer, list) or len(answer) != rows or any(not isinstance(row, list) or len(row) != columns for row in answer):
        raise ValueError("answer must match the exact public grid dimensions")
    if any((type(v) is not int or not 1 <= v <= 9) if kind == "kakuro" else type(v) is not bool for row in answer for v in row):
        raise ValueError("answer cell values have invalid types or ranges")


def _public(kind, raw):
    return {"params": raw["params"], "description": raw["description"]} if kind in UPSTREAM else copy.deepcopy(raw.get("problem", raw.get("puzzle")))


def _paths(root, kind):
    paths = ["scripts/sample35/upstream.py", "scripts/sample35/eight.py", "scripts/sample35/verify_upstream.py", "outputs/Puzzle-Paper-Capabilities.json"]
    if kind in UPSTREAM:
        game = MAPPING.get(kind, kind)
        paths += ["work/paper-probe/build/" + game, "work/tatham-source/puzzles-20260923.616da16/" + game + ".c"]
    else:
        paths.append("work/cspuz-probe/smoke_one.py" if kind in EIGHT[:5] else "work/gap-three-probe/probe.py")
    return {path: _sha(root / path) for path in paths}


def _cell_mm(kind, raw, upstream):
    if kind in EIGHT or kind in ("range", "mosaic", "fillomino"):
        return 12
    if kind == "undead":
        return 20
    text = (upstream.SRC / (raw["upstream_game"] + ".c")).read_text()
    block = re.search(r"static void game_print_size[\s\S]*?\n}", text).group()
    return int(re.search(r"game_compute_size\(params, (\d+),", block).group(1)) / 100


def _custom_board(upstream, raw):
    minimum = {'undead': 16, 'mosaic': 14}.get(raw['type_id'])
    if minimum is None:
        return upstream.custom_board(raw)
    # Preserve geometry and clues; the source specimen's 11pt inventory becomes
    # 8.65pt in the selected A5 area. Raise text in this worker only.
    original = upstream.canvas.Canvas
    class LegibleCanvas(original):
        def setFont(self, name, size, leading=None):
            return super().setFont(name, max(size, minimum), leading)
    upstream.canvas.Canvas = LegibleCanvas
    try:
        return upstream.custom_board(raw)
    finally:
        upstream.canvas.Canvas = original


def _worker(action, payload):
    root, timeout = Path(payload["source_project"]), payload["timeout_seconds"]
    upstream, eight, verifier = _modules(root)
    if action == "verify":
        record = payload["record"]
        kind, raw = record["type_id"], copy.deepcopy(record["raw"])
        errors = []
        if record["source"]["project"] != str(root) or record["source"]["path_hashes"] != _paths(root, kind):
            errors.append("source identity or code hashes changed")
        if _sha(record["board_pdf"]) != record["board_sha256"]:
            errors.append("board SHA256 mismatch")
        from pypdf import PdfReader
        pages = PdfReader(record["board_pdf"]).pages
        dimensions = record["dimensions"]
        if len(pages) != 2 or any(
                abs(float(page.mediabox.width) * 25.4 / 72 - dimensions["width_mm"]) > 0.02 or
                abs(float(page.mediabox.height) * 25.4 / 72 - dimensions["height_mm"]) > 0.02
                for page in pages) or dimensions["cell_mm"] != _cell_mm(kind, raw, upstream):
            errors.append("board dimensions or source cell size mismatch")
        if _public(kind, raw) != record["public_clues"]:
            errors.append("public clues do not match raw puzzle")
        difficulty = record.get("difficulty", {})
        if not isinstance(difficulty, dict):
            return {'unique_verified': False, 'answer_rule_checked': False,
                    'method': 'identity checks', 'evidence': {}, 'errors': ['difficulty must be an object']}
        source_params = raw.get("params", raw.get("size", raw.get("puzzle", {}).get("grid")))
        hard = kind in CHALLENGE_VARIANTS and raw.get("params") == CHALLENGE_VARIANTS[kind]
        profile_variant = raw.get('params') if kind in UPSTREAM else (
            'x'.join(map(str, raw['size'])) if kind in EIGHT[:5] else None)
        expected = difficulty_metadata(kind, profile_variant)
        expected_grade = expected['upstream_difficulty'] if 'profile_variant' in difficulty else ('Hard' if hard else None)
        if (not isinstance(difficulty, dict) or difficulty.get("source_params") != source_params
                or difficulty.get("label") != "unrated"
                or difficulty.get("upstream_difficulty") != expected_grade
                or 'profile_variant' in difficulty and difficulty['profile_variant'] != expected.get('profile_variant')
                or (hard or 'profile_variant' in difficulty) and difficulty.get("human_calibration") != "pending"):
            errors.append("difficulty provenance differs from the actual upstream specification")
        if errors:
            return {"unique_verified": False, "answer_rule_checked": False, "method": "identity checks", "evidence": {}, "errors": errors}
        raw["solution_move" if kind in UPSTREAM else "answer"] = record["solution"]
        return _validation(kind, raw, eight, verifier, timeout)
    kind, seed, destination = payload["type_id"], payload["seed"], Path(payload["output_dir"])
    upstream.BASE = destination
    eight.OUT = destination
    folder = destination / kind
    folder.mkdir(exist_ok=False)
    if kind in UPSTREAM:
        info = _catalog(root)[kind]
        game = MAPPING.get(kind, kind)
        params = resolve_variant(kind, payload.get("variant"), root)
        proc = subprocess.run([str(root / "work/paper-probe/build" / game), params, str(seed), str(folder / "native")],
                              capture_output=True, text=True, timeout=timeout, check=False)
        _dump(folder / "native-command.json", {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        if proc.returncode:
            raise RuntimeError("native generator failed")
        raw = json.loads(proc.stdout)
        if raw.get("params") != params:
            raise ValueError("native generator changed the requested specification; refusing fallback")
        raw.update(type_id=kind, name_zh=info["name_zh"], upstream_game=game)
        name, rules, legend = info["name_zh"], list(upstream.RULES[kind]), upstream.LEGENDS[kind]
        if kind == "dominosa":
            rules[0] = "把上下或左右相邻的两个数字圈成一张多米诺骨牌。"
        if kind == "keen" and params == "5dh":
            rules[0] = "每格填入1至5，每行和每列都恰好出现这五个数字各一次。"
        if kind == 'futoshiki':
            order = int(re.match(r'\d+', params).group())
            rules[0] = f'每格填入1至{order}，每行和每列各数字都恰好出现一次。'
        if kind == 'fillomino':
            rules[0] = '每个格子填入一个正整数，原有数字不能改变。'
        if kind == 'signpost':
            width, height = upstream.dimensions(raw)
            total = width * height
            rules[0] = f'在每格填入1至{total}，每个数字恰好出现一次，保留已知数字。'
            rules[-1] = f'{total}是终点，不需要再指向其他格。'
    else:
        numeric = int(hashlib.sha256(str(seed).encode()).hexdigest(), 16) % (2 ** 31)
        size_variant = resolve_variant(kind, payload.get('variant'), root)
        if size_variant is not None:
            size = int(size_variant.split('x')[0])
            proc = subprocess.run([str(eight.PY), '-B', str(eight.CSP), kind, str(size), str(numeric)],
                                  text=True, capture_output=True, timeout=timeout, check=False,
                                  env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
            (folder / 'generation.log').write_text(proc.stdout + proc.stderr)
            if proc.returncode or not proc.stdout.strip():
                raise RuntimeError('sized expanded generator failed: ' + proc.stderr[-500:])
            raw = json.loads(proc.stdout.splitlines()[-1])
            if raw.get('status') != 'passed' or raw.get('size') != [size, size]:
                raise ValueError('sized generator did not return a proven puzzle at the requested size')
        else:
            raw = eight.generate(kind, numeric)
        name, rules, legend = eight.NAMES[kind], eight.RULES[kind], "答案以原题规则中的数字、填黑、星形或连线表示完整填写。"
    _dump(folder / "raw-evidence.json", raw)
    validation = _validation(kind, raw, eight, verifier, timeout)
    _dump(folder / "fresh-validation.json", validation)
    if not validation["unique_verified"] or not validation["answer_rule_checked"]:
        raise RuntimeError("fresh rule or uniqueness proof failed: " + json.dumps(validation))
    if kind in UPSTREAM:
        geometry = _custom_board(upstream, raw) if kind in ("range", "undead", "mosaic", "fillomino") else upstream.native_board(raw)
        if "cell_mm" not in geometry:
            geometry["cell_mm"] = _cell_mm(kind, raw, upstream)
        dimensions = {"width_mm": geometry["board_width_mm"], "height_mm": geometry["board_height_mm"], "cell_mm": geometry["cell_mm"]}
    else:
        geometry = eight.draw(kind, raw)
        dimensions = {key: geometry[key] for key in ("width_mm", "height_mm", "cell_mm")}
    board = folder / "board.pdf"
    from pypdf import PdfReader
    if len(PdfReader(board).pages) != 2:
        raise ValueError("board PDF must contain exactly puzzle and answer pages")
    actual_variant = raw['params'] if kind in UPSTREAM else ('x'.join(map(str, raw['size'])) if kind in EIGHT[:5] else None)
    difficulty = difficulty_metadata(kind, actual_variant)
    difficulty['source_params'] = raw.get('params', raw.get('size', raw.get('puzzle', {}).get('grid')))
    return {"type_id": kind, "name_zh": name, "seed": seed, "raw": raw, "public_clues": _public(kind, raw),
            "solution": raw["solution_move" if kind in UPSTREAM else "answer"], "board_pdf": str(board.resolve()),
            "board_sha256": _sha(board), "dimensions": dimensions, "rules_zh": rules, "answer_legend": legend,
            "validation": validation, "difficulty": difficulty,
            "source": {"project": str(root), "path_hashes": _paths(root, kind), "backend": "upstream" if kind in UPSTREAM else "expanded"},
            "scope": "verified_instance", "physical_print_test": "pending"}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "__worker":
        try:
            print(json.dumps(_worker(sys.argv[2], json.load(sys.stdin)), ensure_ascii=False))
            return 0
        except Exception as exc:
            print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    for action in ("capabilities", "select", "generate"):
        sub = subs.add_parser(action)
        sub.add_argument("--source-project", required=True)
        if action == "generate":
            sub.add_argument("--type", required=True)
            sub.add_argument("--seed", required=True)
            sub.add_argument("--output-dir", required=True)
            sub.add_argument("--timeout-seconds", type=float, default=120)
            sub.add_argument("--variant", help="Reviewed exact upstream specification; legacy default when omitted")
        if action == 'select':
            sub.add_argument('--difficulty', choices=('challenge', 'mixed'), default='challenge')
            sub.add_argument('--max-types', type=int)
    try:
        args = parser.parse_args()
        if args.action == 'capabilities':
            result = list_capabilities(args.source_project)
        elif args.action == 'select':
            result = select_profiles(args.source_project, difficulty=args.difficulty, max_types=args.max_types)
        else:
            result = generate_extended(args.type, args.seed, args.output_dir, args.source_project, args.timeout_seconds, variant=args.variant)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
