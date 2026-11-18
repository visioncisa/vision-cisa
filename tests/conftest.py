import sys
from pathlib import Path

# Para poder importar ml/ y config desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
