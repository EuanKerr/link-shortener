# Link Shortener

A minimal, self-hosted URL shortener. Paste a long URL, get a short link.
Built with FastAPI + SQLite, deployed via Docker Compose, and designed to sit
behind an nginx reverse proxy that handles TLS and access control.

## Features

- Single responsive web page (mobile-first, dark-mode aware).
- Auto-generated 5-character base62 codes.
- Idempotent: submitting the same URL again returns the same short link.
- Persistent SQLite storage on a Docker volume.
- Management view (`/admin`) to list and revoke links (protect it upstream).
- No tracking, no accounts, no analytics.

## Configuration

Environment variables (set in `docker-compose.yml`):

| Variable   | Default                 | Purpose                                                  |
|------------|-------------------------|----------------------------------------------------------|
| `BASE_URL` | `http://localhost:8000` | Public URL used to build short links. No trailing slash. |
| `DB_PATH`  | `dev-links.db`          | SQLite file location.                                    |

The `DB_PATH` default (`dev-links.db`) is a working-directory file so local dev
works out of the box. `docker-compose.yml` overrides it with `/data/links.db`,
which lives on the `links-data` volume.

## Run

```bash
docker compose up -d
```

The app listens on `127.0.0.1:8000` by default. A complete reverse-proxy example
with TLS, security headers, and compression is in
[`nginx.example.conf`](nginx.example.conf). The minimal version is just:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Set `BASE_URL` to the public hostname nginx serves (e.g. `https://s.example.com`)
so generated links are correct.

## Management

`GET /admin` lists every link with a delete button; `POST /admin/delete` revokes
one. These routes have no built-in authentication, so they **must** be protected
by the reverse proxy. The example config restricts the `/admin` prefix with HTTP
basic auth (an IP allowlist is shown as an alternative); see
[`nginx.example.conf`](nginx.example.conf).

Because the app issues 302 (temporary) redirects, a revoked link stops resolving
immediately rather than staying pinned in client caches.

## Development

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

## Data

Links live in the SQLite file on the `links-data` volume and survive restarts
and rebuilds. `docker compose down -v` deletes the volume (and all links).
