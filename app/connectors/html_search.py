"""Connectors that scrape the search result pages of JDIH websites.

Government JDIH sites change their markup from time to time, so the parser is
deliberately heuristic: it looks for links to detail pages whose text (or the
surrounding result card) contains a citation like
"Peraturan Menteri Ketenagakerjaan Nomor 5 Tahun 2018", then takes the
"tentang ..." text and the Berlaku/Dicabut badge from the same card.
URL templates and the detail-link pattern can be overridden per source in
its JSON config without touching code.
"""
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from ..legal import CITATION_RE, parse_citation
from .base import Connector, make_record

STATUS_RE = re.compile(r"\b(dicabut|diubah|berlaku|tidak berlaku)\b", re.IGNORECASE)
CITATION_HEAD_RE = re.compile(r"(.{3,120}?)\s+(?:nomor|no\.?)\s*[\w./\-]+\s+tahun\s+\d{4}", re.IGNORECASE)


def _card_for(anchor, max_up=5):
    """Climb from a link to the element that represents one search result."""
    node = anchor
    for _ in range(max_up):
        parent = node.parent
        if parent is None or parent.name in ("body", "html"):
            break
        node = parent
        classes = " ".join(node.get("class", []))
        if node.name in ("li", "tr", "article") or re.search(r"card|item|result|list-group", classes):
            break
    return node


def _lines(node):
    return [" ".join(t.split()) for t in node.stripped_strings if t.strip()]


def parse_results(html, page_url, link_pattern):
    soup = BeautifulSoup(html, "html.parser")
    link_re = re.compile(link_pattern)
    seen = set()
    records = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not link_re.search(href):
            continue
        url = urljoin(page_url, href)
        if url in seen:
            continue
        card = _card_for(a)
        lines = _lines(card)
        anchor_text = " ".join(a.get_text(" ").split())
        text_blob = " ".join(lines)

        parsed = parse_citation(anchor_text)
        if not parsed:
            # The citation may be in a heading next to the link instead of the link itself.
            for line in lines:
                parsed = parse_citation(line)
                if parsed:
                    break
        if not parsed:
            m = CITATION_HEAD_RE.search(text_blob)
            parsed = parse_citation(m.group(0)) if m else None
        if not parsed:
            continue

        judul = parsed["judul"]
        if not judul:
            for line in lines:
                low = line.lower()
                if low.startswith("tentang "):
                    judul = line[8:]
                    break
            if not judul:
                # Fallback: the longest line that is not itself the citation or a badge.
                candidates = [ln for ln in lines if not CITATION_RE.match(ln)
                              and not STATUS_RE.fullmatch(ln) and len(ln) > 15]
                judul = max(candidates, key=len) if candidates else ""
        status_m = STATUS_RE.search(text_blob)
        rec = make_record(parsed["jenis"], parsed["nomor"], parsed["tahun"], judul,
                          status=status_m.group(1) if status_m else None,
                          url=url, external_id=href)
        if rec:
            seen.add(url)
            records.append(rec)
    return records


class HtmlSearchConnector(Connector):
    kind = "html"
    default_search_url = ""
    default_link_pattern = r"detail"

    def search_url(self, keyword, page):
        tmpl = self.config.get("search_url") or self.default_search_url
        return tmpl.format(base=self.base_url, q=quote_plus(keyword), page=page)

    def fetch(self, categories=None):
        pattern = self.config.get("link_pattern") or self.default_link_pattern
        max_pages = int(self.config.get("max_pages", 2))
        for kw in self.keywords(categories):
            for page in range(1, max_pages + 1):
                url = self.search_url(kw, page)
                html = self.get(url).text
                records = parse_results(html, url, pattern)
                if not records:
                    break
                yield from records


class BpkConnector(HtmlSearchConnector):
    """JDIH BPK RI — https://peraturan.bpk.go.id (database peraturan nasional & daerah)."""
    kind = "bpk"
    default_search_url = "{base}/Search?keywords={q}&tentang=&nomor=&p={page}"
    default_link_pattern = r"/Details/\d+"


class KemnakerConnector(HtmlSearchConnector):
    """JDIH Kementerian Ketenagakerjaan — https://jdih.kemnaker.go.id."""
    kind = "kemnaker"
    default_search_url = "{base}/katalog-peraturan?search={q}&page={page}"
    default_link_pattern = r"(detail|peraturan)[-/]"
