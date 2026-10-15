"""Punto de entrada para GitHub Actions: resúmenes automáticos.

  python src/resumir.py                      # ejecución normal
  python src/resumir.py --comprobar-canales  # verifica los canales
  python src/resumir.py --prueba URL         # resume un vídeo concreto
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agente.automatico import main  # noqa: E402

if __name__ == "__main__":
    main()
