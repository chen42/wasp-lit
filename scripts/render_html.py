#!/usr/bin/env python3
"""Render wasp-lit workspace Markdown files as interactive HTML documents with dark theme and PubMed tooltips."""

import argparse
from collections import defaultdict
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup
import markdown

SOURCECERY_NORD_CSS = """
:root {
  /* High-Contrast Dark Theme Palette */
  --bg-color: #14171d;
  --panel-bg-color: #1d212a;
  --card-bg-color: #1d212a;
  --text-color: #faf4e6;
  --text-muted: #c8c0b0;
  --header-color: #ffffff;
  --border-color: #3b4252;
  --border-light: #2a303c;
  --control-bg-color: #2e3440;
  --accent-color: #88c0d0;
  --accent-hover-color: #a3e8ff;
  --accent-bg-color: rgba(136, 192, 208, 0.14);
  --accent-bg-hover-color: rgba(136, 192, 208, 0.28);
  --pmid-color: #81a1c1;
  --pmid-hover-color: #88c0d0;
  --authoryear-color: #d8dee9;
  --authoryear-bg-color: #2e3440;
  --code-bg: #101217;
  --table-stripe: #232833;
  --badge-bg: #2e3440;
  --badge-text: #faf4e6;
  --shadow: 0 8px 32px rgba(0, 0, 0, 0.7);
  --tooltip-shadow: 0 12px 36px rgba(0, 0, 0, 0.85);
}

* {
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  margin: 0;
  padding: 0;
  background-color: var(--bg-color);
  color: var(--text-color);
  line-height: 1.65;
  font-size: 15px;
}

/* Header & Top Navigation Bar */
.top-nav {
  position: sticky;
  top: 0;
  z-index: 1000;
  background-color: var(--panel-bg-color);
  border-bottom: 1px solid var(--border-color);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3);
  padding: 10px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.nav-brand {
  font-weight: 700;
  font-size: 1.15em;
  color: var(--header-color);
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-brand .tag {
  font-size: 0.72em;
  background-color: var(--accent-color);
  color: #2e3440;
  padding: 2px 7px;
  border-radius: 4px;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.nav-link {
  color: var(--text-color);
  text-decoration: none;
  padding: 6px 12px;
  border-radius: 5px;
  font-size: 0.88em;
  font-weight: 500;
  transition: all 0.15s ease;
  background-color: transparent;
  border: 1px solid transparent;
}

.nav-link:hover {
  background-color: var(--control-bg-color);
  color: var(--header-color);
}

.nav-link.active {
  background-color: var(--accent-bg-color);
  color: var(--accent-color);
  border-color: rgba(136, 192, 208, 0.4);
  font-weight: 600;
}

/* Main Layout Container */
.container {
  max-width: 1060px;
  margin: 32px auto;
  padding: 0 24px 64px 24px;
}

.content-card {
  background-color: var(--card-bg-color);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  padding: 40px 48px;
  box-shadow: var(--shadow);
}

/* Typography */
h1, h2, h3, h4, h5, h6 {
  color: var(--header-color);
  font-weight: 700;
  line-height: 1.3;
}

h1 {
  font-size: 1.85em;
  margin-top: 0;
  margin-bottom: 0.5em;
  padding-bottom: 0.4em;
  border-bottom: 1px solid var(--border-color);
}

/* Document Header Metadata */
.doc-metadata {
  color: #8fa0b2;
  font-size: 0.88em;
  line-height: 1.65;
  margin-top: 4px;
  margin-bottom: 24px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-light);
}

.doc-metadata a {
  color: #8fa0b2;
  text-decoration: underline;
}

.doc-metadata a:hover {
  color: var(--accent-hover-color);
}

h2 {
  font-size: 1.35em;
  margin-top: 1.8em;
  margin-bottom: 0.6em;
  padding-bottom: 0.3em;
  border-bottom: 1px solid var(--border-light);
}

h3 {
  font-size: 1.15em;
  margin-top: 1.4em;
  margin-bottom: 0.4em;
}

p, ul, ol {
  margin-top: 0;
  margin-bottom: 1em;
}

ul, ol {
  padding-left: 26px;
}

li {
  margin-bottom: 6px;
}

strong {
  color: #fff9e6;
  font-weight: 600;
}

/* Links */
a {
  color: var(--accent-color);
  text-decoration: none;
  transition: color 0.15s, background-color 0.15s;
}

a:hover {
  color: #ffffff;
  text-decoration: underline;
}

/* PMID Links with Tooltip triggers */
a.pmid-link {
  display: inline;
  color: var(--pmid-color);
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  margin: 0;
  font-family: inherit;
  font-size: calc(1em - 2px);
  font-weight: 500;
  text-decoration: none;
  cursor: pointer;
  transition: color 0.15s ease, text-decoration 0.15s ease;
}

a.pmid-link:hover {
  color: var(--pmid-hover-color);
  text-decoration: underline;
  background: transparent;
  border: none;
  box-shadow: none;
  transform: none;
}

/* Tables */
table {
  width: 100%;
  border-collapse: collapse;
  margin: 24px 0;
  font-size: 0.9em;
  background-color: var(--card-bg-color);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  overflow: hidden;
  display: table;
}

th {
  background-color: var(--control-bg-color);
  color: var(--header-color);
  font-weight: 600;
  text-align: left;
  padding: 10px 14px;
  border-bottom: 2px solid var(--border-color);
}

td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border-light);
  color: var(--text-color);
  vertical-align: top;
}

tr:nth-child(even) td {
  background-color: var(--table-stripe);
}

tr:hover td {
  background-color: rgba(136, 192, 208, 0.08);
}

/* Code & Preformatted Text */
code {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  background-color: var(--code-bg);
  color: #ebcb8b;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.88em;
}

pre {
  background-color: var(--code-bg);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 14px 18px;
  overflow-x: auto;
}

pre code {
  background-color: transparent;
  padding: 0;
  color: #e5e9f0;
}

hr {
  border: 0;
  height: 1px;
  background-color: var(--border-color);
  margin: 28px 0;
}

/* SourceCery Tooltip */
#tooltip {
  display: none;
  position: absolute;
  background-color: #171b22;
  border: 1px solid var(--accent-color);
  border-radius: 8px;
  box-shadow: var(--tooltip-shadow);
  padding: 18px 20px;
  z-index: 10000;
  pointer-events: none;
  line-height: 1.55;
  color: var(--text-color);
  max-width: 540px;
  font-size: 13.5px;
  backdrop-filter: blur(6px);
  transition: opacity 0.15s ease;
}

#tooltip .pmid-badge {
  display: inline-block;
  background-color: var(--accent-color);
  color: #14171d;
  font-size: 0.75em;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  margin-bottom: 8px;
  font-family: monospace;
}

#tooltip .title {
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 6px;
  font-size: 1.05em;
  line-height: 1.35;
}

#tooltip .authors {
  font-style: italic;
  color: var(--authoryear-color);
  margin-bottom: 6px;
  font-size: 0.92em;
}

#tooltip .journal {
  font-size: 0.9em;
  color: var(--accent-color);
  margin-bottom: 12px;
  font-weight: 500;
}

#tooltip .abstract {
  font-size: 0.92em;
  max-height: 320px;
  overflow-y: auto;
  border-top: 1px solid var(--border-color);
  padding-top: 10px;
  color: var(--text-color);
  line-height: 1.55;
}

#tooltip .abstract p {
  margin: 0 0 8px 0;
}

#tooltip .loading {
  font-style: italic;
  color: var(--text-muted);
}

/* KPI Cards */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 14px;
  margin: 24px 0 32px 0;
}

.kpi-card {
  background-color: var(--panel-bg-color);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 16px 18px;
  text-align: left;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
}

.kpi-value {
  font-size: 1.85em;
  font-weight: 700;
  color: var(--accent-color);
  line-height: 1.1;
  margin-bottom: 4px;
}

.kpi-card.kpi-focused .kpi-value {
  color: #ebcb8b;
}

.kpi-card.kpi-fulltext .kpi-value {
  color: #b48ead;
}

.kpi-label {
  font-size: 0.82em;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
}

.kpi-sub {
  font-size: 0.8em;
  color: var(--authoryear-color);
  margin-top: 4px;
}

/* Tree Structure Styles */
.tree-container {
  margin: 28px 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.tree-controls {
  display: flex;
  gap: 10px;
  margin-bottom: 4px;
}

.tree-toggle-btn {
  background-color: var(--control-bg-color);
  color: var(--text-color);
  border: 1px solid var(--border-color);
  border-radius: 5px;
  padding: 5px 12px;
  font-size: 0.82em;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tree-toggle-btn:hover {
  background-color: var(--accent-bg-color);
  color: var(--accent-color);
  border-color: rgba(136, 192, 208, 0.4);
}

details.tree-branch {
  margin: 0;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background-color: rgba(29, 33, 42, 0.6);
  overflow: hidden;
  transition: all 0.2s ease;
}

details.tree-branch[open] {
  background-color: var(--panel-bg-color);
  border-color: rgba(136, 192, 208, 0.35);
}

summary.tree-summary {
  padding: 14px 18px;
  cursor: pointer;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: space-between;
  user-select: none;
  background-color: var(--control-bg-color);
  transition: background-color 0.15s ease;
  color: var(--header-color);
  list-style: none;
}

summary.tree-summary::-webkit-details-marker {
  display: none;
}

summary.tree-summary:hover {
  background-color: rgba(136, 192, 208, 0.15);
}

.tree-summary-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.tree-summary-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tree-arrow {
  display: inline-block;
  transition: transform 0.2s ease;
  font-size: 0.75em;
  color: var(--accent-color);
}

details.tree-branch[open] > summary.tree-summary .tree-arrow {
  transform: rotate(90deg);
}

.tree-category-name {
  font-size: 1.05em;
  color: #ffffff;
  font-weight: 700;
}

.tree-branch-body {
  padding: 16px 20px 20px 20px;
  border-top: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tree-leaf {
  display: flex;
  flex-direction: column;
  padding: 12px 16px;
  border-radius: 6px;
  background-color: var(--card-bg-color);
  border: 1px solid var(--border-light);
  transition: border-color 0.15s ease;
}

.tree-leaf:hover {
  border-color: rgba(136, 192, 208, 0.4);
}

.tree-leaf.is-focused {
  border-left: 4px solid #ebcb8b;
  background-color: rgba(235, 203, 139, 0.04);
}

.tree-leaf-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 6px;
}

.tree-leaf-title {
  font-weight: 600;
  color: #ffffff;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.tree-leaf-title code {
  color: #88c0d0;
  font-size: 0.82em;
}

.tree-stats {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.tree-terms {
  font-size: 0.85em;
  color: var(--text-muted);
  line-height: 1.45;
  margin-top: 4px;
}

.tree-fulltexts {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-light);
  font-size: 0.86em;
}

.tree-fulltexts-label {
  font-weight: 600;
  color: #b48ead;
  margin-bottom: 6px;
}

.tree-fulltexts ul {
  margin: 0;
  padding-left: 20px;
}

.tree-fulltexts li {
  margin-bottom: 4px;
  line-height: 1.4;
}

/* Badges */
.badge {
  display: inline-flex;
  align-items: center;
  font-size: 0.74em;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 4px;
  line-height: 1.3;
}

.badge-focused {
  background-color: rgba(235, 203, 139, 0.18);
  color: #ebcb8b;
  border: 1px solid rgba(235, 203, 139, 0.4);
}

.badge-standard {
  background-color: rgba(216, 222, 233, 0.08);
  color: var(--authoryear-color);
  border: 1px solid rgba(216, 222, 233, 0.18);
}

.badge-stat {
  background-color: var(--control-bg-color);
  color: var(--text-color);
  border: 1px solid var(--border-color);
  font-size: 0.76em;
}

.badge-stat strong {
  color: var(--accent-color);
  margin-left: 3px;
}

.badge-stat.stat-included strong {
  color: #a3be8c;
}

.badge-stat.stat-excluded strong {
  color: #d08770;
}

.badge-stat.stat-fulltext strong {
  color: #b48ead;
}
"""

