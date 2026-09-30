from merval_agent.domain.models import (
    AgentState,
    AssetResolution,
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
    state.observations.append(result)
