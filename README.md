# Stock Analysis Agent

Agente educativo para analizar acciones argentinas con datos de mercado, indicadores calculados en Python y un flujo opcional de revisión humana.

**Integrante:** Emanuel Tivano

**Trabajo:** TFI — Desarrollador de Agentes de IA, ITBA

> El resultado es informativo. No constituye asesoramiento financiero ni una recomendación de compra o venta.

## Privacidad y trazabilidad

No ingresar datos personales o sensibles. Las consultas pueden procesarse mediante servicios
externos y almacenarse para trazabilidad técnica. Este aviso describe el comportamiento actual;
el MVP todavía no implementa una política de retención o borrado automático.

## Problema y usuario

El proyecto responde consultas sobre acciones domésticas argentinas. Está pensado para una persona que quiere una lectura técnica trazable sin tener que buscar precios, calcular indicadores y comparar señales manualmente.

El alcance es el análisis técnico. Los pedidos fundamentales o integrales se rechazan explícitamente como fuera del alcance del MVP.

## Qué hace

Ante una consulta, el agente:

1. identifica el tipo de análisis y el activo;
2. decide qué herramienta ejecutar;
3. obtiene y valida el histórico de mercado;
4. calcula SMA, EMA, RSI y MACD en Python;
5. evalúa tendencia, momentum, contradicciones y calidad de datos;
6. genera un resultado con fuentes, limitaciones y traza;
7. si el usuario pide finalizar un informe, pausa antes de publicarlo para permitir aprobarlo, modificarlo o rechazarlo.

## Arquitectura

Se usa un agente único. El LLM planifica el próximo paso, pero no puede inventar el activo, los precios, los indicadores ni la conclusión técnica.

```text
Web / API
    ↓
FastAPI ───────────────→ Presenter
    ↓                         ↑
EquityAgent ───────────→ FinalAnalysis
    │
    ├── LLM provider: Fake o Gemini
    ├── ToolRegistry
    │     ├── resolve_asset
    │     ├── get_market_history
    │     └── calculate_technical_indicators
    ├── reglas técnicas deterministas
    └── Repository
          ├── SQLite: ejecución local reproducible
          └── PostgreSQL: Vercel y producción
```

Componentes principales:

- `src/merval_agent/agents/equity_agent.py`: loop del agente.
- `src/merval_agent/tools/registry.py`: herramientas y precondiciones.
- `src/merval_agent/adapters/market_tracker.py`: mercado y normalización.
- `src/merval_agent/domain/technical.py`: indicadores.
- `src/merval_agent/domain/technical_assessment.py`: señales y calidad.
- `src/merval_agent/agents/report.py`: construcción de `FinalAnalysis`.
- `src/merval_agent/memory/`: persistencia e HITL.
- `src/merval_agent/api/app.py`: API y aplicación web.

## Decisiones técnicas

### Agente único

El alcance no necesita agentes especializados independientes. Un solo loop hace más simple seguir la traza, aplicar límites de pasos y mantener una autoridad determinista sobre los resultados.

### Cálculos fuera del LLM

Los indicadores y las señales se calculan en Python. El modelo sólo propone acciones estructuradas. Cada propuesta se valida antes de ejecutar una herramienta.

### Sin RAG productivo

No hay RAG ni retrieval local: el MVP no cuenta con un corpus autoritativo que aporte valor al caso. Un pedido atribuido explícitamente a Murphy se rechaza por falta de una fuente verificable.

### Estado y memoria

`AgentState` conserva el estado durante la ejecución. El repositorio persiste el resultado, la
traza, las acciones pendientes y las decisiones humanas. SQLite es el default local;
`DATABASE_URL` activa PostgreSQL para que esos datos sobrevivan a reinicios e instancias
serverless independientes.

### Human-in-the-Loop

La solicitud explícita de preparar/finalizar un informe técnico crea un snapshot inmutable y devuelve `PAUSED`. La continuación usa versión esperada e idempotency key. Aprobar no vuelve a consultar al LLM ni al mercado.

### Integraciones

- Argentina Market Tracker: histórico y cotización.
- Gemini: planificación del agente.
- SQLite: persistencia local.
- PostgreSQL: persistencia durable opcional para el despliegue.

## Skill reutilizable

La skill de dominio se encuentra en:

```text
src/merval_agent/skills/merval_equity_analysis/SKILL.md
```

Incluye el procedimiento, contratos, herramientas y ejemplos para repetir el análisis con las mismas reglas.

## Instalación

Requiere Python 3.11 o posterior.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Los defaults usan `LLM_PROVIDER=fake`, por lo que la aplicación puede iniciarse sin una API key.

## Configuración

Variables principales:

| Variable | Uso |
|---|---|
| `LLM_PROVIDER` | `fake` o `gemini` |
| `LLM_BASE_URL` | endpoint del provider |
| `LLM_MODEL` | modelo solicitado |
| `LLM_API_KEY` | credencial; no versionar |
| `MARKET_TRACKER_BASE_URL` | fuente de precios |
| `DATABASE_PATH` | archivo SQLite local |
| `DATABASE_URL` | PostgreSQL productivo; si está definido tiene precedencia |
| `MAX_AGENT_STEPS` | presupuesto máximo de decisiones |
| `RATE_LIMIT_ENABLED` | activa la protección de endpoints públicos costosos |
| `RATE_LIMIT_*_PER_MINUTE` | cuotas por cliente para chat, ejecución y decisiones HITL |

