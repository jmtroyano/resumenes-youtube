# Agente de resúmenes de YouTube (economía e inversión)

Dos piezas que comparten el mismo código (`agente/`) y los mismos datos (este repositorio):

| Pieza | Dónde funciona | Qué hace |
|---|---|---|
| **Resúmenes automáticos** | GitHub Actions (gratis, sin tu PC) | Cada 3 h resume los vídeos nuevos de los canales **activos** y te los manda por Telegram. Los domingos, informe semanal comparativo. |
| **App web local** | Tu ordenador (`http://localhost:8000`) | Eliges canales y vídeos, descargas sus transcripts cuando quieras, los resumes, comparas varios vídeos con Gemini y gestionas los canales (añadir, borrar, pausar/activar). |
| **Conexión con Claude** | App de escritorio de Claude | Claude puede consultar tus canales, transcripts y resúmenes, descargar transcripts y guardar análisis. |

```
                ┌──────────── agente/ (núcleo en Python) ────────────┐
                │ canales · youtube · transcripts · ia · almacén ·    │
                │ análisis · notificar · sync                         │
                └─────────────────────────────────────────────────────┘
      ▲                         ▲                          ▲
 src/*.py                 app/servidor.py            app/mcp_claude.py
 (GitHub Actions)         API REST + app/web         (Claude desktop)
```

## Uso diario

- **Abrir la app:** doble clic en el acceso directo **Agente YouTube** del Escritorio. Se abre el navegador; deja la ventana negra abierta mientras la uses.
- **Vídeos:** marca canales → *Cargar vídeos* → selecciona vídeos → *Descargar transcripts*, *Resumir* o *Analizar / comparar*.
- **Biblioteca:** todo lo guardado (transcripts y resúmenes, también los automáticos).
- **Análisis:** escribe qué quieres saber y Gemini compara los vídeos seleccionados. Se guarda en `data/analisis/`.
- **Canales:** añade por @nombre o URL, elimina, o usa el interruptor **Automático / En pausa**.
- **Claude:** en la app de escritorio de Claude pide cosas como *"compara lo que dicen Cárpatos y Los Locos de Wall Street sobre la Fed esta semana"*.

Los cambios que hagas en la app se suben solos a GitHub (y GitHub Actions los usa en la siguiente ejecución).

## Por qué los transcripts se descargan en tu ordenador

YouTube bloquea la descarga de subtítulos desde servidores en la nube, pero no desde una conexión doméstica. Por eso:
- La app (y Claude) descargan transcripts desde tu PC y los guardan en `transcripts/`.
- GitHub Actions resume desde el transcript si existe (rápido, poco cupo) y, si no, viendo el vídeo con Gemini.

## Instalación (ya hecha en tu PC)

1. `git clone https://github.com/jmtroyano/resumenes-youtube.git`
2. Doble clic en `windows\instalar.bat` (crea el entorno, instala dependencias, el acceso directo y la conexión con Claude).
3. Abre la app y en **Ajustes** pega tu clave de Gemini (se guarda solo en el archivo `.env` local, nunca se sube).

Para actualizar: `windows\actualizar.bat`.

## Secrets de GitHub (para los resúmenes automáticos)

`Settings → Secrets and variables → Actions`: `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (y opcionalmente `EMAIL_USUARIO`, `EMAIL_PASSWORD`, `EMAIL_DESTINO`).

## Datos

| Ruta | Contenido | Quién escribe |
|---|---|---|
| `config.yaml` | Ajustes y canales (`activo: true` = automático) | App |
| `transcripts/<id>.json` | Subtítulos con marcas de tiempo | App / Claude |
| `data/resumenes/AAAA/MM/*.json` | Un resumen estructurado por vídeo | Actions y App |
| `data/resumenes.csv`, `data/sentimiento_por_tema.csv` | Tablas para Excel (se regeneran) | Actions |
| `data/analisis/*.md` | Análisis comparativos | App / Claude |
| `data/informes/` | Informes semanales | Actions |
| `state/estado.json` | Cola interna de Actions | Actions |

## Migrar a otro tipo de aplicación

- **Toda la lógica está en `agente/`**, sin interfaz. Cualquier otra app (móvil, escritorio, web en la nube) puede usar la **API REST** de `app/servidor.py` o importar `agente/` directamente.
- **Proveedor de IA intercambiable:** `agente/ia.py` (`proveedor_ia` en `config.yaml`).
- **Almacenamiento centralizado:** `agente/almacen.py` y `agente/transcripts.py`. Para pasar a una base de datos solo cambian esos módulos.
- **Interfaz sin dependencias:** `app/web` es HTML + JavaScript puro; se puede envolver en una app de escritorio (pywebview, Tauri) sin cambios.
- Desplegar la app en la nube es posible, salvo la descarga de transcripts, que necesitaría un proxy residencial (de pago).
