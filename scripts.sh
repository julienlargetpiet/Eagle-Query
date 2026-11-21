python3 src/search.py index --source ~/archives --index database/search_index.db --rebuild

python3 src/search.py search --index database/search_index.db --query "the" --limit 100 --output contacts.csv
