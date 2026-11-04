"""Isolated test database for PowerWize tests.

`src/db/core.py` reads DATABASE_URL at MODULE IMPORT time, and importing
`app` runs init_db(). So the environment has to be redirected *before* any
`db` or `app` import happens — importing first and reconfiguring afterwards
would run the schema against the developer's real database.

Usage, as the very first thing a test does:

    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
    from _testdb import use_test_db
    use_test_db()                 # must precede `from app import app`
    from app import app
"""
import os
import sys
from urllib.parse import (parse_qs, parse_qsl, urlencode,
                          urlparse, urlunparse)

TEST_DB_NAME = "powerwize_test"


def _base_url():
    from dotenv import load_dotenv
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("DATABASE_URL is not set; cannot derive a test database URL.")
    return url


def test_db_url():
    """The real URL with its database name swapped. Credentials are reused,
    never guessed or printed.

    Validation runs on the FULLY RESOLVED parameters, via the same resolver
    the guard uses. Reading urlparse().hostname alone missed a query-string
    override: "postgresql://u@localhost/db?host=remote.invalid" presented as
    local while libpq connected to remote.invalid.
    """
    raw = _base_url()
    host, _port, _db = _connection_target([raw], {})
    if host != "local":
        sys.exit(f"Refusing to build a test database against non-local host "
                 f"'{host or '<unresolved>'}'. Tests must not touch a remote "
                 f"database.")
    p = urlparse(raw)
    # Any host/dbname override in the query string is dropped, not carried
    # through: it would silently redirect everything built from this URL.
    kept = [(k, v) for k, v in parse_qsl(p.query)
            if k not in ("host", "hostaddr", "port", "dbname")]
    return urlunparse(p._replace(path="/" + TEST_DB_NAME,
                                 query=urlencode(kept)))


def ensure_test_db(recreate=False):
    """Create the test database if absent. `recreate` drops it first, which
    is how a fresh-install check gets a genuinely empty schema."""
    import psycopg2
    # Derived from test_db_url(), which has already refused a non-local host.
    # Re-reading the raw DATABASE_URL here would reintroduce the hole this
    # ordering was changed to close.
    p = urlparse(test_db_url())
    admin = urlunparse(p._replace(path="/postgres"))
    conn = psycopg2.connect(admin)
    conn.autocommit = True
    cur = conn.cursor()
    if recreate:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()", (TEST_DB_NAME,))
        cur.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,))
    if not cur.fetchone():
        cur.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    cur.close()
    conn.close()


LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "")


def _norm_host(host):
    """Collapse the equivalent spellings of 'this machine'."""
    return "local" if (host or "").lower() in LOCAL_HOSTS else (host or "").lower()


def _connection_target(args, kwargs):
    """(host, port, dbname) that a psycopg2.connect() call would actually open.

    psycopg2 accepts a DSN positionally, as `dsn=`, or as discrete keywords
    (`dbname=` / the `database=` alias), so all four shapes are read here. An
    unrecognised shape returns all-None and is refused rather than waved
    through.

    The host matters as much as the name: a REMOTE database that happens to be
    called powerwize_test is not isolation. An earlier version of this guard
    compared the name alone and let exactly that through.
    """
    host = port = dbname = None
    dsn = kwargs.get("dsn") or (args[0] if args else None)
    if isinstance(dsn, str):
        if "://" in dsn:
            u = urlparse(dsn)
            host, port, dbname = u.hostname, u.port, u.path.lstrip("/") or None
            # libpq honours connection parameters in the URI QUERY STRING, and
            # they win over the authority. Ignoring them classified
            # "postgresql://u@localhost/db?host=remote.invalid" as local while
            # the connection went to remote.invalid.
            q = parse_qs(u.query)
            if q.get("host"):
                host = q["host"][-1]
            if q.get("hostaddr"):
                host = q["hostaddr"][-1]
            if q.get("port"):
                port = q["port"][-1]
            if q.get("dbname"):
                dbname = q["dbname"][-1]
        else:
            for part in dsn.split():               # key=value DSN form
                k, _, v = part.partition("=")
                k, v = k.strip(), v.strip()
                if k in ("dbname", "database"):
                    dbname = v
                elif k == "host":
                    host = v
                elif k == "port":
                    port = v
    elif dsn is not None:
        return (None, None, None)                  # unrecognised shape

    # psycopg2 lets discrete keywords OVERRIDE the DSN, so they are applied
    # last. Reading them only when no DSN was given missed
    # connect(local_dsn, host="elsewhere") entirely — the DSN looked local and
    # the connection went somewhere else.
    if kwargs.get("dbname") or kwargs.get("database"):
        dbname = kwargs.get("dbname") or kwargs.get("database")
    if kwargs.get("host") is not None:
        host = kwargs["host"]
    if kwargs.get("port") is not None:
        port = kwargs["port"]

    if dbname is None and host is None and port is None:
        return (None, None, None)
    return (_norm_host(host), int(port) if port else 5432, dbname)


