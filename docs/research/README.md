# Conversaciones con usuarios

Tres conversaciones con personas de una boutique de wealth management en Lima, una por cada rol que toca el KYC. No conseguí a nadie del área comercial; la visión comercial la cubre el Head of Wealth Management.

| # | Rol | Notas |
|---|---|---|
| 1 | Head of Wealth Management (estrategia y negocio) | [`01_head_wealth_management.md`](01_head_wealth_management.md) |
| 2 | Back Office (redacta los KYC) | [`02_back_office.md`](02_back_office.md) |
| 3 | Compliance Trainee (riesgo y debida diligencia) | [`03_compliance_trainee.md`](03_compliance_trainee.md) |

## Qué aprendí

- **El tiempo.** Un KYC sencillo toma de 1 a 2 horas de trabajo efectivo, y Back Office hace varios al mes. Los casos complejos toman varios días. La demora retrasa el onboarding y afecta la experiencia comercial.
- **Lo más pesado:** repetir búsquedas, contrastar datos y trasladar información de distintas fuentes a un mismo documento (Back Office), y decidir si una coincidencia corresponde de verdad al cliente (Compliance).
- **Los tres coinciden en que validar el patrimonio no tiene fórmula:** "predomina el criterio". Comparan ingresos, trayectoria, antigüedad, empresas vinculadas y patrimonio declarado.
- **Qué piden del producto:**
  - un informe profesional y fácil de leer, que sirva de respaldo formal del onboarding (Head);
  - un borrador editable con fuentes identificadas (Back Office);
  - enlaces verificables, fecha de consulta, separación entre coincidencias confirmadas y falsos positivos, la justificación de cada alerta y evidencia para auditoría (Compliance).
- **Quién compra:** Compliance y la dirección. Pagarían si reduce horas y riesgos de compliance; Compliance ve viable una suscripción mensual. Nadie dio un monto.

## Cómo responde el producto

| Pedido o dolor | Qué hace KYC OSINT |
|---|---|
| Repetir búsquedas y trasladar datos a un documento | Una corrida busca, organiza y redacta el borrador en Word, que se puede editar |
| ¿Esta coincidencia es el cliente? | Puntaje de identidad por fuente, con su razón; los homónimos quedan descartados pero registrados |
| No hay fórmula para el patrimonio | Monto tope plausible con la ENAHO 2024 y supuestos visibles, comparado con lo declarado |
| Fuentes verificables y justificación de cada alerta | Cada afirmación lleva su cita [n] con enlace; cada regla de riesgo deja su razón y sus puntos |
| Identificar alertas rápido | Semáforo de riesgo, tipo de DD y factores en la primera pantalla |
| Fecha de consulta y evidencia para auditoría | Descarga de evidencia en JSON: enlace, fecha de publicación, fecha de consulta y extracto de cada fuente, con la huella SHA-256 que la une al Word |
| Respaldo formal del onboarding | Word con el manual de marca y bloque de decisión y firmas (elaborado, revisado, aprobado) |
| Separar coincidencias confirmadas de falsos positivos | Hoy lo hace el puntaje de identidad. Pendiente: que el analista confirme o descarte cada una |
