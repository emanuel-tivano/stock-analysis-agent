# Evaluación

Este directorio conserva sólo los artefactos necesarios para reproducir y auditar la evaluación del MVP.

## Archivos

- `real_llm_dataset_v4.jsonl`: dataset técnico usado por el evaluador real/Fake.
- `mvp_evaluation_summary.json`: resumen reproducible de la evaluación offline del MVP.

## Ejecutar offline

```powershell
.\.venv\Scripts\python.exe scripts/eval_real_llm.py --fake
```

El comando usa fixtures para las fuentes de datos y no requiere una API key.
Escribe el reporte completo en `evals/results/fake_baseline.json`. Para actualizar la evidencia
publicada, `mvp_evaluation_summary.json` conserva sin renombrar la metadata y las métricas de ese
reporte, y agrega la ruta y el SHA-256 del dataset evaluado.

## Ejecutar con un provider real

Configurar `.env`, habilitar explícitamente las llamadas y ejecutar:

```powershell
$env:RUN_LLM_TESTS = "1"
.\.venv\Scripts\python.exe scripts/eval_real_llm.py --runs 1
```

Los resultados nuevos se escriben en `evals/results/`, ignorado por Git. No se guardan API keys ni respuestas crudas del proveedor.
