"""Offline contracts and scripted evals, not evidence of real model compliance."""

import hashlib
import json

import httpx
import pytest

from merval_agent.adapters.llm.context import PROMPT_VERSIONS, get_system_instructions
from merval_agent.bootstrap import build_provider
from merval_agent.config import Settings
from merval_agent.domain.errors import ExternalServiceError
from merval_agent.domain.models import AgentDecision, AgentState, FinancialDocument
from merval_agent.evaluation import evaluate, load_cases, score_case


def decision(action="ABSTAIN", **kwargs):
    return dict(action=action, reason="Evidence check", confidence=1, **kwargs)


def call(name, **args):
    return decision("CALL_TOOL", tool_name=name, tool_args=args)


@pytest.fixture
def scripted_provider():
    clients = []

    def factory(outputs, version="phase2a-v2", provider="compatible"):
        requests = []

        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            content = json.dumps(outputs[len(requests) - 1])
            payload = (
                {"choices": [{"message": {"content": content}}]}
                if provider == "compatible"
                else {
                    "candidates": [
                        {"finishReason": "STOP", "content": {"parts": [{"text": content}]}}
                    ]
                }
            )
            return httpx.Response(200, json=payload)

        http = httpx.Client(transport=httpx.MockTransport(handler))
        clients.append(http)
        settings = Settings(
            _env_file=None,
            llm_provider=provider,
            llm_model="offline",
            llm_base_url="https://llm.test/v1",
            llm_api_key="private",
            agent_prompt_version=version,
        )
        return build_provider(settings, http), requests

    yield factory
    for client in clients:
        client.close()


def test_historical_v1_is_frozen():
    assert hashlib.sha256(get_system_instructions("phase2a-v1").encode()).hexdigest() == (
        "5502d0e2a82374e7142a5bcb99c7cc8c1d08e3df680c48b06b439131e12560b9"
    )
    assert get_system_instructions("phase2a-v2") != get_system_instructions("phase2a-v1")
    with pytest.raises(ValueError, match="Unsupported"):
        get_system_instructions("unknown")


@pytest.mark.parametrize("version", list(PROMPT_VERSIONS))
@pytest.mark.parametrize("provider", ["compatible", "gemini"])
def test_selected_text_and_trace_match_metadata(scripted_provider, version, provider):
    real, requests = scripted_provider([decision()], version, provider)
    events = []
    real.decide_validated(
        AgentState(user_request="GGAL"),
        [],
        lambda d: None,
        lambda event, **fields: events.append(dict(event=event, **fields)),
    )
    body = requests[0]
    system = (
        body["messages"][0]["content"]
        if provider == "compatible"
        else body["systemInstruction"]["parts"][0]["text"]
    )
    assert system == get_system_instructions(version) + "\nSchema:\n" + json.dumps(
        AgentDecision.model_json_schema()
    )
    assert all(e["prompt_version"] == version for e in events)


def technical_steps():
    return [
        call("resolve_asset", query="GGAL"),
        call("get_market_history", ticker="GGAL", range="6M"),
        call("calculate_technical_indicators", ticker="GGAL"),
    ]


def test_calculations_without_methodology_support_technical_signals(scripted_provider, make_agent):
    real, requests = scripted_provider(technical_steps() + [decision("FINAL_ANSWER")])
    agent, repo = make_agent(provider=real)
    case = load_cases()[0]
    result = agent.run(case["input"])
    context = json.loads(requests[-1]["messages"][1]["content"])
    assert context["technical_metrics"]["sma20"] is not None
    assert context["methodology"] == []
    assert result.technical.status == "BULLISH"
    assert result.technical.assessment.status == "COMPLETE"
    row = score_case(case, repo.records[0][0], result, 0)
    assert row["result"] == "PASS"
    assert row["tools_correct"] is True
    # No deterministic routing or automatic search was introduced.
    assert [c.name for c in repo.records[0][0].tool_calls] == [
        "resolve_asset",
        "get_market_history",
        "calculate_technical_indicators",
    ]


