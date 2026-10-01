from datetime import datetime

from merval_agent.agents.decisions import (
    explicit_methodology_requested,
    resolve_effective_terminal_action,
)
from merval_agent.agents.intent import explicit_analysis_type, explicit_full_request
from merval_agent.domain.models import (
    AgentState,
    DataQuality,
    Dimension,
    Evidence,
    FinalAnalysis,
    Generation,
    now,
)
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess, is_answerable, narrative


def describe_generation(events: list[dict], status: str, degraded: bool) -> Generation:
    """Build public generation metadata from sanitized per-run trace events."""
    attempts = [
        event
        for event in events
        if event["event"] in ("LLM_SUCCEEDED", "LLM_FAILED", "DECISION_VALIDATION_FAILED")
    ]
    if not attempts:
        return Generation(mode="FAILED" if status == "ERROR" else "SIMULATED")
    last = attempts[-1]
    successes = [event for event in attempts if event["event"] == "LLM_SUCCEEDED"]
    model_version = (
        successes[-1].get("modelVersion")
        if successes and last["event"] == "LLM_SUCCEEDED"
        else None
    )
    outcome = (
        "SUCCEEDED"
        if last["event"] == "LLM_SUCCEEDED"
        else (
            "INVALID_OUTPUT"
            if last["event"] == "DECISION_VALIDATION_FAILED"
            else last.get("error_class", "UNAVAILABLE")
        )
    )
    warnings = []
    if degraded:
        warnings.append(
            "El LLM no pudo finalizar; se entrega únicamente el análisis técnico ya calculado por Python."
        )
    return Generation(
        mode=(
            "DETERMINISTIC_FALLBACK"
            if degraded and status == "ANSWER"
            else "FAILED"
            if status == "ERROR"
            else "LLM_ORCHESTRATED"
        ),
        llm_status=outcome,
        provider=last.get("provider"),
        requested_model=attempts[0].get("model"),
        model=last.get("model"),
        model_version=model_version,
        attempts=len(attempts),
        retry_after_seconds=last.get("retry_after_seconds")
        if outcome != "SUCCEEDED"
        else None,
        warnings=warnings,
    )


