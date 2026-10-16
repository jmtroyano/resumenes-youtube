"use strict";
// Interfaz de la app. Solo habla con la API (/api/...), sin dependencias externas.

const estado = {
  canales: [],
  videos: [],            // vídeos cargados desde los feeds
  biblioteca: [],
  seleccion: new Map(),  // video_id -> {titulo, canal, publicado}
};

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const escHtml = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ utilidades
async function api(metodo, url, cuerpo) {
  const opciones = { method: metodo, headers: {} };
  if (cuerpo !== undefined) { opciones.headers["Content-Type"] = "application/json"; opciones.body = JSON.stringify(cuerpo); }
  const r = await fetch(url, opciones);
  let datos = {};
  try { datos = await r.json(); } catch { /* respuesta vacía */ }
  if (!r.ok) throw new Error(datos.error || `Error ${r.status}`);
  return datos;
}

let temporizadorAviso;
function aviso(texto, error = false, ms = 4000) {
  const el = $("#aviso");
  el.textContent = texto; el.className = "aviso" + (error ? " error" : ""); el.hidden = false;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => (el.hidden = true), error ? 8000 : ms);
}

async function trabajando(texto, funcion) {
  $("#cargando-texto").textContent = texto; $("#cargando").hidden = false;
  try { return await funcion(); }
  catch (e) { aviso(e.message, true); throw e; }
  finally { $("#cargando").hidden = true; }
}

function fecha(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "2-digit" }) +
    " " + d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

function claseSent(s) { return s && s.includes("alcista") ? "alcista" : s && s.includes("bajista") ? "bajista" : ""; }

// Markdown mínimo (títulos, listas, negritas, cursivas, enlaces, citas)
function markdown(md) {
  const lineas = escHtml(md).split("\n");
  let html = "", lista = false;
  const inline = (t) => t
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*]+?)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  for (const l of lineas) {
    const h = l.match(/^(#{1,6})\s+(.*)/);
    const li = l.match(/^\s*[-*•]\s+(.*)/) || l.match(/^\s*\d+[.)]\s+(.*)/);
    if (!li && lista) { html += "</ul>"; lista = false; }
    if (h) html += `<h${Math.min(h[1].length + 1, 4)}>${inline(h[2])}</h${Math.min(h[1].length + 1, 4)}>`;
    else if (li) { if (!lista) { html += "<ul>"; lista = true; } html += `<li>${inline(li[1])}</li>`; }
    else if (/^&gt;\s?/.test(l)) html += `<blockquote>${inline(l.replace(/^&gt;\s?/, ""))}</blockquote>`;
    else if (/^-{3,}$/.test(l.trim())) html += "<hr>";
    else if (l.trim()) html += `<p>${inline(l)}</p>`;
  }
  return html + (lista ? "</ul>" : "");
}

// ------------------------------------------------------------------ pestañas
function mostrarVista(nombre) {
  $$("#pestanas button").forEach((b) => b.classList.toggle("activa", b.dataset.vista === nombre));
  $$(".vista").forEach((v) => v.classList.toggle("activa", v.id === "vista-" + nombre));
  if (nombre === "biblioteca") cargarBiblioteca();
  if (nombre === "analisis") { pintarSeleccionAnalisis(); cargarListaAnalisis(); }
  if (nombre === "canales") pintarTablaCanales();
  if (nombre === "ajustes") cargarEstado();
}

// ------------------------------------------------------------------ estado / sync
async function cargarEstado() {
  const e = await api("GET", "/api/estado");
  const g = e.git || {};
  const el = $("#sync");
  if (!g.disponible) { el.textContent = "GitHub: no conectado"; el.className = "sync error"; }
  else if (g.ultimo_error) { el.textContent = "⚠ Error al sincronizar"; el.className = "sync error"; el.title = g.ultimo_error; }
  else if (g.en_curso || g.pendiente) { el.textContent = "⟳ Sincronizando…"; el.className = "sync"; }
  else { el.textContent = "✓ Sincronizado" + (g.ultimo_ok ? " " + g.ultimo_ok : ""); el.className = "sync ok"; el.title = g.ultimo_commit || ""; }
  $$(".estado-clave").forEach((s) => {
    const si = e.claves[s.dataset.clave];
    s.textContent = si ? "✓ configurada" : "✗ sin configurar"; s.className = "estado-clave " + (si ? "si" : "no");
  });
  $("#aj-modelo").value = e.modelo; $("#aj-idioma").value = e.idioma_resumen;
  $("#info-git").innerHTML = g.disponible
    ? `Último cambio: ${escHtml(g.ultimo_commit || "—")}<br>Cambios locales sin subir: ${g.cambios_sin_subir ?? 0}` +
      (g.ultimo_error ? `<br><span style="color:var(--rojo)">Último error: ${escHtml(g.ultimo_error)}</span>` : "")
    : "Esta copia no está conectada a GitHub.";
  if (!e.claves.GEMINI_API_KEY && !cargarEstado.avisado) {
    cargarEstado.avisado = true;
    aviso("Falta la clave de Gemini: ponla en Ajustes para resumir y analizar", true);
  }
  return e;
}

