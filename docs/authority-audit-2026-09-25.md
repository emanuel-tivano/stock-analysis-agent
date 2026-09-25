# AuditorÃ­a de autoridad: Python, reglas y LLM

Fecha de corte: 2026-09-25
Fuente de verdad: working tree y tests actuales del repositorio.
Base Git observada: `61861df`; el working tree ya contenÃ­a cambios no relacionados con esta auditorÃ­a.
VerificaciÃ³n: `804 passed, 10 skipped` con `.venv\Scripts\python.exe -m pytest -q`.

## 1. Dictamen ejecutivo

La lectura tÃ©cnica publicada es, en la arquitectura actual, esencialmente determinÃ­stica. Python posee los datos normalizados, las fÃ³rmulas, la suficiencia, todas las seÃ±ales, la tendencia, el momentum, `momentum_state`, `confirmation`, `volume_confirmation`, los conflictos, la conclusiÃ³n, la confianza y la narrativa financiera. El LLM no tiene un schema para producir ninguno de esos campos: produce un `AgentDecision` operativo.

El LLM sÃ­ conserva autoridad relevante sobre la orquestaciÃ³n: propone intenciÃ³n cuando el pedido no la hace explÃ­cita, sÃ­mbolo/mercado, siguiente tool, perÃ­odo dentro del enum permitido y acciÃ³n terminal. Python valida schema, precondiciones, universo, identidad del activo, duplicados, reintentos e invariantes del reporte. Por eso la clasificaciÃ³n correcta no es â€œtodo Pythonâ€: la cadena es hÃ­brida, con autoridad financiera determinÃ­stica y autoridad operativa del LLM con guardrails.

La correcciÃ³n reciente de autoridad terminal funciona: un `ABSTAIN` propuesto por el LLM se reemplaza por `FINAL_ANSWER` cuando el pedido es tÃ©cnico ordinario, el assessment es `COMPLETE` o `PARTIAL`, no hay un pedido integral no soportado y no queda una metodologÃ­a explÃ­cita pendiente. La decisiÃ³n se vuelve a comprobar al construir el reporte. Los tests demuestran que no muta mÃ©tricas ni assessment y que conserva `ABSTAIN` para evidencia realmente insuficiente.

No encontrÃ© una ventaja medible que justifique entregar al LLM autoridad V1 sobre cÃ¡lculos, categorÃ­as canÃ³nicas o invariantes. SÃ­ hay un candidato razonable para experimentar offline: que proponga Ã©nfasis y explicaciÃ³n contextual de configuraciones mixtas sobre un assessment canÃ³nico inmutable, con Python validando cobertura, contradicciones, claims y categorÃ­as. No debe implementarse antes de medirlo.

Hallazgos que conviene registrar para el cierre V1, sin corregirlos en esta auditorÃ­a:

1. La defensa contra `ABSTAIN` estÃ¡ duplicada deliberadamente en resoluciÃ³n terminal y construcciÃ³n del reporte. Es defensa en profundidad, pero el predicado â€œanswerableâ€ tambiÃ©n aparece repetido como tuplas literales en fallback/HITL y puede derivar con el tiempo.
2. Un `CLARIFY` propuesto despuÃ©s de obtener un assessment publicable no recibe el mismo override que `ABSTAIN`. Por lo tanto, la invariante general â€œevidencia tÃ©cnica publicable implica publicaciÃ³nâ€ todavÃ­a no es absoluta; la correcciÃ³n actual cubre especÃ­ficamente `ABSTAIN`.
3. El rango real lo propone el LLM y Python sÃ³lo valida el enum. `6M` es default de polÃ­tica, prompt, fake provider y evaluaciÃ³n, pero no se inyecta determinÃ­sticamente en la llamada de un proveedor real.
4. El presenter vuelve a inferir la zona RSI leyendo substrings de una explicaciÃ³n y vuelve a inferir warnings leyendo prosa, aunque ya existen campos estructurados. Es duplicaciÃ³n accidental de semÃ¡ntica en una capa que deberÃ­a limitarse a presentaciÃ³n.
5. PerÃ­odos y warmups aparecen en cÃ¡lculo, assessment y oracle de evaluaciÃ³n. La duplicaciÃ³n con el oracle es intencional; la duplicaciÃ³n producciÃ³n `technical.py`/`technical_assessment.py` merece una Ãºnica especificaciÃ³n compartida o una prueba explÃ­cita de consistencia.
6. `LOW` existe en el contrato de confianza y en presentaciÃ³n, pero ninguna regla actual lo produce.

## 2. Leyenda de autoridad y tipos de regla

Autoridades usadas:

- `DATA_SOURCE`: hecho provisto por fuente externa, sujeto a validaciÃ³n local.
- `DETERMINISTIC_PYTHON`: cÃ¡lculo o decisiÃ³n reproducible en Python.
- `HARDCODED_DOMAIN_RULE`: threshold o polÃ­tica de dominio expresada en cÃ³digo.
- `CONFIGURATION`: valor configurable o enum de contrato.
- `LLM`: propuesta aceptada sin correcciÃ³n semÃ¡ntica determinÃ­stica equivalente.
- `LLM_WITH_GUARDRAIL`: el LLM propone y Python valida, normaliza, limita o reemplaza.
- `DETERMINISTIC_PRESENTER`: transformaciÃ³n de visualizaciÃ³n que no debe cambiar el dominio.
- `HUMAN_AUTHORITY`: aprobaciÃ³n editorial explÃ­cita del flujo HITL.

Tipos de regla distinguidos:

1. `FORMULA_ESTABLE`: identidad o fÃ³rmula matemÃ¡tica.
2. `THRESHOLD_TECNICO`: convenciÃ³n cuantitativa explÃ­cita.
3. `REGLA_DOMINIO`: semÃ¡ntica elegida por el proyecto.
4. `POLITICA_AUTORIDAD_SEGURIDAD`: lÃ­mites de autoridad, evidencia o seguridad.
5. `MAPPING_PRESENTACION`: traducciÃ³n/formato sin autoridad financiera.
6. `HEURISTICA_CONTEXTUAL`: elecciÃ³n donde podrÃ­a haber mÃ¡s de una opciÃ³n razonable.
7. `CONSTANTE_ACCIDENTAL_DUPLICADA`: repeticiÃ³n o acoplamiento no canÃ³nico.

## 3. Traza completa y mapa de autoridad actual

