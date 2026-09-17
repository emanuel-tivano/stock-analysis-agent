# Fase 2: auditoría de cierre

**Dictamen:** estabilización funcional completada y cobertura real PASS de los 17 casos
tras revalidar los afectados. No se certifica la DoD forense estricta: las cuatro causas
individuales de invalidación del trace histórico no fueron almacenadas y no pueden
reconstruirse con certeza. La causa general de reparación insuficiente sí fue reproducida
y corregida. Esta salvedad no se oculta bajo los resultados verdes posteriores.

## Evidencia de entrada

Reporte original: `real_llm_gemini_3_5_flash_lite_phase2a-v2_20260915T225528565653Z.json`
en `evals/results/`. Gemini `gemini-3.5-flash-lite`, prompt `phase2a-v2`, dataset
`phase2a-v1`, evaluator `phase2a-v2`: 14 PASS / 3 FAIL. Se inspeccionaron sus eventos
SQLite, las 17 definiciones, fixtures HTTP, reducer, adapters, registry, loop y scorer
antes de modificar código. No se modificaron los expected del dataset ni el prompt.

### unknown

Trace `b80fc163-368a-4dc7-a7fe-54c30568ea05`: una decisión CLARIFY, sin tools ni errores.
Fixture: activo esperado null, estados CLARIFY/ABSTAIN, `resolve_asset` esperado.
`clarification_correct` y `abstention_correct` verifican estado/dimensiones; no exigen
tools. `tools_correct` exigía todos los nombres de expected_tools; task_success incluía
esa condición. Por eso las cuatro métricas no eran contradictorias, pero el criterio
de herramientas penalizaba una aclaración válida.

Corrección del evaluator: cuando el fixture acepta el terminal CLARIFY/ABSTAIN, no
espera activo, el resultado no inventa uno y sólo exige resolución, ésta es opcional.
No se exime una consulta de datos ni una respuesta sobre un activo conocido.

### market_failure

Trace `9a4bdd93-4a71-410f-930b-f2e4c98e1e4c`: resolve_asset, tres decisiones sucesivas
get_market_history con los mismos argumentos (GGAL, 6M), después ABSTAIN. Cada request
de datos devuelve 503 del fixture. Son nuevas decisiones del LLM, no retries ocultos
del adapter. El registry marcaba cualquier ExternalServiceError como retryable y no
había presupuesto por operación. La proyección del contexto deduplicaba las ternas
(tool, success, error), perdiendo la multiplicidad y sin exponer retryable/intentos.

Corrección del controlador: hasta dos intentos por operación (inicial + un retry
explícitamente propuesto). No hay retry automático. Sólo errores transitorios tipados
permiten repetir. El presupuesto se aplica en la validación y en el executor. Una tercera
propuesta se rechaza y recibe feedback; si insiste hasta agotar reparaciones, termina ERROR.
Una decisión ABSTAIN por evidencia ausente sigue siendo distinta de ese ERROR.

Corrección del evaluator: una abstención permitida tras fallar el dato indispensable
no necesita recuperar metodología incapaz de restaurar ese dato. Se conserva la exigencia
de intentar los datos, las tools prohibidas y todas las demás condiciones del fixture.
La excepción no aplica a una conclusión con indicadores pero metodología omitida.

### known_observation: qué se sabe y qué no

Trace `df90bfb5-092f-45ac-8a9e-192f2444d4ee`:

| Paso / intento | Evidencia registrada |
|---|---|
| 1 / 0 | INVALID_DECISION; tool/source null; no observaciones previas |
| 1 / 1 | resolve_asset válido |
| 2 / 0 | get_market_history válido; historia preservada |
| 3 / 0 | calculate_technical_indicators válido; métricas preservadas |
| 4 / 0 | search_methodology, source=murphy, INVALID_DECISION |
| 4 / 1 | misma tool/source, INVALID_DECISION |
| 4 / 2 | misma tool/source, INVALID_DECISION; presupuesto agotado → ERROR |

Los cuatro rechazos tienen duplicate_tool_call=false. No hay evidencia de repetición
de historial/indicadores ni de pérdida de observaciones. El código proyecta historia,
métricas, metodología, llamadas y observaciones en cada turno. Los tres rechazos finales
ocurren después de parsear AgentDecision y reconocer search_methodology/murphy: son
compatibles con argumentos inválidos o con cambio de intent bloqueado. No son prueba de
una transición imposible. La primera invalidación ocurrió antes de existir observaciones.

