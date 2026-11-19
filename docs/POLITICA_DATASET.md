# Política del dataset

## 1. Qué entra al dataset

Cada recorte recibe una de tres decisiones (`reentrenamiento/seleccion.py`, umbrales en `reentrenamiento/config_reentrenamiento.yaml`):

| Decisión | Significado | Qué hace la persona |
|---|---|---|
| **revisar** | Caso difícil: el modelo actual duda o se equivoca | Corregir las cajas con cuidado |
| **conservar** | Representante de una pasada sin problemas | Revisión por muestreo (10 %) |
| **descartar** | No aporta | No se sube |

### Criterios para descartar

| Razón | Regla (valor por defecto) |
|---|---|
| `mala_calidad:borrosa` | Varianza del Laplaciano < 15 (con el recorte a 96 px de alto) |
| `mala_calidad:oscura` | Brillo medio < 25 |
| `mala_calidad:sobreexpuesta` | Brillo medio > 235 |
| `mala_calidad:sin_contraste` | Desviación estándar del gris < 12 |
| `mala_calidad:pequena` | Lado menor < 20 px (igual que `BBOX_MIN_POR_TIPO['lateral']`) |
| `mala_calidad:ilegible` | El archivo no se puede abrir |
| `redundante` | dHash a menos de 6 bits de un recorte ya elegido de la misma pasada |
| `cupo_pasada` | La pasada ya tiene 3 elegidos |
| `pasada_facil_fuera_de_muestra` | Pasada sin nada difícil que no cayó en el 20 % de control |
| `tope_total` | Se pasó `max_total` (si se configuró) |

### Criterios para mandar a revisión (caso difícil)

| Razón | Regla |
|---|---|
| `sin_digitos` | El modelo no detectó ningún dígito |
| `digitos_raros` | Detectó una cantidad distinta de 3 o 4 |
| `desacuerdo` | Su lectura no coincide con el consenso de la pasada |
| `baja_conf` | Algún dígito con confianza < 0.50 |
| `sistema_distinto` | Producción registró otro número (p. ej. corrigió "0063" a "5063") |
| `fuera_padron` | La lectura no está en el padrón |
| `condicion_nueva` | Luz de noche (brillo < 70) o contraluz |
| `calidad_dudosa` | Nitidez entre 15 y 40: legible, pero difícil |

> El 20 % de control de pasadas fáciles evita que el dataset tenga **solo** casos difíciles; si no, el modelo podría empeorar en lo que hoy hace bien.

## 2. Reglas de etiquetado (iguales para todos)

**M3 · Dígitos**
- **Caja** (tecla `B`), no polígono. Una caja por dígito, pegada al dígito.
- Clase = el dígito (`0`–`9`). El orden lo calcula el código (de izquierda a derecha).
- Dígito cortado o tapado más de la mitad: **no** se etiqueta.
- Recorte ilegible incluso para una persona: se marca como *null* (sin objetos) o se borra del lote.
- Calcomanías que no son el número económico (tarifa "$30", placas, números de CDMX como "122") **no** se etiquetan.
- Números de otras empresas (COPATTSA 25xx, CDMX 00xx): **sí** se etiquetan si son números económicos; el modelo lee dígitos, no empresas.

**M2 · Zona del número**: `delantero` (parabrisas o frente), `lateral` (costado), `trasera`. Una caja que cubra el número completo con su placa.

**M1 · Autobús**: `Autobus` y `Unidades` según la definición del dataset original (`Autobuses-2` en Roboflow). La caja cubre el vehículo completo visible.

**Orden de clases**: obligatorio el de `reentrenamiento/clases.py`. Producción se guía por el número de clase (el `.engine` pierde los nombres). `validar` y `entrenar` se detienen si el orden no coincide.

**Aumentos en Roboflow**: brillo, exposición, desenfoque y ruido sí. **Volteo horizontal no** en M3 (un dígito volteado ya no es el mismo dígito) ni en M2 (cambia la geometría de la zona).

## 3. Control de calidad de etiquetas

1. Una segunda persona revisa el **10 %** del lote al azar.
2. Si encuentra más del **5 %** de imágenes con errores, **se devuelve el lote completo**.
3. `python -m reentrenamiento validar` antes de cada entrenamiento: clases, coordenadas, polígonos, archivos huérfanos, **fuga entre splits** y clases con menos de 20 ejemplos.
4. Los errores que muestra `evaluacion.md` ("Ejemplos de lecturas equivocadas") se revisan: a veces la etiqueta es la que está mal.

## 4. Conjunto de evaluación independiente

- `dividir --congelado congelado_mX.txt` crea el set de prueba la primera vez y **lo reutiliza siempre**.
- Las pasadas del test congelado nunca entran a entrenamiento.
- Para ampliarlo (p. ej. aparece una condición nueva), se crea un **congelado nuevo con otro nombre** y se evalúan **ambos**. El viejo no se edita, para que los números sigan siendo comparables.
- Se versiona en el repo (`experimentos/congelado_m3.txt`); son nombres de pasada, no imágenes.

## 5. Almacenamiento y privacidad

- **Nunca** van a git: imágenes, videos, datasets, pesos, `.env`, sesión de WhatsApp (ver `.gitignore`).
- Las imágenes muestran a personas del patio: los proyectos de Roboflow deben ser **privados** (hoy M1, M2 y M3 están en *Public*).
- Retención en la Jetson: grabaciones 72 h (automático). Recortes: sin límite hoy → ver [MANTENIMIENTO.md](MANTENIMIENTO.md).
