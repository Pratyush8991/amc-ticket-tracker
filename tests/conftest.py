"""Shared test scaffolding.

Exactly one seam is faked: the outbound HTTP edge. Everything inward of `session.get` —
the RSC unescaping, the JSON extraction, the seat flattening, the error taxonomy — runs
for real against payloads recorded from AMC, so a parser regression fails the suite
rather than passing against a convenient mock (parent #1, "Testing Decisions").
"""

import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "rsc"
GRAPHQL_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "graphql"
QUEUE_URL = "https://queue.amctheatres.com/?c=amctheatres&e=globalsafetynetweb"


def load_rsc(name):
    """Read a recorded Seat Page payload by fixture name."""
    return (FIXTURE_DIR / f"{name}.rsc.txt").read_text()


def load_graphql(name):
    """Read a recorded GraphQL response payload by fixture name."""
    return json.loads((GRAPHQL_FIXTURE_DIR / f"{name}.json").read_text())


class FakeResponse:
    """The slice of requests.Response that fetch_core actually reads."""

    def __init__(self, text="", status_code=200, url="", history=()):
        self.text = text
        self.status_code = status_code
        self.url = url
        self.history = list(history)
        self.headers = {}

    @property
    def ok(self):
        return 200 <= self.status_code < 400


class Redirect:
    """A hop in `response.history`; only its Location header is consulted."""

    def __init__(self, location):
        self.headers = {"location": location}


class FakeSession:
    """Stands in for requests.Session at the one faked seam.

    `handler` receives the requested URL and returns a FakeResponse, so a test can vary
    the answer per showtime or across successive polls.
    """

    def __init__(self, handler):
        self.handler = handler
        self.requests = []

    def get(self, url, headers=None, timeout=None):
        self.requests.append({"url": url, "headers": headers, "timeout": timeout})
        return self.handler(url)

    def close(self):
        pass


def serving(fixture_name):
    """A session that answers every Seat Page request with one recorded payload."""
    body = load_rsc(fixture_name)
    return FakeSession(lambda url: FakeResponse(text=body, url=url))


# --- The GraphQL edge (curl_cffi) --------------------------------------------------
#
# Same seam, second backend: tests inject a session shaped like curl_cffi's, serving
# recorded GraphQL JSON. Query building, the session-date cookie dance, response
# classification and payload walking all run for real inward of here.


class FakeCookieJar:
    """The slice of the curl_cffi cookie jar the client touches.

    Keyed by (domain, name) exactly as the real jar is, because that dimension is
    load-bearing: a warm-up cookie set host-only on www and ours set on the parent
    domain are two *different* entries, both sent to AMC, and a flat name→value dict
    would quietly hide that.
    """

    def __init__(self, cookies=None):
        self._store = {}
        for name, value in (cookies or {}).items():
            self._store[("www.amctheatres.com", name)] = value
        self.set_calls = []

    def _matching(self, name):
        return [key for key in self._store if key[1] == name]

    def get(self, name, default=None):
        matches = self._matching(name)
        return self._store[matches[-1]] if matches else default

    def set(self, name, value, domain=None, path="/"):
        self._store[(domain or "", name)] = value
        self.set_calls.append({"name": name, "value": value, "domain": domain})

    def delete(self, name, domain=None, path=None):
        for key in [k for k in self._matching(name) if domain in (None, k[0])]:
            del self._store[key]

    def entries(self, name):
        """Every (domain, value) pair stored under `name` — what AMC would receive."""
        return [(key[0], self._store[key]) for key in self._matching(name)]


class FakeGraphQLResponse:
    """The slice of a curl_cffi response the GraphQL client actually reads."""

    def __init__(self, payload=None, status_code=200, text=None, url=""):
        self.status_code = status_code
        self.text = json.dumps(payload) if payload is not None else (text or "")
        self.url = url

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        return json.loads(self.text)


class FakeGraphQLSession:
    """Stands in for a curl_cffi session at the one faked seam.

    `handler` receives the posted JSON body (query + variables), so a test can answer
    per-query — e.g. serve successive theatre pages keyed off the `after` cursor.
    """

    def __init__(self, handler, cookies=None):
        self.handler = handler
        self.posts = []
        self.gets = []
        self.cookies = FakeCookieJar(cookies)

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.handler(json)

    def get(self, url, headers=None, timeout=None):
        self.gets.append({"url": url, "headers": headers, "timeout": timeout})
        return FakeGraphQLResponse(payload={}, url=url)

    def close(self):
        pass


def graphql_serving(fixture_name, cookies=None):
    """A session that answers every GraphQL POST with one recorded payload."""
    body = load_graphql(fixture_name)
    return FakeGraphQLSession(lambda posted: FakeGraphQLResponse(payload=body), cookies=cookies)


def graphql_responding(**kwargs):
    """A session that answers every GraphQL POST with one canned response."""
    return FakeGraphQLSession(lambda posted: FakeGraphQLResponse(**kwargs))


def graphql_paging(fixture_by_cursor):
    """A session that serves connection pages keyed off the posted `after` cursor."""

    def handler(posted):
        after = (posted.get("variables") or {}).get("after")
        return FakeGraphQLResponse(payload=load_graphql(fixture_by_cursor[after]))

    return FakeGraphQLSession(handler)


def responding(**kwargs):
    """A session that answers every request with one canned response."""
    return FakeSession(lambda url: FakeResponse(url=url, **kwargs))


@pytest.fixture
def as_recorded():
    """The Seat Page exactly as AMC served it: near sold out, row I absent."""
    return serving("metreon_imax70mm_as_recorded")


# --- Postgres -------------------------------------------------------------------
#
# The database is infrastructure under test, not a seam: the suite runs against a real
# ephemeral Postgres so that JSONB, timezone-aware timestamps and the migration chain are
# genuinely exercised. CI supplies one as a service container via DATABASE_URL; locally
# we boot a throwaway container.


@pytest.fixture(scope="session")
def postgres_url():
    # Note: this fixture is a generator, so the CI path must yield too — an early
    # `return` here would hand every test a None url.
    if url := os.environ.get("DATABASE_URL"):
        yield url
        return
    try:
        from testcontainers.community.postgres import PostgresContainer
    except ImportError:  # pragma: no cover - older testcontainers
        try:
            from testcontainers.postgres import PostgresContainer
        except ImportError:
            pytest.skip("no DATABASE_URL and testcontainers is not installed")

    with PostgresContainer("postgres:17-alpine", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def migrated_database(postgres_url):
    """Apply the migration chain from scratch, exactly as a fresh box would."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    os.environ["DATABASE_URL"] = postgres_url
    command.upgrade(cfg, "head")
    return postgres_url


@pytest.fixture
def db_session(migrated_database):
    """A session whose writes are rolled back, so tests cannot leak into each other."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(migrated_database)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
