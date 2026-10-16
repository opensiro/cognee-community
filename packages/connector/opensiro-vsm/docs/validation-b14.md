# B14: actual SIGKILL during Cognee graph ingestion (local integration)

**Run:** 2026-10-16, dev-alpha CPU, Cognee 1.6.4, pinned canonical OpenSiro Index commit `35bc8ab9ed4b42bb8955a6f0684a4f5529a05424`, three `included` assessments (`goose`, `langflow`, `openjiuwen-core`). No upstream Cognee actions, LLM, embeddings, GPU, vector DB or hosted service.

This is a **real operating-system SIGKILL** sent by a supervisor to its own disposable child process, **not** a simulated Python exception. The child pauses after Cognee's native `add_data_points` returns for both the first assessment's typed graph and its six source-derived chunks. It writes and fsyncs a checkpoint; the supervisor validates the PID belongs to the spawned child, then delivers SIGKILL and checks exit code `-9`.

## Observations

| Phase | Measured outcome | Verdict |
| --- | --- | --- |
| Child termination | `SIGKILL` observed, exit code `-9`; first graph record and chunks written before checkpoint | PASS |
| Fresh process reopening the terminated store | 3 committed source Data documents; **26 nodes**, **19 edges**, including only **1/3** typed assessments and **6/18** function grades | PASS (partial detected) |
| Native source-ref inspection | 26/26 persisted nodes had source ownership | PASS (not sufficient for admission) |
| Independent full-selection audit | Rejects incomplete counts, cannot approve the incomplete dataset | PASS (fail-closed) |
| Fresh-only re-ingest into the partial dataset | Rejected before writing because the dataset is nonempty | PASS |
| Active pointer before clean recovery | Absent; incomplete dataset was never activated | PASS |
| New isolated dataset for same pinned source selection | 3 documents, **69 nodes**, **48 edges**, **18/18 exact S1–S5 grades**, independently audited | PASS |
| Activate only audited fresh dataset | Single-host CAS pointer selected fresh generation `sequence=1` | PASS |
| Reopen active generation in yet another process | Full independent audit PASS, source refs correct | PASS |

**Interpretation:** A process can be killed while the source has committed Data rows but before all graph records exist. Document existence is **not** proof of complete admission. The packaged fail-closed stage guard and independent graph audit prevented unsafe in-place reuse and selection. The bounded recovery strategy is **reimport into a new empty dataset, independently audit, then select it**. Neither the interrupted dataset nor prior versions were deleted.

## Reproduce safely

The repository includes an **opt-in manual test** at `tests/manual_sigkill_recovery.py`. It deliberately kills a process. Do **not** use it with a production/shared Cognee directory, or a working copy you want to keep. It is not run in normal unit-test discovery or CI.

Provide an existing local clone of [OpenSiro Index](https://github.com/opensiro/vsm-harness-index) which contains the pinned SHA, and a **new, disposable, empty** scratch directory for this test:

```bash
export OPENSIRO_B14_INDEX_REPO="$(realpath /path/to/vsm-harness-index)"
export OPENSIRO_B14_TEST_ROOT="$(realpath -m /path/to/new-empty-b14-scratch)"

# From packages/connector/opensiro-vsm in a Python env with Cognee 1.6.4:
python tests/manual_sigkill_recovery.py --mode kill
python tests/manual_sigkill_recovery.py --mode inspect
python tests/manual_sigkill_recovery.py --mode recover
python tests/manual_sigkill_recovery.py --mode verify
```

The supervisor sends SIGKILL *only* to its own child after verifying the PID and stage checkpoint. It times out or refuses to start if an earlier checkpoint or crash store already exists. Stages are separate processes; each one writes receipts under `$OPENSIRO_B14_TEST_ROOT/results/`. The Index Git checkout is read-only. These scripts never create upstream PRs, comments, issues or API writes.

If a test aborts, inspect the receipts and scratch directory manually; do **not** retry the same staging dataset or mistake a leftover process for a successful run.

### Portable-driver verification (separate scratch store)

After the first B14 research run, the repository's opt-in manual driver was
executed again in a **second, newly created disposable directory** with the
four commands above. All four phases independently **PASS**:

- `kill`: real child `SIGKILL`, exit `-9` after two committed native graph writes;
- `inspect`: read-back 3 Data docs / 26 graph nodes / 19 edges, audited and refused;
- `recover`: fresh 3-record dataset independently audited (69 nodes / 48 edges / 18 grades) and activated;
- `verify`: reopened clean selected dataset in a further process and audited it as PASS.

This validates the test script's portability across distinct local scratch
folders on the **same host**, not platform or backend portability.

## Limits / claims not proven

- Only one deterministic kill boundary **after** fully writing the first assessment graph and chunks, on the dev-alpha local native Ladybug/SQLite-related backend. This is not an arbitrary instruction-boundary crash, forced shutdown of the host, crash during document DLT ingest, nor a comprehensive failure-state matrix.
- No evidence here of native Cognee in-place restart/resume, safe source-owned forget/delete, automatic garbage collection, distributed failover, live reader migration, shared concurrent writers or cross-backend behavior.
- OS process `SIGKILL` is **not a power-loss/fsync guarantee**; an external DB and its storage durability characteristics would require independent experiments.
- Fresh-version selection uses single-host filesystem CAS, not a distributed atomic transaction. Production deployment needs coordination, lifecycle/retention and security review.

Evidence receipts for the original B14 run: local dev-alpha `b14_sigkill_recovery.py` and `results/b14_{sigkill,inspect,recover,verify}.json`; the portable manual driver above implements the same test in a disposable workspace. See [research issue #1598](https://github.com/opensiro/vsm-harness-index/issues/1598).
