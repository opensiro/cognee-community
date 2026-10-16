# B15 — real SIGKILL during DLT document ingestion (precommit boundary)

**Research date:** 2026-10-16. Local CPU-only dev-alpha, Cognee 1.6.4, pinned OpenSiro Index snapshot `35bc8ab9ed4b42bb8955a6f0684a4f5529a05424`. Three canonically `included` source records (`goose`, `langflow`, `openjiuwen-core`). This is an **opt-in destructive process test targeting only a freshly spawned disposable child**, not a production test or an upstream Cognee modification.

## Finding: zero Data rows is not a safe retry signal

A small instrumented, read-only DLT source yielded its **first** assessment to Cognee's DLT iterator, then paused before yielding the second. A supervisor verified the checkpoint came from its own child and delivered actual OS `SIGKILL` (**exit code −9**). In this observation, the first record had been **handed to the source iterator but was not yet committed**. A separate **read-only SQLite** inspection found:

- Cognee relational dataset metadata already existed;
- **0** committed Cognee `Data` rows;
- DLT destination database file existed, but no source data was committed.

Therefore, checking only `if existing Data rows` cannot distinguish an unused empty dataset from a **partially attempted** dataset at this early boundary. This was a real safety hole in the former fresh-only admission guard. The repository did **not** have proof of safe in-place retry and did not retry this failed generation.

## Implemented protection

`cognee_community_connector_opensiro_vsm.attempt.claim_attempt()` now creates an exclusive (`O_EXCL`) JSON marker for each dataset under an explicit **single-host, durable local directory**, writes and `fsync`s it, and syncs its parent directory. The marker records pinned Index commit, dataset name, source tag and digest of selected IDs. Its name is SHA256(dataset) to prevent dataset names from escaping the marker root. A second claim is rejected, **even if there are zero rows in Cognee**.

The `ingest_fresh(..., attempt_root=path)` opt-in hook performs that claim before Cognee database initialization. The supported local `examples/example.py` uses `attempt_root=<local-store>/stage-attempts` by default, so the marker accompanies the experimental store. The caller must preserve this directory: **deleting or separating it from the Cognee store defeats the guard**. The claim is never automatically removed on success or failure: refreshing requires a **new dataset**.

The marker is not a distributed lock, graph ownership proof or cross-backend durability protocol. Do not claim native Cognee DLT resumability or transparent crash recovery.

## Guarded kill → independent audit → clean recovery

Repeat the same real SIGKILL while `attempt_root` is enabled:

| Stage | Observed result |
| --- | --- |
| Child reached DLT checkpoint after first item handed to iterator | Yes |
| Supervisor sent actual `SIGKILL`; child exit | **−9** |
| Durable attempt marker survived | **Yes** |
| Reopen incomplete store in another process | 0 Data rows, 0 graph nodes, 0 graph edges |
| Independent admission audit of 3-record target | **Rejected** (missing source Data rows) |
| Attempt to rerun on the identical dataset/marker root | **Rejected before Cognee write** |
| Active selection after crash | **None** |
| New clean dataset import | 3/3 Data documents; 69 nodes, 48 edges, 18 exact grades |
| Independent source/graph ownership audit | **PASS** |
| Single-host activation after independent audit | **PASS** |
| Clean reopen in an additional process | **PASS**: same verified dataset and active generation |

This shows a **precommit DLT-source iteration kill**; it does not simulate an interruption after the backend has committed one of multiple source documents. That intermediate commit state may need a different injection point and further tests.

## Reproduce in your own disposable directory

The repository includes two **manual, opt-in** scripts in `tests/`, which are *not* discovered by normal `unittest` or executed by CI. Provide an existing clone of the pinned Index Git repository and a brand-new disposable scratch directory. All four steps run with Cognee 1.6.4 installed:

```bash
export OPENSIRO_B15_INDEX_REPO="$(realpath /path/to/vsm-harness-index)"
export OPENSIRO_B15_TEST_ROOT="$(realpath -m /path/to/new-disposable-b15-folder)"

# From packages/connector/opensiro-vsm:
python tests/manual_dlt_sigkill.py kill
python tests/manual_dlt_recovery.py inspect
python tests/manual_dlt_recovery.py recover
python tests/manual_dlt_recovery.py verify
```

The supervisor only signals its own spawned child after checking the child's PID and a uniquely created checkpoint. All scratch files are written **only** under `OPENSIRO_B15_TEST_ROOT`; the Index is read-only. Neither script creates a GitHub PR, issue, comment or mutation in upstream Cognee. Never point them at a shared or production datastore.

### Portable-script repeat

In a **second, new scratch directory** on the same dev-alpha host, the bundled
manual scripts repeated all four phases with the durable claim enabled:
`kill` (SIGKILL exit −9), `inspect` (0 docs / 0 graph, audit and retry refused),
`recover` (new 3-assessment, 69-node graph independently audited and
activated), and `verify` (separate-process reopen and independent audit).
**All four phases PASS.** Ordinary Python unit tests **36/36 PASS**, Ruff lint
and format checks PASS, and Hatchling wheel build PASS.

## Scope limits

- SIGKILL is issued at a deterministic **DLT iterator checkpoint**, not every possible instruction or a documented Cognee backend commit boundary.
- The recovered graph comes from a **different fresh dataset**, not an in-place undo, transparent Cognee resume, or garbage collection of failed state.
- Single-host `O_EXCL` and `fsync` do not demonstrate operation across machines, NFS, a disconnected marker store, database credential scopes, unexpected concurrent writers or power loss.
- A live service, Agent runtime, VSM S3–S5 delegation or other organizational governance is not necessary for this OSS connector.

Local dev-alpha evidence: `results/b15_kill.json`, `results/b15_guarded_kill.json`, `results/b15_inspect.json`, `results/b15_recover.json`, `results/b15_verify.json`, plus unit tests in `tests/test_attempt.py`. Previous [B14](validation-b14.md) covered a different `SIGKILL` checkpoint *after* graph writes; [B13](validation-b13.md) verified full 533-assessment packaged input and a controlled Python exception after the first graph write.
