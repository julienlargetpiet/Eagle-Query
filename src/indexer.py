import json
import os
import sqlite3
import tempfile

from collections import defaultdict
from contextlib import closing
from pathlib import Path

from database import SCHEMA, discover_sources, opened_source
from tokenizer import tokenize, extract_text


def index_source(index, path, term_cache):

    stat = path.stat()
    key = str(path)

    previous = index.execute(
        "SELECT id, size_bytes, mtime_ns FROM sources WHERE path = ?", (key,)
    ).fetchone()
    
    if previous and previous[1:] == (stat.st_size, stat.st_mtime_ns):
        print(f"[SKIP] {path.name} (unchanged)", flush=True)
        return

    print(f"[INDEX] {path.name}", flush=True)
    with opened_source(path) as source_db:
        
        with index:

            if previous:

                source_id = previous[0]

                index.execute("DELETE FROM documents WHERE source_id = ?", (source_id,))
                index.execute(
                    "UPDATE sources SET size_bytes=?, mtime_ns=? WHERE id=?",
                    (stat.st_size, stat.st_mtime_ns, source_id),
                )

            else:

                source_id = index.execute(
                    "INSERT INTO sources(path, size_bytes, mtime_ns) VALUES (?, ?, ?)",
                    (key, stat.st_size, stat.st_mtime_ns),
                ).lastrowid

            count = 0

            for page_id, url, content, content_type in source_db.execute(
                "SELECT id, url, content, content_type FROM pages"
            ):


                positions = defaultdict(list)
                document_length = 0

                for position, term in enumerate(tokenize(extract_text(content, content_type))):
                    positions[term].append(position)
                    document_length += 1
    

                document_id = index.execute(
                    """
                    INSERT INTO documents(source_id, page_id, url, length)
                    VALUES (?, ?, ?, ?)
                    """,
                    (source_id, page_id, url, document_length),
                ).lastrowid
   
                postings = []

                for term, term_position in positions.items():

                    term_id = term_cache.get(term)

                    if term_id is None:

                        index.execute(
                            "INSERT OR IGNORE INTO terms(term) VALUES (?)",
                            (term,)
                        )

                        term_id = index.execute(
                            "SELECT id FROM terms WHERE term = ?",
                            (term,)
                        ).fetchone()[0]

                        term_cache[term] = term_id

                    postings.append((term_id, 
                                     document_id, 
                                     len(term_position), 
                                     json.dumps(term_position))
                                   )

                index.executemany(
                    """
                    INSERT INTO postings(term_id, document_id, frequency, positions)
                    VALUES (?, ?, ?, ?)
                    """,
                    postings
                )

                count += 1

    print(f"[OK] {count} pages indexed from {path.name}", flush=True)


def index_command(args):

    sources = discover_sources(args.source)

    target = Path(args.index).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if args.rebuild:

        with tempfile.NamedTemporaryFile(prefix=".new-search-", 
                                         suffix=".db",
                                         dir=target.parent, 
                                         delete=False) as tmp:
            working = Path(tmp.name)

    else:
        working = target


    try:
        with closing(sqlite3.connect(working)) as index:

            index.execute("PRAGMA foreign_keys = ON")

            index.executescript(SCHEMA)

            term_cache = {}

            for path in sources:
                if path == target:
                    raise ValueError("Source database must not be the search index")

                index_source(index, path, term_cache)

        if args.rebuild:

            os.replace(working, target)

        print(f"Index ready: {target}")

    except Exception:

        if args.rebuild:
            working.unlink(missing_ok=True)
        raise



