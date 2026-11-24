import gzip
import shutil
import sqlite3
import tempfile

from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    size_bytes INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    page_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    length INTEGER NOT NULL,
    UNIQUE(source_id, page_id)
);

CREATE TABLE IF NOT EXISTS terms (
    id INTEGER PRIMARY KEY,
    term TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS postings (
    term_id INTEGER NOT NULL REFERENCES terms(id),
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    frequency INTEGER NOT NULL,
    positions TEXT NOT NULL,
    PRIMARY KEY(term_id, document_id)
);

CREATE INDEX IF NOT EXISTS postings_document ON postings(document_id);

"""


def discover_sources(source):
    source = Path(source).expanduser().resolve()


    if source.is_file() and source.name.endswith((".db", ".db.gz")):
        return [source]

    if source.is_dir():
        found = sorted(
            p for p in source.iterdir()
            if p.is_file() and p.name.endswith((".db", ".db.gz"))
        )
    
        if found:
            return found

    raise ValueError(f"No .db or .db.gz sources found at {source}")



@contextmanager
def opened_source(path):

    if not path.name.endswith(".gz"):

        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)

        try:
            yield conn
        finally:
            conn.close()

        return

    with tempfile.TemporaryDirectory() as temporary:

        database_path = Path(temporary) / "pages.db"

        with gzip.open(path, "rb") as source:
            with open(database_path, "wb") as destination:
                shutil.copyfileobj(source, destination)

        conn = sqlite3.connect(
            database_path.as_uri() + "?mode=ro",
            uri=True
        )

        try:
            yield conn
        finally:
            conn.close()




