"""contributions land before they are enriched

Revision ID: 0002_pending
Revises: 0001_baseline
Create Date: 2026-08-13

A Contribution carries a bare showtime ID and nothing else — the Seat Page supplies the
rest, later. So every enrichment column becomes nullable and `enriched_at` becomes the
one marker of whether a row has been filled in yet.

Enrichment can also fail, and failure has to survive the command that hit it: `dead_at`
records a showtime AMC says does not exist, `last_error` records why the last attempt
failed at all.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_pending"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

# Everything a Seat Page tells us, and therefore everything that is unknown at the moment
# of Contribution.
ENRICHED_COLUMNS = [
    ("movie_id", sa.Integer()),
    ("movie_name", sa.String(length=300)),
    ("theatre_id", sa.Integer()),
    ("theatre_name", sa.String(length=300)),
    ("format_code", sa.String(length=100)),
    ("format_name", sa.String(length=200)),
    ("starts_at_utc", sa.DateTime(timezone=True)),
]


# What "enriched" is worth: the Seat Page described the showtime completely, or it did not
# describe it at all. 0001 got this from NOT NULL; once the columns go nullable the promise
# has to be restated, or a half-filled row reads as enriched and the formatter dies on the
# NULL it was told could not be there.
ENRICHED_MEANS_DESCRIBED = (
    "enriched_at IS NULL OR ("
    + " AND ".join(f"{name} IS NOT NULL" for name, _ in ENRICHED_COLUMNS)
    + ")"
)


def upgrade():
    for name, type_ in ENRICHED_COLUMNS:
        op.alter_column("showtimes", name, existing_type=type_, nullable=True)
    op.add_column("showtimes", sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("showtimes", sa.Column("last_error", sa.String(length=500), nullable=True))
    op.create_check_constraint("ck_showtimes_enriched_means_described", "showtimes", sa.text(ENRICHED_MEANS_DESCRIBED))
    # The hot query of the enrichment pass, and of every poller tick after #4: find the
    # handful of rows still owed a fetch. Partial, so it stays the size of the backlog
    # rather than the size of the Registry.
    op.create_index(
        "ix_showtimes_pending",
        "showtimes",
        ["showtime_id"],
        postgresql_where=sa.text("enriched_at IS NULL AND dead_at IS NULL"),
    )


def downgrade():
    op.drop_index("ix_showtimes_pending", table_name="showtimes")
    op.drop_constraint("ck_showtimes_enriched_means_described", "showtimes", type_="check")
    op.drop_column("showtimes", "last_error")
    op.drop_column("showtimes", "dead_at")
    # Unenriched rows have no metadata to invent, so they cannot survive going back.
    op.execute("DELETE FROM showtimes WHERE enriched_at IS NULL")
    for name, type_ in ENRICHED_COLUMNS:
        op.alter_column("showtimes", name, existing_type=type_, nullable=False)
