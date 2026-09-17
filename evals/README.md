# Estado actual de evaluación (16/09/2026)

Dataset `technical-v3`, evaluator `phase2-v4`: los pedidos técnicos ordinarios ya no
exigen búsqueda de Murphy ni abstención técnica si hay datos suficientes. Fallos de fuente
esperan ERROR/SOURCE_ERROR. Se conservan los 17 casos, sus restricciones de alcance y los
tests de trazas históricas. Ver [verificación técnica](../docs/technical-v3.md).
Las cifras y versiones de las secciones siguientes son antecedentes históricos.

# Evaluaciones iniciales

Comparación histórica de prompts y suficiencia metodológica:
[phase2a-v1 frente a phase2a-v2](../docs/prompt-phase2a-v2.md).

Baseline Ollama / LM Studio con el mismo adapter y evaluator:
[configuración y validación local](../docs/local-llm.md).

Ejecutar `python -m pytest tests/integration/test_evals.py -q -s`.
Dataset independiente, ejecutor offline con transporte HTTP fake y provider fake.
Los resultados miden comportamiento del simulador y contratos, **no calidad de un LLM real**.
Las siete tareas imprimen JSON con éxito, selección de tools, llamadas innecesarias,
pasos, latencia, errores y corrección de abstención. No se exige orden fijo.

En Fase 2 agregar evaluador con provider real y fuentes congeladas, evaluación humana de
fidelidad/citas, casos adversariales y umbrales de aceptación. `tool_selection_accuracy`
es precisión del conjunto de tools; el éxito exige además todas las esperadas.

Cada caso declara `expected_tools`, `forbidden_tools`, estados permitidos,
`expected_asset` (null para desconocidos) y dimensiones en `expected_abstention`.
Incluye falla HTTP simulada y Murphy DEMO. El reporte agregado imprime `cases`, `passed`,
`failed`, `tool_selection_accuracy`, `forbidden_tool_violations` y `average_steps`.
En el agregado, accuracy es la proporción de casos con todas las tools requeridas y ninguna
prohibida; por caso se conserva la precisión anterior. No son métricas de inteligencia.

`tests/integration/test_trace_baseline.py` fija cinco golden traces semánticas:
técnico GGAL, fundamentos PAMP, XXXX, Murphy DEMO y falla Market Tracker.
Compara secuencia de eventos y pasos sin fijar UUID, fechas ni latencias.
Ese orden caracteriza al fake actual, no impone un workflow al agente.

## Fase 2A implementada: runner separado

`real_llm_dataset.jsonl` contiene 17 casos, incluyendo los 7 originales. Ejecutar
`python scripts/eval_real_llm.py --fake --runs 3` para comparación offline o, con
credenciales y RUN_LLM_TESTS=1, `python scripts/eval_real_llm.py --runs 3`.
Los datos de tools son fixtures sintéticos, incluso si su metadata interna dice live.
El LLM es externo solo en el segundo comando. `scripts/run_real_llm.py` separa la prueba
con servicios de datos externos.

El scorer no exige orden; acepta alternativas documentales y registra propuestas prohibidas
rechazadas, duplicados, recuperación, latencia y usage. Métricas, denominadores y límites:
[guía Fase 2A](../docs/phase2a-real-llm.md). Resultados locales en `evals/results/` ignorados
por Git. Salida 1 indica casos fallidos, no pérdida del reporte.

Fake ampliado: 45/51 éxitos (17 × 3). Falla fuera de alcance y contradicción; las evals
originales mantienen 7 PASS. No hay resultados externos todavía. El trabajo futuro de
fidelidad narrativa citado arriba no se considera validado por estos tests.

## Gemini nativo

El runner compartido ahora respeta LLM_PROVIDER=compatible o gemini; rechaza fake salvo
`--fake`. Los reportes incluyen el provider seleccionado y reasoning_tokens opcional.
Con reasoning informado no se estima costo usando solamente tarifas input/output.
La prueba mínima externa Gemini pasó; GGAL con servicios externos terminó ERROR por 503/429
tras resolver el activo y consultar mercado. No se ejecutó el dataset completo Gemini.
Evidencia y límites: [Gemini nativo](../docs/gemini-native.md).

## Evaluador real: calidad y disponibilidad separadas

Versión del evaluator: `phase2a-v2`. Prompt y dataset conservan sus versiones.
Cada fila de caso/repetición contiene `result`:

- `PASS`: resultado evaluable que cumple las condiciones semánticas.
- `FAIL`: resultado evaluable que no las cumple, incluyendo agotamiento de decisiones inválidas.
- `PROVIDER_ERROR`: el run terminó ERROR/LLM_FAILURE con último intento LLM_FAILED.
  Incluye 429, 5xx, timeout y otros fallos de transporte/protocolo. No se penaliza la ausencia
  de tools que el modelo no pudo llegar a seleccionar.
