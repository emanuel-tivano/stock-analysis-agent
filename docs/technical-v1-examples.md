# Respuestas completas de la V1 técnica

Ejecución Fake offline del dataset `technical-v1-closure-1`; no son cotizaciones reales.
Los JSON siguientes son las respuestas completas de `POST /agent/run`, sin recortes.

## Tendencia clara

Caso `bullish`. Snapshot y SQLite en `evals/results/technical-v1-20260916T215304/verified-technical-fake/bullish/`.

```json
{
  "status": "ANSWER",
  "ticker": "GGAL",
  "company_name": "Grupo Financiero Galicia",
  "analysis_type": "technical",
  "as_of": "2026-09-15",
  "executive_summary": "Señal técnica alcista; tendencia alcista según las medias y el precio. Momentum alcista sustentado por: RSI14 100.00: sobrecompra, sesgo alcista. No implica reversión automática.; MACD / cero: 7.00 por encima de 0.00.; MACD / señal: 7.00 igual de 7.00.. Muestra: 60 observaciones al 2026-09-15.",
  "generation": {
    "mode": "SIMULATED",
    "llm_status": "NOT_USED",
    "provider": null,
    "requested_model": null,
    "model": null,
    "model_version": null,
    "attempts": 0,
    "retry_after_seconds": null,
    "model_fallback_used": false,
    "warnings": []
  },
  "technical": {
    "status": "BULLISH",
    "metrics": {
      "current_price": 159.0,
      "macd_histogram": -1.7763568394002505e-15,
      "sma20": 149.5,
      "sma50": 134.5,
      "ema12": 153.5,
      "ema26": 146.5,
      "rsi14": 100.0,
      "macd": 7.0,
      "macd_signal": 7.000000000000002,
      "change_percent": 59.00000000000001,
      "period_high": 160.0,
      "period_low": 99.0,
      "average_volume": 100.0,
      "sample_size": 60
    },
    "history_only_metrics": null,
    "assessment": {
      "status": "COMPLETE",
      "signals": {
        "price_sma20": {
          "signal": "BULLISH",
          "explanation": "Precio / SMA20: 159.00 por encima de 149.50."
        },
        "price_sma50": {
          "signal": "BULLISH",
          "explanation": "Precio / SMA50: 159.00 por encima de 134.50."
        },
        "sma20_sma50": {
          "signal": "BULLISH",
          "explanation": "SMA20 / SMA50: 149.50 por encima de 134.50."
        },
        "ema12_ema26": {
          "signal": "BULLISH",
          "explanation": "EMA12 / EMA26: 153.50 por encima de 146.50."
        },
        "rsi14": {
          "signal": "BULLISH",
          "explanation": "RSI14 100.00: sobrecompra, sesgo alcista. No implica reversión automática."
        },
        "macd_signal": {
          "signal": "NEUTRAL",
          "explanation": "MACD / señal: 7.00 igual de 7.00."
        },
        "macd_zero": {
          "signal": "BULLISH",
          "explanation": "MACD / cero: 7.00 por encima de 0.00."
        },
        "macd_histogram": {
          "signal": "NEUTRAL",
          "explanation": "Histograma MACD / cero: -0.00 igual de 0.00. Magnitud absoluta 0.00; -0.0000% del precio. Una sola lectura no demuestra expansión ni un cruce reciente."
        },
        "period_change": {
          "signal": "BULLISH",
          "explanation": "Variación del período / cero: 59.00 por encima de 0.00. Contexto de la muestra; no confirma la dirección actual."
        },
        "volume": {
          "signal": "NEUTRAL",
          "explanation": "Volumen último 100.00 frente al promedio de las 20 barras previas 100.00: sin confirmación direccional. No certifica cierre de rueda ni anticipa precios."
        }
      },
      "trend": "BULLISH",
      "momentum": "BULLISH",
      "momentum_state": "BULLISH",
      "confirmation": "ALIGNED",
      "completion_reasons": [
        "Todos los indicadores de precios requeridos disponibles; sin filas descartadas."
      ],
      "basis": {
        "history_as_of": "2026-09-15",
        "indicators_as_of": "2026-09-15",
        "history_fetched_at": "2026-09-16T22:00:00Z",
        "history_closure": "UNVERIFIED",
        "quote_as_of": null,
        "quote_observed_at": null,
        "quote_fetched_at": null,
        "quote_price": null,
        "quote_provisional": false,
        "quote_in_indicators": false,
        "policy": "HISTORY_ONLY"
      },
      "conclusion": "BULLISH",
      "confidence": "HIGH",
      "as_of": "2026-09-15",
      "fetched_at": "2026-09-16T22:00:00Z",
      "freshness": "RECENT",
      "missing_indicators": {},
      "agreements": [
        "Lectura alcista: price_sma20, price_sma50, sma20_sma50, ema12_ema26, rsi14, macd_zero",
        "Lectura neutral: macd_signal, macd_histogram"
      ],
      "conflicts": [],
      "warnings": [
        "Vigencia con tolerancia de días calendario; no certifica ausencia de ruedas faltantes ni cierre."
      ]
    },
    "narrative_origin": "deterministic",
    "evidence": [
      {
        "source": "https://market.test/api/stocks/GGAL/history?range=6M&market=bCBA",
        "chunk_id": "fb643fd4-d3b0-4c56-a17c-500ef32506d3:ohlcv",
        "text": "OHLCV normalizado; métricas derivadas por Python.",
        "score": 1.0,
        "kind": "DATA",
        "metadata": {
          "mode": "live",
          "fetched_at": "2026-09-16T22:00:00+00:00",
          "as_of": "2026-09-15",
          "currency": "peso_Argentino",
          "discarded_rows": 0,
          "enrichment_status": "unavailable"
        }
      }
    ],
    "interpretation": "Momentum alcista sustentado por: RSI14 100.00: sobrecompra, sesgo alcista. No implica reversión automática.; MACD / cero: 7.00 por encima de 0.00.; MACD / señal: 7.00 igual de 7.00.. Precio / SMA20: 159.00 por encima de 149.50. Precio / SMA50: 159.00 por encima de 134.50. SMA20 / SMA50: 149.50 por encima de 134.50. EMA12 / EMA26: 153.50 por encima de 146.50. RSI14 100.00: sobrecompra, sesgo alcista. No implica reversión automática. MACD / señal: 7.00 igual de 7.00. MACD / cero: 7.00 por encima de 0.00. Histograma MACD / cero: -0.00 igual de 0.00. Magnitud absoluta 0.00; -0.0000% del precio. Una sola lectura no demuestra expansión ni un cruce reciente. Variación del período / cero: 59.00 por encima de 0.00. Contexto de la muestra; no confirma la dirección actual. Volumen último 100.00 frente al promedio de las 20 barras previas 100.00: sin confirmación direccional. No certifica cierre de rueda ni anticipa precios. Confirmación: indicadores alineados; no es certeza predictiva.  Describe señales observadas, no un pronóstico ni una recomendación financiera personalizada.",
    "limitations": [
      "Precios según variante del proveedor; no se verificaron ajustes corporativos.",
      "Confianza describe calidad de evidencia, no probabilidad de un pronóstico.",
      "Vigencia con tolerancia de días calendario; no certifica ausencia de ruedas faltantes ni cierre.",
      "Quote no disponible o no válida; se conserva únicamente el historial."
    ]
  },
  "fundamental": {
    "status": "NOT_REQUESTED",
    "metrics": null,
    "history_only_metrics": null,
    "assessment": null,
    "narrative_origin": null,
    "evidence": [],
    "interpretation": "",
    "limitations": []
  },
  "integrated_view": {
    "agreements": [],
    "conflicts": [],
    "risks": []
  },
  "data_quality": {
    "missing_information": [],
    "stale_data": false,
    "abstentions": []
  },
  "sources": [
    "https://market.test/api/stocks/GGAL/history?range=6M&market=bCBA"
  ],
  "trace_id": "fb643fd4-d3b0-4c56-a17c-500ef32506d3",
  "session_id": "9af4bf3e-3895-4117-a7b3-f6fabdd50ec8",
  "errors": []
}
```

