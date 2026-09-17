import re
from collections.abc import Callable

from merval_agent.adapters.bolsar_parser import folded
from merval_agent.agents.intent import explicit_analysis_type, explicit_full_request
from merval_agent.domain.models import AgentDecision, AgentState, UserIntent
from merval_agent.domain.policy import DEFAULT_TECHNICAL_RANGE
from merval_agent.tools.assets import CATALOG


class FakeLLMProvider:
    """Deterministic simulator; injected scripts enable arbitrary/reordered decisions in tests."""

    def __init__(self, script: Callable | None = None):
        self.script = script

    def decide(self, state: AgentState, tools: list[dict]) -> AgentDecision | dict:
        if self.script:
            return self.script(state)
        text = folded(state.user_request)
        technical = explicit_analysis_type(text) == "technical" or any(
            w in text for w in ("tecnic", "technic", "tendencia", "murphy")
        )
        fundamental = any(w in text for w in ("fundament", "graham", "solida"))
        kind = "full" if technical == fundamental else "technical" if technical else "fundamental"
        intent = UserIntent(
            analysis_type=kind, methodology=[s for s in ("murphy", "graham") if s in text]
        )
        if not state.observations:
            if explicit_full_request(text) and kind == "full":
                return AgentDecision(
                    action="ABSTAIN",
                    confidence=1,
                    reason="El análisis integral requiere métricas fundamentales aún no implementadas; solicitá un análisis técnico.",
                )
            catalog_terms = {
                term
                for ticker, (_, _, aliases) in CATALOG.items()
                for term in (ticker.lower(), *aliases)
            }
            relevant = (
                bool(re.fullmatch(r"[A-Z]{2,5}", state.user_request.strip()))
                or technical
                or fundamental
                or any(word in text for word in ("analiz", "analisis", "accion", "byma", "merval"))
                or bool(set(re.findall(r"[a-z]+", text)) & catalog_terms)
            )
            if not relevant:
                return AgentDecision(
                    action="ABSTAIN", reason="Pedido fuera del análisis de acciones.", confidence=1
                )
            if technical and "balance" in text:
                return AgentDecision(
                    action="CLARIFY",
                    reason="Confirmá análisis técnico de precios o análisis de balances.",
                    confidence=1,
                )

        def call(name, **args):
            return AgentDecision(
                action="CALL_TOOL",
                tool_name=name,
                tool_args=args,
                reason="Simulated decision from current observations",
                confidence=1,
                intent=intent,
            )

        if not state.observations:
            return call("resolve_asset", query=state.user_request)
        if state.resolved_asset is None or state.resolved_asset.ticker is None:
            return AgentDecision(
                action="CLARIFY",
                reason="Indicá un ticker de acción BYMA inequívoco (por ejemplo GGAL); confirmá instrumento y mercado.",
                confidence=0.5,
            )
        ticker = state.resolved_asset.ticker
        attempted = {c.name for c in state.tool_calls}
        if kind != "fundamental" and "get_market_history" not in attempted:
            return call("get_market_history", ticker=ticker, range=DEFAULT_TECHNICAL_RANGE)
        if (
            kind != "fundamental"
            and state.technical_data
            and "calculate_technical_indicators" not in attempted
        ):
            return call("calculate_technical_indicators", ticker=ticker)
        if kind != "technical" and "get_latest_financial_statement" not in attempted:
            return call("get_latest_financial_statement", ticker=ticker)
        searched = {
            c.arguments.get("source") for c in state.tool_calls if c.name == "search_methodology"
        }
        for source in (
            (["murphy"] if "murphy" in intent.methodology else [])
            if kind == "technical"
            else ["graham"]
            if kind == "fundamental"
            else ["murphy", "graham"]
        ):
            if source not in searched:
                return call("search_methodology", query=state.user_request, source=source)
        if not state.technical_assessment or state.technical_assessment.status not in (
            "COMPLETE",
            "PARTIAL",
        ):
            return AgentDecision(
                action="ABSTAIN",
                reason="No hay evidencia cuantitativa suficiente para responder esta dimensión.",
                missing_information=["Métricas verificables suficientes"],
                confidence=1,
            )
        return AgentDecision(
            action="FINAL_ANSWER",
            reason="Evaluación técnica determinista completada.",
            confidence=1,
            interpretation="",
        )
