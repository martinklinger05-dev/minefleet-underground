# Auditoría técnica de MineFleet (noviembre de 2026)

Revisión del código publicado en `main` antes de la versión 2.0 (commit `2ba59d3`). Estado inicial: 12/12 pruebas aprobadas y resultados guardados idénticos a los descritos en el README. Se distinguen **defectos confirmados** (con evidencia en el código) de **riesgos revisados** sin defecto.

## Defectos confirmados

| # | Impacto | Evidencia (v1) | Corrección |
|---|---|---|---|
| 1 | Alto: modelo | `simulate`: el ciclo era `load → ramp_loaded → travel_loaded → dump → delivered → ramp_empty → travel_empty`. El cruce cargado ocurría junto al frente y el vacío junto a la descarga, de modo que una misma rampa estaba en dos lugares. | Secuencias coherentes en `STAGE_SEQUENCES` (`ramp_side`). Cambia resultados; v1 se conserva con `model_version: 1`. |
| 2 | Alto: integridad | `policy.py` y `tests/test_policy.py` no estaban en el repositorio. | Integrados y comprobados contra los resultados históricos (ver abajo). |
| 3 | Medio: estadística | `random.Random(seed*100003 + i)` por número de volquete. Al pasar de 3/3 a 4/2, el volquete 4 cambia de ruta y su flujo alimenta otra ruta: el emparejamiento entre alternativas es débil. No introduce sesgo. | Flujo por puesto (ruta, posición), con semilla de texto (SHA‑512, estable entre plataformas). |
| 4 | Medio: robustez | `write_dashboard`: `f"{x['cost_per_t']:.2f}"` falla cuando el costo es `None` (producción cero). | `fmt` muestra "—". Prueba `test_zero_production_exports_without_crashing`. |
| 5 | Medio: generalidad | `sensitivity.py` rechazaba flotas distintas de 6 y fijaba 4/2. El panel principal decía "flota de 6 equipos" sin importar el escenario. `reliability.py` imprimía solo base y 4/2. | Flota y asignación resaltada configurables (`--highlight`); textos generados desde el escenario. |
| 6 | Medio: validación | `validate` accedía con `c[key]`: una clave faltante daba `KeyError` y un texto en un campo numérico daba `TypeError`. `True` pasaba como número. `enabled` no se validaba. | Validación completa con mensajes en español; 16 casos inválidos probados. |
| 7 | Bajo: robustez | `events.csv` usaba `events[0]` para los encabezados (falla con lista vacía). Las escrituras eran secuenciales, así que un fallo dejaba resultados mezclados. | Encabezados fijos; escritura en temporales y luego reemplazo. |
| 8 | Bajo: seguridad HTML | Los nombres de ruta y otros textos no se escapaban (en v1 no se mostraban, pero el riesgo existía al ampliar los paneles). | `html.escape` en todos los textos configurables. |

## Riesgos revisados sin defecto

- **Orden temporal y reservas:** los eventos se procesan en orden cronológico (heap + contador), así que la reserva al llegar equivale a una cola FIFO por hora de llegada. La prueba de exclusión verifica que ningún recurso se use dos veces a la vez.
- **Reservas más allá del cierre:** no alteran los indicadores. Solo cuentan descargas terminadas hasta el minuto 450, y espera y utilización se recortan al horizonte. Nueva prueba: espera + servicio + viaje suman exactamente flota × 450 min.
- **Inicio en t = 0:** todos los volquetes empiezan vacíos en su frente y se forma cola en el carguío. Es un supuesto, no un error; está documentado (sin período de calentamiento).
- **Corte de guardia:** el caso manual de un volquete (21 min la primera descarga, luego cada 30 min, 375 t) se mantiene en v2.
- **Costo por tonelada:** es razón de medias (costo fijo / producción media), ahora indicado en el panel y en el código.
- **Experimento de rampa:** el código mantiene fijo el tiempo total de viaje y cambia la ocupación; la documentación lo explica así.

## Verificación de policy.py frente a los resultados v1 (1000 réplicas)

| Valor obtenido antes (v1) | Obtenido ahora |
|---|---|
| Rampa 2, 4/2: 1889,65 t; B 499,90 t; 996/1000; Wilson ≈ 99,0–99,8 % | 1889,65; 499,90; 996/1000; 98,98–99,84 % |
| Rampa 3, 4/2: B 486,025 t; 462/1000 | 486,025; 462/1000 |
| Umbral 0,95, rampa 2: mean → 3/3, frequency y wilson → 4/2 | igual |
| Umbral 0,95, rampa 3: los tres → 3/3 | igual |

## Hallazgo: la meta coincide con el techo del frente B

Con 2 volquetes, el frente B casi nunca supera 20 viajes por guardia (v1: 996 guardias en 500 t, 4 en 475 t, ninguna sobre 500 t; v2: 946 en 500 t, 1 en 525 t). La meta de 500 t es exactamente ese techo, así que la media no puede superarla y basta una demora para quedar debajo. Esto explica por qué la elegibilidad de 4/2 cambia con el número de réplicas (30 frente a 1000), con el criterio (media frente a frecuencia) y con la corrección de la rampa. Es una propiedad del escenario, no del muestreo, y se reporta sin ajustar metas ni semillas.

## Validación fuera de muestra

| Modelo | Rampa | Criterio | Elegida | Validación (semillas 1 000 000–1 000 999) |
|---|---|---|---|---|
| v2 | 2 y 3 min | los tres | 3/3 | 1000/1000 con ambas metas; elección estable |
| v1 | 2 min | frequency / wilson | 4/2 | 994/1000 (Wilson 98,7–99,7 %); B 499,85 t medias: sigue elegible por frecuencia, no por metas medias |

## Qué no se validó

- Ningún resultado se contrastó con datos operacionales; todo es interno al modelo.
- No se verificó que la ubicación `"dump"` de la rampa represente una mina concreta. Con `"load"`, la selección con rampa de 2 min también es 3/3 (B: 495,0 t con 4/2).
- No se ejecutó GitHub Actions con el workflow nuevo; se probó localmente con Python 3.11, 3.12 y 3.13, y la sintaxis se comprobó para 3.10.
- La forma triangular simétrica y el ±15 % son supuestos sin calibrar.
