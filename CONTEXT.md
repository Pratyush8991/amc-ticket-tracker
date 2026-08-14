# CONTEXT — amc-ticket-tracker

Ubiquitous language for the seat-watching domain. Glossary only — no implementation details.

## Terms

**Seat Page** — AMC's server-rendered page at `www.amctheatres.com/showtimes/<id>/seats`.
A *seat-read fallback*, no longer the system's data source: given a bare showtime ID it
yields the showtime's movie, theatre, format, date/time, and full seat layout (a
`seatingLayout` object in the Next.js RSC payload). Open to plain HTTP with a browser
User-Agent, and it fails independently of the GraphQL seat query, so it backstops seat
reads — never Discovery. The primary data source is now AMC's public GraphQL API
(theatres, showtimes, seat layouts; see **Discovery**); the queue-walled HTML *listing*
pages stay unusable for enumeration.

**Theatre** — a Registry entry for one AMC location: `theatreId`, `slug`, `name`,
location (city/state/coordinates), and its attributes/formats. Sourced from AMC's GraphQL
`viewer.theatres` search (free-text query, coordinates, attribute filters, cursor
pagination). Theatres power Discovery targeting — a `slug` is what the showtime-enumeration
query needs — and back the theatre pickers in Watch creation.

**Showtime** — one screening (movie × theatre × auditorium × date/time × format),
identified by AMC's numeric showtime ID. Arrives pre-enriched from Discovery — the GraphQL
showtime rows already carry movie, format, start time and auditorium — so there is no
separate enrichment fetch and no human ever supplies showtime metadata.

**Registry** — the shared pool of known Showtimes (and the Theatres they play at). Grows
only by automated **Discovery** — there is no manual contribution path. Shared across all
users: once Discovery finds a showtime, every matching Watch covers it.

**Discovery** — automated enumeration of Showtimes through AMC's public GraphQL API
(`viewer.theatre(slug){…showtimes…}`), the *sole* way Showtimes enter the Registry. The
rows come back pre-enriched (movie, format, start time, auditorium), so no separate
enrichment fetch follows. Runs as a pass inside the poller, targeting the distinct
theatres and movies of active Watches; there is no human step. The business date is driven
by a `session` cookie, so Discovery loops forward day by day and unions the showtime IDs.

**Format** — AMC's presentation format for a showtime (e.g. `imax70mm`, Dolby Cinema,
InfinityVision), carried on the discovery rows as a format `code` + `name`. A format
implies an auditorium in practice, which is why seat criteria are chosen per format — the
system never models auditoriums directly.

**Polling Budget** — the hard global ceiling on outbound requests per minute, shared by
everything the system watches. The scarce resource of the whole domain: AMC's tolerance,
not compute, is the limit. Spent through three lanes — the **discovery lane** (GraphQL
theatre-enumeration passes, slow), and two seat-read lanes: the **fast lane** (imminent
showtimes, recent seat churn, or a Watch marked **hot**, e.g. on-sale day) polled ~every
minute, and the **slow lane** (everything else) polled on a stretched interval. When the
cap is hit, the slow and discovery lanes stretch further; the fast lane is protected.

**Seat Criteria** — the block of acceptable seats for a Watch: row letters plus a
seat-number range, always chosen against the *actual* auditorium layout (rendered from an
already-fetched Seat Page, screen shown for orientation, missing rows preserved — AMC
skips rows like "I"), never guessed blind. Criteria are expressed in *printed* seat names
(the "N7" a human reads off a ticket), which are a different coordinate system from the
Grid Position below.

**Grid Position** — a seat's `row`/`column` in the Seat Page's layout grid, as distinct
from its printed name. The two are not interchangeable and need not even run in the same
direction: in Metreon 16's IMAX house, seat K34 sits at grid column 1 and K1 at column 34,
so printed numbers descend as grid columns ascend. Adjacency is therefore *only* ever
computed on Grid Positions — two seats with consecutive printed numbers are neighbours by
accident of layout, not by rule.

**Party Size** — how many adjacent seats a Watch requires. A Watch field, default 2.

**Bookable** — a seat a normal customer can actually reserve (AMC type `CanReserve`).
AMC marks wheelchair/companion seats "available" too; availability alone is *not*
bookability, and only Bookable seats count toward an Opening.

**Opening** — Party Size (or more) adjacent Bookable seats, all within a Watch's Seat
Criteria, in one Showtime. The unit of alerting: a Watch fires when a new Opening
appears. Adjacency means consecutive grid columns in the same grid row (see Grid
Position — never consecutive printed seat numbers); aisles and wheelchair/companion
positions occupy their own grid cells, so they break adjacency naturally.

**Channel** — the delivery mechanism by which a user receives Alerts. Pluggable by
design; initially one private ntfy topic per user (subscribe once, all Watches page
there). Per-watch topics are a possible later refinement, not a day-one concept.

**Alert** — the message sent to a user's Channel when one of their Watches gains a new
Opening. Labeled with movie, format, showtime, and seats, and carries a one-tap link to
the Seat Page. Deduplicated per Opening: the same Opening never re-pages while it stays
open, but an Opening that closes and later reopens pages again.

**Watch** — a user's standing intent to be alerted about bookable seat openings,
expressed as a *selector* over the Registry: movie + theatre + format, optionally
narrowed by a date/time window, plus seat criteria and party size. Every Showtime in the
Registry that matches the selector is covered automatically, including ones discovered
after the Watch was created. A user wanting two formats creates two Watches.
Lifecycle: **active** → (**paused** ⇄ active) → **done** (user got tickets) or
**expired** (last covered Showtime's start time has passed — automatic). Only active
Watches generate Alerts, and only Showtimes covered by at least one active Watch are
polled; a Showtime whose start time has passed is never polled.
