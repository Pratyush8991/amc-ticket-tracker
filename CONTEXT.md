# CONTEXT — amc-ticket-tracker

Ubiquitous language for the seat-watching domain. Glossary only — no implementation details.

## Terms

**Seat Page** — AMC's server-rendered page at `/showtimes/<id>/seats`. The system's *only*
data source. Self-describing: given a bare showtime ID, it yields the showtime's movie,
theatre, format, date/time, and the full seat layout. Open to plain HTTP; everything else
on amctheatres.com is queue-walled.

**Showtime** — one screening (movie × theatre × auditorium × date/time × format),
identified by AMC's numeric showtime ID. Enriched automatically from its Seat Page;
no human ever supplies showtime metadata.

**Registry** — the shared pool of known Showtimes. Grows only by Contribution; AMC's
listings cannot be scraped (Queue-it waiting room). Shared across all users: once any
user contributes a showtime, every matching Watch covers it.

**Contribution** — the act of submitting bare showtime IDs to the Registry, either by
pasting or via the Bookmarklet. The only manual step in the whole system.

**Bookmarklet** — a browser helper that harvests every showtime ID from whatever AMC page
a user legitimately has open (they pass the queue as a human) and submits them as a
Contribution in one tap.

**Format** — AMC's presentation format for a showtime (e.g. `imax70mm`, Dolby Cinema,
InfinityVision), as reported by the Seat Page. A format implies an auditorium in practice,
which is why seat criteria are chosen per format — the system never models auditoriums
directly.

**Polling Budget** — the hard global ceiling on Seat Page requests per minute, shared by
everything the system watches. The scarce resource of the whole domain: AMC's tolerance,
not compute, is the limit. Spent through two lanes — the **fast lane** (imminent
showtimes, recent seat churn, or a Watch marked **hot**, e.g. on-sale day) polled ~every
minute, and the **slow lane** (everything else) polled on a stretched interval. When the
cap is hit, the slow lane stretches further; the fast lane is protected.

**Seat Criteria** — the block of acceptable seats for a Watch: row letters plus a
seat-number range, always chosen against the *actual* auditorium layout (rendered from an
already-fetched Seat Page, screen shown for orientation, missing rows preserved — AMC
skips rows like "I"), never guessed blind.

**Party Size** — how many adjacent seats a Watch requires. A Watch field, default 2.

**Bookable** — a seat a normal customer can actually reserve (AMC type `CanReserve`).
AMC marks wheelchair/companion seats "available" too; availability alone is *not*
bookability, and only Bookable seats count toward an Opening.

**Opening** — Party Size (or more) adjacent Bookable seats, all within a Watch's Seat
Criteria, in one Showtime. The unit of alerting: a Watch fires when a new Opening
appears. Adjacency means consecutive grid columns in the same grid row; aisles and
wheelchair/companion positions occupy their own grid cells, so they break adjacency
naturally.

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
Registry that matches the selector is covered automatically, including ones contributed
after the Watch was created. A user wanting two formats creates two Watches.
Lifecycle: **active** → (**paused** ⇄ active) → **done** (user got tickets) or
**expired** (last covered Showtime's start time has passed — automatic). Only active
Watches generate Alerts, and only Showtimes covered by at least one active Watch are
polled; a Showtime whose start time has passed is never polled.
