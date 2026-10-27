"""Connectors that scrape JDIH websites: search/listing pages and each regulation's own page.

Government JDIH sites change their markup from time to time, so the parsers are
deliberately heuristic:
  * result pages — find links to detail pages whose text (or the surrounding result
    card) contains a citation like "Peraturan Menteri Ketenagakerjaan Nomor 5 Tahun 2018",
    then take the "tentang ..." text, the Berlaku/Dicabut badge and any PDF link;
  * detail pages — read "Label: value" metadata (Status, Tentang/Judul) and the PDF link.
URL templates and link patterns can be overridden per source in its JSON config.

Known URL shapes (2026):
  BPK      search  https://peraturan.bpk.go.id/Search?keywords=...&p=2
           detail  https://peraturan.bpk.go.id/Details/145520/permenaker-no-6-tahun-2017
           pdf     https://peraturan.bpk.go.id/Download/189838/Permenaker%20Nomor%2024%20Tahun%202021.pdf
           (the PDF id differs from the detail id, so the detail page must be opened)
  Kemnaker list    https://jdih.kemnaker.go.id/peraturan?hal=2&keyword=...&nomor=&sort=terbaru&status=&tahun=
           detail  https://jdih.kemnaker.go.id/peraturan/detail/1588/peraturan-presiden-nomor-7-tahun-2019
           pdf     https://jdih.kemnaker.go.id/asset/data_puu/2025pmnaker013.pdf
Detail URLs end in a slug that spells the citation ("permenkes-no-11-tahun-2022"), which is used as a
fallback when the result card's text cannot be parsed.
"""
import re
from urllib.parse import quote_plus, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from ..legal import CITATION_RE, normalize_status, parse_citation, reg_key
from .base import Connector, ConnectorError, make_record

STATUS_RE = re.compile(r"\b(tidak berlaku|dicabut|diubah|berlaku)\b", re.IGNORECASE)
# Phrases containing "berlaku" that are dates, not the legal status.
NOT_STATUS_RE = re.compile(r"(tanggal|tgl\.?|mulai|masa)\s+berlaku", re.IGNORECASE)
CITATION_HEAD_RE = re.compile(r"(.{3,120}?)\s+(?:nomor|no\.?)\s*[\w./\-]+\s+tahun\s+\d{4}", re.IGNORECASE)
DEFAULT_PDF_PATTERN = r"(?i)(\.pdf(\?|#|$)|/download/)"


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


def _status_in(node):
    """Legal status shown in a node: prefer badge-like elements, then free text."""
    for el in node.find_all(class_=re.compile(r"badge|label|status|tag", re.IGNORECASE)):
        m = STATUS_RE.fullmatch(" ".join(el.get_text(" ").split()))
        if m:
            return m.group(1)
    text = NOT_STATUS_RE.sub(" ", " ".join(_lines(node)))
    m = STATUS_RE.search(text)
    return m.group(1) if m else None


def _pdf_link(node, page_url, pdf_pattern):
    rx = re.compile(pdf_pattern)
    for tag, attr in (("a", "href"), ("iframe", "src"), ("embed", "src"), ("object", "data")):
        for el in node.find_all(tag, **{attr: True}):
            target = el[attr]
            if rx.search(target):
                return urljoin(page_url, target.strip())
    return None


def citation_from_url(url):
    """Citation spelled by a detail URL's slug, e.g. .../permenkes-no-11-tahun-2022 -> Permenkes 11/2022."""
    for segment in reversed(urlparse(url).path.strip("/").split("/")):
        text = unquote(segment).replace("-", " ").replace("_", " ")
        parsed = parse_citation(text)
        if parsed:
            return parsed
    return None


def parse_results(html, page_url, link_pattern, pdf_pattern=DEFAULT_PDF_PATTERN):
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
        slug = citation_from_url(url)
        if not parsed and slug:
            parsed = slug
        if not parsed:
            m = CITATION_HEAD_RE.search(text_blob)
            parsed = parse_citation(m.group(0)) if m else None
        if not parsed:
            continue

        judul = parsed["judul"]
        if not judul:
            for line in lines:
                if line.lower().startswith("tentang "):
                    judul = line[8:]
                    break
            if not judul:
                # Fallback: the longest line that is not itself the citation or a badge.
                candidates = [ln for ln in lines if not CITATION_RE.match(ln)
                              and not STATUS_RE.fullmatch(ln) and len(ln) > 15]
                judul = max(candidates, key=len) if candidates else ""
        rec = make_record(parsed["jenis"], parsed["nomor"], parsed["tahun"], judul,
                          status=_status_in(card), url=url, external_id=href,
                          pdf_url=_pdf_link(card, page_url, pdf_pattern))
        if rec:
            seen.add(url)
            records.append(rec)
    return records


