# A price alert is a push, not an order

[ADR 0020](0020-an-idea-is-a-note-not-an-order.md) keeps the Ideas page away from the venue. A **Price alert** is the one place an Idea's price now does something: when Last reaches a level, moves by a percent, or the Daily Change crosses one, the desk raises a toast, sends a Push and writes the Idea log. That is all it does. It is the operator's own tripwire, stated as a fact ([ADR 0013](0013-an-alert-is-a-fact-and-a-toast-is-a-coincidence.md)), and it leaves the desk the way every other Push does ([ADR 0017](0017-a-push-is-a-toast-that-leaves-the-desk.md)).

It does not place an order, arm a Planner, or move the Idea's status. "Buy when it reaches the zone" is still a Trail entry or a Planner started from the desk. Checks run inside the desk process, so an alert is only as awake as the desk. A level crossed while the desk was down fires at the first look after it starts, and says so.
