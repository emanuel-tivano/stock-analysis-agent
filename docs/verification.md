# Phase 1 Release Candidate — verificación 2026-09-15

## Resultado y salvedad para congelar

Windows, Python 3.14.6. Baseline ejecutada antes de editar: 55 tests offline aprobados,
2 live omitidos. Resultado final: **87 offline aprobados y 2 live aprobados por separado**.
Fase 2 permanece pendiente.

Esta carpeta no contiene `.git`: `git status --short` falla con “not a git repository”.
No se pueden certificar archivos trackeados, historial ni ausencia de secretos en ese historial.
No se creó un repositorio ni se hicieron commits, pushes, tags, releases o deploys.

## Verificación final ejecutada

En este orden, después del último cambio de código:

| Comando | Resultado |
|---|---|
| `python -m ruff check src tests scripts` | PASS |
| `python -m ruff format --check src tests scripts` | PASS, 48 archivos |
| `python -m pytest -q` | 87 PASS, 2 live SKIP |
| `python -m pytest tests/integration/test_evals.py -q -s` | 7 PASS |
| `python scripts/smoke_api.py` | PASS: Uvicorn, health 200, agent/run 200 CLARIFY y limpieza |
| `python -m pip check` | No broken requirements found |
| `RUN_LIVE_TESTS=1`, `python -m pytest tests/integration/test_live.py -q` | 2 PASS |

Los live fallaron inicialmente por sockets bloqueados (WinError 10013); pasaron con acceso
de red autorizado fuera del sandbox. Continúan siendo opt-in.

Reporte agregado: cases=7, passed=7, failed=0, tool_selection_accuracy=1.0,
forbidden_tool_violations=0, average_steps=3.857142857142857.
Las siete evals están incluidas en los 87 tests offline. Miden regresiones del fake,
selección de herramientas y contratos, no inteligencia de un LLM.

Se creó `.venv-rc` sin paquetes previos y se ejecutó:

```powershell
.venv-rc\Scripts\python -m pip install -e ".[dev]" -c requirements-tested.txt
.venv-rc\Scripts\python -m pytest -q
.venv-rc\Scripts\python -m pip check
```

Instalación PASS; suite final 87 PASS, 2 SKIP; dependencias compatibles. La descarga también
requirió acceso de red autorizado. No se cambiaron versiones de dependencias. `>=3.11` sigue
siendo el mínimo declarado; solo Python 3.14.6 fue probado aquí.

Warnings restantes: deprecaciones externas de Starlette/TestClient sobre httpx y
BlockingPortal, y warning del cache pytest al ejecutar live fuera del sandbox.

## Problemas y correcciones

- SQLite guardaba tools, pero no decisiones ni todas las transiciones. Ahora persiste eventos
  sanitizados recuperables por trace_id sin cambiar FinalAnalysis. Migración aditiva;
  no se reconstruyen eventos anteriores.
- Las abstenciones ahora incluyen AGENT_ABSTAINED y AGENT_FINISHED. Se registran decisiones
  inválidas y transiciones por errores, límite de pasos y suficiencia del reporte.
- El filtro de argumentos de logs excluía Murphy/Graham por longitud. Ahora permite valores
  categóricos conocidos y conserva la fuente sin guardar texto libre.
- JSON no objeto o metadata inválida podía producir AttributeError en Market Tracker.
  Ahora genera el error de servicio normalizado; meta.stale debe ser booleano.
- Horizonte implícito centralizado en domain/policy.py: default 6M.
- Las conexiones SQLite no se cerraban explícitamente: el context manager solo administra
  transacciones. Se agregó contextlib.closing y una prueba de cierre tras crear, guardar y leer.
  Se observó un bloqueo intermitente al limpiar el smoke en Windows; después de corregir el
  cierre pasaron tres repeticiones del smoke y la ejecución final. No se garantiza eliminar
  todo posible bloqueo externo de archivos.