def _labelled(lines, labels):
    """Value following a metadata label, from 'Label: value' or 'Label' / ':' / 'value' line runs."""
    labels = [l.lower() for l in labels]
    for i, line in enumerate(lines):
        low = line.lower().rstrip(" :").strip()
        for lab in labels:
            if low == lab:
                for nxt in lines[i + 1:i + 3]:
                    val = nxt.lstrip(": ").strip()
                    if val:
                        return val
            m = re.match(rf"^{re.escape(lab)}\s*:\s*(.+)$", line, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    return None


def parse_detail(html, page_url, pdf_pattern=DEFAULT_PDF_PATTERN):
    """Extract PDF link, legal status and title from a regulation's own page."""
    soup = BeautifulSoup(html, "html.parser")
    for junk in soup(["script", "style", "nav", "footer", "header"]):
        junk.decompose()
    lines = _lines(soup)
    status = _labelled(lines, ["Status", "Status Peraturan", "Keterangan Status"])
    if status and not STATUS_RE.search(status):
        status = None
    judul = _labelled(lines, ["Tentang", "Judul", "T.E.U.", "Judul Peraturan"])
    if judul:
        parsed = parse_citation(judul)
        judul = parsed["judul"] if parsed and parsed["judul"] else judul
    return {
        "pdf_url": _pdf_link(soup, page_url, pdf_pattern),
        "status": normalize_status(status) if status else None,
        "judul": judul,
    }


class HtmlSearchConnector(Connector):
    kind = "html"
    default_search_url = ""
    default_link_pattern = r"detail"
    default_max_pages = 2

    @property
    def search_template(self):
        return self.config.get("search_url") or self.default_search_url

    @property
    def pdf_pattern(self):
        return self.config.get("pdf_pattern") or DEFAULT_PDF_PATTERN

    @property
    def link_pattern(self):
        return self.config.get("link_pattern") or self.default_link_pattern

    def search_url(self, keyword, page):
        return self.search_template.format(base=self.base_url, q=quote_plus(keyword or ""), page=page)

    def _pages(self, keyword):
        max_pages = int(self.config.get("max_pages", self.default_max_pages))
        previous = None
        for page in range(1, max_pages + 1):
            url = self.search_url(keyword, page)
            try:
                html = self.get(url).text
            except ConnectorError as exc:
                self.errors.append(str(exc))
                return
            records = parse_results(html, url, self.link_pattern, self.pdf_pattern)
            if not records:
                if page == 1 and keyword is None:
                    self.errors.append(f"Tidak ada peraturan yang dikenali di {url} — tampilan situs mungkin "
                                       "berubah; sesuaikan link_pattern/search_url")
                return
            urls = [r["url"] for r in records]
            if urls == previous:
                return  # the site ignored the page parameter and served the same page again
            previous = urls
            yield from records

    def fetch(self, categories=None):
        if "{q}" not in self.search_template:
            # Listing without keyword search: walk the newest pages once and classify locally.
            yield from self._pages(None)
            return
        found = False
        failed_in_a_row = 0
        for kw in self.keywords(categories):
            errors_before = len(self.errors)
            for rec in self._pages(kw):
                found = True
                yield rec
            failed_in_a_row = failed_in_a_row + 1 if len(self.errors) > errors_before else 0
            if failed_in_a_row >= 3:
                self.errors.append("Pencarian dihentikan setelah 3 kata kunci berturut-turut gagal")
                break
        if not found and not self.errors:
            self.errors.append(f"Pencarian di {self.search_url('…', 1)} tidak mengembalikan peraturan yang dikenali "
                               "— tampilan situs mungkin berubah; gunakan tombol Tes koneksi")

    default_lookup_url = None

    @property
    def lookup_template(self):
        tmpl = self.config.get("lookup_url") or self.default_lookup_url
        if tmpl:
            return tmpl
        return self.search_template if "{q}" in self.search_template else None

    @property
    def supports_lookup(self):
        return bool(self.lookup_template)

    def fetch_detail(self, url):
        return parse_detail(self.get(url).text, url, self.pdf_pattern)

    def lookup(self, jenis, nomor, tahun):
        """Search the site for one citation and return the matching result (with its detail URL)."""
        if not self.supports_lookup:
            return None
        key = reg_key(jenis, nomor, tahun)
        url = self.lookup_template.format(
            base=self.base_url, page=1, q=quote_plus(f"{jenis} No. {nomor} Tahun {tahun}"),
            jenis=quote_plus(jenis), nomor=quote_plus(str(nomor)), tahun=tahun or "")
        for rec in parse_results(self.get(url).text, url, self.link_pattern, self.pdf_pattern):
            if reg_key(rec["jenis"], rec["nomor"], rec["tahun"]) == key:
                return rec
        return None


class BpkConnector(HtmlSearchConnector):
    """JDIH BPK RI — https://peraturan.bpk.go.id (database peraturan nasional & daerah)."""
    kind = "bpk"
    default_search_url = "{base}/Search?keywords={q}&tentang=&nomor=&p={page}"
    default_link_pattern = r"(?i)Details/\d+"


class KemnakerConnector(HtmlSearchConnector):
    """JDIH Kementerian Ketenagakerjaan — https://jdih.kemnaker.go.id.

    The catalogue /peraturan pages with "hal" and filters with keyword / nomor / tahun.
    """
    kind = "kemnaker"
    default_search_url = "{base}/peraturan?hal={page}&keyword={q}&nomor=&sort=terbaru&status=&tahun="
    default_lookup_url = "{base}/peraturan?hal=1&keyword=&nomor={nomor}&sort=terbaru&status=&tahun={tahun}"
    default_link_pattern = r"(?i)peraturan/detail/\d+"
    default_max_pages = 5
