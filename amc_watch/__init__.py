"""AMC seat watcher.

Watches AMC seat maps for a movie/format and alerts when two adjacent seats open up
inside a target block. Public, key-less: the seat data is server-rendered into the page.

Layout:
  config.py  — load the watcher config and the on-disk notified-state
  seats.py   — fetch a seat page and reduce it to adjacent free-seat pairs
  notify.py  — push an alert via ntfy.sh
  __main__.py — CLI: poll every showtime, alert on newly-open pairs
"""
