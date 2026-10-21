# SDK 1.1.8 operator check

Do these on the live desk after the rebuild, in this order. The agent does not place, amend, or cancel anything.

1. Place one post-only limit far from the touch, at Quick size, on a perp whose index is at least 4095 (`STONK` or `DRV`). It rests. That proves create on a high index.
2. Amend its size from the Orders tab. That proves modify. The desk leaves `order_version` at the signer default.
3. Cancel all on that Market from the Orders tab. The order is gone. That proves per-market Cancel all on a high index, the signer fix from lighter-sdk 1.1.4.
4. With no algo live, rest one far post-only limit on BTC and one on `STONK`, then Kill without flatten. Both are gone. That proves Cancel all across every market, with indexes on both sides of 255.
5. Read `/api/health`. `trading_enabled` is true, and `market_ws` and `account_ws` are both `live`.
