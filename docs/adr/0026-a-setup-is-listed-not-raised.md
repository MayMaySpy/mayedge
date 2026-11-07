# A setup is listed, not raised

The desk keeps a **Setups** board on Scan: markets where open interest moves without price, funding has been stretched for three days, a market goes against the board, a range has gone quiet at a Week high or low, a break of one failed, or one side was flushed by liquidations. It is rebuilt once an hour, on closed hours and days. It raises no toast and sends no push.

The minute alerts were measured for 30 days to 6 Nov 2026, and none of them called the next 15 minutes better than a coin flip ([ADR 0023](0023-a-toast-is-for-what-the-operator-has-on.md)). The operator trades swings. What a swing trade starts from is positioning and range over hours and days: who is getting in, who is paying to stay in, who was forced out, and where price has gone quiet. Those change slowly, so a board the operator reads when looking for trades fits them; an interruption does not.

Each Setup states its facts and is written to the database when it is first listed, with the price then. None of them is trusted yet. They will be scored the way alert rows are ([ADR 0012](0012-an-alert-is-scored-from-the-price-it-fired-at.md)), at 4 hours, 24 hours and 3 days, and a Setup that does no better than a random bar comes off the board.
