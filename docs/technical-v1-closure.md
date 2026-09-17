# Cierre y evaluación de la V1 técnica

**V1 TÉCNICA CERRADA**, para el recorrido técnico determinístico descrito aquí.
Verificación final: 17/09/2026. Se puede comenzar análisis fundamental como una etapa
separada. Este dictamen no certifica el desempeño de un LLM real, trading en producción,
ajustes corporativos ni exactitud económica de la fuente de precios.

El alcance permanece en un agente, FastAPI, herramientas existentes y Python para
cálculos, suficiencia, señales, confianza y narrativa financiera. No se agregaron
indicadores financieros al contrato, frameworks, RAG ni extracción fundamental.
No se hicieron commits, push, resets ni borrados de resultados. No se abrieron secretos.

## Evidencia y baseline

Directorio de esta pasada: `evals/results/technical-v1-20260916T215304/` (ignorado por Git).
Estado inicial: `initial-status.txt`; copia previa: ubicación en `baseline-location.json`.
Los archivos `baseline-*.txt` y `baseline-checks.json` registran comandos y duración.
La baseline real fue **393 passed, 4 skipped, 0 failed, 2 warnings**, no 366.
Integración inicial: 40 passed, 4 skipped; Fake histórico: 17/17. Lint, formato,
dependencias y smoke también aprobaron.

Resultados finales autoritativos: `verified-checks.json`, `verified-*.txt`,
`verified-historical-fake/fake_baseline.json` y `verified-technical-fake/evaluation.json`.
Las ejecuciones intermedias se conservan; no se mezclaron casos de corridas distintas.
El prefijo anterior `final-*` corresponde a una corrida intermedia que encontró una
regresión de CLARIFY (1 failed, 626 passed). Se corrigió y se repitió toda la suite.

## Resultados exactos

| Comprobación | Resultado final | Duración externa | Baseline |
|---|---|---:|---:|
| pytest | 628 passed, 4 skipped, 0 failed, 2 warnings (11,87 s de pytest) | 13.06 s | 14.29 s |
| lint | PASS | 0.17 s | 0.18 s |
| format | PASS, 89 archivos | 0.17 s | 0.15 s |
| dependencies | PASS, sin dependencias rotas | 0.74 s | 0.99 s |
| integration | 73 passed, 4 skipped, 0 failed, 2 warnings (6,09 s de pytest) | 7.27 s | 5.54 s |
| smoke | GET /health=200; POST /agent/run=200 CLARIFY | 1.56 s | 2.06 s |
| fake | 17/17, 0 fallos funcionales, 0 fallos de proveedor | 1.04 s | 1.12 s |
| technical-fake | 33/33, 0 fallos funcionales, 0 fallos de proveedor Fake | 2.78 s | nuevo |

Los 4 omitidos siguen opt-in: dos tests de servicios reales y dos de LLM real. La captura
pública separada sí se ejecutó; no convierte esos skips en tests aprobados.
Warnings conservados: `StarletteDeprecationWarning` sobre httpx/TestClient y
`DeprecationWarning` sobre `anyio.abc.BlockingPortal`. No se ocultaron ni se actualizaron
dependencias sin necesidad. Los warnings del adapter en escenarios de quote fallida y
fila inválida son salidas esperadas de esos escenarios.

Comandos de verificación (PowerShell, desde la raíz):

```powershell
$env:RUN_LIVE_TESTS="0"
$env:RUN_LLM_TESTS="0"
.venv\Scripts\python.exe -m pytest -q -ra
.venv\Scripts\python.exe -m ruff check src tests scripts
.venv\Scripts\python.exe -m ruff format --check src tests scripts
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m pytest tests/integration -q -ra
.venv\Scripts\python.exe scripts/smoke_api.py
.venv\Scripts\python.exe scripts/eval_technical_v1.py
```

La evaluación histórica se ejecutó con `evaluate(Settings.model_construct(), fake=True,
output_dir=<directorio nuevo>)`; el comando literal y su salida están en
`verified-checks.json` y `verified-fake.txt`. El smoke final se lanzó desde un directorio
vacío con ruta absoluta del script para evitar cargar `.env`. La demo nueva usa ajustes
construidos sin leer `.env` ni secretos del entorno y crea siempre un directorio nuevo.

## Criterios de aceptación

