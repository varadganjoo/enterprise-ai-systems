"""Refund cases move only through an explicit transition table. Amounts cannot exceed a cap."""

from __future__ import annotations

from dataclasses import dataclass, field

CAPS = {
    "duplicate_charge": 500.0,
    "goodwill": 25.0,
    "shipping": 40.0,
}


@dataclass(frozen=True)
class Event:
    event_id: str
    event_type: str
    reason: str = ""
    amount: float = 0
    note: str = ""


@dataclass
class CaseState:
    status: str = "empty"
    reason: str = ""
    amount: float | None = None
    note: str = ""
    seen: set[str] = field(default_factory=set)
    history: list[str] = field(default_factory=list)


def apply_event(state: CaseState, event: Event) -> CaseState:
    if not event.event_id:
        raise ValueError("Event id is empty.")
    if event.event_id in state.seen:
        return state
    nxt = CaseState(
        status=state.status,
        reason=state.reason,
        amount=state.amount,
        note=state.note,
        seen=set(state.seen),
        history=list(state.history),
    )
    nxt.seen.add(event.event_id)
    kind = event.event_type
    if kind == "open" and nxt.status == "empty":
        nxt.status = "intake"
        nxt.note = event.note.strip()
    elif kind == "classify" and nxt.status == "intake":
        if event.reason not in CAPS:
            known = ", ".join(sorted(CAPS))
            raise ValueError(f"Reason {event.reason!r} is not allowed. Known reasons: {known}.")
        nxt.status = "classified"
        nxt.reason = event.reason
    elif kind == "propose" and nxt.status == "classified":
        cap = CAPS[nxt.reason]
        if event.amount <= 0:
            raise ValueError(f"Proposed amount must be positive, got {event.amount}.")
        if event.amount > cap:
            raise ValueError(
                f"Proposed amount {event.amount:.2f} exceeds the {nxt.reason} cap of {cap:.2f}."
            )
        nxt.status = "proposed"
        nxt.amount = float(event.amount)
    elif kind == "approve" and nxt.status == "proposed":
        nxt.status = "approved"
    elif kind == "reject" and nxt.status == "proposed":
        nxt.status = "rejected"
    elif kind == "execute" and nxt.status == "approved":
        nxt.status = "executed"
    else:
        raise ValueError(f"Cannot apply {kind!r} while the case is {nxt.status}.")
    nxt.history.append(kind)
    return nxt


def project(events: list[Event]) -> CaseState:
    state = CaseState()
    for event in events:
        state = apply_event(state, event)
    return state