SOURCECERY_JS = """
// SourceCery Tooltip and Dynamic Retrieval Logic
(function() {
  const tooltip = document.getElementById("tooltip");
  let currentHoverPmid = null;
  const fetchingPmids = new Set();

  function formatAuthors(authorsArr) {
    if (!authorsArr || authorsArr.length === 0) return "Unknown authors";
    if (authorsArr.length > 3) {
      return `${authorsArr[0]}, ..., ${authorsArr[authorsArr.length - 1]}`;
    }
    return authorsArr.join(", ");
  }

  function positionTooltip(e) {
    if (!tooltip || tooltip.style.display !== "block") return;
    const pad = 16;
    const tipWidth = tooltip.offsetWidth || 480;
    const tipHeight = tooltip.offsetHeight || 260;
    let left = e.pageX + pad;
    let top = e.pageY + pad;

    // Viewport collision handling
    if (e.clientX + pad + tipWidth > window.innerWidth) {
      left = Math.max(10, e.pageX - tipWidth - pad);
    }
    if (e.clientY + pad + tipHeight > window.innerHeight) {
      top = Math.max(10, e.pageY - tipHeight - pad);
    }
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
  }

  async function fetchBatchPmidData(pmids) {
    const toFetch = pmids.filter(p => !window.pmidCache[p]);
    if (toFetch.length === 0) return;
    try {
      const response = await fetch(
        `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id=${toFetch.join(",")}`
      );
      const xmlText = await response.text();
      const xmlDoc = new DOMParser().parseFromString(xmlText, "text/xml");
      xmlDoc.querySelectorAll("PubmedArticle").forEach((article) => {
        const pmid = article.querySelector("PMID")?.textContent;
        if (!pmid) return;

        const firstAuthorLastName =
          article.querySelector("Author LastName")?.textContent || "N/A";
        const year =
          article.querySelector("PubDate Year")?.textContent || "N/A";
        const title =
          article.querySelector("ArticleTitle")?.textContent ||
          "No Title Found";
        const abstractText =
          Array.from(article.querySelectorAll("AbstractText"))
            .map((el) => {
              const label = el.getAttribute("Label");
              return (label ? "<strong>" + label + ":</strong> " : "") + el.textContent;
            })
            .join("<br><br>") || "No Abstract Found.";

        const authorsArray = Array.from(
          article.querySelectorAll("Author")
        ).map((author) =>
          `${author.querySelector("LastName")?.textContent || ""} ${author.querySelector("Initials")?.textContent || ""}`.trim()
        ).filter(Boolean);

        const journal =
          article.querySelector("Journal Title")?.textContent ||
          article.querySelector("Journal ISOAbbreviation")?.textContent || "";

        window.pmidCache[pmid] = {
          authorYear: `${firstAuthorLastName} ${year}`,
          tooltipData: {
            title,
            authors: formatAuthors(authorsArray),
            journal: year !== "N/A" ? `${journal} (${year})` : journal,
            abstract: abstractText,
          },
        };
      });
    } catch (error) {
      console.error("Failed to fetch batch PMID data:", error);
    }
  }

  function showTooltip(pmid, e) {
    const entry = window.pmidCache ? window.pmidCache[pmid] : null;
    if (entry && entry.tooltipData) {
      const d = entry.tooltipData;
      tooltip.innerHTML = `
        <div class="pmid-badge">PMID: ${pmid}</div>
        <div class="title">${d.title}</div>
        <div class="authors">${d.authors}</div>
        <div class="journal">${d.journal}</div>
        <div class="abstract">${d.abstract}</div>
      `;
    } else {
      tooltip.innerHTML = `
        <div class="pmid-badge">PMID: ${pmid}</div>
        <div class="loading">Fetching PubMed details from NCBI...</div>
      `;
      if (!fetchingPmids.has(pmid)) {
        fetchingPmids.add(pmid);
        fetchBatchPmidData([pmid]).then(() => {
          if (currentHoverPmid === pmid) {
            showTooltip(pmid, e);
          }
        });
      }
    }
    tooltip.style.display = "block";
    positionTooltip(e);
  }

  document.addEventListener("mouseover", (e) => {
    const target = e.target.closest("[data-pmid]");
    if (target) {
      const pmid = target.getAttribute("data-pmid");
      if (pmid) {
        currentHoverPmid = pmid;
        showTooltip(pmid, e);
      }
    }
  });

  document.addEventListener("mouseout", (e) => {
    const target = e.target.closest("[data-pmid]");
    if (target) {
      currentHoverPmid = null;
      if (tooltip) tooltip.style.display = "none";
    }
  });

  document.addEventListener("mousemove", (e) => {
    if (currentHoverPmid) {
      positionTooltip(e);
    }
  });
})();
"""