def _target_dbname(args, kwargs):
    """Just the database name. Kept because it reads well in assertions."""
    return _connection_target(args, kwargs)[2]


_guard_installed = False
_guard_expects = None


def _install_connection_guard():
    """Refuse any non-test connection at the psycopg2 boundary.

    assert_isolated() was a voluntary, late check: every test called it AFTER
    `from app import app`, and importing app runs init_db() — so the first
    schema mutation had already landed before isolation was ever verified. If
    DATABASE_URL had been wrong, the damage was done and the check only
    reported it afterwards.

    A guard on connect() cannot be reached too late. Nothing can connect, read
    or mutate without passing through it, whatever order a test imports in.
    """
    global _guard_installed, _guard_expects
    if _guard_installed:
        return
    import psycopg2
    real_connect = psycopg2.connect
    _guard_expects = _connection_target([test_db_url()], {})

    def guarded_connect(*args, **kwargs):
        target = _connection_target(args, kwargs)
        if target != _guard_expects:
            shown = (f"{target[0]}:{target[1]}/{target[2]}"
                     if target[2] else "<unrecognised DSN>")
            want = f"{_guard_expects[0]}:{_guard_expects[1]}/{_guard_expects[2]}"
            sys.exit(f"ABORT: a test tried to open '{shown}', not '{want}'. "
                     f"No connection was made and no statement was sent.")
        return real_connect(*args, **kwargs)

    guarded_connect.__wrapped__ = real_connect
    psycopg2.connect = guarded_connect
    _guard_installed = True


def use_test_db(recreate=False):
    """Point this process at the test database. Call before importing db/app.

    Installs the connect() guard before returning, so isolation is enforced
    from this line onward rather than asserted later.
    """
    if "db" in sys.modules or "app" in sys.modules:
        sys.exit("use_test_db() called after db/app was already imported — "
                 "DATABASE_URL is read at import time, so isolation is "
                 "already lost. Move this call to the top of the file.")
    # FIRST, before anything opens a socket: test_db_url() refuses a
    # non-local host and exits. ensure_test_db() connects to the `postgres`
    # maintenance database of whatever DATABASE_URL names, so calling it
    # first let a remote URL reach connect() before any check had run.
    url = test_db_url()
    os.environ["DATABASE_URL"] = url
    # Now safe to create the database. Still unguarded, deliberately and
    # only here: creating it requires the `postgres` maintenance database,
    # which the guard forbids by design.
    ensure_test_db(recreate=recreate)
    _install_connection_guard()
    return url


def assert_isolated():
    """Confirm the configured URL is the test DB, and the guard is armed.

    Kept as a readable one-line statement in each test, but it is no longer
    what provides the isolation — _install_connection_guard() is.
    """
    # Guard first: reading db.core raises ModuleNotFoundError in a bare
    # process, which would mask "the guard is not armed" with an import error.
    if not _guard_installed:
        sys.exit("ABORT: the connection guard is not installed, so nothing is "
                 "stopping a connection to the real database.")
    from db.core import DATABASE_URL
    name = urlparse(DATABASE_URL).path.lstrip("/")
    if name != TEST_DB_NAME:
        sys.exit(f"ABORT: connected to '{name}', expected '{TEST_DB_NAME}'.")
    return name
