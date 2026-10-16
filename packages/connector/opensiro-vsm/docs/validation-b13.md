# B13: independent package-scale acceptance and incomplete-stage recovery

**Run date:** 2026-10-16. **Scope:** local research on the OpenSiro dev-alpha CPU host, Cognee SDK **1.6.4**, with pinned source tree `35bc8ab9ed4b42bb8955a6f0684a4f5529a05424`. No LLM, embeddings, GPU, LanceDB/vector search, or upstream Cognee writes. These are **reproducible research observations**, not a production compatibility certification.

## Full corpus: accepted-only source to native Cognee graph

The code from `packages/connector/opensiro-vsm/` was imported in a fresh, isolated dataset. The full pinned Index contains **590** assessment Markdown files: **533 included**, 45 excluded, 12 proposed. The connector admitted exactly the **533 included** records.

| Actual observation | Result |
| --- | ---: |
| Source Data documents | **533 / 533** |
| Native typed harness + assessment nodes | **533 + 533** |
| Exact six-function-grade nodes | **3,198 / 3,198** |
| Explicit assessment-scoped Primary evidence nodes | **541** |
| Native Markdown function-section `DocumentChunk` nodes | **3,198** |
| Native `TextDocument` parent nodes | **3,198** |
| Total native graph | **11,201 nodes / 7,470 edges** |
| Independent post-write audit: native node source refs | **11,201 / 11,201 exact** |
| Independent post-write audit: native edge source refs | **7,470 / 7,470 exact** |
| Document-level native refs (`source_ref:v1`) | **8,003** |
| Chunk-level native refs (`source_ref:v2`) | **3,198** |
| Literal S1–S5 via public Cognee `search(CYPHER)` | **3,198 / 3,198 exact** |
| Elapsed fresh import, this specific host | **653.691 seconds** |

This repeats B10's **full-corpus combined initial ingestion**, now from the packaged connector rather than from standalone research scripts. No claims about partial retry, native vector lifecycle or production throughput can be inferred from this single local run.

### BM25 negative control

Separate, read-only reopening of the full 3,198-section store, using public `cognee.search(query_type=SearchType.CHUNKS_LEXICAL, top_k=5)`:

| Query | Expected top section document | Actual rank |
| --- | --- | --- |
| Goose | `goose.md` | **1** |
| Agno | `agno.md` | **1** |
| Langflow | `langflow.md` | **1** |
| openJiuwen Core | `openjiuwen-core.md` | **1** |
| `zzzxxyyrareunlikelykeyword2026` | none | native top_k returned **5 unrelated hits**; local overlap guard returned **0** |

The guard is **diagnostic application-side token overlap**, not a built-in Cognee BM25 relevance threshold or a general test of semantic similarity. The six-section lexical index covers only S1–S5 narrative sections, not every byte of the canonical Markdown.

## Controlled interrupted graph ingestion

Tested with three accepted records (Goose, Langflow, openJiuwen Core) in **separate isolated datasets**. The exposed `test_only_fail_after_graph_records=1` parameter raises a **controlled exception after fully writing the first graph record**; this is not a hard-kill/power-failure simulation.

1. Source document ingestion committed all **3** Data rows, then graph creation stopped after **1** graph record. The actual incomplete graph retained **26 nodes and 19 edges** (1 harness, 1 assessment, 6 function grades, 6 evidence bullets, 6 document chunks and 6 text parents).
2. Independent read-only graph audit detected the incomplete 1/3 projection and **failed closed**. A separate process reopened the same dataset and confirmed the same incomplete graph.
3. Attempting the fresh-only ingest again into that dataset was **refused before a new write**; no implicit destructive retry or deletion of that store.
4. A **different fresh dataset** imported all 3 records, with **69 nodes / 48 edges / 18 exact grades**, and passed its independent audit.
5. Only after passing audit did the local single-host CAS selector publish the new clean dataset as active. Another process reopened it and independently audited it as **PASS**. The incomplete dataset was left isolated and not activated.

**This demonstrates fail-closed detection and recover-by-staging-another-fresh-generation**, not automatic Cognee resumability, distributed transaction safety, crash-safe cleanup, or unlimited retry. Stale/incomplete datasets need an explicit retention and eventual garbage-collection policy before production operation.

## Test and source receipt locations

Research-only dev-alpha files (not bundled in the connector wheel):

- `b13_package_full.py`, `results/b13_package_full_{ingest,audit,result}.json`;
- `b13_full_lexical_readback.py`, `results/b13_lexical_readback.json`;
- `b13_failure_recovery.py`, `results/b13_{fail,check_incomplete,recover,verify}.json`.

Connector test suite: **28/28 unittest PASS**; Cognee Community root-configured Ruff `check` and `format --check` both PASS. Packaging with Hatchling and the Python wheel were validated in the previous B12 step.

See [OpenSiro Index research #1598](https://github.com/opensiro/vsm-harness-index/issues/1598) for earlier B0–B12 receipts and domain-specific assumptions. Maintainer acceptance, release backend portability, vector retrieval and production failure semantics remain **unverified**. Do **not** claim any submitted upstream issue or PR.
