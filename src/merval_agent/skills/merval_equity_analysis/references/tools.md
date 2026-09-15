# Tools

| Tool | Cuándo usar | Cuándo no |
|---|---|---|
| resolve_asset(query) | Antes de datos; nombre ambiguo | No asumir instrumento por semejanza |
| get_market_history(ticker, range) | Técnico/full; ampliar rango si falta muestra | Fundamental puro |
| calculate_technical_indicators(ticker) | Sobre historial almacenado | Sin OHLCV; nunca inyectar precios del LLM |
| list_financial_documents(ticker) | Explorar metadata Bolsar | Técnico puro; no calcula ratios |
| get_latest_financial_statement(ticker) | Buscar documento financiero reciente | No implica extracción/solidez |
| search_methodology(query, source) | murphy técnico; graham fundamental | No usar notas demo como evidencia del libro |

Rangos: 1W, 1M, 3M, 6M, 1Y. SMA50 requiere 50 ruedas; MACD señal 34; RSI14 15.
No hace falta ejecutar todas las tools. Reutilizá observaciones y elegí según necesidad.
