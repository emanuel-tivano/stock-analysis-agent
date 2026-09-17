# Gemini nativo — Fase 2A

## Diseño

`GeminiLLMProvider` es la tercera implementación de LLMProvider. Fake y Compatible se
conservan. `HTTPDecisionProvider` reúne el mecanismo ya existente de prompt, parse,
Pydantic, validación de negocio, retries y eventos; cada adapter implementa transporte y
normalización. `build_provider` centraliza la selección para bootstrap y evaluador.
No hubo cambios de esta iteración en EquityAgent, AgentState, AgentDecision, ToolRegistry,
tools, adapters de mercado, API ni políticas. El prompt conserva exactamente phase2a-v1.

La configuración local `.env` ya seleccionaba gemini al empezar. Eso causaba cuatro
fallos de validación de Settings en el chequeo previo; el literal ahora admite gemini.
El test de composición offline selecciona Fake explícitamente para que una configuración
local real nunca lo convierta accidentalmente en una llamada externa.

## Configuración

```dotenv
LLM_PROVIDER=gemini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta
LLM_MODEL=gemini-3.6-flash
LLM_API_KEY=<secreto local>
LLM_TIMEOUT_SECONDS=20
LLM_MAX_RETRIES=2
LLM_RESPONSE_FORMAT=json_object
AGENT_PROMPT_VERSION=phase2a-v1
```

La key sigue siendo SecretStr en Settings; se usa solo para construir el header nativo.
Los valores de URL/modelo anteriores son ejemplos configurables, no constantes del adapter.
La eliminación preexistente de `.env.example` se respetó; no se alteró `.env` ni su secreto.

## Request, respuesta y structured output

POST `{LLM_BASE_URL}/models/{LLM_MODEL}:generateContent`, con `x-goog-api-key` y Content-Type
application/json. Nunca chat/completions ni autenticación en query string. No se envían
native tools ni function declarations. Las tools siguen siendo schemas dentro del contexto.

`systemInstruction` contiene el mismo system prompt y schema de AgentDecision.
`contents` contiene un turno user con partes JSON separadas: user_request y agent_context.
El contexto es la misma proyección acotada; no duplica el objetivo. El feedback de reparación
ocupa una parte adicional y conserva su contenido previo. El hash identifica los mensajes
lógicos compartidos antes de su adaptación al wire format nativo.

- json_object: generationConfig.responseMimeType=application/json (validado realmente).
- json_schema: además responseJsonSchema con el schema de AgentDecision (probado offline).
- none: JSON solicitado mediante el prompt, sin restricciones de MIME/schema.

Se usa candidateCount=1. Se toma el primer candidate, se exige finishReason STOP y se unen
sus partes text no marcadas thought. Se descartan thoughtSignature, thoughts y otros campos
opacos. Ausencia de candidates/text no se convierte en decisión financiera.
Después: parse JSON, AgentDecision Pydantic, callback de validación de negocio existente.
La ejecución solo ocurre después de aceptar esa decisión.

