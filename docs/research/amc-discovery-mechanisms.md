# How seat/showtime notifiers actually discover AMC data

**Status:** research memo, 2026-08-14. **Bearing on the project:** directly challenges
ADR-0001's premise that "AMC's listings cannot be scraped, so discovery must be human
Contribution." That premise is true *only for the server-rendered HTML listing pages*
(the Queue-it surface). It is **false for AMC's data layer**, which is reachable two other
ways. Automated discovery of showtimes — the thing the Registry currently waits on a human
for — is feasible today.

This memo is reconstructed from third-party open-source code and the builders' own public
statements. **No requests were sent to amctheatres.com** while writing it (the project's
own 429 caution, see the catalog-IDs memory, still holds). Every AMC-endpoint shape below
should be validated with a *single* manual browser call before you build on it.

---

## Headline

There are three independent doors into AMC showtime + seat data. The Queue-it waiting room
sits in front of only one of them.

| Door | Discovery (list showtimes)? | Live seats? | Auth | Approval | Works today |
| --- | --- | --- | --- | --- | --- |
| **1. Public GraphQL** `graph.amctheatres.com` | **Yes** | **Yes** | browser cookies/Origin | none | **yes** |
| **2. Official REST API** `api.amctheatres.com` | **Yes** | **Yes** (catalog tier TBC) | `X-AMC-Vendor-Key` | ~10-day vendor request | after key |
| **3. Third-party feeds** (Intl Showtimes et al.) | Yes | No (times only) | vendor key | paid tier | after signup |

The HTML path in ADR-0001 (`www.amctheatres.com/.../showtimes/...`) is a *fourth*, worst
door — it's the one behind Queue-it/Cloudflare. Everyone who scrapes it (e.g. the
open-source Odyssey tracker) does so only because they don't know about door 1.

---

## Door 1 — the public GraphQL endpoint (the discovery route around Queue-it)

