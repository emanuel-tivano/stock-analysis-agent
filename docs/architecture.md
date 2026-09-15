# Arquitectura — Fase 1

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
La variación usa primer y último cierre; extremos usan high/low, volumen usa media aritmética.
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

ANSWER habilita un informe parcial de cálculos con historial live reciente y SMA20/RSI14
disponibles. Datos demo, desconocidos, antiguos o escasos fuerzan abstención. Fundamental
siempre INSUFFICIENT_DATA mientras no exista extracción confiable. Categorías direccionales
y valoración están reservadas y no se asignan en Fase 1. `NOT_REQUESTED` distingue una dimensión
fuera del pedido. Se conserva `as_of` del último dato de mercado; los documentos tienen su
propia fecha de publicación en evidence. No se inventa una fecha de balance.

El umbral de antigüedad usa días calendario, no calendario de ruedas. No hay garantía sobre
ajustes corporativos ni completitud del historial. La interpretación es del provider y requiere
evaluación adicional antes de habilitar afirmaciones direccionales.

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