| Etapa | Archivo/lÃ­nea | Input | Output | Autoridad actual | Tipo de regla | Â¿LLM interviene? | Â¿Python puede corregir al LLM? | Tests | JustificaciÃ³n |
|---|---|---|---|---|---|---|---|---|---|
| Input del usuario | `api/app.py:29-40,134-153` | JSON `message`, `session_id` | `RunRequest`/`ChatRequest` | `DETERMINISTIC_PYTHON` | contrato/seguridad | No en validaciÃ³n | SÃ­; rechaza longitud, vacÃ­o y session id invÃ¡lido | `test_api_storage.py:10-24`; `test_web_ui.py:62-71` | Pydantic/FastAPI fija el contrato antes del agente. |
| DetecciÃ³n de intenciÃ³n explÃ­cita | `agents/intent.py:8-32`; `equity_agent.py:76-83` | texto | `technical`, `fundamental` o `None`; detecciÃ³n de full explÃ­cito | `HARDCODED_DOMAIN_RULE` | DespuÃ©s, si queda ambigua | SÃ­; una intenciÃ³n explÃ­cita precarga el estado y se valida contra propuestas operativas | `test_phase2a_regressions.py:13-29`; `test_technical_v1_regressions.py:35-44,82-99` | Regex normalizada posee autoridad sobre dimensiones explÃ­citas. |
| IntenciÃ³n no explÃ­cita | `models.py:42-45`; `context.py:69-92`; `equity_agent.py:155-187` | objetivo + estado | `UserIntent` | `LLM_WITH_GUARDRAIL` | SÃ­ | SÃ­; schema, branch guards e intent lock tras tools | `test_agent.py:101-148`; `test_real_llm_robustness.py:128-151` | El LLM elige la rama contextual; Python impide tools fuera de la rama. |
| ResoluciÃ³n del activo | `tools/assets.py:19-223`; `registry.py:148-170`; `market_tracker.py:216-330` | query y propuesta `symbol/market/company_name` | `AssetResolution` | `LLM_WITH_GUARDRAIL` + `DATA_SOURCE` | Propone sÃ­mbolo/mercado | SÃ­; catÃ¡logo/proveedor, regex, universo BYMA y clasificaciÃ³n reemplazan la propuesta | `test_asset_resolution_semantics.py:22-390`; `test_web_ui.py:105-186` | La propuesta nunca acredita existencia ni elegibilidad. |
| SelecciÃ³n de perÃ­odo/timeframe | `models.py:23`; `policy.py:13`; `context.py:79`; `registry.py:38-40,67-97`; `fake.py:101-104` | objetivo y tool schema | `1W/1M/3M/6M/1Y` | `LLM_WITH_GUARDRAIL`; default `CONFIGURATION`/polÃ­tica | SÃ­ en provider real | SÃ³lo valida enum/precondiciones; no fuerza `6M` | `test_contracts.py:29-37`; evaluator `evaluation_technical_v1.py:181-202` | `6M` es default recomendado, no autoridad efectiva universal. |
| ObtenciÃ³n de datos | `market_tracker.py:366-464` | ticker, rango, polÃ­tica quote | payload histÃ³rico + quote opcional | `DATA_SOURCE` + `CONFIGURATION` | SÃ³lo elige invocar y argumentos | SÃ­; identidad/rango/mercado, HTTP y contratos son validados | `test_market_enrichment.py`; `test_market_history_partial.py` | Valores provienen del proveedor; Python no inventa precios. |
| NormalizaciÃ³n de datos | `market_tracker.py:37-121,132-185`; `models.py:106-211` | JSON externo | `MarketHistory`, `Bar`, `QuoteSnapshot` | `DETERMINISTIC_PYTHON` | No | SÃ­; descarta filas OHLC invÃ¡lidas, rechaza identidad, monedas mixtas, duplicados y timestamps invÃ¡lidos | `test_market_enrichment.py:82-203,239-294`; `test_contracts.py:50-63` | Capa factual y reproducible. |
| Provisionalidad/enriquecimiento | `market_tracker.py:401-464`; `config.py:9-13` | histÃ³rico y quote mÃ¡s nueva | `appended`, `excluded`, `not_newer`, etc. | `CONFIGURATION` + `HARDCODED_DOMAIN_RULE` | No | N/A | `test_market_enrichment.py:82-214`; `test_technical_v4.py:166-213` | Una quote es siempre provisional; la polÃ­tica define si entra en indicadores. |
| Frescura | `technical_assessment.py:42-53,123-163`; `policy.py:8-11`; `config.py:33` | fechas, clocks, `stale`, feriados configurados | `RECENT/STALE/INVALID/UNKNOWN` | `HARDCODED_DOMAIN_RULE` + `CONFIGURATION` | No | N/A | `test_technical_assessment.py:125-219` | Tolerancia configurable de 7 dÃ­as; reloj remoto con margen fijo de 2 s. |
| Suficiencia | `technical_assessment.py:17-27,164-205,367-369` | barras, mÃ©tricas, filas descartadas | `COMPLETE/PARTIAL/INSUFFICIENT_DATA/...` | `HARDCODED_DOMAIN_RULE` | No | SÃ­; un terminal LLM incompatible puede degradarse o reemplazarse | `test_technical_assessment.py:36-64,222-236`; dataset `minimum`, `short`, `missing_sma50` | Reglas de ventanas, mÃ­nimo y calidad son canÃ³nicas. |
| CÃ¡lculo de indicadores | `technical.py:8-80` | OHLCV normalizado | `TechnicalMetrics` | `DETERMINISTIC_PYTHON` | SÃ³lo propone ejecutar tool | No puede modificar el resultado persistente; recibe deep copy | `test_technical.py`; `test_technical_v1_reference.py`; oracle `evaluation_reference.py` | FÃ³rmulas puras verificadas contra oracle independiente. |
| SeÃ±ales derivadas atÃ³micas | `technical_assessment.py:212-255,319-328` | mÃ©tricas disponibles | `TechnicalSignal` por comparaciÃ³n | `HARDCODED_DOMAIN_RULE` | No | No | `test_technical_assessment.py:67-103`; `test_technical_v1_real_snapshots.py` | Thresholds y comparaciones explÃ­citas. |
| Tendencia | `technical_assessment.py:56-62,256-261` | precio/SMA, SMA/SMA, EMA/EMA | `trend` | `HARDCODED_DOMAIN_RULE` | No | No | `test_technical_v4.py:95-118`; snapshots reales | Cualquier oposiciÃ³n produce `MIXED`; no usa mayorÃ­a. |
| Momentum legado | `technical_assessment.py:262-264` | RSI, MACD/seÃ±al, MACD/cero | `momentum` | `HARDCODED_DOMAIN_RULE` | No | No | `test_technical_assessment.py:67-86`; `test_technical_v1_regressions.py:47-56` | Campo compatible que agrega tres polaridades. |
| `momentum_state` | `technical_assessment.py:265-280` | baseline, territorio, relaciÃ³n y histogramas | estado enriquecido | `HARDCODED_DOMAIN_RULE` | No | No | `test_technical_v4.py:50-110` | Distingue territorio de mejora relativa y contracciÃ³n del histograma. |
| InterpretaciÃ³n RSI | `technical_assessment.py:234-245` | RSI14 | sesgo + zona + explicaciÃ³n | `HARDCODED_DOMAIN_RULE` | No | No | `test_technical_assessment.py:89-103`; `test_technical_v4.py:50-60` | 50 define sesgo; 30/70 zona, sin inferir reversiÃ³n. |
| InterpretaciÃ³n MACD | `technical_assessment.py:246-255,265-280` | MACD, seÃ±al, cero, histogramas | seÃ±ales y estado | `HARDCODED_DOMAIN_RULE` | No | No | `test_technical_v4.py:50-110`; `test_presenter.py:159-165` | Territorio, relaciÃ³n e histograma tienen roles distintos. |
| `confirmation` | `technical_assessment.py:294-304` | trend, baseline, relaciÃ³n, completitud, quote incluida | `ALIGNED/UNCONFIRMED/UNAVAILABLE` | `HARDCODED_DOMAIN_RULE` | No | No | `test_technical_v4.py:50-100`; `test_market_metadata.py:145-168`; snapshots reales | Es alineaciÃ³n estricta de precio/momentum, no predicciÃ³n ni volumen. |
| `volume_confirmation` | `technical_assessment.py:329-366` | Ãºltimas 21 barras histÃ³ricas con volumen | confirmaciÃ³n y fecha | `HARDCODED_DOMAIN_RULE` | No | No | `test_market_metadata.py:107-142`; `test_technical_v1_regressions.py:70-79` | Excluye quote provisional y compara la Ãºltima barra con promedio previo. |
| Conflictos/acuerdos | `technical_assessment.py:305-318` | seÃ±ales creadas hasta ese punto | listas de acuerdos/conflictos | `HARDCODED_DOMAIN_RULE` | No | No | `test_technical_assessment.py:75-86`; `test_technical_v4.py:113-118` | Expone coexistencia direccional; no decide por sÃ­ solo la conclusiÃ³n. |
| ConclusiÃ³n | `technical_assessment.py:281-293,367-369` | tendencia + baseline | `conclusion` | `HARDCODED_DOMAIN_RULE` | No | No | `test_technical_v4.py:50-118`; eval dataset bullish/bearish/neutral/mixed | Prevalece tendencia salvo discrepancia material con baseline. |
| Confianza | `technical_assessment.py:187-210` | completitud, quote, descartes, volumen | `HIGH/MEDIUM/UNAVAILABLE` | `HARDCODED_DOMAIN_RULE` | No; el `AgentDecision.confidence` es distinto | No | `test_technical_assessment.py:233-236`; snapshots reales | Calidad de evidencia, no probabilidad. `LOW` no se alcanza hoy. |
| AcciÃ³n terminal propuesta | `models.py:348-364`; `context.py:69-92` | estado proyectado | `CLARIFY/FINAL_ANSWER/ABSTAIN` | `LLM` | SÃ­ | Parcialmente | tests de providers y robustez | El modelo propone una acciÃ³n operativa tipada. |
| AcciÃ³n terminal efectiva | `decisions.py:31-54`; `equity_agent.py:188-224,444-480`; `report.py:87-93,219-255` | acciÃ³n propuesta + evidencia | estado `ANSWER/.../ERROR` | `LLM_WITH_GUARDRAIL` | SÃ­, como propuesta | SÃ­: override de `ABSTAIN`, fallos tÃ©cnicos a `ERROR`, evidencia insuficiente a `ABSTAIN` | `test_terminal_authority.py:64-196`; `test_technical_contract.py:77-90` | Python conserva invariantes; `CLARIFY` aÃºn puede sobrevivir con evidencia publicable. |
| SelecciÃ³n/generaciÃ³n de explicaciÃ³n financiera | `technical_assessment.py:372-410`; `report.py:168-176` | assessment canÃ³nico | summary + interpretation | `DETERMINISTIC_PYTHON` | No en el texto publicado | SÃ­; descarta prosa financiera del LLM | `test_technical_contract.py:20-68`; evaluator `evaluation_technical_v1.py:281-293` | Narrativa se reconstruye exactamente desde seÃ±ales. |
| Limitaciones y evidencia | `report.py:96-170,177-226` | history/assessment/metodologÃ­a | `Dimension`, evidence, missing info | `DETERMINISTIC_PYTHON` + `DATA_SOURCE` | SÃ³lo pudo proponer metodologÃ­a/tool | SÃ­ | `test_market_enrichment.py:214-236`; `test_prompt_versions.py` | Distingue dato, metodologÃ­a y limitaciÃ³n factual. |
| `FinalAnalysis` | `models.py:473-490`; `report.py:285-307` | estado y dimensiones | contrato final tipado | `DETERMINISTIC_PYTHON` | No produce el objeto | SÃ­; Pydantic y builder fijan campos | `test_contracts.py`; `test_technical_contract.py:40-74` | Es la autoridad API canÃ³nica. |
| Gate HITL opcional | `domain/actions.py:42-58,76-157`; `equity_agent.py:570-594` | pedido explÃ­cito + report answerable | `PAUSED`, snapshot, pending action | `DETERMINISTIC_PYTHON` + `HUMAN_AUTHORITY` | No autoriza el gate | SÃ­; sÃ³lo ediciÃ³n permitida y aprobaciÃ³n humana | `test_hitl_domain.py`; `test_hitl.py` | La autorizaciÃ³n se deriva del usuario, nunca del LLM. |
| `/agent/run` | `api/app.py:134-136` | request validado | `FinalAnalysis` | `DETERMINISTIC_PYTHON` | Usa al agente internamente | Schema de respuesta | `test_api_storage.py`; `test_technical_contract.py` | Expone el contrato crudo sin reinterpretarlo. |
| Presenter `/chat` | `presenter.py:95-367`; `api/app.py:138-170` | `FinalAnalysis` | `ChatResponse` | `DETERMINISTIC_PRESENTER` | No | No debe cambiar dominio | `test_presenter.py`; `test_web_ui.py`; `test_market_metadata.py:145-168` | Traduce, formatea, filtra URLs y consolida warnings. |

