"""baseline: registry showtimes

Revision ID: 0001_baseline
Revises:
Create Date: 2026-07-28

The first migration of the hosted service. Every column here is something a Seat Page
told us about a bare showtime ID — there is no column a human fills in.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "showtimes",
        # AMC's own showtime ID, so re-contributing a known ID collides instead of
        # duplicating.
        sa.Column("showtime_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("movie_id", sa.Integer(), nullable=False),
        sa.Column("movie_name", sa.String(length=300), nullable=False),
        sa.Column("theatre_id", sa.Integer(), nullable=False),
        sa.Column("theatre_name", sa.String(length=300), nullable=False),
        sa.Column("format_code", sa.String(length=100), nullable=False),
        sa.Column("format_name", sa.String(length=200), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("showtime_id"),
    )
    # Watch selectors match on movie + theatre + format, optionally narrowed by a
    # date/time window, so those four are what the Registry is queried by.
    op.create_index("ix_showtimes_movie_id", "showtimes", ["movie_id"])
    op.create_index("ix_showtimes_theatre_id", "showtimes", ["theatre_id"])
    op.create_index("ix_showtimes_format_code", "showtimes", ["format_code"])
    op.create_index("ix_showtimes_starts_at_utc", "showtimes", ["starts_at_utc"])


def downgrade():
    op.drop_index("ix_showtimes_starts_at_utc", table_name="showtimes")
    op.drop_index("ix_showtimes_format_code", table_name="showtimes")
    op.drop_index("ix_showtimes_theatre_id", table_name="showtimes")
    op.drop_index("ix_showtimes_movie_id", table_name="showtimes")
    op.drop_table("showtimes")
