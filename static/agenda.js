"use strict";
// Agenda / Kanban de prazos. Usa utilidades de app.js ($, api, esc, toast, fmtData, estado, abrirPainel...).

const COLUNAS = [
  ["sugerido", "Sugeridos", "aguardando confirmação"],
  ["a_fazer", "A fazer", ""],
  ["andamento", "Em andamento", ""],
  ["aguardando", "Aguardando terceiros", ""],
  ["concluido", "Concluído", ""],
];
const NOME_STATUS = Object.fromEntries(COLUNAS.map(([k, n]) => [k, n]));
const URGENCIAS = [
  ["vencido", "Vencidos"], ["hoje", "Vencem hoje"], ["amanha", "Próximo dia útil"],
  ["ate5", "Até 5 dias úteis"], ["folgado", "Folgados"], ["sem_data", "Sem data"],
];
const SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
  "novembro", "dezembro"];

const ag = {
  tarefas: [], visao: lerPreferencia("ag-visao") || "kanban", calModo: "mes", calRef: new Date(),
  editando: null, checklist: [], calculo: undefined, arrastando: null, feriadosCache: {},
};

// ---------- utilidades ----------
function dataBr(iso, comSemana = true) {
  if (!iso) return "";
  const [a, m, d] = iso.slice(0, 10).split("-").map(Number);
  const dt = new Date(a, m - 1, d);
  return `${String(d).padStart(2, "0")}/${String(m).padStart(2, "0")}` + (comSemana ? ` (${SEMANA[dt.getDay()]})` : "");
}

function rotuloUrgencia(t) {
  const n = t.dias_restantes;
  switch (t.urgencia) {
    case "vencido": return `Vencido há ${-n || 1} dia${-n > 1 ? "s" : ""} út.`;
    case "hoje": return "Vence hoje";
    case "amanha": {
      const amanha = isoLocal(new Date(Date.now() + 864e5));
      return t.prazo_fatal === amanha ? "Vence amanhã" : "Vence no próximo dia útil";
    }
    case "ate5": case "folgado": return `${n} dia${n > 1 ? "s" : ""} úte${n > 1 ? "is" : "il"}`;
    case "concluido": return "Concluído";
    default: return "Sem data";
  }
}

function advogadasDaTarefa(t) {
  if (t.advogada_id) return [advogadaPorId(t.advogada_id)].filter(Boolean);
  return t.advogadas_processo.map(advogadaPorId).filter(Boolean); // sem responsável: mostra as do processo
}

// ---------- carregar e filtrar ----------
async function carregarAgenda() {
  const d = await api("/api/agenda");
  ag.tarefas = d.tarefas;
  ag.regras = d.regras;
  if (!estado.advogadas.length) await carregarEstado();
  preencherFiltrosAgenda();
  renderAgenda();
  carregarAlertas();
}

function filtrosAgenda() {
  return {
    adv: $("#ag-f-adv").value, proc: $("#ag-f-proc").value.trim(), status: $("#ag-f-status").value,
    de: $("#ag-f-de").value, ate: $("#ag-f-ate").value,
  };
}

function tarefasFiltradas() {
  const f = filtrosAgenda();
  const digitos = f.proc.replace(/\D/g, "");
  const texto = f.proc.toLowerCase();
  return ag.tarefas.filter((t) => {
    if (f.adv) {
      const id = Number(f.adv);
      if (!(t.advogada_id === id || (!t.advogada_id && t.advogadas_processo.includes(id)))) return false;
    }
    if (f.proc) {
      const casaNum = digitos.length >= 4 && (t.numero || "").includes(digitos);
      const casaTxt = (t.partes || "").toLowerCase().includes(texto) || (t.numero_fmt || "").includes(f.proc);
      if (!casaNum && !casaTxt) return false;
    }
    if (f.status === "abertos" && t.status === "concluido") return false;
    if (f.status && f.status !== "abertos" && t.status !== f.status) return false;
    if ((f.de || f.ate) && !t.prazo_fatal) return false;
    if (f.de && t.prazo_fatal < f.de) return false;
    if (f.ate && t.prazo_fatal > f.ate) return false;
    return true;
  });
}

function preencherFiltrosAgenda() {
  const sel = $("#ag-f-adv"), atual = sel.value;
  sel.innerHTML = `<option value="">Todas as advogadas</option>` +
    estado.advogadas.map((a) => `<option value="${a.id}" ${String(a.id) === atual ? "selected" : ""}>${esc(a.nome)}</option>`).join("");
  const procs = new Map();
  ag.tarefas.forEach((t) => t.numero && procs.set(t.numero_fmt, t.partes));
  estado.processos.forEach((p) => procs.set(p.numero_fmt, partesTexto(p)));
  $("#ag-processos").innerHTML = [...procs].map(([n, p]) => `<option value="${esc(n)}">${esc(p || "")}</option>`).join("");
}

function renderAgenda() {
  const lista = tarefasFiltradas();
  renderContadores(lista);
  document.querySelectorAll("#ag-visao [data-visao]").forEach((b) => b.classList.toggle("ativa", b.dataset.visao === ag.visao));
  $("#ag-kanban").hidden = ag.visao !== "kanban";
  $("#ag-calendario").hidden = ag.visao !== "calendario";
  $("#ag-lista").hidden = ag.visao !== "lista";
  if (ag.visao === "kanban") renderKanban(lista);
  else if (ag.visao === "calendario") renderCalendario(lista);
  else renderLista(lista);
  $("#ag-limpar").hidden = !Object.values(filtrosAgenda()).some(Boolean);
}

