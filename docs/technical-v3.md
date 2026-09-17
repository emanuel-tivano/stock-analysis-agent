# Análisis técnico v3 — implementación y verificación

Fecha: 16/09/2026. Alcance exclusivo: análisis técnico educativo.

Se leyó la auditoría existente, el código, los tests y la consigna oficial aportada por el
usuario (`TFI_AI_Agent_Developer_ITBA_Instrucciones_Entrega.pdf`, nueve páginas), además de
`PautasTP.png`. El TFI permite agente único y RAG opcional; exige HITL para la entrega final.
HITL continúa pendiente y fuera de esta iteración por instrucción expresa del usuario.
No se usaron los libros del repositorio como conocimiento ni se agregaron dependencias.

## Causa y solución

El reporte inicializaba technical.status en INSUFFICIENT_DATA y nunca lo cambiaba aunque
`enough` fuera verdadero. Además, los providers validados sustituían su texto por mensajes
genéricos; los prompts v1/v2 vinculaban las conclusiones a evidencia metodológica de libros.
No era una excepción de GGAL ni un fallo de las fórmulas de SMA, EMA, RSI o MACD.

Ahora `technical_assessment.py` convierte indicadores en señales antes de la siguiente
decisión del LLM. El reporte utiliza la misma función. El LLM conserva selección de tools,
acciones y finalización; no puede modificar las cifras ni las relaciones del reporte.
La narrativa financiera publicada es **determinista**, identificada mediante
`narrative_origin=deterministic`. No se implementó redacción financiera libre del LLM:
los textos reason/interpretation del provider no se consideran evidencia verificada.

El prompt nuevo `technical-v3` no requiere buscar libros para un análisis técnico ordinario.
v1/v2 se conservan sin alterar sus textos para comparaciones históricas. Se actualizó el
default, `.env.example` y únicamente AGENT_PROMPT_VERSION en `.env` local; no se cambiaron
credenciales ni otras opciones personales. Reiniciar el servidor para cargar el nuevo código.

## Contrato y reglas

Se conservan campos y estados terminales del endpoint. Se agregan current_price y
macd_histogram a metrics; assessment y narrative_origin a la dimensión técnica.
Los consumidores del repositorio, schemas OpenAPI, skill, datasets y tests se actualizaron.

| Campo | Significado |
|---|---|
| status superior | ANSWER, CLARIFY, ABSTAIN o ERROR del recorrido |
| technical.status | Dirección BULLISH/BEARISH/NEUTRAL/MIXED, o motivo de no disponibilidad |
| technical.metrics | Valores Python sin redondeo interno, null si no disponibles |
| technical.assessment.status | Suficiencia/calidad: COMPLETE, PARTIAL, INSUFFICIENT_DATA, SOURCE_ERROR, STALE, INVALID_DATA, UNVERIFIED |
| assessment.signals | Comparaciones individuales y explicación derivada |
| assessment.trend / momentum / conclusion | Agregación de señales; conclusion corresponde al status direccional legado |
| assessment.confidence | Calidad de evidencia, nunca probabilidad de acierto ni certeza de mercado |
| assessment.agreements / conflicts | Coincidencias y contradicciones explícitas |
| assessment.warnings / missing_indicators | Advertencias de calidad y causas específicas de ausencia |
| technical.interpretation | Narrativa renderizada desde las señales; no copia la respuesta libre del LLM |

Ventanas: EMA12=12; RSI14=15 precios; SMA20=20; EMA26/MACD=26;
señal/histograma MACD=34; SMA50=50. Mínimo de análisis parcial: precio actual válido,
15 observaciones y al menos una señal disponible. Con todos los indicadores y sin filas
descartadas, la muestra es COMPLETE. Ausencia de SMA50 o de MACD produce PARTIAL y explica
el indicador faltante. Volumen desconocido sigue null, no invalida el análisis de precios
y reduce la confianza a MEDIUM. No se sustituyen valores ausentes por cero.

HIGH requiere indicadores completos; faltantes, filas descartadas o barra provisional
reducen calidad. La cantidad 124 no garantiza calidad por sí sola: se verifican muestra,
precio final, origen, orden, duplicados, valores finitos y fechas. Pydantic rechaza OHLC
inválido; el adapter puede descartar filas inválidas y declara cuántas. Normaliza el orden
de la respuesta HTTP, rechaza duplicados; la evaluación pura exige orden cronológico.
Los fallos del transporte se presentan como SOURCE_ERROR; contratos inválidos como
INVALID_DATA, con ERROR superior. La ausencia de datos utilizables es diferente.

