# Diagramas

Los archivos editables están en [`docs/diagramas/`](diagramas/) (formato Mermaid). GitHub los muestra directamente aquí abajo. Para editarlos: [mermaid.live](https://mermaid.live) o la extensión de Mermaid de VS Code.

Colores: **amarillo** = aprobación o trabajo humano · **rojo** = error o retorno para corrección · **verde** = éxito · **gris** = descartado.

## 1. Flujo general (inspección → actualización operativa)

Vista completa con los dos puntos de aprobación humana y los retornos cuando un modelo se rechaza o hay regresión en producción.

Fuente: [`diagramas/01_flujo_general.mmd`](diagramas/01_flujo_general.mmd)

```mermaid
%% Flujo general: de la inspección inicial a la actualización operativa.
%% Cada bloque grande se detalla en 02..05. Editable: https://mermaid.js.org
flowchart TD
    INICIO(["Inicio: se decide actualizar M1, M2 o M3"]) --> P0

    subgraph P0["P0 · Auditoría y línea base"]
        A1["Respaldar estado actual:<br/>.env, modelos/engine_nx, padron.csv, commit"] --> A2["Medir línea base en la Jetson:<br/>exactitud del número, FPS, conteo<br/>(docs/EVALUACION_MODELOS.md)"]
        A2 --> A3{"¿Existe set de prueba<br/>congelado del modelo?"}
        A3 -- "No" --> A4["Crearlo en el primer 'dividir'<br/>(congelado_mX.txt)"]
        A3 -- "Sí" --> A5["Usar el mismo congelado"]
    end

    P0 --> CAP["P1 · Captura inteligente<br/>(diagrama 02)"]
    CAP --> SEL["P1 · Filtrado y selección<br/>(diagrama 02)"]
    SEL --> ETQ["P2 · Preanotación + revisión humana selectiva<br/>(diagrama 03)"]
    ETQ --> ENT["P3 · Dataset versionado + fine-tuning + evaluación<br/>(diagrama 04)"]
    ENT --> DEC{"¿Evaluación = ACEPTAR?"}
    DEC -- "RECHAZAR" --> DIAG["Leer motivos del reporte:<br/>olvido de clase, baja exactitud,<br/>no mejora"]
    DIAG --> R1{"¿Faltan datos o<br/>hay etiquetas malas?"}
    R1 -- "Etiquetas" --> ETQ
    R1 -- "Faltan casos" --> CAP
    R1 -- "Hiperparámetros" --> ENT
    DEC -- "ACEPTAR" --> APR1{{"Aprobación humana #1:<br/>responsable revisa el reporte"}}
    APR1 -- "No" --> DIAG
    APR1 -- "Sí" --> DEP["P4 · Exportar en la Jetson + canary<br/>(diagrama 05)"]
    DEP --> FIN{"¿Canary y 48 h en producción<br/>sin regresiones?"}
    FIN -- "No" --> RB["Rollback al modelo anterior"] --> DIAG
    FIN -- "Sí" --> DOC["P5 · Registrar: CHANGELOG, registro.jsonl,<br/>versión del modelo en docs"]
    DOC --> FINAL(["Fin: nueva versión operando<br/>y documentada"])

    classDef humano fill:#FFF4CC,stroke:#B8860B,color:#000;
    classDef error fill:#FDE2E2,stroke:#B22222,color:#000;
    class APR1 humano;
    class DIAG,RB error;
```

## 2. Captura inteligente, filtrado y selección

Qué pasa con una captura **redundante** (`redundante`, `cupo_pasada`), con **mala calidad** (`mala_calidad:*`), con **baja confianza** (`baja_conf` → revisar) y con un evento sin video.

Fuente: [`diagramas/02_captura_seleccion.mmd`](diagramas/02_captura_seleccion.mmd)

```mermaid
%% P1 · Captura inteligente, filtrado y selección (reentrenamiento/extraer_video.py, calidad.py,
%% redundancia.py, seleccion.py). Comando: python -m reentrenamiento seleccionar|preanotar
flowchart TD
    subgraph FUENTES["Fuentes (ya existen en la Jetson)"]
        F1["Recortes que guarda producción<br/>crops_dataset/{delantero,lateral,trasera}<br/>nombre: fecha_hora_ms_numero_tTRACK.jpg"]
        F2["Grabaciones por hora<br/>cam1_AAAAMMDD_HHMMSS.mp4 (72 h)"]
        F3["Errores marcados por validadores<br/>telegram_unidades_erroneas/"]
    end
    F2 --> E1{"¿Captura por eventos<br/>o periódica?"}
    E1 -- "Eventos" --> E2["Exportar cruces de /api/detecciones<br/>→ cuadros de -3 s a +3 s"]
    E1 -- "Periódica" --> E3["1 cuadro cada N s<br/>(condiciones nuevas)"]
    E2 --> E4{"¿Hay grabación para<br/>esa hora? (72 h)"}
    E4 -- "No" --> E5["Evento sin video:<br/>se reporta, se sigue"]
    E4 -- "Sí" --> POOL
    E3 --> POOL
    F1 --> POOL
    F3 --> POOL
    POOL["Conjunto de imágenes candidatas"] --> Q1["Medir calidad: nitidez, brillo,<br/>contraste, tamaño, tipo de luz"]
    Q1 --> Q2{"¿Mala calidad?<br/>borrosa / oscura / chica / ilegible"}
    Q2 -- "Sí" --> D1["DESCARTAR<br/>razón: mala_calidad:*"]
    Q2 -- "No" --> G1["Agrupar por PASADA<br/>(zona + track + ventana 6 s)"]
    G1 --> M1{"¿Hay modelo actual (.pt)?"}
    M1 -- "Sí" --> M2["Predecir con v3 →<br/>lectura, conf mínima, n dígitos"]
    M1 -- "No" --> C1
    M2 --> C1["Consenso de lecturas<br/>por pasada"]
    C1 --> C2{"¿Recorte difícil?<br/>sin_digitos · digitos_raros · desacuerdo ·<br/>baja_conf · sistema_distinto · fuera_padron ·<br/>condicion_nueva · calidad_dudosa"}
    C2 -- "Ninguna razón" --> C3{"¿Pasada fácil cae en la<br/>muestra de control (20%)?"}
    C3 -- "No" --> D2["DESCARTAR<br/>pasada_facil_fuera_de_muestra"]
    C3 -- "Sí" --> K1["CONSERVAR 1 representante<br/>(el más nítido)"]
    C2 -- "Sí" --> H1["Representante + hasta 3<br/>difíciles por pasada"]
    H1 --> H2{"¿Se parece (dHash < 6)<br/>a uno ya elegido?"}
    H2 -- "Sí" --> D3["DESCARTAR<br/>redundante"]
    H2 -- "No" --> R1["REVISAR<br/>(humano en Roboflow)"]
    H1 --> H3{"¿Pasó el cupo<br/>por pasada?"}
    H3 -- "Sí" --> D4["DESCARTAR<br/>cupo_pasada"]
    K1 --> LOTE
    R1 --> LOTE["Lote YOLO: images/ labels/ data.yaml<br/>resumen.csv manifiesto.json"]

    classDef descartar fill:#EEEEEE,stroke:#777,color:#000;
    classDef revisar fill:#FFF4CC,stroke:#B8860B,color:#000;
    class D1,D2,D3,D4,E5 descartar;
    class R1 revisar;
```

## 3. Preanotación y revisión humana selectiva

Qué pasa con una **anotación incorrecta** (control de calidad, más de 5 % → se devuelve el lote) y con un **dataset incompleto o inválido** (`validar` lo detiene).

Fuente: [`diagramas/03_etiquetado.mmd`](diagramas/03_etiquetado.mmd)

```mermaid
%% P2 · Preanotación y revisión humana selectiva (Roboflow) + control de calidad
flowchart TD
    L0["Lote con pre-etiquetas del modelo actual<br/>(conf 0.25: sobran cajas, no faltan)"] --> L1["Subir carpeta a Roboflow<br/>proyecto M1 / M2 / M3"]
    L1 --> L2{"¿Roboflow la rechaza<br/>por imagen duplicada?"}
    L2 -- "Sí" --> L3["Quitar el lote viejo sin etiquetar<br/>(requiere aprobación del responsable)"] --> L1
    L2 -- "No" --> L4["Ordenar por etiqueta:<br/>1° sistema_distinto, desacuerdo<br/>2° baja_conf, fuera_padron, condicion_nueva<br/>3° conservar (muestreo)"]
    L4 --> L5["Corregir cajas: una por dígito,<br/>tecla B (no polígono)"]
    L5 --> L6{"¿Imagen legible?"}
    L6 -- "No" --> L7["Marcar como sin objetos (null)<br/>o borrar del lote"]
    L6 -- "Sí" --> L8["Guardar anotación"]
    L7 --> QA
    L8 --> QA{"Control de calidad:<br/>2a persona revisa 10% al azar"}
    QA -- "Error > 5%" --> L9["Anotación incorrecta:<br/>devolver el lote completo<br/>+ repasar reglas"] --> L5
    QA -- "Error ≤ 5%" --> V1["Generar versión en Roboflow<br/>(sin volteos en M3)"]
    V1 --> V2["Exportar formato YOLO<br/>→ python -m reentrenamiento validar"]
    V2 --> V3{"¿validar = OK?<br/>clases en orden, coords 0-1,<br/>sin polígonos, sin fuga"}
    V3 -- "No: dataset incompleto o inválido" --> V4["Corregir en Roboflow<br/>según el reporte"] --> V1
    V3 -- "Sí" --> V5(["Dataset listo para P3"])

    classDef humano fill:#FFF4CC,stroke:#B8860B,color:#000;
    classDef error fill:#FDE2E2,stroke:#B22222,color:#000;
    class L3,L5,QA humano;
    class L9,V4 error;
```

## 4. Dataset, entrenamiento y evaluación

Qué pasa cuando **el entrenamiento falla** (estado `fallido` en el registro) y cuando **el modelo nuevo es peor** (RECHAZAR por regresión global, olvido por clase o exactitud del número).

Fuente: [`diagramas/04_entrenamiento_evaluacion.mmd`](diagramas/04_entrenamiento_evaluacion.mmd)

```mermaid
%% P3 · Dataset versionado, fine-tuning y evaluación (Colab Pro)
flowchart TD
    D0["Dataset validado (export de Roboflow)"] --> D1["dividir POR PASADA<br/>(misma pasada = mismo split)"]
    D1 --> D2{"¿Existe congelado_mX.txt?"}
    D2 -- "No (primera vez)" --> D3["Crear test congelado con las<br/>pasadas que cayeron en test"]
    D2 -- "Sí" --> D4["test = congelado;<br/>datos nuevos solo a train/valid"]
    D3 --> D5
    D4 --> D5["validar de nuevo<br/>(fuga entre splits)"]
    D5 --> D6{"¿Hay fuga?"}
    D6 -- "Sí" --> D7["Revisar nombres/pasadas<br/>y volver a dividir"] --> D1
    D6 -- "No" --> T0["Experimento YAML:<br/>base = v3.pt, lr0 bajo, patience 30"]
    T0 --> T1["entrenar → registro.jsonl<br/>(commit, hash dataset, versiones, args)"]
    T1 --> T2{"¿El entrenamiento terminó?"}
    T2 -- "Falló: memoria, Colab desconectado,<br/>clases fuera de orden" --> T3["Estado 'fallido' en el registro.<br/>Bajar batch / reanudar / corregir data.yaml"] --> T0
    T2 -- "Sí" --> E0["evaluar candidato vs v3<br/>sobre el MISMO test congelado"]
    E0 --> E1{"¿Recall o precisión global bajan<br/>más de 1 punto?"}
    E1 -- "Sí" --> RJ["RECHAZAR"]
    E1 -- "No" --> E2{"¿Alguna clase pierde<br/>más de 3 puntos de recall?<br/>(olvido)"}
    E2 -- "Sí" --> RJ
    E2 -- "No" --> E3{"M3: ¿baja la exactitud del<br/>número o sube el CER?"}
    E3 -- "Sí" --> RJ
    E3 -- "No" --> E4{"¿Mejora alguna métrica<br/>principal ≥ 0.5 puntos?"}
    E4 -- "No" --> RJ
    E4 -- "Sí" --> AC["ACEPTAR → evaluacion.md"]
    RJ --> RJ2["Ajustar: freeze 10, más épocas,<br/>más datos del caso olvidado"] --> T0
    AC --> SAL(["best.pt + reporte → aprobación humana"])

    classDef error fill:#FDE2E2,stroke:#B22222,color:#000;
    classDef ok fill:#E2F5E2,stroke:#2E7D32,color:#000;
    class RJ,T3,D7 error;
    class AC ok;
```

## 5. Exportación, canary, activación y rollback

Qué pasa cuando **falla la exportación a TensorRT**, cuando **la Jetson es incompatible** (no carga o es lenta) y cuando **hay regresiones en producción** (rollback por `.env`).

Fuente: [`diagramas/05_despliegue_rollback.mmd`](diagramas/05_despliegue_rollback.mmd)

```mermaid
%% P4 · Exportación en la Jetson, canary y rollback (scripts/exportar_engine.sh, docs/DESPLIEGUE.md)
flowchart TD
    S0(["best.pt aceptado + aprobación #1"]) --> S1["Copiar best.pt a la Jetson (scp)"]
    S1 --> S2["Horario de poco tráfico<br/>(18:00-20:00 según el tablero)"]
    S2 --> S3["bash scripts/exportar_engine.sh mX best.pt v4"]
    S3 --> S4{"¿Clases en orden oficial?"}
    S4 -- "No" --> S5["Abortar: el .pt no es del<br/>dataset correcto"] --> X1(["Regresar a P3"])
    S4 -- "Sí" --> S6{"¿Export a TensorRT OK?"}
    S6 -- "No: versión TRT/CUDA,<br/>memoria GPU, imgsz" --> S7["Revisar log; reintentar con<br/>workspace menor o fuera de horario.<br/>Si persiste: incompatibilidad →<br/>revisar versiones del Dockerfile"] --> S3
    S6 -- "Sí" --> S8{"¿Velocidad ≥ línea base<br/>y predicción corre?"}
    S8 -- "No" --> S9["Jetson incompatible o modelo<br/>más pesado: no se despliega"] --> X1
    S8 -- "Sí" --> C0["Canary con VIDEO GRABADO<br/>(modo prueba, sin tocar la cámara real)"]
    C0 --> C1{"¿Conteo, tracking y lectura<br/>≥ v3 en el mismo video?"}
    C1 -- "No" --> S9
    C1 -- "Sí" --> APR{{"Aprobación humana #2:<br/>activar en producción"}}
    APR -- "No" --> X1
    APR -- "Sí" --> P1["Respaldar .env → cambiar ruta del modelo<br/>→ docker compose up -d --force-recreate cisa-vision"]
    P1 --> P2{"¿Arranca y muestra<br/>'Clases M' correctas?"}
    P2 -- "No" --> RB["ROLLBACK inmediato:<br/>restaurar .env y recrear"]
    P2 -- "Sí" --> P3["Vigilar 48 h: descartadas, Desconocida,<br/>alternancia entrada/salida, FPS, errores"]
    P3 --> P4{"¿Regresión en producción?"}
    P4 -- "Sí" --> RB
    P4 -- "No" --> OK(["Versión adoptada · CHANGELOG + registro"])
    RB --> RB2["Documentar incidente<br/>y volver a P3"] --> X1

    classDef humano fill:#FFF4CC,stroke:#B8860B,color:#000;
    classDef error fill:#FDE2E2,stroke:#B22222,color:#000;
    classDef ok fill:#E2F5E2,stroke:#2E7D32,color:#000;
    class APR humano;
    class S5,S7,S9,RB,RB2 error;
    class OK ok;
```

## 6. Diagrama de bloques (arquitectura)

Distinto del flujo: muestra **componentes**, no pasos. Azul = existe; verde punteado = nuevo o propuesto; gris = externo. Explicación de cada bloque en [ARQUITECTURA.md](ARQUITECTURA.md).

Fuente: [`diagramas/06_bloques_arquitectura.mmd`](diagramas/06_bloques_arquitectura.mmd)

```mermaid
%% Diagrama de bloques: arquitectura completa. Línea continua = existe hoy; punteada = propuesto.
%% Clases: existente (azul), propuesto (verde), externo (gris).
flowchart LR
    subgraph FIS["Infraestructura física"]
        CAM["Cámara IP Cam 1<br/>RTSP H.265 Full HD"]
        CAM2["Cámara 2<br/>(opcional, botón Cam 2)"]
        RED["Red del patio<br/>+ Tailscale"]
        JET["Jetson Orin NX Super 16 GB<br/>JetPack 7.2 · CUDA 13.2 · TRT 10.16<br/>disco NVMe 915 GB"]
        COLAB["Google Colab Pro<br/>(GPU de entrenamiento)"]
        DRIVE["Google Drive<br/>CISA_Reentrenamiento/"]
        RF["Roboflow<br/>workspace cisas"]
    end

    subgraph INF["Inferencia en la Jetson (contenedor cisa-vision)"]
        CS["logica/camara.py<br/>CameraStream: GStreamer NVDEC<br/>(FFmpeg de respaldo)"]
        H1["ml/hilos.py · HiloM1<br/>M1 bus_v3.engine + ByteTrack"]
        H2["ml/hilos.py · HiloM2M3<br/>M2 zona (1280) → M3 dígitos"]
        REC["ml/reconocimiento.py<br/>CLAHE, quitar_encimados,<br/>validar_numero, crops"]
        LV["ml/linea_virtual.py<br/>cruce, maniobra, debounce"]
        VAL["avisos/gemini.py + telegram.py<br/>validación (LLM + humano)"]
        WA["cisa-whatsapp<br/>(Node + Baileys)"]
        DB[("PostgreSQL patio_cca<br/>metricas/storage.py")]
        WEB["web/ Flask :5001<br/>tablero, video, API"]
        GRAB["cisa-grabacion<br/>scripts/grabar.sh (72 h)"]
        FS[("Jetson8/<br/>crops_dataset, cisa_frames,<br/>grabaciones, errores")]
    end

    subgraph PROC["Procesamiento para reentrenamiento (reentrenamiento/)"]
        EX["extraer_video.py<br/>por eventos / periódico"]
        CA["calidad.py<br/>nitidez, luz, tamaño"]
        RD["redundancia.py<br/>pasadas + dHash"]
        SE["seleccion.py<br/>conservar / revisar / descartar"]
        PA["preanotacion.py + predicciones.py<br/>lote YOLO con cajas"]
        VE["validar_etiquetas.py<br/>clases, coords, fuga"]
        DV["dividir.py<br/>por pasada + test congelado"]
        EN["entrenar.py<br/>fine-tuning + registro.jsonl"]
        EV["evaluar.py<br/>métricas + ACEPTAR/RECHAZAR"]
    end

    subgraph ADM["Administración"]
        CFG["config.py + .env (producción)<br/>config_reentrenamiento.yaml"]
        REG["experimentos/registro.jsonl<br/>CHANGELOG.md"]
        TST["tests/ (pytest)"]
        EXP["scripts/exportar_engine.sh<br/>+ rollback por .env"]
        SVC["cisa.service (systemd)<br/>arranque al encender"]
        MON["Monitoreo propuesto:<br/>alternancia, descartadas, FPS"]
    end

    CAM -->|RTSP| RED --> CS
    CAM2 -.->|RTSP| CS
    CS -->|"frame BGR"| H1 -->|"cola: frame + buses"| H2
    H2 <--> REC
    H2 --> LV
    LV -->|"cruce + número"| VAL --> DB
    VAL --> WA
    DB --> WEB
    REC -->|"jpg"| FS
    RED --> GRAB -->|"mp4/h"| FS
    SVC --> CS

    FS -.->|"scp / Drive"| DRIVE
    WEB -.->|"JSON eventos"| EX
    DRIVE -.-> EX
    EX -.-> CA -.-> RD -.-> SE -.-> PA
    PA -.->|"lote YOLO"| RF
    RF -.->|"export YOLO"| VE -.-> DV -.-> EN -.-> EV
    COLAB -.-> EN
    EV -.->|"best.pt aceptado"| EXP -.->|".engine FP16"| JET
    EN -.-> REG
    CFG --> H1
    TST -.-> PROC
    MON -.-> DB

    classDef existe fill:#E3F0FF,stroke:#1F5FAD,color:#000;
    classDef propuesto fill:#E2F5E2,stroke:#2E7D32,color:#000,stroke-dasharray: 5 3;
    classDef externo fill:#F0F0F0,stroke:#777,color:#000;
    class CS,H1,H2,REC,LV,VAL,WA,DB,WEB,GRAB,FS,CFG,SVC existe;
    class EX,CA,RD,SE,PA,VE,DV,EN,EV,REG,TST,EXP,MON propuesto;
    class CAM,CAM2,RED,JET,COLAB,DRIVE,RF externo;
```
