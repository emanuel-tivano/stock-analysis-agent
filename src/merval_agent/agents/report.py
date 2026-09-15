from merval_agent.domain.models import (
    AgentState,
    DataQuality,
    Dimension,
    Evidence,
    FinalAnalysis,
    now,
)


def build_report(
    state: AgentState, summary: str, interpretation: str, stale_after_days: int
) -> FinalAnalysis:
    history, metrics = state.technical_data, state.technical_metrics
    kind = state.intent.analysis_type
    asset = state.resolved_asset
    stale = bool(
        history
        and (
            history.stale
            or (
                history.bars
                and not 0 <= (now().date() - history.bars[-1].date).days <= stale_after_days
            )
        )
    )
    enough = bool(
        history
        and history.mode == "live"
        and not stale
        and metrics
        and metrics.sma20 is not None
        and metrics.rsi14 is not None
    )
    technical = Dimension(status="NOT_REQUESTED" if kind == "fundamental" else "INSUFFICIENT_DATA")
    fundamental = Dimension(status="NOT_REQUESTED" if kind == "technical" else "INSUFFICIENT_DATA")
    missing = list(state.missing_information)
    if kind != "fundamental":
        technical.metrics = metrics
        technical.limitations = [
            "Precios según variante del proveedor; no se verificaron ajustes corporativos.",
            "No se asigna categoría direccional en Fase 1; INSUFFICIENT_DATA indica ausencia de conclusión validada.",
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
                        "as_of": str(history.bars[-1].date) if history.bars else None,
                        "currency": history.currency,
                    },
                )
            ]
        if not enough:
            missing.append("Historial live reciente con al menos 20 ruedas válidas")
        if metrics:
            unavailable = [k for k, v in metrics.model_dump().items() if v is None]
            if unavailable:
                technical.limitations.append(
                    "Indicadores sin muestra suficiente: " + ", ".join(unavailable)
                )
        technical.interpretation = (
            interpretation
            if enough
            else "Abstención: evidencia técnica insuficiente, demo, desconocida o antigua."
        )
    if kind != "technical":
        fundamental.limitations = [
            "Fase 1 descubre documentos; no extrae ni valida métricas de balances.",
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
    if state.intent.methodology and not any(
        e.kind == "METHODOLOGY" for e in state.methodology_evidence
    ):
        missing.append("Fuentes metodológicas privadas indexadas y verificadas")
    if state.status == "ANSWER" and (
        not enough
        or (
            state.intent.methodology
            and not any(e.kind == "METHODOLOGY" for e in state.methodology_evidence)
        )
    ):
        state.status = "ABSTAIN"
        summary = "No hay evidencia suficiente para completar el análisis solicitado; se adjuntan los datos disponibles."
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
