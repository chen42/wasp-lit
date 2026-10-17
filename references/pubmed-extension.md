# PubMed wrapper extension

Read this reference before live coordinator calls. Also read the installed `pubmed-database` skill and its search, fetch, bulk and cross-database linking references.

`scripts/pubmed_extension.py` imports the installed `scripts/pubmed_api.py`. The original wrapper and its existing callers remain unchanged. The extension uses only the wrapper's `_get`, `_post`, environment parameters, PMC client, EPost function and ELink function. Long encoded queries and ID batches use the wrapper's POST transport rather than oversized GET URLs. It adds parsing and count-preserving operations, not another HTTP client. A single wrapper instance remains alive throughout a run, sharing its rate limiter. API calls are serialized even when screening workers run concurrently.

| Operation | Input | Output |
|---|---|---|
| `search` | exact query, maximum IDs, optional history environment | count, PMIDs, query translation, warnings, sort, raw ESearch JSON |
| `fetch` | batch of selected PMIDs | complete parsed records and raw efetch XML; parse errors retained with the XML |
| `order_ids` | screened candidate PMIDs | publication-date order via EPost and ESearch, with transport history |
| `links` | PMID | PMC deposition links, not a guarantee of full-text access |
| `fulltext` | PMID and its linked PMC IDs | identity-verified JATS or BioC text, route attempts, sections/passages and reported license |

Parsed records retain inline title text, structured abstract sections, publication types, preprint status, date components, DOI/PMCID when supplied, and PubMed relationship metadata. They do not infer experimental context or certify publication status. Raw responses remain immutable sources.

The supplied source XML is authoritative. Flattened abstract text includes section labels and preserves section text and punctuation; `abstract_sections` preserves the original section text separately. Workers quote the saved abstract exactly. Original fetch responses remain as immutable source snapshots; if a record changes, older parsed content can be recovered from the saved response without storing a duplicate per-record JSON file.

Full text tries NCBI PMC `efetch db=pmc` first, then Europe PMC `fullTextXML`, then PMC BioC. Full-text requests use dedicated per-provider HTTP clients with at most two retries per route (three attempts total), a 1-second initial backoff (ordinary delays are about 1 and 2 seconds) while retaining the HTTP client's 180-second ceiling for server-provided `Retry-After` values, and a 30-second per-request timeout. This policy does not alter PubMed discovery or Europe PMC metadata requests. HTTP 500 remains retryable; exhausted errors are recorded before falling through to the next provider. The policy is included in each full-text source snapshot. The timeout is not a whole-candidate deadline. Full-text identity requires a reported matching PMID or a PMCID that matches PubMed's deposition links. Conflicting identifiers and empty documents are rejected. Missing licensing information is `not checked`, not an inferred license. The implementation does not inspect images or supplements.

Errors retain redacted messages. Credentials are loaded locally by the wrapper; requests stored in the corpus contain only scientific arguments, never environment parameters. No direct `curl`, alternative E-utilities client, or fallback EDirect invocation is part of this implementation.

Live prerequisites: installed `uv`, the PubMed wrapper and its declared dependencies, safe local credential checks, and a recorded terms notification. The current safe-credentials workflow requests both `NCBI_API_KEY` and `USER_EMAIL` locally. NCBI itself permits keyless access at a lower rate, but this coordinator follows the installed skill's credential-check procedure before live use.
