"""B16: inspect partially COMMITTED DLT table job, reject reuse, restore fresh.

Each mode is a new Python process; no source Index or upstream changes.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

raw_root = os.environ.get("OPENSIRO_B16_TEST_ROOT")
raw_index = os.environ.get("OPENSIRO_B16_INDEX_REPO")
if not raw_root or not raw_index:
    raise SystemExit("Set OPENSIRO_B16_TEST_ROOT and OPENSIRO_B16_INDEX_REPO")
ROOT = Path(raw_root).resolve()
INDEX = Path(raw_index).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PIN = os.environ.get("OPENSIRO_B16_INDEX_SHA", "35bc8ab9ed4b42bb8955a6f0684a4f5529a05424")
IDS = ("goose", "langflow", "openjiuwen-core")
FOLDERS = {
    "inspect": (
        "b16-sigkill-store",
        "b16-sigkill-dlt",
        "opensiro_b16_committed_partial",
        "opensiro_b16_source",
    ),
    "recover": (
        "b16-recovery-store",
        "b16-recovery-dlt",
        "opensiro_b16_recovery_clean",
        "opensiro_b16_recovery_source",
    ),
    "verify": (
        "b16-recovery-store",
        "b16-recovery-dlt",
        "opensiro_b16_recovery_clean",
        "opensiro_b16_recovery_source",
    ),
}
ACTIVE = ROOT / "b16-active-control"


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
        from manual_partial_dlt_sigkill import inspect_committed_rows

        visible = inspect_committed_rows()
        assert visible["total"] == 1, visible
        assert len(visible["tables"]) == 3, visible
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
            raise AssertionError("Partially committed DLT stage was illegally reusable")
        assert read_active(ACTIVE) is None
        record.update(
            status="PASS_PARTIAL_COMMITTED_DLT_KILL_GUARDED",
            committed_dlt=visible,
            cognee_documents=0,
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
    path = ROOT / f"results/b16_{mode}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(
        "B16_RESULT",
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
