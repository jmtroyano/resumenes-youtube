# Agente de resúmenes de YouTube (economía e inversión)

Cada 3 horas este sistema revisa los canales de `config.yaml`, resume con Gemini los vídeos
nuevos, te los manda por **Telegram** (y por email si quieres) y guarda cada resumen como datos
estructurados para análisis futuros. Los domingos te llega un **informe comparativo** con el
sentimiento por tema y por canal.

Todo funciona gratis: GitHub Actions (servidor), plan gratuito de Gemini (resúmenes) y Telegram.

```
YouTube (RSS)  →  GitHub Actions cada 3 h  →  Gemini (ve el vídeo)  →  JSON + CSV en el repo
                                                                    →  Telegram / email
Domingos:  resúmenes de la semana  →  Gemini compara  →  Informe semanal por Telegram
```

---

## Instalación paso a paso (unos 15 minutos)

Necesitas: tu cuenta de GitHub, tu clave de Gemini (`AIza...`), el token de tu bot de Telegram
(`123456:AA...`) y tu chat ID (un número).

### 1. Crear el repositorio

1. En GitHub pulsa **+** (arriba a la derecha) → **New repository**.
2. Nombre: `resumenes-youtube`.
3. Visibilidad: **Public** (recomendado, ver nota abajo) o Private.
4. Marca **Add a README file** y pulsa **Create repository**.

> **¿Público o privado?** En repositorios públicos GitHub Actions es ilimitado y gratuito. En
> privados tienes 2.000 minutos al mes, que con 38 canales se pueden quedar cortos. Tus claves
> **no** se ven en ningún caso (van como "secrets"); lo único visible serían los resúmenes de
> vídeos que ya son públicos. Si prefieres privado, cambia en `.github/workflows/resumenes.yml`
> la línea `cron: "17 */3 * * *"` por `cron: "17 */6 * * *"` (cada 6 horas).

### 2. Subir los archivos

1. Descomprime el zip en tu ordenador.
2. En tu repositorio pulsa **Add file → Upload files**.
3. Arrastra **el contenido** de la carpeta descomprimida: `config.yaml`, `requirements.txt`,
   `README.md`, `.gitignore` y las carpetas `src`, `data` y `state`.
4. Pulsa **Commit changes**.

**Los dos archivos de automatización hay que crearlos a mano** (la carpeta `.github` está oculta
en Windows y Mac y no suele subirse arrastrando):

1. **Add file → Create new file**.
2. En el nombre escribe exactamente: `.github/workflows/resumenes.yml`
   (al escribir las barras `/` GitHub crea las carpetas solo).
3. Abre en tu ordenador el archivo `.github/workflows/resumenes.yml` del zip con el Bloc de notas,
   copia todo y pégalo. Pulsa **Commit changes**.
4. Repite con `.github/workflows/informe-semanal.yml`.

> En Mac, para ver la carpeta oculta en Finder pulsa `Cmd + Shift + .`
> En Windows: Explorador → Vista → Mostrar → Elementos ocultos.

### 3. Guardar tus claves como secrets

En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**.
Crea estos tres (el nombre tiene que ser exacto):

| Nombre               | Valor                           |
|----------------------|---------------------------------|
| `GEMINI_API_KEY`     | tu clave de Gemini              |
| `TELEGRAM_BOT_TOKEN` | el token que te dio BotFather   |
| `TELEGRAM_CHAT_ID`   | tu número de chat ID            |

**Email (opcional).** Si también quieres los resúmenes por correo con Gmail:

1. Activa la verificación en dos pasos en tu cuenta de Google.
2. Crea una contraseña de aplicación en https://myaccount.google.com/apppasswords
3. Añade los secrets `EMAIL_USUARIO` (tu Gmail), `EMAIL_PASSWORD` (la contraseña de aplicación,
   no la tuya normal) y opcionalmente `EMAIL_DESTINO` (si quieres recibirlo en otra dirección).

Si no creas estos secrets, simplemente no se envía email.

### 4. Dar permiso de escritura

**Settings → Actions → General → Workflow permissions** → marca **Read and write permissions**
→ **Save**. Sin esto los resúmenes no se pueden guardar en el repositorio.

### 5. Primeras pruebas

Ve a la pestaña **Actions** (si te pide activar los workflows, acéptalo).

1. **Comprobar canales.** Pulsa **Resúmenes de YouTube → Run workflow**, en *Qué hacer* elige
   `comprobar_canales` y dale a **Run workflow**. En un minuto te llega a Telegram la lista de
   canales encontrados y los que fallan.
