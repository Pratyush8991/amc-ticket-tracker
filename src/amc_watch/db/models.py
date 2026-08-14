"""Domain tables.

Baseline only: the Registry's Showtime row, whose every column is something a Seat Page
told us. There is deliberately no place for a human to type a movie name or a format —
Showtime metadata is never user-supplied (ADR-0001).
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Showtime(Base):
    """One screening in the Registry, enriched from its Seat Page.

    The primary key is AMC's own showtime ID, which is what makes Contribution
    idempotent: several friends harvesting the same AMC page is a no-op collision rather
    than a duplicate row.

    A Contribution stores the bare ID alone, so a row exists before anything is known
    about it: every enrichment column below is null until the enrichment pass fetches the
    Seat Page. `enriched_at` is the marker — null means "still pending", and nothing may
    infer pending-ness from a null movie name instead.
    """

    __tablename__ = "showtimes"

    showtime_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    movie_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    movie_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    theatre_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    theatre_name: Mapped[str | None] = mapped_column(String(300), nullable=True)

    # Read from the Seat Page, never hardcoded — InfinityVision's code is unknown until
    # the first Doomsday Contribution lands.
    format_code: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    format_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    starts_at_utc: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )

    # The full seat grid as last fetched. Kept so the visual seat picker can render a
    # real auditorium the moment any showtime for that house is in the Registry, without
    # spending Polling Budget on a fetch just to draw the map.
    layout: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # A showtime AMC says does not exist. Set once and never retried: a 404 is permanent,
    # and Polling Budget spent rediscovering a typo is budget stolen from a real Watch.
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Why the last enrichment attempt failed, kept so the reason outlives the command that
    # produced it — an operator reading the Registry later must not find silence.
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
