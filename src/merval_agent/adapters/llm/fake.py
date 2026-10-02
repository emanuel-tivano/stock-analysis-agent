import re
from collections.abc import Callable

from merval_agent.agents.intent import explicit_analysis_type, explicit_full_request
from merval_agent.domain.models import TICKER_PATTERN, AgentDecision, AgentState, UserIntent
from merval_agent.domain.policy import DEFAULT_TECHNICAL_RANGE
from merval_agent.tools.assets import folded, symbol_candidates


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
        kind = (
            "full" if technical and fundamental else "fundamental" if fundamental else "technical"
        )
        intent = UserIntent(analysis_type=kind)
        if not state.observations:
            if fundamental or explicit_full_request(text):
                return AgentDecision(
                    action="ABSTAIN",
                    confidence=1,
                    reason="El MVP sólo ofrece análisis técnico; el análisis fundamental está fuera de alcance.",
                    intent=intent,
                )
            relevant = (
                bool(re.fullmatch(TICKER_PATTERN, state.user_request.strip()))
                or technical
                or fundamental
                or any(word in text for word in ("analiz", "analisis", "accion", "byma", "merval"))
                or bool(re.search(r"\b(grupo|banco|energia|financiero|sociedad)\b", text))
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
            candidates = [
                value
                for value in symbol_candidates(state.user_request)
                if re.fullmatch(r"[A-Z][A-Z0-9]{1,4}", value)
            ]
            # Repeated-letter placeholders stay an offline negative case for the simulator.
            candidates = [value for value in candidates if len(set(value)) > 1]
            if "BYMA" in candidates and len(candidates) > 1:
                candidates = [value for value in candidates if value != "BYMA"]
            proposal = {}
            if len(candidates) == 1:
                proposal.update(symbol=candidates[-1], market="bCBA")
            return call("resolve_asset", **proposal)
        if state.resolved_asset is None or state.resolved_asset.ticker is None:
            return AgentDecision(
                action="CLARIFY",
                reason="Indicá un ticker de acción BYMA inequívoco (por ejemplo GGAL); confirmá instrumento y mercado.",
                confidence=0.5,
            )
        ticker = state.resolved_asset.ticker
        attempted = {c.name for c in state.tool_calls}
        if "get_market_history" not in attempted:
            return call("get_market_history", ticker=ticker, range=DEFAULT_TECHNICAL_RANGE)
        if state.technical_data and "calculate_technical_indicators" not in attempted:
            return call("calculate_technical_indicators", ticker=ticker)
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
