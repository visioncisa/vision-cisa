# Problema: correcciones silenciosas en `validar_numero`

**Estado:** documentado y verificado; **producción sin modificar** (pendiente de aprobación, tarea P4.3).
**Archivo:** `ml/reconocimiento.py:83` · **Lo llama:** `ml/hilos.py` `HiloM2M3._leer_bus` (línea ~499)
**Prueba que fija el comportamiento actual:** `tests/test_validar_numero_produccion.py` (15 casos)

## 1. Qué hace hoy

Cuando M3 lee un número que **no está en el padrón**, la función intenta "corregirlo" con tres reglas fijas:

| Lectura | Regla | Ejemplo verificado |
|---|---|---|
| 3 dígitos que empiezan con 5 | Inserta un `0`: `5XY` → `50XY` | `508` → **5008** |
| 3 dígitos que no empiezan con 5 | Antepone un `5`: `XYZ` → `5XYZ` | `063` → **5063** |
| 4 dígitos que no empiezan con 5 | Cambia el primer dígito por `5` | `0063` → **5063**, `9063` → **5063** |

Si el resultado existe en el padrón, se acepta como si se hubiera leído así. Solo queda un `print("[CORREGIDO] …")` en el log; en la base de datos **no queda registro** de la lectura original.

## 2. Por qué es un problema

1. **Inventa unidades.** Con el padrón de ejemplo de la prueba, las **63 de 63** combinaciones de 4 dígitos probadas (que no empiezan con 5 y cuyos 3 últimos dígitos son de una unidad 50xx) terminan registradas como una unidad del padrón.
2. **Caso real (18 nov 2026):** un camión de CDMX con la calcomanía `0063` se registró como la unidad **5063**, en estado *VERIFICADO*. El error no se ve en el tablero porque el número sí existe.
3. **Lecturas parciales:** si a `5051` se le "cae" el último dígito, M3 lee `505` y la regla lo convierte en **5005**: otra unidad que sí existe. En Roboflow hay recortes de la 5051 que producción leyó como `505` (p. ej. `20261015_133952_289_505_t9.jpg`).
4. **Contamina las métricas:** estancias, entradas y salidas de unidades que no pasaron, y faltantes de las que sí pasaron.
5. **La confianza no lo delata:** en la muestra revisada, las lecturas erróneas tenían confianza de 0.58 a 0.72, igual que las correctas.

## 3. Qué lo mitiga hoy (parcialmente)

`ml/hilos.py` ya tiene dos defensas, que **no cubren todos los casos**:
- `_leer_bus`: si el mismo camión se lee **4 o más veces** (`VOTOS_FUERA_PADRON`) con un número de 4 dígitos fuera del padrón, se ignora la corrección (así se arregló COPATTSA 2508). Un camión que pasa rápido o se lee pocas veces no llega a 4.
- `_elegir_numero`: si un número corto está "contenido" en uno largo (504 dentro de 5014), gana el largo. No aplica cuando la corrección produce un número de 4 dígitos.

## 4. Cómo medir su impacto (sin tocar producción)

En la Jetson, solo lectura:
```bash
cd ~/Documents/ProyectoVisionCISA_R
docker compose logs cisa-vision 2>&1 | grep -o "\[CORREGIDO\] [0-9]* → [0-9]*" | sort | uniq -c | sort -rn | head -30
```
Esto da cuántas correcciones hubo y cuáles. Para saber cuántas fueron **falsas**, se revisan las fotos de evidencia de esos eventos (`/api/detecciones` → `fotos`). Como el log solo guarda lo reciente, conviene repetir la medición una semana.

## 5. Propuesta de corrección (NO aplicada)

En orden, del menor al mayor riesgo:

1. **Registrar la lectura cruda**: agregar `numero_crudo` a `evento_paso` (o al menos al log estructurado) para auditar cada corrección.
2. **Flag `CORREGIR_LECTURAS`** en `config.py`/`.env`, con valor por defecto `1` (igual que hoy):
   - `1` = comportamiento actual.
   - `0` = una lectura fuera del padrón se trata como "fuera del padrón" (igual que COPATTSA), no se corrige.
3. **Corrección más estricta** (alternativa intermedia): corregir solo cuando el primer dígito leído es `0`-`9` **y** el mismo camión produjo la versión corregida en otra lectura, o exigir más votos para un número corregido que para uno leído tal cual.
4. Mandar las correcciones a revisión del validador humano, en lugar de aprobarlas directo.

### Plan de prueba antes de activarla
1. Línea base: correr v3 con el video de canary (P0.3) y contar falsos *VERIFICADO*.
2. Repetir con `CORREGIR_LECTURAS=0`.
3. Comparar los falsos verificados (deben bajar) contra las unidades que dejan de reconocerse (no deben subir). Ambos números se reportan antes de pedir la aprobación para producción.
4. Actualizar `tests/test_validar_numero_produccion.py`: las pruebas de corrección **deben fallar** cuando cambie el comportamiento, a propósito, para que el cambio sea consciente.
