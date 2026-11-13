# Documentación de CISA

Carpeta de la documentación técnica del proyecto **CISA — Control de unidades por
visión**. Aquí vive el documento escrito en LaTeX, sus imágenes y todo lo
necesario para compilarlo. El resultado es un PDF único:
`CISA-documentacion.pdf`.

> **Regla de oro:** si cambias el comportamiento del sistema, cambia también la
> documentación en el mismo *pull request*. La documentación es parte del
> código, no un extra.

---

## 1. Qué hay en esta carpeta

```
documentacion/
├── README.md                 este archivo: cómo trabajar aquí
├── main.tex                  documento maestro (SOLO ordena, no lleva texto)
├── Makefile                  atajos: make, make ver, make limpio
├── latexmkrc                 configuración de compilación
├── .gitignore                ignora los archivos generados
│
├── capitulos/                el escrito, un archivo por capítulo
│   ├── 00_portada.tex
│   ├── 01_introduccion.tex
│   ├── 02_arquitectura.tex
│   ├── 03_instalacion.tex
│   ├── 04_operacion.tex
│   ├── 05_datos.tex
│   ├── 06_referencia.tex
│   ├── A_checklist.tex
│   └── ...                   un archivo por capítulo
│
├── figuras/                  TODAS las imágenes, separadas por capítulo
│   ├── compartidas/          logo, iconos, imágenes de varios capítulos
│   ├── 01_introduccion/
│   ├── 02_arquitectura/
│   ├── 03_instalacion/
│   ├── 04_operacion/
│   ├── 05_datos/
│   ├── 06_referencia/
│   ├── A_checklist/
│   └── LEEME.md              reglas para nombrar y usar imágenes
│
├── estilos/
│   └── cisa.sty              paquetes, colores, cajas y comandos propios
│
├── plantillas/
│   └── capitulo-nuevo.tex    plantilla para empezar un capítulo
│
├── bibliografia/
│   └── referencias.bib       fuentes citadas (BibTeX)
│
├── build/                    (se crea al compilar; NO se sube a Git)
└── CISA-documentacion.pdf    (se crea al compilar; NO se sube a Git)
```

### Para qué sirve cada cosa

| Archivo / carpeta | Función |
|---|---|
| `main.tex` | Une portada, índices y capítulos. Casi nunca se toca: solo para registrar un capítulo nuevo. |
| `capitulos/*.tex` | El texto real. Cada capítulo es independiente: se puede editar sin tocar a los demás. |
| `figuras/<capítulo>/` | Espacio propio de cada capítulo para sus imágenes. Así nadie pisa los archivos de otro. |
| `estilos/cisa.sty` | El estilo del documento. Si necesitas un paquete o un comando nuevo, va aquí. |
| `plantillas/` | Punto de partida para no empezar de cero. |
| `bibliografia/` | Fuentes en formato BibTeX. |
| `build/` | Archivos intermedios de LaTeX. Se borra sin miedo. |

---

## 2. Instalar lo necesario (una sola vez)

Se necesita una distribución de LaTeX con `pdflatex` y `latexmk`:

```bash
# Ubuntu / Debian (instala lo básico + los paquetes que usa el documento)
sudo apt install texlive-latex-recommended texlive-latex-extra \
                 texlive-lang-spanish texlive-fonts-recommended latexmk

# macOS
brew install --cask mactex-no-gui
```

Comprobar que quedó instalado:

```bash
pdflatex --version
latexmk --version
```

