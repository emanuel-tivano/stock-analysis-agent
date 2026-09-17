# Fase 2A — Real LLM Agent Validation

## Estado y alcance

Este documento conserva el historial de implementación. Para la política actual del
loop, la evidencia Gemini y el dictamen de Fase 2, consultar la
[auditoría de cierre](phase2-closure.md).

Implementación preparada y validada offline. **No se ejecutó un proveedor externo**:
no están configurados LLM_BASE_URL, LLM_MODEL ni LLM_API_KEY. El milestone real y la
Definition of Done completa permanecen pendientes de esa ejecución.

Baseline auditada: commit `b0dfdab`, árbol inicialmente limpio, sin tags locales.
Antes de modificar: 87 tests PASS, 2 live SKIP. Se preservan AgentState, AgentDecision,
FinalAnalysis, ToolRegistry, adapters de datos, SQLite, API, políticas y golden traces.
No se modificó argentina-market-tracker. No hay LangGraph ni multiagente.

## Implementación

EquityAgent conserva el mismo loop. LLMProvider.decide conserva su contrato. El adapter
compatible expone una extensión opcional `decide_validated`: recibe el validador del
agente y un callback de eventos. El Fake sigue usando decide y sus eventos originales.
No se agregó un SDK ni se fijó un proveedor/modelo/URL personal.

Cada intento HTTP pasa por parse JSON, Pydantic y validación de negocio. Se reutiliza
ToolRegistry.validate antes de ejecutar la decisión real: nombre, argumentos, ticker,
precondiciones e intent. Un intent no cambia después de comenzar tools. Se rechazan
llamadas idénticas con éxito previo (argumentos normalizados); una llamada con ERROR
puede reintentarse. El registro de intentos permite observar propuestas rechazadas.

`LLM_MAX_RETRIES=1` significa hasta 2 peticiones por step; admite 0–2 retries. Se corrigen
JSON, schema, precondiciones o duplicados con un mensaje genérico sin repetir la respuesta
cruda. Timeout, HTTP error, rate limit y respuesta vacía también tienen presupuesto acotado.
Al agotarse: ERROR/LLM_FAILURE, nunca una conclusión financiera. Un tool error sigue siendo
una observación sobre la que decidir. MAX_AGENT_STEPS conserva su semántica original.

No se extrae un JSON desde texto libre: texto alrededor del JSON es inválido y consume
el presupuesto de reparación. No hay fallback automático entre formatos: configurarlo
según las capacidades del endpoint. `json_schema` envía el schema Pydantic existente sin
exigir extensiones strict particulares de un vendor; algunos endpoints podrían rechazarlo.

## Prompt, privacidad y salida

`adapters/llm/context.py` define AGENT_PROMPT_VERSION=phase2a-v1, instrucciones y
build_agent_context. El objetivo se limita a 2000 caracteres (con indicador de truncado),
se envían métricas Python y resumen de historial, hasta 10 documentos/metodologías,
100 llamadas/observaciones y 10 errores/faltantes. Se deduplican observaciones. No se envían
barras completas, respuestas HTTP, headers, SQLite, PDFs ni metadata documental arbitraria.
Los schemas de tools pertenecen al registry fijo de la aplicación.

El texto del usuario es dato de menor prioridad. Las instrucciones explican ramas,
precondiciones, reutilización, abstención, DEMO, NOT_REQUESTED y límite de pasos.
reason es breve (hasta 400 caracteres), interpretation hasta 800; respuesta hasta 32000.
No se solicita razonamiento interno. El prompt no garantiza fidelidad por sí solo.

En esta fase la prosa libre del provider real NO se publica como conclusión: summary,
interpretation y faltantes propuestos se convierten en texto operacional fijo. Las cifras,
fuentes, estados y limitaciones provienen del reporte determinístico existente. La pregunta
CLARIFY es genérica: confirmar ticker, instrumento y tipo de análisis. El Fake conserva su
salida original. Evaluar narrativa libre requerirá trabajo posterior separado.

Eventos reales: LLM_STARTED; LLM_SUCCEEDED después de validar; LLM_FAILED por transporte
/protocolo; DECISION_VALIDATION_FAILED por JSON/schema/negocio. Incluyen provider, model,
step, retry, latencia en ms, usage numérico disponible, outcome, hash SHA-256 y bytes del
prompt, versión. No incluyen prompt, respuesta cruda, reason, Authorization ni API key.
SQLite conserva su esquema y su almacenamiento privado histórico de request/summary;
show_trace continúa excluyendo esos campos.

## Configuración y ejecución (PowerShell)

Configurar en `.env` local o variables del proceso:

```dotenv
LLM_PROVIDER=compatible
LLM_BASE_URL=<base del endpoint con prefijo de API>
LLM_MODEL=<modelo habilitado>
LLM_API_KEY=<secreto local>
LLM_TIMEOUT_SECONDS=20
LLM_MAX_RETRIES=1
LLM_RESPONSE_FORMAT=json_object
AGENT_PROMPT_VERSION=phase2a-v1
```

LLM_RESPONSE_FORMAT admite json_schema, json_object y none. None pide JSON mediante
instrucciones sin response_format. La API utiliza la selección LLM_PROVIDER; los scripts
real/fake la seleccionan explícitamente. RUN_LLM_TESTS se lee del entorno del proceso.

