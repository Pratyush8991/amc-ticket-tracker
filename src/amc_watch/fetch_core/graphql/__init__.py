"""GraphQL discovery + seat reads on graph.amctheatres.com (ADR-0005)."""

from .client import (
    GRAPHQL_HEADERS,
    GRAPHQL_URL,
    WARMUP_URL,
    fetch_seat_page_graphql,
    open_graphql_session,
)

__all__ = [
    "GRAPHQL_HEADERS",
    "GRAPHQL_URL",
    "WARMUP_URL",
    "fetch_seat_page_graphql",
    "open_graphql_session",
]
