# Arquitectura — Fase 1 y extensiones

Estado actual y cambios de contratos: [análisis técnico v4](technical-v4.md).
Antecedente: [análisis técnico v3](technical-v3.md).
Las secciones de Fase 1/2A siguientes conservan contexto histórico donde se indica.

## Límites y dependencias

`domain/` contiene modelos Pydantic y funciones puras, sin FastAPI, HTTP, SQLite ni SDKs.
`agents/` implementa loop, validación, reducer y reporte. Depende del protocolo LLMProvider,
registry y AnalysisRepository. `adapters/` encapsula HTTP y parsing. `tools/` contiene
contratos de entrada, descripciones semánticas y handlers pequeños. `retrieval/` expone un
protocolo reemplazable. `bootstrap.py` conecta implementaciones; `api/` solo valida requests
y delega. `memory/` persiste mediante parámetros SQL. No se crea otro repositorio ni se integra
código de argentina-market-tracker.

## Ciclo agéntico

1. Construir AgentState por ejecución con session_id y trace_id independientes.
2. Provider recibe una copia del estado y schemas de tools; decide la próxima acción.
3. Pydantic valida estructura; reglas de negocio validan resolución y alcance.
4. CALL_TOOL produce ToolResult, incluyendo fallas esperables; reducer actualiza datos tipados.
5. Provider observa resultados y vuelve a decidir, sin aristas obligatorias entre tools.
6. CLARIFY/ABSTAIN/FINAL_ANSWER terminan; la suficiencia de evidencia puede degradar ANSWER
   a ABSTAIN. Errores de proveedor/internos se representan como ERROR.
7. MAX_AGENT_STEPS limita todas las decisiones, incluidas inválidas. Persistir y registrar cierre.

El fake simula este protocolo con reglas y admite scripts inyectados. La prueba de orden
alternativo demuestra que la orquestación no fija la ruta, pero no valida inteligencia de un LLM.
Se permite recuperación tras error de tool/decisión. No hay retry automático oculto en adapters.
Falla de persistencia devuelve ERROR explícito. Repositorio inicial no reanuda estado.

## Contratos y evidencia

`AgentDecision` separa CALL_TOOL, CLARIFY, FINAL_ANSWER y ABSTAIN. tool_args no se admiten
en acciones terminales. El registry valida argumentos y evita ticker diferente del resuelto,
herramientas fuera del alcance y cálculos sin historial. Cambiar intent después de ejecutar
tools requiere una nueva solicitud; no se permite ampliar alcance silenciosamente.

MarketHistory conserva barras cronológicas, fuente, fetched_at, mode, stale y moneda.
TechnicalMetrics no recibe cifras del LLM: la tool toma el historial guardado en el estado.
La variación usa primer y último cierre; extremos usan high/low, volumen usa media aritmética solo si todas las barras tienen volumen conocido; de otro modo es null.
EMA se inicializa con SMA del período. MACD alinea EMA12 y EMA26 en la rueda 26 y calcula
señal EMA9 sobre la línea MACD desde la rueda 34. RSI usa Wilder; sin pérdidas = 100,
sin ganancias = 0, serie plana = 50. Sin muestra suficiente = null, sin redondeo interno.

FinancialDocument incluye metadata y fiscal_period nullable, nunca inventado. Selección de
balance: publicación más reciente entre Estados Financieros/Síntesis, desempate por documento
completo y luego id. Filtros de fecha son de publicación, no período contable. El parser
rechaza páginas sin tabla esperada. Cambios HTML requieren actualizar fixtures y parser.

Evidence distingue DATA/METHODOLOGY/DEMO y mantiene chunk_id y metadata. Las notas demo nunca
validan una conclusión atribuida a libros. Score no es probabilidad de verdad. La interpretación
del provider aparece separada de métricas y no reemplaza datos. Fase 2 debe evaluar fidelidad
semántica del texto: la validación estructural no garantiza corrección financiera.

## Suficiencia y reportes

`domain/technical_assessment.py` centraliza ventanas, suficiencia, vigencia y señales.
El loop calcula assessment antes de cada decisión; la proyección del contexto lo entrega al
LLM junto con métricas separadas. El reporte aplica las mismas reglas y redacta desde ellas.
No publica cifras ni conclusiones libres del LLM. No impone una secuencia nueva de tools.
Mínimo parcial: precio y 15 observaciones; completo: todos los indicadores con ventanas
hasta 50, sin filas descartadas. Volumen ausente no invalida los indicadores de precios.
El contrato técnico separa estado de datos, dirección, confianza de evidencia y narrativa.
Fundamental conserva su estado insuficiente; `NOT_REQUESTED` distingue lo no solicitado.

Vigencia usa tolerancia calendario (7 días), respeta fines de semana y permite inyectar
feriados verificados en la función pura. No hay un calendario BYMA integrado ni certificación
de cierres. `as_of` es la última observación; fetched_at sigue siendo recepción upstream.
Una quote provisional nunca rejuvenece un histórico vencido.

## Observabilidad y privacidad

