#!/usr/bin/env python3

import json
import math
import re
import sqlite3

from pathlib import Path
from urllib.parse import urlsplit

from database import opened_source
from tokenizer import tokenize
from contacts import get_company, extract_emails, export_contacts


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

#def tokenize(text):
#    return [word 
#            for word in re.findall(r"[^\W_]+", text.casefold()) 
#            if len(word) <= 64
#    ]



def phrase_matches(phrase, positions):

    first_positions = positions.get(phrase[0], set())

    return any(
        all(
            start + offset in positions.get(term, set())
            for offset, term in enumerate(phrase)
        )
        for start in first_positions
    )
 
def search_command(args):

    target = Path(args.index).expanduser().resolve()

    if not target.is_file():
        raise ValueError(f"Index not found: {target}. Run 'index' first.")

    #words = list(dict.fromkeys(tokenize(args.query)))

    #if not words:
    #    print("No searchable words in query.")
    #    return

    phrases = [
        list(tokenize(phrase)) 
        for phrase in re.findall('"([^"]+)"', args.query)
    ]

    phrases = [phrase for phrase in phrases if phrase]

    remaining_query = re.sub('"([^"]+)"', ' ', args.query)
    single_words = list(dict.fromkeys(tokenize(remaining_query)))

    words = list(dict.fromkeys(
        single_words +
        [word for phrase in phrases for word in phrase]
    ))
    
    has_phrases = bool(phrases)

    placeholders = ", ".join("?" for _ in words)

    if has_phrases:

        sql = f"""
              SELECT
                  d.id,
                  d.url,
                  s.path,
                  d.page_id,
                  d.length,
                  t.id,
                  p.frequency,
                  t.term,
                  p.positions
              FROM terms AS t
              JOIN postings AS p ON p.term_id = t.id
              JOIN documents AS d ON d.id = p.document_id
              JOIN sources AS s ON s.id = d.source_id
              WHERE t.term IN ({placeholders})
          """

    else:

        if args.and_behavior:

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

        else:

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

        if has_phrases:
            parameters = words
        elif args.and_behavior:
            parameters = (*words, *words, len(words))
        else:
            parameters = words
        
        rows = index.execute(sql, parameters).fetchall()

        documents = {}
        
        for row in rows:
        
            if has_phrases:
                (
                    document_id, url, source_path, page_id,
                    length, term_id, frequency, term, raw_positions
                ) = row
            else:
                (
                    document_id, url, source_path, page_id,
                    length, term_id, frequency
                ) = row
        
            if document_id not in documents:
                documents[document_id] = {
                    "url": url,
                    "source": source_path,
                    "page_id": page_id,
                    "score": 0.0
                }
        
                if has_phrases:
                    documents[document_id]["positions"] = {}
        
            documents[document_id]["score"] += bm25(
                tf=frequency,
                df=document_frequencies[term_id],
                length=length,
                avgdl=avgdl,
                N=N
            )
        
            if has_phrases:
                documents[document_id]["positions"][term] = set(
                    json.loads(raw_positions)
                )


    if has_phrases:
    
        filtered_documents = {}
    
        for document_id, doc in documents.items():
    
            positions = doc["positions"]
    
            matches = [
                phrase_matches(phrase, positions)
                for phrase in phrases
            ]
    
            matches.extend(
                term in positions
                for term in single_words
            )
    
            if (
                (args.and_behavior and all(matches))
                or (not args.and_behavior and any(matches))
            ):
                filtered_documents[document_id] = doc
                #print(f"ok: {doc}")
    
        documents = filtered_documents

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

    export_contacts(contacts, args.output)



