# Watch is a desk view, not a second client

Watch can undock to its own window so Paths and the price chart can be seen at once. That window is opened from the desk, shares Watch Sets via localStorage, and receives quotes over BroadcastChannel. It never opens `/ws`. If the desk tab closes, Watch closes.

A mosaic panel would have kept Watch on the same screen. A second WebSocket would have duplicated the desk feed. A SharedWorker that owns one socket for every window is more plumbing than this desk needs.