- Gitignore ampliado para bases .db, logs, variantes de .env, PDFs y entornos de verificación.

No se reescribieron indicadores, parser Bolsar, rutas FastAPI ni política de suficiencia.
Se mantiene un agente, loop explícito y decisiones dinámicas del provider.

## Cobertura incorporada

32 casos adicionales respecto de la baseline, incluidas dos evals nuevas:

- Cinco golden traces: técnico GGAL, fundamentos PAMP, XXXX, Murphy DEMO y falla Market Tracker.
  Comparan secuencia, steps, estados, fuente metodológica, persistencia y CLI.
- Default 6M, tools fuera de alcance y cuatro estados terminales por API.
- FINAL_ANSWER sin activo, respuesta sin datos y trazado de decisiones inválidas.
- Migración SQLite, recuperación inexistente, privacidad y cierre de conexiones.
- JSON no objeto, metadata, rango, timezone, monedas mezcladas y timeout.
- Bolsar: español, protocol-relative, período fiscal desconocido, tabla vacía y fila incompleta.
  Las pruebas existentes cubren columnas ocultas y prioridad del balance completo.
- EMA12/26, MACD/señal, sample_size, un punto, volumen requerido y NaN/infinito en boundaries.
  Las pruebas anteriores cubren SMA, RSI Wilder, series constantes y fechas duplicadas.
- Bytes UTF-8, request con á é í ó ú ñ ¿, Swagger HTML y OpenAPI.

Las pruebas existentes conservan reordenamiento de tools, ampliación del rango según
observaciones, errores externos y MAX_AGENT_STEPS. No se agregó un workflow fijo.

## Encoding y privacidad

Se decodificaron estrictamente como UTF-8 los 58 archivos de texto inspeccionados sin errores.
La API contiene los bytes correctos de “Métricas técnicas”, “conclusión” y “Metodología”;
Content-Type es application/json. /docs y OpenAPI responden 200. Se verificó el HTML de
Swagger con TestClient; no una interacción visual en navegador.

PowerShell mostró mojibake al leer sin encoding explícito. Su pipe también reemplazó acentos
al crear inicialmente pruebas nuevas; esos archivos se corrigieron y las pruebas finales
usan caracteres reales. README documenta Get-Content -Encoding UTF8, Console.OutputEncoding
y OutputEncoding. No se modificó la serialización del servidor.

La búsqueda de API_KEY, Authorization, Bearer, password, secret y token encontró referencias
de configuración, adapter, tokens del resolver y valores sintéticos de tests. No se encontraron
credenciales reales en los textos auditados ni patrones de claves privadas. No se inspeccionó
el contenido privado de PDFs ni se modificaron los originales. Gitignore no certifica el
índice/historial ausente. SQLite conserva el pedido privado por contrato; el inspector no
lo imprime y no sustituye permisos de acceso al archivo local.

## Ejemplo real recuperable

Pedido: “Analizá técnicamente GGAL”. Resultado comprobado:

- trace_id: 1132266a-2918-45ff-af7d-8fd3ed8169ea.
- ANSWER, ticker GGAL, analysis_type technical.
- fundamental NOT_REQUESTED, technical INSUFFICIENT_DATA.
- Mercado live, 124 barras, todos los indicadores presentes.
- Murphy DEMO, sin categoría direccional ni recomendación, cero errores.
- Recuperación comprobada con get_trace y CLI.

```powershell
python scripts/show_trace.py 1132266a-2918-45ff-af7d-8fd3ed8169ea
```

| Step | Decisión/tool | Resultado | Latencia |
|---|---|---|---|
| 1 | CALL_TOOL resolve_asset | GGAL | 0.25 ms |
| 2 | CALL_TOOL get_market_history | 6M, live | 393.78 ms |
| 3 | CALL_TOOL calculate_technical_indicators | Métricas | 0.34 ms |
| 4 | CALL_TOOL search_methodology | DEMO | 0.05 ms |
| 5 | FINAL_ANSWER | ANSWER, cierre | — |

