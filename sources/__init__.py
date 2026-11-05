"""Source registry. To add another AUTHORIZED source (e.g. a licensed provider): create sources/<name>.py with a Source
subclass (see base.py) and register it here. Nothing else changes: the engine validates every candidate again."""
from .internet_archive import InternetArchive
from .wikimedia import WikimediaCommons

REGISTRY = {cls.name: cls for cls in (InternetArchive, WikimediaCommons)}


def get_sources(names):
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise SystemExit("unknown source(s): %s (available: %s)" % (", ".join(unknown), ", ".join(sorted(REGISTRY))))
    return [REGISTRY[n]() for n in names]
