# Merval Equity Analyst AI — Phase 1 Release Candidate

Base Python para el Trabajo Final Integrador de la Certificación Profesional en AI Agent
Developer del ITBA. Asistente educativo de investigación de acciones argentinas.
Proyecto independiente: **Argentina Market Tracker se consume por HTTP**, sin copiar su
proveedor, cache ni lógica bursátil. No emite recomendaciones BUY/SELL.

## Qué funciona en esta iteración

- Contratos Pydantic, estado explícito y loop de un agente con decisiones por paso.
- Seis tools registradas con schemas, precondiciones y errores como observaciones.
- Historial real de Market Tracker y metadata documental de Bolsar mediante `httpx`.
- SMA20/50, EMA12/26, RSI14 Wilder, MACD/señal, variación, extremos y volumen promedio,
  calculados exclusivamente en Python.
- FastAPI, SQLite, eventos recuperables por `trace_id`, tests offline y siete evals fake.
- Provider fake determinístico y adapter HTTP compatible configurable, probado con transporte
  simulado. **No se ha validado una sesión con un LLM real.**

El loop no contiene una secuencia fija de herramientas: solicita una decisión al provider,
valida, ejecuta o termina y vuelve a decidir con las observaciones. Los tests demuestran que
el provider puede elegir metodología antes del mercado y cambiar decisiones tras errores.
El **FakeLLMProvider es un simulador con reglas**, útil para pruebas, no un LLM ni evidencia
de razonamiento autónomo real. Validar un modelo real será un hito de la Fase 2.

## Arquitectura y trazabilidad

```text
FastAPI → EquityAgent ↔ LLMProvider
              ↓ decisión validada
          ToolRegistry → adapters HTTP / cálculos puros / retrieval local
              ↓ observación tipada
          AgentState → reporte / repository SQLite
```

- **DATO:** OHLCV, métricas derivadas o metadata de documentos, con fecha y fuente.
- **METODOLOGÍA:** evidencia separada; las notas locales están marcadas `DEMO`.
- **INTERPRETACIÓN:** texto del provider, separado de las cifras determinísticas.
- **LIMITACIONES:** muestra insuficiente, antigüedad, fuente demo/desconocida y abstenciones.

Ver [arquitectura](docs/architecture.md) y
[skill reutilizable](src/merval_agent/skills/merval_equity_analysis/SKILL.md).

## Instalación (Python 3.11+)

Verificado en Windows con Python 3.14.6. `>=3.11` es el mínimo declarado;
esta consolidación no verifica otras versiones de Python.

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

## Ejecutar

```powershell
python -m uvicorn merval_agent.api.app:app --host 127.0.0.1 --port 8000
```

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
parcial: datos técnicos disponibles y abstención fundamental. En Fase 1 no se asignan
categorías direccionales; `INSUFFICIENT_DATA` significa que no hay una conclusión validada,
aunque existan cálculos. Las solicitudes explícitas según Murphy/Graham se abstienen mientras
el retrieval sea demo. Las solicitudes genéricas pueden devolver cálculos educativos parciales.
En particular, `status=ANSWER` con `technical.status=INSUFFICIENT_DATA` es intencional:
hay datos y cálculos, pero falta una conclusión metodológica validada.
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

Los archivos y los bytes JSON de la API son UTF-8. La respuesta usa `application/json`;
no necesita un `charset` adicional para JSON. Las pruebas verifican los acentos y `/docs`.
En Windows PowerShell, usar lectura explícita `Get-Content -Encoding UTF8` y configurar:

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
```

`$OutputEncoding` también controla el texto enviado a programas por pipe. Si un cliente antiguo
decodifica mal una respuesta JSON sin charset, leer los bytes con `httpx` o decodificarlos
explícitamente como UTF-8. No recodificar el contenido correcto del servidor.

## Configuración

Todas las variables están en `.env.example`:

| Variable | Uso |
|---|---|
| MARKET_TRACKER_BASE_URL | Servicio de OHLCV externo |
| BOLSAR_BASE_URL | Origen de la página documental |
| MAX_AGENT_STEPS | Máximo de decisiones, incluidas inválidas; default 12 |
| HTTP_TIMEOUT_SECONDS | Timeout HTTP; default 20 |
| STALE_AFTER_DAYS | Antigüedad máxima en días calendario; default 7 |
| DATABASE_PATH | SQLite local, excluido de Git |
| LLM_PROVIDER | `fake` o `compatible` |
| LLM_BASE_URL | Base que incluye el prefijo de API, por ejemplo `/v1` |
| LLM_MODEL / LLM_API_KEY | Modelo y secreto del proveedor elegido |

El adapter `compatible` utiliza `/chat/completions`, JSON mode y validación Pydantic. Se eligió
HTTP encapsulado sin SDK para preparar la integración; comprobar soporte del endpoint y JSON
mode en el proveedor seleccionado antes de usarlo. No se agregan claves al código ni logs.

## Fuentes externas

### Argentina Market Tracker

`GET /api/stocks/{symbol}/history?range={range}&market=bCBA`.
Rangos: `1W`, `1M`, `3M`, `6M`, `1Y`. El contrato observado contiene `ok`, `data`, `symbol`,
`market`, `range`, `fetchedAt`, `meta.source` y `meta.stale`. Se validan OHLCV, fechas únicas,
instrumento, moneda y rango. Se conserva `live/demo/unknown`; solo datos live recientes pueden
habilitar una respuesta técnica. `get_quote` queda explícitamente no implementado hasta
verificar su contrato. No hay integración bursátil directa en este proyecto.
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
La prueba `smoke_api.py` inicia Uvicorn en un puerto local disponible, verifica health y
una aclaración sin internet, y detiene su propio proceso. Resultados de esta iteración:
[verificación](docs/verification.md).

## Límites y Fase 2

Catálogo inicial: GGAL, BMA, SUPV, PAMP, YPFD, ALUA, TRAN. Galicia se aclara por instrumento;
ADR/NYSE/USD quedan fuera de cobertura. No hay cobertura universal del Merval ni métricas de
balances, valoración Graham, vector DB, multiagente, LangGraph, deploy o UI.

SQLite conserva cada ejecución, pedido, estado final, trace de tools sanitizado y resumen;
no reconstruye conversaciones ni reanuda CLARIFY automáticamente. `session_id` agrupa ejecuciones.
El usuario envía una nueva solicitud completa tras aclarar.
También conserva los eventos de decisión y transición. `.gitignore` cubre `.env`, bases,
PDFs, datos privados, caches y logs. Esta copia de trabajo no incluye `.git`: se auditó
el contenido disponible, pero no se puede certificar el índice ni el historial de Git.

Fase 2: validar provider real y selección de tools, RAG privado con citas verificables,
extracción acotada de balances y revisión humana, ratios por sector, evaluación de conclusiones,
mejoras de sesiones y futura propuesta HITL. Los contratos `PendingAction` contemplan
PAUSED → APPROVE/MODIFY/REJECT; no existe tool con efectos externos ejecutables.
