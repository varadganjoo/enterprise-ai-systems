from app.memory import (
    MemoryOp,
    apply_op,
    connect,
    contains_sensitive,
    list_memories,
    new_session,
)
from app.service import PIITokenizer, get_active_memory_context


def test_correction_supersedes_the_old_fact(tmp_path):
    conn = connect(tmp_path / "mem.db")
    session_id = new_session()
    first = apply_op(conn, session_id, MemoryOp(op="add", kind="preference", content="Prefers aisle seats."))
    assert first.stored
    active = list_memories(conn, session_id, active_only=True)
    second = apply_op(
        conn,
        session_id,
        MemoryOp(op="correct", kind="preference", content="Prefers window seats.", target_id=active[0]["id"]),
    )
    assert second.stored
    active = list_memories(conn, session_id, active_only=True)
    history = [row for row in list_memories(conn, session_id) if row["status"] != "active"]
    assert len(active) == 1
    assert active[0]["content"] == "Prefers window seats."
    assert history[0]["status"] == "superseded"
    assert history[0]["superseded_at"] is not None
    assert "aisle" not in active[0]["content"]
    conn.close()


def test_forget_removes_the_fact_from_recall(tmp_path):
    conn = connect(tmp_path / "mem.db")
    session_id = new_session()
    apply_op(conn, session_id, MemoryOp(op="add", kind="preference", content="Prefers aisle seats."))
    apply_op(conn, session_id, MemoryOp(op="forget", content="aisle"))
    assert list_memories(conn, session_id, active_only=True) == []
    history = [row for row in list_memories(conn, session_id) if row["status"] == "forgotten"]
    assert len(history) == 1
    assert history[0]["superseded_at"] is not None
    conn.close()


def test_sensitive_text_is_not_stored(tmp_path):
    conn = connect(tmp_path / "mem.db")
    session_id = new_session()
    message = "My social security number is 123-45-6789."
    assert contains_sensitive(message)
    result = apply_op(
        conn,
        session_id,
        MemoryOp(op="add", kind="preference", content=message),
    )
    assert result.stored is False
    assert result.op == "reject_sensitive"
    dumped = " ".join(row["content"] for row in list_memories(conn, session_id))
    assert "123-45-6789" not in dumped
    conn.close()


def test_ambiguous_correction_does_not_guess(tmp_path):
    conn = connect(tmp_path / "mem.db")
    session_id = new_session()
    apply_op(conn, session_id, MemoryOp(op="add", kind="preference", content="Prefers aisle seats."))
    apply_op(conn, session_id, MemoryOp(op="add", kind="preference", content="Vegetarian meals."))
    result = apply_op(
        conn,
        session_id,
        MemoryOp(op="correct", kind="preference", content="Prefers window seats.", target_id=0),
    )
    assert result.stored is False
    assert len(list_memories(conn, session_id, active_only=True)) == 2
    conn.close()


def test_a_new_value_in_the_same_slot_replaces_the_old_one(tmp_path):
    conn = connect(tmp_path / "mem.db")
    session_id = new_session()
    apply_op(
        conn,
        session_id,
        MemoryOp(op="add", kind="preference", slot="seat_preference", content="Prefers aisle seats."),
    )
    replaced = apply_op(
        conn,
        session_id,
        MemoryOp(op="add", kind="preference", slot="seat_preference", content="Prefers window seats."),
    )
    assert replaced.op == "correct"
    active = list_memories(conn, session_id, active_only=True)
    history = [row for row in list_memories(conn, session_id) if row["status"] == "superseded"]
    assert len(active) == 1
    assert active[0]["content"] == "Prefers window seats."
    assert history[0]["content"] == "Prefers aisle seats."
    assert history[0]["superseded_at"] is not None
    assert active[0]["supersedes_id"] == history[0]["id"]
    conn.close()


def test_duplicate_add_is_idempotent(tmp_path):
    conn = connect(tmp_path / "mem.db")
    session_id = new_session()
    apply_op(conn, session_id, MemoryOp(op="add", kind="decision", content="Ship on Friday."))
    again = apply_op(conn, session_id, MemoryOp(op="add", kind="decision", content="ship on friday."))
    assert again.stored is False
    assert len(list_memories(conn, session_id, active_only=True)) == 1
    conn.close()


def test_pii_tokenizer_mask_and_rehydrate():
    raw_message = (
        "Contact me at user@enterprise.com or call 415-555-0199. "
        "My SSN is 000-12-3456 and my card is 4111-2222-3333-4444."
    )
    res = PIITokenizer.tokenize(raw_message)

    # All sensitive values masked
    assert "user@enterprise.com" not in res.redacted_text
    assert "415-555-0199" not in res.redacted_text
    assert "000-12-3456" not in res.redacted_text
    assert "4111-2222-3333-4444" not in res.redacted_text

    # Tokens present
    assert "[EMAIL_1]" in res.redacted_text
    assert "[PHONE_1]" in res.redacted_text
    assert "[SSN_1]" in res.redacted_text
    assert "[CREDIT_CARD_1]" in res.redacted_text

    # Rehydrate
    rehydrated = PIITokenizer.rehydrate(res.redacted_text, res.vault)
    assert rehydrated == raw_message


def test_slot_supersession_timeline_and_lineage(tmp_path):
    conn = connect(tmp_path / "mem.db")
    session_id = new_session()

    # Slot 1: user_location
    apply_op(conn, session_id, MemoryOp(op="add", slot="user_location", content="San Francisco"))
    # Slot 1 updated:
    apply_op(conn, session_id, MemoryOp(op="add", slot="user_location", content="New York"))
    # Slot 1 updated again:
    apply_op(conn, session_id, MemoryOp(op="add", slot="user_location", content="London"))

    active = list_memories(conn, session_id, active_only=True)
    all_mems = list_memories(conn, session_id)

    assert len(active) == 1
    assert active[0]["content"] == "London"
    assert len(all_mems) == 3

    # Check supersession chain
    superseded = [m for m in all_mems if m["status"] == "superseded"]
    assert len(superseded) == 2
    for s in superseded:
        assert s["superseded_at"] is not None

    conn.close()


def test_active_memory_context_endpoint_pii_protection(tmp_path):
    conn = connect(tmp_path / "mem.db")
    session_id = new_session()

    apply_op(
        conn,
        session_id,
        MemoryOp(op="add", slot="contact_email", content="admin@company.com"),
    )
    apply_op(
        conn,
        session_id,
        MemoryOp(op="add", slot="emergency_phone", content="415-555-9876"),
    )

    # Retrieve with PII protection
    ctx = get_active_memory_context(conn, session_id, redact_pii=True)
    assert ctx["pii_protected"] is True
    assert "admin@company.com" not in ctx["context"]
    assert "415-555-9876" not in ctx["context"]
    assert "[EMAIL_1]" in ctx["context"]
    assert "[PHONE_1]" in ctx["context"]

    # Retrieve without PII protection
    ctx_raw = get_active_memory_context(conn, session_id, redact_pii=False)
    assert "admin@company.com" in ctx_raw["context"]
    assert "415-555-9876" in ctx_raw["context"]

    conn.close()