def build_report(
    state: AgentState,
    summary: str,
    interpretation: str,
    stale_after_days: int,
    *,
    reference_time: datetime | None = None,
) -> FinalAnalysis:
    history, metrics = state.technical_data, state.technical_metrics
    unsupported_full = (
        explicit_full_request(state.user_request)
        and explicit_analysis_type(state.user_request) != "technical"
    )
    kind = "full" if unsupported_full else state.intent.analysis_type
    asset = state.resolved_asset
    if asset and asset.status != "RESOLVED":
        resolution_status = {
            "NOT_FOUND": "ASSET_NOT_FOUND",
            "AMBIGUOUS": "AMBIGUOUS_ASSET",
            "UNSUPPORTED": "UNSUPPORTED_ASSET",
        }[asset.status]
        technical = Dimension(
            status=resolution_status if kind != "fundamental" else "NOT_REQUESTED"
        )
        fundamental = Dimension(
            status=resolution_status if kind != "technical" else "NOT_REQUESTED"
        )
        return FinalAnalysis(
            status=state.status,
            analysis_type=kind,
            ticker=asset.ticker,
            company_name=asset.company_name,
            executive_summary=summary,
            technical=technical,
            fundamental=fundamental,
            data_quality=DataQuality(
                missing_information=list(dict.fromkeys(state.missing_information)),
                abstentions=[
                    dimension
                    for dimension, requested in (
                        ("technical", kind != "fundamental"),
                        ("fundamental", kind != "technical"),
                    )
                    if requested
                ],
            ),
            trace_id=state.trace_id,
            session_id=state.session_id,
            errors=state.errors,
        )
    historical_bars = (
        history.bars[:-1]
        if history and history.enrichment_status == "appended"
        else history.bars
        if history
        else []
    )
    reference_time = reference_time or state.technical_evaluated_at or now()
    if reference_time.tzinfo is None:
        raise ValueError("reference_time must be timezone-aware")
    if state.technical_assessment is not None and state.technical_evaluated_at == reference_time:
        assessment = state.technical_assessment
    else:
        assessment = assess(history, metrics, reference_time, stale_after_days)
        state.technical_assessment = assessment
        state.technical_evaluated_at = reference_time
    stale = assessment.freshness == "STALE"
    enough = is_answerable(assessment)
    if state.status in ("ABSTAIN", "CLARIFY"):
        safety_resolution = resolve_effective_terminal_action(state.status, state)
        if safety_resolution.effective_action == "FINAL_ANSWER":
            state.status = "ANSWER"
    technical = Dimension(status="NOT_REQUESTED" if kind == "fundamental" else "INSUFFICIENT_DATA")
    fundamental = Dimension(status="NOT_REQUESTED" if kind == "technical" else "INSUFFICIENT_DATA")
    missing = list(state.missing_information)
    if kind != "fundamental":
        technical.metrics = metrics
        if history and history.enrichment_status == "appended":
            technical.history_only_metrics = calculate(historical_bars)
        technical.assessment = assessment
        technical.narrative_origin = "deterministic"
        technical.status = assessment.conclusion if enough else assessment.status
        technical.limitations = [
            (
                "Serie histórica ajustada según la variante informada por el proveedor."
                if history and history.resolved_variant == "ajustada"
                else f"Variante de la serie histórica informada por el proveedor: {history.resolved_variant}."
                if history and history.resolved_variant
                else "Precios según variante del proveedor; no se verificaron ajustes corporativos."
            ),
            "Confianza describe calidad de evidencia, no probabilidad de un pronóstico.",
            *assessment.warnings,
        ]
        if history:
            technical.evidence = [
                Evidence(
                    source=history.source,
                    chunk_id=f"{state.trace_id}:ohlcv",
                    text="OHLCV normalizado; métricas derivadas por Python.",
                    score=1,
                    kind="DATA" if history.mode == "live" else "DEMO",
                    metadata={
                        "mode": history.mode,
                        "fetched_at": history.fetched_at.isoformat(),
                        "provider_fetched_at": history.provider_fetched_at.isoformat(),
                        "received_at": history.received_at.isoformat(),
                        "provider_clock_skew_ms": (
                            history.provider_fetched_at - history.received_at
                        ).total_seconds()
                        * 1000,
                        "as_of": str(historical_bars[-1].date) if historical_bars else None,
                        "currency": history.currency,
                        "resolved_variant": history.resolved_variant,
                        "range": history.range,
                        "discarded_rows": history.discarded_rows,
                        **(
                            {
                                "discarded_details": [
                                    detail.model_dump(mode="json", exclude_none=True)
                                    for detail in history.discarded_details
                                ]
                            }
                            if history.discarded_details
                            else {}
                        ),
                        "enrichment_status": history.enrichment_status,
                    },
                )
            ]
            if history.quote:
                technical.evidence.append(
                    Evidence(
                        source=history.quote.source,
                        chunk_id=f"{state.trace_id}:quote",
                        text="Último precio operado y OHLC provisional; no acredita cierre de rueda.",
                        score=1,
                        kind="DATA",
                        metadata=history.quote.model_dump(mode="json"),
                    )
                )
                technical.limitations.append(
                    "La última barra es provisional: los indicadores de precios incluyen la quote y pueden cambiar durante la rueda."
                    if history.enrichment_status == "appended"
                    else "Cotización provisional separada: no se incorporó a los indicadores; current_price corresponde al último precio histórico utilizado."
                )
            if history.discarded_rows:
                technical.limitations.append(
                    f"Se descartaron {history.discarded_rows} filas históricas inválidas; muestra parcial."
                )
            if history.enrichment_status == "unavailable":
                technical.limitations.append(
                    "Quote no disponible o no válida; se conserva únicamente el historial."
                )
            if any(b.volume is None for b in history.bars):
                technical.limitations.append(
                    "Volumen desconocido en parte de la muestra; average_volume no se calcula."
                )
        if not enough:
            missing.extend(assessment.warnings)
        technical.limitations.extend(f"{k}: {v}" for k, v in assessment.missing_indicators.items())
        if enough:
            technical_summary, technical.interpretation = narrative(assessment, metrics.sample_size)
            if state.status == "ANSWER":
                summary = technical_summary
        else:
            technical.interpretation = " ".join(assessment.warnings)
    if kind != "technical":
        fundamental.limitations = [
            "El análisis fundamental está fuera del alcance de este MVP técnico.",
        ]
        missing.append("Análisis fundamental fuera de alcance")
    explicit_methodology = explicit_methodology_requested(state)
    if explicit_methodology:
        missing.append("Fuentes metodológicas privadas indexadas y verificadas")
        technical.limitations.append(
            "La lectura determinista no valida una interpretación atribuida a Murphy."
        )
        if kind != "fundamental":
            technical.status = "INSUFFICIENT_DATA"
    if state.status == "ANSWER" and (not enough or explicit_methodology):
        state.status = "ABSTAIN"
        summary = "No hay evidencia suficiente para completar el análisis solicitado; se adjuntan los datos disponibles."
    if state.status == "ANSWER" and unsupported_full:
        state.status = "ABSTAIN"
        summary = "No se puede completar el análisis integral: faltan métricas fundamentales verificadas. Se conserva la evidencia técnica disponible."
        fundamental.status = "INSUFFICIENT_DATA"
        missing.append("Análisis fundamental fuera de alcance")
    # Technical failures are not evidence insufficiency. A later successful result
    # for the same capability (including an alternative document lookup) recovers it.
    capabilities = {}
    calls = iter(state.tool_calls)
    previous_ticker = None
    for observation in state.observations:
        if observation.tool_name == "decision":
            continue
        next(calls, None)
        if observation.tool_name == "resolve_asset" and observation.success:
            ticker = observation.data.get("ticker")
            if ticker != previous_ticker:
                capabilities.clear()
            previous_ticker = ticker
        capability = observation.tool_name
        capabilities[capability] = observation
    if state.status in ("ANSWER", "ABSTAIN") and any(
        not o.success and o.error and o.error.code in ("EXTERNAL_SERVICE", "CALCULATION_FAILED")
        for o in capabilities.values()
    ):
        state.status = "ERROR"
        summary = "Un fallo técnico no recuperado impidió completar el análisis; se conservan los datos disponibles."
    market_failure = capabilities.get("get_market_history")
    calculation_failure = capabilities.get("calculate_technical_indicators")
    if (
        kind != "fundamental"
        and calculation_failure
        and not calculation_failure.success
        and calculation_failure.error
        and calculation_failure.error.code == "CALCULATION_FAILED"
    ):
        assessment.status = technical.status = "INVALID_DATA"
        assessment.confidence = "UNAVAILABLE"
        assessment.conclusion = "UNAVAILABLE"
        technical.interpretation = (
            "Falló el cálculo técnico; los datos de mercado se conservan como evidencia."
        )
        technical.limitations.append(technical.interpretation)
    if kind != "fundamental" and market_failure and not market_failure.success:
        assessment.status = (
            "INVALID_DATA" if market_failure.error_kind == "INVALID_RESPONSE" else "SOURCE_ERROR"
        )
        assessment.confidence = "UNAVAILABLE"
        technical.status = assessment.status
        assessment.conclusion = "UNAVAILABLE"
        technical.limitations.append("La fuente de precios falló; no es insuficiencia estadística.")
        technical.interpretation = (
            "La fuente de precios falló; no hay una nueva lectura técnica validada."
        )
        assessment.warnings = [technical.interpretation]
    evidence = technical.evidence + fundamental.evidence
    return FinalAnalysis(
        status=state.status,
        ticker=asset.ticker if asset else None,
        company_name=asset.company_name if asset else None,
        analysis_type=kind,
        as_of=history.bars[-1].date if history and history.bars else None,
        executive_summary=summary,
        technical=technical,
        fundamental=fundamental,
        data_quality=DataQuality(
            missing_information=list(dict.fromkeys(missing)),
            stale_data=stale,
            abstentions=[
                name
                for name, dimension in (("technical", technical), ("fundamental", fundamental))
                if dimension.status == "INSUFFICIENT_DATA"
            ],
        ),
        sources=list(dict.fromkeys(e.source for e in evidence)),
        trace_id=state.trace_id,
        session_id=state.session_id,
        errors=state.errors,
    )