## Señales contradictorias

Caso `contradictions`. Snapshot y SQLite en `evals/results/technical-v1-20260916T215304/verified-technical-fake/contradictions/`.

```json
{
  "status": "ANSWER",
  "ticker": "GGAL",
  "company_name": "Grupo Financiero Galicia",
  "analysis_type": "technical",
  "as_of": "2026-09-15",
  "executive_summary": "Señal técnica mixta; tendencia mixta según las medias y el precio. Momentum bajista sustentado por: RSI14 18.49: sobreventa, sesgo bajista. No implica reversión automática.; MACD / cero: -2.42 por debajo de 0.00.; MACD / señal: -2.42 por debajo de 3.19.. Muestra: 60 observaciones al 2026-09-15.",
  "generation": {
    "mode": "SIMULATED",
    "llm_status": "NOT_USED",
    "provider": null,
    "requested_model": null,
    "model": null,
    "model_version": null,
    "attempts": 0,
    "retry_after_seconds": null,
    "model_fallback_used": false,
    "warnings": []
  },
  "technical": {
    "status": "MIXED",
    "metrics": {
      "current_price": 105.0,
      "macd_histogram": -5.604329368686102,
      "sma20": 141.5,
      "sma50": 131.3,
      "ema12": 133.32393419752054,
      "ema26": 135.7392272108252,
      "rsi14": 18.490300501682725,
      "macd": -2.415293013304648,
      "macd_signal": 3.189036355381454,
      "change_percent": 5.000000000000004,
      "period_high": 155.0,
      "period_low": 99.0,
      "average_volume": 100.0,
      "sample_size": 60
    },
    "history_only_metrics": null,
    "assessment": {
      "status": "COMPLETE",
      "signals": {
        "price_sma20": {
          "signal": "BEARISH",
          "explanation": "Precio / SMA20: 105.00 por debajo de 141.50."
        },
        "price_sma50": {
          "signal": "BEARISH",
          "explanation": "Precio / SMA50: 105.00 por debajo de 131.30."
        },
        "sma20_sma50": {
          "signal": "BULLISH",
          "explanation": "SMA20 / SMA50: 141.50 por encima de 131.30."
        },
        "ema12_ema26": {
          "signal": "BEARISH",
          "explanation": "EMA12 / EMA26: 133.32 por debajo de 135.74."
        },
        "rsi14": {
          "signal": "BEARISH",
          "explanation": "RSI14 18.49: sobreventa, sesgo bajista. No implica reversión automática."
        },
        "macd_signal": {
          "signal": "BEARISH",
          "explanation": "MACD / señal: -2.42 por debajo de 3.19."
        },
        "macd_zero": {
          "signal": "BEARISH",
          "explanation": "MACD / cero: -2.42 por debajo de 0.00."
        },
        "macd_histogram": {
          "signal": "BEARISH",
          "explanation": "Histograma MACD / cero: -5.60 por debajo de 0.00. Magnitud absoluta 5.60; -5.3375% del precio. Una sola lectura no demuestra expansión ni un cruce reciente."
        },
        "period_change": {
          "signal": "BULLISH",
          "explanation": "Variación del período / cero: 5.00 por encima de 0.00. Contexto de la muestra; no confirma la dirección actual."
        },
        "volume": {
          "signal": "NEUTRAL",
          "explanation": "Volumen último 100.00 frente al promedio de las 20 barras previas 100.00: sin confirmación direccional. No certifica cierre de rueda ni anticipa precios."
        }
      },
      "trend": "MIXED",
      "momentum": "BEARISH",
      "momentum_state": "BEARISH",
      "confirmation": "UNCONFIRMED",
      "completion_reasons": [
        "Todos los indicadores de precios requeridos disponibles; sin filas descartadas."
      ],
      "basis": {
        "history_as_of": "2026-09-15",
        "indicators_as_of": "2026-09-15",
        "history_fetched_at": "2026-09-16T22:00:00Z",
        "history_closure": "UNVERIFIED",
        "quote_as_of": null,
        "quote_observed_at": null,
        "quote_fetched_at": null,
        "quote_price": null,
        "quote_provisional": false,
        "quote_in_indicators": false,
        "policy": "HISTORY_ONLY"
      },
      "conclusion": "MIXED",
      "confidence": "HIGH",
      "as_of": "2026-09-15",
      "fetched_at": "2026-09-16T22:00:00Z",
      "freshness": "RECENT",
      "missing_indicators": {},
      "agreements": [
        "Lectura bajista: price_sma20, price_sma50, ema12_ema26, rsi14, macd_signal, macd_zero, macd_histogram"
      ],
      "conflicts": [
        "Señales alcistas (sma20_sma50) coexisten con bajistas (price_sma20, price_sma50, ema12_ema26, rsi14, macd_signal, macd_zero, macd_histogram)."
      ],
      "warnings": [
        "Vigencia con tolerancia de días calendario; no certifica ausencia de ruedas faltantes ni cierre."
      ]
    },
    "narrative_origin": "deterministic",
    "evidence": [
      {
        "source": "https://market.test/api/stocks/GGAL/history?range=6M&market=bCBA",
        "chunk_id": "37af2a8e-3450-41db-982f-fb2474ed1aa2:ohlcv",
        "text": "OHLCV normalizado; métricas derivadas por Python.",
        "score": 1.0,
        "kind": "DATA",
        "metadata": {
          "mode": "live",
          "fetched_at": "2026-09-16T22:00:00+00:00",
          "as_of": "2026-09-15",
          "currency": "peso_Argentino",
          "discarded_rows": 0,
          "enrichment_status": "unavailable"
        }
      }
    ],
    "interpretation": "Momentum bajista sustentado por: RSI14 18.49: sobreventa, sesgo bajista. No implica reversión automática.; MACD / cero: -2.42 por debajo de 0.00.; MACD / señal: -2.42 por debajo de 3.19.. Precio / SMA20: 105.00 por debajo de 141.50. Precio / SMA50: 105.00 por debajo de 131.30. SMA20 / SMA50: 141.50 por encima de 131.30. EMA12 / EMA26: 133.32 por debajo de 135.74. RSI14 18.49: sobreventa, sesgo bajista. No implica reversión automática. MACD / señal: -2.42 por debajo de 3.19. MACD / cero: -2.42 por debajo de 0.00. Histograma MACD / cero: -5.60 por debajo de 0.00. Magnitud absoluta 5.60; -5.3375% del precio. Una sola lectura no demuestra expansión ni un cruce reciente. Variación del período / cero: 5.00 por encima de 0.00. Contexto de la muestra; no confirma la dirección actual. Volumen último 100.00 frente al promedio de las 20 barras previas 100.00: sin confirmación direccional. No certifica cierre de rueda ni anticipa precios. Confirmación: sin confirmación conjunta de los indicadores. Señales alcistas (sma20_sma50) coexisten con bajistas (price_sma20, price_sma50, ema12_ema26, rsi14, macd_signal, macd_zero, macd_histogram). Describe señales observadas, no un pronóstico ni una recomendación financiera personalizada.",
    "limitations": [
      "Precios según variante del proveedor; no se verificaron ajustes corporativos.",
      "Confianza describe calidad de evidencia, no probabilidad de un pronóstico.",
      "Vigencia con tolerancia de días calendario; no certifica ausencia de ruedas faltantes ni cierre.",
      "Quote no disponible o no válida; se conserva únicamente el historial."
    ]
  },
  "fundamental": {
    "status": "NOT_REQUESTED",
    "metrics": null,
    "history_only_metrics": null,
    "assessment": null,
    "narrative_origin": null,
    "evidence": [],
    "interpretation": "",
    "limitations": []
  },
  "integrated_view": {
    "agreements": [],
    "conflicts": [],
    "risks": []
  },
  "data_quality": {
    "missing_information": [],
    "stale_data": false,
    "abstentions": []
  },
  "sources": [
    "https://market.test/api/stocks/GGAL/history?range=6M&market=bCBA"
  ],
  "trace_id": "37af2a8e-3450-41db-982f-fb2474ed1aa2",
  "session_id": "27c67c81-c52c-4d79-ab8f-782239af1429",
  "errors": []
}
```

