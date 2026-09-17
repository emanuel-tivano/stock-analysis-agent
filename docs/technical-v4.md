# Technical v4 — semántica y resiliencia

Verificación: 16 de septiembre de 2026. Iteración sobre technical-v3, sin RAG, fundamentales, multiagente ni HITL nuevos. No se modificó `.env`, no se agregaron dependencias ni nombres de modelos obligatorios. El identificador de prompt configurado sigue siendo `technical-v3`; esta versión identifica las reglas y políticas del sistema.

## Evidencia inicial y causas raíz

Se leyeron la consigna oficial TFI, las pautas de entrega, `audit-2026-09-16.md`, `technical-v3.md`, los componentes de v3 y las trazas SQLite recientes antes de modificar código. La línea base fue **366 aprobados, 0 fallidos, 4 omitidos**. La consigna no exige que la redacción final provenga del LLM: permite entregar el análisis determinista cuando la orquestación ya obtuvo y calculó los datos.

1. **MIXED ambiguo:** v3 combinaba RSI, MACD/cero y MACD/señal como polaridades equivalentes. Un MACD negativo pero superior a su señal se enfrentaba a los indicadores bajistas y arrastraba la conclusión global a MIXED. Se separó territorio del momentum de su mejora relativa y se dio precedencia a la tendencia.
2. **ALUA PARTIAL:** no era causado por `average_volume=null`. La traza `fdabf691-03e3-4062-90ea-e825ccf7446b` tenía una fila descartada; GGAL, traza `f52d7dd1-444d-4427-884f-9af8abdd9f36`, ninguna. Una consulta real posterior a `/history` confirmó que ALUA, el **2026-04-22**, informa apertura 952,5, máximo 964, mínimo 942 y cierre 964,5: el cierre supera al máximo. Se conserva el descarte y PARTIAL por calidad de la serie, con motivo explícito. No se fuerza COMPLETE ocultando esta anomalía.
3. **Volumen:** las reglas de precios ya podían completar un análisis con null. Ahora se explicita su carácter opcional y el adaptador también normaliza un campo omitido a null, sin descartar una fila de precios válida. La falta de volumen limita la confirmación por volumen y la confianza, no la completitud de precios.
4. **Fechas:** el enriquecimiento existente añadía OHLC de `/quote`, pero no exponía claramente el corte de cada cálculo ni una alternativa que excluyera la cotización. Se agregaron una política configurable, procedencia temporal y métricas separadas del histórico.
5. **Gemini:** las trazas mostraban 429/503 con esperas de 500/1000 ms, sin Retry-After ni jitter. El agotamiento del proveedor terminaba en ERROR aunque ya existieran cálculos utilizables. Ahora los intentos son limitados y observables y se conserva el análisis determinista cuando corresponde.

## Reglas finales

No hay suma de pesos numéricos ni doble voto del histograma. La precedencia es jerárquica:

| Componente | Regla y peso funcional |
|---|---|
| Tendencia | Precio/SMA20, precio/SMA50, SMA20/SMA50 y EMA12/EMA26 tienen igual relevancia. Si hay direcciones opuestas, MIXED; no hay mayoría que oculte el desacuerdo. Neutrales y faltantes no anulan una dirección disponible. |
| RSI14 | Más de 50: sesgo alcista; menos de 50: bajista. Sobreventa solamente <=30; sobrecompra >=70. Un RSI de 39 no es sobreventa. |
| MACD/cero | Define territorio positivo o negativo del momentum. Se combina con RSI para contrastar la tendencia. |
| MACD/señal | Define mejora o debilitamiento relativo. MACD negativo sobre señal: IMPROVING_BUT_BEARISH; positivo debajo: WEAKENING_BUT_BULLISH. No confirma una reversión. |
| Histograma | Explica MACD menos señal y su magnitud; no agrega otro voto de la misma evidencia. Una lectura no demuestra expansión ni un cruce reciente. |
| Variación del período | Contexto de toda la muestra; no vota la dirección actual. |
| Volumen | Complementario. Un promedio aislado no confirma dirección; null significa no evaluable. |
| Estado global | Predomina tendencia. MIXED si la propia tendencia discrepa, si RSI/MACD-cero direccionales se oponen a ella o si una tendencia neutral tiene momentum mixto. Sin tendencia disponible se usa el momentum de base. Los conflictos se enumeran con sus indicadores. |
| Confirmación | ALIGNED requiere completitud, acuerdo de tendencia y momentum de base, relación MACD/señal compatible y ausencia de cotización provisional incorporada. En otro caso UNCONFIRMED; sin evidencia, UNAVAILABLE. Alineación no significa certeza predictiva. |