// ------------------------------------------------------------------ canales
async function cargarCanales() {
  estado.canales = (await api("GET", "/api/canales")).canales;
  pintarChecksCanales();
  const sel = $("#bib-canal"), actual = sel.value;
  sel.innerHTML = '<option value="">Todos los canales</option>' +
    estado.canales.map((c) => `<option>${escHtml(c.nombre)}</option>`).join("");
  sel.value = actual;
}

function pintarChecksCanales() {
  const filtro = $("#filtro-canales").value.toLowerCase();
  const marcados = new Set($$("#lista-canales-check input:checked").map((i) => i.value));
  $("#lista-canales-check").innerHTML = estado.canales
    .filter((c) => !filtro || c.nombre.toLowerCase().includes(filtro))
    .map((c) => `<label title="${c.activo ? "Resumen automático activo" : "En pausa"}">
      <input type="checkbox" value="${escHtml(c.clave)}" ${marcados.has(c.clave) ? "checked" : ""}>
      <span class="punto ${c.activo ? "on" : ""}"></span>${escHtml(c.nombre)}</label>`).join("");
}

function pintarTablaCanales() {
  const filtro = $("#filtro-tabla-canales").value.toLowerCase();
  $("#tabla-canales tbody").innerHTML = estado.canales
    .filter((c) => !filtro || JSON.stringify(c).toLowerCase().includes(filtro))
    .map((c) => `<tr data-clave="${escHtml(c.clave)}">
      <td><b>${escHtml(c.nombre)}</b><br><a class="ayuda" href="https://www.youtube.com/${c.handle ? escHtml(c.handle) : "channel/" + escHtml(c.channel_id)}" target="_blank">${escHtml(c.handle || c.channel_id || "")}</a></td>
      <td>${escHtml(c.region || "")}</td><td>${escHtml(c.idioma || "")}</td><td>${escHtml(c.tipo || "")}</td>
      <td><label class="interruptor"><input type="checkbox" class="t-activo" ${c.activo ? "checked" : ""}><span></span></label>
          <span class="ayuda">${c.activo ? "Automático" : "En pausa"}</span></td>
      <td class="acciones"><button class="t-videos">Ver vídeos</button> <button class="peligro t-borrar">Eliminar</button></td>
    </tr>`).join("");
}

async function cambiarActivo(clave, activo) {
  await api("PATCH", "/api/canales/" + encodeURIComponent(clave), { activo });
  await cargarCanales(); pintarTablaCanales();
  aviso(activo ? "Canal activado: se resumirá automáticamente" : "Canal en pausa");
  setTimeout(cargarEstado, 4000);
}

async function borrarCanal(clave) {
  const c = estado.canales.find((x) => x.clave === clave);
  if (!confirm(`¿Eliminar «${c.nombre}» de la lista? (Sus resúmenes y transcripts guardados se conservan)`)) return;
  await api("DELETE", "/api/canales/" + encodeURIComponent(clave));
  await cargarCanales(); pintarTablaCanales(); aviso("Canal eliminado");
}

async function anadirCanal() {
  const datos = { entrada: $("#nc-entrada").value, nombre: $("#nc-nombre").value, idioma: $("#nc-idioma").value,
    region: $("#nc-region").value, tipo: $("#nc-tipo").value, activo: $("#nc-activo").checked };
  const r = await trabajando("Buscando el canal en YouTube…", () => api("POST", "/api/canales", datos));
  ["#nc-entrada", "#nc-nombre", "#nc-region", "#nc-tipo"].forEach((s) => ($(s).value = ""));
  $("#nc-activo").checked = false;
  await cargarCanales(); pintarTablaCanales();
  aviso(`Añadido: ${r.canal.nombre}`);
}