## 4. DiagnÃ³stico especÃ­fico de `confirmation`

La definiciÃ³n vigente es exacta y conjuntiva:

```text
ALIGNED si y sÃ³lo si:
  trend âˆˆ {BULLISH, BEARISH, NEUTRAL}
  AND baseline == trend
  AND macd_signal_relation âˆˆ {trend, NEUTRAL}
  AND assessment.status == COMPLETE
  AND quote provisional no fue incorporada a indicadores
de lo contrario: UNCONFIRMED
```

Donde `baseline = combine(RSI14, MACD/cero)`. La relaciÃ³n MACD/seÃ±al no vota la conclusiÃ³n, pero sÃ­ puede impedir confirmaciÃ³n. El histograma no participa en `confirmation`; sÃ³lo refina `momentum_state`. El volumen tampoco participa: tiene el campo separado `volume_confirmation`.

Conclusiones del diagnÃ³stico:

- La autoridad es 100 % Python y reproducible (`technical_assessment.py:294-304`).
- `ALIGNED` exige `COMPLETE`; un resultado `PARTIAL` publicable siempre es `UNCONFIRMED`.
- Incorporar una quote provisional fuerza `UNCONFIRMED`, incluso con todas las seÃ±ales alineadas. Con polÃ­tica `history_only`, la quote queda fuera y no bloquea por esa condiciÃ³n.
- Una tendencia internamente contradictoria es `MIXED` y no puede ser `ALIGNED`.
- MACD negativo pero sobre seÃ±al es mejora relativa, no confirmaciÃ³n de reversiÃ³n: la relaciÃ³n opuesta al trend impide `ALIGNED`.
- El nombre `confirmation` puede inducir a leer â€œconfirmaciÃ³n predictivaâ€ o â€œconfirmaciÃ³n por volumenâ€. El contrato y la narrativa aclaran que significa alineaciÃ³n conjunta, y el volumen estÃ¡ separado. Para V1 conviene mantener la semÃ¡ntica y documentar el label, no delegarla al LLM.
- No existe un threshold probabilÃ­stico oculto. Es una conjunciÃ³n de estados categÃ³ricos ya calculados.

Riesgo residual: la condiciÃ³n estÃ¡ embebida en `assess` y sus invariantes se prueban por ejemplos, no mediante una matriz exhaustiva de todas las combinaciones de `trend Ã— baseline Ã— relative Ã— status Ã— provisional`. Un test de tabla exhaustiva aumentarÃ­a trazabilidad sin cambiar autoridad.

## 5. Inventario de fÃ³rmulas, thresholds y reglas hardcodeadas

### 5.1 CÃ¡lculo matemÃ¡tico

