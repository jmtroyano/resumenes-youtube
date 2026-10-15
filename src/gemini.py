"""Llamadas a la API de Gemini: esquema del resumen y prompts."""
from __future__ import annotations

import json
import os
import time
from typing import Literal

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, Field

Sentimiento = Literal["muy bajista", "bajista", "neutral", "alcista", "muy alcista"]

# Lista de temas "canónicos". Usar siempre los mismos nombres es lo que permite
# comparar vídeos de canales distintos sobre un mismo tema.
TEMAS_CANONICOS = [
    "Fed y tipos de interés EE. UU.", "BCE y tipos de interés Europa",
    "Otros bancos centrales", "Inflación", "Empleo", "Crecimiento y recesión",
    "Deuda pública y déficit", "Bonos y renta fija", "Bolsa EE. UU.",
    "Bolsa Europa", "Bolsa España", "Mercados emergentes", "China",
    "Tecnología e inteligencia artificial", "Semiconductores", "Bancos",
    "Energía y petróleo", "Oro y metales", "Materias primas", "Dólar y divisas",
    "Criptomonedas", "Inmobiliario y vivienda", "Geopolítica",
    "Aranceles y comercio", "Política fiscal e impuestos", "Resultados empresariales",
    "Valoración de mercado y burbujas", "Value investing", "Small caps",
    "Fondos indexados y ETFs", "Finanzas personales", "Liquidez y crédito",
]


class SentimientoTema(BaseModel):
    tema: str = Field(description="Uno de los temas de la lista canónica si encaja")
    sentimiento: Sentimiento
    puntuacion: float = Field(description="De -1 (muy bajista) a +1 (muy alcista)")
    justificacion: str = Field(description="Una frase con el motivo")


class Prediccion(BaseModel):
    afirmacion: str = Field(description="La predicción concreta tal como la hace el autor")
    activo_o_variable: str
    direccion: Literal["sube", "baja", "lateral", "no aplica"]
    horizonte: str = Field(description="Plazo mencionado, o 'no especificado'")
    conviccion_del_autor: Literal["baja", "media", "alta"]


class Resumen(BaseModel):
    resumen_breve: str = Field(description="3-4 frases con lo esencial del vídeo")
    ideas_clave: list[str] = Field(description="Entre 5 y 8 ideas clave")
    tesis_principal: str
    temas: list[str] = Field(description="Temas tratados, usando la lista canónica")
    activos_mencionados: list[str] = Field(description="Índices, acciones, ETFs, materias primas, divisas...")
    sentimiento_general: Sentimiento
    puntuacion_sentimiento: float = Field(description="De -1 a +1")
    sentimiento_por_tema: list[SentimientoTema]
    predicciones: list[Prediccion]
    datos_y_argumentos: list[str] = Field(description="Datos, cifras o argumentos concretos que usan")
    riesgos_mencionados: list[str]
    participantes: list[str] = Field(description="Presentadores e invitados si se nombran")
    nivel_conviccion: Literal["baja", "media", "alta"]
    es_contenido_de_mercados: bool = Field(description="False si el vídeo no trata de economía, mercados o inversión")


def prompt_resumen(titulo: str, canal: str, idioma: str) -> str:
    temas = "; ".join(TEMAS_CANONICOS)
    return f"""Eres un analista financiero que resume vídeos de economía, inversión y mercados.
Mira y escucha el vídeo completo "{titulo}" del canal "{canal}".

Escribe TODO el resultado en {idioma}, aunque el vídeo esté en otro idioma.

Instrucciones:
- Sé fiel a lo que dicen los participantes. No añadas opiniones propias ni datos que no aparezcan.
- Si hay varios participantes con opiniones distintas, refléjalo en las ideas clave indicando quién opina qué.
- Ideas clave: concretas y accionables, con cifras cuando se den. Nada de frases genéricas.
- Sentimiento: valora la visión que transmiten sobre los mercados o la economía, no el tono emocional.
  Usa la escala -1 (muy bajista) a +1 (muy alcista); 0 es neutral.
- sentimiento_por_tema: una entrada por cada tema relevante del vídeo.
- Para "temas" y "sentimiento_por_tema.tema" usa, siempre que encaje, exactamente uno de estos
  nombres: {temas}. Solo si ninguno encaja, crea un nombre corto nuevo.
- predicciones: solo afirmaciones explícitas sobre el futuro (precios, tipos, recesión...).
  Lista vacía si no las hay.
- Si el vídeo no trata de economía, mercados o inversión, marca es_contenido_de_mercados=false y
  resume igualmente en pocas líneas.
"""


