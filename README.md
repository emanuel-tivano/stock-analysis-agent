# Merval Equity Analyst AI

Estado actual: [HITL de finalización de informes](docs/hitl-v1.md), con propuesta
persistida, revisión editorial, aprobación/rechazo y continuación idempotente.
La revalidación final offline/Fake del 24/09/2026 sobre el commit funcional
`3818a508d732501bc8632e058633e76c57894181` obtuvo 726 tests aprobados, cuatro
integraciones live/LLM opt-in omitidas y cero fallos; Ruff, formato, dependencias,
ambos smokes, evaluación técnica 33/33, evaluación HITL 10/10 y JavaScript 8/8
también aprobaron. El tag anotado `v1.0-tfi` identifica la versión entregable.
Baseline de esta extensión: [auditoría integral del 17/09/2026](docs/audit-2026-09-17.md),
665 tests aprobados, 4 opt-in omitidos y evaluación técnica Fake 33/33.
El cierre de la V1 técnica está documentado en
[cierre y evaluación de la V1 técnica](docs/technical-v1-closure.md).
Capturas históricas documentadas de GGAL/BMA fueron contrastadas con un oráculo independiente;
sus artefactos son locales e ignorados por Git. No se ejecutó una nueva evaluación con LLM real
en este cierre.
Antecedente: [análisis técnico v4, resiliencia y pruebas reales](docs/technical-v4.md).
Antecedente: [análisis técnico v3 y verificación](docs/technical-v3.md).
Antecedente: [auditoría integral del 16/09/2026](docs/audit-2026-09-16.md).
La quote se incorpora como provisional, el volumen ausente no se reemplaza por cero
y un fallo técnico no recuperado termina ERROR.

Historia de Fase 2, diagnóstico de fallos, política de decisiones/retries y evidencia de
evaluación real: [auditoría de cierre](docs/phase2-closure.md). Los apartados históricos
de Fase 1 se conservan como contexto; el dictamen de cierre está en esa auditoría.

Base Python para el Trabajo Final Integrador de la Certificación Profesional en AI Agent
Developer del ITBA. Asistente educativo de investigación de acciones argentinas.
Proyecto independiente: **Argentina Market Tracker se consume por HTTP**, sin copiar su
proveedor, cache ni lógica bursátil. No emite recomendaciones BUY/SELL.

**Integrante:** Emanuel Tivano.

**Problema:** reunir datos de mercado, cálculos técnicos, procedencia y limitaciones en una
respuesta auditable, sin delegar cifras ni señales financieras al LLM.

**Destinatarios:** personas que investigan acciones argentinas con fines educativos y
necesitan una primera lectura técnica reproducible; no sustituye asesoramiento financiero.

## Qué funciona en esta iteración

- Contratos Pydantic, estado explícito y loop de un agente con decisiones por paso.
- Seis tools registradas con schemas, precondiciones y errores como observaciones.
- Historial real de Market Tracker y metadata documental de Bolsar mediante `httpx`.
- SMA20/50, EMA12/26, RSI14 Wilder, MACD/señal, variación, extremos y volumen promedio,
  calculados exclusivamente en Python.
- FastAPI, SQLite, eventos recuperables por `trace_id`, tests offline y datasets Fake
  histórico (17 casos) y técnico V1 (33 casos con 12 ejes separados).
- Providers Fake, OpenAI-compatible (incluido servidor local) y Gemini nativo; pruebas
  determinísticas y evaluaciones reales Gemini documentadas en la auditoría de Fase 2.

El loop no contiene una secuencia fija de herramientas: solicita una decisión al provider,
valida, ejecuta o termina y vuelve a decidir con las observaciones. Los tests demuestran que
el provider puede elegir metodología antes del mercado y cambiar decisiones tras errores.
El **FakeLLMProvider es un simulador con reglas**, útil para pruebas, no un LLM ni evidencia
de razonamiento autónomo real. La evidencia del modelo real se registra por separado.

