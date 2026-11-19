"""
reentrenamiento/
================================================================
Herramientas para actualizar los modelos M1, M2 y M3 con la menor
revisión manual posible:

    extraer → seleccionar → preanotar → (revisión en Roboflow)
    → validar → dividir → entrenar → evaluar → (exportar en la Jetson)

Este paquete NO importa config.py ni ml/ (config.py exige el .env,
el padrón y los modelos; ml/modelos.py carga los modelos en la GPU
al importarse). Así corre igual en la Mac, en Colab y en la Jetson.

Uso:  python -m reentrenamiento --help
Guía: docs/PIPELINE_REENTRENAMIENTO.md
================================================================
"""
__version__ = "0.1.0"
