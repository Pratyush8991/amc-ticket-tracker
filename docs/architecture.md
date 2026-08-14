# System design — amc-ticket-tracker (GraphQL-discovery architecture)

The invite-only hosted seat-watcher, as redesigned around **automated discovery via AMC's
public GraphQL API** (ADR-0005; supersedes ADR-0001). No human contribution, no bookmarklet.
Diagrams are Mermaid — GitHub renders them inline; in VSCode use the *Markdown Preview
Mermaid Support* extension (or any Mermaid preview) and open this file's preview.

> **One-line summary:** a poller enumerates showtimes for the theatres/movies people are
> watching (GraphQL), reads seat maps for the covered showtimes, a matcher finds blocks of
> adjacent bookable seats inside each Watch's criteria, and an alerter pings the user's phone
> — who then books manually on AMC.

---

## 1. Component architecture

Three services on one cloud box over one Postgres, no broker (ADR-0002). The only outbound
edge is `fetch-core`, which has two backends: **GraphQL via `curl_cffi`** (primary; discovery
+ seats) and the already-built **RSC seat page via `requests`** (seat-read fallback only).

```mermaid
flowchart LR
  subgraph AMC["AMC — external"]
    GQL["Public GraphQL<br/>graph.amctheatres.com<br/>curl_cffi · no vendor key · off Queue-it"]
    RSC["RSC seat page<br/>www.amctheatres.com/showtimes/&lt;id&gt;/seats<br/>requests · seat-read fallback"]
    CHK["AMC checkout<br/>login + CAPTCHA<br/>MANUAL — never automated"]
  end

  USER["User<br/>browser / phone"]
  NTFY["ntfy.sh<br/>private topic per user"]

  subgraph BOX["Cloud box — systemd unit per service · ADR-0002 / 0004"]
    WEB["web service (FastAPI)<br/>invites + device-cookie auth<br/>Watch mgmt · Registry browse · seat picker"]
    subgraph POLL["poller service"]
      DP["discovery pass<br/>enumerate showtimes"]
      SP["seat pass<br/>read seat maps (fast/slow lanes)"]
    end
    MN["matcher + notifier service<br/>compute Openings · dedup ledger · dispatch"]
    subgraph FC["fetch-core module"]
      GB["GraphQL backend<br/>curl_cffi + cookie jar + session-date cookie"]
      RB["RSC backend<br/>requests"]
    end
    PG[("Postgres<br/>domain tables + work tables")]
  end

  USER -->|create / manage Watches| WEB
  WEB <--> PG
  DP --> GB
  SP --> GB
  SP -. fallback .-> RB
  GB --> GQL
  RB --> RSC
  DP -->|upsert Registry rows| PG
  SP -->|seat snapshots| PG
  MN <--> PG
  MN -->|Alert| NTFY
  NTFY -->|push| USER
  USER -. books manually .-> CHK
```

---

## 2. Runtime flow (the three passes)

Discovery, seat-polling, and matching are independent synchronous passes coordinating only
through Postgres work tables. Each is a `run_once()` the tests drive directly.

```mermaid
sequenceDiagram
  actor U as User
  participant W as web
  participant DB as Postgres
  participant P as poller
  participant G as AMC GraphQL
  participant M as matcher+notifier
  participant N as ntfy

  U->>W: Create Watch (movie+theatre+format, seat criteria, party size)
  W->>DB: store Watch (active)

  rect rgb(230,240,255)
  Note over P,G: DISCOVERY pass — slow lane
  P->>DB: read active Watches to get (theatre, movie) targets
  P->>G: viewer.theatres(query / coordinates)  [theatre registry]
  P->>G: viewer.theatre(slug){ showtimes }  [loop dates via session cookie]
  G-->>P: pre-enriched showtimes (movie, format, time, auditorium)
  P->>DB: upsert Registry rows — no separate enrichment fetch
  end

  rect rgb(230,255,235)
  Note over P,G: SEAT pass — fast / slow lanes
  P->>DB: read Showtimes covered by an active Watch (never past ones)
  P->>G: viewer.showtime(id){ seatingLayout }
  G-->>P: seat grid (name, row, column, available, type)
  P->>DB: write seat snapshots (work tables)
  end

  rect rgb(255,245,230)
  Note over M,N: MATCH pass
  M->>DB: read snapshots + active Watches
  M->>M: compute Openings (>= party size adjacent Bookable seats within criteria)
  M->>DB: consult per-Opening dedup ledger
  M->>N: Alert (movie, format, showtime, seat names, seat-page deep link)
  N-->>U: push notification
  end
  U-->>U: book manually on AMC
```

**Why discovery has no enrichment step:** the `viewer.theatre(slug){…showtimes…}` payload
already carries movie, format code+name, start time and auditorium, so a discovered row lands
fully enriched. The seat map is fetched separately (per-showtime) only when polling.

---

## 3. Domain model

The Registry is the shared pool of Showtimes (and the Theatres that host them); Watches are
selectors over it; Openings are what fire Alerts.

```mermaid
erDiagram
  USER ||--o{ WATCH : owns
  USER ||--|| CHANNEL : "has (ntfy topic)"
  THEATRE ||--o{ SHOWTIME : hosts
  WATCH }o--o{ SHOWTIME : "covers (selector match)"
  SHOWTIME ||--o{ SEAT_SNAPSHOT : "polled into"
  WATCH ||--o{ OPENING : produces
  SHOWTIME ||--o{ OPENING : contains
  OPENING ||--o| ALERT : "paged as (deduped)"

  USER {
    id id
    string invite_token
    string device_cookie
    string ntfy_topic
  }
  THEATRE {
    int theatreId
    string slug
    string name
    string city_state
    json attributes_formats
  }
  SHOWTIME {
    int showtimeId
    int movieId
    string movie_name
    string format_code
    datetime starts_at_utc
    string auditorium
  }
  WATCH {
    id id
    string movie
    string theatre
    string format
    json date_window
    json seat_criteria
    int party_size
    enum state
    bool hot
  }
  SEAT_SNAPSHOT {
    int showtime_id
    datetime observed_at
    json seats
  }
  OPENING {
    id id
    int watch_id
    int showtime_id
    string seat_run
    string identity
  }
  ALERT {
    id id
    int watch_id
    int showtime_id
    string opening_identity
    datetime sent_at
  }
```

