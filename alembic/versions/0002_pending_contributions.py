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


def upgrade():
    for name, type_ in ENRICHED_COLUMNS:
        op.alter_column("showtimes", name, existing_type=type_, nullable=True)
    op.add_column("showtimes", sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("showtimes", sa.Column("last_error", sa.String(length=500), nullable=True))


def downgrade():
    op.drop_column("showtimes", "last_error")
    op.drop_column("showtimes", "dead_at")
    # Unenriched rows have no metadata to invent, so they cannot survive going back.
    op.execute("DELETE FROM showtimes WHERE enriched_at IS NULL")
    for name, type_ in ENRICHED_COLUMNS:
        op.alter_column("showtimes", name, existing_type=type_, nullable=False)