// ------------------------------------------------------------------ vídeos
function tarjetaVideo(v) {
  const sel = estado.seleccion.has(v.video_id);
  const marcas = [];
  if (v.tiene_transcript) marcas.push('<span class="etiqueta ok">📝 transcript</span>');
  if (v.tiene_resumen) marcas.push(`<span class="etiqueta ${claseSent(v.sentimiento)}">${escHtml(v.sentimiento)} ${v.puntuacion > 0 ? "+" : ""}${(v.puntuacion ?? 0).toFixed(1)}</span>`);
  if (v.palabras) marcas.push(`<span class="etiqueta">${v.palabras.toLocaleString("es-ES")} palabras</span>`);
  const botones = [];
  if (v.tiene_transcript) botones.push(`<button class="btn-mini" data-ver="transcript">Ver texto</button>`);
  if (v.tiene_resumen) botones.push(`<button class="btn-mini" data-ver="resumen">Ver resumen</button>`);
  return `<div class="video ${sel ? "sel" : ""}" data-id="${v.video_id}">
    <div class="check">${sel ? "✓" : ""}</div>
    <img loading="lazy" src="${escHtml(v.miniatura)}" alt="">
    <div class="cuerpo">
      <div class="tit" title="${escHtml(v.titulo)}">${escHtml(v.titulo || v.video_id)}</div>
      <div class="meta">${escHtml(v.canal || "")} · ${fecha(v.publicado)}</div>
      <div class="marcas">${marcas.join("")} ${botones.join(" ")}
        <a class="btn-mini" href="https://www.youtube.com/watch?v=${v.video_id}" target="_blank" title="Abrir en YouTube">↗</a></div>
    </div></div>`;
}

function videosFiltrados() {
  const q = $("#filtro-videos").value.toLowerCase(), est = $("#filtro-estado").value;
  return estado.videos.filter((v) =>
    (!q || (v.titulo + " " + v.canal).toLowerCase().includes(q)) &&
    (!est || (est === "sin" && !v.tiene_transcript) || (est === "con" && v.tiene_transcript) || (est === "resumen" && v.tiene_resumen)));
}

function pintarVideos() {
  const lista = videosFiltrados();
  $("#lista-videos").innerHTML = lista.length ? lista.map(tarjetaVideo).join("")
    : '<p class="vacio">No hay vídeos que mostrar.</p>';
}

async function cargarVideos() {
  const claves = $$("#lista-canales-check input:checked").map((i) => i.value);
  if (!claves.length) return aviso("Marca al menos un canal", true);
  const mas = $("#opt-mas").checked ? "1" : "0", shorts = $("#opt-shorts").checked ? "1" : "0";
  const r = await trabajando(`Cargando vídeos de ${claves.length} canal(es)…`, () =>
    api("GET", `/api/videos?canales=${encodeURIComponent(claves.join(","))}&mas=${mas}&shorts=${shorts}`));
  const sueltos = estado.videos.filter((v) => v.suelto);
  estado.videos = [...sueltos, ...r.videos.filter((v) => !sueltos.some((s) => s.video_id === v.video_id))];
  $("#avisos-videos").innerHTML = r.errores.length ? `<p class="ayuda" style="color:var(--rojo)">${r.errores.map(escHtml).join("<br>")}</p>` : "";
  pintarVideos();
}

async function anadirVideoSuelto() {
  const url = $("#url-video").value.trim();
  if (!url) return;
  const r = await trabajando("Buscando el vídeo…", () => api("POST", "/api/videos/info", { url }));
  const v = { ...r.video, suelto: true };
  estado.videos = [v, ...estado.videos.filter((x) => x.video_id !== v.video_id)];
  alternarSeleccion(v, true);
  $("#url-video").value = ""; pintarVideos();
}

// ------------------------------------------------------------------ selección
function alternarSeleccion(v, forzar) {
  const ya = estado.seleccion.has(v.video_id);
  const poner = forzar === undefined ? !ya : forzar;
  if (poner) estado.seleccion.set(v.video_id, { titulo: v.titulo, canal: v.canal, publicado: v.publicado || "" });
  else estado.seleccion.delete(v.video_id);
  pintarBarra();
}

