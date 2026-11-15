# `ingresos_ocupacion_edad.csv`: ingreso laboral anual por ocupación y edad (ENAHO 2024)

Esta tabla agregada usa `kyc/wealth.py` para estimar el patrimonio laboral plausible de
un cliente. Ese patrimonio es la suma de los ingresos de cada año de su carrera, tomados
en un percentil dado, multiplicada por una tasa de ahorro y capitalizada.

**En el repo solo va esta tabla.** Los microdatos (`datos/`) no se suben nunca.

## Fuente

| | |
|---|---|
| Encuesta | INEI, Encuesta Nacional de Hogares (ENAHO) 2024 |
| Módulo | 05, "Empleo e Ingresos" (código de encuesta 966 en el portal de microdatos) |
| Archivo | `enaho01a-2024-500.dta` (85 992 registros y 1 425 variables) |
| URL | <https://proyectos.inei.gob.pe/iinei/srienaho/descarga/STATA/966-Modulo05.zip> |
| Descargado | 15/11/2026 (`Last-Modified` del servidor: 17/05/2025) |
| SHA-256 del ZIP | `462e4e08475c4107f7af261178c9ac492f0fa4239455ae2d765f4c14e176bb0f` |

## Cómo regenerarla

```bash
uv run --no-project --with pandas --with pyreadstat python -I scripts/build_enaho_table.py
```

Si el `.dta` no está, el script descarga el ZIP en `datos/zip/` y lo descomprime en
`datos/enaho2024_mod500/`. Antes de extraer, rechaza cualquier ruta absoluta o con `..`.
Con `--dta RUTA` se puede usar un `.dta` ya descargado.

## Universo y filtros

| Paso | Registros |
|---|---:|
| Registros del módulo 500 | 85 992 |
| Ocupados (`ocu500 == 1`) | 58 579 |
| + residentes habituales: `(p204 == 1 & p205 == 2) \| (p204 == 2 & p206 == 1)` | 57 684 |
| + 18 años o más (`p208a >= 18`) | 55 509 |
| + ingreso laboral anual > 0 (**universo final**) | **50 264** |

- El filtro de residentes habituales es el que usa el INEI en sus indicadores de empleo.
- Se excluyen 5 245 ocupados con ingreso laboral igual a 0. El 97,7 % son trabajadores
  familiares no remunerados (`p507 == 5`). Se excluyen porque un cliente de wealth
  management siempre tiene ingresos, y con ellos los percentiles bajarían de forma
  artificial en los grupos 6 y 9.
- Población ponderada del universo final: **16,3 millones** de personas.
- Factor de expansión: `fac500a`. En el diccionario figura como "Factor de Expansión de
  Empleo/Ingresos proyecciones CPV-2007".

## Ingreso laboral anual

Es la suma, para cada persona, de las variables derivadas del INEI que se listan abajo.
El INEI ya las entrega anualizadas. Los valores faltantes cuentan como 0. Es la misma
construcción del "ingreso proveniente del trabajo" que se usa con la ENAHO.

| Variable | Ocupación | Concepto | Tipo |
|---|---|---|---|
| `i524a1` | principal | Dependiente: ingreso total (bruto, antes de descuentos de ley e impuestos), incluye horas extras, bonificaciones, refrigerio, movilidad y comisiones | imputada, anual |
| `d529t` | principal | Dependiente: pagos en especie (alimentos, vestido, transporte, vivienda, salud, otros) | deflactada, anual |
| `i530a` | principal | Independiente: ganancia neta | imputada, anual |
| `d536` | principal | Independiente: valor de los productos de su negocio usados para consumo propio (autoconsumo) | deflactada, anual |
| `i538a1` | secundaria | Dependiente: ingreso total | imputada, anual |
| `d540t` | secundaria | Dependiente: pagos en especie | deflactada, anual |
| `i541a` | secundaria | Independiente: ganancia neta | imputada, anual |
| `d543` | secundaria | Independiente: autoconsumo | deflactada, anual |
| `d544t` | ambas | Ingresos extraordinarios de los últimos 12 meses: gratificaciones, bonificaciones, CTS, participación de utilidades, etc. | deflactada, anual |

Los nombres y las etiquetas se verificaron en el `.dta` y en `Diccionario2024.pdf`.
Para el ingreso en especie y los extraordinarios solo existe la versión deflactada
(`d*`). No se incluyen rentas de capital (`d557t`), transferencias ni pensiones (`d556t*`),
porque aquí solo interesa el ingreso por trabajo.

