#!/usr/bin/env python3
"""Evaluate current evidence and build deterministic, explicitly separated releases."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import zipfile

PUBLIC = {"calendar", "rules", "calibration", "punch_guide", "preview", "print_notes", "sources"}
PRIVATE = {"request_data", "plan", "records", "board", "information", "renderer_manifest",
           "layout_report", "qa", "design", "other_private"}
KINDS = {"content", "pdf", "visual", "user_acceptance", "physical_print", "human_difficulty"}
STATUSES = {"passed", "failed", "pending", "not_requested"}
VISUAL = {"hierarchy", "readability", "style", "spacing", "writing_space"}


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _basis(job):
    return _sha(json.dumps({"request": job["request"], "brief": job.get("brief", {})},
                           sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def _positive(value):
    return type(value) is int and value > 0


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _path(root, value):
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise ValueError("artifact path must be a relative POSIX path")
    parts = value.split("/")
    if len(parts) < 2 or parts[0] != "artifacts" or any(p in ("", ".", "..") for p in parts):
        raise ValueError("artifact path must stay inside artifacts/")
    candidate = root.joinpath(*PurePosixPath(value).parts).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("artifact path escapes task root")
    if not candidate.is_file():
        raise FileNotFoundError("artifact path is not a file")
    return candidate


def _range(value):
    if not isinstance(value, dict) or set(value) != {"start", "end"}:
        raise ValueError("date scope needs start and end")
    for key in ("start", "end"):
        if not isinstance(value[key], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[key]):
            raise ValueError("date scope must use YYYY-MM-DD")
    start, end = date.fromisoformat(value["start"]), date.fromisoformat(value["end"])
    if start > end:
        raise ValueError("date scope is reversed")
    return start, end


def _criteria(review, index):
    checks = review.get("criteria")
    required = VISUAL if review["kind"] == "visual" else set()
    good = (isinstance(checks, dict) and bool(checks) and required <= checks.keys()
            and all(isinstance(v, dict) and v.get("status") == "passed" and _text(v.get("notes"))
                    for v in checks.values()))
    if not good or review["kind"] != "visual":
        return good
    coverage = review.get("coverage", {})
    if not isinstance(coverage, dict):
        return False
    for ident in review["scope"]:
        if index[ident]["role"] not in {"calendar", "answers"}:
            continue
        row, count = coverage.get(ident, {}), index[ident].get("page_count")
        if not isinstance(row, dict) or not _positive(count) or row.get("page_count") != count or not _text(row.get("method")):
            return False
        pages, enlarged = row.get("reviewed_pages"), row.get("enlarged_pages")
        if not isinstance(pages, list) or any(type(p) is not int for p in pages) or sorted(pages) != list(range(1, count + 1)):
            return False
        if not isinstance(enlarged, list) or any(type(p) is not int or p not in pages for p in enlarged):
            return False
    return True


def _audience(artifact, index):
    role = artifact["role"]
    if role != "preview":
        return "player" if role in PUBLIC else "answers" if role == "answers" else "private"
    ids = artifact.get("source_pdf_ids", [])
    sources = {index[i]["role"] for i in ids if i in index} if isinstance(ids, list) and all(_text(i) for i in ids) else set()
    return "player" if sources and sources <= PUBLIC - {"preview"} else "answers" if sources == {"answers"} else "private"


def _private_json(value):
    if isinstance(value, dict):
        return bool({"solution", "solutions", "solution_projection", "source_records"} & value.keys()) or any(_private_json(v) for v in value.values())
    return isinstance(value, list) and any(_private_json(v) for v in value)


def evaluate_job(job, root):
    """Read files without mutation; errors block packaging, pending permits a trial."""
    result = {"digital_ready": False, "release_kind": "trial", "errors": [], "pending": [], "stale_reviews": [], "historical_warnings": [], "scope": None,
              "user_acceptance": "not_requested", "physical_print": "not_requested", "human_difficulty": "not_requested"}
    errors, pending = result["errors"], result["pending"]
    root = Path(root).resolve()
    if not root.is_dir():
        errors.append("task root is not a directory")
    if not isinstance(job, dict) or job.get("schema_version") != "2.0" or not _positive(job.get("revision")) or not _text(job.get("job_id")):
        errors.append("invalid job identity/schema/revision")
        return result
    try:
        request = job["request"]
        full = request["requirements"]["date_range"]
        scope = request.get("scope", full)
        start, end = _range(scope)
        first, last = _range(full)
        if start < first or end > last:
            raise ValueError("scope exceeds requested date range")
        result["scope"] = dict(scope)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append("invalid request scope: " + str(exc))
    artifacts, reviews = job.get("artifacts"), job.get("reviews")
    if not isinstance(artifacts, list) or not isinstance(reviews, list):
        errors.append("artifacts and reviews must be lists")
        return result
    index, paths, payloads = {}, set(), {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            errors.append("artifact must be an object")
            continue
        ident = artifact.get("id")
        if not _text(ident) or ident in index:
            errors.append("invalid or duplicate artifact id: " + str(ident))
            continue
        if not _text(artifact.get("role")) or artifact["role"] not in PUBLIC | PRIVATE | {"answers"}:
            errors.append("unknown artifact role: " + ident)
            continue
        index[ident] = artifact
        if type(artifact.get("active", True)) is not bool:
            errors.append("artifact active must be boolean: " + ident)
        if not _positive(artifact.get("revision")) or artifact["revision"] > job["revision"]:
            errors.append("invalid artifact revision: " + ident)
        try:
            path = _path(root, artifact.get("path"))
            if path in paths:
                raise ValueError("duplicate artifact file")
            paths.add(path)
            data = path.read_bytes()
            payloads[ident] = data
            if not _hash(artifact.get("sha256")) or _sha(data) != artifact["sha256"]:
                raise OSError("SHA256 mismatch")
            if type(artifact.get("bytes")) is not int or len(data) != artifact["bytes"]:
                raise OSError("byte count mismatch")
            if artifact.get("role") in {"calendar", "answers"} and path.suffix.lower() != ".pdf":
                raise ValueError("calendar/answers must be PDF")
        except OSError as exc:
            (errors if artifact.get("active", True) else result["historical_warnings"]).append("artifact " + ident + ": " + str(exc))
        except (TypeError, ValueError) as exc:
            errors.append("artifact " + ident + ": " + str(exc))
    all_index, index = index, {i: a for i, a in index.items() if a.get("active", True)}
    targets = {i for i, a in index.items() if a.get("role") in {"calendar", "answers"}}
    answer_hashes = {a.get("sha256") for a in all_index.values() if a.get("role") == "answers" and _hash(a.get("sha256"))}
    for ident, artifact in index.items():
        if _audience(artifact, index) == "player":
            if _hash(artifact.get("sha256")) and artifact["sha256"] in answer_hashes:
                errors.append("public artifact duplicates known answer bytes: " + ident)
            try:
                if _private_json(json.loads(payloads.get(ident, b""))):
                    errors.append("public artifact contains private solution JSON: " + ident)
            except (ValueError, UnicodeError):
                pass
    for role in ("calendar", "answers"):
        if not any(a.get("role") == role for a in index.values()):
            pending.append("missing " + role + " PDF")
    preview_ids = set()
    for ident, artifact in index.items():
        if artifact.get("role") != "preview":
            continue
        ids, hashes = artifact.get("source_pdf_ids"), artifact.get("source_pdf_sha256")
        if not isinstance(ids, list) or not ids or any(not _text(i) for i in ids) or len(ids) != len(set(ids)) or not isinstance(hashes, dict) or set(hashes) != set(ids):
            errors.append("invalid preview binding: " + ident)
            continue
        valid = True
        for source in ids:
            a = index.get(source, {})
            if not str(a.get("path", "")).lower().endswith(".pdf") or hashes[source] != a.get("sha256"):
                errors.append("preview " + ident + " does not bind current PDF: " + source)
                valid = False
        if valid:
            preview_ids.add(ident)
    if not preview_ids or not any(set(index[i]["source_pdf_ids"]) & targets for i in preview_ids):
        pending.append("missing preview bound to current calendar/answers PDF")
    evidence = {kind: {} for kind in KINDS}
    review_ids = set()
    for review in reviews:
        if not isinstance(review, dict):
            errors.append("review must be an object")
            continue
        ident, kind, status = review.get("id"), review.get("kind"), review.get("status")
        if not _text(ident) or ident in review_ids or not _text(kind) or kind not in KINDS or not _text(status) or status not in STATUSES:
            errors.append("invalid review identity/kind/status: " + str(ident))
            continue
        review_ids.add(ident)
        ids, hashes = review.get("scope"), review.get("artifact_sha256")
        if not isinstance(ids, list) or any(not _text(i) or i not in all_index for i in ids) or len(ids) != len(set(ids)) or not isinstance(hashes, dict) or set(hashes) != set(ids) or any(not _hash(v) for v in hashes.values()):
            errors.append("invalid review scope/hash map: " + ident)
            continue
        if not _positive(review.get("revision")) or review["revision"] > job["revision"]:
            errors.append("invalid review revision: " + ident)
            continue
        stale_basis = status == "passed" and (review.get("delivery_scope") != result["scope"] or review.get("basis_sha256") != _basis(job))
        if stale_basis or review.get("invalidated_by_revision") is not None or review.get("invalidated_reason") or any(i not in index or hashes[i] != index[i].get("sha256") for i in ids):
            result["stale_reviews"].append(ident)
            if kind in {"user_acceptance", "physical_print", "human_difficulty"}:
                result[kind] = "pending"
            continue
        documented = _text(review.get("notes")) and _text(review.get("reviewer"))
        valid = documented and (kind not in {"content", "pdf", "visual"} or _criteria(review, index))
        state = status if status != "passed" or valid else "pending"
        for source in ids:
            evidence[kind][source] = state
        if kind in {"user_acceptance", "physical_print", "human_difficulty"}:
            result[kind] = state if state != "passed" or targets <= set(ids) else "pending"
    for kind in ("content", "pdf", "visual"):
        missing = sorted(i for i in targets if evidence[kind].get(i) != "passed")
        if missing:
            pending.append(kind + " review incomplete: " + ", ".join(missing))
    result["digital_ready"] = not errors and not pending
    result["release_kind"] = "ready" if result["digital_ready"] else "trial"
    return result


def _zip(path, entries):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system, info.external_attr = 3, 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)


def _public_names(index):
    buckets, names = {}, {}
    for artifact in sorted(index.values(), key=lambda a: (a["path"], a["id"])):
        audience = _audience(artifact, index)
        if audience != "private":
            buckets.setdefault((audience, artifact["role"]), []).append(artifact)
    for (_, role), artifacts in buckets.items():
        for number, artifact in enumerate(artifacts, 1):
            suffix = Path(artifact["path"]).suffix.lower()
            suffix = suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin"
            serial = f"-{number:02d}" if len(artifacts) > 1 or role == "preview" else ""
            names[artifact["id"]] = role.replace("_", "-") + serial + suffix
    return names


def build_release(job, root, destination):
    """Build a new release from registered bytes; never change the source job."""
    evaluation = evaluate_job(job, root)
    if evaluation["errors"]:
        raise ValueError("release refused: " + "; ".join(evaluation["errors"]))
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("release destination must be new: " + str(destination))
    groups = {"player": {}, "answers": {}, "private": {"job.json": _json(job)}}
    rows, index = [], {a["id"]: a for a in job["artifacts"] if a.get("active", True)}
    public_names = _public_names(index)
    for a in sorted(job["artifacts"], key=lambda a: a["path"]):
        try:
            data = _path(Path(root).resolve(), a["path"]).read_bytes()
            if _sha(data) != a["sha256"] or len(data) != a["bytes"]:
                raise OSError("registered bytes changed")
        except OSError as exc:
            if a.get("active", True):
                raise ValueError("artifact changed during release: " + a["id"]) from exc
            data = None
        members = ["private"] if data is not None else []
        if a.get("active", True) and _audience(a, index) != "private":
            members.append(_audience(a, index))
        package_members = {}
        for group in members:
            member = a["path"] if group == "private" else public_names[a["id"]]
            groups[group][member] = data
            package_members[group + ".zip"] = member
        rows.append({**a, "packages": sorted(package_members), "package_members": package_members,
                     "packaged_sha256": _sha(data) if data is not None else None})
    readme = ("Puzzle Calendar " + evaluation["release_kind"] + " release\n"
              "digital_ready=" + str(evaluation["digital_ready"]).lower() + "\n"
              "Digital evidence applies only to the recorded scope.\n"
              "player.zip: player materials; answers.zip: separate answers; private.zip: production records.\n"
              "User acceptance, physical print and human difficulty remain independent:\n" +
              "\n".join(k + "=" + evaluation[k] for k in ("user_acceptance", "physical_print", "human_difficulty")) +
              "\nVerify manifest.json with manifest.sha256; the manifest and its sidecar exclude themselves.\n").encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".calendar-release-", dir=destination.parent) as scratch:
        stage = Path(scratch)
        (stage / "README.txt").write_bytes(readme)
        for group, entries in groups.items():
            _zip(stage / (group + ".zip"), entries)
        files = [{"path": p.name, "bytes": p.stat().st_size, "sha256": _sha(p.read_bytes())}
                 for p in sorted(stage.iterdir())]
        manifest = {"schema_version": "2.0", "job_id": job["job_id"], "revision": job["revision"],
                    "evaluation": evaluation, "artifacts": rows, "files": files,
                    "self_hash_exclusions": ["manifest.json", "manifest.sha256"]}
        raw = _json(manifest)
        (stage / "manifest.json").write_bytes(raw)
        (stage / "manifest.sha256").write_text(_sha(raw) + "  manifest.json\n", encoding="utf-8")
        if destination.exists():
            raise FileExistsError("release destination appeared during build")
        stage.rename(destination)
    return {**evaluation, "destination": str(destination), "manifest": str(destination / "manifest.json"), "manifest_sha256": _sha(raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="new release directory; omit to evaluate only")
    args = parser.parse_args()
    try:
        job = json.loads(args.job.read_text(encoding="utf-8"))
        result = build_release(job, args.job.parent, args.output) if args.output else evaluate_job(job, args.job.parent)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result["errors"] else 0
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