En **Windows** se instala [MiKTeX](https://miktex.org/) o TeX Live y se usa
`latexmk` desde la terminal de MiKTeX.

**No hace falta instalar nada si se usa Overleaf** (ver sección 6).

---

## 3. Compilar el documento

Desde esta carpeta:

```bash
cd documentacion
make            # compila y deja CISA-documentacion.pdf
make ver        # compila y abre el PDF
make limpio     # borra los archivos intermedios
```

Equivalente sin `make`:

```bash
latexmk -pdf main.tex
```

El PDF final queda en `documentacion/CISA-documentacion.pdf` y una copia en
`build/main.pdf`.

### Compilar con VS Code (recomendado)

1. Instalar la extensión **LaTeX Workshop**.
2. Abrir `main.tex` y pulsar **Ctrl+Alt+B** (compilar) o **Ctrl+Alt+V** (ver).
3. Si LaTeX Workshop no encuentra `latexmk`, revisar que esté en el `PATH`.

### Compilar en Overleaf

1. Subir el contenido de `documentacion/` como proyecto (sin `build/`).
2. En *Menu → Compiler* elegir **pdfLaTeX**.
3. En *Menu → Main document* elegir `main.tex`.
4. Al bajar cambios de Git, volver a subir **solo** los archivos que cambiaron.

> El documento está pensado para **pdfLaTeX**. No cambiar a XeLaTeX o LuaLaTeX
> sin avisar: el estilo usa codificación T1 y fuentes Latin Modern.

---

## 4. Flujo de trabajo con Git

### 4.1 Antes de escribir

```bash
git pull                      # traer lo último de main
git checkout -b docs/mi-tema  # rama propia, no trabajar en main
```

Usar nombres de rama claros: `docs/arquitectura`, `docs/operacion-camara`,
`docs/corregir-tabla-env`.

### 4.2 Mientras se escribe

- Editar **solo** los archivos de tu tema: tu capítulo y tus imágenes.
- Compilar seguido (`make`) para no acumular errores.
- Si dos personas tocan el mismo capítulo, avisar en el grupo antes de seguir.

### 4.3 Al terminar

```bash
make                            # debe compilar sin errores
git add capitulos/02_arquitectura.tex figuras/02_arquitectura/flujo.png
git commit -m "docs(arquitectura): explica la votación de números"
git push -u origin docs/mi-tema
```

Después se abre el *pull request* contra `main`. Mensajes de commit sugeridos:

| Prefijo | Cuándo |
|---|---|
| `docs(<capítulo>): ...` | Texto nuevo o corregido |
| `fig(docs): ...` | Imagen nueva o reemplazada |
| `fix(docs): ...` | Error de compilación o errata |
| `style(docs): ...` | Formato, sin cambiar el contenido |

### 4.4 Revisión antes de aprobar un PR

- [ ] `make` compila sin errores (los *warnings* se revisan, no se ignoran).
- [ ] Lo que dice el documento coincide con el código actual.
- [ ] Las imágenes están en `figuras/<capítulo>/`, no sueltas.
- [ ] No se subieron `build/`, `*.aux`, `*.log` ni el PDF.
- [ ] No se subieron `.env`, `datos/` ni `whatsapp/sesion/`.

---

## 5. Cómo escribir

### 5.1 Agregar un capítulo nuevo

1. Copiar la plantilla:
   ```bash
   cp plantillas/capitulo-nuevo.tex capitulos/07_mi-capitulo.tex
   ```
2. Editar el título y el contenido.
3. Registrarlo en `main.tex`, **en el orden** en que debe aparecer:
   ```latex
   \input{capitulos/07_mi-capitulo}
   ```
4. Crear su carpeta de imágenes:
   ```bash
   mkdir -p figuras/07_mi_capitulo && touch figuras/07_mi_capitulo/.gitkeep
   ```

### 5.2 Agregar una imagen

1. Guardarla en la carpeta del capítulo:
   `figuras/02_arquitectura/flujo-deteccion.png`
2. Insertarla con el comando del estilo:
   ```latex
   \figura[0.8\linewidth]{02_arquitectura/flujo-deteccion.png}
           {Flujo completo de la detección}
           {fig:flujo-deteccion}
   ```
3. Referenciarla en el texto:
   ```latex
   Como muestra la figura~\ref{fig:flujo-deteccion}, ...
   ```

Si todavía no tienes la imagen, deja un marcador visible (compila igual):

```latex
\figuraPendiente{02_arquitectura/flujo-deteccion.png}
                 {Flujo completo de la detección}
                 {fig:flujo-deteccion}
```

**Reglas de las imágenes**

- Nombre en minúsculas, sin acentos ni espacios: `flujo-deteccion.png`,
  no `Flujo Detección final(2).PNG`.
- Prefijo del capítulo en la carpeta, nunca todas sueltas en `figuras/`.
- Preferir `.png` para capturas y `.pdf`/`.svg` para diagramas vectoriales.
- Capturas de pantalla: recortar lo que no aporta y no superar ~1600 px de ancho.
- Toda figura lleva **pie de figura** que explique qué se ve, y **etiqueta**
  (`\label`) para poder referenciarla.

### 5.3 Comandos que ya existen

| Comando | Para qué |
|---|---|
| `\path{ruta/al/archivo.py}` | Rutas y nombres de archivo. Respeta los `_` y corta la línea en las `/`. |
| `\texttt{texto}` | Código corto. **Escapar los guiones bajos**: `\texttt{VAR\_NAME}`. |
| `\figura[ancho]{carpeta/archivo}{pie}{label}` | Insertar figura. |
| `\figuraPendiente{archivo}{descripción}{label}` | Marcador de figura que falta. |
| `\begin{nota} ... \end{nota}` | Caja azul de información. |
| `\begin{aviso} ... \end{aviso}` | Caja amarilla de advertencia. |
| `\begin{peligro} ... \end{peligro}` | Caja roja de riesgo. |
| `\begin{lstlisting}[language=bash, caption={...}, label={...}]` | Bloque de código. |
| `\ref{...}`, `\cite{...}` | Referencias cruzadas y bibliografía. |

Ejemplo de código:

```latex
\begin{lstlisting}[language=bash, caption={Arranque del sistema},
                   label={lst:arranque}]
docker compose up -d
docker compose ps
\end{lstlisting}
```

Para citar una fuente, agregarla a `bibliografia/referencias.bib` y usar
`\cite{clave}` en el texto.

### 5.4 Estilo de escritura

- Español neutro, impersonal: «se registra», no «yo registro».
- Frases cortas. Una idea por párrafo.
- Explicar el **porqué** de las decisiones, no solo el qué.
- Comandos y nombres de archivo siempre en `\path{}` o `\texttt{}`.
- Números con unidad: «30 px», «60 s», «65 GB».
- Nada de capturas con datos personales, números de teléfono reales ni tokens.

### 5.5 Etiquetas (labels)

Usar prefijos para no chocar entre capítulos:

| Prefijo | Para |
|---|---|
| `cap:` | Capítulo (`cap:arquitectura`) |
| `sec:` | Sección (`sec:variables`) |
| `fig:` | Figura (`fig:flujo`) |
| `tab:` | Tabla (`tab:env`) |
| `lst:` | Código (`lst:arranque`) |

Si dos personas usan la misma etiqueta, LaTeX avisa con
«multiply-defined labels».

---

## 6. Problemas frecuentes

| Mensaje / síntoma | Causa | Solución |
|---|---|---|
| `Undefined control sequence` | Comando mal escrito o paquete que no se cargó | Revisar el nombre; si es un paquete nuevo, agregarlo en `estilos/cisa.sty`, no en el capítulo. |
| `Missing $ inserted` | Un `_` sin escapar dentro de `\texttt{}` | Escribir `\_` o usar `\path{}`. |
| `File ... not found` | Ruta de imagen incorrecta | La ruta es relativa a `figuras/` y sin `figuras/` al inicio. |
| `Reference ... undefined` | La etiqueta no existe o falta compilar dos veces | Ejecutar `make` otra vez; `latexmk` lo hace solo. |
| `\url used in a moving argument` | `\path` dentro de un `\caption` o `\section` | Usar `\texttt{}` en títulos y pies. |
| El PDF no se actualiza | Se abrió `build/main.pdf` en vez del final | Abrir `CISA-documentacion.pdf`. |
| `make: latexmk: command not found` | Falta LaTeX | Ver sección 2. |

Si nada funciona, compilar limpio:

```bash
make todo-limpio && make
```

---

## 7. Qué NO se sube a Git

- `build/` y cualquier `*.aux`, `*.log`, `*.toc`, `*.bbl`.
- El PDF final (`CISA-documentacion.pdf`): se regenera con `make`. Si alguien lo
  necesita sin compilar, se lo comparte por otro medio.
- Fotos con personas identificables o datos sensibles sin autorización.
- Archivos de más de ~10 MB. Optimizar antes de hacer commit.

---

## 8. Responsabilidades

| Tema | Responsable |
|---|---|
| Estilo, `main.tex` y compilación | *(nombre)* |
| Capítulo de arquitectura | *(nombre)* |
| Capítulo de instalación y operación | *(nombre)* |
| Capítulo de datos | *(nombre)* |

> Completar esta tabla al inicio del semestre. Si alguien no aparece, la
> responsabilidad por omisión es del equipo completo.

Ante cualquier duda de LaTeX, revisar primero esta guía y la documentación de
[Overleaf](https://www.overleaf.com/learn). Si el problema es del sistema y no
del documento, ver el `README.md` de la raíz del repositorio.