Comparaciones de medias y MACD usan igualdad con tolerancia numérica pequeña. RSI >=70
indica sobrecompra, <=30 sobreventa; dentro de la zona neutral, >50 indica sesgo alcista,
<50 bajista y 50 neutral. Sobrecompra/sobreventa no implican una reversión automática.
MACD frente a señal, MACD frente a cero e histograma se informan por separado. El histograma
incluye magnitud absoluta y porcentaje del precio; una lectura no demuestra expansión ni
un cruce reciente. Las señales dependientes no se suman como votos independientes.
Al coexistir componentes alcistas y bajistas, la agregación es MIXED; neutralidad no cancela
una dirección disponible. No se inventan soportes, resistencias o precios objetivo.

Las solicitudes explícitamente atribuidas a Murphy/Graham mantienen abstención metodológica:
pueden tener assessment COMPLETE y technical.status INSUFFICIENT_DATA por esa atribución,
con limitación expresa. Esta excepción no afecta pedidos técnicos ordinarios.

## Fechas y encoding

as_of representa la última barra incluida, no el día de consulta. fetched_at conserva la
recepción declarada por upstream; la quote tiene su propia recepción y observación.
La validación compara fechas de Buenos Aires, rechaza fechas futuras e histórico posterior
a la fecha de recepción. Una quote no renueva un histórico vencido.

Se centralizó la política de frescura utilizada también por el adapter: tolerancia de siete
días calendario y reconocimiento de la última sesión posible sin suponer cerrado el día
actual. La función pura acepta feriados verificados inyectados y tiene pruebas para ellos.
**No hay calendario oficial BYMA integrado**: la API usa la tolerancia conservadora, que
cubre fines de semana y feriados ordinarios, pero puede admitir ruedas faltantes. No se
certifica cierre, continuidad, ajustes corporativos ni suspensión del instrumento.

No se encontraron secuencias mojibake en fuentes Python. La respuesta HTTP ahora declara
`application/json; charset=utf-8`, incluidos errores JSON. Se probaron bytes UTF-8 estrictos,
prompts/fuentes y round-trip de pedido/resumen en SQLite. Se ejecutaron comandos Python con
`-X utf8` desde PowerShell. Una lectura inicial del PDF con salida cp1252 falló por un glifo;
la lectura UTF-8 se completó. No se aplicaron recodificaciones destructivas a texto válido.

## Ejemplo ejecutado, no cotización real

`scripts/acceptance_technical.py` ejecutó GET /health y POST /agent/run con
`{"message":"Analiza técnicamente GGAL"}` a través de FastAPI TestClient, transporte de
mercado simulado, reloj fijo y Fake. La fixture tiene 124 observaciones sintéticas de días
laborables (no pretende reproducir un calendario BYMA), y su último volumen es null.
Su metadata live sirve para probar esa rama del contrato: **no es evidencia live**.

Respuesta guardada: `evals/results/technical-v3/ggal-response.json`.

```json
{
  "status": "ANSWER",
  "ticker": "GGAL",
  "as_of": "2026-09-16",
  "technical_status": "MIXED",
  "assessment_status": "COMPLETE",
  "sample_size": 124,
  "confidence": "MEDIUM"
}
```

El fragmento anterior es un resumen de campos, no reemplaza el JSON anidado del endpoint.
Valores calculados (redondeados aquí): precio 6970; SMA20 6858,71; SMA50 7176,91;
EMA12 6897,45; EMA26 6957,66; RSI14 50,98; MACD -60,22; señal -100,82;
histograma +40,60; variación 13,33%. Fuente simulada:
`https://market-fixture.test/api/stocks/GGAL/history?range=6M&market=bCBA`.

Lectura: precio sobre SMA20 pero debajo de SMA50; SMA20 < SMA50 y EMA12 < EMA26;
RSI neutral con leve sesgo alcista; MACD negativo pero sobre su señal. Resultado MIXED
por contradicciones observadas. El reporte distingue expresamente señal, pronóstico y
recomendación. No se copiaron los valores del ejemplo original ni se hardcodeó GGAL.

## Verificación ejecutada

| Check | Resultado |
|---|---|
| Baseline pytest | 323 passed, 4 skipped, 0 failed; 9,64 s |
| Suite final pytest | 366 passed, 4 skipped, 0 failed; 9,98 s |
| Evals ampliadas Fake | 17/17 PASS, 0 FAIL, sin tools prohibidas |
| Ruff check | PASS |
| Ruff format --check | PASS, 75 archivos |
| pip check | Sin dependencias rotas |
| git diff --check | PASS; avisos LF/CRLF de Git, sin errores de whitespace |
| Smoke Uvicorn real local | health=200; run=200 CLARIFY para activo desconocido |
| Aceptación GGAL offline | health=200; run=200 ANSWER/MIXED/COMPLETE |