def extract_pubmed_cache_from_corpus(corpus_dir, extra_pmids=None):
    """Build an in-memory dictionary of PubMed metadata from corpus/articles.jsonl."""
    cache = {}
    articles_path = Path(corpus_dir) / "articles.jsonl"
    if articles_path.exists():
        with open(articles_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    art = json.loads(line)
                    pmid = str(art.get("pmid"))
                    authors = art.get("authors") or []
                    if len(authors) > 3:
                        display_authors = f"{authors[0]}, ..., {authors[-1]}"
                    elif authors:
                        display_authors = ", ".join(authors)
                    else:
                        display_authors = "Unknown authors"
                    year = (art.get("publication_date") or {}).get("Year") or "N/A"
                    first_ln = authors[0].split()[0] if authors else "N/A"
                    journal = art.get("journal") or ""
                    journal_label = f"{journal} ({year})" if journal and year != "N/A" else (journal or str(year))
                    abstract = art.get("abstract") or "No abstract recorded in corpus."
                    abstract_html = "<br><br>".join(html.escape(p) for p in abstract.split("\n") if p.strip())
                    cache[pmid] = {
                        "authorYear": f"{first_ln} {year}",
                        "tooltipData": {
                            "title": art.get("title") or "No Title Found",
                            "authors": display_authors,
                            "journal": journal_label,
                            "abstract": abstract_html,
                        },
                    }
                except Exception:
                    pass

    # Check if extra PMIDs need fetching from NCBI efetch
    missing = [str(p) for p in (extra_pmids or []) if str(p) not in cache]
    if missing:
        try:
            url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&retmode=xml&id={','.join(missing)}"
            req = urllib.request.Request(url, headers={"User-Agent": "wasp-lit/0.4.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_data = resp.read()
            root = ET.fromstring(xml_data)
            for article in root.findall(".//PubmedArticle"):
                pmid = article.findtext(".//PMID")
                if not pmid:
                    continue
                title = article.findtext(".//ArticleTitle") or "No Title Found"
                journal = article.findtext(".//Journal/Title") or article.findtext(".//Journal/ISOAbbreviation") or ""
                year = article.findtext(".//JournalIssue/PubDate/Year") or article.findtext(".//PubDate/Year") or "N/A"
                first_ln = article.findtext(".//AuthorList/Author[1]/LastName") or "N/A"
                authors_list = []
                for a in article.findall(".//AuthorList/Author"):
                    ln = a.findtext("LastName") or ""
                    init = a.findtext("Initials") or ""
                    full_a = f"{ln} {init}".strip()
                    if full_a:
                        authors_list.append(full_a)
                if len(authors_list) > 3:
                    display_authors = f"{authors_list[0]}, ..., {authors_list[-1]}"
                elif authors_list:
                    display_authors = ", ".join(authors_list)
                else:
                    display_authors = "Unknown authors"
                abstract_nodes = article.findall(".//Abstract/AbstractText")
                if abstract_nodes:
                    abstract_parts = []
                    for el in abstract_nodes:
                        lbl = el.attrib.get("Label")
                        txt = el.text or ""
                        abstract_parts.append(f"<strong>{html.escape(lbl)}:</strong> {html.escape(txt)}" if lbl else html.escape(txt))
                    abstract_html = "<br><br>".join(abstract_parts)
                else:
                    abstract_html = "No abstract available."
                cache[pmid] = {
                    "authorYear": f"{first_ln} {year}",
                    "tooltipData": {
                        "title": title,
                        "authors": display_authors,
                        "journal": f"{journal} ({year})" if year != "N/A" else journal,
                        "abstract": abstract_html,
                    },
                }
        except Exception as e:
            sys.stderr.write(f"Notice: Could not pre-fetch external PMIDs ({e}); fallback will load in browser.\n")

    return cache


NAV_PAGES = [
    ("synthesis", "synthesis.html", "Synthesis"),
    ("ontology", "ontology.html", "Ontology"),
    ("gene-function", "gene-function.html", "Gene Function"),
    ("user-decisions", "user-decisions.html", "User Decisions"),
    ("ai-decisions", "ai-decisions.html", "AI Decisions"),
    ("gwas-associations", "gwas-associations.html", "GWAS Associations"),
    ("README", "README.html", "Overview"),
]


def detect_accurate_provenance(workspace_path=None):
    """Accurately detect harness and model identity only when verified with high confidence."""
    harness = None
    model = None

    # 1. Check workspace context.json
    if workspace_path:
        ctx_file = Path(workspace_path) / "corpus" / "context.json"
        if ctx_file.exists():
            try:
                data = json.loads(ctx_file.read_text(encoding="utf-8"))
                if data.get("harness"):
                    harness = str(data["harness"]).strip()
                if data.get("llm_model"):
                    model = str(data["llm_model"]).strip()
                elif data.get("model"):
                    model = str(data["model"]).strip()
            except Exception:
                pass

    # 2. Check explicit environment overrides
    if not harness and os.environ.get("WASP_HARNESS"):
        harness = os.environ["WASP_HARNESS"].strip()
    if not model:
        for var in ("WASP_LLM_MODEL", "LLM_MODEL", "MODEL_NAME", "AGENT_MODEL"):
            val = os.environ.get(var)
            if val and val.strip():
                model = val.strip()
                break

    # 3. Google Antigravity detection
    if not harness and (os.environ.get("ANTIGRAVITY_AGENT") == "1" or os.environ.get("ANTIGRAVITY_APP_DATA_DIR")):
        harness = "Google Antigravity"
        if not model:
            app_data = os.environ.get("ANTIGRAVITY_APP_DATA_DIR")
            conv_id = os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
            if app_data and conv_id:
                transcript = Path(app_data) / "brain" / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
                if transcript.exists():
                    try:
                        with open(transcript, "r", encoding="utf-8") as f:
                            for line in f:
                                if "Model Selection" in line:
                                    m = re.search(r"Model Selection\` from None to ([^.]+)\.", line)
                                    if m:
                                        model = m.group(1).strip()
                    except Exception:
                        pass

    # 4. Pi.dev detection
    pi_keys = (
        "PI_CODING_AGENT_DIR",
        "PI_CODING_AGENT_PACKAGE_ROOT_ENV",
        "PI_SUBAGENT_RUNNER_CONFIG",
        "PI_SUBAGENT_CHILD",
        "PI_SESSION_ID",
        "PI_PACKAGE_DIR",
    )
    is_pi = any(os.environ.get(k) for k in pi_keys) or (Path.cwd() / ".pi").is_dir()
    if not harness and is_pi:
        harness = "Pi.dev"
        if not model:
            # Check local .pi/sessions or ~/.pi/agent/sessions/
            cwd = Path.cwd().resolve()
            pi_sessions_dir = cwd / ".pi" / "sessions"
            if not pi_sessions_dir.exists():
                alt_dir = Path.home() / ".pi" / "agent" / "sessions"
                clean_name = f"--{str(cwd).strip('/').replace('/', '-')}--"
                cand = alt_dir / clean_name
                if cand.exists():
                    pi_sessions_dir = cand
            if pi_sessions_dir.exists():
                session_files = sorted(pi_sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
                if session_files:
                    try:
                        with open(session_files[0], "r", encoding="utf-8") as f:
                            for line in f:
                                if '"model_change"' in line:
                                    ev = json.loads(line)
                                    if ev.get("modelId"):
                                        m_id = ev["modelId"]
                                        prov = ev.get("provider")
                                        model = f"{m_id} ({prov})" if prov else m_id
                    except Exception:
                        pass
            if not model:
                settings_file = Path.home() / ".pi" / "agent" / "settings.json"
                if settings_file.exists():
                    try:
                        st = json.loads(settings_file.read_text(encoding="utf-8"))
                        if st.get("defaultModel"):
                            dm = st["defaultModel"]
                            prov = st.get("defaultProvider")
                            model = f"{dm} ({prov})" if prov else dm
                    except Exception:
                        pass

    # 5. Claude Code detection
    if not harness and os.environ.get("CLAUDE_CODE") == "1":
        harness = "Claude Code"
        if not model and os.environ.get("ANTHROPIC_MODEL"):
            model = os.environ["ANTHROPIC_MODEL"].strip()

    # 6. CommandCode / OpenCode detection
    if not harness and (os.environ.get("COMMANDCODE") == "1" or os.environ.get("OPENCODE") == "1"):
        harness = "CommandCode" if os.environ.get("COMMANDCODE") == "1" else "OpenCode"
        if not model:
            model = os.environ.get("COMMANDCODE_MODEL") or os.environ.get("OPENCODE_MODEL")

    # 7. Ollama detection
    if not harness and (os.environ.get("OLLAMA_MODEL") or os.environ.get("OLLAMA_HOST")):
        harness = "Ollama"
        if not model and os.environ.get("OLLAMA_MODEL"):
            model = os.environ["OLLAMA_MODEL"].strip()

    return {"harness": harness, "model": model}


def detect_runtime_model(workspace_path=None):
    """Backwards-compatible wrapper returning only model name."""
    return detect_accurate_provenance(workspace_path).get("model")


def render_html_page(title, body_html, active_key, gene_symbol, cache_dict):
    """Wrap body HTML in the complete dark theme layout with nav and SourceCery script."""
    nav_links = []
    for key, filename, label in NAV_PAGES:
        active_cls = " active" if key == active_key else ""
        nav_links.append(f'<a href="./{filename}" class="nav-link{active_cls}">{label}</a>')
    nav_html = "\n        ".join(nav_links)

    cache_json = json.dumps(cache_dict, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
{SOURCECERY_NORD_CSS}
  </style>
</head>
<body>
  <header class="top-nav">
    <div class="nav-brand">
      <span>wasp-lit</span>
      <span class="tag">{html.escape(gene_symbol)}</span>
    </div>
    <nav class="nav-links">
        {nav_html}
    </nav>
  </header>

  <main class="container">
    <article class="content-card">
{body_html}
    </article>
  </main>

  <div id="tooltip"></div>

  <script>
    window.pmidCache = {cache_json};
  </script>
  <script>
{SOURCECERY_JS}
  </script>
</body>
</html>
"""


def process_markdown_file(md_path, workspace_dir, gene_symbol, pmid_cache):
    """Convert one Markdown file to HTML, rewrite .md links, tag PMIDs, and write .html file."""
    md_text = md_path.read_text(encoding="utf-8")
    raw_html = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    soup = BeautifulSoup(raw_html, "html.parser")

    # 1. Rewrite internal .md links to .html (and human-decisions to user-decisions)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "human-decisions" in href:
            href = href.replace("human-decisions", "user-decisions")
        if href.endswith(".md") or ".md#" in href:
            href = re.sub(r"\.md(\b|#)", r".html\1", href)
        a["href"] = href

    # 2. Tag existing PubMed links with class="pmid-link" and data-pmid
    for a in soup.find_all("a", href=True):
        m = re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", a["href"])
        if m:
            pmid = m.group(1)
            a["data-pmid"] = pmid
            classes = a.get("class", [])
            if "pmid-link" not in classes:
                classes.append("pmid-link")
            a["class"] = classes
            a["target"] = "_blank"

    # 3. Detect and tag PMIDs in text nodes (e.g. table cells, lists)
    # Check if number is in pmid_cache or in a PMID table column
    for text_node in list(soup.find_all(string=True)):
        if text_node.parent.name in ("a", "code", "pre", "script", "style", "h1"):
            continue
        # Find 7-8 digit integers
        matches = list(re.finditer(r"\b(\d{7,8})\b", str(text_node)))
        if not matches:
            continue

        # Replace matching PMIDs with links
        def _replace_pmid(match):
            val = match.group(1)
            # If it's a known PMID or parent is a table cell in a PMID column
            is_pmid = val in pmid_cache
            if not is_pmid:
                # Check context (e.g. text mentions 'PMID' nearby or inside table)
                parent = text_node.parent
                if parent.name in ("td", "th", "li", "p") and ("pmid" in str(parent).lower() or "abstract" in str(parent).lower()):
                    is_pmid = True
            if is_pmid:
                return f'<a class="pmid-link" data-pmid="{val}" href="https://pubmed.ncbi.nlm.nih.gov/{val}/" target="_blank">{val}</a>'
            return val

        new_text = re.sub(r"\b(\d{7,8})\b", _replace_pmid, str(text_node))
        if new_text != str(text_node):
            new_soup = BeautifulSoup(new_text, "html.parser")
            text_node.replace_with(new_soup)

    active_key = md_path.stem
    title = f"{gene_symbol} - {active_key.replace('-', ' ').title()}"
    h1 = soup.find("h1")
    if h1 and h1.text.strip():
        title = h1.text.strip()

    # 4. Tag document metadata block right after H1 and guarantee line breaks
    if h1:
        next_sibling = h1.find_next_sibling()
        if next_sibling and next_sibling.name == "p":
            text_content = next_sibling.get_text()
            if any(k in text_content for k in ("Date:", "Workspace/run:", "Model:", "Harness:", "Run:")):
                raw_lines = [l.strip() for l in re.split(r"[\r\n]+|<br\s*/?>", str(next_sibling)) if l.strip()]
                clean_lines = []
                for l in raw_lines:
                    cleaned = re.sub(r"^<p[^>]*>|</p>$", "", l).strip()
                    if cleaned:
                        clean_lines.append(cleaned)

                # Report harness and model only when accurately detected
                if md_path.stem == "synthesis":
                    prov = detect_accurate_provenance(workspace_dir)
                    has_harness = any(l.startswith("Harness:") for l in clean_lines)
                    has_model = any(l.startswith("Model:") for l in clean_lines)
                    if not has_harness and prov.get("harness"):
                        clean_lines.append(f"Harness: {prov['harness']}")
                    if not has_model and prov.get("model"):
                        clean_lines.append(f"Model: {prov['model']}")

                if len(clean_lines) > 1:
                    new_inner_html = "<br>\n".join(clean_lines)
                    new_p = BeautifulSoup(f'<p class="doc-metadata">{new_inner_html}</p>', "html.parser").find("p")
                    next_sibling.replace_with(new_p)
                else:
                    classes = next_sibling.get("class", [])
                    if "doc-metadata" not in classes:
                        classes.append("doc-metadata")
                    next_sibling["class"] = classes

    # Determine subset of cache needed for this file (or full cache)
    # For small/medium sets, full cache provides instant tooltips everywhere
    full_html = render_html_page(title, str(soup), active_key, gene_symbol, pmid_cache)

    out_path = md_path.with_suffix(".html")
    out_path.write_text(full_html, encoding="utf-8")
    return out_path


def generate_ontology_markdown(workspace_path):
    """Generate or update top-level ontology.md from workspace corpus data."""
    ws = Path(workspace_path).resolve()
    corpus_dir = ws / "corpus"
    if not corpus_dir.exists():
        return None

    # Load context
    ctx_file = corpus_dir / "context.json"
    ctx = json.loads(ctx_file.read_text(encoding="utf-8")) if ctx_file.exists() else {}
    gene = "Gene"
    if ctx.get("genes") and ctx["genes"][0].get("symbol"):
        gene = ctx["genes"][0]["symbol"]
    phenotype = ctx.get("phenotype", "phenotype")
    species = ctx.get("evidence_species", "human, mouse, rat")

    # Load ontology definition
    ont_file = corpus_dir / "ontology.json"
    ont_data = json.loads(ont_file.read_text(encoding="utf-8")) if ont_file.exists() else {}
    ont_concepts = ont_data.get("concepts", [])
    if not ont_concepts and isinstance(ont_data, dict):
        for cat, items in ont_data.items():
            if isinstance(items, dict):
                for name, terms in items.items():
                    ont_concepts.append({
                        "category": cat,
                        "id": f"{cat}/{name}",
                        "name": name,
                        "terms": terms if isinstance(terms, list) else [terms],
                    })

    # Load latest run
    runs_dir = corpus_dir / "runs"
    runs = sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime) if runs_dir.exists() else []
    run_data = json.loads(runs[-1].read_text(encoding="utf-8")) if runs else {}
    run_id = run_data.get("run_id", "r1")
    run_date = (run_data.get("created_at") or "2026-10-31")[:10]
    searches = run_data.get("searches", {})

    # Load fulltexts
    fulltexts_file = corpus_dir / "fulltexts.jsonl"
    fulltexts = []
    fulltext_pmids = set()
    if fulltexts_file.exists():
        with open(fulltexts_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    ft = json.loads(line)
                    fulltexts.append(ft)
                    fulltext_pmids.add(str(ft.get("pmid")))

    # Load articles
    articles_file = corpus_dir / "articles.jsonl"
    articles = {}
    if articles_file.exists():
        with open(articles_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    art = json.loads(line)
                    articles[str(art.get("pmid"))] = art

    # Load triage
    triage_file = corpus_dir / "triage.jsonl"
    triage_inc = defaultdict(int)
    triage_exc = defaultdict(int)
    if triage_file.exists():
        with open(triage_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    t = json.loads(line)
                    cid = t.get("concept_id") or "phenotype/direct"
                    dec = t.get("effective_decision")
                    if dec == "include":
                        triage_inc[cid] += 1
                    elif dec == "exclude":
                        triage_exc[cid] += 1

    # Load membership
    mem_file = corpus_dir / "membership.jsonl"
    concept_selected_pmids = defaultdict(set)
    concept_all_pmids = defaultdict(set)
    all_discovered_pmids = set()
    if mem_file.exists():
        with open(mem_file, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    m = json.loads(line)
                    cid = m.get("concept_id") or "phenotype/direct"
                    p = str(m.get("pmid"))
                    all_discovered_pmids.add(p)
                    concept_all_pmids[cid].add(p)
                    if m.get("abstract_selected"):
                        concept_selected_pmids[cid].add(p)

    CATEGORY_ORDER = ["phenotype", "drug", "addiction", "brain", "function", "cell", "stress", "psychiatric"]
    CATEGORY_TITLES = {
        "phenotype": "Phenotype Lane (Direct Association)",
        "drug": "Substances and Pharmacological Agents",
        "addiction": "Addiction and Operant Behavior",
        "brain": "Neuroanatomy and Neural Circuitry",
        "function": "Channel Biophysics and Signaling Pathways",
        "cell": "Cellular Populations and Subtypes",
        "stress": "Stress and Neuroendocrine Reactivity",
        "psychiatric": "Psychiatric and Behavioral Comorbidities",
    }

    # Group concept data
    cats = defaultdict(list)
    all_concepts_data = []

    if searches:
        for qid, s in searches.items():
            conc = s.get("concept") or {}
            cid = conc.get("id") or (conc.get("category", "") + "/" + conc.get("name", "")) or "phenotype/direct"
            cname = conc.get("name") or cid
            cat = conc.get("category") or s.get("lane") or "other"
            cap = s.get("abstract_cap", 30)
            count = s.get("count", 0)
            selected_pmids = [str(p) for p in s.get("selected_pmids", [])]
            terms = conc.get("search_terms") or conc.get("terms") or []

            ft_matches = []
            for pmid in fulltext_pmids:
                if pmid in selected_pmids or pmid in concept_selected_pmids.get(cid, set()):
                    art = articles.get(pmid, {})
                    ft_matches.append({
                        "pmid": pmid,
                        "title": art.get("title", "Unknown Title"),
                        "pmcid": next((f.get("pmcid", "") for f in fulltexts if str(f.get("pmid")) == pmid), ""),
                    })

            cdata = {
                "id": cid,
                "name": cname,
                "category": cat,
                "cap": cap,
                "is_focused": (cap == 200),
                "count": count,
                "selected_count": len(selected_pmids),
                "inc": triage_inc[cid],
                "exc": triage_exc[cid],
                "fulltexts": ft_matches,
                "terms": terms,
                "query": s.get("query", ""),
            }
            cats[cat].append(cdata)
            all_concepts_data.append(cdata)
    else:
        for c in ont_concepts:
            cid = c.get("id", "")
            cat = c.get("category", "other")
            cdata = {
                "id": cid,
                "name": c.get("name", cid),
                "category": cat,
                "cap": 30,
                "is_focused": False,
                "count": 0,
                "selected_count": 0,
                "inc": 0,
                "exc": 0,
                "fulltexts": [],
                "terms": c.get("terms", []),
                "query": "",
            }
            cats[cat].append(cdata)
            all_concepts_data.append(cdata)

    total_strata = len(all_concepts_data)
    focused_concepts = [c for c in all_concepts_data if c["is_focused"]]
    total_discovered = sum(c["count"] for c in all_concepts_data)
    unique_discovered = len(all_discovered_pmids) if all_discovered_pmids else total_discovered
    total_analyzed = len(articles) if articles else sum(c["selected_count"] for c in all_concepts_data)
    total_inc = sum(triage_inc.values())
    total_exc = sum(triage_exc.values())
    total_ft = len(fulltexts)

    # Build KPI HTML cards
    kpi_html = f'''<div class="kpi-grid">
  <div class="kpi-card">
    <div class="kpi-value">{total_strata}</div>
    <div class="kpi-label">Search Strata</div>
    <div class="kpi-sub">50 ontology + 1 direct</div>
  </div>
  <div class="kpi-card kpi-focused">
    <div class="kpi-value">{len(focused_concepts)}</div>
    <div class="kpi-label">Focused Concepts</div>
    <div class="kpi-sub">Elevated Cap: 200</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-value">{total_discovered:,}</div>
    <div class="kpi-label">Discovered Records</div>
    <div class="kpi-sub">{unique_discovered:,} unique PMIDs</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-value">{total_analyzed:,}</div>
    <div class="kpi-label">Analyzed Abstracts</div>
    <div class="kpi-sub">Peer-reviewed corpus</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-value">{total_inc} / {total_exc}</div>
    <div class="kpi-label">Triage Inclusions</div>
    <div class="kpi-sub">Included / Excluded</div>
  </div>
  <div class="kpi-card kpi-fulltext">
    <div class="kpi-value">{total_ft}</div>
    <div class="kpi-label">Full-Text PMC</div>
    <div class="kpi-sub">Retrieved & analyzed</div>
  </div>
</div>'''

    # Build hierarchical tree branches
    tree_branches = []
    ordered_cats = [c for c in CATEGORY_ORDER if c in cats]
    for c in sorted(cats.keys()):
        if c not in ordered_cats:
            ordered_cats.append(c)

    for cat in ordered_cats:
        clist = cats[cat]
        # Sort: focused first, then by count descending, then by name
        clist.sort(key=lambda x: (not x["is_focused"], -x["count"], x["name"]))

        cat_title = CATEGORY_TITLES.get(cat, cat.replace("_", " ").title())
        cat_discovered = sum(c["count"] for c in clist)
        cat_analyzed = sum(c["selected_count"] for c in clist)
        cat_inc = sum(c["inc"] for c in clist)
        cat_exc = sum(c["exc"] for c in clist)
        cat_ft = sum(len(c["fulltexts"]) for c in clist)
        cat_focused = sum(1 for c in clist if c["is_focused"])

        focused_badge_html = f'<span class="badge badge-focused">{cat_focused} focused</span>' if cat_focused > 0 else ""
        ft_badge_html = f'<span class="badge badge-stat stat-fulltext">Full-text: <strong>{cat_ft}</strong></span>' if cat_ft > 0 else ""

        leaf_nodes = []
        for c in clist:
            is_foc_cls = " is-focused" if c["is_focused"] else ""
            badge_foc = (
                '<span class="badge badge-focused">Focused (Cap 200)</span>'
                if c["is_focused"]
                else '<span class="badge badge-standard">Standard (Cap 30)</span>'
            )
            ft_leaf_badge = (
                f'<span class="badge badge-stat stat-fulltext">Full-text: <strong>{len(c["fulltexts"])}</strong></span>'
                if c["fulltexts"]
                else ""
            )

            terms_str = ", ".join(c["terms"][:10]) if c["terms"] else "Direct query matching gene and phenotype"
            if len(c["terms"]) > 10:
                terms_str += f", ... (+{len(c['terms']) - 10} more)"

            ft_list_html = ""
            if c["fulltexts"]:
                items = []
                for ft in c["fulltexts"]:
                    pmid_val = ft["pmid"]
                    pmcid_val = f" ({ft['pmcid']})" if ft.get("pmcid") else ""
                    t_val = ft["title"]
                    items.append(
                        f'<li><a class="pmid-link" data-pmid="{pmid_val}" href="https://pubmed.ncbi.nlm.nih.gov/{pmid_val}/" target="_blank">PMID {pmid_val}</a>{pmcid_val}: {t_val}</li>'
                    )
                ft_list_html = (
                    f'<div class="tree-fulltexts">'
                    f'<div class="tree-fulltexts-label">Full-Text PMC Articles ({len(c["fulltexts"])}):</div>'
                    f'<ul>{" ".join(items)}</ul>'
                    f'</div>'
                )

            leaf_html = f'''<div class="tree-leaf{is_foc_cls}">
  <div class="tree-leaf-header">
    <div class="tree-leaf-title">
      <span>{c['name']}</span>
      <code>{c['id']}</code>
      {badge_foc}
    </div>
    <div class="tree-stats">
      <span class="badge badge-stat">Cap: <strong>{c['cap']}</strong></span>
      <span class="badge badge-stat">Discovered: <strong>{c['count']:,}</strong></span>
      <span class="badge badge-stat">Analyzed: <strong>{c['selected_count']:,}</strong></span>
      <span class="badge badge-stat stat-included">Inc: <strong>{c['inc']}</strong></span>
      <span class="badge badge-stat stat-excluded">Exc: <strong>{c['exc']}</strong></span>
      {ft_leaf_badge}
    </div>
  </div>
  <div class="tree-terms"><strong>Search terms:</strong> {terms_str}</div>
  {ft_list_html}
</div>'''
            leaf_nodes.append(leaf_html)

        branch_html = f'''<details class="tree-branch">
  <summary class="tree-summary">
    <div class="tree-summary-left">
      <span class="tree-arrow">&#9654;</span>
      <span class="tree-category-name">{cat_title} ({cat})</span>
      <span class="badge badge-stat">{len(clist)} concepts</span>
      {focused_badge_html}
    </div>
    <div class="tree-summary-right">
      <span class="badge badge-stat">Discovered: <strong>{cat_discovered:,}</strong></span>
      <span class="badge badge-stat">Analyzed: <strong>{cat_analyzed:,}</strong></span>
      <span class="badge badge-stat stat-included">Inc: <strong>{cat_inc}</strong></span>
      <span class="badge badge-stat stat-excluded">Exc: <strong>{cat_exc}</strong></span>
      {ft_badge_html}
    </div>
  </summary>
  <div class="tree-branch-body">
    {" ".join(leaf_nodes)}
  </div>
</details>'''
        tree_branches.append(branch_html)

    tree_html = f'''<div class="tree-container">
<div class="tree-controls">
  <button type="button" class="tree-toggle-btn" onclick="document.querySelectorAll('details.tree-branch').forEach(d => d.open = true);">Expand All</button>
  <button type="button" class="tree-toggle-btn" onclick="document.querySelectorAll('details.tree-branch').forEach(d => d.open = false);">Collapse All</button>
</div>
{" ".join(tree_branches)}
</div>'''

    # Build reference table
    table_rows = [
        "| Category | Concept ID | Name | Priority | Cap | Discovered | Analyzed | Triage Inc | Triage Exc | Full-Text |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    sorted_for_table = sorted(all_concepts_data, key=lambda x: (x["category"], not x["is_focused"], -x["count"], x["name"]))
    for c in sorted_for_table:
        pri = "Focused" if c["is_focused"] else "Standard"
        ft_cnt = len(c["fulltexts"])
        table_rows.append(
            f"| {c['category']} | `{c['id']}` | {c['name']} | {pri} | {c['cap']} | {c['count']:,} | {c['selected_count']:,} | {c['inc']} | {c['exc']} | {ft_cnt} |"
        )
    table_md = "\n".join(table_rows)

    # Build full texts table
    ft_rows = [
        "| PMID | PMCID | Title | Journal (Year) | Mapped Concepts |",
        "| --- | --- | --- | --- | --- |",
    ]
    pmid_to_concs = defaultdict(list)
    for c in all_concepts_data:
        for ft in c["fulltexts"]:
            pmid_to_concs[ft["pmid"]].append(f"`{c['id']}`")

    for ft in fulltexts:
        p = str(ft.get("pmid"))
        art = articles.get(p, {})
        title = art.get("title", "Unknown")
        pmcid = ft.get("pmcid", "N/A")
        j = art.get("journal", "N/A")
        y = (art.get("publication_date") or {}).get("Year", "N/A")
        j_str = f"{j} ({y})" if y != "N/A" else j
        concs_str = ", ".join(sorted(set(pmid_to_concs.get(p, [])))) or "none"
        ft_rows.append(f"| [{p}](https://pubmed.ncbi.nlm.nih.gov/{p}/) | {pmcid} | {title} | {j_str} | {concs_str} |")
    ft_md = "\n".join(ft_rows)

    md_content = f'''# Literature Search Ontology and Corpus Structure

Date: {run_date}  
Workspace/run: {ws.name} ({run_id})  
Gene: {gene} | Phenotype: {phenotype}  
Search Strata: {total_strata} conceptual lanes ({total_strata - 1} ontology concepts + 1 direct phenotype query)  
Scope: {species}  

This document describes the structured search ontology, priority focus status, and literature corpus partitioning used to evaluate {gene} evidence in {phenotype}. PubMed queries were stratified into {total_strata} conceptual search strata across 8 biological categories.

To prioritize pathways directly mediating nicotine reinforcement, mesolimbic circuit signaling, and calcium channel neuroplasticity, {len(focused_concepts)} priority concepts were focused with an elevated abstract cap of 200 abstracts per concept. Secondary, contextual, and comorbidity concepts operated under a standard cap of 30 abstracts per concept.

{kpi_html}

## Hierarchical Search Ontology Tree

Click any category branch below to expand or collapse its concepts. Focused priority concepts are indicated with a gold badge and elevated abstract cap. Hover over any PMID link to inspect article metadata and abstracts.

{tree_html}

## Search Strata Reference Table

The table below lists all {total_strata} search strata evaluated in this corpus, including priority status, abstract caps, total PubMed discovered hits, analyzed abstracts, and triage outcomes.

{table_md}

## Analyzed Full-Text Corpus

The table below lists the {len(fulltexts)} full-text PMC articles retrieved and analyzed in this workspace, along with the ontology concepts each article supports.

{ft_md}
'''

    # Ensure no em dashes or en dashes
    for ch in ["\\u2014", "\\u2013"]:
        if ch in md_content:
            md_content = md_content.replace(ch, "-")

    out_file = ws / "ontology.md"
    out_file.write_text(md_content, encoding="utf-8")
    return out_file


def render_workspace_html(workspace_path):
    """Render all core workspace markdown files to interactive HTML."""
    ws = Path(workspace_path).resolve()
    context_path = ws / "corpus" / "context.json"
    gene_symbol = "wasp-lit"
    if context_path.exists():
        try:
            ctx = json.loads(context_path.read_text(encoding="utf-8"))
            genes = ctx.get("genes") or []
            if genes and genes[0].get("symbol"):
                gene_symbol = genes[0]["symbol"]
        except Exception:
            pass

    # Generate or refresh ontology.md from corpus if available
    try:
        generate_ontology_markdown(ws)
    except Exception as e:
        sys.stderr.write(f"Notice: Could not generate ontology.md ({e}).\\n")

    # Collect any PMIDs mentioned across markdown files
    extra_pmids = set()
    for md_file in ws.glob("*.md"):
        txt = md_file.read_text(encoding="utf-8")
        for num in re.findall(r"\b\d{7,8}\b", txt):
            extra_pmids.add(num)

    corpus_dir = ws / "corpus"
    pmid_cache = extract_pubmed_cache_from_corpus(corpus_dir, extra_pmids=extra_pmids)

    # Also save pmid-cache.js in workspace for external or local asset use
    cache_js_path = ws / "pmid-cache.js"
    cache_js_path.write_text(f"window.pmidCache = {json.dumps(pmid_cache, indent=2, ensure_ascii=False)};\n", encoding="utf-8")

    generated = []
    # Render all standard workspace deliverable files
    for key, filename, _ in NAV_PAGES:
        md_file = ws / (key + ".md")
        if not md_file.exists() and key == "user-decisions":
            fallback = ws / "human-decisions.md"
            if fallback.exists():
                md_file = fallback
        if md_file.exists():
            out_file = process_markdown_file(md_file, ws, gene_symbol, pmid_cache)
            generated.append(str(out_file))
            if md_file.name == "human-decisions.md":
                user_html = ws / "user-decisions.html"
                user_html.write_text(out_file.read_text(encoding="utf-8"), encoding="utf-8")
                generated.append(str(user_html))

    return {
        "workspace": str(ws),
        "gene": gene_symbol,
        "pmids_cached": len(pmid_cache),
        "generated_html_files": generated,
        "cache_js": str(cache_js_path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", help="Path to wasp-lit research workspace")
    args = parser.parse_args()
    res = render_workspace_html(args.workspace)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
