"""
Prueba de CARACTERIZACIÓN de ml/reconocimiento.py:validar_numero.

Documenta el comportamiento ACTUAL de producción (no el deseado), para que el
problema descrito en docs/PROBLEMA_VALIDAR_NUMERO.md quede verificable y para
que cualquier cambio futuro a esa función sea consciente: si alguien la
corrige, estas pruebas fallan y hay que actualizarlas junto con el documento.

No importa el módulo (cargaría los modelos en la GPU): extrae la función del
código fuente con `ast` y la ejecuta con un padrón de ejemplo.
"""
import ast
from pathlib import Path

import pytest

FUENTE = Path(__file__).resolve().parents[1] / "ml" / "reconocimiento.py"
PADRON = {"5063", "5008", "5005", "5051", "544", "31", "2508"}


@pytest.fixture(scope="module")
def validar_numero():
    arbol = ast.parse(FUENTE.read_text(encoding="utf-8"))
    fn = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == "validar_numero")
    ns = {"UNIDADES_VALIDAS": PADRON, "print": lambda *a, **k: None}
    exec(compile(ast.Module([fn], type_ignores=[]), str(FUENTE), "exec"), ns)
    return ns["validar_numero"]


@pytest.mark.parametrize("lectura, registrado", [
    ("0063", "5063"),   # caso visto en campo: camión CDMX "0063" registrado como la unidad 5063
    ("9063", "5063"),   # cualquier primer dígito distinto de 5 se cambia por 5
    ("063", "5063"),    # a 3 dígitos que no empiezan con 5 se les antepone un 5
    ("008", "5008"),
    ("508", "5008"),    # 3 dígitos que empiezan con 5: se inserta un 0
    ("505", "5005"),    # lectura parcial de 5051 (le faltó el 1) → se registra OTRA unidad
])
def test_correcciones_que_pueden_inventar_una_unidad(validar_numero, lectura, registrado):
    assert validar_numero(lectura) == registrado


@pytest.mark.parametrize("lectura, registrado", [
    ("5051", "5051"),   # en el padrón: sin cambios
    ("2508", "2508"),   # en el padrón aunque no empiece con 5
    ("31", "31"),       # 2 dígitos en el padrón
    ("13", None),       # 2 dígitos fuera del padrón: no se corrigen
    ("5001", None),     # 4 dígitos que empiezan con 5 y no están: no se corrigen
    ("0021", None),     # sin unidad parecida en el padrón
    ("12345", None),    # largo inválido
    ("", None),
    (None, None),
])
def test_casos_sin_correccion(validar_numero, lectura, registrado):
    assert validar_numero(lectura) == registrado
