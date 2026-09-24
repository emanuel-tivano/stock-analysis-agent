# Contratos

La fuente ejecutable es domain/models.py y los schemas Pydantic entregados por el provider.
AgentDecision: action CALL_TOOL / CLARIFY / FINAL_ANSWER / ABSTAIN, reason, confidence,
missing_information; tool_name y tool_args solo para CALL_TOOL. Incluí intent en la primera
decisión. interpretation es texto separado de los datos, sin cifras calculadas por el modelo.
El sistema valida JSON y reglas de negocio; invalidaciones vuelven como observaciones.

FinalAnalysis separa technical, fundamental, integrated_view, data_quality, sources y trace_id.
ANSWER puede contener cálculos parciales y abstenciones por dimensión. CLARIFY pide información
al usuario. ABSTAIN es falta de evidencia; ERROR es falla técnica. technical.status representa
BULLISH/BEARISH/NEUTRAL/MIXED con datos utilizables. technical.assessment.status representa
COMPLETE/PARTIAL/INSUFFICIENT_DATA/SOURCE_ERROR/STALE/INVALID_DATA/UNVERIFIED.
INSUFFICIENT_DATA no significa neutralidad ni falta de RAG en pedidos técnicos ordinarios.
AssetResolution distingue RESOLVED, AMBIGUOUS y NOT_FOUND. Los dos últimos detienen el loop
antes de mercado y se publican como technical.status AMBIGUOUS_ASSET o ASSET_NOT_FOUND, con
assessment ausente; no deben degradarse a INSUFFICIENT_DATA.
metrics conserva cifras Python; assessment conserva señales, tendencia, momentum, confianza
de evidencia y fechas; interpretation se redacta desde esas señales (narrative_origin=deterministic).

momentum_state distingue IMPROVING_BUT_BEARISH y WEAKENING_BUT_BULLISH. MACD sobre su señal
no confirma una reversión: la tendencia tiene precedencia en conclusion. MIXED requiere
conflictos explícitos. confirmation=ALIGNED significa coincidencia de indicadores, no certeza.
completion_reasons explica PARTIAL; volumen desconocido no lo causa, filas descartadas sí.
basis identifica histórico, quote provisional, política y fecha efectiva de los indicadores.
generation distingue LLM_ORCHESTRATED, DETERMINISTIC_FALLBACK, SIMULATED y FAILED.
El fallback de modelo es independiente de la salida determinista, requiere configuración
explícita y queda registrado; los errores de structured output no se convierten en fallback.
## HITL de informes

FinalAnalysis y ChatResponse admiten PAUSED y pending_action como proyección segura:
action_id UUID, tipo, estado, versión, ticker, as_of, resumen, propuesta editorial,
acciones permitidas, trace_id y session_id. PendingAction del dominio está en actions.py;
el antiguo contrato reservado de watchlist/alertas fue reemplazado, sin consumidores previos.
POST /agent/actions/{action_id}/approve|modify|reject exige session_id, expected_version
e idempotency_key; modify agrega changes (focus/include_sections/review_note).
Un informe finalizado conserva FinalAnalysis y agrega publication; no cambia métricas.
La autorización corresponde al humano mediante la API, nunca a AgentDecision del modelo.
