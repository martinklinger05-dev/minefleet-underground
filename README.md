# MineFleet — Underground Haulage Optimization
[![Tests](https://github.com/martinklinger05-dev/minefleet-underground/actions/workflows/tests.yml/badge.svg)](https://github.com/martinklinger05-dev/minefleet-underground/actions/workflows/tests.yml)

**[Ver panel de resultados](https://martinklinger05-dev.github.io/minefleet-underground/results/dashboard.html)** — Resultados del escenario simulado, disponibles sin instalar Python.

Proyecto de portafolio de Martin Klinger Castillo · Ingeniería de Minas.

Simulador en Python de acarreo subterráneo y selección exhaustiva de asignaciones estáticas de volquetes. **Todos los datos y resultados incluidos son simulados.** Primera versión funcional; no es un sistema de despacho operacional ni una tesis validada.

## Resultado reproducible

Escenario de seis volquetes, dos frentes y una descarga; 30 réplicas por distribución.

| Indicador | Base: A=3, B=3 | Seleccionada: A=4, B=2 |
|---|---:|---:|
| Producción media (t/guardia) | 1793.33 | 1890.00 |
| Desviación estándar (t) | 13.02 | 14.08 |
| Costo supuesto (S/ por t) | 3.764 | 3.571 |
| Espera acumulada de la flota (min/guardia) | 162.23 | 159.95 |

Incremento de producción simulada: **5.39%**. La asignación 5/1 produce más toneladas totales, pero incumple la meta de 500 t medias del frente B. La selección es la mejor entre las siete asignaciones evaluadas que cumplen ambas metas medias. No garantiza el cumplimiento en cada réplica ni una mejora real en una mina.

## Ejecutar

Requiere Python 3.10 o superior. No necesita paquetes externos.

```bash
python minefleet.py
python -m unittest discover -s tests -v
```

Abrir `results/dashboard.html` en el navegador. Para servirlo localmente:

```bash
python -m http.server 8000 --directory results
```

Visitar http://localhost:8000/dashboard.html. Este panel presenta resultados; modificar `data/scenario.json` y ejecutar nuevamente para comparar otro escenario.

```bash
python minefleet.py --scenario data/scenario.json --out results
```

## Modelo de ingeniería

Cada volquete sigue: carguío → cruce de rampa cargado → resto del viaje cargado → descarga → cruce de rampa vacío → resto del retorno → carguío.

- Un recurso de carguío por frente, capacidad 1.
- Una descarga compartida, capacidad 1.
- Un tramo de rampa compartido, capacidad 1 en ambos sentidos.
- Colas FIFO según llegada; empate resuelto por orden de inserción del evento.
- Tiempos de carguío, descarga y viajes restantes con distribución triangular ±15% del valor nominal.
- Cruce fijo de 2 min, incluido dentro de los tiempos nominales de viaje; no se agrega de nuevo.
- Las esperas se generan por contención de recursos; no se añade una espera fija de 5 o 7 min.
- Inicio: todos los equipos vacíos y disponibles en su frente a tiempo cero.
- Solo cuentan cargas cuya descarga termina antes o exactamente al minuto 450. No se exige terminar el retorno para contabilizar mineral entregado.

Esta convención difiere del ejercicio inicial basado en ciclos completos. Los seis equipos se mantienen asignados durante toda la guardia; no hay despacho dinámico.

## Optimización y costos

Se enumeran n_A=0,…,6 y n_B=6−n_A. Se maximiza la producción media simulada, sujeta a metas medias por frente y rutas habilitadas. Cada opción usa las mismas semillas de réplica y flujos aleatorios independientes por equipo; la reasignación cambia la secuencia de eventos, por lo que esto no implica emparejamiento perfecto de ciclos entre opciones.

Costo de guardia = número de equipos × horas disponibles × costo por hora. El costo por tonelada publicado es costo fijo de guardia dividido entre producción media. Se supone S/150 por equipo-hora y se pagan los seis equipos durante las 7.5 h. Es un supuesto comparativo, no una estimación integral: no incluye desglose de combustible, mantenimiento, cargadores ni infraestructura.

## Archivos

- `minefleet.py`: simulación, evaluación, búsqueda y exportación.
- `data/scenario.json`: supuestos editables, unidades en minutos, toneladas y soles.
- `results/summary.json`: estadísticas y todas las alternativas.
- `results/events.csv`: trazabilidad de una réplica de la opción seleccionada. Puede incluir servicios programados más allá del cierre; esas descargas no cuentan.
- `results/dashboard.html`: panel autónomo.
- `tests/test_simulation.py`: ocho pruebas de invariantes y cálculo manual.
- `.github/workflows/tests.yml`: configuración para pruebas automáticas en GitHub.

## Verificación y límites

Pruebas locales: 8/8 aprobadas. Se verifica exclusión temporal de recursos, cantidad entregada, corte de guardia, reproducibilidad, restricciones, datos inválidos, caso sin solución y selección exhaustiva. Caso manual de un solo volquete: primera descarga en 21 min; siguientes cada 30 min; 15 viajes entregados = 375 t en 450 min.

Pendientes para una aplicación real: calibración con registros autorizados, validación independiente, distribución empírica de tiempos, fallas, cambios de guardia, geometría y pendientes, múltiples cruces, prioridades de tránsito, restricciones de ventilación, heterogeneidad de equipos y costos detallados. La rampa es un recurso abstracto ubicado antes del resto del viaje en ambos sentidos; no representa la geometría de una ruta específica. No equivale a una evaluación de seguridad.

La selección usa las mismas réplicas para elegir y reportar resultados; puede presentar sesgo de selección. Para tesis, separar réplicas de evaluación fuera de muestra, analizar incertidumbre y sensibilidad y validar contra una operación real. Los 30 escenarios por opción son una demostración, no un tamaño muestral científicamente justificado.

## Publicar en GitHub

Crear un repositorio llamado `minefleet-underground`, extraer este paquete y subir su contenido (README y minefleet.py deben quedar en la raíz). No subir datos empresariales confidenciales.

Descripción sugerida: "Underground mining haulage simulator in Python: discrete-event queues, static fleet allocation, reproducible experiments and operating cost comparison."

Este paquete no está publicado todavía. La automatización incluida se ejecutará cuando se suba a GitHub; únicamente se han ejecutado las pruebas locales en el entorno disponible.

## Explicación para una entrevista

«El proyecto representa la competencia de los volquetes por carguío, rampa y descarga con eventos discretos. Evalúa cada distribución y selecciona la de mayor producción media que cumple las metas por frente. Con datos simulados, pasar de 3/3 a 4/2 incrementó 5.39% la producción media. El resultado depende de los supuestos y requiere calibración antes de aplicarlo en campo».

Proyecto desarrollado con asistencia de IA. Para presentarlo como evidencia de competencias propias, revisa y ejecuta el código y asegúrate de poder explicar el modelo, sus supuestos y sus límites.