@pytest.mark.parametrize("early", [True, False])
@pytest.mark.parametrize("retrieval", ["demo", "empty", "failure"])
def test_methodology_choice_order_and_safe_abstention(
    scripted_provider, make_agent, monkeypatch, early, retrieval
):
    if retrieval != "demo":

        def search(*args, **kwargs):
            if retrieval == "failure":
                raise ExternalServiceError("unavailable")
            return []

        monkeypatch.setattr("merval_agent.retrieval.local.LocalMethodologyRetriever.search", search)
    steps = technical_steps()
    steps.insert(1 if early else 3, call("search_methodology", query="trend", source="murphy"))
    real, requests = scripted_provider(steps + [decision()])
    agent, repo = make_agent(provider=real)
    case = next(c for c in load_cases() if c["id"] == "murphy_demo")
    result = agent.run(case["input"])
    state = repo.records[0][0]
    assert [c.name for c in state.tool_calls] == [d["tool_name"] for d in steps]
    assert result.status == ("ERROR" if retrieval == "failure" else "ABSTAIN")
    assert result.technical.status == "INSUFFICIENT_DATA"
    assert result.fundamental.status == "NOT_REQUESTED"
    # This fixture expects a successful DEMO retrieval; an injected outage is
    # a technical failure, not a valid evidence abstention for that fixture.
    assert score_case(case, state, result, 0)["result"] == (
        "FAIL" if retrieval == "failure" else "PASS"
    )
    assert all(
        c.name not in {"get_latest_financial_statement", "list_financial_documents"}
        for c in state.tool_calls
    )
    if retrieval == "failure":
        assert any(e["event"] == "TOOL_FAILED" for e in state.trace_events)
    if not early:
        before_search = json.loads(requests[3]["messages"][1]["content"])
        assert before_search["technical_metrics"] and not before_search["methodology"]


def test_fundamental_only_metadata_cannot_become_metrics(
    scripted_provider, make_agent, monkeypatch
):
    document = FinancialDocument(
        ticker="PAMP",
        issuer="Pampa",
        published_at="2026-08-20",
        reference="Statement",
        document_id="offline-doc",
        source_url="https://bolsar.test/document",
        document_type="FINANCIAL_STATEMENT",
    )
    monkeypatch.setattr(
        "merval_agent.adapters.bolsar.BolsarClient.find_latest_financial_statement",
        lambda *args: document,
    )
    outputs = [
        call("resolve_asset", query="PAMP"),
        call("search_methodology", query="fundamentals", source="graham"),
        call("get_latest_financial_statement", ticker="PAMP"),
        decision(),
    ]
    real, _ = scripted_provider(outputs)
    agent, repo = make_agent(provider=real)
    result = agent.run("Analizá los fundamentos de PAMP")
    assert result.status == "ABSTAIN"
    assert result.fundamental.metrics is None
    assert repo.records[0][0].financial_data == [document]
    assert result.fundamental.status == "INSUFFICIENT_DATA"
    assert result.technical.status == "NOT_REQUESTED"
    assert [c.name for c in repo.records[0][0].tool_calls] == [
        "resolve_asset",
        "search_methodology",
        "get_latest_financial_statement",
    ]


def test_fake_dataset_metrics_unchanged_across_versions(monkeypatch, tmp_path):
    monkeypatch.setattr("merval_agent.evaluation.perf_counter", lambda: 0)
    reports = [
        evaluate(
            Settings(_env_file=None, agent_prompt_version=v), fake=True, output_dir=tmp_path / v
        )[0]
        for v in PROMPT_VERSIONS
    ]
    assert reports[0]["metrics"] == reports[1]["metrics"]
    assert reports[0]["metrics"]["case_count"] == 17
    assert reports[0]["metrics"]["passed_cases"] == 17
    assert all(r["system_instructions_sha256"] is None for r in reports)


def test_eval_prompt_identity_and_cli_override(monkeypatch, tmp_path):
    import runpy
    from pathlib import Path

    client_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(lambda r: pytest.fail("Empty eval must not request LLM")),
            trust_env=False,
            **kwargs,
        ),
    )
    reports = []
    for version in PROMPT_VERSIONS:
        report, path = evaluate(
            Settings(
                _env_file=None,
                llm_provider="compatible",
                llm_base_url="https://llm.test",
                llm_model="offline",
                llm_api_key="private",
                agent_prompt_version=version,
            ),
            cases=[],
            output_dir=tmp_path,
        )
        assert version in path.name
        assert report["prompt_version"] == version
        reports.append(report)
    assert reports[0]["system_instructions_sha256"] != reports[1]["system_instructions_sha256"]
    assert reports[0]["evaluator_version"] == reports[1]["evaluator_version"]
    assert reports[0]["dataset_version"] == reports[1]["dataset_version"]

    def fake_eval(settings, **kwargs):
        assert settings.agent_prompt_version == "phase2a-v2"
        return {"metrics": {"failed_cases": 0}, "cases": []}, tmp_path / "report.json"

    monkeypatch.setattr("merval_agent.evaluation.evaluate", fake_eval)
    monkeypatch.setenv("AGENT_PROMPT_VERSION", "phase2a-v1")
    monkeypatch.setattr(
        "sys.argv", ["eval_real_llm.py", "--fake", "--prompt-version", "phase2a-v2"]
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(
            str(Path(__file__).parents[2] / "scripts/eval_real_llm.py"), run_name="__main__"
        )
    assert exc.value.code == 2
