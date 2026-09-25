from merval_agent.domain.models import (
    AgentState,
    AssetResolution,
    Evidence,
    FinancialDocument,
    MarketHistory,
    TechnicalMetrics,
    ToolResult,
)


def reduce_observation(state: AgentState, result: ToolResult) -> None:
    if not result.success:
        state.observations.append(result)
        if result.error:
            state.errors.append(result.error)
        return
    if result.tool_name == "resolve_asset":
        asset = AssetResolution.model_validate(result.data)
        if state.resolved_asset and state.resolved_asset.ticker != asset.ticker:
            state.technical_data = None
            state.technical_metrics = None
            state.technical_assessment = None
            state.financial_data = []
            state.methodology_evidence = []
        if asset.status != "RESOLVED":
            state.asset_validation_quote = None
            state.asset_validation_quote_attempted = False
        state.resolved_asset = asset
    elif result.tool_name == "get_market_history":
        state.technical_data = MarketHistory.model_validate(result.data)
        state.technical_metrics = None
        state.technical_assessment = None
    elif result.tool_name == "calculate_technical_indicators":
        state.technical_metrics = TechnicalMetrics.model_validate(result.data)
    elif result.tool_name == "list_financial_documents":
        state.financial_data = [
            FinancialDocument.model_validate(d) for d in result.data["documents"]
        ]
    elif result.tool_name == "get_latest_financial_statement":
        doc = result.data["document"]
        state.financial_data = [FinancialDocument.model_validate(doc)] if doc else []
    elif result.tool_name == "search_methodology":
        state.methodology_evidence.extend(
            [Evidence.model_validate(e) for e in result.data["evidence"]]
        )
    state.observations.append(result)
