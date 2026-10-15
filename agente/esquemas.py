"""Formato estructurado de los resúmenes y textos de las instrucciones (prompts)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Sentimiento = Literal["muy bajista", "bajista", "neutral", "alcista", "muy alcista"]

# Usar siempre los mismos nombres de tema es lo que permite comparar vídeos
# de canales distintos sobre un mismo asunto.
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
    "Análisis técnico",
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


_INSTRUCCIONES_RESUMEN = """Escribe TODO el resultado en {idioma}, aunque el contenido esté en otro idioma.

Instrucciones:
- Sé fiel a lo que dicen los participantes. No añadas opiniones propias ni datos que no aparezcan.
- Si hay varios participantes con opiniones distintas, refléjalo en las ideas clave indicando quién opina qué.
- Ideas clave: concretas y accionables, con cifras cuando se den. Nada de frases genéricas.
- Sentimiento: valora la visión que transmiten sobre los mercados o la economía, no el tono emocional.
  Usa la escala -1 (muy bajista) a +1 (muy alcista); 0 es neutral.
- sentimiento_por_tema: una entrada por cada tema relevante.
- Para "temas" y "sentimiento_por_tema.tema" usa, siempre que encaje, exactamente uno de estos
  nombres: {temas}. Solo si ninguno encaja, crea un nombre corto nuevo.
- predicciones: solo afirmaciones explícitas sobre el futuro (precios, tipos, recesión...).
  Lista vacía si no las hay.
- Si el contenido no trata de economía, mercados o inversión, marca es_contenido_de_mercados=false y
  resume igualmente en pocas líneas.
"""


def prompt_resumen_video(titulo: str, canal: str, idioma: str) -> str:
    return (f'Eres un analista financiero que resume vídeos de economía, inversión y mercados.\n'
            f'Mira y escucha el vídeo completo "{titulo}" del canal "{canal}".\n\n'
            + _INSTRUCCIONES_RESUMEN.format(idioma=idioma, temas="; ".join(TEMAS_CANONICOS)))


def prompt_resumen_transcript(titulo: str, canal: str, idioma: str, texto: str) -> str:
    return (f'Eres un analista financiero que resume vídeos de economía, inversión y mercados.\n'
            f'A continuación tienes la transcripción del vídeo "{titulo}" del canal "{canal}".\n'
            f'Puede venir de subtítulos automáticos: corrige mentalmente errores evidentes en nombres\n'
            f'y cifras, pero no inventes nada. Las marcas [mm:ss] indican el minuto del vídeo.\n\n'
            + _INSTRUCCIONES_RESUMEN.format(idioma=idioma, temas="; ".join(TEMAS_CANONICOS))
            + f"\nTRANSCRIPCIÓN:\n{texto}\n")


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


INSTRUCCION_ANALISIS_POR_DEFECTO = (
    "Compara lo que dicen estos vídeos. Agrupa por temas comunes y, para cada tema, explica en qué "
    "coinciden los canales, en qué discrepan (quién defiende qué y con qué argumentos o datos) y el "
    "sentimiento de cada uno. Termina con las conclusiones principales, las predicciones más concretas "
    "y los riesgos que más se repiten.")


def prompt_analisis(instruccion: str, contexto: str, idioma: str) -> str:
    return f"""Eres un analista financiero independiente. Vas a analizar el contenido de varios vídeos
de YouTube sobre economía, inversión y mercados. Cada vídeo aparece delimitado con su canal, fecha y
título; puede venir como transcripción (subtítulos, con marcas [mm:ss]) o como resumen estructurado.

PETICIÓN DEL USUARIO:
{instruccion}

Normas:
- Responde en {idioma}, en Markdown (títulos con ##, listas con -, negritas con **).
- Atribuye siempre cada idea a su canal (y minuto [mm:ss] si lo hay). No mezcles opiniones.
- Basa todo en el contenido proporcionado. Si algo no se menciona, dilo; no inventes datos.
- Señala cuando las fuentes se contradicen y qué argumentos usa cada una.
- No des recomendaciones de inversión personales.

CONTENIDO DE LOS VÍDEOS:
{contexto}
"""
