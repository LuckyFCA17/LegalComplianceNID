"""Connector interface: each connector yields normalised regulation dicts.

A normalised record has keys: jenis, nomor, tahun, judul, status_berlaku, url (the
regulation's own detail page), pdf_url, external_id (optional) and suggested
(optional list of obligation dicts).
"""
import time
import warnings
from urllib.parse import urlparse

import requests
from urllib3.exceptions import InsecureRequestWarning

from ..legal import normalize_jenis, normalize_status, parse_citation

# Some JDIH sites reject requests that do not look like a browser, so send browser-like headers.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36 LegalComplianceNID/1.1")
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

# Search keywords per category used when a connector has no explicit keyword list.
DEFAULT_KEYWORDS = {
    "K3": ["keselamatan dan kesehatan kerja", "keselamatan kerja", "kebakaran"],
    "Lingkungan": ["lingkungan hidup", "limbah", "baku mutu"],
    "Ketenagakerjaan": ["ketenagakerjaan", "pengupahan", "jaminan sosial"],
}


class ConnectorError(Exception):
    pass


class Connector:
    kind = "base"

    def __init__(self, base_url=None, config=None, session=None, timeout=25):
        self.base_url = (base_url or "").rstrip("/")
        self.config = config or {}
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        if self.config.get("user_agent"):
            self.session.headers["User-Agent"] = self.config["user_agent"]
        self.timeout = timeout
        self.delay = float(self.config.get("delay", 0.5))  # politeness pause between requests
        self.errors = []  # non-fatal request errors collected during fetch()
        self.notes = []   # informational remarks for the sync log
        self._last = 0.0
        self._warmed = False
        self._insecure = False

    def _warm_up(self):
        """Visit the home page once so session cookies (anti-bot / CSRF) are set like in a browser."""
        self._warmed = True
        if not self.base_url:
            return
        try:
            self._request(self.base_url + "/")
        except requests.RequestException:
            pass  # the real request will report the problem

    def _request(self, url, **kw):
        try:
            return self.session.get(url, timeout=self.timeout, verify=not self._insecure, **kw)
        except requests.exceptions.SSLError:
            # Several .go.id sites serve an incomplete certificate chain: browsers repair it, Python does not.
            # These are public, read-only pages, so by default retry without verification and say so.
            if self._insecure or not self.config.get("ssl_fallback", True):
                raise
            self._insecure = True
            self.notes.append(f"sertifikat SSL {urlparse(url).netloc} tidak lengkap; diakses tanpa verifikasi SSL")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                return self.session.get(url, timeout=self.timeout, verify=False, **kw)

    def keywords(self, categories=None):
        explicit = self.config.get("keywords")
        if explicit:
            return list(explicit)
        cats = categories or list(DEFAULT_KEYWORDS)
        out = []
        for c in cats:
            out.extend(DEFAULT_KEYWORDS.get(c, []))
        return out

    def get(self, url, **kw):
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        if not self._warmed:
            self._warm_up()
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", InsecureRequestWarning)
                resp = self._request(url, **kw)
            self._last = time.monotonic()
            resp.raise_for_status()
        except requests.HTTPError as exc:
            code = exc.response.status_code
            hint = {403: " (akses ditolak situs — kemungkinan proteksi bot/IP server)",
                    404: " (alamat tidak ditemukan — halaman dihapus/dipindah atau search_url perlu disesuaikan)",
                    429: " (terlalu banyak permintaan — naikkan 'delay' di konfigurasi sumber)"}.get(code, "")
            if code >= 500:
                hint = " (server JDIH sedang bermasalah — coba lagi nanti)"
            raise ConnectorError(f"HTTP {code} dari {url}{hint}") from exc
        except requests.RequestException as exc:
            self._last = time.monotonic()
            host = urlparse(url).netloc
            if isinstance(exc, requests.Timeout):
                reason = f"tidak merespons dalam {self.timeout} detik"
            elif isinstance(exc, requests.exceptions.SSLError):
                reason = "sertifikat SSL ditolak (set \"ssl_fallback\": true di konfigurasi)"
            elif isinstance(exc, requests.ConnectionError):
                reason = "tidak dapat terhubung (periksa koneksi internet / DNS / firewall)"
            else:
                reason = str(exc)[:160]
            raise ConnectorError(f"Gagal mengakses {host}: {reason}") from exc
        return resp

    def fetch(self, categories=None):
        """Yield normalised regulation dicts."""
        raise NotImplementedError

    def owns(self, url):
        """True when a stored detail URL belongs to this connector's site."""
        return bool(url and self.base_url and urlparse(url).netloc == urlparse(self.base_url).netloc)

    def fetch_detail(self, url):
        """Open a regulation's own page; return dict with pdf_url / status / judul (any may be None)."""
        return {}

    supports_lookup = False

    def lookup(self, jenis, nomor, tahun):
        """Find the regulation's detail page on this site. Returns a record or None."""
        return None


def make_record(jenis, nomor, tahun, judul, status=None, url=None, external_id=None, suggested=None,
                pdf_url=None):
    """Build a normalised record, or return None if mandatory parts are missing."""
    if not (jenis and nomor and judul):
        return None
    try:
        tahun = int(str(tahun)[:4]) if tahun else None
    except ValueError:
        tahun = None
    return {
        "jenis": normalize_jenis(jenis),
        "nomor": str(nomor).strip().upper(),
        "tahun": tahun,
        "judul": " ".join(str(judul).split()),
        "status_berlaku": normalize_status(status),
        # Without an explicit status a sync must not overwrite a known Dicabut/Diubah.
        "status_explicit": bool(status),
        "url": url,
        "pdf_url": pdf_url,
        "external_id": external_id,
        "suggested": suggested or [],
    }


def record_from_text(title, judul=None, **extra):
    """Build a record from a full citation string such as 'PP Nomor 50 Tahun 2012 tentang ...'."""
    parsed = parse_citation(title)
    if not parsed:
        return None
    return make_record(parsed["jenis"], parsed["nomor"], parsed["tahun"],
                       judul or parsed["judul"], **extra)