`assessment.momentum` conserva la agregación anterior para consumidores existentes; la interpretación precisa está en `momentum_state`. `technical.status` expresa conclusión técnica; `assessment.status` expresa calidad/suficiencia. La narrativa se genera desde estas estructuras tipadas e incluye explicaciones individuales, conflictos y confirmación. El LLM no escribe ni modifica esos campos calculados.

### Completitud centralizada

- **COMPLETE:** precio válido, todos los indicadores requeridos disponibles con ventanas suficientes y ninguna fila descartada.
- **PARTIAL:** al menos 15 observaciones y precio utilizable, pero falta algún indicador requerido o hubo filas inválidas descartadas. Los motivos quedan en `completion_reasons`.
- **INSUFFICIENT_DATA:** sin serie/cálculos utilizables, menos de 15 observaciones o conclusión no determinable.
- Ventanas requeridas: SMA20=20, SMA50=50, EMA12=12, EMA26=26, RSI14=15, MACD=26, señal e histograma=34. El volumen es opcional. La variación del período es complementaria.
- Se preservan las categorías existentes INVALID_DATA, STALE y UNVERIFIED para no presentar datos inválidos, antiguos o simulados como evidencia actual.
- **ERROR de ejecución** diferencia fallo de mercado, cálculo (`CALCULATION_FAILED`), proveedor, validación estructurada e interno. No es una dirección técnica ni una insuficiencia de ventana.

Los tests verifican que GGAL y ALUA obtienen la misma completitud ante idéntica disponibilidad y calidad. Los datos reales de ambos no tienen la misma calidad: ALUA contiene la fila OHLC inválida mencionada.

## Política de cotización provisional

`MARKET_QUOTE_POLICY=include_provisional_ohlc` conserva el comportamiento previo explícitamente: solo se incorpora una cotización nueva y validada cuando el proveedor aporta OHLC real; el volumen puede ser null. No se fabrica OHLC desde un precio puntual. `history_only` conserva la quote separada y excluida de todos los indicadores.

`assessment.basis` informa corte del histórico, corte efectivo de indicadores, recepción de ambas fuentes, fecha/hora observada de quote, precio, carácter provisional, inclusión y política aplicada. `as_of` corresponde a la serie utilizada. Con quote incorporada, `history_only_metrics` permite comparar los valores calculados exclusivamente con el histórico. Con quote excluida, `metrics.current_price` sigue siendo el último cierre histórico y `basis.quote_price` contiene la cotización separada.

En la verificación real: histórico hasta **2026-09-15**, indicadores enriquecidos hasta **2026-09-16**. `history_closure=UNVERIFIED`: el corte histórico no certifica por sí solo el cierre oficial. Una quote nueva no rejuvenece un histórico antiguo. Se conserva la tolerancia de vigencia y la función de calendario aislada, sin integrar un calendario BYMA completo.

## Reintentos, fallback y degradación

Se detectan HTTP 429/RESOURCE_EXHAUSTED como RATE_LIMITED. Solo evidencia estructurada de cuota diaria (`google.rpc.QuotaFailure`) permite QUOTA_EXHAUSTED; no se infiere agotamiento diario de un 429 aislado. Los errores transitorios son UNAVAILABLE y los de structured output, INVALID_OUTPUT.

Por solicitud al LLM se conserva el presupuesto configurado existente (0–2 reintentos). El backoff usa `min(0.5 * 2**retry, 2)` segundos más jitter proporcional, con reloj, aleatoriedad y espera inyectables. Retry-After acepta segundos o fecha HTTP. Si la espera exigida supera `LLM_MAX_RETRY_WAIT_SECONDS` (30 por defecto), se registra LLM_RETRY_DEFERRED y se devuelve control: no se reintenta antes de lo permitido ni se bloquea sin límite. Cada intento informa duración, HTTP, clasificación y validación, sin cuerpos sensibles ni claves.

