# Full-text selection and access

The default quota is 10 qualifying accessible full texts across one retrieval run. Candidates are included abstracts with direct or indirect phenotype relevance and the record hash used by that run. Reviews may qualify for background reading; they remain non-primary evidence in synthesis.

Prioritize exact target-phenotype and target-drug evidence first (`phenotype/direct` and `drug/nicotine` concept domains), followed by included evidence with direct phenotype relevance in other concept domains, then indirect phenotype relevance. A PMID assigned to multiple domains takes its highest priority. Within each group, use PubMed's `pub_date` order through the wrapper's EPost and ESearch support. Do not sort by indexing date, PMC deposition date or PMID number. Record the priority groups and their ordered PMIDs. The order operation must return every candidate in each group; more than 9,999 candidates requires a narrower set or an approved extension and cannot silently use a truncated order.

Walk each group in priority order, newest to oldest within the group. Reuse checksum-verified local full texts and count them toward the quota. A PubMed-to-PMC link establishes deposition, not open-access-subset membership or successful retrieval. Reject empty documents or conflicting identities.

Continue past records with no PMC link or a confirmed absence from all routes, recording the attempted routes. A transient error or unverifiable identity blocks selection at that candidate. Resume after resolving it; do not silently move to lower-priority candidates and call them the selected ten. There is no default 25-attempt cutoff. `--max-attempts` is an optional explicit bound and leaves a visible unfinished selection.

Stop when 10 full texts have been retained, the scoped candidate pool is exhausted, an unresolved failure blocks selection, or the explicit attempt bound is reached. Report target attainment, exhaustion, blockers and outcomes. Less than 10 is a valid outcome when the attempted route cannot supply 10. Do not broaden to unrelated papers to fill the quota.

Retain the raw response, extracted passages or sections, verified identifiers, acquisition time, checksums and any reported license. Machine provenance timestamps remain UTC; operational progress and local retrieval timestamps use America/Chicago with an explicit ISO-8601 offset. Missing license information is `not checked`. Retaining text does not establish permission to redistribute it. Do not claim figures or supplements were reviewed.

## Full-text routes

Three routes to PMC are tried in this order:

1. `pmc-efetch` reads the NCBI E-utilities `efetch` record with `db=pmc`. It uses a dedicated E-utilities client with the bounded full-text retry policy, because the request rate limiter enforces its base URL and rejects a cross-host request.
2. `europepmc` reads Europe PMC `fullTextXML` for the linked PMCID. The metadata call also supports PMCID cross-checking and license capture.
3. `pmc-bioc` reads the PMC BioC JSON route used by the installed wrapper.

All three return JATS or BioC for the same corpus, so identity rules are identical: the reported PMID must equal the requested PMID, or the reported PMCID must equal a linked PMCID. Every attempt is recorded in the source snapshot with its provider and status, and the `fulltexts` index records which provider served each document.

Full-text requests use dedicated clients so their retry policy does not change PubMed search or Europe PMC metadata behavior. Each route allows at most two retries, meaning up to three requests per route. The initial backoff is 1 second, so ordinary retry delays are about 1 and 2 seconds; the default 180-second ceiling remains in place so server-provided `Retry-After` delays are not shortened below the client's existing cap. Requests use a 30-second timeout. HTTP 500 remains retryable. If a route still fails, the client records the error and proceeds to the next route. The effective policy is preserved in each full-text source snapshot. The timeout is per request, not a hard end-to-end deadline for the whole candidate.

Route outcomes decide whether a candidate is resolvable:

- Retrieved: some route returned identity-verified text.
- Not available: no route served the article, and at least one route confirmed absence (HTTP 404, empty article set, or a body with no text). The record continues past this candidate, and the outcome lists which routes confirmed absence and which errored.
- Failed: every route errored. The candidate blocks selection, because a route that might hold the article never resolved.

A candidate with no PMCID from either metadata route is terminal and needs no document request.

Legitimate institutional access or a user-supplied paper can support a separate authorized retrieval when needed. Those routes require their own identity and provenance checks and are not automatic CLI fallbacks. Never bypass paywalls, authentication or rate limits. Do not restrict the original PubMed discovery query to open-access records.

## Discovery and retrieval are separate scopes

Europe PMC and the Lens API can also be used for discovery, not only retrieval. That changes which PMIDs exist for a scope, so it is a different workspace with its own frozen scope, licence notice and preprint policy. Adding a retrieval route does not change discovery membership in an existing workspace.

## Separating an upstream BioC outage from a record-specific failure

A blocked candidate means the fetch failed, not that the paper is unavailable. Before treating a block as a property of that record, confirm the route itself still works. The `pmcoa.cgi` root page documents the accepted pattern and answers normally during an outage of the document route:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi"
curl -sS -o /dev/null -w '%{http_code}\n' "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/PMC13900/unicode"
```

PMC13900 is the documentation's own example. If the root answers but the example document also returns 500, the document route is failing for every identifier and no amount of candidate-specific retrying will help. Space probes by a few seconds: this host also returns 429 for rapid requests, which is a different condition and looks nothing like a genuine retrieval.

On 2026-10-07 every identifier tested returned HTTP 500 from that route, with 429 interleaved, so the block on the newest candidate reflected a service outage rather than a missing article. Record the observation with its timestamp and rerun later. Do not reclassify a 500 as "not available through BioC"; that status is reserved for a confirmed 404, and treating an outage as unavailability would silently lower the quota.

## Referencing a stored History set

`order_ids` posts the candidate PMIDs to the History server and reads them back in publication order. The set must be referenced with the `query_key` and `WebEnv` parameters. Passing `term="#<query_key>"` returns count 0 with the messages `Wrong subquery #1` and `No items found.`, which is a rejected request rather than an empty candidate set. That failure raised `Full-text candidate order is incomplete; narrow scope or extend enumeration`, so check the history request before concluding that discovery missed records.

Full text and abstract evidence refer to one paper. Keep a later full-text interpretation linked to its source without overwriting the earlier abstract assessment or synthesis.
