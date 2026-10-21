# The desk reports its own absence

The desk cannot report its own absence while it is absent. It reports a **Down gap** at boot and a **Freeze** on resume. An outside service reports the rest from missing **Heartbeats**.

None of this depends on the host. The same code runs in local Docker and on the VPS. A crash, an OOM kill, a deploy, a host reboot, and a paused VM all look the same from the desk's side. There are no sleep settings, no lid checks, and no Docker Desktop specifics.

The Heartbeat is outbound only: a GET to a URL the operator sets. There is still no public ingress ([ADR 0005](0005-no-app-auth-loopback-tailscale.md)). The desk skips a ping when it is unhealthy, so the service's grace period does the alerting. The desk never pushes "I am fine".

Lighter's scheduled Cancel all (`CANCEL_ALL_TIF_SCHEDULED`) is not a dead man's switch. It would also cancel the venue stops that [ADR 0015](0015-planner-owns-the-exit.md) and [ADR 0016](0016-a-trail-is-moved-by-the-desk.md) deliberately leave on while the desk is down.