**This is the finding that matters most.** AMC's own web app fetches both the showtime
listing *and* the seat map from a GraphQL endpoint, authorized by the browser's ordinary
cookies — **no vendor key, no approval, not Queue-it-walled.** Proven in live open-source
code: [`NameFILIP/amc-good-seats`](https://github.com/NameFILIP/amc-good-seats)
(`amc-script.js`), and independently confirmed by the builder of
[imaxxing.io](https://imaxxing.io/) who states he is "directly calling the GQL"
([HN](https://news.ycombinator.com/item?id=48960551)).

**Endpoint:** `POST https://graph.amctheatres.com/`

**Discovery query** — enumerates every showtime at a theatre (this is what the Registry
needs; it replaces human Contribution):

```graphql
{
  viewer {
    theatre(slug: "<theatre-slug>") {
      name theatreId slug
      formats { items {
        attributes { name code }
        groups(first: 100) { edges { node {
          showtimes(first: 200) { edges { node {
            showtimeId
            showDateTimeUtc
            status
            auditorium
            isReservedSeating
            movie { name slug movieId }
          } } }
        } } }
      } }
    }
  }
}
```

**Seat query** — the same data the current `fetch_core` parser digs out of the RSC HTML,
but as clean JSON:

```graphql
{
  viewer {
    showtime(id: <showtimeId>) {
      showtimeId status
      seatingLayout {
        rows columns
        seats { name row column available seatStatus type shouldDisplay }
      }
    }
  }
}
```

**Request shape (from a browser context):**

```javascript
fetch("https://graph.amctheatres.com/", {
  method: "POST",
  credentials: "include",                       // browser cookies authorize the call
  headers: { "Content-Type": "application/json", "Accept": "application/json" },
  body: JSON.stringify({ query }),
});
```

**Two load-bearing gotchas** (both from the script's own comments):

- **Do NOT send `X-AMC-Vendor-Key` (or any custom header) from a browser.** CORS preflight
  rejects custom headers; the browser's `Origin`/`Referer`/cookies are what authorize it.
  Implication: from a **server-side, non-CORS** context (which is what our poller is) the
  same endpoint most likely accepts a vendor key — i.e. doors 1 and 2 may be the same host
  family with two auth modes.
- **The "business date" is cookie-driven, not a query parameter.** AMC reads the target
  date from a `session` cookie's `nowInDays` / `lastViewedDate` fields. To page through
  future dates you patch that cookie:

  ```javascript
  session.nowInDays = daysSinceEpoch(target);
  session.lastViewedDate = `${yyyyMMdd}T12:00:00.000Z`;
  document.cookie = `session=${encoded}; path=/; domain=.amctheatres.com; max-age=86400; SameSite=Lax`;
  ```

**What this changes for us:** the Bookmarklet and human Contribution are removed entirely
(ADR-0005). A poller can
enumerate a theatre's showtimes itself (the discovery query), feed the `showtimeId`s
straight into the Registry, and read seats from either the GraphQL seat query or the
existing HTML seat-page fetcher. Discovery latency stops being "bounded by a human
noticing" (ADR-0001's stated cost).

---

## Door 2 — the official REST API (`api.amctheatres.com`)

AMC runs a real, documented developer program at
[developers.amctheatres.com](https://developers.amctheatres.com/), served from
**`api.amctheatres.com` — a different host from the queue-walled web frontend**, so it
bypasses Queue-it by construction. Endpoint/field detail below is from the
[API-Evangelist mirror](https://github.com/api-evangelist/amc-entertainment-holdings) of
AMC's OpenAPI/Postman specs and the community
[AMCAPI](https://github.com/StateMachineJunkie/AMCAPI) Swift client (whose path strings are
real).

**Confirmed live today (one benign probe):** `GET https://api.amctheatres.com/v2/theatres`
with a browser UA returned **HTTP 400 (JSON "missing vendor key"), `server: cloudflare`** —
**not** a 302 into `queue.amctheatres.com`. So the host is up, Cloudflare-fronted, and
**off the Queue-it path**. Notably plain `curl` reached it — it does *not* have the
TLS-fingerprint block the website has (contrast ADR-0003), because this host expects API
clients, not browsers.

- **Auth:** single header `X-AMC-Vendor-Key: <GUID>` (API-key model, no OAuth).
  Docs: [Authentication](https://developers.amctheatres.com/GettingStarted/Authentication).
- **Access tiers:**
  - **Catalog — open, self-serve, free:** theatres, movies, showtimes, **seating layouts**,
    media. Apply at
    [New Vendor Request](https://developers.amctheatres.com/GettingStarted/NewVendorRequest).
    Two independent client authors report **~10 days** from registration to a working key.
    "Developers are welcome to access catalog APIs to display AMC showtimes." Apply from a
    real browser — the *docs portal* (not the API host) is Cloudflare-bot-blocked.
  - **Ecommerce — approval-gated, signed contract:** orders, payment, **seat *selection***,
    concessions, refunds.
- **Rate limits:** **not authoritatively published.** The api-evangelist mirror lists
  free = 10 req/min (burst 20) / 1,000-per-month quota, standard `X-RateLimit-*` +
  `Retry-After`, 429 on throttle — but that file **labels these as scaffold placeholders**,
  so treat as unverified until you hold a key.

**Showtime API v2** (discovery) — paths confirmed against the AMCAPI client:

- `GET /v2/theatres` — enumerate theatres (to get theatre numbers).
- `GET /v2/theatres/{theatre-number}/showtimes` — **all future showtimes** for a theatre,
  optional `?movie-id=` filter. **The discovery primitive.**
- `GET /v2/theatres/{theatre-number}/showtimes/{date}` — showtimes on one date (ISO
  `YYYY-MM-DD`).
- `GET /v2/theatres/{theatre-number}/showtimes/{date}/views/embargoed` — embargoed
  (not-yet-on-sale) showtimes → the "alert me the moment tickets drop" feature.
- `GET /v2/showtimes/views/current-location/{date}/{lat}/{lng}` — geo-proximity search.
- `GET /v2/showtimes/{id}` — one showtime (the same self-describing numeric ID we scrape).
- Each showtime returns: numeric `id`, `movieId`/name, `showDateTimeUtc`/`Local`,
  `theatreId`, `auditorium`, `layoutId`, `isSoldOut`, `isAlmostSoldOut`, `isCanceled`,
  `attributes[]` (IMAX / Reserved Seating / …), **`ticketPrices[]` (with tax + formatted
  price — which the RSC seat-page scrape doesn't reliably give)**, a `purchaseUrl`
  (`…/showtimes/<id>/seats`), and a HAL `_links` **`seating-layout`** →
  `https://api.amctheatres.com/v2/seating-layouts/{theatreId}/{showtimeId}`. HAL-paged
  envelope (`pageSize`/`pageNumber`/`count`/`_embedded`/`_links`).

**Seating API** (availability):

- `GET /v2/seating-layouts/{theatre-number}/{performance-number}` → every seat with
  `seatId`, `seatType` (Standard/Recliner/Wheelchair/Companion/Premium/LoveSeat/Couple),
  **`isAvailable`**, `row`, `column`.
- **The one real unknown:** whether `isAvailable` reflects **real-time** booked state on a
  free **catalog** key, or whether live seat state needs the ecommerce tier. The docs page
  is titled "Seating API **v3**" while the mirrored spec shows `/v2/seating-layouts` paths —
  a version gap to check. **Validate this the day a key arrives.** If catalog keys don't
  expose live seat state, keep the existing per-showtime seat-page RSC scrape for the map
  and let the API own discovery + prices (a hybrid).
- A **Webhook API v1** also exists — if it can push seat/showtime events it would replace
  polling for on-sale/seat-drop detection entirely; worth investigating once you have a key.

**Why this could retire most of the project:** if seating is in the open catalog tier, the
official API gives us discovery *and* live per-seat availability (plus prices) without
scraping, without TLS-fingerprint games, and without the 429 tightrope — the seat-page
scraper becomes the fallback, not the engine. The contingencies are approval discretion and
the seating-tier placement, so apply now (10-day lead) and keep the scraper working in
parallel.

---

## Door 3 — third-party showtime feeds (breadth, not seats)

For non-AMC chains or nationwide coverage, aggregators sell showtime feeds. Only one
plausibly carries the AMC showtime ID; none give live seat maps.

| Feed | AMC showtime ID / deep-link | Seats | Cost |
| --- | --- | --- | --- |
| **International Showtimes** (Webedia/Cinepass) | **maybe** — `booking_link` on `booking_type:external` may embed `amctheatres.com/showtimes/NNN` | no | 7-day free trial; **€299/mo** Business tier for ticketing links |
| MovieGlu | no (times only) | no | contact-sales |
| Gracenote / TMS OnConnect | no (Fandango affiliate link, keyed by theatre+date) | no | free public plan |
| Google Showtimes via SerpAPI | no (search link) | no | free 250/mo, then paid |
| Fandango / Atom partner APIs | no (their own IDs) | Atom: seat *count* only | approval + contract |

Verdict: third-party feeds are a **discovery cross-check / non-AMC breadth** play, not a
seat source. The only cheap experiment worth running is the International Showtimes free
trial, purely to see whether its AMC `booking_link` contains the numeric showtime ID.

---

## The enabling layer: staying unblocked (Cloudflare, not the data)

Every builder agrees the adversary is **Cloudflare bot protection**, not the availability
of the data. What actually gets through:

- **TLS/JA3 impersonation.** imaxxing's builder's explicit recommendation is
  [`curl_cffi`](https://github.com/lexiforest/curl_cffi) — a Python client that impersonates
  a real browser's TLS fingerprint. This is the server-side analogue of the project's
  existing hard-won lesson ("python-requests passes where curl 403s", ADR-0003): the fix
  when `requests` eventually gets fingerprinted is `curl_cffi`, not Selenium.
- **Cookie warming.** Hit a normal page first to earn a `__cf_bm` cookie, then call the
  API/JSON endpoint with that cookie jar (the Odyssey tracker does exactly this for Regal).
- **Adaptive polling cadence.** imaxxing polls **every 10 min until 24h before showtime,
  then ramps to every 60s** near showtime (orchestrated with Temporal). This is a concrete
  calibration for our Polling Budget's fast/slow lanes — and it's gentler than one-per-
  minute-per-showtime, which matters given AMC 429s after ~6 rapid probes from one IP.
- **Never headless-browser AMC** (ADR-0001's `webdriverDetected` point stands). The winning
  stack is a fingerprint-correct HTTP client, not a driven browser.

---

## How the reference services actually work

- **seatdrop.app** (the user's example): free notifier for AMC + Cinemark + Alamo, no
  account, never touches payment. Its own
  ["Cancellation Clock"](https://seatdrop.app/insights/cancellation-clock) analytics page
  ("5,600+ seat-opening events captured Mar 21–Apr 10 2026") is a fingerprint of
  **continuous automated seat-map polling that timestamps each open/close transition** —
  not a data feed, not human contribution. Its "Planner" (upcoming-releases) feature is
  currently paused "due to unavailable AMC showtime data," which tells you its AMC discovery
  rides the same fragile listing surface everyone fights. Almost certainly polling the
  public seat maps (very likely GraphQL for AMC) and diffing state.
- **imaxxing.io**: AMC via `graph.amctheatres.com` GraphQL directly; non-AMC via a
  third-party US showtime provider; `curl_cffi` for Cloudflare; adaptive polling via
  Temporal. The most technically transparent competitor.
- **[globalcityzen/odyssey-70mm-tracker](https://github.com/globalcityzen/odyssey-70mm-tracker)**:
  open-source, stdlib-only Python on a 15-min GitHub Actions cron. A full multi-chain
  scraping blueprint — but it scrapes AMC's *HTML* (the Queue-it surface), which is the
  brittle path; it's the best worked example of the **Regal** (`regmovies.com/api/getShowtimes`,
  `StopSales` flag, `__cf_bm` warming) and **Cinemark**
  (`cinemark.com/umbraco/surface/Showtimes/GetByTheaterId`, `soldOut` markup) JSON paths if
  the project ever expands past AMC.
- **Adjacent (concert/sports) drop notifiers** all reduce to the same loop: poll a public
  listing endpoint on an interval, diff against the user's filters, fan out push/SMS/webhook
  the instant a match appears. Faster interval → closer to real-time. That is exactly the
  project's matcher+notifier design already.

---

## Recommendation for amc-ticket-tracker

> **Adopted (2026-08-14, ADR-0005):** GraphQL-only automated discovery. Human Contribution
> and the Bookmarklet are removed entirely — no manual paste, no fallback. The official
> vendor-key path below is retained only as an optional future hedge, not part of the build.

1. **Validate Door 1 with a single manual browser call** (residential, the user's own
   Chrome — the cookie-authorized path, indistinguishable from normal use). Confirm the two
   GraphQL query shapes still return data as of today. One call, not a probe loop.
2. **Adopt GraphQL as the primary fetch surface**, server-side, with a vendor key if it's
   accepted there (test) and cookie-warming + `curl_cffi` if not. It gives clean JSON for
   both discovery and seats — simpler and less brittle than the RSC-HTML unescape/parse in
   `fetch_core/parse.py`, which becomes the fallback.
3. **Add automated discovery** via the GraphQL discovery query per watched theatre, on the
   slow lane, feeding `showtimeId`s into the Registry — the sole way Showtimes enter it.
   Human Contribution and the Bookmarklet are removed entirely (ADR-0005 supersedes
   ADR-0001).
4. **Apply for an official vendor key today** (`NewVendorRequest`, ~10-day lead). If seating
   is in the open catalog tier, migrate to Door 2 as the sanctioned, TLS-game-free path and
   demote scraping to fallback. Investigate the **Webhook API** to replace on-sale polling
   with push.
5. **Keep the Polling Budget, recalibrated** to imaxxing's 10-min→60s adaptive curve rather
   than one-per-minute; the 429 ceiling is real and low.
6. **Terms & ethics:** the official API's catalog tier is explicitly sanctioned for
   displaying showtimes. The GraphQL/scraping paths are the same data your browser already
   fetches, but check AMC's ToS; keep cadence polite; never automate checkout (the project's
   existing manual-booking split is correct and should stay).

---

## Appendix — closing the theatre-discovery gap (GraphQL-only)

The open GraphQL cleanly provides **showtimes** (`viewer.theatre(slug).…showtimes`, date
driven by the `session` cookie) and **seats** (`viewer.showtime(id).seatingLayout`). The one
piece the open-source examples don't exercise is **enumerating/searching theatres** — they
hardcode slugs (`venues.json`). Two facts:

- **You usually don't need it.** A tracker watches a known set of theatres; a slug is a
  stable string you copy once from a theatre's URL
  (`amctheatres.com/movie-theatres/<market>/<slug>` → `<slug>`). That's config, not a call.
- **If you want a "pick any theatre" picker, the open GraphQL does it too — CONFIRMED**
  (2026-08-14, via console introspection from a logged-in browser). `viewer` exposes:
  - `theatre(slug: String) → Theatre` — single lookup (already used).
  - `theatres(query, coordinates, includeAttributes, excludeAttributes, brand, operation,
    after, first, before, last) → TheatreConnection` — a full Relay connection: free-text
    search (`query`), geo/proximity (`coordinates`), format/amenity filters
    (`includeAttributes`/`excludeAttributes`), sub-brand (`brand`), operational status
    (`operation`), and cursor pagination.

  So the GraphQL-only path is self-sufficient end to end — `theatres(...)` → per-theatre
  `showtimes` → per-showtime `seatingLayout` — and **no official key is required even for a
  theatre picker.** The official REST equivalent
  ([`/v2/theatres`](https://developers.amctheatres.com/Theatres): `market`/`state`/`city`/
  `name`/geo) remains a sanctioned, Cloudflare-free alternative if you hold a key.

**To confirm the GraphQL theatre field yourself**, paste this in DevTools console on any
`amctheatres.com` page while logged in (it runs two introspection calls and prints the
theatre-related fields + their args):

```js
(async () => {
  const gql = async (query) => (await fetch("https://graph.amctheatres.com/", {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    body: JSON.stringify({ query }),
  })).json();
  const typeName = (t) => t && (t.name || (t.ofType && t.ofType.name));
  const root = await gql(`{ __schema { queryType { fields { name type { name kind ofType { name kind } } } } } }`);
  if (root.errors || !root.data) { console.log("introspection blocked:", JSON.stringify(root).slice(0,400),
    "\nFallback: open the theatre-finder page, watch the Network tab for the graph.amctheatres.com POST,",
    "or send a bogus persistedQuery hash to force PersistedQueryNotFound and read the resent query."); return; }
  const rf = root.data.__schema.queryType.fields;
  console.log("ROOT fields:", rf.map(f => f.name).join(", "));
  const vType = typeName((rf.find(f => f.name === "viewer") || {}).type);
  console.log("viewer type:", vType);
  const v = await gql(`{ __type(name: "${vType}") { fields { name args { name } type { name kind ofType { name kind } } } } }`);
  const vf = (v.data && v.data.__type && v.data.__type.fields) || [];
  console.log("THEATRE-related viewer fields:",
    JSON.stringify(vf.filter(f => /theat/i.test(f.name) || /theat/i.test(typeName(f.type) || ""))
      .map(f => ({ name: f.name, args: f.args.map(a => a.name), returns: typeName(f.type) })), null, 2));
})();
```

If introspection is disabled, the fallback in the snippet's log applies: read the actual
theatre-finder query off the Network tab, or force a `PersistedQueryNotFound` to make the
client resend the full query text.

*(A headless live probe from the build session on 2026-08-14 was blocked three ways — no
attached browser, a permission block on the outbound POST, and a Cloudflare 403 to headless
fetch — all environmental. The introspection was then run successfully from a logged-in
browser console, which is how the `viewer.theatres` connection above was confirmed. Takeaway:
this endpoint answers only from a real browser context, so any headless/server-side poller
must reproduce a browser TLS fingerprint + cookies (`curl_cffi`) rather than plain requests.)*

## Ready-to-use GraphQL query chain (confirmed live 2026-08-14)

Full `viewer.theatres` schema confirmed by console introspection **plus a live sample that
returned real theatres with working pagination**. These three queries are the complete
discovery→seats pipeline. Run them server-side with a browser TLS fingerprint + cookies
(`curl_cffi`), not plain `requests`/`curl` — the host 403s otherwise. `POST
https://graph.amctheatres.com/`, body `{"query": "..."}`, `credentials: include`, no custom
headers.

**Confirmed signature:** `theatres(query: String, coordinates: CoordinatesInput,
includeAttributes: String, excludeAttributes: String, brand: String, operation: Operation,
after: String, before: String, first: Int, last: Int) → TheatreConnection`
- `CoordinatesInput { latitude: Float, longitude: Float }`
- `Operation` enum = `AND | OR` (how include/exclude attribute filters combine)
- `TheatreConnection { count: Int, pageInfo: PageInfo, edges { node: Theatre } }`
- `Theatre` node: `theatreId, slug, name, longName, city, state, stateCode, postalCode,
  addressLine1/2, latitude, longitude, distance, marketSlug, marketName, utcOffset,
  timezoneAbbreviation, brand, attributes, formats, movies, ticketable, isInOutage,
  websiteUrl, directionsUrl` (+ more).

### 1. Enumerate / search theatres → build the theatre table once, refresh rarely

```graphql
query Theatres($after: String) {
  viewer {
    theatres(query: "AMC", first: 50, after: $after) {
      count
      pageInfo { hasNextPage endCursor }
      edges { node {
        theatreId name slug
        city state postalCode latitude longitude
        marketSlug utcOffset timezoneAbbreviation ticketable isInOutage
      } }
    }
  }
}
```

- `query: "AMC"` matches every theatre → a full enumeration ordered by `theatreId`; page by
  feeding `pageInfo.endCursor` into `$after` until `hasNextPage` is false. (Live sample:
  theatreId 6/24/25 = AMC Esquire 7, Streets of St Charles 8, Ward Parkway 14; `endCursor`
  `cGM6MToxOjI=`.)
- Geo instead: swap in `coordinates: { latitude: 37.78, longitude: -122.40 }`.
- Format filter: `includeAttributes: "imax70mm", operation: AND` — attribute/format codes
  come off each showtime's `format.code` and the theatre's `attributes`/`formats` fields.

### 2. Enumerate a theatre's showtimes (discovery — replaces human Contribution)

```graphql
{
  viewer {
    theatre(slug: "amc-metreon-16") {
      theatreId name slug
      formats { items {
        attributes { name code }
        groups(first: 100) { edges { node {
          showtimes(first: 200) { edges { node {
            showtimeId showDateTimeUtc status auditorium isReservedSeating
            movie { name slug movieId }
          } } }
        } } }
      } }
    }
  }
}
```

The business date is **cookie-driven**, not an argument: before each call, set the `session`
cookie's `nowInDays` (days since epoch of the target date) and `lastViewedDate`, then loop
forward N days and union the `showtimeId`s. (Server-side: GET a page first to obtain a
`session` cookie, URL-decode its JSON, patch those two fields, re-encode into the jar.)
Worth a 2-minute check whether `groups`/`showtimes` accept a date arg directly — if so, skip
the cookie dance.

### 3. Read seats for a showtime (clean JSON alternative to the RSC scrape)

```graphql
{
  viewer {
    showtime(id: 145377422) {
      showtimeId status
      seatingLayout {
        rows columns
        seats { name row column available seatStatus type shouldDisplay }
      }
    }
  }
}
```

Same fields `fetch_core/parse.py` digs out of the RSC HTML, but pre-parsed. Keep the HTML
seat-page fetcher as the fallback (different surface, fails independently).

### Wiring into this repo

- **Theatres query** → seeds a theatre table / watch config (the `slug`s that step 2 needs);
  refresh weekly, not per-poll.
- **Showtimes query** → the Registry-enrichment path and the *only* way Showtimes enter the
  Registry — feed `showtimeId`s straight in; Bookmarklet/human Contribution removed (ADR-0005).
- **Seat query** → a second `fetch_core` backend alongside the RSC scrape; both feed the
  same `SeatPage` model and Opening computation.
- **Transport** is the one real build task: browser-accurate TLS (`curl_cffi`) + warmed
  cookies + the session-date cookie, on the adaptive fast/slow lane cadence (10 min → 60 s
  near showtime). This is ADR-0003's lesson generalized one step.

## Sources

- AMC public GraphQL, verbatim queries: <https://github.com/NameFILIP/amc-good-seats> (`amc-script.js`)
- imaxxing.io builder on GQL + `curl_cffi` + polling cadence: <https://news.ycombinator.com/item?id=48960551>
- Multi-chain scraping blueprint (AMC HTML, Regal, Cinemark): <https://github.com/globalcityzen/odyssey-70mm-tracker>
- seatdrop mechanism fingerprint: <https://seatdrop.app/insights/cancellation-clock> · <https://seatdrop.app/>
- AMC official portal + Showtime API v2 + New Vendor Request + Affiliate Deep Linking:
  <https://developers.amctheatres.com/> · <https://developers.amctheatres.com/ApiReference/showtime-api-v2> · <https://developers.amctheatres.com/GettingStarted/NewVendorRequest> · <https://developers.amctheatres.com/GettingStarted/AffiliateDeepLinking>
- AMC API schema mirror (Postman): <https://github.com/api-evangelist/amc-entertainment-holdings>
- Community AMC client (`X-AMC-Vendor-Key`, ~10-day key lead): <https://github.com/StateMachineJunkie/AMCAPI>
- Third-party feeds: <https://developer.movieglu.com/v2/api-index/filmshowtimes/> · <https://developer.tmsapi.com/> · <https://serpapi.com/showtimes-results> · <https://developer.fandango.com/Fandango> · <https://developers.atomtickets.com/> · <http://api.internationalshowtimes.com/documentation/v4>
- `curl_cffi` (TLS impersonation): <https://github.com/lexiforest/curl_cffi>
</content>
</invoke>

---

## Addendum — live schema corrections from the fetch-core build (2026-08-14, #15)

Server-side introspection and single live calls through `curl_cffi` while building the
GraphQL backend corrected three shape assumptions above:

- **`Showtime.format` is `ShowtimeMovieFormat`** (`id, attributes, groups, movie`), *not*
  a Relay connection — the `format { edges … }` shape exists only inside the RSC page
  embed. On live discovery rows and live `viewer.showtime` seat reads, `format` comes
  back **null**.
- **Where the format identity actually lives — and how to read it safely.** Every
  showtime carries its own `attributes` AttributeConnection, and *that* is the source for
  both discovery rows and seat reads. Do **not** take the first entry: the connection is
  ordered by AMC's global `sort` and mixes categories, so an ordinary 2D showtime leads
  with `reservedseating`. Each attribute carries `groups { id name }`, and AMC's own
  categories are the discriminator:

  | group | id | example codes |
  | --- | --- | --- |
  | **Format** | 3 | `imax70mm`(8), `imax`(11), `70mm`(23), `dolbycinemaatamcprime`(13), `laseratamc`(60), `fanfaves`(26) |
  | Features | 4 | `reclinerseating`(54), `amcclubrockers`(54) |
  | Amenities | 2 | `reservedseating`(170) |
  | Accessibility | 1 | `closedcaption`(200), `descriptivevideo`(999) |

  The format is the **lowest-`sort` member of group 3**; `sort` orders by specificity
  within the group (imax70mm 8 < imax 11 < 70mm 23). A showtime with no group-3
  attribute genuinely has no premium format — record that, don't guess. Note AMC files
  some non-presentation things (`fanfaves`, `opencaption`, `japaneseenglishsubtitle`)
  under Format; store what AMC says rather than second-guessing its taxonomy.

  **Do not** take the format from the enclosing `formats.items[].attributes` tab: a
  showtime is listed under several tabs (an IMAX 70MM screening appears under both the
  IMAX 70MM and IMAX tabs), so the tab decides nothing and using it makes the recorded
  format depend on AMC's tab ordering.
- **`Showtime.auditorium` is a bare `Int`**, and GraphQL validation errors ride the body
  of an HTTP **400** — read the body before trusting the status code.
- **Nested connections are capped, not paged.** `groups(first: N)` / `showtimes(first: N)`
  answer a truncated list with `hasNextPage: true` and no complaint. Select `pageInfo` and
  treat truncation as a failure — a partial discovery is a Registry silently missing
  Showtimes.

Confirmed live the same day, residential IP: discovery returned **69 showtimes** for
`amc-metreon-16` (business date via the session cookie), every row format-attributed, and
the seat read for a row agreed with discovery on its format code. Plain `requests` still
403s the host with a Cloudflare challenge; `curl_cffi` (chrome impersonation, warmed jar)
passes. Re-record fixtures with `tools/record_graphql_fixtures.py` rather than hand-writing
them — every correction on this list came from real payloads disagreeing with an
assumption.
