from contextlib import closing

import pytest

from app.config import get_settings


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "links.db"))
    get_settings.cache_clear()
    from app import db as db_module

    db_module.init_db()
    yield db_module
    get_settings.cache_clear()


def test_create_then_lookup(db):
    code = db.get_or_create("https://example.com/page")
    assert len(code) == 5
    assert db.lookup(code) == "https://example.com/page"


def test_get_or_create_is_idempotent(db):
    first = db.get_or_create("https://example.com/x")
    second = db.get_or_create("https://example.com/x")
    assert first == second


def test_distinct_urls_get_distinct_codes(db):
    a = db.get_or_create("https://a.example.com")
    b = db.get_or_create("https://b.example.com")
    assert a != b


def test_lookup_unknown_returns_none(db):
    assert db.lookup("missing") is None


def test_reserved_codes_are_skipped(db, monkeypatch):
    # A generated code that lands on a reserved route name must be skipped; the
    # generator falls through to the next, non-reserved code. Which names are
    # reserved is derived from the route table in app.main (see
    # tests/test_app.py::test_route_codes_are_reserved); here we just pin the
    # DB-layer skip contract against an explicit reserved set.
    db.init_db(reserved_codes=frozenset({"health"}))
    codes = iter(["health", "safe01"])
    monkeypatch.setattr("app.db.generate", lambda length=5: next(codes))
    assert db.get_or_create("https://example.com/reserved") == "safe01"
    assert db.lookup("health") is None


def test_connection_has_busy_timeout(db):
    with closing(db._connect()) as con:
        assert con.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_database_uses_wal_mode(db):
    with closing(db._connect()) as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_concurrent_url_insert_returns_existing_code(db, monkeypatch):
    # Reproduce the race the retry loop guards: the initial SELECT misses, then
    # another writer inserts the same URL before our INSERT runs. The UNIQUE(url)
    # constraint must trip and we must return the winner's code, not a new one.
    url = "https://example.com/race"

    def racing_generate(length=5):
        with closing(db._connect()) as other:
            other.execute(
                "INSERT INTO links (code, url, created_at) VALUES (?, ?, ?)",
                ("WINNER", url, "2026-01-01T00:00:00Z"),
            )
            other.commit()
        return "LOSER1"

    monkeypatch.setattr("app.db.generate", racing_generate)
    assert db.get_or_create(url) == "WINNER"
    assert db.lookup("LOSER1") is None


def test_code_generation_exhaustion_raises(db, monkeypatch):
    # Occupy a non-reserved code with one URL.
    monkeypatch.setattr("app.db.generate", lambda length=6: "TAKEN1")
    assert db.get_or_create("https://a.example.com") == "TAKEN1"

    # For a DIFFERENT url, force generate() to always return that now-taken code
    # so every attempt is a true PK collision (the url SELECT keeps missing),
    # driving the loop through all _MAX_CODE_ATTEMPTS to the RuntimeError.
    with pytest.raises(RuntimeError, match="unique short code"):
        db.get_or_create("https://b.example.com")
    assert db.lookup("TAKEN1") == "https://a.example.com"


def test_list_all_returns_links_newest_first(db):
    # created_at is a UTC ISO 8601 string, so lexicographic DESC == newest-first.
    with closing(db._connect()) as con:
        con.execute(
            "INSERT INTO links (code, url, created_at) VALUES (?, ?, ?)",
            ("old001", "https://example.com/old", "2026-01-01T00:00:00+00:00"),
        )
        con.execute(
            "INSERT INTO links (code, url, created_at) VALUES (?, ?, ?)",
            ("new001", "https://example.com/new", "2026-06-01T00:00:00+00:00"),
        )
        con.commit()

    rows = db.list_all()
    assert [row["code"] for row in rows] == ["new001", "old001"]
    assert rows[0]["url"] == "https://example.com/new"
    assert rows[0]["created_at"] == "2026-06-01T00:00:00+00:00"


def test_list_all_empty_when_no_links(db):
    assert db.list_all() == []


def test_delete_removes_link_and_reports_true(db):
    code = db.get_or_create("https://example.com/doomed")
    assert db.delete(code) is True
    assert db.lookup(code) is None
    assert db.list_all() == []


def test_delete_unknown_code_reports_false(db):
    db.get_or_create("https://example.com/keep")
    assert db.delete("nope12") is False
    # The unrelated link is untouched.
    assert len(db.list_all()) == 1


def test_pk_collision_is_retried(db, monkeypatch):
    # Occupy the code "AAAAAA" with one URL.
    monkeypatch.setattr("app.db.generate", lambda length=5: "AAAAAA")
    assert db.get_or_create("https://a.example.com") == "AAAAAA"

    # For a different URL, force generate() to collide once ("AAAAAA") and
    # then succeed ("BBBBBB"); the retry loop must skip the collision.
    codes = iter(["AAAAAA", "BBBBBB"])
    monkeypatch.setattr("app.db.generate", lambda length=5: next(codes))
    assert db.get_or_create("https://b.example.com") == "BBBBBB"
    assert db.lookup("BBBBBB") == "https://b.example.com"
