import argparse
import sqlite3

from indexer import index_command
from search import search_command


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

    query.add_argument(
        "--and-behavior",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use AND matching (default) or OR matching"
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