| Criterio | Estado | Evidencia / comando o test | Limitación restante |
|---|---|---|---|
| Suite completa | PASS | `pytest -q -ra`: 628/0/4 | Integraciones opt-in separadas |
| Lint y formato | PASS | Ruff check y format, 89 archivos | Ninguna en este entorno |
| Dependencias | PASS | `pip check` | Windows/Python actual; otras versiones no evaluadas |
| Smoke API | PASS | `scripts/smoke_api.py` | Smoke usa Fake |
| Indicadores contrastados | PASS | 181 casos en `test_technical_v1_reference.py`; 2 snapshots reales | La referencia valida matemática, no proveedor económico |
| Matriz de escenarios | PASS | 33 casos HTTP en `test_technical_v1_matrix.py`, más tests de reglas y adapters | Un activo por análisis |
| Evaluación Fake | PASS | Histórico 17/17; técnico 33/33, cada corrida completa | No mide razonamiento de un LLM |
| Ejecución real o bloqueo documentado | PASS | `live-capture-retry/capture.json`: GGAL y BMA, cuatro HTTP 200 | Fuente pública única; selección de tools Fake |
| Respuesta específica y consistente | PASS | Matriz HTTP; tests de adulteración; cuatro JSON completos | Narrativa determinista, no redacción libre |
| Datos e indicadores trazables | PASS | Snapshots, hashes, SQLite y `trace-verification.json` | Producción no archiva snapshots automáticamente; los runners sí |
| Evidencia parcial | PASS | 15/34 observaciones, volumen null, filas descartadas; BMA real PARTIAL | Faltantes no se interpolan |
| Cifras del LLM no publicadas | PASS | Test adversarial preexistente y nuevo test del evaluador | Transporte LLM real no ejecutado en esta pasada |
| Sin recomendaciones categóricas | PASS | Narrativa, reglas RSI y eje `unsupported_claims` | No es asesoramiento financiero |
| Documentación alineada | PASS | Este informe, README y ejemplos completos | Docs v3/v4 conservadas como antecedentes |
| Demo reproducible | PASS | `scripts/eval_technical_v1.py`: datos controlados, reloj fijo, SQLite | No representa precios reales |
| Limitaciones documentadas | PASS | Sección de deuda abajo | Calendario, ajustes y fuente aún sin certificación |
| Evaluación con proveedor LLM real (adicional) | NOT_EVALUATED | Sin llamadas ni credenciales leídas | Ejecutar opt-in en una etapa específica |

## Defectos corregidos y compatibilidad

1. **Intención técnica incompleta:** RSI, momentum, sobrecompra/sobreventa y tendencia
   no fijaban la dimensión de forma compartida. Se amplió `explicit_analysis_type` y Fake
   lo reutiliza. Se evita que una propuesta de tools/final del proveedor cambie una
   dimensión explícita antes del primer tool. CLARIFY/ABSTAIN siguen permitidos.
2. **Conflicto oculto:** RSI y territorio MACD opuestos podían mantener una conclusión
   direccional por precedencia de tendencia. Ahora esa discrepancia produce MIXED.
   Se conserva v4: MACD negativo pero encima de su señal es mejora relativa todavía
   bajista; no equivale por sí solo a reversión. Todos esos matices siguen enumerados.
3. **Volumen sin comprobación local:** solo se mostraba un promedio global. Se compara
   la última barra con las 20 previas si las 21 tienen volumen conocido y no se incluyó
   quote provisional. Mayor volumen que un promedio positivo acompaña el signo del
   cambio del último cierre; sin ese soporte la lectura es NEUTRAL/UNAVAILABLE. No cambia
   la conclusión de precios ni constituye pronóstico. Un null antiguo conserva promedio
   global null aunque la ventana reciente sea utilizable; el texto no lo contradice.
4. **Recepción futura dentro del mismo día:** se comparaban solo fechas. Se rechazan
   timestamps futuros y quote observada después de recepción. Los fixtures antiguos
   fechaban al mediodía de hoy y fallaban antes del mediodía: ahora usan recepción real.
5. **Alcance integral:** pedidos explícitos integrales o técnico+fundamental ya no pueden
   terminar como completos con solo precios. ABSTAIN explica la dimensión faltante y
   conserva evidencia técnica. Se mantiene el comportamiento histórico del genérico
   “Analizá GGAL” como respuesta parcial con la dimensión fundamental insuficiente.
6. **Actualización fallida con indicadores previos:** ERROR podía conservar confianza o
   conclusión direccional vigente. Ahora confianza/conclusión son UNAVAILABLE; las
   métricas previas permanecen como evidencia y el texto explica el fallo.
