import re

from merval_agent.agents.intent import explicit_analysis_type, explicit_full_request
from merval_agent.domain.models import (
    AgentState,
    DataQuality,
    Dimension,
    Evidence,
    FinalAnalysis,
    now,
)
from merval_agent.domain.technical import calculate
from merval_agent.domain.technical_assessment import assess, narrative


def build_report(
    state: AgentState, summary: str, interpretation: str, stale_after_days: int
) -> FinalAnalysis:
    history, metrics = state.technical_data, state.technical_metrics
    unsupported_full = (
        explicit_full_request(state.user_request)
        and explicit_analysis_type(state.user_request) != "technical"
    )
    kind = "full" if unsupported_full else state.intent.analysis_type
    asset = state.resolved_asset
    historical_bars = (
        history.bars[:-1]
        if history and history.enrichment_status == "appended"
        else history.bars
        if history
        else []
    )
    assessment = assess(history, metrics, now(), stale_after_days)
    stale = assessment.freshness == "STALE"
    enough = assessment.status in ("COMPLETE", "PARTIAL")
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
            "Precios según variante del proveedor; no se verificaron ajustes corporativos.",
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
                        "as_of": str(historical_bars[-1].date) if historical_bars else None,
                        "currency": history.currency,
                        "discarded_rows": history.discarded_rows,
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
            "El descubrimiento de documentos no implica extracción ni validación de métricas de balances.",
            "Publicaciones visibles en Bolsar; no garantiza cobertura histórica completa.",
        ]
        if asset and asset.company_type == "FINANCIAL":
            fundamental.limitations.append(
                "Empresa financiera: futura selección de ratios bancarios; no aplicar current ratio industrial."
            )
        fundamental.evidence = [
            Evidence(
                source=d.source_url,
                chunk_id=d.document_id,
                text=d.reference,
                score=1,
                kind="DATA",
                metadata={"published_at": str(d.published_at), "metadata_only": True},
            )
            for d in state.financial_data
        ]
        missing.append("Métricas fundamentales extraídas y verificadas")
    for evidence in state.methodology_evidence:
        target = technical if "murphy" in evidence.source else fundamental
        target.evidence.append(evidence)
        if evidence.kind == "DEMO":
            target.limitations.append(
                "Metodología demostrativa local: no es recuperación del libro ni evidencia autoritativa."
            )
    # The model's choice to consult a methodology is not an explicit user demand
    # for an authoritative book interpretation. Keep that distinction independent
    # of whether the model fills the optional intent.methodology field.
    explicit_methodology = bool(re.search(r"\b(?:murphy|graham)\b", state.user_request, re.I))
    if (state.intent.methodology or explicit_methodology) and not any(
        e.kind == "METHODOLOGY" for e in state.methodology_evidence
    ):
        missing.append("Fuentes metodológicas privadas indexadas y verificadas")
    if explicit_methodology and not any(
        e.kind == "METHODOLOGY" for e in state.methodology_evidence
    ):
        technical.limitations.append(
            "La lectura determinista no valida una interpretación atribuida a Murphy/Graham."
        )
        if kind != "fundamental":
            technical.status = "INSUFFICIENT_DATA"
    if state.status == "ANSWER" and (
        not enough
        or (
            explicit_methodology
            and not any(e.kind == "METHODOLOGY" for e in state.methodology_evidence)
        )
    ):
        state.status = "ABSTAIN"
        summary = "No hay evidencia suficiente para completar el análisis solicitado; se adjuntan los datos disponibles."
    if state.status == "ANSWER" and unsupported_full:
        state.status = "ABSTAIN"
        summary = "No se puede completar el análisis integral: faltan métricas fundamentales verificadas. Se conserva la evidencia técnica disponible."
        fundamental.status = "INSUFFICIENT_DATA"
        missing.append("Métricas fundamentales extraídas y verificadas")
    # Technical failures are not evidence insufficiency. A later successful result
    # for the same capability (including an alternative document lookup) recovers it.
    capabilities = {}
    calls = iter(state.tool_calls)
    previous_ticker = None
    for observation in state.observations:
        if observation.tool_name == "decision":
            continue
        call = next(calls, None)
        if observation.tool_name == "resolve_asset" and observation.success:
            ticker = observation.data.get("ticker")
            if ticker != previous_ticker:
                capabilities.clear()
            previous_ticker = ticker
        capability = (
            "financial_documents"
            if observation.tool_name
            in ("list_financial_documents", "get_latest_financial_statement")
            else observation.tool_name
        )
        if observation.tool_name == "search_methodology" and call:
            capability += ":" + str(call.arguments.get("source"))
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
