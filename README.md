
<p align="center">

<img src="logo/logo.png" width="220">

</p>

**Eagle-Query** is an open-source Python search engine, part of the **Eagle** software constellation.

It builds a persistent inverted index from SQLite web archives produced by Eagle-Search, ranks documents using BM25, supports exact phrase searches, and extracts email contacts into CSV files.

## Features

- Persistent `SQLite` inverted index with term frequencies and positions

- BM25 document ranking

- AND / OR search behavior

- Exact phrase matching using quotation marks

- Email extraction, deduplication, and CSV export

## Usage


### Build the index

```bash
python3 src/main.py index --source ~/archives --index database/search_index.db
```

Force a complete rebuild:

```bash
python3 src/main.py index --source ~/archives --rebuild
```

### Search

```bash
python3 src/main.py search \
    --query '"business developer" france' \
    --no-and-behavior \
    --limit 100 \
    --output contacts.csv
```

## Command arguments

### `index`

| Argument | Required | Default | Description |
|---|---|---|---|
| `--source` | Yes | — | SQLite archive or directory |
| `--index` | No | `database/search_index.db` | Index database path |
| `--rebuild` | No | `False` | Rebuild the entire index |

### `search`

| Argument | Required | Default | Description |
|---|---|---|---|
| `--index` | No | `database/search_index.db` | Index database path |
| `--query` | Yes | — | Search terms and quoted phrases |
| `--limit` | No | `10` | Maximum number of pages to examine |
| `--output` | No | `contacts.csv` | Output CSV path |
| `--and-behavior` | No | `True` | Require all search conditions |
| `--no-and-behavior` | No | `False` | Match any search condition |

## Search syntax

| Query | Behavior |
|---|---|
| `'business developer'` | Both words required by default |
| `'"business developer"'` | Exact consecutive phrase |
| `'"business developer" france'` | Phrase AND `france` by default |
| `'business developer' --no-and-behavior` | Match either word |

Quoted phrases are matched using token positions stored in the index.

## Output

Contacts are exported as CSV with the following columns:

`company,email,source_url,sector,city,website,notes`

The `sector`, `city`, and `notes` columns are left empty.

## Architecture

```text
src/
|-- main.py       # Command-line interface
|-- database.py   # SQLite schema and archive access
|-- tokenizer.py  # Text extraction and tokenization
|-- indexer.py    # Inverted index construction
|-- search.py     # Search queries and BM25 ranking
|-- contacts.py   # Contact extraction and CSV export
```