Demo técnica offline reproducible: `.venv\Scripts\python.exe scripts/eval_technical_v1.py`.
Crea un directorio nuevo con respuestas HTTP completas, snapshots, hashes y SQLite.
La captura pública es opt-in: `$env:RUN_LIVE_TESTS="1"` y luego
`.venv\Scripts\python.exe scripts/capture_technical_v1.py --live`; no lee `.env` ni llama a un LLM.

## Arquitectura y trazabilidad

```text
Web Chat → POST /chat → presenter determinístico ┐
                                                  ├→ EquityAgent ↔ LLMProvider
Cliente API → POST /agent/run → FinalAnalysis ───┘       ↓ decisión validada
                                                     ToolRegistry
                                                        ↓
                                           adapters HTTP / cálculos Python
                                                        ↓
                                           AgentState → SQLite + reporte
```

- **DATO:** OHLCV, métricas derivadas o metadata de documentos, con fecha y fuente.
- **METODOLOGÍA:** evidencia separada; las notas locales están marcadas `DEMO`.
- **SEÑALES:** relaciones, tendencia y momentum calculados por Python antes de la siguiente decisión LLM.
- **INTERPRETACIÓN:** narrativa determinista de esas señales; no se publica prosa financiera libre del provider.
- **LIMITACIONES:** muestra insuficiente, antigüedad, fuente demo/desconocida y abstenciones.

Ver [arquitectura](docs/architecture.md) y
[skill reutilizable](src/merval_agent/skills/merval_equity_analysis/SKILL.md).

## Instalación (Python 3.11+)

Verificado desde cero en Windows con Python 3.14.6. `>=3.11` es el mínimo declarado;
esta consolidación no pudo ejecutar Python 3.11 porque ese intérprete no está instalado.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

En Linux/macOS activar con `source .venv/bin/activate` y copiar con `cp .env.example .env`.
Las dependencias directas están en `pyproject.toml`; `requirements-tested.txt` registra las
versiones del entorno verificado. Para reproducirlas: `pip install -r requirements-tested.txt`
y luego `pip install --no-deps -e .`. No contiene credenciales.
También se verifica instalación editable en un entorno nuevo con
`python -m pip install -e ".[dev]" -c requirements-tested.txt`, conservando las versiones probadas.
Además se construyó una wheel, se comprobó que incluye la web y el skill, se instaló sin modo
editable en el entorno temporal y se repitió el smoke desde fuera del repositorio.

## Ejecutar

```powershell
python -m uvicorn merval_agent.api.app:app --host 127.0.0.1 --port 8000
```

## Interfaz web

Para revisión humana, escribir **“Prepará un informe técnico de GGAL para revisión.”**.
La respuesta `PAUSED` presenta Aprobar, Modificar y Rechazar. Modificar sólo permite
enfoque, secciones y nota editorial; crea una nueva versión que todavía requiere aprobación.
Aprobar finaliza localmente con la evidencia guardada, sin consultas nuevas a mercado o LLM.
Rechazar conserva auditoría. No se realizan operaciones financieras ni envíos externos.
El análisis ordinario continúa como `ANSWER`. [API, demo offline y garantías](docs/hitl-v1.md).

La referencia `evaluated_at` se captura después de adquirir cada snapshot técnico y se
conserva en el snapshot persistido. Assessment, decisión y reporte usan esa misma referencia;
los timestamps operativos de propuesta y revisión continúan registrando sus instantes reales.