2. **Probar un vídeo.** Run workflow con `prueba` y pega la URL de un vídeo en el segundo campo.
   Te llegará su resumen.
3. **Arrancar.** Run workflow con `normal`. A partir de ahí funciona solo cada 3 horas.

### Si algún canal no se encuentra

Algunos `@handle` de `config.yaml` pueden no ser exactos. Para arreglarlo:

1. Abre el canal en YouTube y mira la dirección: `youtube.com/@ESTE_ES_EL_HANDLE`.
2. En GitHub abre `config.yaml`, pulsa el lápiz ✏️, corrige el `handle` del canal y guarda.

Si aun así falla, añade el ID del canal (empieza por `UC`), que aparece en la página del canal en
**Más información → Compartir canal → Copiar ID del canal**:

```yaml
  - nombre: Los Locos de Wall Street
    handle: "@loslocosdewallstreet"
    channel_id: "UCxxxxxxxxxxxxxxxxxxxxxx"
```

---

## Cómo funciona el cupo gratuito

- El plan gratuito de Gemini permite unas **8 horas de vídeo de YouTube al día**, además de un
  límite de peticiones por minuto y por día.
- Con 38 canales llegan más horas de vídeo de las que caben, así que los vídeos **esperan en cola**
  y se resumen en las siguientes ejecuciones. El reparto es por turnos entre canales, para que
  ninguno acapare el cupo.
- Si un vídeo lleva más de 21 días en cola se descarta (`dias_maximos_en_cola`).
- Los medios que suben decenas de vídeos al día (Bloomberg, CNBC, WSJ, FT) están limitados con
  `max_por_revision`.
- Si se agota el cupo, el sistema para y sigue en la siguiente ejecución. **Nunca se cobra nada**
  mientras no actives la facturación en Google.

Para priorizar canales, desactiva los que menos te interesen con `activo: false`.

---

## Dónde quedan los datos (para tus análisis futuros)

| Archivo                                   | Contenido                                               |
|-------------------------------------------|---------------------------------------------------------|
| `data/resumenes/AAAA/MM/fecha_id.json`    | Resumen completo de cada vídeo (todos los campos)       |
| `data/resumenes.csv`                      | Una fila por vídeo: canal, fecha, sentimiento, tesis... |
| `data/sentimiento_por_tema.csv`           | Una fila por vídeo y tema, con su puntuación (-1 a +1) |
| `data/informes/AAAA-Sxx.md` y `.json`     | Informes semanales y sus estadísticas                   |

Los CSV se abren directamente en Excel o Google Sheets (en GitHub: abre el archivo → botón
**Download raw file**). `sentimiento_por_tema.csv` está pensado para hacer tablas dinámicas
y gráficos de evolución del sentimiento por tema o por canal.

Cada resumen incluye: resumen breve, 5–8 ideas clave, tesis principal, temas (con nombres
normalizados para poder comparar), activos mencionados, sentimiento general y por tema,
predicciones con horizonte, datos y argumentos, riesgos, participantes y nivel de convicción.

---

## Ajustes útiles en `config.yaml`

| Parámetro                    | Qué hace                                              |
|------------------------------|-------------------------------------------------------|
| `modelo`                     | Modelo de Gemini. Cámbialo si Google retira el actual |
| `idioma_resumen`             | Idioma de todos los resúmenes                         |
| `max_videos_por_ejecucion`   | Vídeos por ejecución (sube o baja según el cupo)      |
| `videos_iniciales_por_canal` | Vídeos que se resumen al añadir un canal nuevo        |
| `fps_video`                  | Fotogramas por segundo que mira Gemini (bajo = ahorra)|

Para cambiar el día u hora del informe semanal, edita la línea `cron` de
`.github/workflows/informe-semanal.yml` (está en hora UTC).

## Problemas frecuentes

- **No llega nada a Telegram:** revisa que escribiste al bot al menos una vez y que el chat ID y
  el token son correctos. En la pestaña Actions, abre la última ejecución para ver el error.
- **Error 404 / modelo no encontrado:** el modelo de `config.yaml` ya no existe; pon el "flash"
  más reciente de https://ai.google.dev/gemini-api/docs/models
- **"Cupo agotado" muy a menudo:** baja `max_videos_por_ejecucion` o desactiva canales.
- **El workflow dejó de ejecutarse solo:** GitHub pausa las tareas programadas de repositorios sin
  actividad en 60 días; como el sistema guarda resúmenes a menudo no debería ocurrir, pero si
  pasa, vuelve a activarlo desde la pestaña Actions.