def prompt_informe(bloque_resumenes: str, bloque_estadisticas: str, idioma: str) -> str:
    return f"""Eres un analista financiero. A continuación tienes los resúmenes estructurados de los
vídeos de economía e inversión publicados esta semana por distintos canales, y unas estadísticas
de sentimiento calculadas a partir de ellos.

Escribe un informe semanal comparativo en {idioma}, en texto plano (sin Markdown, sin tablas,
sin asteriscos), con estas secciones y títulos en MAYÚSCULAS:

1. VISIÓN GENERAL: 4-6 frases sobre el clima de la semana.
2. TEMAS PRINCIPALES: para los 4-6 temas más tratados: en qué coinciden los canales, en qué
   discrepan (nombrando qué canal defiende qué) y el sentimiento predominante.
3. CONSENSO Y DISCREPANCIAS: las ideas más repetidas y los choques de opinión más claros.
4. PREDICCIONES DESTACADAS: las más concretas, indicando canal y horizonte.
5. CAMBIOS DE SENTIMIENTO: si algún canal o tema se ha vuelto más alcista o bajista.
6. RIESGOS QUE MÁS PREOCUPAN.

Usa guiones "- " para las listas. Sé concreto, cita canales y cifras. No inventes nada que no esté
en los resúmenes. No des recomendaciones de inversión propias.

ESTADÍSTICAS DE SENTIMIENTO:
{bloque_estadisticas}

RESÚMENES DE LA SEMANA:
{bloque_resumenes}
"""


class CupoAgotado(Exception):
    """Gemini ha devuelto 429: se ha agotado el cupo gratuito por ahora."""


def _cliente() -> genai.Client:
    clave = os.environ.get("GEMINI_API_KEY", "").strip()
    if not clave:
        raise RuntimeError("Falta el secret GEMINI_API_KEY")
    return genai.Client(api_key=clave)


def _con_reintento(funcion):
    """Un reintento tras una espera si hay límite por minuto; si persiste,
    se considera cupo agotado."""
    for intento in range(2):
        try:
            return funcion()
        except errors.APIError as e:
            codigo = getattr(e, "code", None)
            if codigo == 429:
                if intento == 0:
                    print("[gemini] Límite por minuto alcanzado; espero 65 s...")
                    time.sleep(65)
                    continue
                raise CupoAgotado(str(e)) from e
            if codigo in (500, 503, 504) and intento == 0:
                time.sleep(20)
                continue
            raise


def resumir_video(url: str, titulo: str, canal: str, modelo: str, idioma: str,
                  fps: float = 0.1) -> dict:
    cliente = _cliente()
    contenido = types.Content(parts=[
        types.Part(file_data=types.FileData(file_uri=url),
                   video_metadata=types.VideoMetadata(fps=fps)),
        types.Part(text=prompt_resumen(titulo, canal, idioma)),
    ])
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=Resumen,
        media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
        temperature=0.3,
    )

    respuesta = _con_reintento(lambda: cliente.models.generate_content(
        model=modelo, contents=contenido, config=config))
    if getattr(respuesta, "parsed", None) is not None:
        return respuesta.parsed.model_dump()
    if not respuesta.text:
        raise RuntimeError("Gemini devolvió una respuesta vacía")
    return Resumen.model_validate(json.loads(respuesta.text)).model_dump()


def generar_texto(prompt: str, modelo: str) -> str:
    cliente = _cliente()
    respuesta = _con_reintento(lambda: cliente.models.generate_content(
        model=modelo, contents=prompt,
        config=types.GenerateContentConfig(temperature=0.4)))
    return (respuesta.text or "").strip()
