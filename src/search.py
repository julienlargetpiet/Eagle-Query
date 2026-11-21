#!/usr/bin/env python3

import argparse
from collections import Counter
from contextlib import contextmanager, closing
import gzip
from html.parser import HTMLParser
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import math

import csv
from html import unescape
from urllib.parse import urlsplit

import tldextract


extract_domain = tldextract.TLDExtract(suffix_list_urls=())


def get_company(url):
    hostname = urlsplit(url).hostname

    if not hostname:
        return ""

    return extract_domain(hostname).domain


EMAIL_RE = re.compile(
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
    re.IGNORECASE
)


def extract_emails(content):
    return set(EMAIL_RE.findall(unescape(content)))


def bm25(tf, 
         df, 
         length, 
         avgdl, 
         N, 
         k1=1.2, 
         b=0.75
):
    
    # rare words in all documents have log more importance
    idf = math.log(1 + (N - df + 0.5) / (df + 0.5)) 

    # frequents words in a document have more importance (until a k1 saturating point)
    numerator = tf * (k1 + 1)

    # small document gives more importance
    # we don't penalize much the log documents tho with 
    # b being inferior to 1
    denominator = tf + k1 * (
        1 - b + b * length / avgdl # same as 1 + b * (length / avgdl - 1)
    )

    # IDF: How rare or common is this word across 
    # the entire document corpus? 
    #
    # Numerator / denominator: How strongly is this word represented in this particular document? 

    return idf * numerator / denominator

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
    PRIMARY KEY(term_id, document_id)
);

CREATE INDEX IF NOT EXISTS postings_document ON postings(document_id);

