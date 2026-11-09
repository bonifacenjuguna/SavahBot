"""SavahBot intelligence: knowledge packs and detectors that run on this machine, with no AI service.

    knowledge/   data, one JSON file per category, loaded by PackRegistry
    detectors/   algorithms, one file per detector
    service.py   Intelligence: runs detectors, learns, logs shadow findings
    store.py     the database side
"""
from .service import Applied, Intelligence, Outcome  # noqa: F401