- `NOT_EVALUATED`: fallo interno/persistencia u otro ERROR sin evidencia suficiente para
  atribuirlo al modelo o provider. No equivale a una abstención financiera del agente.

Un error recuperado del provider NO invalida un run completado: puede ser PASS o FAIL.
Los errores de tools permanecen dentro de las condiciones semánticas del caso.

`total_cases` cuenta filas (casos × repeticiones); `case_count` conserva los casos únicos.
`evaluated_cases = passed_cases + failed_cases`. La partición completa incluye también
`provider_error_cases` y `not_evaluated_cases`. `task_success_rate = passed_cases / evaluated_cases`.
Si no hay casos evaluables, las tasas de calidad quedan null, no 0% ni 100%.

Tool accuracy, llamadas prohibidas, tasas de decisiones inválidas/duplicados, abstención,
clarificación, average_steps y average_latency usan solamente PASS/FAIL. La tasa de
invalidación excluye los intentos LLM_FAILED de su denominador: un fallo HTTP no es una
respuesta del modelo. average_latency continúa expresada en milisegundos.

La disponibilidad no se oculta:

- provider_error_rate = provider_error_cases / total_cases.
- provider_errors cuenta todos los intentos LLM_FAILED, incluidos los recuperados.
- observed_forbidden_tool_violations / observed_invalid_decisions / observed_duplicate_tool_calls
  conservan los incidentes efectivamente observados incluso en runs interrumpidos.
- attempted_average_steps / attempted_average_latency incluyen todas las ejecuciones.
- Tokens y costos observados conservan todas las ejecuciones; no se inventa usage faltante.

Las filas interrumpidas usan task_success/tools_correct=null. `provider_error` conserva los
HTTP statuses y códigos en orden, sin mensajes ni payloads del servidor. Un timeout tiene
HTTP status null. Por ejemplo:

```json
{"case":"fundamental_plain","result":"PROVIDER_ERROR","provider_error":{"http_statuses":[429,503,429],"codes":["RESOURCE_EXHAUSTED","UNAVAILABLE","RESOURCE_EXHAUSTED"]}}
```

### Throttling secuencial

```powershell
python scripts/eval_real_llm.py --runs 1 --llm-min-interval-seconds 15 --delay-seconds 5 --provider-error-cooldown-seconds 30
```

Conserva el opt-in RUN_LLM_TESTS=1. Los tres parámetros son opcionales, finitos y no negativos;
por defecto 0. Se espera entre casos/repeticiones, nunca antes del primero ni después del
último. Si el run anterior terminó PROVIDER_ERROR con último HTTP 429 o código
RESOURCE_EXHAUSTED, se aplica `max(delay, cooldown)`; un 503 terminal o un 429 recuperado
no activa cooldown. No hay retries automáticos del caso completo. Los retries internos
siguen perteneciendo al provider.

Fake ignora todas las esperas y reporta valores efectivos 0. El JSON registra delay_seconds,
provider_error_cooldown_seconds, delay_policy y delay_before_run_seconds por fila. Las
esperas entre runs no se suman a su latency_ms.

- `--llm-min-interval-seconds`: protege RPM espaciando el inicio de **cada request LLM**,
  incluidos pasos dentro de un mismo Agent.run(), retries internos, casos y repeticiones.
  Un hook HTTP exclusivo del evaluador comparte un reloj monotónico durante toda la
  evaluación secuencial. El primer request sale sin espera; después sólo se espera el
  tiempo faltante. Por ejemplo, con intervalo 15 y backoff de 0,5 s tras un 503 inmediato,
  el siguiente intento espera los 14,5 s restantes. El valor 0 desactiva el hook.
- `--delay-seconds`: separa casos/repeticiones, sin proteger requests dentro del run.
- `--provider-error-cooldown-seconds`: pausa adicional ante un 429 terminal, combinada
  con delay mediante el máximo indicado arriba. Ese tiempo también cuenta como tiempo
  transcurrido para el intervalo entre requests.

El reporte registra `llm_min_interval_seconds` efectivo, `provider`, `model` y
`rate_limit_strategy` (`sequential_http_request_start_interval` o `disabled`). No cambian
las definiciones ni los denominadores de métricas. La latencia del run y del intento
incluye las esperas de throttling ocurridas dentro de ellos. No se limita el cliente de
fixtures ni se modifica el provider fuera de evals. El límite se comparte sólo dentro
de esta ejecución: no coordina otros procesos que usen la misma cuota.

Exit codes: 0 si todos los casos pasan; 1 si hay FAIL funcional; 2 si solo hay evaluación
incompleta por PROVIDER_ERROR/NOT_EVALUATED o no hay casos. El reporte siempre distingue las
categorías aunque coexistan. No comparar automáticamente una baseline Fake de una versión
anterior del evaluator: regenerarla con --fake para usar los mismos denominadores.

Esta extensión se verificó exclusivamente offline; no ejecuta ni acredita nuevas evals reales.
