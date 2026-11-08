# Registro de cambios

## 2.0.0 — auditoría y validación (noviembre de 2026)

### Cambios que modifican resultados
- **Rampa coherente (modelo v2).** En v1, el cruce cargado ocurría al salir del frente y el cruce vacío al salir de la descarga, es decir, en extremos opuestos del recorrido. Ahora ocupa la misma posición en ambos sentidos (`ramp_side`, por defecto `"dump"`: tramo común junto a la descarga).
- **Números aleatorios por puesto.** El flujo aleatorio se asigna por (ruta, posición) y no por número de volquete, para que las asignaciones comparadas compartan números en cada ruta.
- Efecto: con rampa de 2 min y 30 réplicas, la selección pasa de 4/2 (1890,00 t, +5,39 %) a 3/3 (1792,50 t). El frente B con 4/2 baja de 500,0 a 497,5 t medias. Con rampa de 1 min, 4/2 sigue siendo la selección (1917,50 t).
- `"model_version": 1` reproduce exactamente los resultados v1. Escenarios: `data/scenario_v1_historico*.json`.

### Correcciones sin efecto en los resultados
- El panel ya no falla cuando el costo por tonelada es indefinido (producción cero).
- La exportación de eventos funciona con una lista vacía.
- Validación de entradas con mensajes en español: claves faltantes, tipos, booleanos, NaN, infinitos, negativos, `variability`, rutas cerradas, nombres repetidos y rampa mayor que el viaje.
- Los textos configurables (nombres de ruta) se escapan antes de insertarlos en HTML.
- Exportación en dos pasos (temporales y luego reemplazo) para no dejar resultados mezclados si algo falla.
- `sensitivity.py` y `reliability.py` ya no exigen 6 volquetes ni fijan 4/2.
- Empate en la selección: asignación lexicográficamente menor, como antes, ahora explícito.

### Nuevo
- Intervalo del 95 % de la media, diferencia pareada frente a la base, desglose de tiempos (carguío, rampa, viaje, descarga, espera) y utilización de recursos.
- `policy.py`: criterios de selección (metas medias, frecuencia, Wilson), integrado en el repositorio. Reproduce los resultados obtenidos antes con el modelo v1.
- `validation.py`: validación con semillas nuevas sin solapamiento, estabilidad de la elección y distribución de toneladas cerca de la meta.
- `measured.py` y `data/tiempos_medidos_plantilla.csv`: formato para incorporar tiempos medidos.
- `results_v1_historico/`: cumplimiento, criterios y validación con el modelo v1.
- Pruebas: de 12 a 32.
- Workflow: `actions/checkout@v6` y `actions/setup-python@v6` (Node 24). Además de las pruebas, ejecuta la cadena completa con pocas réplicas.

## 1.0.0
- Primera versión publicada: simulador, selección exhaustiva, panel, 8 pruebas. Luego se añadieron rampa lenta, sensibilidad y cumplimiento por guardia (12 pruebas).
