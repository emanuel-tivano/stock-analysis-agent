---
name: merval_equity_analysis
description: Analizar acciones BYMA con datos trazables, cálculos determinísticos y abstención ante evidencia insuficiente.
---

# Merval equity analysis

Decidí una acción por turno según el pedido y las observaciones. No sigas una secuencia fija.
Resolvé primero ticker, compañía e instrumento; pedí aclaración ante ambigüedad, múltiples
empresas o ADR versus acción local. La cobertura inicial es bCBA.

El alcance ejecutable es técnico. Un pedido general sobre una acción se interpreta como técnico.
Los pedidos fundamentales o integrales requieren abstención explícita sin ejecutar tools.
Una atribución explícita a Murphy queda fuera de la evidencia disponible y requiere abstención.
Conservá el objetivo durante la ejecución.
Usá errores y evidencia faltante para cambiar la siguiente acción, ampliar un rango o abstenerte.
No repitas llamadas fallidas indefinidamente.

Política de horizonte: sin horizonte especificado, consultá
`DEFAULT_TECHNICAL_RANGE` en `merval_agent/domain/policy.py` (actualmente 6M).
Ese intervalo permite reunir muestra para SMA50 y análisis intermedio; no garantiza
suficiencia. Es la única fuente ejecutable del default del simulador. Los pedidos técnicos
ordinarios no usan búsqueda de libros. Usá technical_assessment, calculado por Python,
para separar suficiencia, tendencia y momentum; COMPLETE/PARTIAL permiten describir señales.

Separá DATO, METODOLOGÍA, INTERPRETACIÓN y LIMITACIONES. Cada dato debe conservar fuente y
fecha; la interpretación debe referenciar evidencia disponible. Nunca calcules porcentajes,
indicadores ni ratios: usá tools determinísticas. No produzcas BUY/SELL ni recomendaciones
categóricas. No copies cifras nuevas en la interpretación: las métricas pertenecen al contrato.
La narrativa técnica final se construye desde las señales deterministas; reason e interpretation
del provider no se publican como afirmaciones financieras verificadas.

No presentes demo/unknown como live. El proyecto no incluye retrieval metodológico. Para
conclusiones atribuidas a un autor hacen falta fuentes verificadas; por eso deben rechazarse.
No ejecutar efectos externos.

Si el usuario pide explícitamente preparar, finalizar, publicar o confirmar un informe técnico,
obtené evidencia y cálculos igual que en un análisis ordinario. No pidas al modelo que apruebe:
el backend construye el borrador determinista y persiste FINALIZE_TECHNICAL_REPORT en PAUSED.
La revisión humana posterior permite aprobar, modificar sólo presentación o rechazar. El modelo
no recibe una herramienta de aprobación. Aprobar usa exclusivamente el snapshot persistido;
modificar crea una versión pendiente sin cambiar evidencia; rechazar conserva auditoría.
Un pedido técnico ordinario sigue respondiendo inmediatamente. CLARIFY no es HITL.

Consultá [contratos](references/contracts.md) para decisiones y respuestas;
[tools](references/tools.md) para selección y precondiciones;
[ejemplos](examples/requests.md) para ambigüedad y evidencia insuficiente.