La lista completa y valores seguros están en `.env.example`.

### Rate limiting

`POST /chat` y `POST /agent/run` tienen cuotas independientes. Las decisiones HITL
`approve`, `modify` y `reject` comparten otra cuota. Los valores se configuran por entorno con
las variables `RATE_LIMIT_*`; al excederlos, la API responde `429` con un mensaje genérico y
`Retry-After`, antes de ejecutar el agente o la decisión. `/health`, la portada, los assets y las
lecturas HITL no consumen cuota.

En producción la cuota se coordina mediante PostgreSQL entre instancias de Vercel. Localmente se
usa SQLite, y los repositorios fake de tests disponen de un fallback en memoria. La clave guardada
es una huella SHA-256 de la dirección normalizada del cliente, no la IP completa.

## Ejecución

```powershell
.venv\Scripts\python -m uvicorn merval_agent.api.app:app --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000`.

Ejemplo API:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/chat `
  -ContentType "application/json" `
  -Body '{"message":"Analizá técnicamente GGAL","session_id":"demo"}'
```

## Despliegue en Vercel

El repositorio incluye `app.py` como entrypoint y `vercel.json` para el runtime FastAPI. El
despliegue productivo no usa el archivo SQLite local: necesita una URL PostgreSQL durable para
conservar trazas y acciones HITL entre invocaciones.

1. Importar este repositorio en Vercel.
2. Conectar una base PostgreSQL desde Vercel Marketplace o un proveedor equivalente.
3. Configurar `DATABASE_URL` y las variables del provider en Production y Preview.
4. Marcar `DATABASE_URL` y `LLM_API_KEY` como variables sensibles.
5. Desplegar. El repositorio crea el esquema idempotente bajo un advisory lock.
6. Verificar `/health`; debe informar `PostgresRepository` como `storage`.
7. Ejecutar un informe hasta `PAUSED`, abrir otra sesión y aprobar la misma acción. Ese recorrido
   comprueba persistencia real, idempotencia y continuidad del HITL.

Prueba opt-in contra una base PostgreSQL de testing:

```powershell
.venv\Scripts\python scripts/bootstrap_postgres.py
.venv\Scripts\python -m pytest -q -m live tests/integration/test_postgres_live.py
```

El inicializador solicita la contraseña del administrador `postgres` mediante entrada oculta,
crea el rol y la base aislados `merval_agent_test`, genera otra contraseña aleatoria para ese rol
y guarda `TEST_DATABASE_URL` en el `.env` ignorado por Git. No cambia `DATABASE_URL`, por lo que
la aplicación local continúa usando SQLite salvo que se configure expresamente lo contrario.

Usar una conexión PostgreSQL con SSL y pooling recomendada por el proveedor. Conviene ubicar la
función de Vercel y la base en regiones cercanas. No copiar valores reales a `.env.example` ni al
repositorio. SQLite y `LLM_PROVIDER=fake` se conservan para que la evaluación local siga siendo
reproducible sin servicios pagos.

## Demo reproducible

Smoke completo de API y frontend contra un mercado local simulado:

```powershell
.venv\Scripts\python scripts/smoke_api.py
```

El flujo HITL se valida dentro de la suite de integración, incluida la persistencia,
idempotencia, modificación, aprobación y rechazo de acciones pendientes.

Para inspeccionar una traza persistida:

```powershell
.venv\Scripts\python scripts/show_trace.py TRACE_ID
```

## Tests

La suite conservada cubre contratos, adaptadores, agente, cálculo técnico, assessment, presentación, API, HITL y el flujo E2E:

```powershell
.venv\Scripts\python -m pytest -q
```

No necesita red. Los providers y fuentes externas se simulan en los tests.

## Evaluación

El dataset y la evidencia se encuentran en `evals/`.

Ejecución offline con el provider Fake:

```powershell
.venv\Scripts\python scripts/eval_real_llm.py --fake
```

La evaluación offline vigente cubre 16 casos técnicos, ambigüedad, errores de fuente,
alcance no soportado e instrucciones adversariales. Resultado: 16/16 casos aprobados,
sin herramientas prohibidas ni llamadas duplicadas.

Detalle: `evals/mvp_evaluation_summary.json`.

## Limitaciones

- No brinda asesoramiento financiero personalizado.
- La pertenencia a BYMA se valida con catálogo o metadata del proveedor; no se certifica pertenencia a un índice.
- La última cotización puede ser provisional.
- No existe un calendario bursátil completo; la vigencia usa una tolerancia configurable.
- El análisis fundamental y la extracción de balances están fuera de alcance.
- No se recuperan ni atribuyen metodologías de libros.
- La ejecución con un LLM real depende de disponibilidad, cuota y configuración del proveedor.
- El despliegue en Vercel depende de PostgreSQL externo; SQLite sólo está soportado como
  persistencia local.

## Estructura mínima

```text
app.py               entrypoint de Vercel
vercel.json           runtime FastAPI con Fluid Compute
src/merval_agent/     aplicación y repositorios
tests/                pruebas del camino principal
scripts/              demo, smoke, evaluación y trazas
evals/                datasets y resultado publicado
.env.example          configuración reproducible
pyproject.toml        dependencias y paquete
```
