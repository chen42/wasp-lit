"""Additive PubMed support using only the installed skill's HTTP client.

The installed pubmed_api.py is imported, not copied or modified. This module
adds count-preserving search and source-preserving fetch operations. All HTTP
requests use that wrapper's _get, _post, environment parameters and clients.
"""

import importlib.util
import json
import os
import re
import urllib.parse
from pathlib import Path
import xml.etree.ElementTree as ET


class BackendError(RuntimeError):
    pass


def text(element):
    return "".join(element.itertext()) if element is not None else None


def xml_object(element):
    """Keep date components as supplied rather than inventing missing dates."""
    return {child.tag: text(child) for child in element} if element is not None else None


def parse_records(xml):
    root = ET.fromstring(xml)
    errors = [text(e) for e in root.iter("ERROR")]
    if errors:
        raise BackendError("efetch returned an XML error")
    records = []
    for node in root:
        citation = node.find("MedlineCitation")
        article = citation.find("Article") if citation is not None else None
        book = node.find("BookDocument")
        if article is None and book is not None:
            citation, article = book, book
        if article is None:
            continue
        pmid = citation.findtext("PMID")
        if not pmid:
            continue
        sections = []
        for section in article.findall("Abstract/AbstractText"):
            sections.append({"label": section.get("Label"),
                             "category": section.get("NlmCategory"),
                             "text": text(section)})
        other_abstracts = []
        for other in citation.findall("OtherAbstract"):
            other_sections = [{"label": e.get("Label"), "category": e.get("NlmCategory"), "text": text(e)}
                              for e in other.findall("AbstractText")]
            other_abstracts.append({"language": other.get("Language"), "type": other.get("Type"),
                                    "sections": other_sections})
        has_text = lambda values: any(s["text"] and s["text"].strip() for s in values)
        abstract_source = ("BookDocument/Abstract" if book is not None else "Article/Abstract") if has_text(sections) else None
        if not has_text(sections) and other_abstracts:
            chosen = next((a for a in other_abstracts if a["language"] in ("eng", "en") and has_text(a["sections"])),
                          next((a for a in other_abstracts if has_text(a["sections"])), None))
            if chosen:
                sections = chosen["sections"]
                abstract_source = "OtherAbstract:" + str(chosen["language"])
        abstract = "\n".join((s["label"] + ": " if s["label"] else "") + s["text"]
                             for s in sections) if has_text(sections) else None
        identifiers = {}
        for identifier in node.findall(".//ArticleIdList/ArticleId"):
            identifiers.setdefault(identifier.get("IdType", "unknown"), []).append(text(identifier))
        for identifier in article.findall("ELocationID"):
            identifiers.setdefault(identifier.get("EIdType", "unknown"), []).append(text(identifier))
        types = [text(e) for e in article.findall("PublicationTypeList/PublicationType")]
        authors = []
        for author in article.findall("AuthorList/Author"):
            name = author.findtext("CollectiveName") or " ".join(
                p for p in [author.findtext("LastName"), author.findtext("Initials")] if p)
            if name:
                authors.append(name)
        pubdate = xml_object(article.find("Journal/JournalIssue/PubDate"))
        if pubdate is None and book is not None:
            pubdate = xml_object(book.find("Book/PubDate"))
        records.append({
            "pmid": pmid, "title": text(article.find("ArticleTitle")),
            "abstract": abstract, "abstract_sections": sections, "abstract_source": abstract_source,
            "other_abstracts": other_abstracts, "authors": authors,
            "volume": article.findtext("Journal/JournalIssue/Volume"),
            "issue": article.findtext("Journal/JournalIssue/Issue"), "pages": article.findtext("Pagination/MedlinePgn"),
            "languages": [text(e) for e in article.findall("Language")],
            "journal": article.findtext("Journal/Title") or article.findtext("Book/BookTitle"),
            "publication_date": pubdate,
            "article_dates": [{"type": e.get("DateType"), "components": xml_object(e)}
                              for e in article.findall("ArticleDate")],
            "publication_types": types,
            "is_preprint": any(t and t.strip().lower() == "preprint" for t in types),
            "identifiers": identifiers,
            "doi": next(iter(identifiers.get("doi", [])), None),
            "pmcid": next(iter(identifiers.get("pmc", [])), None),
            "relationships": [{"type": e.get("RefType"), "pmid": e.findtext("PMID"),
                               "source": e.findtext("RefSource"), "note": e.findtext("Note")}
                              for e in citation.findall("CommentsCorrectionsList/CommentsCorrections")],
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "publication_status_check": "not checked",
        })
    return records


EUROPEPMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

XLINK = "{http://www.w3.org/1999/xlink}href"


def parse_jats(xml_text, pmid, linked_pmcids, provider, url):
    """Parse a JATS article and verify its identity against the requested record.

    Both the Europe PMC REST route and the NCBI efetch db=pmc route return JATS for
    the same corpus, so one parser serves both and identity rules stay identical.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise BackendError("Full-text response is not well-formed XML") from error
    articles = [root] if root.tag == "article" else list(root.iter("article"))
    if len(articles) != 1:
        raise BackendError("Expected one JATS article")
    article = articles[0]
    identifiers = {}
    for node in article.iter():
        if node.tag == "article-id":
            key, value = node.get("pub-id-type"), (node.text or "").strip()
            if key and value:
                identifiers.setdefault(key, []).append(value)
    reported_pmid = next(iter(identifiers.get("pmid", [])), None)
    reported_pmc = next(iter(identifiers.get("pmcid", [])), None)
    normalize = lambda value: str(value).removeprefix("PMC").split(".")[0]
    linked = {normalize(value) for value in linked_pmcids}
    pmc_verified = reported_pmc is not None and normalize(reported_pmc) in linked
    if reported_pmid is not None and str(reported_pmid) != str(pmid):
        raise BackendError("Full-text PMID does not match requested PMID")
    if reported_pmid is None and not pmc_verified:
        raise BackendError("Full-text identity cannot be verified against PMID or linked PMCID")
    if reported_pmc is not None and linked and not pmc_verified:
        raise BackendError("Full-text PMCID does not match PubMed links")
    body = article.find(".//body")
    if body is None:
        raise BackendError("Full-text response has no body")
    passages = []
    for node in body.iter():
        if node.tag in ("title", "p", "td", "th", "caption", "speech"):
            value = " ".join("".join(node.itertext()).split())
            if value:
                passages.append({"tag": node.tag, "id": node.get("id"), "text": value})
    full_text = "\n".join(passage["text"] for passage in passages)
    if not full_text.strip():
        raise BackendError("Full-text body contains no text")
    license_node = next((node for node in article.iter() if node.tag == "license"), None)
    statement = " ".join("".join(license_node.itertext()).split()) if license_node is not None else None
    references = [node.get(XLINK) for node in article.iter()
                  if node.tag.endswith("license_ref") and node.get(XLINK)]
    for reference in references:
        if statement and statement.startswith(reference):
            statement = statement[len(reference):].strip()
    return {"pmid": str(pmid), "pmcid": "PMC" + normalize(reported_pmc) if pmc_verified else None,
            "doi": next(iter(identifiers.get("doi", [])), None), "full_text": full_text,
            "passages": passages, "provider": provider, "source_url": url,
            "license": statement or "not checked", "license_references": references,
            "license_type": license_node.get("license-type") if license_node is not None else None,
            "identity_basis": "reported PMID" if reported_pmid is not None else "linked PMCID",
            "evidence_level": "full text", "figures_reviewed": False, "supplements_reviewed": False}


def parse_bioc(data, pmid, linked_pmcids):
    """Reject mismatched identifiers and empty responses; retain BioC structure."""
    if not isinstance(data, (list, dict)) or isinstance(data, dict) and "error" in data:
        raise BackendError("BioC retrieval failed")
    containers = data if isinstance(data, list) else [data]
    documents = [doc for container in containers for doc in container.get("documents", [])]
    if len(documents) != 1:
        raise BackendError("Expected one BioC document")
    doc = documents[0]
    metadata = dict(doc.get("infons", {}))
    for passage in doc.get("passages", []):
        for key, value in passage.get("infons", {}).items():
            if key.startswith("article-id_") or key in ("pmid", "pmcid", "license"):
                metadata[key] = value
    reported_pmid = metadata.get("article-id_pmid") or metadata.get("pmid")
    reported_pmc = metadata.get("article-id_pmc") or metadata.get("pmcid") or doc.get("id")
    if reported_pmid is not None and str(reported_pmid) != str(pmid):
        raise BackendError("BioC PMID does not match requested PMID")
    normalized = lambda value: str(value).removeprefix("PMC")
    linked = {normalized(v) for v in linked_pmcids}
    pmc_verified = reported_pmc is not None and normalized(reported_pmc) in linked
    if reported_pmid is None and not pmc_verified:
        raise BackendError("BioC identity cannot be verified against PMID or linked PMCID")
    if reported_pmc is not None and linked and not pmc_verified:
        raise BackendError("BioC PMCID does not match PubMed links")
    passages = doc.get("passages", [])
    full_text = "\n".join(p.get("text", "") for p in passages if p.get("text"))
    if not full_text.strip():
        raise BackendError("BioC response contains no full text")
    return {"pmid": str(pmid), "pmcid": "PMC" + normalized(reported_pmc) if pmc_verified else None,
            "full_text": full_text, "passages": passages, "raw_bioc": data,
            "license": metadata.get("license") or "not checked",
            "identity_basis": "reported PMID" if reported_pmid is not None else "linked PMCID",
            "evidence_level": "full text", "figures_reviewed": False, "supplements_reviewed": False}


class PubmedBackend:
    """One wrapper instance for a whole run, sharing its request rate limiter."""

    interface = "installed pubmed-database wrapper with PMC efetch, Europe PMC JATS and PMC BioC routes using bounded full-text retries"
    providers = ("pmc-efetch", "europepmc", "pmc-bioc")
    fulltext_retry_policy = {
        "max_retries": 2,
        "attempts_per_route": 3,
        "timeout_seconds": 30,
        "backoff_base_seconds": 1,
        "backoff_max_seconds": 180,
    }

    def __init__(self, wrapper):
        self.wrapper_path = Path(wrapper).expanduser().resolve()
        spec = importlib.util.spec_from_file_location("wasp_installed_pubmed", self.wrapper_path)
        if spec is None or spec.loader is None:
            raise BackendError("Cannot import installed PubMed wrapper")
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)
        self.api.dotenv.load_dotenv(Path.home() / ".env")

    def redact(self, value):
        value = str(value)
        for key in ("NCBI_API_KEY", "USER_EMAIL"):
            secret = os.environ.get(key)
            if secret:
                value = value.replace(secret, "<redacted>")
        return re.sub(r"(?i)(api_key|email|token)=([^&\s]+)", r"\1=<redacted>", value)

    def checked(self, data):
        if isinstance(data, dict) and "error" in data:
            raise BackendError(self.redact(data["error"]))
        return data

    def request(self, endpoint, params, raw=False):
        url = self.api.EUTILS_BASE + "/entrez/eutils/" + endpoint
        if len(urllib.parse.urlencode(params)) > 1800:
            result = self.checked(self.api._post(url, params))
            return result if raw else json.loads(result)
        return self.checked(self.api._get(url, params, raw=True) if raw else self.api._get(url, params))

    def search(self, query, max_results=9999, retstart=0, webenv="", query_key=""):
        if not 0 <= max_results <= 9999 or not 0 <= retstart < 9999:
            raise BackendError("PubMed ESearch window must remain below 10,000")
        params = self.api._env_params() | {"db": "pubmed",
                    "retmax": max_results, "retstart": retstart, "sort": "pub_date", "retmode": "json"}
        # A stored History set is referenced with the query_key parameter, not term="#<key>".
        # Live ESearch rejected the term form with "Wrong subquery #1" and returned count 0.
        if query_key:
            params["query_key"] = query_key
        else:
            params["term"] = query
        if webenv:
            params["WebEnv"] = webenv
        raw = self.request("esearch.fcgi", params)
        result = raw.get("esearchresult", {})
        if result.get("ERROR") or result.get("errorlist") or "count" not in result or not isinstance(result.get("idlist"), list):
            return {"error": "Invalid ESearch response or unresolved query error", "raw_response": raw}
        return {"count": int(result["count"]), "pmids": [str(i) for i in result["idlist"]],
                "query_translation": result.get("querytranslation"),
                "warnings": result.get("warninglist", {}), "sort": "pub_date", "raw_response": raw}

    def fetch(self, pmids):
        params = self.api._env_params() | {"db": "pubmed", "id": ",".join(pmids),
                                          "rettype": "abstract", "retmode": "xml"}
        raw = self.request("efetch.fcgi", params, raw=True)
        try:
            return {"records": parse_records(raw), "raw_xml": raw}
        except (ET.ParseError, BackendError) as error:
            return {"records": [], "raw_xml": raw, "parse_error": str(error)}

    def order_ids(self, pmids):
        history = self.checked(self.api.cache_results_history(pmids))
        if not history.get("webenv") or not history.get("query_key"):
            raise BackendError("Invalid PubMed history response")
        result = self.search("", min(len(pmids), 9999), webenv=history["webenv"], query_key=history["query_key"])
        return result | {"history": history}

    def links(self, pmid):
        """Collect candidate identifiers from two independent routes to the PMC corpus."""
        pubmed = self.checked(self.api.find_linked_biological_data(pmid, "pmc", "pubmed_pmc"))
        if not isinstance(pubmed, list):
            raise BackendError("Invalid PubMed PMC link response")
        europepmc = self.europepmc_record(pmid)
        candidate_pmcids = []
        for value in [str(v) for v in pubmed] + ([europepmc.get("pmcid")] if europepmc.get("pmcid") else []):
            normalized = str(value).removeprefix("PMC").split(".")[0]
            if normalized and normalized not in candidate_pmcids:
                candidate_pmcids.append(normalized)
        return {"pmid": str(pmid), "pubmed_pmcids": [str(v) for v in pubmed],
                "europepmc": europepmc, "candidate_pmcids": candidate_pmcids}

    def europepmc_record(self, pmid):
        """Metadata identity and licence from Europe PMC, used for identity cross-checking."""
        params = {"query": f"EXT_ID:{pmid} AND SRC:MED", "resultType": "core", "format": "json"}
        try:
            data = self.api._get(f"{EUROPEPMC_BASE}/search", params, client=self.ebi_client())
        except Exception as error:
            return {"status": "error", "error": self.redact(error)}
        if isinstance(data, dict) and "error" in data:
            return {"status": "error", "error": self.redact(data["error"])}
        if not isinstance(data, dict):
            return {"status": "error", "error": "Unexpected Europe PMC metadata response"}
        results = (data.get("resultList") or {}).get("result") or []
        if not results:
            return {"status": "not found"}
        item = results[0]
        return {"status": "ok", "pmcid": item.get("pmcid"), "doi": item.get("doi"),
                "isOpenAccess": item.get("isOpenAccess"), "inEPMC": item.get("inEPMC"),
                "inPMC": item.get("inPMC"), "hasPDF": item.get("hasPDF"),
                "license": item.get("license"), "source": item.get("source")}

    def ebi_client(self):
        if getattr(self, "_ebi_client", None) is None:
            self._ebi_client = self.api.http_client.HttpClient(EUROPEPMC_BASE, qps=3)
        return self._ebi_client

    def fulltext_http_client(self, attr, base_url, qps):
        client = getattr(self, attr, None)
        if client is None:
            policy = self.fulltext_retry_policy
            client = self.api.http_client.HttpClient(
                base_url, qps=qps, max_retries=policy["max_retries"],
                timeout=policy["timeout_seconds"],
                backoff_base=policy["backoff_base_seconds"],
                backoff_max=policy["backoff_max_seconds"])
            setattr(self, attr, client)
        return client

    def ebi_fulltext_client(self):
        return self.fulltext_http_client("_ebi_fulltext_client", EUROPEPMC_BASE, qps=3)

    def eutils_fulltext_client(self):
        qps = 10 if os.environ.get("NCBI_API_KEY") else 3
        return self.fulltext_http_client("_eutils_fulltext_client", self.api.EUTILS_BASE, qps)

    def pmc_fulltext_client(self):
        qps = 10 if os.environ.get("NCBI_API_KEY") else 3
        return self.fulltext_http_client("_pmc_fulltext_client", self.api.PMC_BIOC_BASE, qps)

    def fulltext(self, pmid, links):
        """Try each independent route in order, recording every attempt.

        A route that answers definitively either supplies the document or confirms
        absence from the PMC corpus. A transport or parsing failure is recorded as an
        error and does not by itself confirm absence.
        """
        pmcids = list(links.get("candidate_pmcids") or [])
        attempts = []
        for name in self.providers:
            attempt = self.provider_document(name, pmid, pmcids)
            attempts.append(attempt)
            if attempt["status"] == "retrieved":
                return {"status": "retrieved", "provider": name, "document": attempt["document"],
                        "attempts": attempts, "candidate_pmcids": pmcids, "pmid": str(pmid),
                        "retry_policy": dict(self.fulltext_retry_policy)}
        negatives = [a for a in attempts if a["status"] == "unavailable"]
        failures = [a for a in attempts if a["status"] == "error"]
        if negatives:
            return {"status": "unavailable", "attempts": attempts, "candidate_pmcids": pmcids, "pmid": str(pmid),
                    "reason": "no route served this article",
                    "confirmed_by": [a["provider"] for a in negatives],
                    "errored": [a["provider"] for a in failures],
                    "retry_policy": dict(self.fulltext_retry_policy)}
        return {"status": "failed", "attempts": attempts, "candidate_pmcids": pmcids, "pmid": str(pmid),
                "error": "; ".join(f"{a['provider']}: {a.get('error')}" for a in failures) or
                         "no usable full-text route for this candidate",
                "retry_policy": dict(self.fulltext_retry_policy)}

    def provider_document(self, name, pmid, pmcids):
        try:
            if name == "europepmc":
                if not pmcids:
                    return {"provider": name, "status": "unavailable", "reason": "no PMCID known"}
                url = f"{EUROPEPMC_BASE}/PMC{pmcids[0]}/fullTextXML"
                raw = self.api._get(url, raw=True, client=self.ebi_fulltext_client())
                if isinstance(raw, dict) and "error" in raw:
                    return self.provider_error(name, raw["error"])
                return self.jats_attempt(name, raw, pmid, pmcids, url)
            if name == "pmc-efetch":
                if not pmcids:
                    return {"provider": name, "status": "unavailable", "reason": "no PMCID known"}
                url = f"{self.api.EUTILS_BASE}/entrez/eutils/efetch.fcgi?db=pmc&id={pmcids[0]}"
                params = self.api._env_params() | {"db": "pmc", "id": pmcids[0], "retmode": "xml"}
                raw = self.api._get(url.split("?")[0], params, raw=True, client=self.eutils_fulltext_client())
                if isinstance(raw, dict) and "error" in raw:
                    return self.provider_error(name, raw["error"])
                return self.jats_attempt(name, raw, pmid, pmcids, url)
            if name == "pmc-bioc":
                data = self.api._get(f"{self.api.PMC_BIOC_BASE}/{pmid}/unicode", client=self.pmc_fulltext_client())
                if isinstance(data, dict) and "error" in data:
                    return self.provider_error(name, data["error"])
                try:
                    document = parse_bioc(data, pmid, pmcids)
                except (BackendError, TypeError, KeyError, AttributeError) as error:
                    return self.provider_failure(name, str(error), data)
                document["provider"] = name
                return {"provider": name, "status": "retrieved", "document": document}
            return {"provider": name, "status": "error", "error": "Unknown full-text provider"}
        except BackendError as error:
            return self.provider_failure(name, str(error))

    def jats_attempt(self, name, raw, pmid, pmcids, url):
        try:
            document = parse_jats(raw, pmid, pmcids, name, url)
        except BackendError as error:
            return self.provider_failure(name, str(error), raw)
        return {"provider": name, "status": "retrieved", "document": document}

    def provider_failure(self, name, message, raw=None):
        message = self.redact(message)
        if any(token in message for token in ("404", "no body", "no full text", "one JATS article",
                                             "contains no text")):
            return {"provider": name, "status": "unavailable", "reason": message}
        attempt = {"provider": name, "status": "error", "error": message}
        if raw is not None:
            attempt["raw_response"] = raw
        return attempt

    def provider_error(self, name, value):
        message = self.redact(value)
        if "404" in message:
            return {"provider": name, "status": "unavailable", "reason": message}
        return {"provider": name, "status": "error", "error": message}
