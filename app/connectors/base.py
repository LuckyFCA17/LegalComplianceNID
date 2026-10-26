"""Connector interface: each connector yields normalised regulation dicts.

A normalised record has keys: jenis, nomor, tahun, judul, status_berlaku, url,
external_id (optional) and suggested (optional list of obligation dicts).
"""
from urllib.parse import urlparse

import requests

from ..legal import normalize_jenis, normalize_status, parse_citation

USER_AGENT = "LegalComplianceNID/1.0 (+compliance register; contact: admin)"

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

    def __init__(self, base_url=None, config=None, session=None, timeout=20):
        self.base_url = (base_url or "").rstrip("/")
        self.config = config or {}
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.timeout = timeout

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
        try:
            resp = self.session.get(url, timeout=self.timeout, **kw)
            resp.raise_for_status()
        except requests.RequestException as exc:
            reason = str(exc)
            reason = reason if len(reason) <= 160 else reason[:160] + "…"
            raise ConnectorError(f"Gagal mengakses {urlparse(url).netloc}: {reason}") from exc
        return resp

    def fetch(self, categories=None):
        """Yield normalised regulation dicts."""
        raise NotImplementedError


def make_record(jenis, nomor, tahun, judul, status=None, url=None, external_id=None, suggested=None):
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