7. **Trazabilidad de la evaluación:** las primeras capturas guardaban JSON ordenado y
   las trazas usaban orden del modelo: hashes de bytes distintos para objetos iguales.
   Se conservó el original y se agregó serialización idéntica a la traza, verificada.
   Los runners nuevos usan desde el inicio los mismos bytes que el hash productivo.

Regresiones reproducidas antes de sus correcciones: las siete iniciales fallaron;
los dos casos de cambio de intención/alcance y el de refresh fallido también fallaron.
Se agregó cobertura para volumen local con faltantes antiguos. El cambio de expectativa
“Tendencia de ALUA” de None a technical refleja el nuevo contrato solicitado, no una
relajación para ocultar un fallo. No se cambió ninguna fórmula financiera correcta.
No hay campos nuevos ni eliminados en el schema público. `signals.volume` puede ahora
ser direccional; los pedidos explícitamente integrales cambian de ANSWER parcial a
ABSTAIN, por defecto contractual demostrado.

## Matemática y reglas

Oráculo de evaluación `evaluation_reference.py`, sin imports de `domain.technical`:
Decimal con precisión 50 y sumas geométricas explícitas para EMA y Wilder. El runtime
productivo no lo importa ni se agregó biblioteca. Comparación de todos los campos,
incluidos null y sample_size, con `rel_tol=1e-10`, `abs_tol=1e-9`.

- SMA20/50: media de las últimas 20/50 observaciones.
- EMA12/26: seed SMA de las primeras 12/26; alfa 2/(p+1), sin redondeo intermedio.
- RSI14: 15 precios mínimos, 14 diferencias iniciales y Wilder alfa 1/14. Serie plana 50,
  solo subidas 100, solo bajas 0. Sobrecompra/sobreventa no dispara compra/venta.
- MACD: EMA12−EMA26 desde la observación 26; señal EMA9 desde la 34, histograma diferencia.
- Variación: primer/último cierre; n=1 no tiene variación; extremos usan high/low, volumen
  global requiere todos los valores conocidos; cero y null se prueban por separado.
- Tests cruzan 15 tamaños frontera × 4 patrones × 3 variantes de volumen = 180, más un
  caso manual lineal (SMA20=139,5; SMA50=124,5; EMA12=143,5; EMA26=136,5; MACD=señal=7).
- Fechas con huecos siguen siendo observaciones; no se rellenan sesiones inventadas.
  Duplicados/orden inválido/OHLC/no finitos se validan en dominio/adapter y tests existentes.
- Mínimo 15 observaciones para PARTIAL; COMPLETE requiere todos los indicadores de
  precios y cero filas descartadas. Sin SMA50 no se pierde toda la evidencia disponible.
- Quote nueva se conserva explícitamente provisional, con volumen desconocido cuando
  falta. Quote de misma fecha no reemplaza histórico; incompatible se excluye. Base
  desactualizada sigue STALE. `history_closed_status=UNVERIFIED` no certifica rueda cerrada.
- Confianza describe evidencia, no probabilidad de acierto. `confirmation` es alineación
  de indicadores de precios; `signals.volume` es evidencia local separada.
- La V1 describe relaciones de medias/MACD. Los fixtures de cruce demuestran relación
  negativa en la barra previa y positiva en la actual; no se agregó un detector ni se
  afirma un “cruce reciente” mirando un solo valor.

## Dataset y evaluación del agente

Dataset `evals/technical_v1_dataset.jsonl`, versión `technical-v1-closure-1`, 33 casos.
Expectativas escritas explícitamente, no derivadas del clasificador al ejecutar.
Reloj de fixtures 2026-09-16T22:00:00Z; no hay fechas ni tickers hardcodeados en reglas
productivas. Se ejercita POST /agent/run, schema, argumentos exactos, herramientas,
SQLite UTF-8, números independientes y hash de snapshots. Los tests de adulteración
hacen fallar el evaluador al cambiar cifras, texto, clasificación o traza.

| Eje | PASS | FAIL | NOT_EVALUATED |
|---|---:|---:|---:|
| schema | 33 | 0 | 0 |
| tool_selection | 33 | 0 | 0 |
| tool_arguments | 33 | 0 | 0 |
| classification | 33 | 0 | 0 |
| numbers | 23 | 0 | 10 |
| evidence | 23 | 0 | 10 |
| contradictions | 1 | 0 | 32 |
| insufficiency | 7 | 0 | 26 |
| external_errors | 4 | 0 | 29 |
| response_quality | 33 | 0 | 0 |
| unsupported_claims | 33 | 0 | 0 |
| tracing | 33 | 0 | 0 |