Formato contrastado con documentación oficial:
[generateContent](https://ai.google.dev/api/generate-content) y
[structured output](https://ai.google.dev/gemini-api/docs/structured-output).

## Usage y metadata

| Gemini | Contrato de tracing | Métrica del evaluador |
| --- | --- | --- |
| promptTokenCount | prompt_tokens | input_tokens |
| candidatesTokenCount | completion_tokens | output_tokens |
| totalTokenCount | total_tokens | total_tokens |
| thoughtsTokenCount | reasoning_tokens | reasoning_tokens |

Solo se aceptan enteros no negativos. Tokens ausentes no se inventan. El total puede incluir
reasoning y ser distinto de input+output. modelVersion y responseId se guardan como metadata
acotada; jamás la respuesta completa ni thoughtSignature. Se conservan en SQLite los eventos
existentes LLM_STARTED, LLM_SUCCEEDED, LLM_FAILED y DECISION_VALIDATION_FAILED.

Costo sigue siendo null sin precios y usage completo. Si hay reasoning tokens también queda
null: no se presupone cómo cobrarlos usando solo los dos precios actuales. No se añadió una
tarifa ni contrato financiero específico de Gemini.

## Errores

Los eventos de error incluyen http_status (si hubo respuesta), provider_error_code local
sanitizado y retryable. No se copia el mensaje del servidor ni su body de error, que puede
contener datos privados. 400/401/403/404 y otros 4xx permanentes no se reintentan. 408, 429,
5xx y errores de transporte se reintentan dentro de LLM_MAX_RETRIES. JSON/schema/negocio
inválidos usan el mismo presupuesto de reparación existente.

No existía backoff de LLM. Para Gemini se agregó espera exponencial acotada: 0,5 s y 1 s
con los dos retries permitidos (cap de 2 s). Compatible conserva su comportamiento previo.
STOP es utilizable; MAX_TOKENS, OTHER o finishReason ausente permiten reparación acotada;
otros motivos terminales, por ejemplo SAFETY, fallan sin retry. Nunca se aumenta el
presupuesto automáticamente. Agotamiento/permanencia termina en ERROR, no ABSTAIN financiero.

## Ejecución

```powershell
# Offline, sin credenciales necesarias:
python -m pytest -q
# Con la configuración local anterior:
$env:RUN_LLM_TESTS = "1"
python -m pytest tests/integration/test_real_llm.py::test_real_llm_minimal -q -s
python scripts/run_real_llm.py
# Dataset compartido con tools sintéticas, cuando cuota/disponibilidad lo permitan:
python scripts/eval_real_llm.py --runs 3
python scripts/show_trace.py b1473d6a-a900-4825-be90-3ffae4ddc34f
```

El mismo evaluador sirve compatible y gemini, con provider/model/prompt_version/dataset_version.
Los reportes quedan locales en evals/results, ignorados por Git. La prueba mínima también
conserva eventos si falla. El runner live conserva el trace en la base configurada.

## Evidencia real del 2026-09-15

1. Prueba mínima: PASS contra gemini-3.6-flash nativo. Decisión CLARIFY, modelVersion
   gemini-3.6-flash, responseId b0Wpaor1Jv35qtsP3r7NkQ8. Usage: input 851, output 92,
   reasoning 551, total 1494. Latencia de petición: 5064 ms. Reporte:
   `evals/results/minimal_gemini_20260915T131743.json`.
2. Primer agente controlado por Gemini:
   **trace_id b1473d6a-a900-4825-be90-3ffae4ddc34f**, prompt phase2a-v1.
   resolve_asset SUCCESS → get_market_history GGAL/6M SUCCESS (datos live de Market Tracker).
   Intent technical; fundamental NOT_REQUESTED. El step 2 recuperó dos HTTP 503 mediante
   retries. En el step 3 hubo 503, 503 y finalmente 429; terminó **ERROR** sin ejecutar
   indicadores ni metodología. No emitió recomendación ni cifras inventadas.
   Reporte: `evals/results/live_b1473d6a-a900-4825-be90-3ffae4ddc34f.json`.

La primera prueba dentro del sandbox falló por conectividad; la prueba mínima autorizada
fuera del sandbox pasó. La ejecución live también fue autorizada fuera del sandbox.
No se hicieron más llamadas después de agotar retries con 429. No se ejecutó el dataset
real completo ni se validó un GGAL end-to-end exitoso. Los 503 también ocurren en la API
nativa: el transporte funcional no garantiza disponibilidad sostenida.

## Verificación offline final

130 tests PASS, 4 opt-in SKIP. Ruff PASS, format PASS (58 archivos), evals originales 7 PASS,
smoke API PASS, pip check PASS. Permanecen las dos advertencias de Starlette de la baseline.
Se agregaron 22 tests offline: transporte, JSON schema, normalización de usage/thoughts,
privacidad, JSON/acción/schema inválidos, tool inexistente, 503/429, 4xx permanentes, timeout,
candidates/text/finishReason, presupuesto/backoff y selección de Gemini en el evaluador.

## Archivos de esta iteración

Agregados: adapters/llm/gemini.py, adapters/llm/http_provider.py,
tests/unit/test_gemini_provider.py y este documento.
Modificados: adapters/llm/compatible.py, bootstrap.py, config.py, evaluation.py,
scripts/eval_real_llm.py, scripts/run_real_llm.py, tests/integration/test_real_llm.py,
tests/integration/test_api_storage.py y documentación README/arquitectura/verificación/evals.
Los archivos de la iteración anterior siguen pendientes de commit, sin revertirlos.

## Pendiente

Repetir el milestone cuando el endpoint y la cuota permitan completar los steps, y ejecutar
las 17 evals con repeticiones. JSON schema nativo aún no está validado externamente.
RAG sigue DEMO; no hay cambios de dominio, valoración, extracción PDF ni recomendaciones.
No se hizo commit, push, tag, release ni deploy.
