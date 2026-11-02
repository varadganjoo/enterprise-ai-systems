"""Exercise the actual endpoint without paid model calls."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from app import main


@pytest.mark.parametrize('missing', [False, True])
def test_endpoint_synthesizes_only_after_verified_hops(monkeypatch, missing):
    calls = []
    monkeypatch.setattr(main, 'get_client', lambda: object())

    def generate(client, *, schema, **kwargs):
        calls.append(schema)
        if schema is main.Plan:
            value = main.Plan(hops=[main.PlannedHop(id='rate', question='Monthly rate?')])
        elif schema is main.HopAnswer:
            value = main.HopAnswer(answer='$400', chunk_id='schedule',
                                   quote='invented quote' if missing else 'The monthly rate is $400.')
        else:
            value = main.Synthesis(answer='The monthly rate is $400.')
        return value, SimpleNamespace(prompt_tokens=10, output_tokens=5)

    monkeypatch.setattr(main, 'generate_model', generate)
    with TestClient(main.app) as client:
        response = client.post('/brief', json={'question': 'What is the monthly rate?'})
    assert response.status_code == 200
    assert response.json()['refused'] is missing
    assert (main.Synthesis in calls) is not missing
    assert bool(response.json()['answer']) is not missing


def test_plan_orders_prerequisites_before_dependents():
    plan = main.Plan(hops=[main.PlannedHop(id='b', question='B?', depends_on=['a']),
                           main.PlannedHop(id='a', question='A?')])
    assert [hop.id for hop in plan.hops] == ['a', 'b']


@pytest.mark.parametrize('hops', [
    [],
    [main.PlannedHop(id='a', question='A?', depends_on=['missing'])],
    [main.PlannedHop(id='a', question='A?', depends_on=['a'])],
    [main.PlannedHop(id='a', question='A?'), main.PlannedHop(id='a', question='B?')],
    [main.PlannedHop(id='a', question='A?', required=False)],
])
def test_plan_rejects_invalid_dependency_graphs(hops):
    with pytest.raises(ValueError):
        main.Plan(hops=hops)
