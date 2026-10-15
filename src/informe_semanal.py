"""Punto de entrada para GitHub Actions: informe semanal comparativo.

  python src/informe_semanal.py            # últimos 7 días
  python src/informe_semanal.py --dias 14  # otro periodo
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agente.informe import main  # noqa: E402

if __name__ == "__main__":
    main()