La política concuerda con la [documentación de errores de Gemini](https://ai.google.dev/gemini-api/docs/troubleshooting) y sus [límites de uso](https://ai.google.dev/gemini-api/docs/rate-limits). La disponibilidad de alias se verifica mediante [Models API](https://ai.google.dev/api/models), sin asumir nombres nuevos.

El cambio entre modelos está **deshabilitado por defecto**. Requiere `LLM_FALLBACK_ENABLED`, `LLM_FALLBACK_MODEL` distinto del principal y pertenencia a `LLM_ALLOWED_FALLBACK_MODELS`. Solo aplica a indisponibilidad/cuota/rate limit; no oculta errores de configuración o validación. Hay un único modelo alternativo, con el mismo contrato. Tras cambiar, se mantiene para ese run; el siguiente run comienza con el principal. La traza conserva el fallo principal y el evento de cambio.

`LLM_DETERMINISTIC_FALLBACK=true` permite entregar ANSWER si el fallo recuperable ocurre **después** de obtener cálculos técnicos COMPLETE/PARTIAL. No inventa resultados si falló antes de conseguirlos; tampoco convierte un structured output inválido en éxito. Solicitudes con otras metodologías no se degradan como si hubieran sido satisfechas.

`generation` informa modo final, estado LLM, proveedor, modelo solicitado, alias realmente seleccionado, versión devuelta por el proveedor cuando existe, número total de intentos del run, Retry-After, uso de modelo alternativo y advertencias. La suma de intentos incluye todas las decisiones, no solo los reintentos de una llamada.

## Contrato y archivos de esta iteración

Se conservan campos y categorías anteriores. Se agregan `generation`, `assessment.momentum_state`, `confirmation`, `completion_reasons`, `basis` y `technical.history_only_metrics`; `enrichment_status` acepta `excluded`. La corrección semántica puede cambiar un resultado antes MIXED a BEARISH/BULLISH. Consumidores que prohíben propiedades adicionales deben actualizar su esquema. No cambia el endpoint.

Archivos implementados o extendidos en esta iteración (el repositorio ya tenía otros cambios sin commit):

- Dominio: `src/merval_agent/domain/{models,technical_assessment,errors}.py`.
- Proveedores: `src/merval_agent/adapters/market_tracker.py`, `src/merval_agent/adapters/llm/{http_provider,gemini,fallback}.py`.
- Orquestación: `src/merval_agent/agents/{equity_agent,report,generation}.py`, `src/merval_agent/tools/registry.py`, `src/merval_agent/{bootstrap,config}.py`.
- Operación: `.env.example`, `scripts/{show_trace,validate_technical_live,acceptance_llm_failure}.py`.
- Tests: `tests/unit/test_technical_v4.py`, `tests/integration/test_gemini_resilience.py`; inyección de aleatoriedad determinista en `test_gemini_provider.py`, `test_evaluation_rate_limit.py` y `test_phase2a_regressions.py`.
- Documentación: `README.md`, `docs/architecture.md`, este documento y `src/merval_agent/skills/merval_equity_analysis/references/contracts.md`.

## Validación y comandos

Comandos ejecutados desde el repositorio, usando `.venv\Scripts\python.exe`:

```powershell
# Línea base y suite final; servicios externos mockeados
$env:RUN_LLM_TESTS='0'; $env:RUN_LIVE_TESTS='0'
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -ra
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
git diff --check
.\.venv\Scripts\python.exe scripts/smoke_api.py
.\.venv\Scripts\python.exe -X utf8 -c "from merval_agent.evaluation import evaluate; from merval_agent.config import Settings; r,p=evaluate(Settings(_env_file=None),fake=True,output_dir='evals/results/technical-v4/simulator'); print(r['metrics']); print(p)"
.\.venv\Scripts\python.exe -X utf8 scripts/acceptance_llm_failure.py

# Integración real autorizada, independiente de los 4 tests opt-in omitidos
$env:RUN_LLM_TESTS='1'; $env:RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -X utf8 scripts/validate_technical_live.py --ticker GGAL --ticker ALUA --ticker YPFD --ticker XXXX --check-model gemini-3.6-flash
.\.venv\Scripts\python.exe -X utf8 scripts/show_trace.py cd3cecda-39cc-49ae-a9ee-1b952cea57c0 --database evals/results/technical-v4/live-20260916T224609Z/traces.sqlite3
```

Resultados finales: **393 aprobados, 0 fallidos, 4 omitidos**, 2 warnings de dependencias; 27 tests más que la línea base, sin eliminar pruebas anteriores. Ruff aprobado, formato aprobado (**92 archivos**), dependencias coherentes y diff sin errores de whitespace (Git avisa conversión LF/CRLF). Simulador **17/17**. Smoke Uvicorn: health 200 y agent/run 200/CLARIFY. No se midió porcentaje de cobertura de líneas; se preservó la suite y se amplió la cobertura funcional.

Los tests nuevos cubren las combinaciones direccionales, RSI sin sobreventa, volumen ausente/omitido, igualdad por ticker, calidad OHLC, quote incluida/excluida, Retry-After/jitter/reloj, máximo de intentos, cuota vs validación, modelos alternativos explícitos, modelo efectivo, degradación, contrato API, persistencia y ausencia de secretos. La prueba de indisponibilidad controlada usa mocks y no consume cuota.

## Resultados reales y ejemplos completos

Evidencia en `evals/results/technical-v4/live-20260916T224609Z/`: cada JSON contiene **respuesta completa, snapshot normalizado y traza**. Las métricas devueltas coinciden con el recálculo Python de los snapshots. Esto verifica integridad aritmética y protección frente al LLM, no certifica la calidad económica del proveedor.

| Solicitud | Resultado | Tendencia / momentum | Completitud | Intentos / latencia |
|---|---|---|---|---|
| GGAL | ANSWER / BEARISH | BEARISH / IMPROVING_BUT_BEARISH | COMPLETE, 125 datos | 5 / 35,77 s |
| ALUA | ANSWER / BEARISH | BEARISH / IMPROVING_BUT_BEARISH | PARTIAL, 124 datos, 1 descarte | 5 / 45,77 s |
| YPFD | ANSWER / MIXED | MIXED / IMPROVING_BUT_BEARISH | COMPLETE, 125 datos | 4 / 6,86 s |
| XXXX | CLARIFY | No se solicitó histórico | No aplica | 1 / 1,39 s |

En todos los runs se utilizó realmente **gemini-3.5-flash-lite**, el principal configurado; modelVersion confirmó ese identificador. GGAL tuvo un **503 real recuperado**; ALUA tuvo un rechazo de validación `DECISION_TEXT_BOUNDS` y posterior decisión válida. Ninguno se presenta como un 429 real. Los GET de metadata de `gemini-3.5-flash-lite` y `gemini-3.6-flash` devolvieron 200 y soporte de generateContent; no se ejecutó generación con 3.6 en esta verificación, ni un cambio real entre modelos.

- [GGAL completo](../evals/results/technical-v4/live-20260916T224609Z/cd3cecda-39cc-49ae-a9ee-1b952cea57c0.json): precio 6745; SMA20 6939,25; SMA50 7382,6; RSI14 39,3453; MACD -116,1205; señal -117,9201; histograma +1,7996; volumen null. Tendencia bajista con mejora relativa de momentum aún negativo; UNCONFIRMED.
- [ALUA completo](../evals/results/technical-v4/live-20260916T224609Z/08c42bf3-048d-4028-9979-21905c250264.json): precio 847; SMA20 861,025; SMA50 915,86; RSI14 37,4871; MACD -12,9892; señal -17,8029; histograma +4,8137; volumen null. Misma interpretación direccional, con PARTIAL por OHLC descartado; UNCONFIRMED.
- [YPFD completo](../evals/results/technical-v4/live-20260916T224609Z/50796e36-20eb-49f4-8c1b-eace33794f73.json).
- [Ticker inválido completo](../evals/results/technical-v4/live-20260916T224609Z/4a01fcf8-07a5-4e50-869a-6085c6dbba80.json).
- [429 controlado completo, MOCK](../evals/results/technical-v4/mock-429/response.json): FastAPI entrega ANSWER tras tres decisiones exitosas y dos intentos fallidos HTTP 429. `generation.mode=DETERMINISTIC_FALLBACK`, `llm_status=RATE_LIMITED`, `requested_model=model=mock-gemini`, `attempts=5`, `retry_after_seconds=2`, `model_fallback_used=false`. Se conserva el error en la traza y una advertencia en la respuesta; los cálculos siguen disponibles.
- [Traza legible de GGAL](../evals/results/technical-v4/trace-readable.txt) y [suite final](../evals/results/technical-v4/pytest-final.txt).

Las ejecuciones reales usan el agente con adaptadores reales y SQLite; el contrato HTTP se verifica mediante los tests de API y la aceptación 429 mock. No se presenta el simulador Fake como integración Gemini.

Después de los últimos ajustes se recalcularon offline los tres snapshots reales con el código final: coincidieron todos los valores y los estados de completitud, tendencia, momentum, conclusión y confirmación. Resultado: [replay offline](../evals/results/technical-v4/offline-replay.json). Esta repetición no llamó a Gemini ni al proveedor de mercado.

## Riesgos y pendientes

- **YPFD:** el proveedor devuelve una discontinuidad grande de escala (precio final 8740, SMA50 33746,9, variación de muestra aproximadamente -84,11%). No se verificaron ajustes corporativos ni continuidad económica de esa serie. COMPLETE describe campos/ventanas disponibles, no certifica ausencia de ajustes faltantes. Se mantiene la limitación sobre precios no ajustados; no se inventó una corrección.
- ALUA conserva la fila inválida descartada; corregir el dato de origen corresponde al proveedor.
- No hay calendario BYMA completo ni certificación de cierre oficial. Los indicadores que incluyen quote pueden cambiar.
- La cuota agotada, el 429 y el cambio entre modelos fueron verificados de forma determinista; el fallo real observado en esta corrida fue 503. No se consumió cuota para forzar errores.
- Los modelos disponibles y límites pueden cambiar. Los resultados reales son evidencia puntual del 16/09/2026, no una garantía futura.
- Los artefactos de aceptación contienen snapshots; la persistencia normal mantiene el contrato existente de reporte/traza, sin introducir un archivo de mercado permanente nuevo.
