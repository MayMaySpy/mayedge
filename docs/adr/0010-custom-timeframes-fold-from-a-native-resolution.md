# Custom timeframes fold from a native resolution

A typed timeframe Lighter does not serve, such as 3m, 2h, or 30s, is bucketed on the desk from the coarsest native resolution that divides it: Lighter's 1m, 5m, 15m, 30m, 1h, 4h, 12h, and 1d, or the desk's 1s buffer when nothing coarser divides. Offering only Lighter's enum would have refused those sizes. The desk does not page past Lighter's 500-candle cap, so a 3m chart is about eight hours of 1m history. Open interest stays on the resolutions already stored.
