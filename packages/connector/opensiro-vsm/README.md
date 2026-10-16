# cognee-community-connector-opensiro-vsm

Source-first, **read-only** local OpenSiro VSM assessment connector for [Cognee](https://github.com/topoteretes/cognee), built using the existing Cognee DLT ingestion, DataPoint graph and source-provenance APIs.

**Work-in-progress in the OpenSiro fork; not submitted or approved upstream.** Source data is read from a local pinned Git tree of [OpenSiro Index](https://github.com/opensiro/vsm-harness-index); the connector does not modify the Index or contact GitHub APIs. A running OpenSiro-hosted service is not needed.

## Install

Use Python 3.11–3.13 and Cognee 1.6.4 (the validated SDK version):

```bash
cd packages/connector/opensiro-vsm
uv sync
```

For CPU-only source/unit tests without a configured Cognee instance:

```bash
uv run python -m unittest discover -s tests -v
```

## Local source validation

```bash
# Outside this package, clone the Index separately first.
git clone https://github.com/opensiro/vsm-harness-index.git ./vsm-harness-index

# Pin to a full, existing 40-character Git SHA; never rely on mutable HEAD.
uv run python -m cognee_community_connector_opensiro_vsm validate \
  --repo ./vsm-harness-index \
  --commit 35bc8ab9ed4b42bb8955a6f0684a4f5529a05424
```

The source reader rejects inconsistent admission catalog entries, invalid literal S1–S5 grades, duplicate YAML keys, missing required included fields and uncertain Git revisions. A narrow in-memory compatibility fix preserves the literal bare `autonomy_s*: ?` as `?`. Original Markdown bytes, source SHA256, upstream reviewed repository SHA and Index commit remain distinct identifiers.

To write a JSON manifest from a pinned revision, use the `manifest` subcommand with `--output` pointing to a **new** file. Existing output files are never overwritten. Use `diff` to compare two fully valid canonical snapshots, or `diff-one` for diagnostic record-only history when old schema revisions fail current contracts.

## Example: fresh import

```bash
uv run python examples/example.py \
  --repo ./vsm-harness-index \
  --commit 35bc8ab9ed4b42bb8955a6f0684a4f5529a05424 \
  --dataset my-vsm-experiment \
  --store-root ./local-vsm-store \
  --ids goose,langflow,openjiuwen-core \
  --lexical
```

For a full accepted snapshot, use `--all` in place of `--ids` (a larger CPU/disk workload). It includes only canonically `included` assessments and never `excluded` or `proposed` records.

This is an intentionally **fresh-only local dataset** import. It refuses nonempty datasets rather than risk erasing or mixing previous revisions. `--lexical` adds 6 `DocumentChunk` objects per assessment using its S1–S5 sections, enabling native `CHUNKS_LEXICAL` BM25. All `VSMFunction` objects can be recovered with `cognee.search(query_type=SearchType.CYPHER)`. No LLM, embeddings or GPU are called in this workflow (`graph_only=True`).

The full 533 accepted assessment corpus passed a single integrated Cognee 1.6.4 local CPU run in the original B10 research; the new package still needs its own complete acceptance run in a clean environment. [Research receipts](https://github.com/opensiro/vsm-harness-index/issues/1598).

## Versioned staging, not destructive sync

Optional `activation.py` and `generation.py` provide **single-host research primitives** for staging a source generation in a **new dataset**, independently auditing exact grade/content SHA/review SHA/native `source_ref:v1` and chunk `source_ref:v2`, and publishing a small atomic local `active.json` pointer with a compare-and-swap lease.

Do not directly run these against a shared/production instance: no distributed locking, automatic recovery of interrupted Cognee imports, dataset garbage collection, credential isolation, reader migration, or proof of power-loss resilience is provided. See the [OpenSiro B11 bounded result](https://github.com/opensiro/vsm-harness-index/issues/1598). B11 tested two and then three real historical records, **not** two full Index generations.

### Full packaged-corpus acceptance

A separately validated **533/533 accepted** local full run and the bounded
fault/recovery tests are documented in [B13 validation](docs/validation-b13.md).
The native read-back included all 3,198 literal VSM grades and all 11,201
source-owned graph nodes. This is not a production reliability guarantee.

## B13: bounded incomplete-stage recovery evidence

A **controlled Python exception** after the first complete graph record (test-only
`ingest_fresh(..., test_only_fail_after_graph_records=1)`) left a deliberately
incomplete local stage with **3 ingested Data documents** but only **1 of 3
assessment graphs** (26 nodes, 19 edges). The independent `audit_dataset`
rejected that stage; reopening the store in a separate process preserved the
same incomplete result. Attempting to call `ingest_fresh` on the same dataset
was refused before any write. A **different new dataset** imported and audited
all three assessments successfully (69 nodes, 48 edges, 18/18 literal grades)
and was then selected by the local single-host active-pointer protocol.

This test supports **fail-closed detection + recover-by-fresh-generation**.
It does *not* prove that Cognee automatically resumes an interrupted partial
import or that process hard-kill, power loss, distributed readers and backend
failure recovery are handled. Never interpret the presence of Data documents
or a successful pipeline return as equivalent to independent graph admission.

## B14: real OS process termination

A separate local [B14 SIGKILL integration test](docs/validation-b14.md) sent an
actual SIGKILL to its **own spawned child** after the first full native graph
record was written. Independent audit rejected the incomplete store; an
unmodified fresh-only guard refused rewriting it. A new empty dataset passed
independent audit and was then selected, with an additional process reopening
it successfully. An optional manual driver is under
`tests/manual_sigkill_recovery.py`; it must run only against a dedicated
**disposable** local store, never a shared Cognee runtime. This is not
power-loss or arbitrary-backend crash recovery certification.

## B15: early DLT failure and durable attempt marker

The [B15 validation report](docs/validation-b15.md) covers a **real SIGKILL
while Cognee's DLT iterator is processing source records, before any Data rows
are committed**. In this state the older nonempty-Data guard alone would be
insufficient. The opt-in **single-host** `attempt_root` parameter now writes an
exclusive, durable `CLAIMED_NEVER_REUSABLE` marker **before** any Cognee write.
The normal `examples/example.py` supplies this guard automatically under the
requested local store root. An interrupted/failed generation must be replaced
by a **different** dataset name; its attempt marker is not automatically
removed. Operators must preserve attempt markers alongside dataset state.

This does not make Cognee's native DLT transaction atomic and is **not** a
cross-host fencing lease, a production cleanup guarantee, or proof that the
filesystem survives host power loss.

## B16: partial committed DLT load-job SIGKILL

The [B16 report](docs/validation-b16.md) adds another real SIGKILL case: a
**three-job** DLT load package in a disposable SQLite store was stopped after
one native SQL job had **committed**, proven by an independent read-only SQLite
connection. **1/3 DLT rows survived** the kill, but Cognee still contained
**0 Data rows**. The B15 durable single-host attempt marker rejected reuse of
that dataset before any new write. Recovery is a **different empty dataset →
independent audit → CAS selection → new-process read-back**.

This is a test-specific multi-resource DLT package, **not** a partial
transaction within the connector's normal single resource/table, or evidence
of general native DLT resumability / distributed crash safety.

## Evidence and search boundaries

- Exactly six literal function grades per **included** assessment are indexed. `?` is *unknown*, `—` means *not established*; neither is a substitute for `C`.
- Explicit `Primary evidence` bullets are associated with their **assessment**, never falsely attributed to individual functions. Other evidence remains in original Markdown.
- Function-section BM25 covers only those sections, not entire Markdown or semantic/vector retrieval. Cognee 1.6.4 may return BM25 zero-score candidates for an unmatched query; callers need an explicit relevance guard.
- Ladybug custom properties are JSON-encoded strings. Verify exact fields after Cypher retrieval instead of trusting substring matches, and never interpolate unchecked user strings into raw Cypher.
- Cognee DLT may strip trailing source whitespace, so raw Git blob SHA256 is the authoritative source identity.
- Native LanceDB on non-AVX dev-alpha CPU raises SIGILL if initialized; no claim of portable production vector support is made.

## Test layout

- `tests/test_source.py`: pinned sources, malformed catalog/frontmatter, states and immutable history.
- `tests/test_activation.py`: CAS, failpoint-before-swap, idempotency and invalid audit refusal.
- `tests/test_native_contract.py`: native typed/lexical model consistency in an installed Cognee SDK.
- `examples/example.py`: bounded local fresh-source import.

No upstream Cognee PR, issue, or comment is created by any command here.