| Regla exacta | UbicaciÃ³n | ClasificaciÃ³n | RazÃ³n aparente / origen | Tests que la fijan | Si cambiara |
|---|---|---|---|---|---|
| SMA = media de las Ãºltimas `period` observaciones; `None` si no alcanza | `technical.py:8-11` | `FORMULA_ESTABLE` | ConvenciÃ³n matemÃ¡tica estÃ¡ndar | `test_technical.py:9-12`; oracle `evaluation_reference.py:49-50` | CambiarÃ­an mÃ©tricas, seÃ±ales, snapshots y evals. |
| EMA inicial = SMA de las primeras `period`; `alpha=2/(period+1)`; recursiÃ³n estÃ¡ndar | `technical.py:14-28` | `FORMULA_ESTABLE` con convenciÃ³n de seed | ConvenciÃ³n tÃ©cnica explÃ­cita | `test_technical.py:14-17`; oracle `evaluation_reference.py:27-40` | CambiarÃ­a toda la serie EMA/MACD; requiere versionado. |
| RSI Wilder 14: seed de 14 cambios, smoothing `(prev*13+nuevo)/14`; sin pÃ©rdidas => 100, sin movimiento => 50 | `technical.py:31-44` | `FORMULA_ESTABLE` + edge policy | ConvenciÃ³n tÃ©cnica estÃ¡ndar | `test_technical.py:19-46`; oracle `evaluation_reference.py:41-46` | CambiarÃ­a RSI, zonas, momentum y conclusiÃ³n. |
| MACD = EMA12âˆ’EMA26; alineaciÃ³n `fast[14:]` con slow; seÃ±al EMA9 de la lÃ­nea | `technical.py:47-50` | `FORMULA_ESTABLE` | Identidad MACD 12/26/9 y alineaciÃ³n temporal | `test_technical.py:48-53`; `test_technical_v1_reference.py`; oracle | CambiarÃ­a identidad, warmup y todos los estados MACD. |
| Histograma = MACDâˆ’signal; previous histogram se recalcula excluyendo Ãºltima barra | `technical.py:57-65` | `FORMULA_ESTABLE` | Identidad y comparaciÃ³n temporal reproducible | `test_technical.py:110-132`; snapshots reales | CambiarÃ­a `momentum_state` fading y explicaciones. |
| VariaciÃ³n = `(Ãºltimo/primeroâˆ’1)*100`; high/low de muestra | `technical.py:74-76` | `FORMULA_ESTABLE` | Resumen descriptivo | `test_technical.py:55-63`; oracle | SÃ³lo contexto/presentaciÃ³n salvo conflictos explicativos. |
| Average volume = media de toda la muestra sÃ³lo si todos los volÃºmenes son conocidos | `technical.py:77-80` | `REGLA_DOMINIO` | No imputar desconocidos | `test_technical.py:55-63,99-107`; `test_market_enrichment.py:176-182` | CambiarÃ­a warnings/confianza, no `volume_confirmation` local. |

### 5.2 Ventanas y suficiencia

| Regla exacta | UbicaciÃ³n | ClasificaciÃ³n | RazÃ³n / origen | Tests | Si cambiara |
|---|---|---|---|---|---|
| SMA20=20, SMA50=50, EMA12=12, EMA26=26 | `technical.py:67-70`; `technical_assessment.py:17-26` | `THRESHOLD_TECNICO`; duplicado producciÃ³n | Convenciones elegidas de V1 | `test_technical_v1_reference.py:10-54`; sample boundaries | MÃ©tricas disponibles y `COMPLETE/PARTIAL`. |
| RSI14 requiere 15 precios | `technical.py:31-35`; `technical_assessment.py:22` | `THRESHOLD_TECNICO` | 14 cambios requieren 15 observaciones | `test_technical_assessment.py:36-56` | Mueve frontera de respuesta publicable. |
| MACD requiere 26; seÃ±al/histograma 34 | `technical.py:47-50`; `technical_assessment.py:23-25` | `THRESHOLD_TECNICO` | 26 para lÃ­nea, 9 puntos de lÃ­nea para seÃ±al: 26+8=34 | boundary/reference tests | Cambia disponibilidad y PARTIAL. |
| MÃ­nimo global = 15 barras y precio actual | `technical_assessment.py:27,178-182` | `REGLA_DOMINIO` | Permite RSI aunque falten medias largas/MACD signal | `test_technical_assessment.py:36-56`; dataset `minimum/short` | 14â†”15 cambia `ABSTAIN` a `ANSWER/PARTIAL`. |
| `COMPLETE` si no faltan indicadores requeridos ni filas descartadas; `PARTIAL` en otro caso | `technical_assessment.py:171-198` | `REGLA_DOMINIO` | Contrato de calidad V1 | tests de boundaries y filas descartadas | Impacta confianza, confirmation, terminal y HITL. |
| Volumen es opcional para completitud de precio | `technical_assessment.py:204-208` | `REGLA_DOMINIO` | SeparaciÃ³n de price analysis y volumen | `test_technical_assessment.py:59-64`; `test_technical_v4.py:135-156` | Si se hiciera obligatorio degradarÃ­a casos vÃ¡lidos. |

### 5.3 Comparaciones e interpretaciÃ³n

| Regla exacta | UbicaciÃ³n | ClasificaciÃ³n | RazÃ³n / origen | Tests | Si cambiara |
|---|---|---|---|---|---|
| Igualdad: `isclose(rel_tol=1e-9, abs_tol=1e-10)`; mayor=alcista, menor=bajista | `technical_assessment.py:215-228` | `THRESHOLD_TECNICO` numÃ©rico | Evitar ruido de floating point | flat/neutral eval y unit tests | Mueve casos cercanos entre neutral/direccional. |
| Precio vs SMA20/SMA50; SMA20 vs SMA50; EMA12 vs EMA26 | `technical_assessment.py:230-233` | `REGLA_DOMINIO` basada en convenciÃ³n | SeÃ±ales de estructura/tendencia | `test_technical_v4.py`; snapshots | Cambia tendencia/conclusiÃ³n. |
| RSI >50 alcista, <50 bajista, =50 neutral | `technical_assessment.py:240` | `THRESHOLD_TECNICO` | LÃ­nea central estÃ¡ndar | `test_technical_assessment.py:89-103` | Cambia baseline/momentum/conclusiÃ³n. |
| RSI >=70 sobrecompra; <=30 sobreventa; no implica reversiÃ³n | `technical_assessment.py:241-245` | `THRESHOLD_TECNICO` + seguridad semÃ¡ntica | ConvenciÃ³n tÃ©cnica estÃ¡ndar | RSI zone tests | Cambia sÃ³lo zona textual salvo que tambiÃ©n cambie sesgo 50. |
| MACD vs cero define territorio; MACD vs signal define mejora/debilitamiento | `technical_assessment.py:246-268` | `REGLA_DOMINIO` basada en convenciÃ³n | Evita tratar mejora relativa como reversiÃ³n | `test_technical_v4.py:50-110` | Cambia momentum_state/confirmation/conflictos. |
| Histograma actual < previous, con MACD bajo cero y sobre signal => `RECOVERY_FADING_BUT_BEARISH`; si no, `IMPROVING_BUT_BEARISH` | `technical_assessment.py:269-280` | `HEURISTICA_CONTEXTUAL` verificable | Una barra de contracciÃ³n refina fuerza relativa | `test_technical_v4.py:65-92` | Cambia estado/narrativa; no conclusiÃ³n base. |

### 5.4 AgregaciÃ³n, contradicciÃ³n y confirmaciÃ³n

