# A push is a toast that leaves the desk

A **Push** repeats a fact the desk already raised or already acted on: a Held-market alert, an algo fill, Auto kill, the venue going quiet. It does not decide, and it is not a new kind of Alert. The operator still trades from the desk page.

v1 is outbound only. The desk posts `sendMessage` and never reads a reply. A read-only `/status` (Positions, uPnL, live algos) via `getUpdates` long polling, gated to the configured chat, is a fine v2. It needs its own section when it is built.

Long polling, never a webhook. A webhook would need a public ingress. The desk has none ([ADR 0005](0005-no-app-auth-loopback-tailscale.md)): loopback, Tailscale Serve, no Funnel. Polling stays inside that boundary; a webhook would not.

A push never blocks or fails a trading path. The call that enqueues a message returns immediately and does not raise. The worker that talks to Telegram can drop a message. It cannot fail an order, a kill, or an algo step.

`/kill` from Telegram is out. It would be the first way to trade that does not go through the desk page. It needs an explicit yes and its own ADR.
