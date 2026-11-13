# Imágenes de la documentación

Aquí viven **todas** las imágenes del documento. Cada capítulo tiene su propia
carpeta para que nadie pise los archivos de otro.

```
figuras/
├── compartidas/       logo, iconos y lo que se use en varios capítulos
├── 01_introduccion/
├── 02_arquitectura/
├── 03_instalacion/
├── 04_operacion/
├── 05_datos/
├── 06_referencia/
└── A_checklist/
```

## Reglas

1. **Cada imagen va en la carpeta de su capítulo.** Nada suelto en `figuras/`.
2. **Nombre en minúsculas, sin acentos ni espacios:**
   `flujo-deteccion.png` — no `Flujo Detección final(2).PNG`.
3. **Formatos:**
   - `.png` para capturas de pantalla y fotos.
   - `.pdf` o `.svg` para diagramas hechos con vectores (se ven nítidos a
     cualquier zoom).
   - Evitar `.jpg` para capturas con texto: se ve borroso.
4. **Tamaño:** capturas de hasta ~1600 px de ancho; optimizar antes de subir.
   Una imagen de más de 2 MB casi siempre se puede reducir sin perder nada.
5. **Sin datos sensibles:** nada de tokens, contraseñas, teléfonos reales ni
   personas identificables.

## Cómo insertarlas

La ruta que se escribe es **relativa a `figuras/`** y sin el prefijo `figuras/`:

```latex
\figura[0.8\linewidth]{02_arquitectura/flujo-deteccion.png}
        {Flujo completo de la detección}
        {fig:flujo-deteccion}
```

Si la imagen todavía no existe, deja el marcador (compila igual):

```latex
\figuraPendiente{02_arquitectura/flujo-deteccion.png}
                 {Flujo completo de la detección}
                 {fig:flujo-deteccion}
```

Y refiérela en el texto con `\ref{fig:flujo-deteccion}`.

## Diagramas

Los diagramas de flujo sencillos se hacen directo en TikZ dentro del capítulo
(ver `02_arquitectura.tex`): así se versionan como texto, se editan sin abrir un
editor gráfico y no pesan nada. Usar una imagen solo cuando el diagrama sea
demasiado complejo o sea una captura de pantalla.

## Antes de hacer commit

- [ ] La imagen está en la carpeta correcta.
- [ ] El nombre no tiene espacios, acentos ni mayúsculas.
- [ ] Tiene pie de figura y etiqueta en el capítulo.
- [ ] El documento compila (`make` en `documentacion/`).
