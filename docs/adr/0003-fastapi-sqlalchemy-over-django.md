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
