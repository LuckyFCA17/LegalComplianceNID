"""Connector for JSON feeds in the JDIHN integration format.

Member sites of the Jaringan Dokumentasi dan Informasi Hukum Nasional (JDIHN)
publish their catalogue as JSON using shared field names (judul, noPeraturan,
tahun_pengundangan, jenis/singkatanJenis, status, urlDetailPeraturan, ...).
The feed URL differs per site, so it is configured on the source.
"""
from .base import Connector, ConnectorError, make_record
from ..legal import parse_citation


def _first(item, *keys):
    for k in keys:
        v = item.get(k)
        if v not in (None, ""):
            return v
    return None


def parse_feed(payload):
    if isinstance(payload, dict):
        payload = _first(payload, "data", "result", "results", "items") or []
    if not isinstance(payload, list):
        raise ConnectorError("Format feed JDIHN tidak dikenali (harus list atau {data: [...]})")
    records = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        judul = _first(item, "judul", "title", "tentang") or ""
        jenis = _first(item, "jenis", "jenisPeraturan", "bentuk", "singkatanJenis")
        nomor = _first(item, "noPeraturan", "nomor", "no_peraturan")
        tahun = _first(item, "tahun_pengundangan", "tahun", "tahunPengundangan")
        if not (jenis and nomor):
            # Some feeds only put the full citation in "judul".
            parsed = parse_citation(judul)
            if parsed:
                jenis, nomor, tahun, judul = parsed["jenis"], parsed["nomor"], parsed["tahun"], parsed["judul"]
        elif " tentang " in judul.lower():
            judul = judul[judul.lower().index(" tentang ") + 9:]
        rec = make_record(
            jenis, nomor, tahun, judul,
            status=_first(item, "status", "statusPeraturan", "keterangan_status"),
            url=_first(item, "urlDetailPeraturan", "url", "link", "urlDownload", "fileDownload"),
            external_id=str(_first(item, "idData", "id") or ""),
        )
        if rec:
            records.append(rec)
    return records


class JdihnFeedConnector(Connector):
    kind = "jdihn"

    def fetch(self, categories=None):
        url = self.config.get("feed_url") or self.base_url
        if not url:
            raise ConnectorError("feed_url belum diisi pada konfigurasi sumber")
        resp = self.get(url)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ConnectorError(f"Respons {url} bukan JSON") from exc
        yield from parse_feed(payload)
