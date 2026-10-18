# A spike is a multiple of the hour's biggest minute

Price, volume and open interest spike by one rule: this minute is at least N times the biggest minute of the last 60. N is 2 for price and open interest and 3 for volume, whose tail is fatter. Each has a floor so a dead tape stays quiet.

Two other rules were tried on the desk's own tape. Sigmas of a market's last four hours made a small tick look like an event: on tapes that print nothing most minutes the median deviation was exactly zero. "The biggest minute of the hour" sounds like a spike and is not one, because every market sets a new hourly high about once an hour by chance: 419 volume rows a day across 43 liquid perps. Asking for a multiple of the previous biggest is what makes a minute stand out of its own surroundings, and it reads the same on BTC and on a thin alt.

The rule re-arms itself. Once a spike's minute closes it is the hour's biggest, so the next has to beat it. On 8.3 hours of 11 Oct 2026 and three days of stored open interest it found about 220 a day.
