# Evaluaciones iniciales

Ejecutar `python -m pytest tests/integration/test_evals.py -q -s`.
Dataset independiente, ejecutor offline con transporte HTTP fake y provider fake.
Los resultados miden comportamiento del simulador y contratos, **no calidad de un LLM real**.
Las siete tareas imprimen JSON con éxito, selección de tools, llamadas innecesarias,
pasos, latencia, errores y corrección de abstención. No se exige orden fijo.

En Fase 2 agregar evaluador con provider real y fuentes congeladas, evaluación humana de
fidelidad/citas, casos adversariales y umbrales de aceptación. `tool_selection_accuracy`
es precisión del conjunto de tools; el éxito exige además todas las esperadas.

Cada caso declara `expected_tools`, `forbidden_tools`, estados permitidos,
`expected_asset` (null para desconocidos) y dimensiones en `expected_abstention`.
Incluye falla HTTP simulada y Murphy DEMO. El reporte agregado imprime `cases`, `passed`,
`failed`, `tool_selection_accuracy`, `forbidden_tool_violations` y `average_steps`.
En el agregado, accuracy es la proporción de casos con todas las tools requeridas y ninguna
prohibida; por caso se conserva la precisión anterior. No son métricas de inteligencia.

`tests/integration/test_trace_baseline.py` fija cinco golden traces semánticas:
técnico GGAL, fundamentos PAMP, XXXX, Murphy DEMO y falla Market Tracker.
Compara secuencia de eventos y pasos sin fijar UUID, fechas ni latencias.
Ese orden caracteriza al fake actual, no impone un workflow al agente.
