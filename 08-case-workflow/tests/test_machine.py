import pytest

from app.machine import CAPS, Event, apply_event, project


def _open() -> list[Event]:
    return [
        Event("e1", "open", note="Duplicate card charge"),
        Event("e2", "classify", reason="duplicate_charge"),
    ]


def test_execute_before_approval_is_rejected():
    state = project(_open() + [Event("e3", "propose", amount=40)])
    assert state.status == "proposed"
    with pytest.raises(ValueError, match="Cannot apply 'execute'"):
        apply_event(state, Event("e4", "execute"))


def test_amount_above_the_cap_does_not_change_the_case():
    state = project(_open())
    with pytest.raises(ValueError, match="exceeds"):
        apply_event(state, Event("e3", "propose", amount=CAPS["duplicate_charge"] + 1))
    assert state.status == "classified"


def test_replay_is_stable_and_duplicate_events_do_not_apply_twice():
    events = _open() + [
        Event("e3", "propose", amount=40),
        Event("e3", "propose", amount=999),
        Event("e4", "approve"),
        Event("e5", "execute"),
    ]
    assert project(events).status == "executed"
    assert project(events).amount == 40


def test_goodwill_cap_is_tighter_than_a_duplicate_charge():
    state = project(
        [
            Event("e1", "open", note="Sorry about the delay"),
            Event("e2", "classify", reason="goodwill"),
        ]
    )
    with pytest.raises(ValueError, match="25.00"):
        apply_event(state, Event("e3", "propose", amount=26))


def test_full_happy_path_lifecycle():
    events = [
        Event("e1", "open", note="Late package delivery"),
        Event("e2", "classify", reason="shipping"),
        Event("e3", "propose", amount=35.0),
        Event("e4", "approve"),
        Event("e5", "execute"),
    ]
    state = project(events)
    assert state.status == "executed"
    assert state.reason == "shipping"
    assert state.amount == 35.0
    assert state.history == ["open", "classify", "propose", "approve", "execute"]


def test_rejection_branch():
    events = [
        Event("e1", "open", note="Damaged box"),
        Event("e2", "classify", reason="goodwill"),
        Event("e3", "propose", amount=15.0),
        Event("e4", "reject"),
    ]
    state = project(events)
    assert state.status == "rejected"
    with pytest.raises(ValueError, match="Cannot apply 'execute'"):
        apply_event(state, Event("e5", "execute"))


def test_shipping_cap_enforcement():
    base = [
        Event("e1", "open", note="Shipping issue"),
        Event("e2", "classify", reason="shipping"),
    ]
    # 40.0 is allowable
    state_valid = project(base + [Event("e3", "propose", amount=40.0)])
    assert state_valid.status == "proposed"
    assert state_valid.amount == 40.0

    # 40.01 exceeds cap of 40.00
    with pytest.raises(ValueError, match="40.00"):
        apply_event(project(base), Event("e4", "propose", amount=40.01))


def test_cannot_propose_zero_or_negative_amount():
    base = [
        Event("e1", "open", note="Duplicate fee"),
        Event("e2", "classify", reason="duplicate_charge"),
    ]
    with pytest.raises(ValueError, match="must be positive"):
        apply_event(project(base), Event("e3", "propose", amount=0))
    with pytest.raises(ValueError, match="must be positive"):
        apply_event(project(base), Event("e3", "propose", amount=-10))


def test_store_commit_and_list_events(tmp_path):
    from app.store import connect, commit, list_events, snapshot
    conn = connect(tmp_path / "cases.db")
    case_id = "test-case-100"

    commit(conn, case_id, Event("ev-1", "open", note="Initial intake"))
    commit(conn, case_id, Event("ev-2", "classify", reason="goodwill"))
    commit(conn, case_id, Event("ev-3", "propose", amount=20.0))

    events = list_events(conn, case_id)
    assert len(events) == 3
    assert events[0]["event_type"] == "open"
    assert events[1]["reason"] == "goodwill"
    assert events[2]["amount"] == 20.0

    # Idempotent re-commit
    commit(conn, case_id, Event("ev-3", "propose", amount=20.0))
    events_re = list_events(conn, case_id)
    assert len(events_re) == 3  # not duplicated
    
    state = snapshot(conn, case_id)
    assert state.status == "proposed"
    assert state.amount == 20.0
    conn.close()

