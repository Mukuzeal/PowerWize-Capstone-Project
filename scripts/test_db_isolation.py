"""Regression: test isolation is enforced BEFORE any connection or mutation.

Every test used to call assert_isolated() after `from app import app`, and
importing app runs init_db(). Isolation was therefore only *reported* after
the first schema mutation — if DATABASE_URL had been wrong, the real database
was already altered.

This checks the structural guard instead: psycopg2.connect() itself refuses
anything that is not the test database, so no ordering mistake can reach the
real one. The refusal is verified to happen before `real_connect` is called —
a guard that connects first and complains second would be worthless.

    cd src; ..\\venv\\Scripts\\python.exe ..\\scripts\\test_db_isolation.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import _testdb                                        # noqa: E402
from _testdb import (TEST_DB_NAME, _target_dbname,     # noqa: E402
                     _connection_target)

results = []


def check(name, passed, detail=""):
    results.append((name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


print("\n1. Every DSN shape psycopg2 accepts is read correctly")
cases = [
    ("URI, positional", (["postgresql://u:p@localhost:5432/powerwize"], {}), "powerwize"),
    ("URI, dsn= keyword", ([], {"dsn": "postgresql://u@localhost/powerwize"}), "powerwize"),
    ("key=value DSN", (["host=localhost dbname=powerwize user=u"], {}), "powerwize"),
    ("dbname= keyword", ([], {"dbname": "powerwize", "host": "localhost"}), "powerwize"),
    ("database= alias", ([], {"database": "powerwize"}), "powerwize"),
    ("test URI", (["postgresql://u@localhost/" + TEST_DB_NAME], {}), TEST_DB_NAME),
]
for label, (a, kw), want in cases:
    got = _target_dbname(a, kw)
    check(f"{label} -> {want}", got == want, f"got {got!r}")

# A shape the parser does not understand must not be mistaken for the test DB.
check("unrecognised DSN yields None, not a false match",
      _target_dbname([object()], {}) is None)
check("empty call yields None", _target_dbname([], {}) is None)


print("\n2. The guard refuses a non-test database without connecting")
import psycopg2                                        # noqa: E402

real_calls = []
_original = psycopg2.connect


def _spy(*a, **kw):
    """Stands in for the real connect so a refusal cannot be confused with a
    connection that merely failed. If the guard lets a call through, this
    records it — nothing ever reaches a real server."""
    real_calls.append((a, kw))
    return "FAKE-CONNECTION"


psycopg2.connect = _spy
_testdb._guard_installed = False
_testdb._install_connection_guard()
guarded = psycopg2.connect
check("guard wrapped connect", guarded is not _spy)

refused = [
    ("the developer's real database", ["postgresql://u@localhost/powerwize"], {}),
    ("the postgres maintenance database", ["postgresql://u@localhost/postgres"], {}),
    ("a remote host, test-looking name", ["postgresql://u@db.example.com/" + TEST_DB_NAME], {}),
    ("discrete keywords", [], {"dbname": "powerwize"}),
    ("key=value DSN", ["host=localhost dbname=powerwize"], {}),
    ("an unparseable DSN", [12345], {}),
]
for label, a, kw in refused:
    before = len(real_calls)
    try:
        guarded(*a, **kw)
        check(f"refuses {label}", False, "the call was ALLOWED")
    except SystemExit as e:
        check(f"refuses {label}", True, str(e)[:58])
        # The whole point: refusal precedes the connection attempt.
        if len(real_calls) != before:
            check(f"  …and did not connect first ({label})", False,
                  "real connect was called before refusing")
    except Exception as e:                                   # noqa: BLE001
        check(f"refuses {label}", False, f"raised {type(e).__name__}: {e}")

check("no connection was attempted for any refused DSN", not real_calls,
      f"{len(real_calls)} leaked through")

# The name alone is not isolation: the guard must compare the host too.
check("a remote host is distinguished from local",
      _connection_target(["postgresql://u@db.example.com/" + TEST_DB_NAME], {})[0]
      != _connection_target(["postgresql://u@localhost/" + TEST_DB_NAME], {})[0])
check("localhost and 127.0.0.1 are treated as the same machine",
      _connection_target(["postgresql://u@localhost/x"], {})[0]
      == _connection_target(["postgresql://u@127.0.0.1/x"], {})[0])
check("an omitted port means 5432, not None",
      _connection_target(["postgresql://u@localhost/x"], {})[1] == 5432)


print("\n2b. Discrete keywords override a DSN, and the guard must see it")
# psycopg2 applies keyword arguments ON TOP of the DSN. A local-looking DSN
# with a host= override connected somewhere else entirely while the guard,
# which only read kwargs when no DSN was present, saw "local".
over = [
    ("host= overriding a local DSN",
     ["postgresql://u@localhost/" + TEST_DB_NAME], {"host": "db.example.com"}),
    ("dbname= overriding a local DSN",
     ["postgresql://u@localhost/" + TEST_DB_NAME], {"dbname": "powerwize"}),
    ("port= overriding a local DSN",
     ["postgresql://u@localhost/" + TEST_DB_NAME], {"port": 6543}),
]
for label, a, kw in over:
    before = len(real_calls)
    try:
        guarded(*a, **kw)
        check(f"refuses {label}", False, "the call was ALLOWED")
    except SystemExit as e:
        check(f"refuses {label}", True, str(e)[:58])
        if len(real_calls) != before:
            check(f"  ...and did not connect first ({label})", False,
                  "real connect ran before refusing")
check("no keyword override leaked through", not real_calls,
      f"{len(real_calls)} leaked")


print("\n2c. URI query parameters override the authority, and libpq obeys them")
# "postgresql://u@localhost/db?host=remote.invalid" presented as local while
# the connection went to remote.invalid. Reading only urlparse().hostname
# classified every one of these as local.
q_cases = [
    ("?host=", f"postgresql://u@localhost/{TEST_DB_NAME}?host=remote.invalid"),
    ("?hostaddr=", f"postgresql://u@localhost/{TEST_DB_NAME}?hostaddr=10.0.0.5"),
    ("?port=", f"postgresql://u@localhost/{TEST_DB_NAME}?port=6543"),
    ("?dbname=", f"postgresql://u@localhost/{TEST_DB_NAME}?dbname=powerwize"),
]
for label, dsn in q_cases:
    before = len(real_calls)
    try:
        guarded(dsn)
        check(f"refuses a {label} override", False, "the call was ALLOWED")
    except SystemExit as e:
        check(f"refuses a {label} override", True, str(e)[:58])
        if len(real_calls) != before:
            check(f"  ...and did not connect first ({label})", False,
                  "real connect ran before refusing")
check("an unrelated query parameter is still allowed",
      _connection_target([f"postgresql://u@localhost/{TEST_DB_NAME}"
                          "?sslmode=disable"], {})
      == ("local", 5432, TEST_DB_NAME))
check("no query override leaked through", not real_calls,
      f"{len(real_calls)} leaked")


print("\n3. The test database itself is allowed through")
real_calls.clear()
conn = guarded(f"postgresql://u@localhost/{TEST_DB_NAME}")
check("test database passes the guard", conn == "FAKE-CONNECTION")
check("and reaches the underlying connect", len(real_calls) == 1)
psycopg2.connect = _original


print("\n4. assert_isolated() now fails loudly if the guard is missing")
_testdb._guard_installed = False
try:
    _testdb.assert_isolated()
    check("assert_isolated refuses an unguarded process", False, "it returned")
except SystemExit as e:
    check("assert_isolated refuses an unguarded process",
          "guard is not installed" in str(e), str(e)[:58])
except Exception as e:                                       # noqa: BLE001
    # db.core is not imported here, so an ImportError is the wrong failure:
    # the guard check must come first, before touching the db package.
    check("assert_isolated refuses an unguarded process", False,
          f"raised {type(e).__name__} instead of exiting")
_testdb._guard_installed = True


print("\n4b. The URL is validated BEFORE anything connects")
# ensure_test_db() opens the `postgres` maintenance database of whatever
# DATABASE_URL names. Calling it before the host check let a remote URL reach
# connect() first. Prove the ordering by spying on connect with a remote URL.
_saved_url = os.environ.get("DATABASE_URL")
_saved_guard = _testdb._guard_installed
attempted = []
_testdb._guard_installed = False
psycopg2.connect = lambda *a, **kw: (attempted.append((a, kw)), "X")[1]
os.environ["DATABASE_URL"] = "postgresql://u:p@db.example.com:5432/powerwize"
try:
    _testdb.use_test_db()
    check("a remote DATABASE_URL is refused", False, "use_test_db returned")
except SystemExit as e:
    check("a remote DATABASE_URL is refused", "non-local host" in str(e),
          str(e)[:58])
check("and NOTHING connected before the refusal", not attempted,
      f"{len(attempted)} connection(s) attempted")

# The same ordering must hold for a query-string override, which is how a URL
# that LOOKS local reaches a remote server.
attempted.clear()
_testdb._guard_installed = False
os.environ["DATABASE_URL"] = (
    "postgresql://u:p@localhost:5432/powerwize?host=remote.invalid")
try:
    _testdb.use_test_db()
    check("a ?host= override is refused too", False, "use_test_db returned")
except SystemExit as e:
    check("a ?host= override is refused too", "non-local host" in str(e),
          str(e)[:58])
check("and nothing connected for it either", not attempted,
      f"{len(attempted)} attempted")

# A harmless parameter must survive into the derived URL, while a redirecting
# one must be dropped rather than carried through.
os.environ["DATABASE_URL"] = "postgresql://u:p@localhost/powerwize?sslmode=disable"
derived = _testdb.test_db_url()
check("an unrelated parameter is preserved", "sslmode=disable" in derived,
      derived)
check("the derived URL points at the test database",
      derived.endswith("/" + TEST_DB_NAME) or
      ("/" + TEST_DB_NAME + "?") in derived, derived)
os.environ["DATABASE_URL"] = "postgresql://u:p@localhost/powerwize?host=localhost"
derived = _testdb.test_db_url()
check("a redirecting parameter is dropped, not carried through",
      "host=" not in derived, derived)
psycopg2.connect = _original
if _saved_url is not None:
    os.environ["DATABASE_URL"] = _saved_url
_testdb._guard_installed = _saved_guard


print("\n5. use_test_db() refuses to run after db/app is imported")
sys.modules["db"] = object()
try:
    _testdb.use_test_db()
    check("late use_test_db() is refused", False, "it returned")
except SystemExit as e:
    check("late use_test_db() is refused", "already imported" in str(e), str(e)[:58])
finally:
    del sys.modules["db"]


failed = [x for x in results if not x[1]]
print(f"\n{'='*64}\n{len(results) - len(failed)}/{len(results)} passed")
for n, _, d in failed:
    print(f"  FAILED: {n} {d}")
print("No database was contacted by this test.")
sys.exit(1 if failed else 0)