**Límite forense:** el formato histórico sólo guardó INVALID_DECISION, sin etapa, campos
ni motivo concreto. Tampoco guardó las respuestas crudas. No es posible afirmar exactamente
qué violación produjo cada rechazo. Atribuirlos a caching o a cambio de intent sería una
conjetura. Esta limitación impide certificar retrospectivamente esa parte de la DoD literal.

Defecto general demostrado: feedback de reparación genérico y telemetría insuficiente.
Ahora se registran etapa, código local y errores Pydantic con campos/tipos, sin inputs,
mensajes arbitrarios o respuestas. El retry recibe esos datos y el intent actualmente
fijado. INTENT_CHANGE y duplicados siguen siendo inválidos; el modelo debe corregirlos.
Una regresión reproduce cambio de intent al pedir Murphy y verifica la corrección válida
posterior sin volver a ejecutar datos ya obtenidos. No se flexibilizó el contrato de intent.

**Confirmación real posterior:** `known_observation` pasó con ANSWER, trace
`dead0f90-ff1d-4bc7-82ec-12a327e3fc7e`. La nueva traza registró INTENT_CHANGE en la
propuesta search_methodology del paso 4, intento 0; el intento corregido fue válido.
No se repitieron historial ni indicadores. Esto reproduce el defecto general de feedback
y su recuperación; no permite adjudicar con certeza ese mismo motivo a cada rechazo antiguo.

## Invariantes de ejecución

- Toda decisión se valida antes de efectos, incluido Fake/scripted. Un rechazo no se
  registra como tool ejecutada ni se transforma silenciosamente en otra decisión.
- Identidad por tool + argumentos normalizados por su schema + estado relevante.
  Cálculos incluyen su historia de entrada; una historia nueva permite recalcular.
  Una operación exitosa equivalente se rechaza con instrucción de reutilizar el estado.
  No se añade caching persistente ni refresco implícito.
- ToolResult conserva operation_key, attempts, max_attempts, error_kind, retryable en
  ErrorInfo, can_retry y retry_budget_exhausted. La proyección agrega esos datos sin
  eliminar la representación histórica. Los traces conservan claves y hashes de argumentos;
  queries libres continúan sin publicarse en logs.
- HTTP 408/429/5xx, timeout y errores de transporte permiten un retry de tool. Errores
  de contrato, 4xx restantes y fallos desconocidos no se asumen recuperables.
- Los adapters de datos no implementan retries. El registry controla el presupuesto;
  el LLM decide si usar el intento restante. El provider LLM conserva su propio límite
  de requests por decisión (`LLM_MAX_RETRIES + 1`), sin añadir otro loop encima.
  LLM_RETRY_DELAY distingue provider_transport de decision_repair; comparten ese límite
  máximo existente, pero no se contabilizan como la misma clase de fallo.
  El agotamiento de reparación se identifica como DECISION_BUDGET_EXHAUSTED; una falla
  de disponibilidad LLM conserva LLM_FAILURE. Ambas terminan ERROR, con distinta causa.
- Resultados inválidos de tools son fallos estructurados de tool, no decisiones inválidas.
  La observación válida se añade tras normalizarla; una inválida no queda marcada exitosa.
- Fake/scripted tiene un límite de dos decisiones inválidas consecutivas. En providers
  HTTP el presupuesto de reparación se aplica dentro de decide_validated. Los límites
  agotados y MAX_AGENT_STEPS son ERROR, no abstenciones por evidencia.
- CLARIFY pide datos al usuario; ABSTAIN expresa insuficiencia; ERROR representa fallo
  técnico o de control. ANSWER conserva el contrato preexistente de cálculos disponibles
  con dimensiones INSUFFICIENT_DATA: no acredita interpretación financiera autoritativa.
  AGENT_FINISHED registra final_reason.

## Métricas y versión

El evaluator pasa a `phase2-v3` por la semántica de alternativas terminales. El dataset
sigue siendo `phase2a-v1` y el prompt sigue siendo `phase2a-v2`. Regenerar la baseline
Fake antes de comparar métricas; no comparar reportes de distinto evaluator como si
hubiesen usado el mismo criterio.

