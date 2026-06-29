import re

import pytest

SHORT_URL_RE = re.compile(r"https://s\.test/([0-9A-Za-z]{5})")


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_index_renders_responsive_form(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert 'name="viewport"' in body
    assert 'name="url"' in body
    assert 'action="/shorten"' in body


def test_shorten_returns_short_url(client):
    response = client.post("/shorten", data={"url": "https://example.com/page"})
    assert response.status_code == 200
    assert SHORT_URL_RE.search(response.text)


def test_same_url_yields_same_code(client):
    first = client.post("/shorten", data={"url": "https://example.com/dup"})
    second = client.post("/shorten", data={"url": "https://example.com/dup"})
    code_a = SHORT_URL_RE.search(first.text).group(1)
    code_b = SHORT_URL_RE.search(second.text).group(1)
    assert code_a == code_b


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "   ",
        "not a url",
        "ftp://example.com",
        "javascript:alert(1)",
        "data:text/html,x",
    ],
)
def test_invalid_url_is_rejected(client, bad_url):
    response = client.post("/shorten", data={"url": bad_url})
    assert response.status_code == 400
    assert "error" in response.text.lower() or "valid" in response.text.lower()
    assert not SHORT_URL_RE.search(response.text)


def test_known_code_redirects(client):
    # 302 (temporary), not 301: a mapping revoked via /admin stops resolving
    # immediately because browsers and caches re-check it instead of pinning it.
    created = client.post("/shorten", data={"url": "https://example.com/target"})
    code = SHORT_URL_RE.search(created.text).group(1)

    response = client.get(f"/{code}", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/target"


@pytest.mark.parametrize(
    "target",
    [
        "https://trusted.com@evil.com/",
        "https://user:pass@evil.com/",
    ],
)
def test_credentialed_targets_are_rejected(client, target):
    response = client.post("/shorten", data={"url": target})
    assert response.status_code == 400
    assert not SHORT_URL_RE.search(response.text)


def test_route_codes_are_reserved(client):
    # Reserved codes are derived from the live route table; pinned so a route
    # rename can't silently un-reserve a code.
    from app import db

    assert {"shorten", "admin", "health", "static"} <= db._reserved_codes


def test_overly_long_url_is_rejected(client):
    long_url = "https://example.com/" + "a" * 5000
    response = client.post("/shorten", data={"url": long_url})
    assert response.status_code == 400
    assert not SHORT_URL_RE.search(response.text)


def test_shorten_handles_db_failure(client, monkeypatch):
    def boom(url):
        raise RuntimeError("could not generate a unique short code")

    monkeypatch.setattr("app.main.db.get_or_create", boom)
    response = client.post(
        "/shorten",
        data={"url": "https://example.com/page"},
    )
    assert response.status_code == 500
    assert "create your short link" in response.text.lower()
    assert not SHORT_URL_RE.search(response.text)


def test_admin_lists_existing_links(client):
    created = client.post("/shorten", data={"url": "https://example.com/listed"})
    code = SHORT_URL_RE.search(created.text).group(1)

    response = client.get("/admin")
    assert response.status_code == 200
    assert code in response.text
    assert "https://example.com/listed" in response.text


def test_admin_renders_with_no_links(client):
    response = client.get("/admin")
    assert response.status_code == 200
    # No stored link, so no 5-char short code should appear in the table.
    assert not SHORT_URL_RE.search(response.text)


def test_admin_delete_revokes_link(client):
    created = client.post("/shorten", data={"url": "https://example.com/revoke"})
    code = SHORT_URL_RE.search(created.text).group(1)

    response = client.post("/admin/delete", data={"code": code}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"

    # The short link no longer resolves...
    assert client.get(f"/{code}", follow_redirects=False).status_code == 404
    # ...and it is gone from the management list.
    assert code not in client.get("/admin").text


def test_admin_delete_get_is_not_allowed(client):
    # Deletion must be POST-only: a GET can be fired by link-prefetching or a
    # crawler, which would silently destroy links.
    response = client.get("/admin/delete", follow_redirects=False)
    assert response.status_code == 405


def test_admin_delete_unknown_code_is_harmless(client):
    response = client.post(
        "/admin/delete", data={"code": "nope12"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"


def test_unknown_code_returns_404(client):
    response = client.get("/nope123", follow_redirects=False)
    assert response.status_code == 404
    assert "doesn't exist" in response.text