| Regla exacta | UbicaciÃ³n | ClasificaciÃ³n | RazÃ³n / origen | Tests | Si cambiara |
|---|---|---|---|---|---|
| `combine`: elimina neutral/unavailable; oposiciÃ³n o MIXED => MIXED; una direcciÃ³n => esa; sÃ³lo neutrales => neutral | `technical_assessment.py:56-62` | `REGLA_DOMINIO` | No ocultar disenso por mayorÃ­a | direction/mixed tests | Impacta trend, momentum, baseline y conclusiÃ³n. |
| Trend combina cuatro relaciones con igual peso; una oposiciÃ³n basta para MIXED | `technical_assessment.py:256-261` | `REGLA_DOMINIO` | Conservador y explicable | `test_technical_v4.py:113-118` | Una mayorÃ­a podrÃ­a ocultar conflictos. |
| Momentum legado combina RSI, MACD/signal, MACD/cero | `technical_assessment.py:262-264` | `REGLA_DOMINIO` de compatibilidad | Mantiene consumidor previo | regression tests | Cambia campo legacy y algunas ramas neutrales. |
| Baseline de conclusiÃ³n combina sÃ³lo RSI y MACD/cero | `technical_assessment.py:265-266` | `REGLA_DOMINIO` | Separa territorio de cambio relativo | `test_technical_v4.py` | Evita que MACD/signal duplique/vote reversiÃ³n. |
| ConclusiÃ³n: trend; si falta, baseline; si baseline mixed/opuesto, MIXED; trend neutral + momentum mixed => MIXED | `technical_assessment.py:281-293` | `REGLA_DOMINIO` | Precedencia de tendencia con veto por contradicciÃ³n material | V4 + eval dataset | Cambia clasificaciÃ³n contractual. |
| `confirmation` usa la conjunciÃ³n documentada en secciÃ³n 4 | `technical_assessment.py:294-304` | `REGLA_DOMINIO`/autoridad | AlineaciÃ³n estricta | V4, metadata, snapshots | Cambia significado pÃºblico de â€œalineadoâ€. |
| Acuerdo: mÃ¡s de una seÃ±al con misma direcciÃ³n; conflicto: existe al menos una alcista y una bajista | `technical_assessment.py:305-318` | `REGLA_DOMINIO` | Explicabilidad factual | contradiction tests | Cambia lista explicativa, no necesariamente conclusiÃ³n. |
| `period_change` y volumen se agregan despuÃ©s de calcular conflictos | `technical_assessment.py:305-328` | `CONSTANTE_ACCIDENTAL_DUPLICADA`/acoplamiento por orden | Evitar que contexto/volumen voten conflicto, pero estÃ¡ implÃ­cito | `test_technical_v4.py:62` sÃ³lo fija que no es voto | Reordenar cÃ³digo alterarÃ­a conflicts sin cambiar reglas declaradas. Conviene hacer explÃ­cito el set. |

### 5.5 Volumen

| Regla exacta | UbicaciÃ³n | ClasificaciÃ³n | RazÃ³n / origen | Tests | Si cambiara |
|---|---|---|---|---|---|
| Se usan 21 barras histÃ³ricas; si quote fue appended, se excluye | `technical_assessment.py:329-332` | `REGLA_DOMINIO` + provisionalidad factual | Comparar barras completas equivalentes | `test_market_metadata.py:137-142` | PodrÃ­a comparar intradÃ­a con cierre y generar falso confirmado. |
| Baseline = promedio de 20 barras anteriores; requiere todas conocidas | `technical_assessment.py:332-336` | `THRESHOLD_TECNICO` | Ventana local explÃ­cita | metadata/regression tests | Cambia disponibilidad y sensibilidad. |
| Confirmado sÃ³lo si `latest_volume > baseline_volume > 0` y Ãºltimo close cambia; direcciÃ³n sigue el precio | `technical_assessment.py:337-347` | `REGLA_DOMINIO` | Volumen superior acompaÃ±a movimiento, no forecast | `test_market_metadata.py:107-134` | `>=`, multiplicadores o percentiles cambiarÃ­an casos frontera. |
| Volumen igual/menor => NOT_CONFIRMED; faltantes => UNAVAILABLE | `technical_assessment.py:334-366` | `REGLA_DOMINIO` | Distingue ausencia de falta de confirmaciÃ³n | mismos tests | Afecta API/presenter, no conclusiÃ³n. |

### 5.6 Confianza, frescura, provisionalidad y terminal

| Regla exacta | UbicaciÃ³n | ClasificaciÃ³n | RazÃ³n / origen | Tests | Si cambiara |
|---|---|---|---|---|---|
| HIGH si COMPLETE; MEDIUM si PARTIAL; quote, descartes o average volume ausente fuerzan MEDIUM; no hay LOW | `technical_assessment.py:199-208` | `REGLA_DOMINIO` | Calidad de evidencia | quality/snapshot tests | Cambia etiqueta pÃºblica, no seÃ±ales. |
| Stale si flag proveedor o fecha anterior a Ãºltima sesiÃ³n posible y edad calendario > grace; default 7 | `technical_assessment.py:42-53,149-159`; `config.py:33` | `CONFIGURATION` + `REGLA_DOMINIO` | Conservador sin inventar calendario bursÃ¡til | freshness tests | Cambia publicabilidad. |
| Reloj remoto puede adelantar como mÃ¡ximo 2 s | `policy.py:8-11`; `technical_assessment.py:133-147` | `POLITICA_AUTORIDAD_SEGURIDAD` | Margen observado 1.112547 s | skew tests | MÃ¡s bajo rechaza payloads vÃ¡lidos; mÃ¡s alto acepta mayor incoherencia. |
| Quote siempre provisional; nunca rejuvenece histÃ³rico stale | `models.py:122-147`; `market_tracker.py:403-415`; assessment | `POLITICA_AUTORIDAD_SEGURIDAD` | No afirmar cierre | enrichment/freshness tests | Riesgo de presentar intradÃ­a como cierre. |
| `COMPLETE/PARTIAL` son answerable | `technical_assessment.py:37-39` | `POLITICA_AUTORIDAD` | Publicar evidencia disponible | terminal authority tests | Cambia override, fallback y HITL. |
| ABSTAIN answerable tÃ©cnico ordinario => FINAL_ANSWER; excepciones full/metodologÃ­a | `decisions.py:31-54` | `POLITICA_AUTORIDAD_SEGURIDAD` | El LLM no invalida evidencia canÃ³nica | `test_terminal_authority.py` | DevolverÃ­a variabilidad terminal para inputs idÃ©nticos. |
| Source/calculation failure no recuperado => ERROR, no ABSTAIN | `report.py:227-283` | `POLITICA_AUTORIDAD_SEGURIDAD` | No confundir falla tÃ©cnica con insuficiencia financiera | integration contract tests | Cambia semÃ¡ntica operativa y observabilidad. |
| Review request + ANSWER tÃ©cnico answerable => PAUSED/HITL | `actions.py:42-58`; `equity_agent.py:570-594` | `POLITICA_AUTORIDAD_SEGURIDAD` | AutorizaciÃ³n humana explÃ­cita | HITL tests | Impacta publicaciÃ³n, no assessment. |

### 5.7 Mappings de presentaciÃ³n

Los mappings de `presenter.py:15-92,224-243` son `MAPPING_PRESENTACION`: labels de seÃ±ales, confianza, momentum state, confirmation, volume confirmation, mÃ©tricas, status warnings y resumen MACD. `_format_number` (`106-120`) es formato espaÃ±ol. No son defectos por estar hardcodeados.

Hay dos duplicaciones frÃ¡giles:

- `_rsi_summary` (`202-221`) vuelve a descubrir la zona buscando â€œsobrecompraâ€, â€œsobreventaâ€ y â€œzona neutralâ€ dentro de prosa determinÃ­stica. Si cambia la redacciÃ³n de dominio, puede cambiar la UI aunque el cÃ³digo RSI no cambie.
- `_presentation_warnings` (`176-199`) combina campos estructurados con bÃºsquedas de substrings en warnings/limitations. SÃ³lo afecta visualizaciÃ³n, pero duplica semÃ¡ntica factual.

## 6. Inventario real del LLM

### 6.1 Prompt y contexto

El prompt efectivo default es `technical-v3` (`context.py:5,66-94`; `config.py:27`). Declara expresamente:

- usuario como datos, no instrucciones de sistema;
- un solo `AgentDecision` por paso;
- propuesta de sÃ­mbolo/mercado, validada por la aplicaciÃ³n;
- universe de acciones domÃ©sticas BYMA;
- historia 6M como default recomendado;
- `COMPLETE/PARTIAL` permiten responder;
- Python posee todos los nÃºmeros, comparaciones, trend, momentum y confidence;
- prohibiciÃ³n de recalcular, sobreescribir, inventar cruces, soportes, resistencias o targets;
- `reason/interpretation` son texto operativo; la narrativa financiera sale de Python.

