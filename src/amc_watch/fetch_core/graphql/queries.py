"""The GraphQL documents sent to graph.amctheatres.com.

Shapes confirmed live 2026-08-14 by browser-console introspection and a returned sample
(docs/research/amc-discovery-mechanisms.md). The seat query selects the same showtime
object the RSC Seat Page embeds, which is what lets both backends share one SeatPage
extraction. The showtime id is inlined as an int literal (the confirmed form) rather
than a typed variable, because the argument's schema type name is unverified.
"""

THEATRES_QUERY = """
query Theatres(
  $query: String
  $coordinates: CoordinatesInput
  $includeAttributes: String
  $excludeAttributes: String
  $brand: String
  $operation: Operation
  $first: Int
  $after: String
) {
  viewer {
    theatres(
      query: $query
      coordinates: $coordinates
      includeAttributes: $includeAttributes
      excludeAttributes: $excludeAttributes
      brand: $brand
      operation: $operation
      first: $first
      after: $after
    ) {
      count
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          theatreId
          name
          slug
          city
          state
          postalCode
          latitude
          longitude
          marketSlug
          utcOffset
          timezoneAbbreviation
          ticketable
          isInOutage
        }
      }
    }
  }
}
"""


DISCOVERY_QUERY = """
query TheatreShowtimes($slug: String!) {
  viewer {
    theatre(slug: $slug) {
      theatreId
      name
      slug
      formats {
        items {
          attributes { name code }
          groups(first: 100) {
            edges {
              node {
                showtimes(first: 200) {
                  edges {
                    node {
                      showtimeId
                      showDateTimeUtc
                      status
                      auditorium
                      isReservedSeating
                      format { attributes { code name } }
                      movie { name slug movieId }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""


_SEAT_QUERY = """
{
  viewer {
    showtime(id: $SHOWTIME_ID) {
      showtimeId
      showDateTimeUtc
      format { attributes { code name } }
      movie { movieId name }
      theatre { theatreId name }
      seatingLayout {
        rows
        columns
        seats { name row column available seatStatus type shouldDisplay }
      }
    }
  }
}
"""


def seat_query(showtime_id):
    return _SEAT_QUERY.replace("$SHOWTIME_ID", str(int(showtime_id)))
