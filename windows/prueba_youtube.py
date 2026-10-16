"""Prueba real: listar vídeos (con títulos en su idioma) y descargar un transcript."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agente import youtube
canales = {"Cava": ("UCvCCLJkQpRg0NdT3zNcI08A", "es"), "Locos": ("UCCVIYA5kpLvEToE8Gj8Fszw", "es"),
           "PatrickBoyle": ("UCASM0cgfkJxQ1ICmRilfHLw", "en")}
for nombre, (cid, idioma) in canales.items():
    t = time.time()
    v = youtube.listar_videos(cid, 3, idioma)
    print(f"[OK] {nombre} ({time.time()-t:.1f}s):")
    for x in v:
        print(f"     {x['video_id']} | {x['publicado'][:16]} | {x['titulo'][:70]}")
