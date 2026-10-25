"""Finds a PostgreSQL server for local development.
   1) DATABASE_URL if you set it (Render does)   2) a server already running on localhost
   3) otherwise starts an embedded PostgreSQL (pip install pgserver) inside ./.pgdata -- no install needed."""
import os
import psycopg2

DEFAULT_URL = "postgresql://fest:fest@localhost:5432/festverse"
_server = None   # keep a reference so the embedded server stays alive

def resolve_url():
    global _server
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    try:
        psycopg2.connect(DEFAULT_URL, connect_timeout=2).close()
        return DEFAULT_URL
    except psycopg2.Error:
        pass
    try:
        import pgserver, pathlib
    except ImportError:
        raise RuntimeError(
            "No PostgreSQL found. Easiest fix:  pip install -r requirements-local.txt  (starts an embedded database automatically)\n"
            "Or start your own PostgreSQL and set DATABASE_URL (see README).")
    here = pathlib.Path(__file__).resolve().parent
    _server = pgserver.get_server(here / ".pgdata")
    print("[The Anthem Board] Using embedded PostgreSQL stored in .pgdata/")
    return _server.get_uri()
