# Evaluación con personas sintéticas

Modelo `claude-opus-5-5`. 5/5 casos correctos. Costo total US$ 0.45.

| Caso | Riesgo | DD | PEP | Declarado/tope | Falló en | OK | US$ | s |
|---|---|---|---|---|---|---|---|---|
| 1 · Creador de contenido que opina de política (ruido alto, riesgo bajo) | bajo | simplificada | no | 0.07 | — | ✅ | 0.095 | 28 |
| 2 · Contadora limpia con un homónimo sentenciado (debe descartarse) | medio | estándar | no | 0.64 | — | ✅ | 0.089 | 29 |
| 3 · Ex gerente de un gobierno regional (PEP → DD reforzada) | alto | reforzada | si | 0.19 | — | ✅ | 0.096 | 28 |
| 4 · Empresario con investigación fiscal por lavado (riesgo alto) | alto | reforzada | no | 0.35 | — | ✅ | 0.097 | 29 |
| 5 · Comerciante formal que declara muy por encima de su tope (pedir sustento) | alto | reforzada | no | 7.29 | — | ✅ | 0.076 | 23 |

Los nombres, las fuentes y los hechos son ficticios (ver `fixtures/`).
