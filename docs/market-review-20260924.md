# Revisión diagnóstica de metadata y volumen — 24/09/2026

## Propagación y corrección

El adapter conserva `resolved_variant` en el histórico. El volumen se calcula
en Python (no es un campo de confirmación suministrado por el proveedor).
El assessment y el reporte ya propagaban `volume_confirmation`, `volume_as_of`
y la variante hasta `/agent/run` y `/chat`. El fallo demostrado estaba en
`renderTechnicalDetails`: solo renderizaba la confirmación tradicional.

Se agrega una fila independiente con fecha. `CONFIRMED` se presenta como
«Confirma el movimiento de la última barra histórica». Se evita afirmar
«rueda cerrada», porque `history_closure` sigue siendo `UNVERIFIED`.
NOT_CONFIRMED y UNAVAILABLE conservan sus textos diferentes. Los snapshots
antiguos sin campo de volumen siguen renderizando sin esa fila.

La consulta pública real de GGAL produjo precio 6395, variante `ajustada`,
histórico hasta 23/09 y quote provisional de 24/09 a las 17:00:02 -03:00.
La evaluación del snapshot produce `volume_confirmation=CONFIRMED`,
`volume_as_of=2026-09-23`, `quote_provisional=true`.
Volumen último: 2.480.908; promedio de los 20 anteriores: 1.511.389,40.
Cierre último: 6445; anterior: 6640. Confirma ese movimiento bajista.

Las respuestas completas de ambos endpoints se guardaron en
`evals/results/market-review-20260924/{agent-run,chat}.json`.
Se usó el snapshot recién capturado de mercado real con orquestador Fake:
esto valida API y proyección, no constituye una nueva ejecución Gemini.
No hubo llamadas LLM nuevas. La nota de serie ajustada, Variación 6M y la
ausencia de warnings de volumen faltante permanecen correctas.

## Confirmación tradicional

La tendencia combina precio/SMA20, precio/SMA50, SMA20/SMA50 y EMA12/EMA26.
La base del momentum combina RSI14 (respecto de 50) y MACD respecto de cero.
El momentum relativo compara MACD con su señal.
`ALIGNED` exige simultáneamente:

- tendencia BULLISH, BEARISH o NEUTRAL;
- base del momentum igual a tendencia;
- momentum relativo igual a tendencia o NEUTRAL;
- assessment COMPLETE;
- quote provisional no incorporada en los indicadores.

En GGAL se cumplen las primeras cuatro condiciones; falla la última.
No es una discrepancia entre indicadores bajistas: la regla conservadora veta
ALIGNED al incorporar una quote. Se conserva la regla y se aclara el label:
«Sin confirmación conjunta: los indicadores incluyen una quote provisional».
La confirmación de volumen histórico no modifica ese estado.

## MACD: comparación reproducible

Comando de captura (solo mercado):
`python scripts/diagnose_macd_warmup.py evals/results/market-review-20260924 --live`

Para repetir sin red, ejecutar el mismo comando sin `--live`.
Se verificaron variante y cierres coincidentes en todo el tramo común.
Se usó la misma quote final para ambas ventanas; no se modificaron fórmulas.
EMA utiliza semilla SMA y recurrencia con alpha=2/(periodo+1).
La señal MACD aplica la misma EMA de 9 períodos a EMA12−EMA26.

| Ventana | Barras | EMA12 | EMA26 | MACD | Señal | Histograma |
|---|---:|---:|---:|---:|---:|---:|
| 6M + quote | 126 | 6701,475746 | 6877,374824 | -175,899077 | -141,123312 | -34,775766 |
| 1Y + misma quote | 247 | 6701,475746 | 6877,346080 | -175,870333 | -141,081041 | -34,789293 |
| TradingView informado por el usuario | — | — | — | -176,59 | -141,55 | -35,04 |

Delta agente menos TradingView: en 6M, +0,690923 / +0,426688 / +0,264234;
en 1Y, +0,719667 / +0,468959 / +0,250707 (MACD/señal/histograma).
**La hipótesis no se confirma:** MACD y señal se alejan ligeramente del valor
informado; el histograma se aproxima solo marginalmente.

Máximo cambio absoluto entre EMA12, EMA26, MACD, señal e histograma frente
a la referencia de 247 barras: 126 barras=0,042271; 150=0,010647;
175=0,002015; 200=0,000074; 225=0,000177.
En esta muestra, 175 barras bastan para diferencia menor que 0,01 y
200–225 para menor que 0,001. No es garantía universal ni convergencia
monótona. 1Y es una referencia finita, no el valor verdadero.
No se probó 2Y: el contrato del adapter admite como máximo 1Y.

Separar ventana visible y warm-up podría reducir sensibilidad a la semilla,
pero no resolvería esta discrepancia observada. Antes de cambiar producción
se necesitan los cierres exactos, fuente, variante, sesión y configuración
de TradingView; sus tres valores aproximados no permiten aislar otra causa.

## Latencia y reparación (solo lectura)

Traza existente: `00507165-a37f-4096-b960-eb6c1440e646`, terminada en ANSWER.
Cuatro decisiones: resolver activo, consultar histórico, calcular y finalizar.
La cuarta produjo `SCHEMA_VALIDATION`, etapa `decision_schema`, tipo
`json_invalid`, HTTP 200. El provider registró INVALID_OUTPUT y envió feedback
de reparación dentro de su presupuesto; retry_number=1 terminó VALID.
Son cuatro llamadas iniciales más una reparación: cinco, según diseño.

LLM: 1125,51 / 22883,58 / 1021,79 / 1394,13 / 1237,64 ms.
Mercado: 624,14 ms. Cálculo: 1,58 ms. La demora dominante pertenece al
tramo HTTP/provider del paso 2, no al cálculo ni al fetch de mercado.
La traza no distingue tiempo interno del modelo de red/cola del proveedor.
No se encontró un bug evidente en ese reintento y no se cambió orquestación.

## Validación

Tests de contrato verifican ambos endpoints, fecha, variante, provisionalidad
y coexistencia de confirmaciones. Tres tests de frontend ejecutan JavaScript
real con DOM simulado para cada estado de volumen. Dos tests diagnósticos
sintéticos verifican estabilización y rechazo de precios/variantes distintos.
Los fixtures sintéticos no se presentan como validación de TradingView.