## Agrupación

- **`grupo_cno`**: gran grupo de la Clasificación Nacional de Ocupaciones 2015 (CNO 2015).
  Sale de `p505r4` (ocupación principal, CNO 2015) como `p505r4 // 1000`. `p505r4` es
  numérico, así que los códigos militares y policiales (gran grupo 0) perdieron el cero
  inicial y quedaron con 3 dígitos: 111, 220, etc. Los nombres de los grupos 0 a 9 son
  los de la CNO 2015.
- **`grupo_edad`**: `p208a` agrupada en `18-24`, `25-34`, `35-44`, `45-54`, `55-64` y `65+`.
  Además, cada gran grupo tiene una fila `todas` con todas las edades de 18 años en adelante.

## Columnas

| Columna | Descripción |
|---|---|
| `grupo_cno` | int, de 0 a 9 |
| `grupo_cno_nombre` | nombre del gran grupo según la CNO 2015 |
| `grupo_edad` | `18-24` … `65+`, o `todas` |
| `n_obs` | observaciones muestrales, sin ponderar |
| `poblacion` | personas representadas (suma de `fac500a`) |
| `p50`, `p75`, `p90`, `p95`, `p99` | percentiles ponderados del ingreso laboral **anual**, en soles corrientes de 2024, redondeados al sol |

Los percentiles ponderados siguen la regla de Stata `_pctile [pw=]`. Se toma el primer
valor cuya masa acumulada de `fac500a` supera q·W, y si la iguala exactamente, se promedia
con el valor siguiente.

## Reglas de uso

- **Respaldo**: si la celda (grupo × edad) tiene `n_obs < 30` o no existe, se usa la fila
  `todas` de su grupo. Hoy hay 5 celdas con `n_obs < 30`: grupo 0 (edades 18-24 y 55-64)
  y grupo 1 (edades 18-24, 25-34 y 65+). Hay una celda que no existe: grupo 0 con 65+,
  porque no hay militares ni policías ocupados de esa edad en la muestra.
- **p95 y p99** son inestables en celdas con menos de 200 observaciones. Con n ≈ 30, el
  p99 es casi el máximo muestral. Por ejemplo, el p99 del grupo 0 con 45-54 es S/ 242 822,
  mientras que su p95 es S/ 60 559. En celdas chicas conviene usar el p95 de la celda o el
  p99 de la fila `todas`.
- Las cifras son anuales. Para obtener un monto mensual, se divide entre 12.

## Chequeo de cordura

Sobre el universo final:

- Mediana ponderada del ingreso laboral **mensual**: **S/ 1 255**. Supera ligeramente la
  remuneración mínima vital de 2024 (S/ 1 025), algo coherente con un país de alta
  informalidad.
- Media: **S/ 1 662**. p90: **S/ 3 326**.
- Con el universo amplio (ocupados de 14 años o más, residentes, incluidos los que tienen
  ingreso 0), la media es S/ 1 522 y la mediana S/ 1 151. La prensa, citando al INEI,
  reportó un ingreso laboral promedio nacional de alrededor de S/ 1 766 al mes para 2024.
  Esa cifra puede venir de otra encuesta (la EPEN) o usar otra definición. La diferencia,
  entre 6 % y 14 %, es razonable.

## ⚠️ Advertencia: la ENAHO subestima los ingresos altos

La ENAHO es una encuesta de hogares. Mide bien el centro de la distribución y mal la cola
superior, que es justo la que importa para clientes de wealth management.

- **Los hogares ricos casi no aparecen**: tienen más tasa de rechazo y de no respuesta,
  y los condominios cerrados son difíciles de encuestar.
- **Hay subdeclaración**: los ingresos altos, sobre todo los de independientes y
  empleadores, se reportan por debajo de su valor real.
- **Hay pocas observaciones en la cola**: en toda la muestra, el ingreso anual máximo
  de un dependiente en su ocupación principal (`i524a1`) es S/ 300 181. En los registros
  tributarios aparecen ingresos laborales muy superiores.
- **Solo es ingreso laboral**: no incluye rentas de capital, herencias, venta de empresas
  ni ingresos del cónyuge.

Por eso, en `kyc/wealth.py` estos percentiles deben leerse como un **piso conservador** de
lo que puede acumular un profesional de altos ingresos, no como un techo. Un patrimonio
declarado por encima del monto calculado no es sospechoso por sí solo. Indica que hay que
pedir sustento del origen de fondos, como herencia, venta de un negocio o inversiones.