Con la aplicación iniciada, abrir [http://127.0.0.1:8000/](http://127.0.0.1:8000/).
No hace falta usar PowerShell, `curl`, Postman ni conocer el contrato JSON. La consulta se
escribe en lenguaje natural; por ejemplo: `Analizá técnicamente GGAL`, `Analizá YPFD` o
`¿Qué señales técnicas tiene GGAL?`.

La interfaz muestra primero la conclusión, la confianza, el resumen, la tendencia, el
momentum, RSI, MACD y las advertencias. Los indicadores, fuentes y detalles técnicos quedan
en secciones desplegables. Si la última barra es una cotización provisional, la interfaz lo
indica explícitamente. El navegador trata el texto de usuario y de la API como texto, no como
HTML, y sólo permite abrir fuentes HTTP/HTTPS.

`POST /chat` es el adapter de presentación usado por la interfaz. Traduce de forma
determinística el resultado ya calculado por Python; no hace una llamada adicional al LLM ni
modifica las señales. `POST /agent/run` sigue disponible, sin cambios, para obtener el JSON
técnico completo necesario para tests, auditoría y debugging. También siguen disponibles
`/docs` y `/health`.

La UI conserva el `session_id` en la pestaña durante la conversación y “Nueva conversación”
inicia otro agrupador. Esta versión **no reconstruye contexto ni resuelve follow-ups por
memoria**: SQLite agrupa ejecuciones, pero cada consulta debe ser autocontenida. La
disponibilidad del análisis depende de las fuentes externas configuradas. El provider por
defecto es Fake para orquestación, pero los datos de mercado de la aplicación siguen siendo
reales.

### Universo de activos

El universo funcional es **acciones domésticas argentinas negociadas en BYMA**, consultadas al
proveedor con `market=bCBA`, para análisis técnico. No es una whitelist: el LLM propone símbolo,
mercado y empresa; después el sistema valida existencia y elegibilidad de forma determinística.
El catálogo interno es solamente una vía rápida para símbolos conocidos. Un símbolo ausente del
catálogo puede resolverse si la quote del proveedor confirma identidad, mercado, moneda ARS y los
invariantes de precio.

Quedan fuera de alcance CEDEARs, ADRs, acciones extranjeras y otros instrumentos que no sean
acciones domésticas. La API de quote de Argentina Market Tracker inspeccionada no expone un campo
estructurado de tipo, categoría o `security_type`. Por eso no se inventa esa metadata: el adaptador
registra una clasificación derivada y su método. Una descripción normalizada que comienza con
`Cedear ` se rechaza como CEDEAR. También se rechazan descripciones que comienzan con marcadores
de bono, obligación negociable, letra, opción, futuro, índice, fondo, ETF o cripto. Para candidatos
locales se exige además un símbolo de 2–5 caracteres formado por 2–5 letras o por 1–4 letras y
un único dígito final (por ejemplo `TECO2`, `TGNO4`, `TGSU2` y el borde `A3`), `bCBA`, ARS, quote
live/no-stale e identidad coherente. La forma sintáctica no prueba existencia ni elegibilidad:
ambas requieren la validación posterior. Esta es una política operativa sujeta al contrato actual del proveedor; si
éste agrega tipo estructurado, debe reemplazar la heurística de descripción.

“MERVAL” se conserva en el nombre histórico del proyecto y en algunos módulos, pero **no** significa
“sólo integrantes del índice MERVAL/S&P Merval”. En este agente significa el mercado accionario
doméstico argentino soportado bajo la política anterior; la pertenencia a un índice no se usa para
aceptar ni rechazar activos.

En otra consola:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$body = @{message="Analizá técnicamente GGAL"} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/agent/run -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

Documentación interactiva: `http://127.0.0.1:8000/docs`.
`/health` comprueba la aplicación, no la disponibilidad de servicios externos.
El provider por defecto es fake, **pero las tools de la API consultan servicios reales**.
Los tests utilizan `MockTransport` y no necesitan internet.

`POST /agent/run` devuelve un contrato uniforme con `status` ANSWER, CLARIFY, ABSTAIN o ERROR,
`trace_id`, `session_id`, métricas, evidencia y limitaciones. Una respuesta ANSWER puede ser
parcial: datos técnicos disponibles y abstención fundamental. `technical.status` expresa la
lectura BULLISH/BEARISH/NEUTRAL/MIXED cuando hay datos utilizables. `technical.assessment.status`
separa COMPLETE, PARTIAL, INSUFFICIENT_DATA, SOURCE_ERROR, STALE, INVALID_DATA y UNVERIFIED.
Una resolución que no habilita análisis termina antes de consultar historia: inexistencia produce
`technical.status=ASSET_NOT_FOUND`, falta de desambiguación produce `AMBIGUOUS_ASSET` y un
instrumento identificado pero fuera del universo produce `UNSUPPORTED_ASSET`; todos conservan
`technical.assessment=null`. Así también se distinguen de un ticker elegible con historia
insuficiente, que conserva `technical.status=INSUFFICIENT_DATA`. Las fallas del proveedor son
`EXTERNAL_SERVICE`, nunca ausencia del activo.
Un pedido técnico ordinario no requiere libros. Las solicitudes explícitas según Murphy/Graham
se abstienen de atribuirles conclusiones mientras el retrieval sea demo.
`fundamental.status=NOT_REQUESTED` indica que esa dimensión no se pidió.

### Inspeccionar una ejecución local

```powershell
python scripts/show_trace.py <trace_id>
# Si se usó otra base:
python scripts/show_trace.py <trace_id> --database data/sessions.sqlite3
```

Muestra eventos ordenados con paso, decisión, tool, resultado, latencia y estado resumido.
No muestra el pedido privado ni el resumen libre. No agrega la traza a `FinalAnalysis`.
Las bases anteriores se migran al iniciar el repositorio; sus ejecuciones antiguas conservan
solo la traza de tools que originalmente existía. El inspector abre SQLite en modo lectura.
Si falla la persistencia, la API devuelve `ERROR` y el cierre corregido queda en logs;
no se garantiza recuperación desde una base que no pudo escribirse.

### UTF-8 en Windows PowerShell

Los archivos y los bytes JSON de la API son UTF-8. La respuesta declara
`application/json; charset=utf-8`. Las pruebas verifican acentos, SQLite y `/docs`.
En Windows PowerShell, usar lectura explícita `Get-Content -Encoding UTF8` y configurar:

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = '1'
$env:AGENT_PROMPT_VERSION = 'technical-v3'
```

`$OutputEncoding` también controla el texto enviado a programas por pipe. Si un cliente antiguo
decodifica mal una respuesta JSON sin charset, leer los bytes con `httpx` o decodificarlos
explícitamente como UTF-8. No recodificar el contenido correcto del servidor.

## Configuración

Defaults seguros y variables disponibles en `.env.example` (restaurado en la auditoría):

| Variable | Uso |
|---|---|
| MARKET_TRACKER_BASE_URL | Servicio de OHLCV externo |
| BOLSAR_BASE_URL | Origen de la página documental |
| MAX_AGENT_STEPS | Máximo de decisiones, incluidas inválidas; default 12 |
| HTTP_TIMEOUT_SECONDS | Timeout HTTP; default 20 |
| STALE_AFTER_DAYS | Antigüedad máxima en días calendario; default 7 |
| DATABASE_PATH | SQLite local, excluido de Git |
| LLM_PROVIDER | `fake`, `compatible` o `gemini` |
| MARKET_QUOTE_ENRICHMENT | Enriquecimiento provisional best-effort; default true |
| LLM_BASE_URL | Base que incluye el prefijo de API, por ejemplo `/v1` |
| LLM_MODEL / LLM_API_KEY | Modelo y secreto del proveedor elegido |
| AGENT_PROMPT_VERSION | `technical-v3`; v1/v2 se conservan para reproducir comparaciones históricas |
| MARKET_QUOTE_POLICY | `include_provisional_ohlc` (default) o `history_only`; siempre expone procedencia |
| LLM_DETERMINISTIC_FALLBACK | Default true; conserva un análisis técnico ya calculado ante indisponibilidad del LLM |
| LLM_MAX_RETRY_WAIT_SECONDS | Default 30; si Retry-After excede el presupuesto, no reintenta antes de tiempo |
| LLM_FALLBACK_ENABLED | Default false; habilita un único modelo alternativo explícito |
| LLM_FALLBACK_MODEL / LLM_ALLOWED_FALLBACK_MODELS | Modelo alternativo y lista JSON permitida; sin defaults de nombres |

`technical.assessment.momentum_state` distingue mejora relativa con MACD todavía negativo
de una dirección alcista. La tendencia tiene precedencia para la conclusión global;
`MIXED` requiere conflictos enumerados. `assessment.basis` documenta qué serie alimentó
todos los indicadores; `history_only_metrics` permite comparar la lectura sin quote.
`generation` identifica proveedor, modelo, intentos, errores y degradación determinista.
El fallo del LLM sigue en errors/traza aunque se entregue ANSWER con datos ya calculados.

El adapter `compatible` utiliza `/chat/completions`, JSON mode y validación Pydantic. Se eligió
HTTP encapsulado sin SDK para preparar la integración; comprobar soporte del endpoint y JSON
mode en el proveedor seleccionado antes de usarlo. No se agregan claves al código ni logs.

## Fuentes externas

### Argentina Market Tracker

`GET /api/stocks/{symbol}/history?range={range}&market=bCBA`.
Rangos: `1W`, `1M`, `3M`, `6M`, `1Y`. El contrato observado contiene `ok`, `data`, `symbol`,
`market`, `range`, `fetchedAt`, `meta.source` y `meta.stale`. Se validan OHLCV, fechas únicas,
instrumento, moneda y rango. Se conserva `live/demo/unknown`; solo datos live recientes pueden
habilitar una respuesta técnica. `get_history` intenta una quote adicional best-effort cuando el histórico es elegible.
La barra añadida conserva procedencia y marca provisional; no acredita cierre de rueda.
`MARKET_QUOTE_ENRICHMENT=false` desactiva esa consulta. Volumen desconocido implica
`average_volume=null`; no se sustituye por monto negociado. No hay integración bursátil directa en este proyecto.
Sin horizonte especificado, el fake usa `DEFAULT_TECHNICAL_RANGE` de `domain/policy.py`:
**6M**, para disponer de muestra para SMA50 y análisis intermedio. No garantiza 50 ruedas
ni implementa inferencia sofisticada de horizonte. Los providers inyectados pueden elegir
otros rangos válidos según las observaciones.

### Bolsar

Se consulta `https://bolsar.info/relevante_semestral.php`. Parser aislado para la tabla HTML,
incluidas columnas ocultas y fechas duplicadas. Los enlaces se normalizan a
`https://ws.bolsar.info/descarga/?id=...`. Se elige el documento financiero de publicación más
reciente; ante igual fecha se prioriza Estados Financieros sobre Síntesis.

Los filtros `year` y `semester` corresponden a **fecha de publicación en la página disponible**;
no implementan búsqueda en archivo histórico ni infieren período fiscal. No encontrar un
documento devuelve ausencia; un HTML bloqueado o cambiado devuelve error. No se descargan ni
extraen balances PDF. Un documento listado no prueba solidez financiera.

## PDFs privados y metodología

Colocar las fuentes localmente en `data/private/`. La carpeta y los PDFs existentes en la raíz
están excluidos por `.gitignore`; los originales no se movieron ni modificaron. No se suben,
indexan ni envían automáticamente al LLM. Las notas in-memory son originales y demostrativas,
no extractos de los libros. Su score es 0 y no prueba verdad. El reemplazo futuro implementará
`MethodologyRetriever`, preservando fuente, chunk, metadata y trazabilidad.

## Tests y evals

```powershell
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m pytest -q
python -m pytest tests/integration/test_evals.py -q -s
python scripts/smoke_api.py
python -m pip check
```

Integración real opcional, separada de los tests offline:

```powershell
$env:RUN_LIVE_TESTS="1"
python -m pytest tests/integration/test_live.py -q
Remove-Item Env:RUN_LIVE_TESTS
```

Ver [evaluaciones](evals/README.md). Evals fake no miden calidad de un modelo real.
La prueba `smoke_api.py` inicia Uvicorn y un stub local de mercado en puertos disponibles;
verifica `/`, los assets, PPSA/XYZINVALIDO sin llamadas de mercado, GGAL/PAMP, un GGAL con
historia insuficiente y `/agent/run`; luego detiene los procesos propios. No requiere internet
ni credenciales. Resultados históricos:
[verificación](docs/verification.md).

## Límites y Fase 2

Catálogo inicial: GGAL, BMA, SUPV, PAMP, YPFD, ALUA, TRAN. Galicia se aclara por instrumento;
ADR/NYSE/USD quedan fuera de cobertura. No hay cobertura universal del Merval ni métricas de
balances, valoración Graham, vector DB, multiagente, LangGraph, deploy o memoria
conversacional contextual.

SQLite conserva cada ejecución, pedido, estado final, trace de tools sanitizado y resumen;
no reconstruye conversaciones ni reanuda CLARIFY automáticamente. `session_id` agrupa ejecuciones.
El usuario envía una nueva solicitud completa tras aclarar.
También conserva los eventos de decisión y transición. `.gitignore` cubre `.env`, bases,
PDFs, datos privados, caches y logs. Al iniciar la auditoría del 17/09/2026, `main` estaba
limpio y coincidía con `origin/main` en `988e8449c0e91c28197c6cc4bbd7b82979c04765`;
el informe distingue ese estado inicial de las correcciones posteriores.

HITL implementado: `FINALIZE_TECHNICAL_REPORT`, con SQLite transaccional y control de
versión. `session_id` valida pertenencia pero **no equivale a autenticación**. No hay
efectos externos. Fundamentales, RAG, ratios por sector y memoria conversacional siguen
fuera del alcance implementado; esta extensión no los habilita.

## Registro histórico — Fase 2A: validación de LLM real preparada

Se reutiliza el adapter HTTP compatible, con contexto acotado, prompt `phase2a-v1`,
validación Pydantic y de negocio antes de ejecutar tools, retries limitados y tracing de
intentos/usage. Fake y golden traces de Fase 1 permanecen sin cambios.

**Estado histórico al preparar Fase 2A:** el LLM externo todavía no había sido validado;
no había URL/modelo/credenciales configurados.
El soporte está probado con transporte simulado. Hay 17 casos opt-in y runner con
repeticiones y comparación Fake/Real; no equivale a una prueba de razonamiento real.
La prosa de salida del provider real es operacional y determinística; las cifras siguen
viniendo de Python. RAG continúa DEMO; no hay extracción PDF ni valoración Graham.

```powershell
python scripts/eval_real_llm.py --fake --runs 3
# Tras configurar LLM_BASE_URL, LLM_MODEL, LLM_API_KEY:
$env:RUN_LLM_TESTS = "1"
python scripts/eval_real_llm.py --runs 3
python -m pytest tests/integration/test_real_llm.py -q -s
# Además configurar LLM_PROVIDER=compatible para el milestone con datos externos:
python scripts/run_real_llm.py
```

El Fake obtiene 45/51 éxitos en el dataset ampliado: sus fallos son fuera de alcance y
contradicción. Los 7 casos originales siguen aprobados. Los reportes y traces de evals
se guardan localmente en `evals/results/`, ignorados por Git.

Configuración adicional: LLM_TIMEOUT_SECONDS=20, LLM_MAX_RETRIES=1 (0–2),
LLM_RESPONSE_FORMAT=json_object (opciones json_schema/none), AGENT_PROMPT_VERSION=phase2a-v1.
Precios opcionales LLM_INPUT_PRICE_PER_1M / LLM_OUTPUT_PRICE_PER_1M; costo null si faltan
precios o usage completo. Ver [guía exacta de Fase 2A](docs/phase2a-real-llm.md) para métricas,
privacidad, comandos de traces, límites y qué falta validar.

## Registro histórico — primera validación de Gemini nativo

LLM_PROVIDER admite `fake`, `compatible` y `gemini`. Gemini utiliza generateContent nativo,
systemInstruction y el mismo AgentDecision/prompt phase2a-v1. El mecanismo de validación
/retries es compartido entre adapters; EquityAgent y las tools no cambiaron en esta iteración.

**Evidencia real nueva:** decisión mínima CLARIFY PASS con gemini-3.6-flash. El primer agente
resolvió GGAL y obtuvo historial live 6M; terminó ERROR en el step 3 por 503/429 del endpoint
nativo. El recorrido completo todavía no está validado. Trace:
`b1473d6a-a900-4825-be90-3ffae4ddc34f`. No se ejecutó el dataset real completo tras el 429.

Ver [Gemini nativo](docs/gemini-native.md) para configuración, requests/respuestas, usage,
errores, resultados reales y archivos modificados. Verificación final: **130 PASS, 4 SKIP**,
7 evals originales PASS, Ruff/format/smoke API/pip check PASS. Las referencias anteriores a
“no ejecutado” corresponden al estado previo a esta actualización.