- provider_errors cuenta intentos LLM_FAILED, incluso recuperados. provider_error_cases
  cuenta runs cuyo último fallo impidió evaluar por disponibilidad. En la corrida original
  hubo un 503 recuperado en out_of_scope (PASS): por eso 1 intento, 0 casos.
- invalid_decision_rate = suma de invalid_decisions / suma de model_decision_attempts
  **entre casos PASS/FAIL**. El denominador incluye respuestas aceptadas y rechazadas,
  no intentos LLM_FAILED. Original: 10 / 77 = 0.12987012987012986.
- observed_invalid_decisions suma rechazos en todos los runs, incluso interrumpidos;
  no necesariamente comparte población con la tasa. No se cambió la fórmula.
- Una propuesta duplicada rechazada sigue contándose como propuesta inválida/duplicada;
  no se oculta por haber impedido su ejecución.
- La identidad de duplicados usa operation_key cuando está disponible: recalcular tras
  cambiar la historia no es duplicación injustificada. Traces antiguos sin esa metadata
  conservan el criterio histórico tool + argumentos.

## Hallazgo durante la nueva corrida: metodología explícita frente al plan

La primera corrida fuera del sandbox produjo dos resultados complementarios:

- `technical_ggal`, trace `1e469135-2524-441c-b4ec-ce31ec822dcf`: cuatro tools correctas,
  FINAL_ANSWER, convertido a ABSTAIN por el reporte aunque el usuario no nombra Murphy.
- `murphy_demo`, trace `5683044f-c7e8-4804-9336-2a33b115c23e`: FINAL_ANSWER conservado como
  ANSWER aunque el usuario sí pide Murphy y la evidencia es DEMO.

El reporte usaba intent.methodology (rellenado opcionalmente por el LLM) como sustituto
de una exigencia explícita del usuario. La variación de ese campo cambiaba el terminal
sin cambiar los datos ni la solicitud. Corrección en el reporte: detectar la referencia
explícita Murphy/Graham en la solicitud, independientemente del plan propuesto. No cambia
la elección de tools, el prompt ni las dimensiones INSUFFICIENT_DATA. Cuatro regresiones
cubren petición explícita/no explícita y plan con/sin metodología. Es conservador ante una
mención ambigua del autor; no interpreta negaciones complejas.

La nueva telemetría también observó `reason` faltante e INTENT_CHANGE en murphy_demo,
y JSON inválido/reason faltante en market_failure; las reparaciones válidas prosiguieron.
Eso confirma utilidad del diagnóstico, pero no recupera el contenido de rechazos históricos.

## Validación y cierre

Suite final: 249 PASS, 4 pruebas externas omitidas, 2 warnings de deprecación de
Starlette/HTTPX. Ruff, format check y pip check: OK. Smoke Uvicorn normal con Fake:
GET /health=200, POST /agent/run=200 CLARIFY. Incluye replay semántico
de las 14 trayectorias antes verdes. No son respuestas crudas del modelo: se conservan
acciones y argumentos seguros del trace, y se reconstruyen query/intent desde el fixture.
Los escenarios están en `tests/fixtures/phase2_successful_actions.json`.

La ejecución real se realiza después de la suite con el mismo provider/modelo, prompt v2,
17 × 1, intervalo 15 s, delay 0 y cooldown 30. Se interrumpió el intento dentro del sandbox
tras errores de transporte sin HTTP; se reinició fuera de él y Gemini respondió. El runner
no permitía seleccionar casos: se documentó esa limitación antes de agregar `--case-id`
(repetible) para verificaciones focalizadas. Cada selección usa las definiciones originales
y produce un reporte separado con su cantidad real de casos. Nunca se presenta como 17 × 1.

La corrida completa utilizó el código cargado al iniciarla, anterior a la corrección
del reporte descrita arriba. Las verificaciones de esa corrección se registran por separado.

### Corrida completa terminada (antes de la corrección del reporte)

Archivo: `real_llm_gemini_3_5_flash_lite_phase2a-v2_20260915T233521420665Z.json`.
17 × 1, 14 PASS / 3 FAIL. **Los tres fallos originales pasaron**:

