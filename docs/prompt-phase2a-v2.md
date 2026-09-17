# Prompt phase2a-v2: suficiencia metodológica

## Motivación y alcance

Evidencia real reportada por el usuario: Gemini 3.5 Flash-Lite y Qwen 3.5 4B vía
Ollama completan resolve_asset, get_market_history, calculate_technical_indicators
y FINAL_ANSWER, pero omiten search_methodology en análisis técnico.
Esta modificación no ejecutó ninguno de esos modelos ni afirma corregir aún esa conducta.

v2 conserva íntegro el texto v1 y añade condiciones explícitas de suficiencia:

- Historia e indicadores son datos calculados, no una interpretación técnica
  metodológicamente completa. Murphy requiere evidencia de search_methodology;
  si falta y puede obtenerse, considerar esa búsqueda antes de concluir, incluso
  cuando el usuario pide análisis técnico sin nombrar Murphy.
- Graham se aplica a la interpretación fundamental pertinente, sin cruzar ramas.
  Documentos no equivalen a métricas financieras extraídas/verificadas.
- Buscar, obtener resultados y tener evidencia suficiente son situaciones distintas.
  DEMO, resultados vacíos y errores no permiten inventar interpretación autoritativa.
  La indisponibilidad admite abstención segura; no exige retries indefinidos.
- No hay secuencia de tools impuesta. El modelo puede buscar metodología antes o
  después de obtener datos, según objetivo, estado, precondiciones y presupuesto.

No cambia EquityAgent, AgentDecision, tools, policies, RAG, contexto del estado ni
dataset. No hay búsqueda automática ni routing adicional. FINAL_ANSWER puede seguir
exponiendo cálculos con dimensión INSUFFICIENT_DATA y sin conclusión direccional;
INSUFFICIENT_DATA no es una acción de AgentDecision. La metodología disponible sigue
siendo DEMO; las solicitudes explícitas Murphy/Graham requieren abstención sin fuente real.

## Selección y trazabilidad

`AGENT_PROMPT_VERSION` ahora selecciona texto real en ambos providers HTTP; antes sólo
etiquetaba metadata. `context.py` conserva v1 y registra ambas versiones. Una versión
desconocida se rechaza antes del request, para evitar experimentos mal etiquetados.
Se mantiene v1 como default histórico. Para activar v2 en API o runner:

```powershell
$env:AGENT_PROMPT_VERSION = 'phase2a-v2'
```

También puede configurarse en `.env`. Reiniciar Uvicorn para aplicar el cambio.
En el evaluator, `--prompt-version` tiene precedencia sobre la configuración.
Ejemplos **para ejecución manual**, con provider/modelo ya configurados:

```powershell
$env:RUN_LLM_TESTS = '1'
# Local, sin throttling:
python scripts/eval_real_llm.py --runs 1 --prompt-version phase2a-v1 --llm-min-interval-seconds 0
python scripts/eval_real_llm.py --runs 1 --prompt-version phase2a-v2 --llm-min-interval-seconds 0
# Gemini: repetir con su configuración y el intervalo apropiado a su cuota:
python scripts/eval_real_llm.py --runs 1 --prompt-version phase2a-v1 --llm-min-interval-seconds 15
python scripts/eval_real_llm.py --runs 1 --prompt-version phase2a-v2 --llm-min-interval-seconds 15
```

Cada JSON incluye prompt_version y system_instructions_sha256 (UTF-8 del texto del
sistema, sin schema ni contexto variable). El filename incluye la versión del prompt.
Los eventos LLM conservan prompt_version y prompt_hash del request completo: éste sí
incluye schema, estado y mensajes de retry. Fake no consume prompt y reporta hash null.
El archivo fake_baseline.json sigue siendo único; guardar una copia si se desean archivar
múltiples corridas Fake, aunque su comportamiento no depende de la versión del prompt.

## Evaluación y comparación

Dataset phase2a-v1 (17 casos) y evaluator phase2a-v2 conservan sus versiones y métricas:
**versión del prompt y versión del evaluator son campos independientes**.
El scorer ya exige search_methodology en los casos pertinentes, sin imponer orden.
Un terminal con indicadores pero sin metodología sigue siendo FAIL de selección de tools,
aunque el reporte preserve INSUFFICIENT_DATA y sea seguro. No se convierte en decisión
inválida ni se añade una política que obligue a buscar.

Las pruebas de abstención usan el caso Murphy que ya admite ABSTAIN y simulan
fallo/ausencia/DEMO del retriever. No se amplían silenciosamente los estados permitidos
de otros casos para hacer pasar v2. Seguridad del resultado y éxito de tarea son criterios
distintos: una abstención prematura puede ser segura y seguir fallando el dataset.

Comparar v1 frente a v2 dentro del mismo modelo/provider, response_format, datos, límites,
retries, repeticiones y throttling. Separar después el efecto del provider/modelo. Usar
prompt_version/hash, dataset_version y evaluator_version para identificar cada corrida.
Revisar task_success_rate, tool_selection_accuracy, forbidden/duplicate calls, invalid
decisions, provider errors, pasos, latencia y traces. El texto adicional puede aumentar
tokens y latencia; no atribuir esa diferencia exclusivamente a calidad del modelo.

## Verificación offline

Tests con MockTransport verifican selección real del texto para Compatible y Gemini,
preservación por hash de v1, metadata/CLI, omisión metodológica detectada por el scorer,
elección simulada de búsqueda en distintos órdenes, abstención segura ante ausencia/fallo,
separación de ramas y documentos sin métricas inventadas. Fake conserva 15/17 éxitos
con idénticas métricas para ambas versiones al fijar la latencia del test.

Estos tests prueban contratos y recorridos simulados, no que un modelo real obedezca v2.
La comparación real de Gemini y Qwen queda pendiente de ejecución manual.