NOT_EVALUATED por caso significa que ese eje no tiene evidencia aplicable (por ejemplo,
no hay números en una aclaración); no suma como validación numérica. Las 33 respuestas
pasan los ejes aplicables en una única ejecución. Timestamp: `2026-09-17T05:32:59.050649+00:00`;
proveedor Fake, modelo null, prompt `NOT_APPLICABLE_FAKE`. El histórico usa la etiqueta
`technical-v3`, que no implica inferencia LLM cuando el proveedor es Fake.
La nueva evaluación no mide creatividad ni autonomía real del modelo. La narrativa
financiera se compara con la representación determinista exacta y las cifras con el
oráculo independiente, además de expectativas semánticas específicas.

Casos: alcista, bajista, neutral, SMA20>SMA50 con MACD negativo y señales mixtas,
sobrecompra fuerte, sobreventa bajista, cruces de EMA/MACD, volumen confirmatorio/null/cero,
15/14/34 observaciones, stale, quote posterior/igual/incompatible, fila OHLC inválida,
duplicados, 503, timeout, JSON inválido, Galicia ambiguo, nombre sin ticker, AAPL fuera de
catálogo, técnico explícito, integral y ambas dimensiones no disponibles, momentum BMA,
comparación GGAL+BMA, RSI y huecos. Los libros, balances y comparaciones múltiples no se
simulan como funcionalidades técnicas completas.

## Captura real y referencia independiente

Captura autorizada el `2026-09-17T05:24:32.571965+00:00` (~02:24 Argentina). El primer intento
quedó BLOCKED por ConnectError del sandbox; se conservó en `live-capture/capture.json`.
El reintento con permiso de red obtuvo HTTP 200 para history y quote de ambos activos.
No se usaron credenciales ni LLM real. Los datos reales se reprodujeron mediante el mismo
agente y POST /agent/run con Fake; esta distinción figura en cada artifact.

| Activo | Observaciones | Filas descartadas | as_of | Estado | Quote |
|---|---:|---:|---|---|---|
| GGAL | 125 | 0 | 2026-09-16 | ANSWER / COMPLETE / BEARISH | not_newer |
| BMA | 123 | 2 | 2026-09-16 | ANSWER / PARTIAL / BEARISH | not_newer |

Mercado bCBA; moneda `peso_Argentino`; rango 6M. Endpoints, recepción UTC, fetched_at,
fuente, moneda, cantidad y hashes: `live-capture-retry/capture.json`. No hubo quote nueva
incorporada en estas capturas. No se certifica cierre o ajustes de los precios históricos.

Comparación: producción frente a Decimal independiente sobre **idénticas observaciones**.
Valores redondeados aquí solo para lectura; `reference.json` conserva precisión completa.

| Indicador | GGAL producción | GGAL referencia | BMA producción | BMA referencia |
|---|---:|---:|---:|---:|
| current_price | 6745 | 6745 | 12130 | 12130 |
| sma20 | 6939.25 | 6939.25 | 12334 | 12334 |
| sma50 | 7382.6 | 7382.6 | 13312.4 | 13312.4 |
| ema12 | 6929.69527155 | 6929.69527155 | 12368.1138628 | 12368.1138628 |
| ema26 | 7045.81576811 | 7045.81576811 | 12600.4563024 | 12600.4563024 |
| rsi14 | 39.3453079744 | 39.3453079744 | 40.3503291937 | 40.3503291937 |
| macd | -116.12049656 | -116.12049656 | -232.342439615 | -232.342439615 |
| macd_signal | -117.920088857 | -117.920088857 | -266.473519444 | -266.473519444 |
| macd_histogram | 1.79959229728 | 1.79959229728 | 34.1310798282 | 34.1310798282 |
| change_percent | 12.4166666667 | 12.4166666667 | 25.8951738454 | 25.8951738454 |
| period_high | 8725 | 8725 | 15610 | 15610 |
| period_low | 5940 | 5940 | 9550 | 9550 |
| average_volume | 2652204.296 | 2652204.296 | 290939.585366 | 290939.585366 |
| sample_size | 125 | 125 | 123 | 123 |

Máxima diferencia absoluta: GGAL 9,095e−13; BMA 3,468e−12. Diferencias de coma flotante,
sin discrepancias materiales. No se alteraron seeds, fórmulas ni datos para coincidir.
No se comparó contra un portal con mercado, ajustes, sesión o temporalidad diferentes.
Una referencia matemática coincidente no verifica que la cotización del proveedor sea
correcta: esa comprobación económica contra otra fuente sigue fuera de esta validación.