La traza vive en la base local ignorada, no viaja con el código. Los golden tests generan
trazas offline. Este run precedió al ajuste de argumentos Murphy/Graham y al cierre explícito
de conexiones; ambos ajustes posteriores pasaron la suite final, que también verifica trazas
producidas con el código final.

ANSWER significa datos/cálculos respondibles; INSUFFICIENT_DATA indica ausencia de conclusión
metodológica validada. NOT_REQUESTED no es insuficiencia.

## Archivos intervenidos

Nuevos:

- src/merval_agent/domain/policy.py
- scripts/show_trace.py
- tests/integration/test_trace_baseline.py

Modificados:

- .gitignore; README.md; docs/architecture.md; docs/verification.md
- evals/README.md; evals/dataset.jsonl
- src/merval_agent/agents/equity_agent.py; src/merval_agent/domain/models.py
- src/merval_agent/adapters/llm/fake.py; src/merval_agent/adapters/market_tracker.py
- src/merval_agent/memory/sqlite.py
- src/merval_agent/skills/merval_equity_analysis/SKILL.md
- tests/unit/test_adapters.py; tests/unit/test_technical.py; tests/unit/test_recovery.py
- tests/integration/test_api_storage.py; tests/integration/test_evals.py

Artefactos locales: .venv-rc, caches y nueva ejecución en SQLite. No se modificaron
pyproject.toml, requirements-tested.txt, .env.example ni PDFs.

## Riesgos y Fase 2 pendiente

Los servicios pueden cambiar contratos/disponibilidad. Recencia en días calendario no garantiza
ajustes corporativos ni cobertura. Los eventos se persisten al finalizar: una interrupción puede
conservar solo logs. Si falla SQLite, ERROR queda en respuesta/logs sin recuperación garantizada.

Reservado y sin implementar:

1. LLM real y evaluación de razonamiento, interpretación y fidelidad.
2. Ingesta privada, embeddings, base vectorial y RAG Murphy/Graham con citas verificables.
3. Descarga/extracción de balances, OCR, ratios por sector y valoración Graham.
4. HITL ejecutable y side effects: alertas, emails, brokers y órdenes requieren alcance y
   autorización específicos futuros.
5. Memoria conversacional/reanudación y ampliación de cobertura e históricos.
6. Frontend, deploy, autenticación de publicación y Docker requieren otra iteración.

LangGraph y multiagente no se agregaron ni se consideran requisitos de Fase 2.
La baseline no ofrece recomendaciones financieras ni aplicación autoritativa de libros.

## Verificación Fase 2A — 2026-09-15

La sección anterior conserva el registro histórico de Fase 1. Se auditó `b0dfdab` con
árbol limpio y sin tags locales. Previo a cambios: 87 PASS, 2 live SKIP.

| Comando final | Resultado |
| --- | --- |
| `python -m ruff check src tests scripts` | PASS |
| `python -m ruff format --check src tests scripts` | PASS, 55 archivos |
| `python -m pytest -q` | 108 PASS, 3 SKIP |
| `python -m pytest tests/integration/test_evals.py -q -s` | 7 PASS |
| `python scripts/smoke_api.py` | health 200, run 200 CLARIFY |
| `python -m pip check` | PASS |
| `python scripts/eval_real_llm.py --fake --runs 3` | 45/51 éxitos, reporte guardado, exit 1 por casos nuevos fallidos |

Persisten las dos advertencias de deprecación de Starlette observadas en la baseline.
Los 3 SKIP corresponden a 2 tests live de datos y el nuevo test del LLM real.
Los 21 tests offline adicionales verifican transporte inválido, retries acotados,
precondiciones, ramas prohibidas, duplicados vs retry de ERROR, privacidad, contexto acotado,
prosa no verificada, formatos estructurados, scoring, usage/costo y persistencia por repetición.

### Comparación registrada

