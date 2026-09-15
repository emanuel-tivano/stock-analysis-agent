# Contratos

La fuente ejecutable es domain/models.py y los schemas Pydantic entregados por el provider.
AgentDecision: action CALL_TOOL / CLARIFY / FINAL_ANSWER / ABSTAIN, reason, confidence,
missing_information; tool_name y tool_args solo para CALL_TOOL. Incluí intent en la primera
decisión. interpretation es texto separado de los datos, sin cifras calculadas por el modelo.
El sistema valida JSON y reglas de negocio; invalidaciones vuelven como observaciones.

FinalAnalysis separa technical, fundamental, integrated_view, data_quality, sources y trace_id.
ANSWER puede contener cálculos parciales y abstenciones por dimensión. CLARIFY pide información
al usuario. ABSTAIN es falta de evidencia; ERROR es falla técnica. En Fase 1 las categorías
direccionales están reservadas: INSUFFICIENT_DATA no debe interpretarse como señal neutral.