function renderContadores(lista) {
  const abertas = lista.filter((t) => t.status !== "concluido");
  const cont = (u) => abertas.filter((t) => t.urgencia === u).length;
  const chips = URGENCIAS.filter(([u]) => u !== "sem_data" || cont(u))
    .map(([u, nome]) => `<span class="chip u-${u}"><b>${cont(u)}</b> ${nome}</span>`);
  const sug = lista.filter((t) => t.status === "sugerido").length;
  chips.push(`<span class="chip"><b>${sug}</b> sugeridos</span>`);
  chips.push(`<span class="chip"><b>${lista.filter((t) => t.status === "concluido").length}</b> concluídos</span>`);
  $("#ag-contadores").innerHTML = chips.join("");
}

// ---------- cartão ----------
function cartaoHTML(t) {
  const advs = advogadasDaTarefa(t);
  const feitos = t.checklist.filter((c) => c.feito).length;
  const sug = t.status === "sugerido";
  return `
    <article class="cartao u-${t.urgencia}" draggable="true" data-id="${t.id}">
      <div class="c-topo">
        ${sug ? `<input type="checkbox" class="c-sel" data-sel="${t.id}" aria-label="Selecionar">` : ""}
        <span class="c-urg">${rotuloUrgencia(t)}</span>
        ${t.prioridade === "alta" ? `<span class="c-tag prio">alta</span>` : ""}
        ${t.tipo === "audiencia" ? `<span class="c-tag">audiência</span>` : ""}
        <span class="c-tag ${t.origem === "djen" ? "djen" : ""}">${t.origem === "djen" ? "DJEN" : "manual"}</span>
      </div>
      <div class="c-titulo">${esc(t.titulo)}</div>
      ${t.numero ? `<button class="link c-proc" type="button" data-proc="${t.numero}">${esc(t.numero_fmt)}</button>
        ${t.partes ? `<div class="c-partes">${esc(t.partes)}</div>` : ""}` : ""}
      ${t.prazo_fatal ? `<div class="c-datas">${t.tipo === "audiencia" ? "Data" : "Fatal"}: <b>${dataBr(t.prazo_fatal)}</b>${t.hora ? ` ${esc(t.hora)}` : ""}
        ${t.data_interna && t.data_interna !== t.prazo_fatal ? ` · interno ${dataBr(t.data_interna, false)}` : ""}</div>` : ""}
      <div class="c-rodape">
        ${advs.map(etiquetaAdv).join("")}${!t.advogada_id && advs.length > 1 ? `<span class="c-def">definir</span>` : ""}
        ${t.checklist.length ? `<span class="c-check">☑ ${feitos}/${t.checklist.length}</span>` : ""}
        ${t.observacoes ? `<span class="c-check" title="${esc(t.observacoes)}">✎</span>` : ""}
      </div>
      ${t.conferir ? `<div class="c-aviso">⚠ conferir manualmente</div>` : ""}
      ${sug ? `<div class="c-acoes">
        <button class="btn mini primario" type="button" data-acao="confirmar">Confirmar</button>
        <button class="btn mini" type="button" data-acao="editar">Editar</button>
        <button class="btn mini perigo" type="button" data-acao="descartar">Descartar</button></div>` : ""}
    </article>`;
}

// ---------- kanban ----------
function renderKanban(lista) {
  $("#ag-kanban").innerHTML = COLUNAS.map(([st, nome, sub]) => {
    const cards = lista.filter((t) => t.status === st);
    const lote = st === "sugerido" && cards.length ? `
      <div class="col-lote">
        <label class="chk"><input type="checkbox" data-sel-todos> todos</label>
        <button class="link pequeno" type="button" data-lote="confirmar">Confirmar selecionados</button>
        <button class="link pequeno perigo-txt" type="button" data-lote="descartar">Descartar</button>
      </div>` : "";
    return `
      <section class="coluna" data-status="${st}">
        <header class="col-cab"><h3>${nome} <span class="qtd">${cards.length}</span></h3>${sub ? `<small>${sub}</small>` : ""}</header>
        ${lote}
        <div class="col-cartoes">${cards.map(cartaoHTML).join("") || `<p class="nada col-vazia">Arraste cartões para cá</p>`}</div>
      </section>`;
  }).join("");
}