| Métrica (17 casos × 3) | Fake | Real |
| --- | ---: | --- |
| task_success_rate | 88,24% | No ejecutado |
| tool_selection_accuracy | 94,12% | No ejecutado |
| forbidden_tool_violations | 6 | No ejecutado |
| invalid_decision_rate | 0% | No ejecutado |
| duplicate_tool_call_rate | 0% | No ejecutado |
| abstention_correctness | 93,75% | No ejecutado |
| clarification_correctness | 66,67% | No ejecutado |
| average_steps | 4,294 | No ejecutado |
| average_latency (ms) | 15,384 | No ejecutado |
| max_steps_exceeded / provider_errors | 0 / 0 | No ejecutado |
| tokens / cost | null / null | No ejecutado |

Fallos Fake: fuera de alcance (CLARIFY en lugar de ABSTAIN) y contradicción (continúa
análisis técnico sin aclarar). No se alteró Fake para mejorar resultados del dataset ampliado.
Las siete evals de Fase 1 siguen aprobadas y sus golden traces exactos siguen iguales.

Reporte local: `evals/results/fake_baseline.json`; SQLite: `evals/results/traces.sqlite3`.
Se verificó `show_trace.py` sobre `94ea1d80-e744-49fa-8152-b22a30d53331` (**Fake**, GGAL,
ANSWER, 5 steps, resolve_asset → get_market_history 6M → calculate_technical_indicators →
search_methodology Murphy DEMO → FINAL_ANSWER). Este trace no representa un modelo externo.

**Pruebas reales no ejecutadas**: LLM_BASE_URL, LLM_MODEL y LLM_API_KEY no configurados.
No existe trace real ni comparación empírica Real; no se ejecutó nuevo milestone con
Market Tracker externo. Los resultados live históricos arriba no validan el nuevo provider.
La Definition of Done completa de Fase 2A queda pendiente de esa evidencia.

Guía, decisiones de diseño y propuesta separada de Fase 2B:
[phase2a-real-llm.md](phase2a-real-llm.md). No se hicieron commit, push, tag, release ni deploy.

### Inventario de cambios Fase 2A

Modificados:

- `.env.example`, `.gitignore`
- `README.md`, `docs/architecture.md`, `docs/verification.md`, `evals/README.md`
- `src/merval_agent/adapters/llm/compatible.py`
- `src/merval_agent/agents/equity_agent.py`
- `src/merval_agent/bootstrap.py`, `src/merval_agent/config.py`

Agregados:

- `docs/phase2a-real-llm.md`
- `src/merval_agent/adapters/llm/context.py`, `src/merval_agent/evaluation.py`
- `scripts/eval_real_llm.py`, `scripts/run_real_llm.py`
- `evals/real_llm_dataset.jsonl`, `evals/results/.gitkeep`
- `tests/integration/test_real_llm.py`
- `tests/unit/test_real_llm_robustness.py`, `tests/unit/test_real_llm_evaluation.py`

Artefactos generados locales ignorados: `evals/results/fake_baseline.json` y
`evals/results/traces.sqlite3`. No se incluyen como archivos a versionar.

## Actualización Gemini nativo — 2026-09-15

Los registros anteriores describen la evidencia histórica de Fase 2A. Resultado final de
esta extensión: **130 PASS, 4 SKIP**, Ruff PASS, format PASS (58 archivos), 7 evals originales
PASS, smoke API PASS y pip check PASS.

Prueba mínima Gemini real: PASS (CLARIFY). Primer agente Gemini:
`b1473d6a-a900-4825-be90-3ffae4ddc34f`, ERROR por 503/429 después de resolver GGAL y consultar
historial real 6M. Technical; fundamental NOT_REQUESTED. La validación externa es parcial:
no se completaron indicadores/metodología/respuesta final, ni dataset real de 17 casos.

Resultados, errores, usage, comandos e inventario:
[gemini-native.md](gemini-native.md). No se realizaron operaciones Git de publicación.