## Datos insuficientes

Caso `short`. Snapshot y SQLite en `evals/results/technical-v1-20260916T215304/verified-technical-fake/short/`.

```json
{
  "status": "ABSTAIN",
  "ticker": "GGAL",
  "company_name": "Grupo Financiero Galicia",
  "analysis_type": "technical",
  "as_of": "2026-09-15",
  "executive_summary": "No hay evidencia cuantitativa suficiente para responder esta dimensión.",
  "generation": {
    "mode": "SIMULATED",
    "llm_status": "NOT_USED",
    "provider": null,
    "requested_model": null,
    "model": null,
    "model_version": null,
    "attempts": 0,
    "retry_after_seconds": null,
    "model_fallback_used": false,
    "warnings": []
  },
  "technical": {
    "status": "INSUFFICIENT_DATA",
    "metrics": {
      "current_price": 113.0,
      "macd_histogram": null,
      "sma20": null,
      "sma50": null,
      "ema12": 107.5,
      "ema26": null,
      "rsi14": null,
      "macd": null,
      "macd_signal": null,
      "change_percent": 12.99999999999999,
      "period_high": 114.0,
      "period_low": 99.0,
      "average_volume": 100.0,
      "sample_size": 14
    },
    "history_only_metrics": null,
    "assessment": {
      "status": "INSUFFICIENT_DATA",
      "signals": {},
      "trend": "UNAVAILABLE",
      "momentum": "UNAVAILABLE",
      "momentum_state": "UNAVAILABLE",
      "confirmation": "UNAVAILABLE",
      "completion_reasons": [],
      "basis": {
        "history_as_of": "2026-09-15",
        "indicators_as_of": "2026-09-15",
        "history_fetched_at": "2026-09-16T22:00:00Z",
        "history_closure": "UNVERIFIED",
        "quote_as_of": null,
        "quote_observed_at": null,
        "quote_fetched_at": null,
        "quote_price": null,
        "quote_provisional": false,
        "quote_in_indicators": false,
        "policy": "HISTORY_ONLY"
      },
      "conclusion": "UNAVAILABLE",
      "confidence": "UNAVAILABLE",
      "as_of": "2026-09-15",
      "fetched_at": "2026-09-16T22:00:00Z",
      "freshness": "RECENT",
      "missing_indicators": {
        "sma20": "Requiere 20 observaciones; disponibles 14.",
        "sma50": "Requiere 50 observaciones; disponibles 14.",
        "ema26": "Requiere 26 observaciones; disponibles 14.",
        "rsi14": "Requiere 15 observaciones; disponibles 14.",
        "macd": "Requiere 26 observaciones; disponibles 14.",
        "macd_signal": "Requiere 34 observaciones; disponibles 14.",
        "macd_histogram": "Requiere 34 observaciones; disponibles 14."
      },
      "agreements": [],
      "conflicts": [],
      "warnings": [
        "Vigencia con tolerancia de días calendario; no certifica ausencia de ruedas faltantes ni cierre.",
        "Se requiere precio actual y al menos 15 observaciones."
      ]
    },
    "narrative_origin": "deterministic",
    "evidence": [
      {
        "source": "https://market.test/api/stocks/GGAL/history?range=6M&market=bCBA",
        "chunk_id": "6b987ecc-d17a-45fb-b728-5d20629285e5:ohlcv",
        "text": "OHLCV normalizado; métricas derivadas por Python.",
        "score": 1.0,
        "kind": "DATA",
        "metadata": {
          "mode": "live",
          "fetched_at": "2026-09-16T22:00:00+00:00",
          "as_of": "2026-09-15",
          "currency": "peso_Argentino",
          "discarded_rows": 0,
          "enrichment_status": "unavailable"
        }
      }
    ],
    "interpretation": "Vigencia con tolerancia de días calendario; no certifica ausencia de ruedas faltantes ni cierre. Se requiere precio actual y al menos 15 observaciones.",
    "limitations": [
      "Precios según variante del proveedor; no se verificaron ajustes corporativos.",
      "Confianza describe calidad de evidencia, no probabilidad de un pronóstico.",
      "Vigencia con tolerancia de días calendario; no certifica ausencia de ruedas faltantes ni cierre.",
      "Se requiere precio actual y al menos 15 observaciones.",
      "Quote no disponible o no válida; se conserva únicamente el historial.",
      "sma20: Requiere 20 observaciones; disponibles 14.",
      "sma50: Requiere 50 observaciones; disponibles 14.",
      "ema26: Requiere 26 observaciones; disponibles 14.",
      "rsi14: Requiere 15 observaciones; disponibles 14.",
      "macd: Requiere 26 observaciones; disponibles 14.",
      "macd_signal: Requiere 34 observaciones; disponibles 14.",
      "macd_histogram: Requiere 34 observaciones; disponibles 14."
    ]
  },
  "fundamental": {
    "status": "NOT_REQUESTED",
    "metrics": null,
    "history_only_metrics": null,
    "assessment": null,
    "narrative_origin": null,
    "evidence": [],
    "interpretation": "",
    "limitations": []
  },
  "integrated_view": {
    "agreements": [],
    "conflicts": [],
    "risks": []
  },
  "data_quality": {
    "missing_information": [
      "Métricas verificables suficientes",
      "Vigencia con tolerancia de días calendario; no certifica ausencia de ruedas faltantes ni cierre.",
      "Se requiere precio actual y al menos 15 observaciones."
    ],
    "stale_data": false,
    "abstentions": [
      "technical"
    ]
  },
  "sources": [
    "https://market.test/api/stocks/GGAL/history?range=6M&market=bCBA"
  ],
  "trace_id": "6b987ecc-d17a-45fb-b728-5d20629285e5",
  "session_id": "3d27acfc-de1c-4108-8b6a-0c82a306f767",
  "errors": []
}
```

