"""CLI entrypoint for knowledge corpus ingestion (D2, L1).

Usage:
    python -m app.ingest [--reindex-changed] [--force]
"""

from src.rag.ingestion import main

if __name__ == "__main__":
    main()