Archivos por activo: `snapshot.json` original, `snapshot-trace-serialization.json`,
`response.json`, `reference.json`, `trace.sqlite3`. Ambos formatos de snapshot representan
el mismo objeto; `trace-verification.json` distingue sus hashes y comprueba el de SQLite.
Los snapshots originales permanecen intactos. Los runners nuevos guardan directamente
la serialización del modelo que se hashea en la traza.

Repetir la captura (genera directorio nuevo, cuatro solicitudes públicas, cero llamadas LLM):

```powershell
$env:RUN_LIVE_TESTS="1"
.venv\Scripts\python.exe scripts/capture_technical_v1.py --live
```

Si la red o la fuente fallan, el script registra BLOCKED y retorna código 1. No sustituye
la captura por fixtures. Para evaluar un LLM configurado, siguen disponibles las rutas
opt-in existentes `scripts/eval_real_llm.py` y `scripts/validate_technical_live.py`; no
atribuirles el 33/33 nuevo porque ese runner es deliberadamente Fake. Una evaluación del
nuevo dataset con proveedor real queda como trabajo explícito separado.

## Archivos y pruebas de esta pasada

Cambios sobre archivos existentes al inicio:
`adapters/llm/fake.py`, `agents/intent.py`, `agents/decisions.py`, `agents/report.py`,
`domain/technical_assessment.py`, `evaluation.py` (todos bajo `src/merval_agent/`),
`tests/conftest.py`, `tests/unit/test_phase2a_regressions.py`, `README.md`.

Nuevos respecto de la copia inicial:
`src/merval_agent/evaluation_reference.py`, `src/merval_agent/evaluation_technical_v1.py`,
`evals/technical_v1_dataset.jsonl`, `scripts/eval_technical_v1.py`,
`scripts/capture_technical_v1.py`, los cuatro tests siguientes y estos dos documentos.

- `test_technical_v1_reference.py`: 181 referencias numéricas independientes/manuales.
- `test_technical_v1_regressions.py`: 9 regresiones de intención, conflicto, tiempo y volumen.
- `test_technical_v1_evaluator.py`: 12 verificaciones de adulteración, cruces reales,
  alcance integral, error tras evidencia válida, opt-in y conservación de resultados.
- `tests/integration/test_technical_v1_matrix.py`: 33 casos HTTP completos.

Total nuevo: 235 tests; 393 → 628. Los archivos previos estaban modificados antes de
esta tarea; `initial-status.txt` conserva ese estado. La separación usa la copia de
entrada, no HEAD: `closure-task-changes.json` (hashes) y `closure-task-only.patch`.
HEAD cambió durante la sesión y algunos archivos ya aparecen versionados; esta tarea
no ejecutó git commit. Los archivos auxiliares egg-info preexistentes se excluyeron del
inventario. No se restauró ni sobrescribió el trabajo previo del usuario.

## Ejemplos completos, deuda y siguiente etapa

[Cuatro respuestas HTTP completas](technical-v1-examples.md): tendencia clara, señales
contradictorias, datos insuficientes y fallo técnico. Incluyen todos los campos públicos,
valores, fuentes, limitaciones, trace_id y metadata de generación.

Deuda abierta: evaluación del nuevo dataset con LLM real; calendario BYMA oficial;
ajustes corporativos/splits y validación económica contra una segunda fuente; conservar
snapshots automáticamente en despliegues productivos; compatibilidad con otras versiones
de Python/sistema operativo; migración futura de dependencias para resolver los dos
warnings. No hay certificación de rueda cerrada ni backtesting predictivo. La fuente
pública puede devolver filas inválidas (BMA lo demostró); PARTIAL lo deja explícito.
La demo es monoactivo; Galicia sin mercado y comparaciones requieren aclaración.

**Recomendación:** sí, comenzar el análisis fundamental en una etapa separada manteniendo
esta suite como regresión. Primero definir fuente, extracción verificable y contrato de
suficiencia fundamental. No reutilizar metadata documental como métricas económicas ni
presentar el análisis integral como implementado. Antes de una demo que dependa de un
modelo remoto, completar su evaluación opt-in: el cierre técnico no garantiza su servicio.

Mensaje de commit propuesto (no ejecutado):
`test: close technical v1 with independent math oracle and reproducible acceptance matrix`