## Fallo técnico

Caso `http503`. Snapshot y SQLite en `evals/results/technical-v1-20260916T215304/verified-technical-fake/http503/`.

```json
{
  "status": "ERROR",
  "ticker": "GGAL",
  "company_name": "Grupo Financiero Galicia",
  "analysis_type": "technical",
  "as_of": null,
  "executive_summary": "Un fallo técnico no recuperado impidió completar el análisis; se conservan los datos disponibles.",
  "generation": {
    "mode": "FAILED",
    "llm_status": "NOT_USED",
    "provider": null,
    "requested_model": null,
    "model": null,
    "model_version": null,
    "attempts": 0,
    "retry_after_seconds": null,
    "model_fallback_used": false,
    "warnings": []
  },
  "technical": {
    "status": "SOURCE_ERROR",
    "metrics": null,
    "history_only_metrics": null,
    "assessment": {
      "status": "SOURCE_ERROR",
      "signals": {},
      "trend": "UNAVAILABLE",
      "momentum": "UNAVAILABLE",
      "momentum_state": "UNAVAILABLE",
      "confirmation": "UNAVAILABLE",
      "completion_reasons": [],
      "basis": {
        "history_as_of": null,
        "indicators_as_of": null,
        "history_fetched_at": null,
        "history_closure": "UNVERIFIED",
        "quote_as_of": null,
        "quote_observed_at": null,
        "quote_fetched_at": null,
        "quote_price": null,
        "quote_provisional": false,
        "quote_in_indicators": false,
        "policy": "HISTORY_ONLY"
      },
      "conclusion": "UNAVAILABLE",
      "confidence": "UNAVAILABLE",
      "as_of": null,
      "fetched_at": null,
      "freshness": "UNKNOWN",
      "missing_indicators": {},
      "agreements": [],
      "conflicts": [],
      "warnings": [
        "La fuente de precios falló; no hay una nueva lectura técnica validada."
      ]
    },
    "narrative_origin": "deterministic",
    "evidence": [],
    "interpretation": "La fuente de precios falló; no hay una nueva lectura técnica validada.",
    "limitations": [
      "Precios según variante del proveedor; no se verificaron ajustes corporativos.",
      "Confianza describe calidad de evidencia, no probabilidad de un pronóstico.",
      "No hay observaciones de mercado utilizables.",
      "La fuente de precios falló; no es insuficiencia estadística."
    ]
  },
  "fundamental": {
    "status": "NOT_REQUESTED",
    "metrics": null,
    "history_only_metrics": null,
    "assessment": null,
    "narrative_origin": null,
    "evidence": [],
    "interpretation": "",
    "limitations": []
  },
  "integrated_view": {
    "agreements": [],
    "conflicts": [],
    "risks": []
  },
  "data_quality": {
    "missing_information": [
      "Métricas verificables suficientes",
      "No hay observaciones de mercado utilizables."
    ],
    "stale_data": false,
    "abstentions": []
  },
  "sources": [],
  "trace_id": "6da1c985-2b94-49ad-b114-53898dce96ef",
  "session_id": "f03beab4-55ce-44f4-b979-661c0ea7e5a4",
  "errors": [
    {
      "code": "EXTERNAL_SERVICE",
      "message": "External service failed",
      "retryable": true
    }
  ]
}
```
