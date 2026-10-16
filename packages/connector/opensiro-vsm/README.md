# OpenSiro VSM Index source connector for Cognee

Import **canonically included** [OpenSiro VSM Index](https://github.com/opensiro/vsm-harness-index) assessments from a **pinned Git commit** into a **fresh local Cognee dataset**.

**Status: OpenSiro fork review candidate. No upstream PR or maintainer approval.**

## What it does

- Preserves the six literal S1–S5 autonomy values per included assessment. Unknown and non-established states are not guessed.
- Projects native Cognee typed graph nodes: `VSMHarness`, `VSMAssessment`, `VSMFunction`, and assessment-level `VSMEvidence`.
- Keeps the original Markdown SHA256, reviewed upstream Git SHA, pinned Index commit and Cognee-native source refs separate.
- Optionally creates six section-level `DocumentChunk` nodes for lexical BM25 search, with no LLM, embeddings or GPU requirement.
- Provides `audit_dataset` to independently check complete source identity, literal grades and node/edge ownership without changing the dataset.
- Requires a durable single-host stage-attempt marker **before any Cognee write**, so the same dataset cannot be reused after early or partial DLT ingestion failure.

## Install and test

Python 3.11–3.13 and Cognee **1.6.4** were used for validation.

```bash
cd packages/connector/opensiro-vsm
python -m pip install -e .
python -m unittest discover -s tests -v
```

Start with an existing local clone of the Index. Validate a pinned revision:

```bash
python -m cognee_community_connector_opensiro_vsm validate \
  --repo /path/to/vsm-harness-index \
  --commit 35bc8ab9ed4b42bb8955a6f0684a4f5529a05424
```

Then use a **new**, isolated local store:

```bash
python examples/example.py \
  --repo /path/to/vsm-harness-index \
  --commit 35bc8ab9ed4b42bb8955a6f0684a4f5529a05424 \
  --store-root ./my-new-cognee-store \
  --dataset opensiro-review-demo-v1 \
  --ids goose,langflow,openjiuwen-core --lexical
```

Replace `--ids` with `--all` to ingest every included record. The pinned Index snapshot above admitted **533** assessments, excluding **45 excluded** and **12 proposed** records.

Independent audit after import, using the same snapshot, dataset, and source tag. The audit refuses unknown dataset names rather than creating one:

```python
from cognee_community_connector_opensiro_vsm.audit import audit_dataset

# report = await audit_dataset(
#     snapshot, ("goose", "langflow"), "opensiro-review-demo-v1",
#     "opensiro_vsm_canonical_example", lexical=True
# )
# assert report["status"] == "PASS"
```

## Compatibility checks

The source review package includes `tests/test_sdk_contract.py`, which fails
if the **Cognee 1.6.4** native graph/provenance/lexical or local dataset lookup
APIs used by this connector change unexpectedly. It can be run offline with the
rest of the Python tests. These checks are API-shape checks, **not** a guarantee
that internal Cognee APIs will remain stable in future versions.

For a complete **clean Python 3.11 dependency-resolution check** (not yet
verified by OpenSiro on the dev-alpha CPU host), use an actual Python 3.11
interpreter and the built wheel in a brand-new virtual environment:

```bash
python3.11 -m venv /tmp/opensiro-cognee-py311
/tmp/opensiro-cognee-py311/bin/python -m pip install \
  /path/to/cognee_community_connector_opensiro_vsm-0.1.0-py3-none-any.whl
/tmp/opensiro-cognee-py311/bin/python -m pip check
/tmp/opensiro-cognee-py311/bin/python -m cognee_community_connector_opensiro_vsm \
  validate --repo /path/to/vsm-harness-index \
  --commit 35bc8ab9ed4b42bb8955a6f0684a4f5529a05424
```

**Actual completed wheel validation:** an independent Python 3.12 virtual
environment installed the built wheel **without fetching dependencies**, using
Cognee 1.6.4/DLT 1.30.0 already installed in a separate existing environment.
This confirmed package import, pinned-source validation (533 included), native
3-assessment import (69 graph nodes, 48 edges, 18 literal grades), and an
independent new-process audit. Python 3.11 source syntax parsing passed, but a
real Python 3.11 interpreter and fresh dependency installation were **not**
available on the test host. Do not represent this as Python 3.11 runtime PASS.

## Boundaries

This is a **fresh-only, single-host, graph-only** connector. It does not overwrite datasets, delete old records, run a hosted control plane, create embeddings, or perform automatic updates. Every attempt requires a different dataset name and the marker directory must be preserved alongside the Cognee store. Loss of that directory defeats the retry fence.

The independent audit intentionally checks a dataset already **owned by Cognee's default user** and refuses absent names; it does not create audit targets or resolve arbitrary shared-owner datasets.

Cognee's internal data-point, graph and provenance APIs have been validated **only with Cognee 1.6.4**. Lexical searches can return zero-overlap candidates; client applications should enforce a relevance guard.

The full-corpus B13 validation and B14–B16 SIGKILL studies are kept in the [original OpenSiro research branch](https://github.com/opensiro/cognee-community/tree/feat/opensiro-vsm-source/packages/connector/opensiro-vsm/docs), **not** shipped as deployment logic or destructive tests in this review branch. Research showed fail-closed detection and fresh-dataset recovery at specific checkpoints, not power-loss or arbitrary backend/distributed recovery.

### Licensing and attribution

The standalone connector package uses **Apache-2.0**, with the license text bundled in the wheel. [Cognee Community](https://github.com/topoteretes/cognee-community) and [OpenSiro Index](https://github.com/opensiro/vsm-harness-index) also declare Apache-2.0. The connector reads the Index's pinned Git tree without modification; assessment content remains attributed to its originating project, with a source URL, pinned Index commit, document SHA256 and reviewed upstream revision recorded. This does not relicense the evidence or third-party repositories linked by assessments.

Track the contribution in [opensiro/upstream](https://github.com/opensiro/upstream). All changes remain in OpenSiro's fork unless explicitly authorized for upstream submission.
