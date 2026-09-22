from pathlib import Path

from app.hops import bind_hop, compose, load_passages

ROOT = Path(__file__).resolve().parents[1]


def test_a_missing_required_hop_blocks_the_number():
    passages = load_passages(ROOT / "data" / "passages")
    rate = bind_hop(
        "What is the monthly rate?",
        True,
        "The monthly rate is $400.",
        "The monthly rate is $400.",
        "schedule",
        passages,
    )
    months = bind_hop(
        "How many months remain?",
        True,
        "Two months remain.",
        "this quote is not in the contract",
        "contract",
        passages,
    )
    brief = compose([rate, months], "The fee is $800.")
    assert brief.refused
    assert brief.answer == ""
    assert "How many months remain?" in brief.reason


def test_both_supported_hops_allow_the_synthesis():
    passages = load_passages(ROOT / "data" / "passages")
    rate = bind_hop(
        "What is the monthly rate?",
        True,
        "$400",
        "The monthly rate is $400.",
        "schedule",
        passages,
    )
    months = bind_hop(
        "How many months remain at the start of month 5?",
        True,
        "two months",
        "two months remaining in the quarter",
        "contract",
        passages,
    )
    brief = compose([months, rate], "The cancellation fee is $800.")
    assert not brief.refused
    assert brief.answer == "The cancellation fee is $800."
    assert all(hop.supported for hop in brief.hops)


def test_dag_dependent_hop_is_gated_when_parent_lacks_citation():
    passages = load_passages(ROOT / "data" / "passages")
    # hop_1 is missing citation
    hop1 = bind_hop(
        "What is the starting condition?",
        True,
        "Condition A",
        "missing citation quote",
        "contract",
        passages,
        hop_id="hop_1",
    )
    # hop_2 depends on hop_1
    hop2 = bind_hop(
        "What is the dependent rate?",
        True,
        "$400",
        "The monthly rate is $400.",
        "schedule",
        passages,
        hop_id="hop_2",
        depends_on=["hop_1"],
    )

    brief = compose([hop1, hop2], "Final calculation")
    assert brief.refused
    assert brief.answer == ""

    # hop1 is Missing Citation, hop2 is Gated
    by_id = {h.hop_id: h for h in brief.hops}
    assert by_id["hop_1"].status == "Missing Citation"
    assert by_id["hop_2"].status == "Gated"
    assert by_id["hop_2"].answer == ""  # strictly withheld


def test_dag_graph_structure_and_offsets():
    passages = load_passages(ROOT / "data" / "passages")
    rate = bind_hop(
        "What is the monthly rate?",
        True,
        "$400",
        "The monthly rate is $400.",
        "schedule",
        passages,
        hop_id="hop_rate",
    )
    months = bind_hop(
        "How many months remain at the start of month 5?",
        True,
        "two months",
        "two months remaining in the quarter",
        "contract",
        passages,
        hop_id="hop_months",
    )
    brief = compose([rate, months], "The cancellation fee is $800.")
    assert not brief.refused
    assert brief.graph is not None
    assert "nodes" in brief.graph
    assert "edges" in brief.graph

    node_ids = {n["id"] for n in brief.graph["nodes"]}
    assert "hop_rate" in node_ids
    assert "hop_months" in node_ids
    assert "synthesis" in node_ids

    # Check offsets
    assert rate.start_char > 0
    assert rate.end_char > rate.start_char
    sched_passage = next(p for p in passages if p.chunk_id == "schedule")
    assert sched_passage.text[rate.start_char:rate.end_char] == rate.quote
