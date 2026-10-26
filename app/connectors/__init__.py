from .html_search import BpkConnector, HtmlSearchConnector, KemnakerConnector
from .jdihn import JdihnFeedConnector
from .seed import SeedConnector

CONNECTORS = {
    c.kind: c for c in (SeedConnector, BpkConnector, KemnakerConnector, HtmlSearchConnector, JdihnFeedConnector)
}


def get_connector(kind, base_url=None, config=None):
    try:
        cls = CONNECTORS[kind]
    except KeyError:
        raise ValueError(f"Jenis konektor tidak dikenal: {kind}")
    return cls(base_url=base_url, config=config)