`build_agent_context` (`context.py:104-171`) entrega:

- objetivo truncado a 2000 caracteres y flag de truncado;
- activo resuelto completo;
- intent, paso y mÃ¡ximo de pasos;
- resumen del history: ticker, rango, mode, stale, sample size, as_of, provisionalidad, enrichment, descartes y conteo de volumen faltante;
- `technical_metrics` completo;
- `technical_assessment` completo, incluidas seÃ±ales, explicaciones, trend, momentum, states, confirmation, volume, conflicts, warnings y basis;
- metadatos acotados de documentos y metodologÃ­a;
- tools ejecutadas y argumentos truncados;
- observaciones operativas sanitizadas, errores y missing information;
- schemas de tools.

No recibe:

- la serie completa de barras OHLCV;
- payloads JSON crudos del proveedor;
- cuerpos de error externos;
- secretos/API keys;
- objetos HTTP;
- texto completo de documentos financieros;
- una memoria libre fuera de la proyecciÃ³n;
- autoridad para escribir directamente `FinalAnalysis`.

### 6.2 Structured output y pipeline

El Ãºnico output permitido es `AgentDecision` (`models.py:348-364`):

```text
action: CALL_TOOL | CLARIFY | FINAL_ANSWER | ABSTAIN
tool_name?: string
tool_args: object
reason: string
missing_information: string[]
confidence: number [0,1]
intent?: UserIntent
interpretation: string
```

El adapter aÃ±ade el JSON Schema al system prompt y, segÃºn configuraciÃ³n, solicita `json_object` o `json_schema` al proveedor (`http_provider.py:95-144`; `compatible.py:8-26`; `gemini.py:28-50`). DespuÃ©s aplica:

1. lÃ­mite de 32.000 caracteres;
2. Pydantic/extra forbid/tipos/enums;
3. reason <=400, interpretation <=800, hasta 10 missing items;
4. `validate_decision` de negocio;
5. `ToolRegistry.validate/prepare` para args, intent, activo, precondiciones y duplicados;
6. repair acotado; mÃ¡ximo configurable 0..2 retries;
7. fallback de modelo sÃ³lo para fallos operativos permitidos, nunca para output invÃ¡lido;
8. fallback determinÃ­stico del agente sÃ³lo si ya existe assessment tÃ©cnico answerable y el fallo LLM es recuperable.

### 6.3 Campo por campo: propuesta y valor publicado

| Campo LLM | Python acepta/rechaza/normaliza | Efecto finalmente publicado |
|---|---|---|
| `action=CALL_TOOL` | Acepta sÃ³lo schema, tool conocida, rama vÃ¡lida, args vÃ¡lidos, precondiciones y retry budget | Ejecuta la tool; no acepta datos inventados dentro de `technical_metrics`. |
| `action=ABSTAIN` | Puede reemplazarlo por `FINAL_ANSWER` con assessment answerable; report repite la defensa | `ANSWER` determinÃ­stico en el caso protegido; `ABSTAIN` si realmente no answerable o hay excepciÃ³n explÃ­cita. |
| `action=FINAL_ANSWER` | Requiere activo resuelto; report lo degrada por insuficiencia/metodologÃ­a/full o lo cambia a ERROR por fallo tÃ©cnico | `ANSWER` sÃ³lo si las invariantes determinÃ­sticas lo permiten. |
| `action=CLARIFY` | Schema/shape; no existe override simÃ©trico por assessment answerable | Puede quedar `CLARIFY`; es autoridad LLM residual. |
| `tool_name` | Debe existir y estar dentro de intent | SÃ³lo se ejecuta la tool validada. |
| `tool_args.symbol/market` | Se normalizan/validan; proveedor/catÃ¡logo posee identidad | La resoluciÃ³n publicada puede rechazar o reemplazar la propuesta. |
| `tool_args.range` | SÃ³lo enum y precondiciones | El rango propuesto vÃ¡lido se usa; Python no fuerza default. |
| `intent` | ExplÃ­cito se precarga; tras tools queda bloqueado; guards impiden branch cruzada | Determina ramas operativas, no categorÃ­as tÃ©cnicas. |
| `reason` | En provider validado se reemplaza por mensajes operativos canÃ³nicos; en answer tÃ©cnico la narrative reemplaza summary | No puede publicar claims financieros del modelo. |
| `interpretation` | Se vacÃ­a para provider validado y se reemplaza por `narrative()` cuando hay evidencia | No controla interpretaciÃ³n financiera final. |
| `missing_information` | En provider validado se reduce a mensaje genÃ©rico y se ignora si hubo override; report agrega faltantes factuales | No puede inventar una ausencia para degradar el caso protegido. |
| `confidence` numÃ©rica | SÃ³lo schema; se registra en trace | No alimenta `assessment.confidence`, que calcula Python. |

### 6.4 Guardrails y casos de reemplazo

- Deep copy al proveedor: mutaciones del objeto visto por el LLM no tocan estado (`equity_agent.py:155-175`; test adversarial de contrato).
- Prosa financiera adversarial desaparece del `FinalAnalysis` (`test_technical_contract.py:20-68`).
- Tool duplicada exitosa se rechaza; fallo sÃ³lo se reintenta si es retryable y dentro de dos intentos (`tools/operations.py`).
- Intent y metodologÃ­a fuera de rama se rechazan (`registry.py:67-92`).
- Fuente externa fallida se publica como `ERROR`, no como ausencia de evidencia.
- Output invÃ¡lido consume repair budget y termina en error; no se convierte silenciosamente en respuesta.
- `ABSTAIN` con evidence answerable se overridea y se traza como `TERMINAL_ACTION_OVERRIDDEN`.
- Fallback determinÃ­stico no aplica a pedidos Murphy/Graham explÃ­citos, ni antes de tener evidence, ni a output estructurado invÃ¡lido (`equity_agent.py:522-535`).

## 7. Decisiones por grado de determinismo

### 100 % determinÃ­sticas

- validaciÃ³n y normalizaciÃ³n de barras/timestamps;
- SMA, EMA, RSI, MACD, seÃ±al, histogramas y mÃ©tricas de muestra;
- suficiencia, status y freshness;
- seÃ±ales atÃ³micas y zonas RSI;
- trend, momentum, momentum_state;
- conclusion, confirmation, volume_confirmation;
- confidence del assessment;
- conflicts/agreements;
- narrativa financiera canÃ³nica;
- `FinalAnalysis`, labels/formato y `ChatResponse`;
- gate HITL y snapshot/integridad.

### HÃ­bridas

- intenciÃ³n genÃ©rica: LLM propone, Python bloquea ramas y contratos;
- activo: LLM propone semÃ¡ntica, Python/fuente valida identidad y alcance;
- rango: LLM elige dentro del enum; Python valida;
- orden/selecciÃ³n de tools: LLM propone; Python valida precondiciones, duplicados y retries;
- acciÃ³n terminal: LLM propone; Python corrige varias invariantes;
- fallback: un fallo del LLM puede terminar en respuesta determinÃ­stica sÃ³lo con evidence preexistente y condiciones acotadas.

### Autoridad duplicada o acoplada

