# MineFleet — Asignación de volquetes en acarreo subterráneo
[![Tests](https://github.com/martinklinger05-dev/minefleet-underground/actions/workflows/tests.yml/badge.svg)](https://github.com/martinklinger05-dev/minefleet-underground/actions/workflows/tests.yml)

Proyecto de portafolio de Martin Klinger Castillo · Ingeniería de Minas, Universidad Católica de Santa María (Arequipa).

Simulador de eventos discretos en Python (solo biblioteca estándar) que evalúa asignaciones estáticas de volquetes a dos frentes que comparten una rampa y una descarga. **Todos los datos y resultados son simulados.** No es un sistema de despacho, no usa datos de una mina real y sus resultados no están validados operacionalmente.

**Paneles (sin instalar nada):**
[Resultado principal](https://martinklinger05-dev.github.io/minefleet-underground/results/dashboard.html) ·
[Rampa lenta](https://martinklinger05-dev.github.io/minefleet-underground/results_rampa_lenta/dashboard.html) ·
[Sensibilidad](https://martinklinger05-dev.github.io/minefleet-underground/results_sensitivity/dashboard.html) ·
[Cumplimiento por guardia](https://martinklinger05-dev.github.io/minefleet-underground/results_reliability/dashboard.html) ·
[Criterios de selección](https://martinklinger05-dev.github.io/minefleet-underground/results_policy/dashboard.html) ·
[Validación fuera de muestra](https://martinklinger05-dev.github.io/minefleet-underground/results_validation/dashboard.html)

> **Versión 2.0.** Una auditoría ([docs/AUDITORIA.md](docs/AUDITORIA.md)) encontró que en el modelo v1 la rampa ocupaba posiciones distintas en el viaje cargado y en el vacío. El modelo v2 corrige eso y **cambia los resultados**: la asignación 4/2 y la mejora de 5,39 % de la release v1.0.0 ya no se obtienen. Los resultados v1 siguen siendo reproducibles (ver [Trazabilidad](#trazabilidad-de-resultados-históricos)). Detalle en [CHANGELOG.md](CHANGELOG.md).

## Hallazgo principal

La meta de 500 t del frente B equivale exactamente a 20 viajes de 25 t, y **con 2 volquetes ese frente casi nunca puede hacer más de 20 viajes en la guardia**. La asignación 4/2 deja al frente B trabajando en su techo: cualquier demora lo deja en 475 t. Por eso su elegibilidad cambia con detalles del modelo, el número de réplicas y el criterio:

| Experimento | Frente B con 4/2 (media) | Guardias con ambas metas | Selección |
|---|---:|---:|---|
| v1, 30 réplicas (release v1.0.0) | 500,0 t | — | 4/2 (+5,39 %) |
| v1, 1000 réplicas | 499,90 t | 996/1000 | metas medias: 3/3 · frecuencia/Wilson ≥ 0,95: 4/2 |
| v2, 1000 réplicas (selección) | 498,68 t | 947/1000 | los tres criterios: 3/3 |
| v2, 1000 réplicas nuevas (validación) | 498,25 t | 931/1000 | se confirma 3/3 |

No se ajustaron metas, tolerancias ni semillas para cambiar estos resultados. La conclusión defendible no es "4/2 es mejor" ni "3/3 es mejor", sino que **4/2 está en el límite de capacidad del frente B** y la recomendación depende de cuánto riesgo de incumplir se acepte. Una frecuencia alta de cumplimiento puede coexistir con una media ligeramente bajo la meta: unas pocas guardias con 475 t bajan el promedio.

## Resultado principal (modelo v2, rampa de 2 min, 30 réplicas)

| Asignación A/B | t/guardia media | IC 95 % de la media | Media A / B (t) | Cumple metas medias |
|---|---:|---:|---:|:--:|
| 2/4 | 1694,17 | 1688,9 – 1699,5 | 702,5 / 991,7 | Sí |
| **3/3 (seleccionada y base)** | **1792,50** | 1786,9 – 1798,1 | 1045,0 / 747,5 | Sí |
| 4/2 | 1870,00 | 1863,3 – 1876,7 | 1372,5 / 497,5 | No |
| 5/1 | 1910,00 | 1905,3 – 1914,7 | 1660,0 / 250,0 | No |

La tabla completa (siete asignaciones), los tiempos por actividad y la utilización de recursos están en el panel y en `results/summary.json`. Costo supuesto de la base: S/ 3,766 por t (S/ 6750 por guardia ÷ producción media).

## Ejecutar

Requiere Python 3.10 o superior; no necesita instalar paquetes. Desde la carpeta que contiene `minefleet.py`:

```bash
python minefleet.py                                                       # resultado principal → results/
python minefleet.py --scenario data/scenario_rampa_lenta.json --out results_rampa_lenta
python sensitivity.py                                                     # rampa de 1 a 5 min → results_sensitivity/
python reliability.py                                                     # 1000 guardias por asignación → results_reliability/
python policy.py                                                          # criterios de selección → results_policy/
python validation.py                                                      # semillas nuevas → results_validation/
python -m unittest discover -s tests -v                                   # 32 pruebas
```

Otro umbral: `python policy.py --threshold 0.995 --out results_policy_995`. En Windows, para abrir un panel: `start results\dashboard.html`. La cadena completa tarda alrededor de medio minuto.

## Modelo

**Recursos:** un punto de carguío por frente (capacidad 1), una descarga compartida (capacidad 1) y un tramo de rampa compartido (capacidad 1, ambos sentidos). Colas FIFO por hora de llegada; empates por orden de inserción. El carguío es un recurso de servicio: **no hay un LHD modelado como equipo móvil** ni una red geométrica de labores.

**Ciclo (v2, `"ramp_side": "dump"`):** carguío → viaje cargado fuera de rampa → rampa → descarga → rampa → viaje vacío fuera de rampa → carguío. La rampa está en el tramo común junto a la descarga y ocupa la misma posición en ambos sentidos. Con `"ramp_side": "load"` queda junto a los frentes.

**Tiempos:** `loaded_min` y `empty_min` son el tiempo total de viaje e **incluyen** el cruce de rampa; el modelo resta `ramp_crossing_min` para obtener el tramo fuera de rampa. El cruce es fijo; carguío, descarga y viaje fuera de rampa siguen una triangular simétrica de ±`variability` (15 %).

**Guardia:** 450 min simulados (7,5 h, no una jornada completa). Todos los volquetes empiezan vacíos en su frente en t = 0, de modo que la guardia arranca con colas en el carguío (no hay período de calentamiento). Solo cuentan las descargas que terminan hasta el minuto 450; los ciclos incompletos no suman. Las reservas de recursos que pasan del cierre no afectan los indicadores: la producción, la espera y la utilización se recortan al horizonte.

**Números aleatorios:** cada réplica usa una semilla (`seed`, `seed + 1`, …). En v2 cada puesto (ruta, posición) tiene su propio flujo, de modo que el primer volquete de A recibe los mismos números en 3/3 y en 4/2. Esto mejora la comparación pareada, pero las alternativas **no** son muestras independientes entre sí.

**Selección:** se enumeran todas las asignaciones estáticas (0/6 … 6/0) y se elige la de mayor producción media entre las que cumplen las metas medias de ambos frentes. No es optimización dinámica ni aprendizaje automático.

**Costo:** flota × horas de guardia × costo por hora de volquete (6 × 7,5 × 150 = S/ 6750). El costo por tonelada es ese costo fijo dividido entre la producción media (razón de medias, no promedio de costos unitarios). No incluye combustible, personal, mantenimiento, carguío, infraestructura ni capital, y no permite estimar ahorros reales.

## Interpretación del experimento de rampa

Al aumentar `ramp_crossing_min` sin cambiar `loaded_min` ni `empty_min`, el tiempo nominal total de viaje sin colas **no cambia**: aumenta la ocupación del recurso compartido y disminuye el tramo fuera de rampa. Cambian las esperas y también la variabilidad, porque la rampa es fija y el resto aleatorio. No es "el viaje tarda un minuto más".

| Ocupación por cruce | Base 3/3 (t/guardia) | Selección por metas medias | Producción seleccionada |
|---|---:|---|---:|
| 1 min | 1825,83 | 4/2 | 1917,50 |
| 2 min | 1792,50 | 3/3 | 1792,50 |
| 3 min | 1655,00 | 3/3 | 1655,00 |
| 4 min | 1359,17 | 3/3 | 1359,17 |
| 5 min | 1100,83 | ninguna cumple ambas metas medias | — |

30 réplicas por asignación (modelo v2). Con rampa de 3 min, 4/2 deja al frente B en 462,5 t medias.

## Cumplimiento por guardia, criterios y validación

`reliability.py` simula 1000 guardias por asignación (semillas 2026–3025) y cuenta directamente las que cumplen **ambas** metas a la vez; no multiplica frecuencias marginales, porque los frentes comparten recursos.

| Rampa | A/B | Media (t) | Media B (t) | Ambas metas | Wilson 95 % |
|---|---|---:|---:|---:|---:|
| 2 min | 3/3 | 1795,62 | 746,77 | 1000/1000 | 99,6 – 100,0 % |
| 2 min | 4/2 | 1872,20 | 498,68 | 947/1000 | 93,1 – 95,9 % |
| 3 min | 3/3 | 1663,00 | 704,00 | 1000/1000 | 99,6 – 100,0 % |
| 3 min | 4/2 | 1690,45 | 463,52 | 0/1000 | 0,0 – 0,4 % |

`policy.py` aplica tres criterios alternativos sobre ese lote (no vuelve a simular):

- **mean**: la media de cada frente alcanza su meta.
- **frequency**: la frecuencia observada de guardias con ambas metas es ≥ umbral (0,95 por defecto).
- **wilson**: el límite inferior del intervalo de Wilson del 95 % de esa frecuencia es ≥ umbral.

Frecuencia y Wilson **sustituyen** el filtro de metas medias; no lo añaden. En v2, con umbral 0,95, los tres eligen 3/3 en ambas rampas. 4/2 no entra por frecuencia porque 947/1000 = 0,947 < 0,95, otra decisión en el límite.

`validation.py` simula un **lote nuevo** de 1000 guardias (semillas 1 000 000–1 000 999, sin solapamiento; el programa rechaza rangos que se crucen). El lote de selección solo sirve para elegir y el de validación solo para evaluar lo elegido. Resultado v2: 3/3 se confirma en ambas rampas con los tres criterios (1000/1000 guardias con ambas metas). El panel incluye la distribución de toneladas cerca de la meta: con 4/2 y rampa de 2 min, 94,6 % de las guardias del frente B quedan **exactamente** en 500 t y 5,3 % por debajo.

Limitaciones: el 95 % del umbral y el 95 % del intervalo son conceptos distintos. Los intervalos son individuales, sin corrección por comparaciones múltiples. Los porcentajes son estimaciones dentro del modelo, no probabilidades validadas en una mina. La validación usa el mismo modelo; no sustituye datos operacionales.

## Incorporar tiempos medidos (preparado, sin datos)

`data/tiempos_medidos_plantilla.csv` define el formato y está vacía a propósito. Columnas: `fecha, guardia, equipo, ruta, etapa, duracion_min, fuente, observaciones`. Las etapas válidas son `load`, `travel_loaded_total`, `dump`, `travel_empty_total` y `ramp_crossing`; los viajes totales incluyen la rampa y las esperas se excluyen.

```bash
python measured.py --input data/tiempos_medidos.csv                       # valida y resume (n, media, p10, p50, p90)
python measured.py --input data/tiempos_medidos.csv --write-scenario data/scenario_calibrado.json
```

El escenario calibrado solo se genera si cada tiempo tiene al menos 30 observaciones (`--min-n`). Reemplaza los tiempos nominales por las medias medidas y deja registro en `"calibration"`. No ajusta `variability` ni la forma de la distribución. Usar solo registros autorizados.

## Trazabilidad de resultados históricos

| Resultado | Cómo reproducirlo |
|---|---|
| Release v1.0.0 (4/2, 1890,00 t, +5,39 %) | `python minefleet.py --scenario data/scenario_v1_historico.json --out <carpeta>` |
| Rampa lenta v1 (3/3, 1722,50 t) | `python minefleet.py --scenario data/scenario_v1_historico_rampa_lenta.json --out <carpeta>` |
| Cumplimiento, criterios y validación v1 | carpeta [`results_v1_historico/`](results_v1_historico/) |

`"model_version": 1` reproduce exactamente el modelo anterior, y una prueba automática lo verifica. Los archivos originales de la release siguen en la [release v1.0.0](https://github.com/martinklinger05-dev/minefleet-underground/releases).

## Archivos

| Archivo | Contenido |
|---|---|
| `minefleet.py` | Simulación, validación de entradas, evaluación, selección y panel principal |
| `sensitivity.py` | Sensibilidad a la ocupación de rampa |
| `reliability.py` | Cumplimiento por guardia e intervalo de Wilson |
| `policy.py` | Criterios de selección: metas medias, frecuencia y Wilson |
| `validation.py` | Validación con semillas nuevas y análisis cerca de la meta |
| `measured.py` | Formato e ingreso de tiempos medidos |
| `data/` | Escenarios v2, copias v1 históricas y plantilla de tiempos |
| `results*/` | Resultados y paneles generados (JSON, CSV, HTML) |
| `tests/` | 32 pruebas automáticas |
| `docs/AUDITORIA.md` | Defectos encontrados, evidencia y correcciones |

## Verificación y límites

32 pruebas automáticas (8 originales adaptadas + 24 nuevas). Verifican exclusión de recursos, rampa en la misma posición en ambos sentidos, cobertura del tiempo de cada volquete, reproducción exacta de v1, validación de entradas, exportación con producción cero, escape de HTML, criterios, separación de semillas y formato de datos medidos. Las pruebas comprueban el código; no validan el modelo frente a una mina real.

Pendiente para una aplicación real: calibración con registros autorizados, ajuste de distribuciones, LHD y equipos heterogéneos, fallas y mantenimiento, cambio de guardia, geometría, pendientes y prioridades de tránsito, ventilación y costos detallados. No es una evaluación de seguridad.

## Explicación breve para una entrevista

«Modelé con eventos discretos la competencia de los volquetes por carguío, rampa y descarga, y evalué todas las asignaciones estáticas con simulación. Al auditar el modelo encontré que la rampa estaba en posiciones distintas a la ida y a la vuelta. Al corregirlo, la asignación que antes parecía mejor dejó de cumplir la meta del frente B: con dos volquetes ese frente está en su techo de 20 viajes, justo la meta. Separé los lotes de selección y de validación para comprobar que la elección no dependía de las semillas. Son datos simulados; el siguiente paso es calibrar con tiempos medidos.»
