---
name: merval_equity_analysis
description: Analizar acciones BYMA con datos trazables, cálculos determinísticos y abstención ante evidencia insuficiente.
---

# Merval equity analysis

Decidí una acción por turno según el pedido y las observaciones. No sigas una secuencia fija.
Resolvé primero ticker, compañía e instrumento; pedí aclaración ante ambigüedad, múltiples
empresas o ADR versus acción local. La cobertura inicial es bCBA.

Determiná intent technical, fundamental o full. Por defecto un pedido general es full.
Murphy indica metodología técnica; Graham indica fundamental. Ambos requieren full.
Conservá el objetivo durante la ejecución. Podés consultar metodología antes o después de datos.
Usá errores y evidencia faltante para cambiar la siguiente acción, ampliar un rango o abstenerte.
No repitas llamadas fallidas indefinidamente.

Política de horizonte: sin horizonte especificado, consultá
`DEFAULT_TECHNICAL_RANGE` en `merval_agent/domain/policy.py` (actualmente 6M).
Ese intervalo permite reunir muestra para SMA50 y análisis intermedio; no garantiza
suficiencia. Es la única fuente ejecutable del default del simulador. Los pedidos técnicos
ordinarios no requieren búsqueda de libros. Usá technical_assessment, calculado por Python,
para separar suficiencia, tendencia y momentum; COMPLETE/PARTIAL permiten describir señales.

Separá DATO, METODOLOGÍA, INTERPRETACIÓN y LIMITACIONES. Cada dato debe conservar fuente y
fecha; la interpretación debe referenciar evidencia disponible. Nunca calcules porcentajes,
indicadores ni ratios: usá tools determinísticas. No produzcas BUY/SELL ni recomendaciones
categóricas. No copies cifras nuevas en la interpretación: las métricas pertenecen al contrato.
La narrativa técnica final se construye desde las señales deterministas; reason e interpretation
del provider no se publican como afirmaciones financieras verificadas.

No presentes demo/unknown como live. No confundas score de retrieval con verdad. Las notas
locales DEMO no son citas ni recuperación de Murphy/Graham. Para conclusiones atribuidas a
estos autores hacen falta fuentes verificadas; si faltan, abstenerse en esa dimensión.
Un PDF listado no implica balance extraído. En Fase 1 la dimensión fundamental se abstiene
de concluir sobre solidez o valoración. En bancos usar a futuro métricas bancarias, no filtros
industriales como current ratio. No ejecutar efectos externos: futuras propuestas HITL quedan PAUSED.

Consultá [contratos](references/contracts.md) para decisiones y respuestas;
[tools](references/tools.md) para selección y precondiciones;
[ejemplos](examples/requests.md) para ambigüedad y evidencia insuficiente.
