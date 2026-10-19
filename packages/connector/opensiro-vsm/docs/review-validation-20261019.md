# B22 — Sharded Index and developer search flow: focused validation

**Date:** 2026-10-19 UTC. **Scope:** OpenSiro-only Draft PR #1, with source code at `bc18824fd594bef4931f7d78ab04d41f15749fcf` (before this report-only commit). No upstream review, merge, hosted service, model inference or vector retrieval.

## Pinned sources / environment

- Connector: OpenSiro [review branch](https://github.com/opensiro/cognee-community/tree/feat/opensiro-vsm-source-review) plus PR #1 code; original base `d176484e85da55c84450d67040cb4a2d096353c7`.
- Index: full pinned Git tree `5cbb1035538b8f80fa3362f1c99652f4fd7c55e8`, using its real sharded `assessments/<prefix>/<id>.md` layout.
- Python **3.12.3**, existing Cognee SDK **1.6.4** / DLT **1.30.0** development environment. This is a source checkout / `PYTHONPATH` run, **not** a fresh installed wheel or fresh Python 3.11 GitHub CI.
- Local isolated new store: `/tmp/opensiro-cognee-pr1-integration-20261019-a`; fresh dataset `opensiro-pr1-integration-a`; selected `ascension,balrog,dexto`. Historical research datasets not overwritten.

## Checks and actual observations

| Check | Observed result |
| --- | --- |
| Full pinned source validation through modified connector | **PASS**: 583 included / 48 excluded / 12 proposed; 631 catalog records |
| Full 43-test package suite on Cognee 1.6.4 | **PASS**, including three new zero-evidence/unknown-type guards |
| Ruff lint and `ruff format --check` on changed Python files | **PASS** |
| Fresh native `examples/example.py --lexical` | **PASS_FRESH_LOCAL_COGNEE_IMPORT**; 3 assessments, 60 nodes, 39 edges, 18 exact literal grades |
| Original pre-fix read-only audit on 3-document dataset | **FAIL_CLOSED** because no `VSMEvidence` nodes existed yet an expected zero count was compared against an omitted count |
| Fixed independent read-only audit + native `SearchType.CHUNKS_LEXICAL` | **PASS**, 10 ranked returns for `game environment observation action feedback`; zero-count `VSMEvidence` now accepted, other unexpected/mismatched node types still rejected |
| Source inspection using `--inspect ascension --show-markdown` | **PASS**: [Ascension pinned Markdown](https://github.com/opensiro/vsm-harness-index/blob/5cbb1035538b8f80fa3362f1c99652f4fd7c55e8/assessments/as/ascension.md), original source SHA256 `cd2a74a004f62a4bcf11fa2185d94e767b02ce3b23b2ec012ca86f44619ab6f3`, 23,974 characters; [reviewed upstream source tree](https://github.com/AI-Ascension/sts2-harness/tree/53312ddbb074f7c187e5f59d88b6585da797fe17) |
| Missing-dataset negative `--dataset opensiro-pr1-missing-negative` | **FAIL_CLOSED**, exit code 2, `Audit requires exactly one existing locally owned dataset`; no create-on-read API is called |
| Clean independent checkout of source `bc18824` | **PASS**: 43 unit tests, Ruff check/format and repeat read-only Cognee search + pinned source inspection |

The first failed audit is retained as a finding, not rewritten into an initial success. No fresh dataset import was repeated merely to hide it: the audit and search fix was validated against the **same** already imported dataset. The final clean-checkout verification used the published code head `bc18824`.

### Reproduce

From `packages/connector/opensiro-vsm`, install dependencies including pinned Cognee 1.6.4 (see README), and use the **same fixed Index commit** throughout:

```bash
python -m cognee_community_connector_opensiro_vsm validate --repo /path/to/index --commit 5cbb1035538b8f80fa3362f1c99652f4fd7c55e8
python examples/example.py --repo /path/to/index --commit 5cbb1035538b8f80fa3362f1c99652f4fd7c55e8 --store-root /tmp/unique-new-opensiro-store --dataset unique-new-name --ids ascension,balrog,dexto --lexical
python examples/search_and_inspect.py --repo /path/to/index --commit 5cbb1035538b8f80fa3362f1c99652f4fd7c55e8 --store-root /tmp/unique-new-opensiro-store --dataset unique-new-name --query "game environment observation action feedback" --top-k 10 --inspect ascension --show-markdown
python -m unittest discover -s tests -q
```

New import attempts **must use a fresh dataset and preserve attempt markers**. Only the *read-only* search/audit reuses an existing dataset.

## Remaining publication gates

- The original [B20 Python 3.11 clean wheel CI](https://github.com/opensiro/cognee-community/actions/runs/38942238109) validated the base `d176484` only. **No new clean Python 3.11 or upstream CI was run on this PR head**.
- Internal PR #1 has earlier unsigned commits: **DCO is not fully satisfied for upstream**. Prepare a correctly signed candidate commit history before upstream submission, without silently treating a signed final report as curing earlier commits.
- Recheck target `topoteretes/cognee-community` `main` drift and maintainer scope before submitting externally.
- Existing Cognee SDK 1.6.4, single host, full Markdown **stored but only six VSM function sections lexically indexed**. No full-body or embedding retrieval, no automatic updates, distributed recovery or comparative ranking claims.
- No production-quality user study or evidence that the search is better than other tools.

**Status:** focused development workflow integrated and exercised on one local fresh dataset; internal Draft PR remains review-only, no external issue/PR opened.
