# Seat pages are the only AMC data source; showtime discovery is human contribution

AMC's listing and theatre pages 302 into a Queue-it waiting room ("Global Safety Net",
verified 2026-07-21) and the v2 API requires a vendor key, but the per-showtime Seat Page
(`/showtimes/<id>/seats`) remains server-rendered and open to plain HTTP — and it is
self-describing (movie, theatre, format, date/time, full layout). We therefore fetch
*only* Seat Pages, and new showtime IDs enter the Registry exclusively by human
Contribution (paste or Bookmarklet harvesting a page the user legitimately has open).

## Considered options

- **Scrape listings for discovery** — dead: queue-walled, client-side rendered.
- **Sequential ID-range probing** — IDs arrive in near-contiguous batches, so probing
  unseen neighbors would work, but it is speculative traffic AMC never linked to a user
  and materially raises WAF/bot-flag risk against the one endpoint we depend on.
  Rejected; held in reserve.
- **Headless browser through the queue** — AMC actively flags automation
  (webdriverDetected); risks the whole tool. Rejected.

## Consequences

Discovery latency is bounded by a human noticing new showtimes; the Bookmarklet exists
to make that one tap. If AMC ever queue-walls Seat Pages, the system has no data source.
