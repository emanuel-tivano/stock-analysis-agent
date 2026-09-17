# Baseline LLM local: Ollama / LM Studio

## Auditoría y alcance

`CompatibleLLMProvider` ya es suficiente y no se modificó. Usa HTTPX, sin SDK ni
dependencia de OpenAI cloud: POST a `<LLM_BASE_URL>/chat/completions`, Authorization
Bearer configurable, timeout por request y `choices[0].message.content` como texto.
Comparte validación Pydantic de AgentDecision, validaciones de negocio, retries y
tracing con los demás providers. No hay LocalProvider ni infraestructura paralela.

Se conserva EquityAgent, prompt phase2a-v1, AgentDecision, tools, policies, RAG,
dataset de 17 casos y evaluador. Los cambios operativos son el smoke `--provider-only`
del runner existente y metadata adicional en el reporte de evaluación.

Referencias oficiales:

- [Ollama: OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility):
  endpoint compatible y API key ficticia (ignorada por el servidor local).
- [LM Studio: OpenAI-compatible endpoints](https://lmstudio.ai/docs/developer/openai-compat)
  y [structured output](https://lmstudio.ai/docs/developer/openai-compat/structured-output).

La compatibilidad se verificó con MockTransport, sin contactar instalaciones reales.
No se observó una incompatibilidad real de servidor porque esa prueba queda al usuario.

## Configuración

Iniciar el servidor local y cargar previamente el modelo instruct elegido. Los puertos
11434 y 1234 son defaults habituales; usar el puerto real de la instalación. El ID debe
coincidir con `/v1/models`. No se descarga ni fija ningún modelo desde este proyecto.

Ollama, en `.env`:

```dotenv
LLM_PROVIDER=compatible
LLM_BASE_URL=http://127.0.0.1:11434/v1
LLM_MODEL=<modelo-instruct>
LLM_API_KEY=local
LLM_TIMEOUT_SECONDS=120
LLM_MAX_RETRIES=1
LLM_RESPONSE_FORMAT=json_object
AGENT_PROMPT_VERSION=phase2a-v1
```

LM Studio, en `.env`:

```dotenv
LLM_PROVIDER=compatible
LLM_BASE_URL=http://127.0.0.1:1234/v1
LLM_MODEL=<modelo-instruct>
LLM_API_KEY=local
LLM_TIMEOUT_SECONDS=120
LLM_MAX_RETRIES=1
LLM_RESPONSE_FORMAT=json_object
AGENT_PROMPT_VERSION=phase2a-v1
```

El contrato actual exige clave no vacía: `local` sirve para un servidor sin
autenticación. Si el servidor exige autenticación, configurar su token real en privado.
No imprimir Settings completo, claves ni headers. Variables de entorno existentes tienen
precedencia sobre `.env`; evitar conservar configuración Gemini en la misma terminal.
Timeout admite 120 o más segundos sin cambiar el default global de 20; es un timeout
por operación HTTP, no un límite de tiempo total del Agent.run().

## Structured output y errores

Comenzar con `json_object`. Si el servidor/modelo lo rechaza, configurar
`LLM_RESPONSE_FORMAT=none` y volver a probar manualmente. No hay fallback automático.
`none` omite response_format del request, pero el mismo prompt sigue exigiendo JSON y
el parser mantiene Pydantic y validaciones de negocio. Markdown, texto adicional o
decisiones inválidas consumen retries y cuentan como invalid decisions; no se extrae
JSON de texto libre. Los modelos no tienen igual capacidad para respetar JSON.
LM Studio documenta JSON schema; eso no garantiza que todo modelo/versión admita
json_object. Registrar siempre el formato usado al comparar resultados.

Connection refused, timeout y 5xx agotados son PROVIDER_ERROR. Decisiones inválidas
agotadas son FAIL. El resultado conserva LLM_FAILURE, con telemetry HTTP_xxx/TIMEOUT/TRANSPORT_ERROR
y retryable en los eventos. Los 4xx permanentes no se reintentan. Una respuesta lenta exitosa
conserva la evaluación semántica normal. Sin usage, los eventos tienen usage=null y
tokens/costo quedan null: nunca se inventan conteos.

Los traces mantienen los eventos existentes: LLM_STARTED, LLM_SUCCEEDED/LLM_FAILED,
DECISION_MADE, TOOL_STARTED, TOOL_SUCCEEDED, STATE_UPDATED y AGENT_FINISHED, además de
los eventos existentes de validación/retry cuando correspondan. El smoke sólo llama
al provider, por lo que no genera eventos de tools ni persiste una ejecución del agente.

## Validación manual (PowerShell, desde la raíz)

Estos comandos son para ejecutar manualmente. No se ejecutaron contra un LLM local.

### A. Comprobar servidor y modelo cargado

Después de iniciar Ollama o el servidor de LM Studio:

```powershell
# Ollama; para LM Studio usar http://127.0.0.1:1234/v1
$localBase = 'http://127.0.0.1:11434/v1'
Invoke-RestMethod "$localBase/models" | ConvertTo-Json -Depth 6
```

Si el servidor exige token, usar su mecanismo de autenticación sin imprimir headers.
Elegir un modelo local ya disponible; el proyecto no instala servidores ni modelos.

### B. Comprobar Settings sin revelar secretos

Después de completar `.env` con una de las configuraciones anteriores:

```powershell
python -c "from merval_agent.config import Settings; from merval_agent.evaluation import provider_environment; import json; s=Settings(); print(json.dumps(dict(provider=s.llm_provider, model=s.llm_model, environment=provider_environment(s.llm_base_url), timeout=s.llm_timeout_seconds, retries=s.llm_max_retries, response_format=s.llm_response_format, prompt_version=s.agent_prompt_version, api_key_configured=bool(s.llm_api_key.get_secret_value())), indent=2))"
```

Debe indicar compatible, modelo elegido, local, 120, json_object y phase2a-v1.

### C. Smoke sólo del provider

```powershell
$env:RUN_LLM_TESTS = '1'
python scripts/run_real_llm.py --provider-only
```

Envía `Necesito más información` mediante el contexto/prompt existente, sin herramientas
ni fuentes de mercado. Esperar una decisión válida como CLARIFY. Imprime exclusivamente
provider, model, status, decision.action, latency_ms y usage del último intento (si existe).
Salida 0 indica decisión válida; 1 indica error del provider o invalidación agotada.
No imprime respuesta, prompt, claves ni excepciones del servidor. El smoke comprueba
el provider y la validación de decisión disponible, no la corrección del dataset.
Sin `--provider-only`, el runner conserva su ejecución anterior con datos externos.

### D. Levantar Uvicorn

```powershell
python -m uvicorn merval_agent.api.app:app --host 127.0.0.1 --port 8000
```

La API usa Settings y no exige RUN_LLM_TESTS; el opt-in protege los scripts de prueba.
Los siguientes runs de API usan Market Tracker/Bolsar reales según sus configuraciones.
Por eso pueden fallar por datos externos aunque el modelo local funcione. El evaluator
usa fixtures y es la comparación controlada. En otra terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
function Invoke-AgentCase([string]$message) {
    $body = @{message=$message} | ConvertTo-Json -Compress
    Invoke-RestMethod http://127.0.0.1:8000/agent/run -Method Post `
      -ContentType 'application/json; charset=utf-8' `
      -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 1800 |
      ConvertTo-Json -Depth 20
}
```

### E–G. Técnico, fundamentos y ambiguo

```powershell
Invoke-AgentCase 'Analizá técnicamente GGAL'
Invoke-AgentCase 'Analizá los fundamentos de PAMP'
Invoke-AgentCase 'Necesito más información'
```

Revisar status, dimensiones solicitadas, abstenciones y trace_id. No asumir que un
resultado válido de schema equivale a éxito semántico. Los traces permanecen en SQLite.

### H. Si los tres funcionan: dataset 17 × 1

```powershell
$env:RUN_LLM_TESTS = '1'
python scripts/eval_real_llm.py --runs 1 --llm-min-interval-seconds 0 --delay-seconds 0 --provider-error-cooldown-seconds 0
# Baseline Fake del mismo dataset:
python scripts/eval_real_llm.py --fake --runs 1
```

Secuencial, sin espera impuesta con valores 0. PASS/FAIL/PROVIDER_ERROR/NOT_EVALUATED y
denominadores permanecen iguales. Exit codes: 0 todo PASS; 1 algún FAIL; 2 incompleta
sin FAIL. Para Gemini seleccionar su configuración native y usar el mismo evaluator
con el intervalo adecuado a su cuota, por ejemplo `--llm-min-interval-seconds 15`.

## Identidad y comparación Fake / Local / Gemini

Cada reporte separado conserva provider, model, prompt_version, dataset_version,
runs_per_case (repeticiones), response_format, llm_min_interval_seconds y métricas.
provider_environment es local sólo para localhost o una IP loopback (incluido ::1);
el resto se etiqueta remote sin resolver DNS. LAN, contenedores y túneles requieren
anotar el entorno manualmente: es una inferencia del endpoint, no una detección de
hardware ni garantía de ejecución local. Fake usa environment/response_format=null.
No se guarda base_url: no existía una política de sanitización y podría contener secretos.

Los archivos real_llm_<model>_<timestamp>.json no combinan ejecuciones de modelos
distintos. Agrupar por identidad completa, no sólo provider=compatible. Conservar también
versión del servidor, quantización, hardware y modelo exacto en las notas de la corrida.
La comparación automática del CLI muestra Fake frente al reporte actual; comparar el
reporte Gemini separado con iguales versiones y repeticiones. Fake es determinístico
y no ejecuta el prompt LLM. Si cambia response_format, declararlo como variable adicional.

El objetivo es aislar calidad del modelo, estabilidad del provider, latencia y cumplimiento
del output estructurado conservando la arquitectura. La baseline local permite repetición
sin cuotas de una API externa; sigue dependiendo de memoria, capacidad y configuración
del servidor. No reemplaza Gemini como evidencia de integración externa. Para latencia,
considerar calentamiento/carga del modelo, hardware y throttling Gemini (las esperas
dentro del run están incluidas). Mantener precios sin configurar para local: no reutilizar
tarifas Gemini al estimar costo. No se afirma calidad real hasta ejecutar estas pruebas.
