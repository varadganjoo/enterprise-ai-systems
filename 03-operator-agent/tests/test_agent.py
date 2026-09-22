from app.agent import Action, dispatch, run_agent
from app.store import connect, decide_approval, get_ticket, pending_approvals


def _finish(goal, trace):
    return Action(tool="finish", final_answer="done"), 10, 5


def test_propose_send_does_not_mark_the_ticket_replied(tmp_path):
    conn = connect(tmp_path / "ops.db")
    result = dispatch(
        Action(tool="propose_send", ticket_id=1, body="We are reviewing the duplicate charge."),
        conn,
    )
    assert "not sent" in result
    assert get_ticket(conn, 1)["status"] == "open"
    pending = pending_approvals(conn)
    assert len(pending) == 1
    stored = pending[0]["body"]
    decided = decide_approval(conn, pending[0]["id"], "approve")
    assert decided["reply"] == stored
    assert get_ticket(conn, 1)["reply"] == stored
    assert get_ticket(conn, 1)["status"] == "replied"
    conn.close()


def test_second_approval_is_rejected(tmp_path):
    conn = connect(tmp_path / "ops.db")
    dispatch(Action(tool="propose_send", ticket_id=2, body="Try the hardware key."), conn)
    approval_id = pending_approvals(conn)[0]["id"]
    decide_approval(conn, approval_id, "reject")
    try:
        decide_approval(conn, approval_id, "approve")
        raised = False
    except ValueError:
        raised = True
    assert raised
    assert get_ticket(conn, 2)["status"] == "open"
    conn.close()


def test_unknown_tool_is_not_run(tmp_path):
    conn = connect(tmp_path / "ops.db")
    action = Action(tool="list_open_tickets")
    action.tool = "delete_database"
    result = dispatch(action, conn)
    assert "not allowed" in result
    assert get_ticket(conn, 1)["status"] == "open"
    conn.close()


def test_step_cap_stops_the_loop(tmp_path):
    conn = connect(tmp_path / "ops.db")

    def always_list(goal, trace):
        return Action(tool="list_open_tickets"), 3, 1

    result = run_agent(conn, "List tickets forever", always_list, step_cap=2, token_cap=1000)
    assert result.stopped_reason == "step_cap"
    assert len(result.trace) == 2
    assert pending_approvals(conn) == []
    conn.close()


def test_a_completed_refund_claim_is_blocked_before_it_is_queued(tmp_path):
    conn = connect(tmp_path / "ops.db")
    result = dispatch(
        Action(tool="propose_send", ticket_id=1, body="We have processed a refund for the duplicate charge."),
        conn,
    )
    assert "POLICY_BLOCK" in result
    assert pending_approvals(conn) == []
    assert get_ticket(conn, 1)["status"] == "open"
    conn.close()


def test_the_same_pending_message_is_not_queued_twice(tmp_path):
    conn = connect(tmp_path / "ops.db")
    body = "We are reviewing the duplicate charge and will write back."
    first = dispatch(Action(tool="propose_send", ticket_id=1, body=body), conn)
    second = dispatch(Action(tool="propose_send", ticket_id=1, body=body), conn)
    assert "Queued approval" in first
    assert "already pending" in second
    assert len(pending_approvals(conn)) == 1
    conn.close()


def test_finish_ends_without_a_side_effect(tmp_path):
    conn = connect(tmp_path / "ops.db")
    result = run_agent(conn, "Stop", _finish)
    assert result.stopped_reason == "finish"
    assert result.trace == []
    assert get_ticket(conn, 3)["status"] == "open"
    conn.close()


def test_pii_guardrails_block_ssn_and_credit_card(tmp_path):
    conn = connect(tmp_path / "ops.db")
    ssn_result = dispatch(
        Action(tool="propose_send", ticket_id=1, body="Your SSN is 123-45-6789 for verification."),
        conn,
    )
    assert "POLICY_BLOCK" in ssn_result
    assert "PII" in ssn_result

    cc_result = dispatch(
        Action(tool="propose_send", ticket_id=1, body="Refunding to card 4111 2222 3333 4444 now."),
        conn,
    )
    assert "POLICY_BLOCK" in cc_result
    assert pending_approvals(conn) == []
    conn.close()


def test_credential_guardrails_block_api_keys_and_passwords(tmp_path):
    conn = connect(tmp_path / "ops.db")
    key_result = dispatch(
        Action(tool="propose_send", ticket_id=1, body="Use key sk-abcdef1234567890abcdef1234567890 for API access."),
        conn,
    )
    assert "POLICY_BLOCK" in key_result
    assert "credentials" in key_result

    pwd_result = dispatch(
        Action(tool="propose_send", ticket_id=1, body="Temporary password: SecretPassword123!"),
        conn,
    )
    assert "POLICY_BLOCK" in pwd_result
    assert pending_approvals(conn) == []
    conn.close()


def test_abusive_language_guardrail_blocks_hostility(tmp_path):
    conn = connect(tmp_path / "ops.db")
    abusive_result = dispatch(
        Action(tool="propose_send", ticket_id=1, body="You are an idiot and should stop calling us."),
        conn,
    )
    assert "POLICY_BLOCK" in abusive_result
    assert "abusive" in abusive_result or "hostile" in abusive_result
    assert pending_approvals(conn) == []
    conn.close()


def test_explicit_approve_send_marks_message_sent_and_ticket_replied(tmp_path):
    from app.store import approve_send
    conn = connect(tmp_path / "ops.db")
    dispatch(Action(tool="propose_send", ticket_id=1, body="We are looking into the duplicate charge."), conn)
    pending = pending_approvals(conn)
    assert len(pending) == 1
    
    result = approve_send(conn, pending[0]["id"])
    assert result["status"] == "sent"
    assert get_ticket(conn, 1)["status"] == "replied"
    assert get_ticket(conn, 1)["reply"] == "We are looking into the duplicate charge."
    assert pending_approvals(conn) == []
    conn.close()


def test_supervisor_edit_approval_draft(tmp_path):
    from app.store import edit_approval, approve_send
    conn = connect(tmp_path / "ops.db")
    dispatch(Action(tool="propose_send", ticket_id=1, body="Initial draft text."), conn)
    pending = pending_approvals(conn)
    approval_id = pending[0]["id"]

    # Supervisor edits draft
    edited = edit_approval(conn, approval_id, "Polished supervisor approved response.")
    assert edited["body"] == "Polished supervisor approved response."

    # Supervisor approves
    result = approve_send(conn, approval_id)
    assert result["reply"] == "Polished supervisor approved response."
    conn.close()


def test_trace_telemetry_includes_inputs_outputs_and_token_consumption(tmp_path):
    conn = connect(tmp_path / "ops.db")

    def mock_agent_step(goal, trace):
        if not trace:
            return Action(tool="get_ticket", ticket_id=1), 50, 20
        return Action(tool="finish", final_answer="Reviewed ticket"), 30, 15

    result = run_agent(conn, "Inspect ticket 1", mock_agent_step, step_cap=3)
    assert len(result.trace) == 1
    step = result.trace[0]
    assert step["step"] == 1
    assert step["tool"] == "get_ticket"
    assert step["inputs"]["ticket_id"] == 1
    assert "Ada North" in step["output"]
    assert step["prompt_tokens"] == 50
    assert step["output_tokens"] == 20
    assert step["cumulative_tokens"] == 70
    conn.close()