function pintarBarra() {
  const n = estado.seleccion.size;
  $("#barra-accion").hidden = n === 0;
  $("#num-sel").textContent = `${n} seleccionado${n === 1 ? "" : "s"}`;
  $$(".video").forEach((el) => {
    const s = estado.seleccion.has(el.dataset.id);
    el.classList.toggle("sel", s); $(".check", el).textContent = s ? "✓" : "";
  });
}

function buscarVideo(id) {
  return estado.videos.find((v) => v.video_id === id) || estado.biblioteca.find((v) => v.video_id === id);
}

function alClicarVideo(ev) {
  const tarjeta = ev.target.closest(".video");
  if (!tarjeta || ev.target.closest("a")) return;
  const v = buscarVideo(tarjeta.dataset.id);
  const ver = ev.target.closest("[data-ver]");
  if (ver) return verDetalle(v, ver.dataset.ver);
  alternarSeleccion(v);
}

// ------------------------------------------------------------------ acciones
function actualizarMarcas(ids, cambios) {
  for (const lista of [estado.videos, estado.biblioteca])
    for (const v of lista) if (ids[v.video_id]) Object.assign(v, ids[v.video_id]);
  pintarVideos(); pintarBiblioteca();
}

function mostrarResultados(titulo, resultados) {
  const ok = resultados.filter((r) => r.ok).length;
  const html = `<h3>${escHtml(titulo)}</h3><p>${ok} de ${resultados.length} correctos.</p><ul class="resultado-lista">` +
    resultados.map((r) => {
      const v = buscarVideo(r.video_id) || estado.seleccion.get(r.video_id) || {};
      return `<li class="${r.ok ? "" : "mal"}">${escHtml(v.titulo || r.video_id)}: ${r.ok
        ? (r.ya_existia ? "ya tenía resumen" : r.palabras ? `${r.palabras.toLocaleString("es-ES")} palabras (${r.idioma}${r.automatico ? ", automático" : ""})` : r.sentimiento ? `${r.sentimiento} (desde ${r.fuente})` : "ok")
        : escHtml(r.error)}</li>`;
    }).join("") + "</ul>";
  abrirDetalle(html);
}

async function descargarTranscripts() {
  const ids = [...estado.seleccion.keys()];
  const metas = Object.fromEntries(estado.seleccion);
  const r = await trabajando(`Descargando ${ids.length} transcript(s) desde tu conexión…`, () =>
    api("POST", "/api/transcripts", { video_ids: ids, metas }));
  const cambios = {};
  for (const x of r.resultados) if (x.ok) cambios[x.video_id] = { tiene_transcript: true, palabras: x.palabras };
  actualizarMarcas(cambios);
  mostrarResultados("Transcripts", r.resultados);
  setTimeout(cargarEstado, 5000);
}

async function resumirSeleccion() {
  const ids = [...estado.seleccion.keys()];
  const sinTexto = ids.filter((id) => !(buscarVideo(id) || {}).tiene_transcript);
  let permitirVideo = false;
  if (sinTexto.length) {
    permitirVideo = confirm(`${sinTexto.length} vídeo(s) no tienen transcript.\n\nAceptar: resumirlos viendo el vídeo (más lento y gasta más cupo).\nCancelar: resumir solo los que tienen transcript.`);
  }
  const r = await trabajando(`Resumiendo ${ids.length} vídeo(s) con Gemini…`, () =>
    api("POST", "/api/resumir", { video_ids: ids, metas: Object.fromEntries(estado.seleccion),
      permitir_video: permitirVideo, enviar_telegram: $("#opt-tg-resumen").checked }));
  const cambios = {};
  for (const x of r.resultados) if (x.ok && !x.ya_existia) cambios[x.video_id] = { tiene_resumen: true, sentimiento: x.sentimiento, puntuacion: x.puntuacion };
  actualizarMarcas(cambios);
  mostrarResultados("Resúmenes", r.resultados);
  avisoTelegram(r.telegram);
}

function avisoTelegram(t) {
  if (!t) return;
  if (t.enviado) aviso("Enviado a Telegram ✓");
  else aviso("No se envió a Telegram: " + t.motivo, true);
}

// ------------------------------------------------------------------ detalle
function abrirDetalle(html) { $("#detalle-contenido").innerHTML = html; $("#detalle").hidden = false; }

