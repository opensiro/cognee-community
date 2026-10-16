"""B16 real SIGKILL after one independently visible committed dlt SQLite load job.

Experimental multi-resource DLT package with 3 canonical VSM assessments (one per table).
Supervised subprocess only; uses disposable path from environment. No upstream writes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

raw_root = os.environ.get("OPENSIRO_B16_TEST_ROOT")
raw_index = os.environ.get("OPENSIRO_B16_INDEX_REPO")
if not raw_root or not raw_index:
    raise SystemExit("Set OPENSIRO_B16_TEST_ROOT and OPENSIRO_B16_INDEX_REPO")
ROOT = Path(raw_root).resolve()
INDEX = Path(raw_index).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "results").mkdir(exist_ok=True)
PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
PIN = "35bc8ab9ed4b42bb8955a6f0684a4f5529a05424"
IDS = ("goose", "langflow", "openjiuwen-core")
DBNAME = "opensiro_b16_committed_partial"
TAG = "opensiro_b16_source"
STOREDIR = ROOT / "b16-sigkill-store"
DLTDIR = ROOT / "b16-sigkill-dlt"
MARKER = ROOT / "results/b16_sql_commit_checkpoint.json"
ACTIVE = ROOT / "b16-active-control"


def dbpath():
    # Derived from Cognee get_dlt_destination() and _extract_dlt_schema()
    return STOREDIR / "system" / "databases" / f"dlt_database_{DBNAME}__{DBNAME}"


def inspect_committed_rows():
    path = dbpath()
    if not path.exists():
        return {"path": str(path), "tables": {}, "total": 0}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.8)
    try:
        names = [
            row[0]
            for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not row[0].startswith(("_dlt_", "sqlite_"))
        ]
        user = {}
        for name in names:
            if not name.startswith("b16_assessment_"):
                continue
            q = '"' + name.replace('"', '""') + '"'
            user[name] = con.execute(f"SELECT count(*) FROM {q}").fetchone()[0]
        return {"path": str(path), "tables": user, "total": sum(user.values())}
    finally:
        con.close()


def prepare():
    os.environ.update(
        SYSTEM_ROOT_DIRECTORY=str(STOREDIR / "system"),
        DATA_ROOT_DIRECTORY=str(STOREDIR / "data"),
        DLT_DATA_DIR=str(DLTDIR),
        PIPELINES_DIR=str(DLTDIR / "pipelines"),
        COGNEE_SKIP_CONNECTION_TEST="true",
        TELEMETRY_DISABLED="1",
        LOAD__WORKERS="1",
    )
    for n in ("OPENAI_API_KEY", "LLM_API_KEY"):
        os.environ.pop(n, None)


async def child():
    prepare()
    import cognee_community_connector_opensiro_vsm.native as native
    import dlt
    from cognee.tasks.ingestion.dlt_utils import DOCUMENT_SOURCE_ATTR
    from cognee_community_connector_opensiro_vsm.source import read_snapshot
    from dlt.destinations.impl.sqlalchemy.load_jobs import SqlalchemyJsonLInsertJob

    snapshot = read_snapshot(INDEX, PIN)

    # Three real dlt resources/tables: each has one pinned canonical source record.
    # This creates multiple independent SQLite load jobs inside one dlt.pipeline.run.
    def multi_resource(records, tag):
        arr = []
        for index, record in enumerate(records):

            def resource_iter(r=record):
                yield {
                    "id": r.external_id,
                    "title": r.project_name + " VSM assessment",
                    "url": r.assessment_url,
                    "content": r.raw_bytes.decode("utf8"),
                }

            arr.append(
                dlt.resource(
                    resource_iter,
                    name=f"b16_assessment_{index}",
                    primary_key="id",
                    write_disposition="replace",
                )
            )

        @dlt.source(name="b16_multi_source", section="b16")
        def build_source():
            return arr

        source = build_source()
        setattr(source, DOCUMENT_SOURCE_ATTR, tag)
        return source

    native.dlt_source = multi_resource

    original = SqlalchemyJsonLInsertJob.run
    gate = threading.RLock()
    control = {"job_completed": 0}

    def intercept(self):
        # This lock serializes all 3 experimental table jobs and holds later ones
        # while supervisor verifies that one job has committed.
        with gate:
            result = original(self)  # includes commit_transaction() before returning
            name = getattr(getattr(self, "table", None), "name", "")
            if name.startswith("b16_assessment_"):
                control["job_completed"] += 1
                visible = inspect_committed_rows()  # separate SQLite RO connection
                print(
                    "B16_LOAD_JOB_COMMITTED",
                    json.dumps(
                        {"table": name, "job_count": control["job_completed"], "visible": visible}
                    ),
                    flush=True,
                )
                if control["job_completed"] == 1:
                    # Must observe committed row in an independent connection.
                    if visible["total"] != 1:
                        raise AssertionError(f"Missing first committed row: {visible}")
                    checkpoint = {
                        "pid": os.getpid(),
                        "phase": "AFTER_FIRST_SQL_JOB_COMMIT",
                        "completed_jobs": 1,
                        "expected_jobs": 3,
                        "visibility": visible,
                    }
                    with MARKER.open("x", encoding="utf8") as stream:
                        json.dump(checkpoint, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    print("B16_READY_FOR_SIGKILL", json.dumps(checkpoint), flush=True)
                    threading.Event().wait()
            return result

    SqlalchemyJsonLInsertJob.run = intercept
    await native.ingest_fresh(
        snapshot, IDS, DBNAME, TAG, lexical=True, attempt_root=STOREDIR / "stage-attempts"
    )
    raise AssertionError("Child completed unexpectedly without kill")


def supervise():
    if MARKER.exists() or STOREDIR.exists() or ACTIVE.joinpath("active.json").exists():
        raise RuntimeError("Existing B16 state, refusing to reuse")
    proc = None
    t = time.monotonic()
    logfile = ROOT / "results/b16_child.log"
    with logfile.open("wb") as stream:
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "child"],
            cwd=ROOT,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            receipt = None
            while time.monotonic() - t < 170:
                if MARKER.exists():
                    receipt = json.loads(MARKER.read_text())
                    if (
                        receipt["pid"] != proc.pid
                        or receipt["completed_jobs"] != 1
                        or receipt["visibility"]["total"] != 1
                    ):
                        raise RuntimeError("Unexpected checkpoint or wrong PID")
                    # check from supervisor's independent SQLite reader
                    here = inspect_committed_rows()
                    if here["total"] != 1:
                        raise RuntimeError(
                            f"Supervisor did not see precisely 1 committed row: {here}"
                        )
                    break
                if proc.poll() is not None:
                    raise RuntimeError(f"Child exited unexpectedly: {proc.returncode}")
                time.sleep(0.2)
            if receipt is None:
                raise RuntimeError("No first-job SQLite commit checkpoint")
            os.kill(proc.pid, signal.SIGKILL)
            code = proc.wait(timeout=20)
            if code != -signal.SIGKILL:
                raise RuntimeError(f"Expected -9, got {code}")
            after = inspect_committed_rows()
            if after["total"] != 1:
                raise RuntimeError(f"Partial SQL commit not durable after process kill: {after}")
            report = {
                "status": "PASS_REAL_KILL_AFTER_ONE_SQL_COMMIT",
                "signal": "SIGKILL",
                "exit_code": code,
                "before": receipt["visibility"],
                "after": after,
                "completed_jobs": receipt["completed_jobs"],
                "expected_jobs": 3,
                "elapsed_s": round(time.monotonic() - t, 3),
            }
            (ROOT / "results/b16_kill.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            )
            print("B16_RESULT", json.dumps(report), flush=True)
        finally:
            if proc and proc.poll() is None:
                os.kill(proc.pid, signal.SIGKILL)
                proc.wait(timeout=20)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("kill", "child"))
    args = parser.parse_args()
    if args.mode == "kill":
        supervise()
    else:
        asyncio.run(child())
