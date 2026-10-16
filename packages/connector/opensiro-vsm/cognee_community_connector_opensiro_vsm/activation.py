"""Fail-closed, atomic *selection* of a verified immutable Cognee dataset generation.

This does not mutate or delete Cognee datasets. Every generation MUST be imported
into a fresh dataset and independently audited before publication.

Single-host filesystem contract: same-filesystem os.replace, fcntl advisory lock,
fsync file/parent. Not a distributed consensus or cross-host deployment protocol.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .source import SHA40, SourceError

POINTER_SCHEMA = "opensiro-vsm-active-generation/v1"
AUDIT_SCHEMA = "opensiro-vsm-independent-audit/v1"


def stable_bytes(payload: dict) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf8")


def json_object(path: Path) -> dict:
    try:
        parsed = json.loads(path.read_text(encoding="utf8"))
        if not isinstance(parsed, dict):
            raise ValueError("expected JSON object")
        return parsed
    except (ValueError, OSError, UnicodeError) as ex:
        raise SourceError(f"Invalid verified generation document: {path.name}") from ex


def audit_digest(report: dict) -> str:
    return hashlib.sha256(stable_bytes(report)).hexdigest()


def read_active(root: Path) -> dict | None:
    """Returns active pointer only. Staged datasets never become visible."""
    target = root / "active.json"
    if not target.exists():
        return None
    pointer = json_object(target)
    _validate_pointer(pointer)
    return pointer


def _validate_pointer(pointer: dict):
    if pointer.get("schema") != POINTER_SCHEMA:
        raise SourceError("Unknown active pointer schema")
    if type(pointer.get("sequence")) is not int or pointer["sequence"] < 1:
        raise SourceError("Invalid sequence number")
    for name in ("commit", "dataset", "tag", "audit_sha256", "selection_id"):
        if not isinstance(pointer.get(name), str) or not pointer[name]:
            raise SourceError(f"Invalid pointer {name}")
    if not SHA40.fullmatch(pointer["commit"]):
        raise SourceError("Unpinned commit in active generation")
    if not re_hex64(pointer["audit_sha256"]):
        raise SourceError("Invalid receipt digest")


def re_hex64(value: str) -> bool:
    return len(value) == 64 and all(x in "0123456789abcdef" for x in value)


@dataclass(frozen=True)
class Candidate:
    commit: str
    dataset: str
    tag: str
    expected_count: int
    audit: dict

    def validate(self):
        if not SHA40.fullmatch(self.commit):
            raise SourceError("Candidate requires 40-char pinned SHA")
        if not self.dataset or not self.tag or len(self.dataset) > 160:
            raise SourceError("Missing/too-long generation identifiers")
        if type(self.expected_count) is not int or self.expected_count <= 0:
            raise SourceError("Invalid admitted record count")
        report = self.audit
        if report.get("schema") != AUDIT_SCHEMA or report.get("status") != "PASS":
            raise SourceError("A matching independent Cognee audit PASS is required")
        if report.get("index_commit") != self.commit:
            raise SourceError("Receipt source commit differs")
        if report.get("dataset") != self.dataset or report.get("source_tag") != self.tag:
            raise SourceError("Receipt dataset or source tag differs")
        if (
            report.get("documents") != self.expected_count
            or report.get("accepted_harnesses") != self.expected_count
        ):
            raise SourceError("Receipt source admission cardinality differs")
        if report.get("exact_grades") != self.expected_count * 6:
            raise SourceError("Receipt has incomplete literal function facts")
        if report.get("states_exact") is not True or report.get("source_refs_exact") is not True:
            raise SourceError("Receipt did not prove exact grades + provenance")


def publish(
    root: Path,
    candidate: Candidate,
    expected_selection_id: str | None,
    *,
    inject_failure: str | None = None,
) -> dict:
    """CAS publish, never deleting data or auto-advancing the active generation.

    Caller must independently verify receipt first. Use expected_selection_id to
    prevent stale concurrent writers from overruling a newer generation.
    """
    candidate.validate()
    root = Path(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    guard = root / ".publish.lock"
    with guard.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = read_active(root)
        actual = current["selection_id"] if current else None
        if actual != expected_selection_id:
            raise SourceError("Stale generation publish: compare-and-swap mismatch")
        if current and current["commit"] == candidate.commit:
            if current["dataset"] != candidate.dataset:
                raise SourceError(
                    "Same source commit published under a different generation dataset"
                )
            if current["audit_sha256"] != audit_digest(candidate.audit):
                raise SourceError("Same generation has different independent audit")
            return current  # exact idempotent republish
        if current and current["dataset"] == candidate.dataset:
            raise SourceError("Source changed but target dataset was not freshly staged")
        seq = (current["sequence"] if current else 0) + 1
        receipt_sha = audit_digest(candidate.audit)
        selection_id = hashlib.sha256(
            stable_bytes(
                {
                    "sequence": seq,
                    "commit": candidate.commit,
                    "dataset": candidate.dataset,
                    "tag": candidate.tag,
                    "receipt_sha": receipt_sha,
                }
            )
        ).hexdigest()
        pointer = {
            "schema": POINTER_SCHEMA,
            "sequence": seq,
            "selection_id": selection_id,
            "commit": candidate.commit,
            "dataset": candidate.dataset,
            "tag": candidate.tag,
            "audit_sha256": receipt_sha,
            "admitted": candidate.expected_count,
        }
        target = root / "active.json"
        descriptor, tempname = tempfile.mkstemp(prefix=".staged-pointer-", suffix=".json", dir=root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(stable_bytes(pointer))
                stream.flush()
                os.fsync(stream.fileno())
            if inject_failure == "before_swap":
                raise SourceError("Simulated interruption before pointer swap")
            if inject_failure not in (None, "before_swap"):
                raise SourceError("Unknown fault injection point")
            os.replace(tempname, target)  # the only active-state mutation
            folder_fd = os.open(str(root), os.O_DIRECTORY)
            try:
                os.fsync(folder_fd)
            finally:
                os.close(folder_fd)
        finally:
            if os.path.exists(tempname):
                os.unlink(tempname)
        return read_active(root)