```powershell
python -m pytest -q
python scripts/eval_real_llm.py --fake --runs 3
$env:RUN_LLM_TESTS = "1"
python -m pytest tests/integration/test_real_llm.py -q -s
python scripts/eval_real_llm.py --runs 3
# LLM real + servicios de datos externos; exige LLM_PROVIDER=compatible:
python scripts/run_real_llm.py
python scripts/show_trace.py <trace_id>
# Para traces de evals con fixtures:
python scripts/show_trace.py <trace_id> --database evals/results/traces.sqlite3
```

pytest normal es offline y omite tests reales sin opt-in. No se crean credenciales.
La API con provider compatible puede llamar al LLM sin RUN_LLM_TESTS: esa variable protege
los runners de validación, no cambia el contrato público de la API.

## Dataset y métricas

17 casos, dataset_version phase2a-v1, reutilizando las 7 evals originales y ampliando ramas,
full, ambigüedad, ticker desconocido, metodología, fallo de mercado, historial corto,
reutilización, contradicción, fuera de alcance y cuatro pedidos adversariales.
Las evals usan datos sintéticos etiquetados live dentro del fixture para ejercitar las
políticas existentes: **no prueban conectividad ni precios reales**. PAMP incluye metadata
documental sintética en los casos nuevos; jamás descarga balances.
El caso de reutilización examina pasos posteriores de una ejecución; no usa memoria de
otra sesión. Tests offline adicionales fuerzan duplicados y retries después de ERROR.

El evaluador está fuera del agente. No exige orden exacto; admite list_financial_documents
como alternativa a get_latest_financial_statement. Comprueba tools requeridas, propuestas
prohibidas incluso rechazadas, estado, activo permitido, abstenciones, dimensiones y DEMO.
No pretende evaluar calidad de narrativa financiera libre (no se expone en esta fase).

- case_count: casos únicos; run_count: ejecuciones incluyendo repeticiones.
- task_success_rate: proporción que satisface las condiciones semánticas y no duplica éxito.
- tool_selection_accuracy: proporción de ejecuciones con tools requeridas y sin prohibidas/duplicados.
- forbidden_tool_violations: llamadas prohibidas ejecutadas más propuestas conocidas rechazadas.
- invalid_decision_rate: decisiones inválidas / intentos de decisión, incluyendo retries.
- duplicate_tool_call_rate: propuestas duplicadas de éxito / intentos de tools (rechazos incluidos).
- abstention_correctness: cumplimiento de status y dimensiones en casos que esperan abstención.
- clarification_correctness: status permitido en casos que permiten CLARIFY.
- max_steps_exceeded: ejecuciones que agotaron el presupuesto; average_steps: promedio del loop.
- average_latency: milisegundos de ejecución completa, incluyendo datos, retries y persistencia.
- provider_errors: intentos fallidos de transporte/protocolo; validaciones se cuentan separadamente.
- input_tokens/output_tokens/total_tokens: sumas de valores recibidos; null si no se informaron.

Costo null salvo usage completo de entrada/salida y ambos precios explícitos:
LLM_INPUT_PRICE_PER_1M / LLM_OUTPUT_PRICE_PER_1M, en la misma moneda elegida por el usuario.
No se asume USD ni precios permanentes; configurar ambos o dejarlos sin definir, no vacíos.
Usage parcial es un total observado, no una estimación de tokens omitidos.

Reportes locales ignorados por Git: evals/results/fake_baseline.json,
real_llm_<model>_<timestamp>.json y traces.sqlite3. Incluyen versión de prompt/dataset,
modelo, timestamp y filas por repetición. El CLI compara con el último Fake disponible y
sale con código 1 si hay casos fallidos, conservando el reporte. No publicar estos archivos
sin revisarlos; la DB mantiene los campos privados de Fase 1.

## Evidencia y límites actuales

Fake, 17 casos × 3: 45/51 éxitos (88,24%), tool selection 94,12%, 6 llamadas prohibidas
(todas en el caso contradictorio), decisiones inválidas 0, duplicados 0, pasos promedio 4,294.
Fuera de alcance: Fake pide aclaración; contradicción: Fake hace análisis técnico sin aclarar.
Se registran sus límites sin cambiar la baseline. Las 7 evals originales siguen pasando.
No hay métricas, trace_id ni muestra de un LLM externo; tampoco prueba end-to-end real nueva.
Latencia Fake local no predice latencia/costo del proveedor real.

JSON schema no garantiza corrección financiera. El intent inicial sigue siendo propuesto
por el modelo; las evals detectan clasificación/selección incorrecta. Las validaciones
posteriores imponen las restricciones del intent aceptado y del estado. No se agregó un
clasificador alternativo. No hay auditoría exhaustiva de prompt injection.

RAG continúa DEMO. No hay embeddings, vector DB, extracción PDF, valoración Graham ni
HITL con efectos. Fase 2A no debe declararse completada hasta ejecutar y revisar el modelo.

## Propuesta Fase 2B

Primero cerrar las ejecuciones externas de Fase 2A (17 × 3 y GGAL con Market Tracker),
revisar fallos por trace y congelar prompt/dataset. Después, una iteración separada para
recuperación metodológica con autorización de fuentes, citas verificables y evaluación
proveniencia/relevancia. Conservar AgentDecision, tools y políticas; no mezclar ese trabajo
con extracción de balances ni valoración. Nada de Fase 2B se implementa aquí.

## Actualización posterior: Gemini nativo

Se agregó el tercer provider gemini conservando prompt y contratos. La prueba mínima real
pasó; el primer recorrido GGAL terminó ERROR por 503/429 después de consultar historial live.
Las afirmaciones anteriores de ausencia total de ejecución externa describen el estado
previo. La evidencia actual y la validación pendiente están en [gemini-native.md](gemini-native.md).
