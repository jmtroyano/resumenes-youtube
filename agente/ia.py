"""Proveedor de IA. Hoy es Gemini; para usar otro, añade una clase con los mismos
métodos (resumir_video, resumir_texto, generar) y regístrala en `crear()`."""
from __future__ import annotations

import json
import re
import time

from . import entorno, esquemas

TIEMPO_MAXIMO_MS = 8 * 60 * 1000  # 8 minutos por llamada a la IA


class CupoAgotado(Exception):
    """Límite de uso alcanzado por ahora (429)."""


class ErrorConfiguracion(Exception):
    """Clave inválida, modelo inexistente o permisos: no es culpa del vídeo."""


class VideoNoAccesible(Exception):
    """La IA no puede ver ese vídeo (para miembros, privado, directo...). No se reintenta."""


def _es_cupo_diario(texto: str) -> bool:
    t = texto.lower()
    return ("perday" in t or "per_day" in t or "free_tier_requests" in t
            or re.search(r"retry in \d+h", t) is not None)


def _es_error_configuracion(codigo, texto: str) -> bool:
    t = texto.lower()
    if codigo == 401:
        return True
    if codigo == 403 and ("api key" in t or "api_key" in t or "service_disabled" in t):
        return True
    return codigo == 404 and "model" in t


class ProveedorGemini:
    nombre = "gemini"

    def __init__(self, modelo: str):
        self.modelo = modelo
        self._cliente = None

    # ------------------------------------------------------------ interno
    def _cli(self):
        if self._cliente is None:
            from google import genai  # noqa: PLC0415
            from google.genai import types  # noqa: PLC0415
            clave = entorno.obtener("GEMINI_API_KEY")
            if not clave:
                raise ErrorConfiguracion("Falta la clave GEMINI_API_KEY (ponla en Ajustes)")
            # Tiempo máximo por llamada: evita que una ejecución se quede colgada
            self._cliente = genai.Client(api_key=clave,
                                         http_options=types.HttpOptions(timeout=TIEMPO_MAXIMO_MS))
        return self._cliente

    @staticmethod
    def _con_reintento(funcion):
        from google.genai import errors  # noqa: PLC0415
        for intento in range(2):
            try:
                return funcion()
            except errors.APIError as e:
                codigo = getattr(e, "code", None)
                if _es_error_configuracion(codigo, str(e)):
                    raise ErrorConfiguracion(str(e)) from e
                if codigo == 429:
                    if _es_cupo_diario(str(e)):  # límite diario: no tiene sentido esperar
                        raise CupoAgotado(str(e)) from e
                    if intento == 0:
                        print("[ia] Límite por minuto alcanzado; espero 65 s...")
                        time.sleep(65)
                        continue
                    raise CupoAgotado(str(e)) from e
                if codigo in (500, 503, 504) and intento == 0:
                    time.sleep(20)
                    continue
                raise

    def _estructurado(self, contenido) -> dict:
        from google.genai import types  # noqa: PLC0415
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=esquemas.Resumen,
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
            temperature=0.3,
        )
        r = self._con_reintento(lambda: self._cli().models.generate_content(
            model=self.modelo, contents=contenido, config=config))
        if getattr(r, "parsed", None) is not None:
            return r.parsed.model_dump()
        if not r.text:
            raise RuntimeError("La IA devolvió una respuesta vacía")
        return esquemas.Resumen.model_validate(json.loads(r.text)).model_dump()

    # ------------------------------------------------------------ público
    def resumir_video(self, url: str, titulo: str, canal: str, idioma: str,
                      fps: float = 0.1) -> dict:
        from google.genai import errors, types  # noqa: PLC0415
        contenido = types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=url),
                       video_metadata=types.VideoMetadata(fps=fps)),
            types.Part(text=esquemas.prompt_resumen_video(titulo, canal, idioma)),
        ])
        try:
            return self._estructurado(contenido)
        except errors.APIError as e:
            if getattr(e, "code", None) in (400, 403) and (
                    "permission" in str(e).lower() or "invalid" in str(e).lower()):
                raise VideoNoAccesible(str(e)) from e
            raise

    def resumir_texto(self, texto: str, titulo: str, canal: str, idioma: str) -> dict:
        return self._estructurado(esquemas.prompt_resumen_transcript(titulo, canal, idioma, texto))

    def generar(self, prompt: str, temperatura: float = 0.4) -> str:
        from google.genai import types  # noqa: PLC0415
        r = self._con_reintento(lambda: self._cli().models.generate_content(
            model=self.modelo, contents=prompt,
            config=types.GenerateContentConfig(temperature=temperatura)))
        return (r.text or "").strip()


def crear(cfg: dict):
    proveedor = (cfg.get("proveedor_ia") or "gemini").lower()
    if proveedor == "gemini":
        return ProveedorGemini(cfg["modelo"])
    raise ErrorConfiguracion(f"Proveedor de IA desconocido: {proveedor}")