"""
 
class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract_text(content, content_type):
    if content_type in ("text/html", "text/xml"):
        parser = VisibleText()
        parser.feed(content)
        return " ".join(parser.parts)

    return content  


def tokenize(text):
    return [word 
            for word in re.findall(r"[^\W_]+", text.casefold()) 
            if len(word) <= 64
    ]


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


def index_source(index, path):

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


                frequencies = Counter(tokenize(extract_text(content, content_type)))
                
                document_length = sum(frequencies.values())
                
                document_id = index.execute(
                    """
                    INSERT INTO documents(source_id, page_id, url, length)
                    VALUES (?, ?, ?, ?)
                    """,
                    (source_id, page_id, url, document_length),
                ).lastrowid



                for term, frequency in frequencies.items():

                    index.execute("INSERT OR IGNORE INTO terms(term) VALUES (?)", (term,))

                    term_id = index.execute(
                        "SELECT id FROM terms WHERE term = ?", (term,)
                    ).fetchone()[0]

                    index.execute(
                        "INSERT INTO postings(term_id, document_id, frequency) VALUES (?, ?, ?)",
                        (term_id, document_id, frequency),
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

            for path in sources:
                if path == target:
                    raise ValueError("Source database must not be the search index")

                index_source(index, path)

        if args.rebuild:

            os.replace(working, target)

        print(f"Index ready: {target}")

    except Exception:

        if args.rebuild:
            working.unlink(missing_ok=True)
        raise

 
def search_command(args):

    target = Path(args.index).expanduser().resolve()

    if not target.is_file():
        raise ValueError(f"Index not found: {target}. Run 'index' first.")

    words = list(dict.fromkeys(tokenize(args.query)))

    if not words:
        print("No searchable words in query.")
        return

    placeholders = ", ".join("?" for _ in words)

    # AND search; score is simply the sum of word frequencies, not BM25.


    sql = f"""
        SELECT
            d.id,
            d.url,
            s.path,
            d.page_id,
            d.length,
            t.id,
            p.frequency
        FROM terms AS t
        JOIN postings AS p ON p.term_id = t.id
        JOIN documents AS d ON d.id = p.document_id
        JOIN sources AS s ON s.id = d.source_id
        WHERE t.term IN ({placeholders})
        AND d.id IN (
            SELECT p2.document_id
            FROM postings AS p2
            JOIN terms AS t2 ON t2.id = p2.term_id
            WHERE t2.term IN ({placeholders})
            GROUP BY p2.document_id
            HAVING COUNT(*) = ?
        )
    """


    with sqlite3.connect(target.as_uri() + "?mode=ro", 
                         uri=True) as index:

        N, avgdl = index.execute("""
            SELECT COUNT(*), AVG(length)
            FROM documents
        """).fetchone()
        
        if N == 0 or avgdl == 0:
            print("Index contains no searchable documents.")
            return

        df_rows = index.execute(
            f"""
            SELECT t.id, COUNT(*)
            FROM terms AS t
            JOIN postings AS p ON p.term_id = t.id
            WHERE t.term IN ({placeholders})
            GROUP BY t.id
            """,
            words
        ).fetchall()
        
        document_frequencies = dict(df_rows)

        rows = index.execute(
            sql,
            (*words, *words, len(words))
        ).fetchall()

        documents = {}
        
        for document_id, url, source_path, page_id, length, term_id, frequency in rows:
        
            if document_id not in documents:
                documents[document_id] = {
                    "url": url,
                    "source": source_path,
                    "page_id": page_id,
                    "score": 0.0
                }
        
            documents[document_id]["score"] += bm25(
                tf=frequency,
                df=document_frequencies[term_id],
                length=length,
                avgdl=avgdl,
                N=N
            )

    # we sort here to avoid havin unnecessary iterations 
    # for the pages database loop (SQL queries, decompression...)

    results = sorted(
        documents.values(),
        key=lambda doc: doc["score"],
        reverse=True
    )[:args.limit]


    # we group to avoid decompressing the same source more than one time
    grouped = {}

    for doc in results:
        grouped.setdefault(doc["source"], []).append(doc)

    contacts = []

    for source_path, ranked_docs in grouped.items():

        with opened_source(Path(source_path)) as source_db:

            for doc in ranked_docs:

                row = source_db.execute(
                    "SELECT content FROM pages WHERE id = ?",
                    (doc["page_id"],)
                ).fetchone()

                if row is None:
                    print(
                        f"[WARN] Missing page {doc['page_id']} "
                        f"in {source_path}"
                    )
                    continue

                content = row[0]

                emails = extract_emails(content)

                url = doc["url"]
                parsed = urlsplit(url)

                company = get_company(url)
                website = f"{parsed.scheme}://{parsed.netloc}"

                for email in emails:

                    contacts.append((
                        doc["score"],
                        company,
                        email,
                        url,
                        website
                    ))

    contacts.sort(
        key=lambda contact: contact[0],
        reverse=True
    )

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    seen = set()

    with output.open("w", newline="", encoding="utf-8") as file:

        writer = csv.writer(file)

        writer.writerow([
            "company",
            "email",
            "source_url",
            "sector",
            "city",
            "website",
            "notes"
        ])

        for rank, company, email, source_url, website in contacts:

            key = (company, email.casefold())

            if key in seen:
                continue

            seen.add(key)

            writer.writerow([
                company,
                email,
                source_url,
                "",
                "",
                website,
                ""
            ])

    print(f"[OK] {len(seen)} contacts exported to {output}")


def main():

    parser = argparse.ArgumentParser(description="Persistent Python inverted-index search")

    sub = parser.add_subparsers(
        dest="command", 
        required=True
    )

    build = sub.add_parser(
        "index", 
        help="Build or incrementally update an index"
    )

    build.add_argument(
        "--source", 
        required=True, 
        help=".db/.db.gz file, or directory of archives"
    )

    build.add_argument(
        "--index", 
        default="database/search_index.db", 
        help="Where to store the inverted index"
    )

    build.add_argument(
        "--rebuild", 
        action="store_true", 
        help="Build a brand-new index"
    )

    build.set_defaults(run=index_command)

    query = sub.add_parser(
        "search", 
        help="Search an existing index without rebuilding"
    )

    query.add_argument(
        "--index", 
        default="database/search_index.db"
    )

    query.add_argument(
        "--query", 
        required=True
    )

    query.add_argument(
        "--limit", 
        type=int, 
        default=10
    )

    query.add_argument(
        "--output",
        default="contacts.csv",
        help="Destination CSV file"
    )

    query.set_defaults(run=search_command)

    args = parser.parse_args()

    if args.command == "search" and args.limit < 1:

        parser.error("--limit must be positive")

    try:

        args.run(args)

    except (ValueError, sqlite3.Error, OSError) as exc:

        parser.exit(1, f"Error: {exc}\n")

if __name__ == "__main__":
    main()