| Punto | Naturaleza | EvaluaciÃ³n |
|---|---|---|
| Override `ABSTAIN` en `decisions.py` y nuevamente en `report.py` | Defensa en profundidad deliberada | Mantener, pero centralizar el predicado y probar ambas capas. |
| Answerable como `is_answerable` y tuplas `("COMPLETE","PARTIAL")` en `equity_agent.py`, `actions.py` | DuplicaciÃ³n accidental | Riesgo de drift de fallback/HITL/terminal. |
| PerÃ­odos en cÃ¡lculo y `WINDOWS` | DuplicaciÃ³n de especificaciÃ³n | Puede derivar disponibilidad respecto del cÃ¡lculo. |
| 6M en policy, prompt, fake y evaluator | Default distribuido | El real provider puede elegir otro rango; documentar autoridad efectiva. |
| RSI domain explanation y parsing por presenter | SemÃ¡ntica duplicada por texto | FrÃ¡gil ante cambios editoriales. |
| Warnings estructurados y bÃºsqueda de frases | SemÃ¡ntica duplicada por texto | SÃ³lo UI, pero difÃ­cil de auditar. |
| Set de conflictos determinado por orden de inserciÃ³n | Acoplamiento implÃ­cito | Hacer explÃ­citos los keys si se modifica en el futuro. |
| `momentum` legado vs baseline/momentum_state | Dualidad deliberada de compatibilidad | No eliminar sin migrar contrato; documentar cuÃ¡l decide conclusion. |

## 8. EvaluaciÃ³n Aâ€“J y recomendaciÃ³n por Ã¡rea

La sÃ­ntesis de Aâ€“J usa: respuesta Ãºnica, reproducibilidad, contrato, tolerancia a variaciÃ³n, ambigÃ¼edad real, informaciÃ³n extra del LLM, verificabilidad, daÃ±o por error, beneficio concreto y explicabilidad frente a variabilidad.

| Ãrea | Aâ€“D: unicidad/reproducibilidad/contrato | Eâ€“G: ambigÃ¼edad/info extra/verificaciÃ³n | Hâ€“J: error/beneficio/variabilidad | ClasificaciÃ³n |
|---|---|---|---|---|
| SMA/EMA/RSI/MACD, alineaciÃ³n e identidad | Ãšnica, exacta, contractual; variaciÃ³n inaceptable | Sin ambigÃ¼edad Ãºtil; verificable por oracle | Error contamina todo; LLM no aporta | `KEEP_DETERMINISTIC` |
| ValidaciÃ³n, timestamps, freshness factual, provisionalidad | Reproducible e invariante de evidencia | Contexto externo sÃ³lo sirve si es fuente verificable, no razonamiento libre | Error puede publicar datos invÃ¡lidos | `KEEP_DETERMINISTIC` |
| Suficiencia y COMPLETE/PARTIAL/INSUFFICIENT | Contractual y testeable | Puede discutirse la polÃ­tica, pero una vez elegida no debe variar por ejecuciÃ³n | Error cambia terminal y evaluaciÃ³n | `KEEP_DETERMINISTIC` |
| SeÃ±ales atÃ³micas price/SMA, SMA/SMA, EMA/EMA, MACD/cero/signal | Comparaciones Ãºnicas | Sin informaciÃ³n extra para el LLM | SÃ³lo agregarÃ­a variabilidad | `KEEP_DETERMINISTIC_ALLOW_LLM_EXPLANATION` |
| RSI zones | Threshold estÃ¡ndar y auditable | Contexto no cambia el valor de la zona | Error induce sobrecompra/sobreventa falsas | `KEEP_DETERMINISTIC_ALLOW_LLM_EXPLANATION` |
| `volume_confirmation` factual | Ãšnica dada la polÃ­tica | No ambigua | Falso confirmado es material | `KEEP_DETERMINISTIC` |
| Trend | PolÃ­tica explÃ­cita y parte de contrato V1 | Hay alternativas de agregaciÃ³n, pero no informaciÃ³n extra por input | LLM harÃ­a inestable la clasificaciÃ³n | `KEEP_DETERMINISTIC_ALLOW_LLM_EXPLANATION` |
| Momentum/momentum_state | Estados reproducibles; refine de histograma es heurÃ­stica explÃ­cita | Puede haber interpretaciones alternativas, verificables sÃ³lo contra referencia humana | Error semÃ¡ntico moderado; explicaciÃ³n sÃ­ puede mejorar | `KEEP_DETERMINISTIC_ALLOW_LLM_EXPLANATION` |
| DetecciÃ³n/explicaciÃ³n de contradicciones | Existencia de seÃ±ales opuestas es factual; materialidad puede ser contextual | LLM puede ordenar/reformular usando assessment completo | No debe borrar conflictos; puede mejorar legibilidad | `LLM_MAY_PROPOSE_PYTHON_VALIDATES` para Ã©nfasis, no para existencia |
| SelecciÃ³n de seÃ±ales materialmente relevantes | No hay Ãºnica selecciÃ³n editorial | El LLM sÃ­ posee objetivo del usuario y assessment | OmisiÃ³n puede sesgar; validable por cobertura obligatoria | `LLM_MAY_PROPOSE_PYTHON_VALIDATES` |
| `confirmation` | Regla V1 exacta, evaluable e invariante | AmbigÃ¼edad es nominal/editorial, no factual | Error cambia claim de alineaciÃ³n | `KEEP_DETERMINISTIC_ALLOW_LLM_EXPLANATION` |
| ConclusiÃ³n tÃ©cnica | Contractual, reproducible y evaluada | Existen otras metodologÃ­as posibles, pero el LLM no tiene datos extra ni referencia verificable en runtime | Error central y alta variabilidad | `INSUFFICIENT_EVIDENCE_TO_CHANGE` |
| Confidence | Definida como calidad factual, no probabilidad | LLM no dispone de evidencia adicional | ConfundirÃ­a certeza con calidad | `KEEP_DETERMINISTIC_ALLOW_LLM_EXPLANATION` |
| Narrativa final | Los hechos/categorÃ­as deben ser estables; la redacciÃ³n admite variedad | LLM puede mejorar fluidez y adaptaciÃ³n al objetivo | Riesgo de unsupported claims; salida sÃ­ es validable parcialmente | `LLM_MAY_PROPOSE_PYTHON_VALIDATES` sÃ³lo como propuesta editorial |
| ConfiguraciÃ³n mixta | Estado canÃ³nico estable, explicaciÃ³n contextual ambigua | Es el mejor uso potencial del contexto del usuario | Beneficio concreto en comprensiÃ³n; debe preservar conflictos/categorÃ­as | `LLM_MAY_PROPOSE_PYTHON_VALIDATES` |
| Provisionalidad | El hecho es Ãºnico | El LLM sÃ³lo puede explicarlo | Omitirlo es material | `KEEP_DETERMINISTIC_ALLOW_LLM_EXPLANATION` |
| IdentificaciÃ³n de limitaciones | Limitaciones factuales deben salir de estructura | El LLM puede priorizarlas por consulta | No puede inventar/eliminar; sÃ­ resumir | `LLM_MAY_PROPOSE_PYTHON_VALIDATES` |
| AcciÃ³n terminal con evidence tÃ©cnico | Invariante de producto; debe ser estable | LLM no tiene mejor evidencia que el assessment | ABSTAIN errÃ³neo ya demostrÃ³ daÃ±o | `KEEP_DETERMINISTIC` para elegibilidad; LLM puede proponer siguiente acciÃ³n antes de cierre |

No se recomienda hoy ningÃºn `CANDIDATE_FOR_LLM_AUTHORITY` pleno. Los candidatos razonables son de propuesta editorial con validaciÃ³n, no de autoridad final sobre categorÃ­as.

## 9. Alternativas hÃ­bridas evaluadas

