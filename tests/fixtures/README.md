# Synthetic fixtures

All PMIDs, abstracts, gene identities and experiments in these files are artificial software-test inputs. They are not literature sources and must not appear in a scientific synthesis or citation list. The coordinator blocks live PubMed calls from a workspace labeled `synthetic`.

The retrieval fixture covers a missing abstract, a direct finding, an explicit null result, an ambiguous short alias, an incidental gene mention, cellular stress without behavioral data, and a review. It exercises bookkeeping and a screening-worker smoke test. A model's output still requires deterministic validation and parent inspection; these cases are not a benchmark estimate of screening accuracy.

`screener-response.jsonl` is the retained output of the native synthetic smoke test on 2026-10-07. Workflow run: `7d417c8f-2b49-4b33-9394-582aa4f0a1e4`. Child run: `4f6d700f-9cb6-4068-8bf2-afb793a8fcbd`. SHA256: `bc1ad2168eee05297f3c05bcc8d3f17881f5cd23e175438ba4aca12343aeb7d3`. It provides a deterministic round-trip fixture, not evidence about an actual gene or phenotype.
