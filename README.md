# KYC OSINT

> **Hacemos borradores de KYC para boutiques de wealth management en el Perú mediante un agente que cruza listas de sanciones, fuentes públicas peruanas y un estimador de patrimonio: en un minuto y con cada hallazgo citado.**

[![pruebas](https://github.com/luyov-belli/KYC_OSINT/actions/workflows/tests.yml/badge.svg)](https://github.com/luyov-belli/KYC_OSINT/actions/workflows/tests.yml)

Proyecto final de *Data Science con Python* (Universidad del Pacífico, 2026-II) · [issue #205](https://github.com/d2cml-ai/Data-Science-Python/issues/205)

**Demo:** [kyc-osint.streamlit.app](https://kyc-osint.streamlit.app/) · **Video de respaldo:** _pendiente_

---

## 1. One-liner

Hacemos **borradores de KYC** para **boutiques de wealth management en el Perú** mediante **un agente que cruza listas de sanciones, fuentes públicas peruanas y un estimador de patrimonio con la ENAHO**.

## 2. Founder

**Adrián Luyo.** Estudio Economía en la Universidad del Pacífico (octavo ciclo) y trabajo desde hace cuatro meses como *investment operations trainee* en una boutique de wealth management en Lima. En una firma pequeña cada persona asume funciones fuera de su puesto: mi compañero de Back Office redacta los KYC de los prospectos a partir de su propia investigación, una tarea que en rigor es de Compliance. Lo veo desde operaciones: mientras el KYC no está listo, el onboarding no avanza y el cliente espera.

## 3. Problema

**Quién lo sufre.** Boutiques de wealth management, SAF, SAB y family offices en el Perú. Antes de abrir una cuenta deben conocer al cliente: quién es, si es PEP, si figura en listas de sanciones, si tiene noticias adversas y si su patrimonio tiene un origen coherente. En una firma pequeña lo hace alguien de Back Office o de compliance, a mano, googleando.

**Cuánto cuesta.** Según las tres conversaciones:

- Un KYC sencillo toma **de 1 a 2 horas de trabajo efectivo** de Back Office, que hace varios al mes. Los casos complejos toman **varios días**: estructuras societarias, beneficiarios finales, origen de los fondos.
- Lo más pesado es repetir búsquedas, contrastar datos y trasladarlos a un mismo documento (Back Office), y decidir si una coincidencia corresponde de verdad al cliente (Compliance).
- La demora **retrasa el onboarding** y afecta la experiencia comercial (Head of Wealth Management).

**Cómo se resuelve hoy.** Búsquedas manuales en Google, Infogob, El Peruano y medios; listas OFAC y ONU consultadas a mano; el criterio de "¿tiene sentido este patrimonio?" queda en la cabeza de quien revisa: en las tres conversaciones, validar el patrimonio es "criterio", no un cálculo estandarizado. Las bases globales (World-Check de LSEG, Dow Jones Risk & Compliance, ComplyAdvantage) son caras para una boutique y entregan coincidencias sueltas, no un borrador.

**Evidencia:** notas de 3 conversaciones (Head of Wealth Management, Back Office y Compliance) y lo que aprendí de ellas, en [`docs/research/`](docs/research/).

## 4. Solución e insight

Escribes el nombre del lead y sus datos declarados. En un minuto sale un **borrador de KYC en Word** con:

- **Listas de sanciones** OFAC SDN y ONU, con coincidencia difusa y umbral visible.
- **Perfil, PEP y noticias adversas** desde fuentes públicas peruanas, cada afirmación con su cita [n].
- **Espectro de evidencia:** cada fuente recibe dos puntajes, *¿es la misma persona?* y *¿pesa para el riesgo?*. Las opiniones en redes y los homónimos no contaminan el análisis, pero quedan registrados.
- **Monto tope plausible:** con cuánto dinero, como máximo, podría venir este cliente según su ocupación, edad y negocio (ENAHO 2024 + Ley MYPE + tipo de cambio del BCRP), comparado con lo que declara.
- **Nivel de riesgo y tipo de debida diligencia** (simplificada, estándar o reforzada) con reglas explícitas.

**Insight.** El cuello de botella del KYC no es encontrar información, sino **separar lo relevante del ruido** y **juzgar si el patrimonio tiene sentido**. Por eso el LLM solo juzga y redacta; los números (monto tope) y la decisión de riesgo los hacen reglas transparentes que un oficial de cumplimiento puede revisar y defender ante el regulador.

Las conversaciones lo confirman: para Compliance lo más difícil es saber si una coincidencia corresponde al cliente, y los tres entrevistados dicen que validar el patrimonio no tiene fórmula.

## 5. Why now

- **LLMs con búsqueda web y salidas estructuradas.** Hace tres años un modelo no podía buscar en la web, leer 15 fuentes y devolver un JSON validado con puntajes por fuente. Hoy una sola llamada lo hace por centavos.
- **Datos públicos abiertos y con API:** OFAC (Sanctions List Service), la ONU (XML), la API del BCRP y los microdatos de la ENAHO del INEI se descargan en segundos.
- **Costo:** un informe cuesta menos de un dólar en API, frente a horas de un analista.

## 6. Demo

**URL pública:** [kyc-osint.streamlit.app](https://kyc-osint.streamlit.app/) (Streamlit Community Cloud). El modo sintético está abierto; el modo en vivo pide un código de acceso.

- **Modo sintético (abierto):** cinco personas ficticias con evidencia ficticia: un creador de contenido que opina de política sin ser PEP, una contadora con un homónimo sentenciado, un ex funcionario regional (PEP), un empresario con investigación fiscal por lavado y una comerciante que declara muy por encima de su tope. Sus resultados están precalculados en [`fixtures/resultados/`](fixtures/resultados/): se muestran al instante y sin costo de API.
- **Modo en vivo (con código de acceso):** busca en fuentes públicas reales. Está protegido para que nadie use la URL pública para perfilar a terceros. En la presentación corre sobre mi propio perfil.
- **Simular otro monto:** después de generar un informe, cambias el monto declarado y se recalculan al instante el monto tope, la coherencia, el riesgo y el tipo de DD. Es Python puro: no vuelve a llamar al modelo ni cuesta API. El texto del borrador conserva el monto original, y una nota lo advierte.

**Correrlo en local**

```bash
git clone https://github.com/luyov-belli/KYC_OSINT.git && cd KYC_OSINT
cp .env.example .env        # completar ANTHROPIC_API_KEY y KYC_ACCESS_CODE
uv sync
uv run streamlit run app.py
```

Pruebas sin API: `uv run pytest` (corren en GitHub Actions en cada push). Evaluación con los sintéticos: `uv run python scripts/eval_synthetic.py` ([resultados](docs/eval_sinteticos.md)).

**Capturas:** _pendiente (3)_.

**Arquitectura:** ver [`docs/architecture.md`](docs/architecture.md).

```mermaid
flowchart LR
    A[Formulario] --> B[Sanciones<br/>OFAC + ONU] --> C[OSINT<br/>Claude + búsqueda web] --> D[Extracción<br/>identidad × relevancia]
    D --> E[Monto tope<br/>ENAHO + BCRP] --> F[Reglas de riesgo] --> G[Borrador KYC .docx]
```

**Modelos y APIs, y por qué**

| Qué | Para qué | Por qué |
|---|---|---|
| Claude Opus 5.5 (`claude-opus-5-5`), API de Anthropic | Búsqueda, extracción y redacción | Búsqueda web del servidor y salidas estructuradas con una sola key; buen español; razona sobre homónimos |
| Herramientas `web_search` / `web_fetch` del servidor | OSINT | Sin otra key ni scraper propio; respeta los sitios que bloquean bots |
| OFAC SDN + ALT (CSV) y ONU (XML) | Sanciones | Fuentes oficiales y gratuitas |
| ENAHO 2024, módulo 500 (INEI) | Monto tope | Única fuente pública de ingresos por ocupación y edad en el Perú |
| API del BCRP (serie PD04640PD) | Tipo de cambio | Convierte montos en dólares con el dato oficial del día |

## 7. Modelo de negocio

- **Quién paga:** boutiques de wealth management, SAF, SAB y family offices. Según los tres entrevistados, la compra la deciden Compliance y la dirección.
- **Precio:** **S/ 990 al mes** con 30 informes (la suscripción mensual que Compliance vio viable) o **S/ 49 por informe** suelto. Nadie dio un monto en las conversaciones: es una hipótesis anclada a las 1-2 horas de Back Office que ahorra cada KYC.
- **Costo por informe (medido con `usage` de la API):**
  - **En vivo:** ~US$ 0.43 (≈ S/ 1.5). Son 5 búsquedas web (US$ 0.05), ~51 mil tokens de entrada y ~9 mil de salida con Claude Opus 5.5. Tarda entre 75 y 95 s.
  - **Sintético:** ~US$ 0.09 por informe al generarlo (sin búsqueda web) y ~25 s ([evaluación](docs/eval_sinteticos.md): 5/5 casos correctos). Mostrarlo desde el resultado guardado: US$ 0.
  - **Simular otro monto:** US$ 0 (reglas en Python).
  - **Servidor:** S/ 0 en Streamlit Community Cloud.
  - **Margen bruto:** con S/ 49 por informe, el costo variable es ~3 % del precio.
- **Qué sigue:** piloto en mi firma; fecha de consulta por fuente y paquete de evidencia para auditoría (pedidos de Compliance); que el analista confirme o descarte cada coincidencia; plantilla de KYC de cada cliente; más fuentes peruanas (Poder Judicial, SUNARP con convenio) y monitoreo periódico.

## 8. Herramientas del curso

Las dos principales son las que hacen el KYC: **Scraping y APIs (03)** trae los datos que exige el regulador y **LLMs con salidas estructuradas (08)** convierte texto desordenado en evidencia auditable. **Dashboards (05)** y **Despliegue y evaluación (12)** ponen el producto en una URL pública y miden que funcione.

| Herramienta | Sesión | Dónde | Para qué |
|---|---|---|---|
| **LLMs con salidas estructuradas** | 08 | [`kyc/llm.py`](kyc/llm.py), [`kyc/schemas.py`](kyc/schemas.py) | Claude devuelve JSON validado con pydantic: un puntaje de identidad y otro de relevancia por fuente, la condición PEP y las señales de patrimonio. Luego redacta el borrador citando cada fuente [n] |
| **Scraping y APIs** | 03 | [`kyc/sanctions.py`](kyc/sanctions.py) (OFAC en CSV, ONU en XML), [`kyc/wealth.py`](kyc/wealth.py) (API del BCRP en JSON), [`kyc/osint.py`](kyc/osint.py) (búsqueda web) | Ingesta de las listas oficiales de sanciones, el tipo de cambio y las fuentes públicas peruanas |
| Dashboards con Streamlit | 05 | [`app.py`](app.py) | El producto: formulario, semáforo, gráfico identidad × relevancia, monto tope, simulación de monto y descarga del Word |
| Despliegue y evaluación | 12 | Streamlit Community Cloud con secrets, [`scripts/eval_synthetic.py`](scripts/eval_synthetic.py), [`tests/`](tests/), [`.github/workflows/tests.yml`](.github/workflows/tests.yml), `UsageTracker` en [`kyc/llm.py`](kyc/llm.py) | URL pública con código de acceso; set de prueba con 5 casos sintéticos y su resultado esperado ([5/5](docs/eval_sinteticos.md)); costo por token medido en cada informe; pruebas en integración continua en cada push |

**Por qué estas:** un KYC necesita datos oficiales (listas de sanciones, tipo de cambio, fuentes públicas) y criterio para separar lo relevante del ruido. Las APIs resuelven lo primero. Las salidas estructuradas resuelven lo segundo sin perder trazabilidad: cada juicio del modelo queda como un puntaje con su razón y su fuente, que el código valida y las reglas usan. Streamlit y el despliegue lo ponen en manos de un oficial de cumplimiento sin instalar nada, y la evaluación muestra que acierta y cuánto cuesta.

**Precisiones:**
- **Sin Selenium.** La búsqueda web la hace la herramienta del servidor de Claude. Lo propio de la sesión 03 aquí es descargar y leer CSV, XML y JSON de fuentes oficiales.
- **Un solo paso agéntico, a propósito.** El paso OSINT es un agente con herramientas y límites (hasta 5 búsquedas y 1 lectura de página), pero no usa crewAI ni coordina varios agentes: el resto del flujo es determinista para que sea auditable.
- **La ENAHO es una fuente de datos, no una skill.** El ingreso por ocupación y edad sale del módulo 500 de la ENAHO 2024 (INEI), procesado con [`scripts/build_enaho_table.py`](scripts/build_enaho_table.py) en [`data/ingresos_ocupacion_edad.csv`](data/ingresos_ocupacion_edad.csv).

## 9. Qué hizo el agente

Construido con **Claude Code** a lo largo del 15 y 16 de noviembre de 2026.

**Yo (Adrián):**

- Elegí el problema desde mi trabajo y definí el criterio de compliance: los filtros, la idea de un espectro de relevancia en vez de un sí o no, y la del monto tope. Limité el alcance a residentes en el Perú y definí el umbral de US$ 500 mil para la DD reforzada.
- Decidí cómo mostrarlo: mi propio caso más personas sintéticas en vez de figuras públicas, el código de acceso del modo en vivo, guardar los resultados sintéticos y simular el monto en vez de pagar otra corrida.
- Hice las 3 conversaciones con usuarios.
- Creé el repo, la API key con tope de gasto y el despliegue en Streamlit Community Cloud con sus secrets.
- Validé el resultado: probé mi caso en vivo, revisé que el monto tope tuviera sentido con la ENAHO, detecté que el gasto de la consola de Anthropic no cuadraba con mi cuenta y lo reconciliamos, revisé qué herramientas del curso usa el producto y definí la paleta de la interfaz.

**Claude Code:** propuso la arquitectura y la priorización; escribió el código de `kyc/`, `app.py`, los scripts, las pruebas, la integración continua, los cinco fixtures sintéticos (el primero, a partir de mi idea de un creador de contenido que opina de política) y el procesamiento de la ENAHO (en una sesión paralela); y redactó el primer borrador de este README.

---

## Riesgos, límites y base legal

- **Asiste, no decide.** El borrador lo revisa y firma un oficial de cumplimiento.
- **Solo fuentes públicas.** Sin logins, sin captchas, sin redes que lo prohíban.
- **Datos personales.** En producción, la base legal sería la obligación de debida diligencia del sujeto obligado y el uso de fuentes de acceso público (Ley 29733; a validar con asesoría legal). Para este curso, el demo en vivo corre solo sobre mi propio perfil, y los demás casos son sintéticos. Los informes en vivo no se guardan.
- **Monto tope.** La ENAHO subestima los ingresos altos: el tope sirve para pedir sustento, no para rechazar.
- **Homónimos.** Con nombres comunes, la calidad depende de los desambiguadores (DNI, edad, ciudad, empleador).