| Caso | Resultado | Trace |
|---|---|---|
| unknown | PASS / CLARIFY | d8c27870-33bb-440e-8c02-ab8a9670ce01 |
| market_failure | PASS / ABSTAIN | bda9c986-92dd-4193-aae6-51dd9fbaba54 |
| known_observation | PASS / ANSWER | dead0f90-ff1d-4bc7-82ec-12a327e3fc7e |

market_failure realizó dos intentos de historial; tras el segundo HTTP_503, la observación
registró can_retry=false y retry_budget_exhausted=true y el modelo eligió ABSTAIN.

Fallos de esta corrida: technical_ggal y murphy_demo por el contrato del reporte descrito
arriba, y full porque el modelo eligió ABSTAIN (el fixture espera ANSWER), con ambas ramas
consultadas. **full no fue una conversión del reporte**. Se conserva como FAIL; no se
convierte ABSTAIN en ANSWER ni se amplía el expected para obtener verde.

| Métrica de la corrida completa | Valor |
|---|---:|
| task_success_rate | 0.8235294117647058 |
| tool_selection_accuracy | 1.0 |
| forbidden_tool_violations | 0 |
| duplicate_tool_call_rate | 0 |
| invalid_decision_rate | 0.11538461538461539 (9/78) |
| clarification_correctness | 1.0 |
| abstention_correctness | 0.8125 |
| max_steps_exceeded | 0 |
| provider_error_cases / provider_errors | 0 / 1 |
| average_steps | 4.0588235294117645 |
| average_latency (ms, incluye throttling) | 73140.22472940954 |

El error recuperado fue HTTP 503 en tool_text, que terminó PASS.

Baseline Fake regenerada con el nuevo scorer: 15/17; conserva los fallos históricos
out_of_scope y contradiction. Se archivó la anterior en fake_baseline_before_phase2_v3.json.
No se presenta Fake como evidencia de comportamiento LLM.

### Verificación focalizada sobre código final

Se seleccionaron technical_ggal, murphy_demo y full mediante --case-id, conservando modelo,
prompt, cuotas y fixtures. Reporte:
`real_llm_gemini_3_5_flash_lite_phase2a-v2_20260915T234140119857Z.json`.
No sustituye silenciosamente el anterior ni se presenta como una corrida completa de 17 casos.

| Caso | Resultado | Trace |
|---|---|---|
| technical_ggal | PASS / ANSWER | 558aef3f-79a4-47a3-b2c8-b7357053d012 |
| murphy_demo | PASS / ABSTAIN | a36b8219-aaac-439f-95bd-3f855a72c27d |
| full | PASS / ANSWER | ccc5c7ca-300c-43ea-88aa-c9179efff5de |

3/3 PASS; task_success_rate=1.0, tool_selection_accuracy=1.0,
forbidden_tool_violations=0, duplicate_tool_call_rate=0, invalid_decision_rate=0,
abstention_correctness=1.0, max_steps_exceeded=0, provider_error_cases=0,
provider_errors=1 (recuperado), average_steps=6.0, average_latency=105497.52879999384 ms.
El incidente recuperado fue un timeout en technical_ggal.
clarification_correctness=null porque la selección no incluye casos de clarificación.
Son métricas del subconjunto, **no una estimación de tasa global 17/17**.

La tabla automática Fake/Real del runner ahora se omite si las poblaciones de casos o
repeticiones difieren. Esta última corrección es sólo de presentación y tiene test offline;
no modifica los JSON ni los resultados de las ejecuciones reales ya terminadas.

### Cobertura final por caso

| Caso | Última verificación | Fuente |
|---|---|---|
| technical_ggal | PASS / ANSWER | Focalizada |
| fundamental_pamp | PASS / ABSTAIN | Completa |
| ambiguous | PASS / CLARIFY | Completa |
| unknown | PASS / CLARIFY | Completa |
| technical_alua | PASS / ANSWER | Completa |
| murphy_demo | PASS / ABSTAIN | Focalizada |
| market_failure | PASS / ABSTAIN | Completa |
| fundamental_plain | PASS / ABSTAIN | Completa |
| full | PASS / ANSWER | Focalizada |
| known_observation | PASS / ANSWER | Completa |
| short_history | PASS / ABSTAIN | Completa |
| out_of_scope | PASS / ABSTAIN | Completa |
| contradiction | PASS / CLARIFY | Completa |
| irrelevant_instruction | PASS / ANSWER | Completa |
| invent_data | PASS / ABSTAIN | Completa |
| ignore_limits | PASS / ABSTAIN | Completa |
| tool_text | PASS / ANSWER | Completa |

