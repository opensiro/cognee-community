"""B14 isolated real SIGKILL during a Cognee graph-only import.

Supervisor spawns exactly one child inside a disposable store and sends SIGKILL
only after first assessment's graph + six text chunks have returned from native
add_data_points. Parent never signals processes it does not start.

Actions: kill, inspect, recover, verify
No code on upstream GitHub is touched.

Manual integration test, deliberately sends SIGKILL to one process spawned by
this script. Run only against a dedicated disposable workspace, never on a
production/shared Cognee store. Usage is documented in docs/validation-b14.md.

"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Require a dedicated scratch folder, never use the package directory as a DB.
raw_root = os.environ.get("OPENSIRO_B14_TEST_ROOT")
raw_index = os.environ.get("OPENSIRO_B14_INDEX_REPO")
if not raw_root or not raw_index:
    raise SystemExit("Set OPENSIRO_B14_TEST_ROOT and OPENSIRO_B14_INDEX_REPO")
ROOT = Path(raw_root).resolve()
INDEX = Path(raw_index).resolve()
PKG = Path(__file__).resolve().parents[1]
PIN = os.environ.get("OPENSIRO_B14_INDEX_SHA", "35bc8ab9ed4b42bb8955a6f0684a4f5529a05424")
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "results").mkdir(exist_ok=True)
IDS = ("goose", "langflow", "openjiuwen-core")
ACTIVE = ROOT / "b14-active-control"
STORES = {
    "crash": {
        "root": ROOT / "b14-sigkill-store",
        "dlt": ROOT / "b14-sigkill-dlt",
        "dataset": "opensiro_b14_sigkill",
        "tag": "opensiro_b14_killed_stage",
    },
    "recover": {
        "root": ROOT / "b14-recovered-store",
        "dlt": ROOT / "b14-recovered-dlt",
        "dataset": "opensiro_b14_recovered",
        "tag": "opensiro_b14_clean_stage",
    },
}
MARKER = ROOT / "results/b14_sigkill_checkpoint.json"


def prepare(label):
    st = STORES[label]
    os.environ.update(
        SYSTEM_ROOT_DIRECTORY=str(st["root"] / "system"),
        DATA_ROOT_DIRECTORY=str(st["root"] / "data"),
        DLT_DATA_DIR=str(st["dlt"]),
        PIPELINES_DIR=str(st["dlt"] / "pipelines"),
        COGNEE_SKIP_CONNECTION_TEST="true",
        TELEMETRY_DISABLED="1",
    )
    for key in ("OPENAI_API_KEY", "LLM_API_KEY"):
        os.environ.pop(key, None)
    sys.path.insert(0, str(PKG))
    return st


def write_receipt(name, report):
    dest = ROOT / f"results/b14_{name}.json"
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        "B14_RESULT",
        json.dumps(
            {k: v for k, v in report.items() if k not in ("audit", "stage")}, ensure_ascii=False
        ),
        flush=True,
    )


async def run_child():
    st = prepare("crash")
    import cognee_community_connector_opensiro_vsm.native as native
    from cognee_community_connector_opensiro_vsm.source import read_snapshot

    snapshot = read_snapshot(INDEX, PIN)
    real = native.add_data_points
    count = 0

    async def wrapped(points, *args, **kwargs):
        nonlocal count
        result = await real(points, *args, **kwargs)
        count += 1
        # typed graph and section chunks of first full assessment persisted
        if count == 2:
            checkpoint = {
                "pid": os.getpid(),
                "after_native_graph_calls": count,
                "source_record": IDS[0],
                "marker": "GRAPH_RECORD_COMPLETE",
            }
            with MARKER.open("x", encoding="utf8") as stream:
                json.dump(checkpoint, stream)
                stream.flush()
                os.fsync(stream.fileno())
            print("B14_CHILD_AT_KILLPOINT", json.dumps(checkpoint), flush=True)
            # supervisor must deliver SIGKILL; never exits voluntarily
            await asyncio.Event().wait()
        return result

    native.add_data_points = wrapped
    await native.ingest_fresh(snapshot, IDS, st["dataset"], st["tag"], lexical=True)
    raise AssertionError("child survived graph kill checkpoint")


def supervisor():
    if MARKER.exists():
        raise RuntimeError("Checkpoint already exists: refusing ambiguous previous run")
    if STORES["crash"]["root"].exists():
        raise RuntimeError("Crash store already exists: refusing ambiguous previous run")
    if ACTIVE.joinpath("active.json").exists():
        raise RuntimeError("Active generation unexpectedly exists before crash test")
    cmd = [sys.executable, str(Path(__file__).resolve()), "--mode", "child"]
    logfile = ROOT / "results/b14_child_run.log"
    proc = None
    start = time.monotonic()
    observed = None
    with logfile.open("wb") as output:
        proc = subprocess.Popen(
            cmd, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            while time.monotonic() - start < 160:
                if MARKER.exists():
                    observed = json.loads(MARKER.read_text())
                    if observed["pid"] != proc.pid or observed["after_native_graph_calls"] != 2:
                        raise RuntimeError("Checkpoint not produced by expected child")
                    break
                if proc.poll() is not None:
                    raise RuntimeError(f"Child exited before controlled kill: {proc.returncode}")
                time.sleep(0.2)
            if observed is None:
                raise RuntimeError("Child never reached graph checkpoint")
            # The child is suspended in an async wait, so a real SIGKILL
            # terminates it *during* the incomplete graph import.
            os.kill(proc.pid, signal.SIGKILL)
            rc = proc.wait(timeout=25)
            if rc != -signal.SIGKILL:
                raise RuntimeError(f"Expected SIGKILL exit {-signal.SIGKILL}; got {rc}")
            report = {
                "status": "PASS_CHILD_HARD_KILLED",
                "pid": proc.pid,
                "exit_signal": "SIGKILL",
                "exit_code": rc,
                "marker": observed,
                "elapsed_s": round(time.monotonic() - start, 3),
            }
            write_receipt("sigkill", report)
        finally:
            if proc and proc.poll() is None:
                os.kill(proc.pid, signal.SIGKILL)
                proc.wait(timeout=15)


async def inspect():
    st = prepare("crash")
    from cognee.context_global_variables import set_database_global_context_variables
    from cognee.infrastructure.databases.graph import get_graph_engine
    from cognee_community_connector_opensiro_vsm.activation import read_active
    from cognee_community_connector_opensiro_vsm.generation import audit_dataset
    from cognee_community_connector_opensiro_vsm.native import ingest_fresh, source_data
    from cognee_community_connector_opensiro_vsm.source import SourceError, read_snapshot

    snap = read_snapshot(INDEX, PIN)
    user, ds, rows, docs = await source_data(st["dataset"], st["tag"])
    async with set_database_global_context_variables(ds.id, user.id, permission_type="read"):
        graph = await get_graph_engine()
        nodes, edges = await graph.get_graph_data()
        refs = await graph.find_node_source_refs_by_dataset(str(ds.id))
    from collections import Counter

    types = Counter(properties.get("type") for _, properties in nodes)
    if len(rows) != 3 or len(docs) != 3:
        raise AssertionError(f"Unexpected persisted documents: {len(rows)}, {len(docs)}")
    if types.get("VSMAssessment") != 1 or types.get("VSMFunction") != 6:
        raise AssertionError(f"Unexpected partial graph state after SIGKILL: {types}")
    if len(refs) != len(nodes):
        raise AssertionError("Native source refs missing on partial graph")
    audit_failure = None
    try:
        await audit_dataset(snap, IDS, st["dataset"], st["tag"], lexical=True)
    except SourceError as error:
        audit_failure = str(error)
    if not audit_failure:
        raise AssertionError("Independent audit incorrectly accepted killed store")
    ingest_refusal = None
    try:
        await ingest_fresh(snap, IDS, st["dataset"], st["tag"], lexical=True)
    except SourceError as error:
        ingest_refusal = str(error)
    if not ingest_refusal or "nonempty" not in ingest_refusal:
        raise AssertionError("Original partially written dataset may have been reused")
    if read_active(ACTIVE) is not None:
        raise AssertionError("Partial staged dataset unexpectedly activated")
    report = {
        "status": "PASS_KILLED_STORE_FAIL_CLOSED",
        "documents": len(docs),
        "nodes": len(nodes),
        "edges": len(edges),
        "node_types": dict(types),
        "scoped_node_refs": len(refs),
        "independent_audit_rejected": audit_failure,
        "retry_same_dataset_refused": ingest_refusal,
        "active_selection": None,
    }
    write_receipt("inspect", report)


async def recover():
    st = prepare("recover")
    from cognee_community_connector_opensiro_vsm.activation import Candidate, publish, read_active
    from cognee_community_connector_opensiro_vsm.generation import audit_dataset
    from cognee_community_connector_opensiro_vsm.native import ingest_fresh
    from cognee_community_connector_opensiro_vsm.source import read_snapshot

    if read_active(ACTIVE) is not None:
        raise AssertionError("Active selection must not be overwritten")
    snap = read_snapshot(INDEX, PIN)
    stage = await ingest_fresh(snap, IDS, st["dataset"], st["tag"], lexical=True)
    audit = await audit_dataset(snap, IDS, st["dataset"], st["tag"], lexical=True)
    pointer = publish(
        ACTIVE,
        Candidate(
            commit=PIN,
            dataset=st["dataset"],
            tag=st["tag"],
            expected_count=len(IDS),
            audit=audit,
        ),
        None,
    )
    report = {
        "status": "PASS_RECOVERED_AFTER_SIGKILL_IN_NEW_DATASET",
        "stage": stage,
        "audit": audit,
        "active": pointer,
    }
    write_receipt("recover", report)


async def verify():
    st = prepare("recover")
    from cognee_community_connector_opensiro_vsm.activation import read_active
    from cognee_community_connector_opensiro_vsm.generation import audit_dataset
    from cognee_community_connector_opensiro_vsm.source import read_snapshot

    snap = read_snapshot(INDEX, PIN)
    ptr = read_active(ACTIVE)
    if not ptr or ptr["dataset"] != st["dataset"]:
        raise AssertionError("Recovery was not selected")
    audit = await audit_dataset(snap, IDS, st["dataset"], st["tag"], lexical=True)
    report = {"status": "PASS_REOPEN_RECOVERED_AFTER_SIGKILL", "active": ptr, "audit": audit}
    write_receipt("verify", report)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--mode", required=True, choices=("kill", "child", "inspect", "recover", "verify")
    )
    opts = p.parse_args()
    if opts.mode == "kill":
        supervisor()
    else:
        asyncio.run(
            {"child": run_child, "inspect": inspect, "recover": recover, "verify": verify}[
                opts.mode
            ]()
        )
