"""B15: SIGKILL a disposable child in the native DLT generator, before graph ingest.

No upstream interactions. Only kills the subprocess that this supervisor starts.
Opt-in manual integration test: use a **dedicated new disposable scratch store**.
See docs/validation-b15.md. Never run against a shared/prod Cognee database.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

raw_root = os.environ.get("OPENSIRO_B15_TEST_ROOT")
raw_index = os.environ.get("OPENSIRO_B15_INDEX_REPO")
if not raw_root or not raw_index:
    raise SystemExit("Set OPENSIRO_B15_TEST_ROOT and OPENSIRO_B15_INDEX_REPO")
ROOT = Path(raw_root).resolve()
INDEX = Path(raw_index).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "results").mkdir(exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PIN = os.environ.get("OPENSIRO_B15_INDEX_SHA", "35bc8ab9ed4b42bb8955a6f0684a4f5529a05424")
IDS = ("goose", "langflow", "openjiuwen-core")
STORE = ROOT / "b15-guarded-crash-store"
DLT = ROOT / "b15-guarded-crash-dlt"
MARKER = ROOT / "results/b15_guarded_checkpoint.json"


def env():
    os.environ.update(
        SYSTEM_ROOT_DIRECTORY=str(STORE / "system"),
        DATA_ROOT_DIRECTORY=str(STORE / "data"),
        DLT_DATA_DIR=str(DLT),
        PIPELINES_DIR=str(DLT / "pipelines"),
        COGNEE_SKIP_CONNECTION_TEST="true",
        TELEMETRY_DISABLED="1",
    )
    for x in ("OPENAI_API_KEY", "LLM_API_KEY"):
        os.environ.pop(x, None)


async def child():
    env()
    import threading

    import cognee_community_connector_opensiro_vsm.native as native
    import dlt
    from cognee.tasks.ingestion.dlt_utils import DOCUMENT_SOURCE_ATTR
    from cognee_community_connector_opensiro_vsm.source import read_snapshot

    snapshot = read_snapshot(INDEX, PIN)

    def intercepted_source(records, tag):
        @dlt.resource(name="assessments", primary_key="id", write_disposition="replace")
        def resources():
            for ordinal, r in enumerate(records):
                if ordinal == 1:
                    receipt = {
                        "pid": os.getpid(),
                        "phase": "DLT_GENERATOR_SECOND_NEXT",
                        "records_yielded": 1,
                        "note": "First item was handed to iterator; backend commit is not assured.",
                    }
                    with MARKER.open("x", encoding="utf8") as stream:
                        json.dump(receipt, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    print("B15_CHILD_AT_CHECKPOINT", json.dumps(receipt), flush=True)
                    threading.Event().wait()  # Only supervisor's SIGKILL can continue
                yield {
                    "id": r.external_id,
                    "title": r.project_name + " VSM assessment",
                    "url": r.assessment_url,
                    "content": r.raw_bytes.decode("utf-8"),
                }

        resource = resources()
        setattr(resource, DOCUMENT_SOURCE_ATTR, tag)
        return resource

    native.dlt_source = intercepted_source
    await native.ingest_fresh(
        snapshot,
        IDS,
        "opensiro_b15_guarded_crash",
        "opensiro_b15_guarded_source",
        lexical=True,
        attempt_root=STORE / "stage-attempts",
    )
    raise AssertionError("DLT child was not killed")


def supervisor():
    if STORE.exists() or MARKER.exists():
        raise RuntimeError("Existing B15 crash state; refuse ambiguous second run")
    proc = None
    start = time.monotonic()
    with (ROOT / "results/b15_guarded_child.log").open("wb") as stream:
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "child"],
            cwd=ROOT,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            state = None
            for _ in range(850):
                if MARKER.exists():
                    state = json.loads(MARKER.read_text())
                    if state["pid"] != proc.pid or state["records_yielded"] != 1:
                        raise RuntimeError("Unexpected checkpoint PID/state")
                    break
                if proc.poll() is not None:
                    raise RuntimeError(f"child exited early: {proc.returncode}")
                time.sleep(0.2)
            if state is None:
                raise RuntimeError("DLT checkpoint not reached")
            os.kill(proc.pid, signal.SIGKILL)
            rc = proc.wait(timeout=20)
            if rc != -signal.SIGKILL:
                raise RuntimeError(f"Expected -9, got {rc}")
            report = {
                "status": "PASS_SIGKILL_DURING_DLT_ITERATION",
                "signal": "SIGKILL",
                "exit_code": rc,
                "checkpoint": state,
                "elapsed_s": round(time.monotonic() - start, 3),
            }
            (ROOT / "results/b15_guarded_kill.json").write_text(json.dumps(report, indent=2) + "\n")
            print("B15_RESULT", json.dumps(report), flush=True)
        finally:
            if proc and proc.poll() is None:
                os.kill(proc.pid, signal.SIGKILL)
                proc.wait(timeout=20)


if __name__ == "__main__":
    if sys.argv[1:] == ["child"]:
        asyncio.run(child())
    elif sys.argv[1:] == ["kill"]:
        supervisor()
    else:
        raise SystemExit("Usage: b15_kill_dlt.py kill")
