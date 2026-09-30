# Tools

| Tool | Cuándo usar | Cuándo no |
|---|---|---|
| resolve_asset(query) | Antes de datos; nombre ambiguo | No asumir instrumento por semejanza |
| get_market_history(ticker, range) | Técnico; ampliar rango si falta muestra | Pedidos fuera de alcance |
| calculate_technical_indicators(ticker) | Sobre historial almacenado | Sin OHLCV; nunca inyectar precios del LLM |

Rangos: 1W, 1M, 3M, 6M, 1Y. SMA50 requiere 50 ruedas; MACD señal 34; RSI14 15.
No hace falta ejecutar todas las tools. Reutilizá observaciones y elegí según necesidad.
