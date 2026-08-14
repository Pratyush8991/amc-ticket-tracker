# FastAPI + SQLAlchemy/Alembic, not Django

All three services are Python (the fetch/parse core's requests-based behavior is proven
against AMC's Cloudflare hardening where curl is not, so porting runtimes was never on
the table). We chose FastAPI + SQLAlchemy + Alembic over Django because the service is
deliberately API-first — a future app/public API is the stated trajectory — and typed
request/response models pay off there.

## Considered options

Django was the velocity pick and remains worth remembering: free admin UI (registry and
watch inspection during the invite-only era), sessions/auth, and migrations wiring all
come built in. We accepted hand-rolling those in exchange for the API-first skeleton.

## Amendment (2026-08-14)

Transport is now backend-specific. The GraphQL data surface (`graph.amctheatres.com`,
adopted for discovery + seats in ADR-0005) 403s plain python-requests *and* curl, so it is
fetched with `curl_cffi` (browser TLS fingerprint) + a warmed cookie jar. python-requests
stays load-bearing for the RSC seat-page host (`www.amctheatres.com`), where it still
passes and curl 403s. The "requests, not curl" lesson holds per-host; the general fix when
`requests` gets fingerprinted is `curl_cffi`, not a headless browser.
