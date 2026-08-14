"""The GraphQL documents sent to graph.amctheatres.com.

Shapes confirmed live 2026-08-14 by browser-console introspection and a returned sample
(docs/research/amc-discovery-mechanisms.md). The seat query selects the same showtime
object the RSC Seat Page embeds, which is what lets both backends share one SeatPage
extraction. The showtime id is inlined as an int literal (the confirmed form) rather
than a typed variable, because the argument's schema type name is unverified.
"""

_SEAT_QUERY = """
{
  viewer {
    showtime(id: $SHOWTIME_ID) {
      showtimeId
      showDateTimeUtc
      format { edges { node { code name } } }
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