| Arquitectura | Beneficio | Riesgo | Reproducibilidad/tests/eval | Trazabilidad/guardrails | RecomendaciÃ³n V1 |
|---|---|---|---|---|---|
| 1. Python calcula + Python clasifica + LLM explica | Personaliza redacciÃ³n sin tocar facts | Claims no soportados u omisiones | CategorÃ­as estables; narrativa requiere eval adicional | Citar field IDs, lista obligatoria de facts, fallback determinÃ­stico | Experimento viable; no necesario para cerrar V1 |
| 2. Python calcula + LLM propone interpretaciÃ³n + Python valida invariantes | Puede matizar mixed/provisional | Validar semÃ¡ntica libre es difÃ­cil | Requiere golden facts + mÃºltiples runs | Schema de claims, no texto libre; reject/fallback | SÃ³lo si la propuesta es estructurada |
| 3. Python seÃ±ales atÃ³micas + LLM sintetiza + Python valida salida | Mayor flexibilidad contextual | DuplicaciÃ³n de conclusion y variabilidad | Aumenta considerablemente la superficie de eval | Matriz de combinaciones permitidas y veto canÃ³nico | No para V1; no hay beneficio medido |
| 4. Python assessment canÃ³nico + LLM narrativa no autoritativa | Separa claramente autoridad y estilo | Usuario puede confundir narrativa con canon | FÃ¡cil A/B; facts permanecen testeables | Marcar origin, preservar narrativa canÃ³nica y fallback | Mejor candidato futuro |
| 5. LLM decide sÃ³lo cuando varios estados determinÃ­sticos son vÃ¡lidos | Ãštil para selecciÃ³n editorial/foco | Definir â€œvarios vÃ¡lidosâ€ puede esconder una nueva polÃ­tica | Debe precomputarse el conjunto permitido | Enum de opciones, rationale no autoritativo | Viable para foco/secciones, no para conclusiÃ³n V1 |

## 10. Experimento offline previo a cualquier migraciÃ³n

### HipÃ³tesis

El Ãºnico candidato prioritario es: assessment canÃ³nico inmutable + LLM propone (a) seÃ±ales materialmente relevantes y (b) explicaciÃ³n de configuraciÃ³n mixta/provisional, sin poder cambiar categorÃ­as, facts ni terminal.

### Control

Comportamiento V1 actual:

- `narrative()` determinÃ­stica;
- presenter determinÃ­stico;
- action terminal efectiva actual;
- mismas mÃ©tricas, assessment y datasets.

### Candidato

Una Ãºnica ejecuciÃ³n de generaciÃ³n ya existente, sin nueva llamada ni modelo, producirÃ­a en un entorno experimental un schema separado, por ejemplo:

```text
selected_signal_ids: enum[]
explanation_sentences: [{claim_type, signal_ids, text}]
limitations_selected: enum[]
```

Python debe rechazar IDs inexistentes, categorÃ­as diferentes, nÃºmeros no presentes, ausencia de conflictos obligatorios, lenguaje de compra/venta/targets y omisiÃ³n de provisionalidad material. En rechazo, usa narrativa V1 exacta. Este diseÃ±o es para el experimento, no para implementar en la tarea actual.

### Dataset

1. Los 33 casos de `evals/technical_v1_dataset.jsonl`.
2. Snapshots congelados GGAL y PAMP (`tests/fixtures/technical_v1`).
3. Casos unitarios de V4: recovery improving/fading, weakening bullish, trend mixed, RSI 30/50/70.
4. Casos de autoridad terminal `COMPLETE`, `PARTIAL`, `INSUFFICIENT`, explicit Murphy/full.
5. Adversariales nuevos:
   - valores exactamente iguales y apenas dentro/fuera de `isclose`;
   - RSI 29.999/30/30.001/49.999/50/50.001/69.999/70/70.001;
   - MACD/cero y MACD/signal en todas las combinaciones;
   - histograma creciendo, igual y contrayendo;
   - quote appended/excluded/not newer;
   - volumen 20/21 barras, null/0/igual/+epsilon;
   - conflictos numerosos y seÃ±ales duplicadas derivadas;
   - prompt injection en user objective y texto de fuentes;
   - provider output con nÃºmeros/targets inventados;
   - mismo input repetido al menos 20 veces por modelo/prompt.

### MÃ©tricas obligatorias

| MÃ©trica | CÃ¡lculo |
|---|---|
| Agreement con referencia | Exact match para IDs/categorÃ­as; cobertura de facts obligatorios; ranking contra anotaciÃ³n ciega cuando aplique |
| Estabilidad | proporciÃ³n de outputs estructurados idÃ©nticos y Jaccard de seÃ±ales seleccionadas en repeticiones |
| Violaciones de invariantes | tasa absoluta y por tipo; objetivo para campos canÃ³nicos: 0 |
| Contradicciones internas | claims opuestos a seÃ±al/categorÃ­a o entre frases |
| Sensibilidad al modelo | delta de mÃ©tricas entre modelos autorizados |
| Sensibilidad al prompt | delta entre versiones con cambios editoriales controlados |
| ABSTAIN/errores | tasa terminal y de output invÃ¡lido/fallback; no debe empeorar control |
| Calidad explicativa | rÃºbrica ciega: fidelidad, cobertura, claridad, concisiÃ³n; nunca sustituye exactitud |
| Latencia | p50/p95 end-to-end y tiempo de provider |
| Costo | tokens y costo por respuesta usando precios configurados |
| Reproducibilidad | snapshot de modelo/prompt/hash/context y capacidad de reproducir control exacto |

### Criterios de no migraciÃ³n

- cualquier cambio en mÃ©tricas/categorÃ­as/terminal canÃ³nicos;
- cualquier violaciÃ³n de invariantes no capturada automÃ¡ticamente;
- estabilidad insuficiente entre ejecuciones idÃ©nticas;
- mejora explicativa no estadÃ­sticamente/materialmente superior al control;
- latencia/costo sin beneficio medible;
- dependencia fuerte de un modelo o prompt particular;
- necesidad de evaluaciÃ³n subjetiva para decidir si una afirmaciÃ³n factual es vÃ¡lida.

Los tests determinÃ­sticos actuales permanecen; el experimento agrega evals y no reemplaza ninguno.

## 11. RecomendaciÃ³n arquitectÃ³nica para el cierre de V1

1. Mantener Python como autoridad Ãºnica sobre datos validados, fÃ³rmulas, signals, trend, momentum, momentum_state, confirmation, volume_confirmation, conflicts, conclusion, confidence, statuses, provisionalidad y narrativa factual canÃ³nica.
2. Mantener al LLM como orquestador acotado: intenciÃ³n contextual, propuesta de asset, selecciÃ³n de tools y rango dentro del contrato. La existencia/eligibilidad y toda salida financiera siguen en Python.
3. Formalizar como invariante de dominio la elegibilidad terminal basada en `is_answerable`; conservar la defensa doble, pero evitar tuplas duplicadas en fallback/HITL.
4. Decidir explÃ­citamente si `CLARIFY` con assessment answerable debe poder sobrevivir. Hoy puede; eso debe ser una decisiÃ³n de producto testeada, no un efecto lateral del modelo.
5. No migrar `confirmation`, conclusion ni confidence al LLM en V1. No hay informaciÃ³n adicional Ãºtil, la referencia es verificable y el costo del error es superior al beneficio.
6. Si se busca mÃ¡s riqueza, experimentar sÃ³lo con una capa editorial estructurada y no autoritativa sobre el assessment canÃ³nico, con fallback exacto a `narrative()`.
7. Reducir en una fase separada las duplicaciones de especificaciÃ³n y parsing textual del presenter. Eso mejora auditabilidad sin aumentar autoridad LLM.
8. AÃ±adir una matriz exhaustiva de `confirmation` y tests explÃ­citos del caso `CLARIFY` post-assessment antes del tag de cierre.

En sÃ­ntesis: la arquitectura V1 correcta es **Python calcula, clasifica y publica el canon; el LLM orquesta y, como mÃ¡ximo tras un experimento, propone una explicaciÃ³n editorial validada**. La correcciÃ³n de `ABSTAIN` confirma el principio: delegar autoridad terminal al modelo alteraba una invariante del dominio sin aportar nueva evidencia.