Logging estándar JSON: AGENT_STARTED, DECISION_MADE, TOOL_STARTED, TOOL_SUCCEEDED,
TOOL_FAILED, STATE_UPDATED, AGENT_FINISHED / AGENT_ABSTAINED. Incluye trace_id, paso,
acción, tool, argumentos categóricos sanitizados, latencia de tools, error y transición.
No se loguean prompts, respuestas HTTP, API keys ni razones textuales libres del modelo.
La decisión trazada registra acción/confianza; el texto libre se conserva solo donde el
contrato de reporte lo requiere. El pedido se almacena localmente en SQLite según el alcance
solicitado; el archivo queda fuera de Git. No existe plataforma de tracing externa.

Los mismos eventos se acumulan en `AgentState.trace_events` (excluidos del dump al provider)
y se guardan en la columna SQLite `events`, sin ampliar `FinalAnalysis`.
Incluyen `outcome`, `tool_name` cuando corresponde y un resumen de la evidencia del estado.
Toda abstención registra `AGENT_ABSTAINED` y `AGENT_FINISHED`; decisiones inválidas registran
`DECISION_MADE` con outcome INVALID y consumen paso. El reporte registra también su transición
de suficiencia. `scripts/show_trace.py` recupera los eventos por trace_id en modo lectura.
La migración agrega la columna sin borrar filas anteriores; no reconstruye eventos históricos.
Ante falla de SQLite se registra un cierre corregido ERROR en logs; ese cierre no puede
garantizarse persistido. Los errores se representan mediante códigos, sin mensajes externos.

El default de horizonte está centralizado en `domain/policy.py`: 6M para SMA50 y análisis
intermedio. La política del fake no fija el orden del loop; providers de prueba pueden
reordenar tools y ampliar el rango tras una observación insuficiente.

## Extensiones de Fase 2

- Proveedor real: validar JSON mode, decisiones, latencia, errores y fidelidad con evals.
- RAG: ingesta explícita de fuentes privadas, chunks con páginas, citas y recuperación real.
- Fundamentales: extracción por tipo de documento, inputs verificados y funciones puras.
  Bancos FINANCIAL: ROE/ROA, capital, NPL, cobertura, eficiencia y P/BV; evitar ratios industriales
  aplicados mecánicamente. No se implementan ratios sin datos.
- HITL: propuesta PendingAction con action_id y parámetros; PAUSED antes de todo efecto.
  APPROVE autoriza exactamente la propuesta; MODIFY genera una propuesta nueva y REJECT
  termina sin ejecutar. La ejecución futura deberá ser idempotente y auditable; aún no existe.
- API: reanudación conversacional, políticas de concurrencia y autenticación al publicar.

## Extensión implementada en Fase 2A

El mismo loop usa la capacidad opcional `decide_validated` del provider compatible para
reintentar dentro del step con callback de validación/eventos. No cambia LLMProvider.decide
ni los modelos del dominio. Registry.validate se reutiliza antes de aceptar la propuesta;
se rechazan duplicados de llamadas exitosas sin consumir otra API de datos.

El contexto es una proyección explícita y acotada, no AgentState.model_dump. El prompt
versionado incluye políticas operacionales. Los intentos agregan eventos a la lista existente,
sin migración SQLite. La narrativa compatible se publica como texto operacional fijo para
no propagar afirmaciones financieras sin verificar; Fake conserva su texto previo.
El evaluador independiente usa datos sintéticos y guarda métricas por caso/repetición.

La ejecución externa estaba pendiente en esta etapa histórica; la evidencia posterior
está en [phase2-closure.md](phase2-closure.md). Detalles y límites en
[phase2a-real-llm.md](phase2a-real-llm.md). Las secciones anteriores describen la baseline
Fase 1; la interpretación libre del provider allí mencionada solo se conserva para Fake.

## Gemini nativo

`HTTPDecisionProvider` comparte el mecanismo de decisión validada/retry entre Compatible y
Gemini. `build_provider` selecciona los tres providers para API y evaluador. Gemini adapta
los mensajes a systemInstruction/contents y normaliza candidates/usageMetadata; no agrega
funciones nativas ni contratos nuevos. EquityAgent no recibe detalles de Gemini.
Más detalles y evidencia de ejecución en [gemini-native.md](gemini-native.md).

## Enriquecimiento provisional y fallos técnicos (16/09/2026)

MarketHistory.quote conserva barra, moneda, observed_at, fetched_at local, URL y provisional=true.
El source/fetched_at superior siguen perteneciendo al histórico upstream. El reporte publica
dos evidencias y as_of del último dato, sin presentarlo como cierre confirmado. Antigüedad
en días calendario de Buenos Aires, tanto del histórico base como de la barra final.
No hay calendario bursátil ni heurística por hora para certificar cierres.

Enrichment_status y discarded_rows hacen visibles fallback y muestra parcial. El adapter
hace como máximo un request opcional adicional y no reintenta quotes. Una falla opcional
no invalida el histórico; una falla de tool no recuperada termina ERROR. Un resultado
posterior exitoso de la misma capacidad recupera el fallo. DEMO/ausencia válida siguen
siendo insuficiencia de evidencia (ABSTAIN). Las fórmulas de precios no cambiaron.