async function moverTarefa(id, status) {
  const t = ag.tarefas.find((x) => x.id === id);
  if (!t || t.status === status) return;
  t.status = status;
  renderAgenda();
  try {
    await api(`/api/agenda/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
  } catch (e) {
    toast("Erro: " + e.message);
  }
  carregarAgenda();
}

async function emLote(ids, acao) {
  if (!ids.length) { toast("Selecione pelo menos um cartão."); return; }
  if (acao === "descartar" && !confirm(`Descartar ${ids.length} sugestão(ões)? A publicação não volta a gerar sugestão.`)) return;
  const r = await api("/api/agenda/lote", { method: "POST", body: JSON.stringify({ ids, acao }) });
  toast(`${r.alterados} ${acao === "confirmar" ? "confirmado(s): foram para A fazer" : "descartado(s)"}.`);
  carregarAgenda();
}

// ---------- calendário ----------
function inicioSemana(d) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - x.getDay());
  return x;
}

async function feriadosNoPeriodo(de, ate) {
  const chave = `${de}|${ate}`;
  if (!ag.feriadosCache[chave]) ag.feriadosCache[chave] = api(`/api/feriados/dias?de=${de}&ate=${ate}`).catch(() => []);
  return ag.feriadosCache[chave];
}

async function renderCalendario(lista) {
  const ref = ag.calRef;
  let ini, dias;
  if (ag.calModo === "mes") {
    ini = inicioSemana(new Date(ref.getFullYear(), ref.getMonth(), 1));
    const fimMes = new Date(ref.getFullYear(), ref.getMonth() + 1, 0);
    dias = Math.ceil(((fimMes - ini) / 864e5 + 1) / 7) * 7;
    const mes = MESES[ref.getMonth()];
    $("#cal-titulo").textContent = `${mes[0].toUpperCase() + mes.slice(1)} de ${ref.getFullYear()}`;
  } else {
    ini = inicioSemana(ref);
    dias = 7;
    const fim = new Date(ini.getTime() + 6 * 864e5);
    $("#cal-titulo").textContent = `${dataBr(isoLocal(ini), false)} a ${dataBr(isoLocal(fim), false)}/${fim.getFullYear()}`;
  }
  document.querySelectorAll("#cal-modo [data-modo]").forEach((b) => b.classList.toggle("ativa", b.dataset.modo === ag.calModo));
  const datas = Array.from({ length: dias }, (_, i) => isoLocal(new Date(ini.getFullYear(), ini.getMonth(), ini.getDate() + i)));
  const feriados = await feriadosNoPeriodo(datas[0], datas[datas.length - 1]);
  const hoje = isoLocal(new Date());
  const porDia = (campo) => lista.reduce((m, t) => (t[campo] && (m[t[campo]] ||= []).push(t), m), {});
  const fatais = porDia("prazo_fatal"), internas = porDia("data_interna");
  $("#cal-grade").className = `cal-grade ${ag.calModo}`;
  $("#cal-grade").innerHTML = SEMANA.map((s) => `<div class="cal-cab">${s}</div>`).join("") + datas.map((iso) => {
    const dt = new Date(iso + "T12:00:00");
    const fora = ag.calModo === "mes" && dt.getMonth() !== ref.getMonth();
    const fer = feriados.filter((f) => f.data === iso);
    const chips = (fatais[iso] || []).map((t) =>
      `<button type="button" class="cal-chip u-${t.urgencia}" data-id="${t.id}" title="${esc(t.titulo)} — ${esc(t.numero_fmt)}">${t.hora && !t.titulo.includes(t.hora) ? esc(t.hora) + " " : ""}${esc(t.titulo)}</button>`);
    const ints = (internas[iso] || []).filter((t) => t.data_interna !== t.prazo_fatal && t.status !== "concluido").map((t) =>
      `<button type="button" class="cal-chip interno" data-id="${t.id}" title="Data interna: ${esc(t.titulo)}">↳ ${esc(t.titulo)}</button>`);
    return `<div class="cal-dia ${fora ? "fora" : ""} ${iso === hoje ? "hoje" : ""} ${fer.length || dt.getDay() % 6 === 0 ? "nao-util" : ""}" data-dia="${iso}">
      <div class="cal-num">${dt.getDate()}</div>
      ${fer.map((f) => `<div class="cal-fer" title="${esc(f.descricao)}${f.tribunais ? " — " + esc(f.tribunais) : ""}${f.comarca ? " — " + esc(f.comarca) : ""}">${esc(f.descricao)}${f.tribunais ? ` <small>(${esc(f.tribunais.length > 12 ? "alguns tribunais" : f.tribunais)})</small>` : ""}</div>`).join("")}
      ${chips.join("")}${ints.join("")}
    </div>`;
  }).join("");
}

// ---------- lista por data ----------
function renderLista(lista) {
  const hoje = isoLocal(new Date());
  const grupos = new Map();
  [...lista].sort((a, b) => (a.prazo_fatal || "9999").localeCompare(b.prazo_fatal || "9999")).forEach((t) => {
    const k = !t.prazo_fatal ? "sem" : (t.prazo_fatal < hoje && t.status !== "concluido" ? "vencidos" : t.prazo_fatal);
    if (!grupos.has(k)) grupos.set(k, []);
    grupos.get(k).push(t);
  });
  const titulo = (k) => k === "sem" ? "Sem data" : k === "vencidos" ? "⚠ Vencidos" :
    `${dataBr(k)}${k === hoje ? " — hoje" : ""} <small>${k.slice(0, 4)}</small>`;
  const ordem = [...grupos.keys()].sort((a, b) => (a === "vencidos" ? -1 : b === "vencidos" ? 1 : a === "sem" ? 1 : b === "sem" ? -1 : a.localeCompare(b)));
  $("#ag-lista").innerHTML = ordem.map((k) => `
    <section class="lista-grupo"><h3>${titulo(k)}</h3>
      ${grupos.get(k).map((t) => `
        <div class="lista-item u-${t.urgencia}" data-id="${t.id}">
          <span class="c-urg">${rotuloUrgencia(t)}</span>
          <span class="li-titulo">${esc(t.titulo)}${t.hora && !t.titulo.includes(t.hora) ? ` · ${esc(t.hora)}` : ""}</span>
          ${t.numero ? `<button class="link c-proc" type="button" data-proc="${t.numero}">${esc(t.numero_fmt)}</button>` : "<span></span>"}
          <span class="li-adv">${advogadasDaTarefa(t).map(etiquetaAdv).join("")}</span>
          <span class="li-status">${NOME_STATUS[t.status] || t.status}${t.conferir ? " · ⚠ conferir" : ""}</span>
        </div>`).join("")}
    </section>`).join("") || `<p class="vazio">Nenhuma tarefa com esses filtros.</p>`;
}

// ---------- editar / criar ----------
function abrirTarefa(t, padrao = {}) {
  ag.editando = t || null;
  const x = t || { titulo: "", tipo: "tarefa", status: "a_fazer", prioridade: "media", checklist: [], ...padrao };
  ag.checklist = JSON.parse(JSON.stringify(x.checklist || []));
  ag.calculo = undefined; // só envia se recalcular
  $("#t-titulo-dlg").textContent = t ? (t.status === "sugerido" ? "Prazo sugerido" : "Editar") : "Nova tarefa";
  $("#t-titulo").value = x.titulo || "";
  $("#t-tipo").value = x.tipo || "tarefa";
  $("#t-status").innerHTML = COLUNAS.map(([k, n]) => `<option value="${k}" ${k === x.status ? "selected" : ""}>${n}</option>`).join("");
  $("#t-numero").value = x.numero_fmt || x.numero || "";
  $("#t-adv").innerHTML = `<option value="">— as duas / a definir —</option>` +
    estado.advogadas.map((a) => `<option value="${a.id}" ${a.id === x.advogada_id ? "selected" : ""}>${esc(a.nome)}</option>`).join("");
  $("#t-fatal").value = x.prazo_fatal || "";
  $("#t-interna").value = x.data_interna || "";
  $("#t-hora").value = x.hora || "";
  $("#t-prio").value = x.prioridade || "media";
  $("#t-obs").value = x.observacoes || "";
  const c = x.calculo || {};
  $("#t-disp").value = c.disponibilizacao || "";
  $("#t-dias").value = c.dias || "";
  $("#t-contagem").value = c.contagem || "";
  renderMemoria(c);
  $("#t-aviso").hidden = !x.aviso;
  $("#t-aviso").textContent = x.aviso || "";
  $("#t-trecho-box").hidden = !x.trecho;
  $("#t-trecho").textContent = x.trecho || "";
  $("#t-link").hidden = !x.link;
  if (x.link) $("#t-link").href = x.link;
  $("#t-abrir-proc").hidden = !x.numero;
  $("#t-excluir").hidden = !t;
  $("#t-excluir").textContent = t && t.origem === "djen" ? "Descartar" : "Excluir";
  $("#t-confirmar").hidden = !(t && t.status === "sugerido");
  renderChecklist();
  $("#dlg-tarefa").showModal();
}

function renderMemoria(c) {
  if (!c || !c.passos) { $("#t-memoria").innerHTML = ""; return; }
  const pulados = (c.pulados || []).map((p) => `<li>${dataBr(p.data)}${p.data ? "/" + p.data.slice(0, 4) : ""}: ${esc(p.motivo)}</li>`).join("");
  $("#t-memoria").innerHTML = `
    <div class="rotulo">Memória de cálculo${c.confianca ? ` <small>(detecção: confiança ${esc(c.confianca)}${c.fonte ? " — " + esc(c.fonte) : ""})</small>` : ""}</div>
    <ol>${c.passos.map((p) => `<li>${esc(p)}</li>`).join("")}</ol>
    ${pulados ? `<div class="rotulo">Dias úteis pulados (feriados/suspensões)</div><ul>${pulados}</ul>` : ""}
    ${c.tribunal ? `<p class="ajuda">Calendário usado: ${esc(c.tribunal)}. Fins de semana não aparecem na lista.</p>` : ""}`;
}

function renderChecklist() {
  $("#t-check").innerHTML = ag.checklist.map((c, i) => `
    <li><label class="chk"><input type="checkbox" data-ci="${i}" ${c.feito ? "checked" : ""}> <span class="${c.feito ? "feito" : ""}">${esc(c.texto)}</span></label>
      <button class="link pequeno perigo-txt" type="button" data-cx="${i}">remover</button></li>`).join("");
}

async function calcularNoDialogo() {
  const disp = $("#t-disp").value, dias = $("#t-dias").value;
  if (!disp || !dias) { toast("Informe a data de disponibilização e o número de dias."); return; }
  const p = new URLSearchParams({ disponibilizacao: disp, dias, numero: $("#t-numero").value, contagem: $("#t-contagem").value });
  try {
    const c = await api("/api/prazos/calcular?" + p);
    const anterior = (ag.editando && ag.editando.calculo) || {};
    ag.calculo = { ...anterior, ...c };
    $("#t-fatal").value = c.vencimento;
    $("#t-interna").value = c.interno;
    renderMemoria(ag.calculo);
  } catch (e) {
    toast("Erro: " + e.message);
  }
}

function dadosDoDialogo() {
  const d = {
    titulo: $("#t-titulo").value.trim(), tipo: $("#t-tipo").value, status: $("#t-status").value,
    numero: $("#t-numero").value.replace(/\D/g, "") || null, advogada_id: Number($("#t-adv").value) || null,
    prazo_fatal: $("#t-fatal").value || null, data_interna: $("#t-interna").value || null, hora: $("#t-hora").value || null,
    prioridade: $("#t-prio").value, observacoes: $("#t-obs").value.trim() || null, checklist: ag.checklist,
  };
  if (ag.calculo) d.calculo = ag.calculo;
  return d;
}

async function salvarTarefa(confirmar = false) {
  const d = dadosDoDialogo();
  if (!d.titulo) { $("#t-titulo").focus(); return; }
  if (d.numero && d.numero.length !== 20) { toast("Número de processo incompleto (precisa de 20 dígitos)."); return; }
  if (confirmar) d.status = "a_fazer";
  try {
    if (ag.editando) await api(`/api/agenda/${ag.editando.id}`, { method: "PATCH", body: JSON.stringify(d) });
    else await api("/api/agenda", { method: "POST", body: JSON.stringify(d) });
    $("#dlg-tarefa").close();
    toast(confirmar ? "Prazo confirmado: foi para A fazer." : "Salvo.");
    carregarAgenda();
  } catch (e) {
    toast("Erro: " + e.message);
  }
}

async function excluirTarefa() {
  const t = ag.editando;
  const djen = t.origem === "djen";
  if (!confirm(djen ? "Descartar este cartão? A publicação não volta a gerar sugestão." : "Excluir esta tarefa?")) return;
  await api(`/api/agenda/${t.id}`, { method: "DELETE" });
  $("#dlg-tarefa").close();
  toast(djen ? "Descartado." : "Excluída.");
  carregarAgenda();
}

// ---------- verificar prazos ----------
async function rodarVerificacao() {
  const btn = $("#v-rodar");
  btn.disabled = true;
  btn.textContent = "Verificando…";
  try {
    const r = await api("/api/agenda/verificar", { method: "POST", body: JSON.stringify({ incluir_vencidos: $("#v-vencidos").checked }) });
    $("#v-resultado").hidden = false;
    $("#v-resultado").innerHTML = r.analisadas ? `
      <div><strong>${r.analisadas}</strong> publicação(ões) analisada(s).</div>
      <div><strong>${r.sugeridos}</strong> prazo(s) e <strong>${r.audiencias}</strong> audiência(s) sugerido(s)${r.conferir ? ` — ${r.conferir} marcado(s) para conferir manualmente` : ""}.</div>
      <div>${r.sem_prazo} sem prazo identificado; ${r.repetidos} repetida(s) (mesmo prazo já sugerido).</div>
      ${r.ja_vencidos ? `<div>${r.ja_vencidos} com prazo já vencido não viraram cartão (marque a opção acima para incluí-los).</div>` : ""}
      ${r.erros ? `<div class="ruim">${r.erros} erro(s): veja logs/app.log.</div>` : ""}`
      : "Nenhuma publicação nova para analisar. Use “Atualizar tudo” para buscar publicações no DJEN.";
    carregarAgenda();
  } catch (e) {
    $("#v-resultado").hidden = false;
    $("#v-resultado").innerHTML = `<div class="ruim">Erro: ${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Verificar agora";
  }
}

// ---------- exportar .ics ----------
function icsTexto(s) {
  return String(s || "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

function icsDobrar(linha) {
  // RFC 5545: linhas de até 75 octetos; continuação começa com espaço
  const enc = new TextEncoder();
  const partes = [];
  let atual = "";
  for (const ch of linha) {
    if (enc.encode(atual + ch).length > (partes.length ? 74 : 75)) { partes.push(atual); atual = ""; }
    atual += ch;
  }
  partes.push(atual);
  return partes.join("\r\n ");
}

function exportarIcs() {
  const filtradas = tarefasFiltradas();
  const temFiltro = Object.values(filtrosAgenda()).some(Boolean);
  let lista = ag.tarefas;
  if (temFiltro && confirm(`Exportar só as ${filtradas.length} tarefa(s) filtradas?\n(Cancelar = exportar todas as ${ag.tarefas.length})`)) lista = filtradas;
  lista = lista.filter((t) => t.prazo_fatal && t.status !== "sugerido"); // sugestões só entram depois de confirmadas
  if (!lista.length) { toast("Nada para exportar (só entram cartões com data; sugeridos não confirmados ficam de fora)."); return; }
  const blob = new Blob([gerarIcs(lista)], { type: "text/calendar;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `prazos-${isoLocal(new Date())}.ics`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  toast(`${lista.length} evento(s) exportado(s). No Google Agenda: Configurações → Importar e exportar → Importar.`);
}

function gerarIcs(lista) {
  const agora = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
  const dia = (iso) => iso.replace(/-/g, "");
  const seguinte = (iso) => isoLocal(new Date(new Date(iso + "T12:00:00").getTime() + 864e5)).replace(/-/g, "");
  const linhas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//processos-local//agenda//PT-BR", "CALSCALE:GREGORIAN",
    "X-WR-CALNAME:Prazos e tarefas"];
  lista.forEach((t) => {
    const advs = advogadasDaTarefa(t).map((a) => a.nome).join(", ");
    const desc = [t.numero_fmt && `Processo ${t.numero_fmt}`, t.partes, advs && `Responsável: ${advs}`,
      t.data_interna && `Data interna: ${dataBr(t.data_interna)}`, `Status: ${NOME_STATUS[t.status] || t.status}`,
      t.observacoes, t.trecho && `Trecho: ${t.trecho}`, t.link,
      "Prazos calculados automaticamente são sugestões. Confirme sempre no processo e no calendário do tribunal."]
      .filter(Boolean).join("\n");
    const ev = ["BEGIN:VEVENT", `UID:tarefa-${t.id}@processos-local`, `DTSTAMP:${agora}`];
    if (t.hora) {
      const ini = dia(t.prazo_fatal) + "T" + t.hora.replace(":", "") + "00";
      const [h, m] = t.hora.split(":").map(Number);
      ev.push(`DTSTART:${ini}`, `DTEND:${dia(t.prazo_fatal)}T${String(Math.min(h + 1, 23)).padStart(2, "0")}${String(m).padStart(2, "0")}00`);
    } else {
      ev.push(`DTSTART;VALUE=DATE:${dia(t.prazo_fatal)}`, `DTEND;VALUE=DATE:${seguinte(t.prazo_fatal)}`);
    }
    ev.push(`SUMMARY:${icsTexto((t.tipo === "prazo" ? "PRAZO: " : t.tipo === "audiencia" ? "" : "") + t.titulo + (t.numero_fmt ? " — " + t.numero_fmt : ""))}`,
      `DESCRIPTION:${icsTexto(desc)}`, "TRANSP:TRANSPARENT", "END:VEVENT");
    linhas.push(...ev);
  });
  linhas.push("END:VCALENDAR");
  return linhas.map(icsDobrar).join("\r\n") + "\r\n";
}

// ---------- alertas ----------
async function carregarAlertas() {
  let a;
  try { a = await api("/api/agenda/alertas"); } catch (_) { return; }
  const proximos = a.hoje + a.amanha;
  const partes = [];
  if (proximos) partes.push(`<strong>${proximos}</strong> ${proximos === 1 ? "prazo vence" : "prazos vencem"} hoje/amanhã`);
  if (a.vencidos) partes.push(`<strong>${a.vencidos}</strong> ${a.vencidos === 1 ? "vencido" : "vencidos"}`);
  if (a.sugeridos) partes.push(`${a.sugeridos} ${a.sugeridos === 1 ? "sugestão aguardando" : "sugestões aguardando"} confirmação`);
  $("#alerta-prazos").hidden = !partes.length;
  $("#alerta-prazos").classList.toggle("grave", !!(proximos || a.vencidos));
  $("#alerta-prazos-texto").innerHTML = "⏰ " + partes.join(", ") + ".";
  const badge = $("#qtd-aba-agenda");
  badge.hidden = !(proximos || a.vencidos);
  badge.textContent = proximos + a.vencidos;
}

// ---------- feriados ----------
async function abrirFeriados() {
  const anoAtual = new Date().getFullYear();
  const sel = $("#fer-ano");
  if (!sel.options.length) {
    sel.innerHTML = [anoAtual - 1, anoAtual, anoAtual + 1, anoAtual + 2]
      .map((a) => `<option ${a === anoAtual ? "selected" : ""}>${a}</option>`).join("");
  }
  await renderFeriados();
  $("#dlg-feriados").showModal();
}

let tiposFeriado = {};
async function renderFeriados() {
  const d = await api(`/api/feriados?ano=${$("#fer-ano").value}`);
  tiposFeriado = d.tipos;
  const ano = $("#fer-ano").value;
  const full = (v, rec) => (rec && v ? `${ano}-${v}` : v || "");
  $("#fer-linhas").innerHTML = d.feriados.map((f) => linhaFeriado(f, full)).join("");
}

function linhaFeriado(f, full) {
  const opcoes = Object.entries(tiposFeriado).map(([k, n]) => `<option value="${k}" ${k === f.tipo ? "selected" : ""}>${esc(n)}</option>`).join("");
  return `<tr data-fid="${f.id || ""}" class="${f.ativo === 0 ? "inativo" : ""}">
    <td><input type="date" class="campo" data-k="inicio" value="${full(f.inicio, f.recorrente)}"></td>
    <td><input type="date" class="campo" data-k="fim" value="${full(f.fim, f.recorrente)}"></td>
    <td><input type="text" class="campo" data-k="descricao" value="${esc(f.descricao)}">${f.origem === "padrao" ? `<small class="ajuda">pré-preenchido — conferir</small>` : ""}</td>
    <td><select class="campo" data-k="tipo">${opcoes}</select></td>
    <td><input type="text" class="campo estreito" data-k="tribunais" value="${esc(f.tribunais || "")}" placeholder="todos"></td>
    <td><input type="text" class="campo estreito" data-k="comarca" value="${esc(f.comarca || "")}" placeholder="todas"></td>
    <td><input type="checkbox" data-k="recorrente" ${f.recorrente ? "checked" : ""} title="Repete todo ano"></td>
    <td class="acoes-linha"><button class="link pequeno" type="button" data-fer-salvar>salvar</button>
      <button class="link pequeno perigo-txt" type="button" data-fer-excluir>excluir</button></td>
  </tr>`;
}

async function salvarFeriado(tr) {
  const d = {};
  tr.querySelectorAll("[data-k]").forEach((el) => { d[el.dataset.k] = el.type === "checkbox" ? el.checked : el.value; });
  const id = tr.dataset.fid;
  try {
    await api(id ? `/api/feriados/${id}` : "/api/feriados", { method: id ? "PUT" : "POST", body: JSON.stringify(d) });
    ag.feriadosCache = {};
    toast("Feriado salvo. Prazos já sugeridos não mudam sozinhos: recalcule no cartão se precisar.");
    renderFeriados();
  } catch (e) {
    toast("Erro: " + e.message);
  }
}

// ---------- tipos de ato ----------
async function abrirTipos() {
  const tipos = await api("/api/tipos-ato");
  $("#tipos-linhas").innerHTML = tipos.map(linhaTipo).join("");
  $("#dlg-tipos").showModal();
}

function linhaTipo(t) {
  return `<tr>
    <td><input type="text" class="campo" data-k="nome" value="${esc(t.nome || "")}"></td>
    <td><input type="text" class="campo largo-txt" data-k="palavras" value="${esc(t.palavras || "")}"></td>
    <td><input type="number" class="campo curto" data-k="dias" min="1" max="365" value="${t.dias || 5}"></td>
    <td><select class="campo" data-k="contagem"><option value="uteis">úteis</option><option value="corridos" ${t.contagem === "corridos" ? "selected" : ""}>corridos</option></select></td>
    <td><select class="campo" data-k="justica"><option value="">qualquer</option><option value="trabalho" ${t.justica === "trabalho" ? "selected" : ""}>trabalho</option></select></td>
    <td><input type="checkbox" data-k="ativo" ${t.ativo !== 0 ? "checked" : ""}></td>
    <td class="acoes-linha"><button class="link pequeno" type="button" data-tipo-mover="-1" title="Subir">↑</button>
      <button class="link pequeno" type="button" data-tipo-mover="1" title="Descer">↓</button>
      <button class="link pequeno perigo-txt" type="button" data-tipo-remover>remover</button></td>
  </tr>`;
}

async function salvarTipos() {
  const lista = [...document.querySelectorAll("#tipos-linhas tr")].map((tr) => {
    const d = {};
    tr.querySelectorAll("[data-k]").forEach((el) => { d[el.dataset.k] = el.type === "checkbox" ? el.checked : el.value; });
    return d;
  });
  await api("/api/tipos-ato", { method: "PUT", body: JSON.stringify(lista) });
  $("#dlg-tipos").close();
  toast("Tipos de ato salvos. Valem para as próximas verificações.");
}

// ---------- telas ----------
function mostrarTela(tela) {
  estado.tela = tela;
  gravarPreferencia("tela", tela);
  document.querySelectorAll("[data-tela]").forEach((b) => b.classList.toggle("ativa", b.dataset.tela === tela));
  $("#tela-processos").hidden = tela !== "processos";
  $("#tela-agenda").hidden = tela !== "agenda";
  if (tela === "agenda") carregarAgenda().catch((e) => toast("Erro: " + e.message));
}

// ---------- eventos ----------
function ligarAgenda() {
  document.querySelectorAll("[data-tela]").forEach((b) => { b.onclick = () => mostrarTela(b.dataset.tela); });
  $("#alerta-prazos-ver").onclick = () => {
    $("#ag-f-status").value = "abertos";
    ag.visao = "lista";
    mostrarTela("agenda");
  };
  $("#ag-visao").onclick = (ev) => {
    const b = ev.target.closest("[data-visao]");
    if (!b) return;
    ag.visao = b.dataset.visao;
    gravarPreferencia("ag-visao", ag.visao);
    renderAgenda();
  };
  ["#ag-f-adv", "#ag-f-status", "#ag-f-de", "#ag-f-ate"].forEach((s) => { $(s).onchange = renderAgenda; });
  $("#ag-f-proc").oninput = renderAgenda;
  $("#ag-limpar").onclick = () => {
    ["#ag-f-adv", "#ag-f-proc", "#ag-f-status", "#ag-f-de", "#ag-f-ate"].forEach((s) => { $(s).value = ""; });
    renderAgenda();
  };
  $("#ag-nova").onclick = () => abrirTarefa(null, { advogada_id: Number($("#ag-f-adv").value) || null });
  $("#ag-verificar").onclick = () => { $("#v-resultado").hidden = true; $("#dlg-verificar").showModal(); };
  $("#v-rodar").onclick = rodarVerificacao;
  $("#ag-ics").onclick = exportarIcs;
  $("#ag-feriados").onclick = abrirFeriados;
  $("#ag-tipos").onclick = abrirTipos;

  // cartões (kanban e lista): abrir, abrir processo, ações de sugerido, seleção em lote
  const telaAgenda = $("#tela-agenda");
  telaAgenda.addEventListener("click", (ev) => {
    const proc = ev.target.closest("[data-proc]");
    if (proc) { ev.stopPropagation(); abrirPainel(proc.dataset.proc); return; }
    if (ev.target.closest(".c-sel")) return;
    const todos = ev.target.closest("[data-sel-todos]");
    if (todos) { document.querySelectorAll(".c-sel").forEach((c) => { c.checked = todos.checked; }); return; }
    const lote = ev.target.closest("[data-lote]");
    if (lote) {
      const ids = [...document.querySelectorAll(".c-sel:checked")].map((c) => Number(c.dataset.sel));
      emLote(ids, lote.dataset.lote);
      return;
    }
    const alvo = ev.target.closest("[data-id]");
    if (!alvo) return;
    const t = ag.tarefas.find((x) => x.id === Number(alvo.dataset.id));
    const acao = ev.target.closest("[data-acao]");
    if (acao && acao.dataset.acao === "confirmar") emLote([t.id], "confirmar");
    else if (acao && acao.dataset.acao === "descartar") emLote([t.id], "descartar");
    else abrirTarefa(t);
  });

  // arrastar e soltar entre colunas
  const kanban = $("#ag-kanban");
  kanban.addEventListener("dragstart", (ev) => {
    const c = ev.target.closest(".cartao");
    if (!c) return;
    ag.arrastando = Number(c.dataset.id);
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", c.dataset.id);
    c.classList.add("arrastando");
  });
  kanban.addEventListener("dragend", (ev) => { ev.target.closest(".cartao")?.classList.remove("arrastando"); });
  kanban.addEventListener("dragover", (ev) => {
    const col = ev.target.closest(".coluna");
    if (!col || ag.arrastando == null) return;
    ev.preventDefault();
    document.querySelectorAll(".coluna.alvo").forEach((c) => c !== col && c.classList.remove("alvo"));
    col.classList.add("alvo");
  });
  kanban.addEventListener("dragleave", (ev) => {
    const col = ev.target.closest(".coluna");
    if (col && !col.contains(ev.relatedTarget)) col.classList.remove("alvo");
  });
  kanban.addEventListener("drop", (ev) => {
    const col = ev.target.closest(".coluna");
    if (!col) return;
    ev.preventDefault();
    col.classList.remove("alvo");
    const id = ag.arrastando ?? Number(ev.dataTransfer.getData("text/plain"));
    ag.arrastando = null;
    moverTarefa(id, col.dataset.status);
  });

  // calendário
  document.querySelectorAll("[data-cal]").forEach((b) => {
    b.onclick = () => {
      const passo = Number(b.dataset.cal), r = ag.calRef;
      if (!passo) ag.calRef = new Date();
      else if (ag.calModo === "mes") ag.calRef = new Date(r.getFullYear(), r.getMonth() + passo, 1);
      else ag.calRef = new Date(r.getFullYear(), r.getMonth(), r.getDate() + 7 * passo);
      renderAgenda();
    };
  });
  $("#cal-modo").onclick = (ev) => {
    const b = ev.target.closest("[data-modo]");
    if (b) { ag.calModo = b.dataset.modo; renderAgenda(); }
  };
  $("#cal-grade").addEventListener("dblclick", (ev) => {
    const dia = ev.target.closest("[data-dia]");
    if (dia && !ev.target.closest("[data-id]")) abrirTarefa(null, { prazo_fatal: dia.dataset.dia, data_interna: dia.dataset.dia });
  });

  // diálogo da tarefa
  $("#t-salvar").onclick = () => salvarTarefa(false);
  $("#t-confirmar").onclick = () => salvarTarefa(true);
  $("#t-excluir").onclick = excluirTarefa;
  $("#t-calcular").onclick = calcularNoDialogo;
  $("#t-abrir-proc").onclick = () => {
    const n = $("#t-numero").value.replace(/\D/g, "");
    if (n.length === 20) { $("#dlg-tarefa").close(); abrirPainel(n); }
  };
  const addItem = () => {
    const v = $("#t-check-novo").value.trim();
    if (!v) return;
    ag.checklist.push({ texto: v, feito: false });
    $("#t-check-novo").value = "";
    renderChecklist();
  };
  $("#t-check-add").onclick = addItem;
  $("#t-check-novo").onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); addItem(); } };
  $("#t-check").onclick = (ev) => {
    const ci = ev.target.closest("[data-ci]");
    if (ci) { ag.checklist[Number(ci.dataset.ci)].feito = ci.checked; renderChecklist(); return; }
    const cx = ev.target.closest("[data-cx]");
    if (cx) { ag.checklist.splice(Number(cx.dataset.cx), 1); renderChecklist(); }
  };

  // feriados
  $("#fer-ano").onchange = renderFeriados;
  $("#fer-novo").onclick = () => {
    const ano = $("#fer-ano").value;
    $("#fer-linhas").insertAdjacentHTML("afterbegin", linhaFeriado(
      { inicio: `${ano}-01-01`, descricao: "", tipo: "feriado", tribunais: "", comarca: "", recorrente: 0 }, (v) => v));
    $("#fer-linhas [data-k=descricao]").focus();
  };
  $("#fer-linhas").onclick = async (ev) => {
    const tr = ev.target.closest("tr");
    if (ev.target.closest("[data-fer-salvar]")) salvarFeriado(tr);
    if (ev.target.closest("[data-fer-excluir]")) {
      if (!tr.dataset.fid) { tr.remove(); return; }
      if (!confirm("Excluir este feriado/suspensão?")) return;
      await api(`/api/feriados/${tr.dataset.fid}`, { method: "DELETE" });
      ag.feriadosCache = {};
      renderFeriados();
    }
  };

  // tipos de ato
  $("#tipos-novo").onclick = () => $("#tipos-linhas").insertAdjacentHTML("beforeend", linhaTipo({ dias: 15, contagem: "uteis" }));
  $("#tipos-salvar").onclick = () => salvarTipos().catch((e) => toast("Erro: " + e.message));
  $("#tipos-linhas").onclick = (ev) => {
    const tr = ev.target.closest("tr");
    const mover = ev.target.closest("[data-tipo-mover]");
    if (mover) {
      const viz = mover.dataset.tipoMover === "-1" ? tr.previousElementSibling : tr.nextElementSibling;
      if (viz) (mover.dataset.tipoMover === "-1" ? viz.before(tr) : viz.after(tr));
    }
    if (ev.target.closest("[data-tipo-remover]")) tr.remove();
  };

  carregarAlertas();
  const inicial = location.hash === "#agenda" ? "agenda" : (lerPreferencia("tela") || "processos");
  mostrarTela(inicial);
}

ligarAgenda();
