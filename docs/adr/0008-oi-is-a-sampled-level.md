# Open interest is a sampled level

Trades do not include open interest. The desk samples the two-sided USD print already on `market_stats/all`: one close per perp per UTC minute for 30 days, then one high, low, and last per UTC day for the life of the desk. A day is not a sum — open interest is a level, and minutes the desk missed stay missing. The series is drawn on the price chart. Liquidation intensity stays on the live print until a window is fully sampled, because a partial average would pretend the window had a denominator.