async function verDetalle(v, tipo) {
  if (tipo === "transcript") {
    const { transcript: t } = await trabajando("Abriendo transcript…", () => api("GET", "/api/transcripts/" + v.video_id));
    abrirDetalle(`<h3>${escHtml(t.titulo)}</h3><p class="ayuda">${escHtml(t.canal)} · ${t.palabras?.toLocaleString("es-ES")} palabras · ${escHtml(t.idioma)}${t.es_automatico ? " (subtítulos automáticos)" : ""}</p><pre>${escHtml(t.texto)}</pre>`);
  } else {
    const { resumen: reg } = await trabajando("Abriendo resumen…", () => api("GET", "/api/resumenes/" + v.video_id));
    const r = reg.resumen;
    const lista = (t, xs) => xs?.length ? `<h3>${t}</h3><ul>${xs.map((x) => `<li>${escHtml(x)}</li>`).join("")}</ul>` : "";
    abrirDetalle(`<h3>${escHtml(reg.titulo)}</h3>
      <p class="ayuda">${escHtml(reg.canal)} · ${fecha(reg.fecha_publicacion)} · resumido desde ${escHtml(reg.fuente || "vídeo")}</p>
      <p><span class="etiqueta ${claseSent(r.sentimiento_general)}">${escHtml(r.sentimiento_general)} ${r.puntuacion_sentimiento > 0 ? "+" : ""}${r.puntuacion_sentimiento.toFixed(2)}</span> · Convicción ${escHtml(r.nivel_conviccion)}</p>
      <p>${escHtml(r.resumen_breve)}</p>
      ${lista("Ideas clave", r.ideas_clave)}
      <h3>Tesis</h3><p>${escHtml(r.tesis_principal)}</p>
      ${lista("Por tema", r.sentimiento_por_tema.map((s) => `${s.tema} (${s.puntuacion > 0 ? "+" : ""}${s.puntuacion}): ${s.justificacion}`))}
      ${lista("Predicciones", r.predicciones.map((p) => `${p.afirmacion} — ${p.horizonte}`))}
      ${lista("Datos y argumentos", r.datos_y_argumentos)}
      ${lista("Riesgos", r.riesgos_mencionados)}
      ${lista("Participantes", r.participantes)}`);
  }
}

// ------------------------------------------------------------------ biblioteca
async function cargarBiblioteca() {
  const q = encodeURIComponent($("#bib-q").value), canal = encodeURIComponent($("#bib-canal").value), dias = $("#bib-dias").value;
  estado.biblioteca = (await api("GET", `/api/biblioteca?q=${q}&canal=${canal}&dias=${dias}`)).videos;
  pintarBiblioteca();
}
function pintarBiblioteca() {
  $("#lista-biblioteca").innerHTML = estado.biblioteca.length ? estado.biblioteca.map(tarjetaVideo).join("")
    : '<p class="vacio">Todavía no hay vídeos guardados con estos filtros.</p>';
  pintarBarra();
}

// ------------------------------------------------------------------ análisis
function pintarSeleccionAnalisis() {
  const chips = [...estado.seleccion.entries()].map(([id, v]) =>
    `<span class="chip">${escHtml((v.canal ? v.canal + ": " : "") + (v.titulo || id)).slice(0, 70)}<button data-quitar="${id}">✕</button></span>`);
  $("#analisis-seleccion").innerHTML = chips.length ? chips.join("")
    : '<p class="ayuda">Selecciona vídeos en <b>Vídeos</b> o <b>Biblioteca</b> (necesitan transcript o resumen).</p>';
}

async function cargarListaAnalisis() {
  const { analisis } = await api("GET", "/api/analisis");
  $("#lista-analisis").innerHTML = analisis.length ? analisis.map((a) =>
    `<a href="#" data-analisis="${escHtml(a.id)}">${escHtml(a.titulo)}<small>${fecha(a.fecha)} · ${a.videos.length} vídeos</small></a>`).join("")
    : '<p class="ayuda">Aún no hay análisis.</p>';
}

