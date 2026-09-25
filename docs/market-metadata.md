# Variante de precios y confirmación por volumen

`meta.resolvedVariant` se conserva como `MarketHistory.resolved_variant`,
`technical.assessment.basis.resolved_variant` y en la metadata de la evidencia
histórica. `/chat` lo expone en `technical_details.resolved_variant`.
Los campos son opcionales: snapshots anteriores siguen siendo válidos.
`ajustada` significa únicamente que el proveedor informa esa variante; no
certifica de forma independiente los ajustes ni la variante de la quote.
Otras variantes se muestran literalmente atribuidas al proveedor; sin metadata
se conserva la nota cautelosa anterior.

`technical.assessment.confirmation` conserva su contrato de alineación de
indicadores y no incorpora la provisionalidad de la última observación, que se
expone por separado en `basis` y como advertencia. El nuevo `volume_confirmation` distingue `CONFIRMED`,
`NOT_CONFIRMED` y `UNAVAILABLE`, y se proyecta con etiquetas en
`technical_details.volume_confirmation`. `volume_as_of` identifica la barra
histórica evaluada, que puede diferir de la fecha de los indicadores de precios.

La regla conserva el umbral existente: requiere 21 barras históricas con volumen
conocido. El volumen de la última debe ser estrictamente mayor que el promedio
de las 20 anteriores, ese promedio debe ser positivo y el cierre debe cambiar
respecto del cierre anterior. Si se cumple, el volumen acompaña el movimiento
alcista o bajista de esa última barra (`CONFIRMED`); si no, es `NOT_CONFIRMED`.
No confirma una predicción, reversión ni toda la tendencia. Cero es un valor
disponible; `null` es desconocido.

Antes, incorporar una quote deshabilitaba toda evaluación de volumen. Ahora se
evalúa el histórico previo, excluyendo la quote provisional. Si faltan 21 barras
históricas o alguna carece de volumen, el estado es `UNAVAILABLE`. El promedio
de volumen de la muestra completa sigue conservando su cálculo: puede ser nulo
aunque la ventana local histórica permita confirmar volumen.

Una quote sigue siendo provisional aun después de las 17:00, con `stale=false`
y `source=live`. No se incorporaron campos de finalidad ni heurísticas horarias.
Las fórmulas y los valores de los indicadores no cambian. `basis.range` conserva
el rango solicitado y permite mostrar «Variación 6M» únicamente cuando es `6M`.

La regresión `quote_new` del dataset técnico ahora espera una señal de volumen
`NEUTRAL`: su histórico tiene volumen constante, disponible pero sin confirmar.
La quote de ese caso continúa teniendo volumen desconocido y siendo provisional.