Key rules baked into the model:
- **Coverage is automatic** — a Watch covers every Registry Showtime matching its selector,
  including ones discovered *after* the Watch was created; no re-editing.
- **Adjacency is computed on grid coordinates only** (see CONTEXT.md "Grid Position"), never
  on printed seat numbers.
- **Bookable = AMC `CanReserve` only** — wheelchair/companion seats are "available" but never
  count toward an Opening.
- **Alerts dedup per Opening identity** — a persisting Opening never re-pages; one that closes
  and reopens pages again.

---

## 4. Watch lifecycle

Only **active** Watches drive discovery targeting, get their showtimes polled, and generate
Alerts.

```mermaid
stateDiagram-v2
  [*] --> active : created
  active --> paused : pause
  paused --> active : resume
  active --> done : user booked
  paused --> done : user booked
  active --> expired : last covered showtime started (auto)
  paused --> expired : last covered showtime started (auto)
  done --> [*]
  expired --> [*]

  note right of active
    Active only:
    - included in Discovery targeting
    - its Showtimes are seat-polled
    - can generate Alerts
    Past Showtimes are never polled.
  end note
```

---

## 5. Polling Budget

AMC's tolerance — not compute — is the scarce resource. One hard global requests/minute cap
now covers **discovery enumeration and seat reads together**.

```mermaid
flowchart TB
  CAP["Hard global cap<br/>requests / minute"]
  CAP --> DL["Discovery lane — slow<br/>enumerate per watched theatre"]
  CAP --> FL["Fast seat lane ~60s<br/>start &lt;72h · seat churn · Watch hot"]
  CAP --> SL["Slow seat lane ~3-5min<br/>everything else"]
  PRESS["Under cap pressure:<br/>discovery + slow lanes stretch;<br/>fast lane is protected"]
  DL -.-> PRESS
  SL -.-> PRESS
```

Transport politeness is backend-specific: the GraphQL backend uses a `curl_cffi` browser TLS
fingerprint + a warmed cookie jar + jitter + a small worker pool; the RSC fallback keeps the
fresh-session / browser-UA behavior. Never a headless browser (AMC flags automation).

---

## 6. What's built vs. planned, and the build order

`fetch-core` (RSC backend), the monorepo skeleton, Alembic baseline and smoke-test are
**built** (issue #2). Everything else is planned; **#15 is the only unblocked next step.**
Arrows are the GitHub-native `blocked_by` dependencies.

```mermaid
flowchart LR
  I2["#2 Skeleton + fetch-core RSC + smoke-test"]:::done
  I15["#15 fetch-core GraphQL backend<br/>curl_cffi · discovery + seat queries"]:::next
  I3["#3 Registry: automated GraphQL discovery"]:::planned
  I4["#4 Tracer bullet: Watch to Opening to Alert"]:::planned
  I6["#6 Watch lifecycle + discovery/poll targeting"]:::planned
  I7["#7 Polling Budget: lanes + global cap"]:::planned
  I5["#5 Deploy: cloud box, systemd, smoke-test-first"]:::planned
  I8["#8 Web: invites/auth/ntfy"]:::planned
  I9["#9 Web: Registry browsing"]:::planned
  I10["#10 Web: Watch mgmt + Alert history"]:::planned
  I11["#11 Visual seat picker"]:::planned
  I12["#12 Bookmarklet — NOT REQUIRED (wontfix)"]:::dropped

  I2 --> I15
  I15 --> I3
  I15 --> I4
  I3 --> I4
  I4 --> I5
  I4 --> I6
  I6 --> I7
  I4 --> I8
  I8 --> I9
  I8 --> I10
  I10 --> I11

  classDef done fill:#1f7a3d,color:#ffffff,stroke:#0d3d1f;
  classDef next fill:#9a6300,color:#ffffff,stroke:#4d3200;
  classDef planned fill:#2b3550,color:#ffffff,stroke:#141b2b;
  classDef dropped fill:#5a2020,color:#ffffff,stroke:#3a1010,stroke-dasharray:4 3;
```

**Order:** `#15 → #3 → #4`, then the operational track (`#6 → #7`, `#5`) and the web track
(`#8 → #9 / #10 → #11`). Day-one of #15: spike whether `curl_cffi` reaches
`graph.amctheatres.com` from the server/datacenter IP before building the full client.

---

## 7. Non-negotiable invariants

- **No human contribution, no bookmarklet, no fallback for them** — discovery is entirely
  automated (ADR-0005).
- **Booking stays manual** — the tool watches; the human does checkout (login + CAPTCHA +
  AMC Stubs). No Selenium/Playwright at checkout, ever.
- **The Seat Page describes itself / discovery rows arrive enriched** — showtime metadata is
  never user-supplied; format codes (e.g. InfinityVision) are stored exactly as reported,
  never hardcoded.
- **`SeatPageShapeChanged` is loud** — a parser regression fails, never silently reads "no
  seats". "AMC blocked us" and "no seats open" must never look alike.

References: `CONTEXT.md` (glossary), `docs/adr/0001`–`0005`, `docs/research/amc-discovery-mechanisms.md` (verified queries).
</content>
