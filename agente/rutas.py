"""Rutas de archivos del proyecto (todas relativas a la raíz del repositorio)."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CONFIG = RAIZ / "config.yaml"
RUTA_ENV = RAIZ / ".env"
RUTA_ESTADO = RAIZ / "state" / "estado.json"

DIR_DATOS = RAIZ / "data"
DIR_RESUMENES = DIR_DATOS / "resumenes"
DIR_INFORMES = DIR_DATOS / "informes"
DIR_ANALISIS = DIR_DATOS / "analisis"
DIR_TRANSCRIPTS = RAIZ / "transcripts"

CSV_RESUMENES = DIR_DATOS / "resumenes.csv"
CSV_SENTIMIENTO = DIR_DATOS / "sentimiento_por_tema.csv"
