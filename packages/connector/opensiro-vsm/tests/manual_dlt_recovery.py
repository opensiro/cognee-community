"""B15: independently inspect a killed DLT attempt, reject reuse and restore fresh.

Each mode is a new Python process; no source Index or upstream changes.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

raw_root = os.environ.get("OPENSIRO_B15_TEST_ROOT")
raw_index = os.environ.get("OPENSIRO_B15_INDEX_REPO")
if not raw_root or not raw_index:
    raise SystemExit("Set OPENSIRO_B15_TEST_ROOT and OPENSIRO_B15_INDEX_REPO")
ROOT = Path(raw_root).resolve()
INDEX = Path(raw_index).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PIN = os.environ.get("OPENSIRO_B15_INDEX_SHA", "35bc8ab9ed4b42bb8955a6f0684a4f5529a05424")
IDS = ("goose", "langflow", "openjiuwen-core")
FOLDERS = {
    "inspect": (
        "b15-guarded-crash-store",
        "b15-guarded-crash-dlt",
        "opensiro_b15_guarded_crash",
        "opensiro_b15_guarded_source",
    ),
    "recover": (
        "b15-recovery-store",
        "b15-recovery-dlt",
        "opensiro_b15_recovery_clean",
        "opensiro_b15_recovery_source",
    ),
    "verify": (
        "b15-recovery-store",
        "b15-recovery-dlt",
        "opensiro_b15_recovery_clean",
        "opensiro_b15_recovery_source",
    ),
}
ACTIVE = ROOT / "b15-active-control"


async def main(mode):
    rootname, dltname, dataset, tag = FOLDERS[mode]
    store = ROOT / rootname
    dlt = ROOT / dltname
    os.environ.update(
        SYSTEM_ROOT_DIRECTORY=str(store / "system"),
        DATA_ROOT_DIRECTORY=str(store / "data"),
        DLT_DATA_DIR=str(dlt),
        PIPELINES_DIR=str(dlt / "pipelines"),
        COGNEE_SKIP_CONNECTION_TEST="true",
        TELEMETRY_DISABLED="1",
    )
    for x in ("OPENAI_API_KEY", "LLM_API_KEY"):
        os.environ.pop(x, None)
    from cognee_community_connector_opensiro_vsm.activation import Candidate, publish, read_active
    from cognee_community_connector_opensiro_vsm.generation import audit_dataset
    from cognee_community_connector_opensiro_vsm.native import ingest_fresh, source_data
    from cognee_community_connector_opensiro_vsm.source import SourceError, read_snapshot

    snap = read_snapshot(INDEX, PIN)
    record = {"mode": mode, "status": "STARTED"}
    if mode == "inspect":
        from cognee.context_global_variables import set_database_global_context_variables
        from cognee.infrastructure.databases.graph import get_graph_engine

        user, ds, allrows, docs = await source_data(dataset, tag)
        async with set_database_global_context_variables(ds.id, user.id, permission_type="read"):
            g = await get_graph_engine()
            nodes, edges = await g.get_graph_data()
        assert len(allrows) == len(docs) == 0, (len(allrows), len(docs))
        assert len(nodes) == len(edges) == 0, (len(nodes), len(edges))
        try:
            await audit_dataset(snap, IDS, dataset, tag, lexical=True)
        except SourceError as e:
            record["audit_rejection"] = str(e)
        else:
            raise AssertionError("Unaudited early-DLT-crash stage falsely approved")
        attempt_dir = store / "stage-attempts"
        attempts = list(attempt_dir.glob("*.json"))
        assert len(attempts) == 1
        receipt = json.loads(attempts[0].read_text())
        assert receipt["dataset"] == dataset
        try:
            await ingest_fresh(snap, IDS, dataset, tag, lexical=True, attempt_root=attempt_dir)
        except SourceError as e:
            record["stage_reuse_rejection"] = str(e)
        else:
            raise AssertionError("Incomplete stage with zero docs illegally reusable")
        assert read_active(ACTIVE) is None
        record.update(
            status="PASS_PRECOMMIT_DLT_KILL_GUARDED",
            documents=0,
            graph_nodes=0,
            graph_edges=0,
            attempt_marker=receipt,
            active=None,
        )
    elif mode == "recover":
        assert read_active(ACTIVE) is None
        report = await ingest_fresh(
            snap, IDS, dataset, tag, lexical=True, attempt_root=store / "stage-attempts"
        )
        audited = await audit_dataset(snap, IDS, dataset, tag, lexical=True)
        assert audited["status"] == "PASS"
        selection = publish(ACTIVE, Candidate(PIN, dataset, tag, len(IDS), audited), None)
        record.update(
            status="PASS_NEW_STAGE_AFTER_DLT_KILL",
            stage=report,
            independent_audit=audited,
            active=selection,
        )
    else:
        current = read_active(ACTIVE)
        assert current is not None and current["dataset"] == dataset
        audited = await audit_dataset(snap, IDS, dataset, tag, lexical=True)
        assert audited["status"] == "PASS"
        record.update(
            status="PASS_REOPEN_AFTER_DLT_KILL", independent_audit=audited, active=current
        )
    path = ROOT / f"results/b15_{mode}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(
        "B15_RESULT",
        json.dumps(
            {k: v for k, v in record.items() if k not in ("independent_audit", "stage")},
            ensure_ascii=False,
        )[:2600],
        flush=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in FOLDERS:
        raise SystemExit("inspect | recover | verify")
    asyncio.run(main(sys.argv[1]))
