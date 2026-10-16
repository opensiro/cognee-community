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

This is an intentionally **fresh-only local dataset** import. It refuses nonempty datasets rather than risk erasing or mixing previous revisions. `--lexical` adds 6 `DocumentChunk` objects per assessment using its S1–S5 sections, enabling native `CHUNKS_LEXICAL` BM25. All `VSMFunction` objects can be recovered with `cognee.search(query_type=SearchType.CYPHER)`. No LLM, embeddings or GPU are called in this workflow (`graph_only=True`).

The full 533 accepted assessment corpus passed a single integrated Cognee 1.6.4 local CPU run in the original B10 research; the new package still needs its own complete acceptance run in a clean environment. [Research receipts](https://github.com/opensiro/vsm-harness-index/issues/1598).

## Versioned staging, not destructive sync

Optional `activation.py` and `generation.py` provide **single-host research primitives** for staging a source generation in a **new dataset**, independently auditing exact grade/content SHA/review SHA/native `source_ref:v1` and chunk `source_ref:v2`, and publishing a small atomic local `active.json` pointer with a compare-and-swap lease.

Do not directly run these against a shared/production instance: no distributed locking, automatic recovery of interrupted Cognee imports, dataset garbage collection, credential isolation, reader migration, or proof of power-loss resilience is provided. See the [OpenSiro B11 bounded result](https://github.com/opensiro/vsm-harness-index/issues/1598). B11 tested two and then three real historical records, **not** two full Index generations.

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
