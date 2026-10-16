# B16: actual SIGKILL after a partially committed DLT load package

**Run:** 2026-10-16; local dev-alpha CPU, Cognee 1.6.4 / DLT 1.30.0, SQLite/SQLAlchemy destination, source commit `35bc8ab9ed4b42bb8955a6f0684a4f5529a05424`. Exactly three canonically accepted OpenSiro assessment documents (`goose`, `langflow`, `openjiuwen-core`). This is a **bounded experimental multi-resource DLT source**, not the normal connector's single-table `dlt_source` and not a general Cognee transaction certification.

## Test boundary

For this manual fault test only, the three pinned source records are split into **three DLT resources**, each producing one SQLite table/load job inside one `dlt.pipeline.run` call. Cognee itself uses SQLAlchemy DLT destination. The test wraps `SqlalchemyJsonLInsertJob.run`, serializes the experimental jobs with a local thread lock, and waits **after the first native load job returned (committed)**. It then opens a **separate, read-only SQLite connection** and confirms exactly **1 row committed, 2 still absent** across those three source tables. A checkpoint is written and fsynced, containing the test child PID and these actual SQLite row counts.

Only after checking both child PID and independent SQLite visibility, the supervising process sends **actual operating-system `SIGKILL`**, observes child exit **−9**, and opens SQLite again in the parent. It finds the same one committed source row. This is stronger than B15's kill during generator iteration **before** any database commit; it is not a claim of a partial commit **within a single SQL transaction**. DLT's table jobs are independent transactional units, and the test intercepts their completion **between jobs**.

## Actual observations

| Independent observation | Result |
| --- | --- |
| One complete native SQLite insert-job committed within three-job DLT package | **1 of 3** |
| Source table rows read via an independent SQLite connection before SIGKILL | **1/3** |
| OS SIGKILL and child exit status | **−9** |
| SQLite rows independently re-read by supervisor after process termination | **1/3**, persisted |
| Cognee `Data` rows in killed dataset in a new process | **0/3** — post-DLT admission did not begin |
| Cognee graph nodes / edges | **0 / 0** |
| Independent full admission audit | **REJECTED** |
| Durable stage-attempt marker from B15 | **Present**, pinned and source-scoped |
| Attempted in-place reuse of killed dataset | **REJECTED** before any Cognee write despite 0 Cognee Data rows |
| Active generation pointer before recovery | **None** |
| New clean dataset | 3 documents, 69 graph nodes, 48 edges, 18 exact function-grade facts |
| Independent fresh dataset audit, then active selection | **PASS** |
| Separate process reopen and audit | **PASS** |

**Implication:** Cognee `Data` table cardinality and DLT staging commit progress are **different states**. Even when some DLT jobs are fully committed, an interrupted Cognee ingestion may still have **zero** application-visible `Data` rows. Checking only the `Data` table would falsely categorize this dataset as unused. The B15 single-host **exclusive, fsynced stage-attempt claim** prevents reuse across this gap when its marker directory is retained with the dataset. Recovery creates a **different fresh dataset**, audits its source identities and full graph, then uses an atomic local compare-and-swap selection pointer. No failed dataset is modified, removed, or silently promoted.

## Reproduction (manual, disposable local store only)

Two opt-in manual tests under `tests/`: `manual_partial_dlt_sigkill.py` and `manual_partial_dlt_recovery.py`. They are **not** part of normal CI/unittest discovery. They deliberately SIGKILL **only the child spawned by their own supervisor**, at a validated checkpoint. Do **not** use a shared, hosted or production Cognee database or storage directory.

Provide an existing local clone of the pinned OpenSiro Index repository and a **previously unused** scratch directory. From `packages/connector/opensiro-vsm` in a Python environment with Cognee 1.6.4 and DLT 1.30.0:

```bash
export OPENSIRO_B16_INDEX_REPO="$(realpath /path/to/vsm-harness-index)"
export OPENSIRO_B16_TEST_ROOT="$(realpath -m /new/disposable/b16-scratch)"

python tests/manual_partial_dlt_sigkill.py kill
python tests/manual_partial_dlt_recovery.py inspect
python tests/manual_partial_dlt_recovery.py recover
python tests/manual_partial_dlt_recovery.py verify
```

The entire test state is under `$OPENSIRO_B16_TEST_ROOT`, with exact JSON result files at `results/b16_{kill,inspect,recover,verify}.json`. The SIGKILL script refuses to reuse an existing killed-stage store or checkpoint; the stage-attempt guard rejects reusing that dataset even if zero Cognee `Data` rows exist. The canonical source Git repository is read-only. No upstream Cognee API action, PR, issue, comment or repository write occurs.

## Limits and deployment risks

- **Not the normal source layout:** the fault test deliberately splits a normal assessment source into three `dlt.resource` tables to guarantee at least three separately committed DLT jobs. The normal production candidate uses a single resource/table. An in-transaction partial row failure in that single table remains untested.
- No host power failure, arbitrary instruction-boundary kill, PostgreSQL backend parity, distributed datasets, marker-loss scenario, multiple readers/writers, or automatic native Cognee DLT recovery demonstrated.
- The loader hook is **test-only** and monkeypatches installed DLT load-job machinery **only inside the disposable child process**. It is not incorporated into shipping connector behavior.
- A marker stored separately from the underlying database can be lost/deleted independently. This is **single-host crash prevention by dataset non-reuse**, not cross-store distributed consensus or atomic rollback.
- A completed staging dataset requires independent audit before selection. Source-grades and provenance were proven on the full accepted 533-record corpus in B13; B16 is a **three-record fault scenario**.

See [B15](validation-b15.md) for precommit DLT kill and durable attempt claim, and [B14](validation-b14.md) for post-graph-write SIGKILL.