Cuatro skips opt-in: dos de test_live.py y dos de test_real_llm.py. Se conservaron;
RUN_LIVE_TESTS=0 y RUN_LLM_TESTS=0 en la suite final. Dos warnings existentes de
deprecación Starlette/TestClient y anyio, sin ocultarlos ni cambiar dependencias.
No se ejecutaron Gemini, servicios bursátiles externos ni pruebas live en esta pasada.

Comandos ejecutados desde la raíz en PowerShell:

```powershell
$env:RUN_LLM_TESTS='0'
$env:RUN_LIVE_TESTS='0'
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -ra
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m pip check
git diff --check
.\.venv\Scripts\python.exe -X utf8 scripts/smoke_api.py
.\.venv\Scripts\python.exe -X utf8 scripts/acceptance_technical.py
.\.venv\Scripts\python.exe -X utf8 -c "from merval_agent.evaluation import evaluate; from merval_agent.config import Settings; r,p=evaluate(Settings(_env_file=None),fake=True,output_dir='evals/results/technical-v3'); print(r['metrics']); print(p)"
```

También se ejecutaron corridas intermedias para localizar regresiones de contrato y
`ruff format` sobre los archivos editados. No se borraron tests. Las expectativas de
INSUFFICIENT_DATA y búsqueda metodológica obligatoria se sustituyeron por el contrato nuevo.

Los dos FAIL históricos del simulador eran out_of_scope (CLARIFY en lugar de ABSTAIN) y
contradiction (ANSWER y tools prohibidas en lugar de CLARIFY). Se corrigió la selección
inicial del Fake; se preservaron esos casos y restricciones. El dataset pasó a technical-v3
porque los pedidos técnicos suficientes ya no esperan abstención ni búsqueda de libros.
17/17 mide simulación y contrato; no demuestra autonomía ni calidad de un LLM real.

Cobertura nueva: muestra 124, límites 50/49/34/15/14/1/0, volumen opcional, valores no finitos,
precio inválido, duplicados/desorden, fechas futuras/vencidas, fines de semana y feriado
inyectado, sesgos alcista/bajista/neutral/mixto, zonas RSI, MACD faltante, calidad parcial,
fuente fallida/contrato inválido, OpenAPI, UTF-8 y SQLite. Un provider adversarial intenta
modificar métricas y emitir objetivos inventados: el endpoint conserva los valores Python.

## Archivos de esta iteración

El árbol ya tenía cambios previos; esta lista no equivale al diff total contra HEAD.

- Configuración: `.env` (solo versión local del prompt), `.env.example`.
- Dominio: `src/merval_agent/domain/models.py`, `domain/technical.py`, nuevo `domain/technical_assessment.py`.
- Agente: `src/merval_agent/agents/equity_agent.py`, `agents/state.py`, `agents/report.py`.
- Adaptadores y composición: `src/merval_agent/adapters/llm/context.py`, `adapters/llm/fake.py`, `adapters/market_tracker.py`, `config.py`.
- API/evaluador: `src/merval_agent/api/app.py`, `evaluation.py`.
- Tests existentes: `tests/integration/test_trace_baseline.py`; `tests/unit/test_agent.py`, `test_gemini_provider.py`, `test_local_llm.py`, `test_phase2_closure.py`, `test_phase2a_regressions.py`, `test_prompt_versions.py`.
- Tests/fixture nuevos: `tests/unit/test_technical_assessment.py`, `tests/integration/test_technical_contract.py`, `tests/fixtures/technical_124.json`.
- Aceptación nueva: `scripts/acceptance_technical.py`.
- Datasets: `evals/dataset.jsonl`, `evals/real_llm_dataset.jsonl`.
- Documentación: `README.md`, `docs/architecture.md`, `docs/technical-v3.md`, `evals/README.md`.
- Skill del proyecto: `src/merval_agent/skills/merval_equity_analysis/SKILL.md`, `references/contracts.md`.
- Artefactos locales ignorados: `evals/results/technical-v3/` (respuesta, logs, evaluación y trazas SQLite).

Pendiente: validación live con Gemini y fuentes reales, calendario bursátil integrado,
certificación de ajustes/cierres y evaluación predictiva (no implementada ni prometida).
SQLite conserva pedido, resumen y trazas, no el reporte completo ni snapshot de mercado.
HITL, fundamentales, RAG y multiagente no se ampliaron. No se hicieron commits ni push.