function pintarAnalisis(a) {
  const videos = a.videos.map((v) => `<li>${escHtml(v.canal)} — <a href="https://www.youtube.com/watch?v=${v.video_id}" target="_blank">${escHtml(v.titulo || v.video_id)}</a> <span class="ayuda">(${escHtml(v.fuente)})</span></li>`).join("");
  $("#resultado-analisis").innerHTML = `<div class="md"><h1>${escHtml(a.titulo)}</h1>
    <p class="ayuda">${fecha(a.fecha)} · ${escHtml(a.autor || "")}
      <button class="btn-mini" id="btn-analisis-tg" data-id="${escHtml(a.id)}">📨 Enviar a Telegram</button></p>
    ${(a.avisos || []).length ? `<p class="ayuda" style="color:var(--rojo)">${a.avisos.map(escHtml).join("<br>")}</p>` : ""}
    <details><summary class="ayuda">${a.videos.length} vídeos analizados · petición</summary><ul>${videos}</ul><p class="ayuda">${escHtml(a.instruccion)}</p></details>
    ${markdown(a.markdown)}</div>`;
  $("#resultado-analisis").scrollIntoView({ behavior: "smooth" });
}

async function analizar() {
  const ids = [...estado.seleccion.keys()];
  if (!ids.length) return aviso("Selecciona primero algunos vídeos", true);
  const r = await trabajando(`Analizando ${ids.length} vídeo(s) con Gemini… (puede tardar un minuto)`, () =>
    api("POST", "/api/analizar", { video_ids: ids, titulo: $("#an-titulo").value, instruccion: $("#an-instruccion").value,
      modo: $("#an-modo").value, enviar_telegram: $("#an-telegram").checked }));
  pintarAnalisis(r.analisis); cargarListaAnalisis();
  avisoTelegram(r.telegram);
}