No se fusionan estas filas para fabricar un reporte de una corrida que no ocurrió.
Los 14 recorridos originalmente verdes tienen tests de replay y evidencia PASS posterior,
incluida la revalidación de los afectados por el error del reporte y la variación del modelo.

## Cambios y deuda restante

Archivos de esta tarea (se preservaron los cambios previos del árbol):

| Archivos | Cambio |
|---|---|
| `src/merval_agent/agents/equity_agent.py` | Validación previa, límites, normalización y trazabilidad |
| `src/merval_agent/agents/decisions.py`, `validation_feedback.py` | Motivos de rechazo y feedback seguro |
| `src/merval_agent/agents/report.py` | Metodología explícita frente a plan del modelo |
| `src/merval_agent/agents/state.py` | Preservación atómica de observaciones |
| `src/merval_agent/tools/registry.py`, `operations.py` | Identidad y presupuesto por operación |
| `src/merval_agent/domain/models.py`, `errors.py` | Metadata de ToolResult y errores tipados |
| `src/merval_agent/adapters/llm/context.py`, `http_provider.py` | Contexto de operaciones y reparación estructurada |
| `src/merval_agent/evaluation.py` | Semántica del scorer y versión |
| `scripts/eval_real_llm.py` | Selección de casos y comparación de poblaciones |
| `tests/unit/test_phase2_closure.py` | Regresiones y replays parametrizados |
| `tests/unit/test_agent.py`, `test_recovery.py` | Expectativas de agotamiento/control corregidas |
| `tests/fixtures/phase2_successful_actions.json` | Acciones semánticas de los 14 PASS históricos |
| `README.md`, `docs/phase2a-real-llm.md`, `docs/phase2-closure.md` | Estado, auditoría y resultados |

Los JSON de resultados y SQLite quedan como artefactos locales; no se hizo commit.

- Loop/validator: validación previa para todos los providers, límites de reparación,
  final_reason, separación de agotamiento de decisiones y fallos de disponibilidad.
- Tool executor/state: identidad normalizada, presupuesto de operaciones, errores tipados,
  preservación atómica de observaciones válidas, diagnósticos en contexto y trace.
- Provider HTTP: feedback estructurado sin filtrar secretos; sin cambio de modelo o prompt.
- Reporte: exigencia metodológica explícita separada del plan opcional del modelo.
- Evaluator/CLI: alternativas legítimas de tools, claves de duplicación con estado relevante,
  versión phase2-v3, selección de casos y prevención de comparaciones de distintas poblaciones.
- Tests: 36 verificaciones nuevas parametrizadas (incluidos 14 replays), más actualización
  justificada de cuatro expectativas de tests de control. No se editaron los 17 fixtures.

Riesgos: el LLM sigue siendo no determinista (full eligió ABSTAIN y luego ANSWER); el
presupuesto limita y hace visibles los errores, no garantiza cero rechazos futuros.
La mención de Murphy/Graham se detecta conservadoramente y no interpreta negaciones
complejas. DEMO y documentos no validan interpretación financiera. No se añadieron
caching persistente ni refresco automático; un nuevo run obtiene su propio estado.

La reconstrucción exacta de las cuatro invalidaciones antiguas sigue imposible sin una
captura adicional de aquella ejecución. No se atribuyen retrospectivamente motivos inventados.
Por esa condición explícita no se declara cumplida la DoD estricta sin salvedades, aunque
la implementación y las verificaciones funcionales solicitadas estén completadas.

Hashes conservados:

- Dataset: `88b6589247aa51588ca97874988d906fa59a01da6ee21c6835fdef9625605f7d`.
- Prompt v2: `10b8c778227a69c9aec29accd8316238467fc6ed6c2654dd17109e75de42f7f0`.

Commit sugerido (no ejecutado):
`fix(agent): close phase 2 decision loop and evaluation edge cases`