// ------------------------------------------------------------------ ajustes
async function guardarClaves() {
  const datos = {};
  for (const k of ["GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]) {
    const v = $("#k-" + k).value.trim(); if (v) datos[k] = v;
  }
  if (!Object.keys(datos).length) return aviso("No has escrito ninguna clave nueva");
  await api("POST", "/api/ajustes/claves", datos);
  $$("[id^=k-]").forEach((i) => (i.value = ""));
  aviso("Claves guardadas en tu ordenador"); cargarEstado();
}

// ------------------------------------------------------------------ eventos
function eventos() {
  $("#pestanas").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) mostrarVista(b.dataset.vista); });
  $("#filtro-canales").addEventListener("input", pintarChecksCanales);
  $("#sel-todos").onclick = (e) => { e.preventDefault(); $$("#lista-canales-check input").forEach((i) => (i.checked = true)); };
  $("#sel-ninguno").onclick = (e) => { e.preventDefault(); $$("#lista-canales-check input").forEach((i) => (i.checked = false)); };
  $("#sel-activos").onclick = (e) => {
    e.preventDefault();
    const activos = new Set(estado.canales.filter((c) => c.activo).map((c) => c.clave));
    $$("#lista-canales-check input").forEach((i) => (i.checked = activos.has(i.value)));
  };
  $("#btn-cargar").onclick = cargarVideos;
  $("#btn-url").onclick = anadirVideoSuelto;
  $("#url-video").addEventListener("keydown", (e) => e.key === "Enter" && anadirVideoSuelto());
  $("#filtro-videos").addEventListener("input", pintarVideos);
  $("#filtro-estado").addEventListener("change", pintarVideos);
  $("#sel-videos-todos").onclick = (e) => { e.preventDefault(); videosFiltrados().forEach((v) => alternarSeleccion(v, true)); };
  $("#sel-bib-todos").onclick = (e) => { e.preventDefault(); estado.biblioteca.forEach((v) => alternarSeleccion(v, true)); };
  $("#lista-videos").addEventListener("click", alClicarVideo);
  $("#lista-biblioteca").addEventListener("click", alClicarVideo);
  let t; for (const id of ["#bib-q", "#bib-canal", "#bib-dias"])
    $(id).addEventListener("input", () => { clearTimeout(t); t = setTimeout(cargarBiblioteca, 300); });

  $("#btn-limpiar-sel").onclick = (e) => { e.preventDefault(); estado.seleccion.clear(); pintarBarra(); pintarSeleccionAnalisis(); };
  $("#btn-transcripts").onclick = descargarTranscripts;
  $("#btn-resumir").onclick = resumirSeleccion;
  $("#btn-ir-analisis").onclick = () => mostrarVista("analisis");
  $("#analisis-seleccion").addEventListener("click", (e) => {
    const b = e.target.closest("[data-quitar]"); if (!b) return;
    estado.seleccion.delete(b.dataset.quitar); pintarBarra(); pintarSeleccionAnalisis();
  });
  $("#btn-analizar").onclick = analizar;
  $("#lista-analisis").addEventListener("click", async (e) => {
    const a = e.target.closest("[data-analisis]"); if (!a) return; e.preventDefault();
    pintarAnalisis((await api("GET", "/api/analisis/" + encodeURIComponent(a.dataset.analisis))).analisis);
  });

  $("#btn-anadir-canal").onclick = anadirCanal;
  $("#filtro-tabla-canales").addEventListener("input", pintarTablaCanales);
  $("#tabla-canales").addEventListener("change", (e) => {
    if (e.target.classList.contains("t-activo")) cambiarActivo(e.target.closest("tr").dataset.clave, e.target.checked).catch((x) => aviso(x.message, true));
  });
  $("#tabla-canales").addEventListener("click", (e) => {
    const tr = e.target.closest("tr"); if (!tr) return;
    if (e.target.classList.contains("t-borrar")) borrarCanal(tr.dataset.clave).catch((x) => aviso(x.message, true));
    if (e.target.classList.contains("t-videos")) {
      mostrarVista("videos");
      $$("#lista-canales-check input").forEach((i) => (i.checked = i.value === tr.dataset.clave));
      cargarVideos();
    }
  });

  $("#btn-guardar-claves").onclick = () => guardarClaves().catch((x) => aviso(x.message, true));
  $("#btn-probar-ia").onclick = () => trabajando("Probando Gemini…", () => api("POST", "/api/ajustes/probar-ia"))
    .then((r) => aviso("Gemini responde: " + r.respuesta)).catch(() => {});
  $("#btn-guardar-ajustes").onclick = () => api("POST", "/api/ajustes", { modelo: $("#aj-modelo").value, idioma_resumen: $("#aj-idioma").value })
    .then(() => aviso("Ajustes guardados")).catch((x) => aviso(x.message, true));
  $("#btn-bajar").onclick = () => trabajando("Trayendo novedades de GitHub…", () => api("POST", "/api/sync/bajar")).then(() => { aviso("Actualizado"); cargarEstado(); cargarCanales(); });
  $("#btn-subir").onclick = () => trabajando("Subiendo cambios a GitHub…", () => api("POST", "/api/sync/subir")).then(() => { aviso("Subido"); cargarEstado(); });
  $("#resultado-analisis").addEventListener("click", (e) => {
    const b = e.target.closest("#btn-analisis-tg"); if (!b) return;
    trabajando("Enviando a Telegram…", () => api("POST", `/api/analisis/${encodeURIComponent(b.dataset.id)}/telegram`))
      .then(() => aviso("Enviado a Telegram ✓")).catch(() => {});
  });
  $("#btn-detectar-chat").onclick = () => trabajando("Buscando tu chat en Telegram…", () => api("POST", "/api/ajustes/telegram/detectar"))
    .then((r) => { aviso(`Chat ID guardado (${r.nombre || "tu chat"})`); cargarEstado(); }).catch(() => {});
  $("#btn-probar-telegram").onclick = () => trabajando("Enviando mensaje de prueba…", () => api("POST", "/api/ajustes/telegram/probar"))
    .then(() => aviso("Mensaje de prueba enviado ✓")).catch(() => {});
  $("#btn-reiniciar").onclick = async () => {
    try { await api("POST", "/api/reiniciar"); } catch { /* el servidor se cierra */ }
    $("#cargando-texto").textContent = "Reiniciando la app…"; $("#cargando").hidden = false;
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      try { await api("GET", "/api/estado"); location.reload(); return; } catch { /* aún no */ }
    }
    $("#cargando").hidden = true; aviso("La app no ha vuelto a arrancar. Ábrela desde el acceso directo.", true);
  };
  $("#cerrar-detalle").onclick = () => ($("#detalle").hidden = true);
  document.addEventListener("keydown", (e) => e.key === "Escape" && ($("#detalle").hidden = true));
}

// ------------------------------------------------------------------ inicio
(async function iniciar() {
  eventos();
  try {
    await cargarCanales();
    $("#an-instruccion").value = (await api("GET", "/api/analisis/instruccion")).instruccion;
    await cargarEstado();
  } catch (e) { aviso(e.message, true); }
  setInterval(() => cargarEstado().catch(() => {}), 20000);
})();
