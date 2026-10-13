"use strict";
// Agenda / Kanban de prazos. Usa utilidades de app.js ($, api, esc, toast, fmtData, estado, abrirPainel...).

const COLUNAS = [
  ["sugerido", "Sugeridos", "aguardando confirmação"],
  ["a_fazer", "A fazer", ""],
  ["andamento", "Em andamento", ""],
  ["aguardando", "Aguardando terceiros", ""],
];
// Concluídas saem do quadro e ficam só na vista "Concluídos" (ícone ao lado das visões)
const NOME_STATUS = { ...Object.fromEntries(COLUNAS.map(([k, n]) => [k, n])), concluido: "Concluído" };
const SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
  "novembro", "dezembro"];

const ag = {
  // o calendário saiu do Monitoramento (virou a tela Agenda, em calendario.js): preferência antiga cai no Kanban
  tarefas: [], cardsQuadro: [], visao: lerPreferencia("ag-visao") === "lista" ? "lista" : "kanban",
  editando: null, ck: null, calculo: undefined, arrastando: null, feriadosCache: {}, vendoFeitas: false,
  memoria: memoriaCards("cards-agenda"), modelos: {},
};
const TIPO_PRAZO = { processual: "Prazo processual (veio do processo)", interno: "Prazo interno (posto pela equipe)" };

// Pontinho que distingue prazo processual (cheio) de interno (vazado)
function marcaPrazo(tipo) {
  return tipo ? `<span class="pz pz-${tipo}" title="${TIPO_PRAZO[tipo]}" aria-label="${TIPO_PRAZO[tipo]}"></span>` : "";
}

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
  ag.cardsQuadro = d.cards || [];
  estado.pessoas = d.pessoas || estado.pessoas;
  ag.regras = d.regras;
  if (!estado.advogadas.length) await carregarEstado();
  preencherFiltrosAgenda();
  renderAgenda();
  carregarAlertas();
}

function filtrosAgenda() {
  return { adv: $("#ag-f-adv").value, proc: $("#ag-f-proc").value.trim() };
}

// filtro "Processo (número ou parte)"
function casaProcesso(f, x) {
  if (!f.proc) return true;
  const digitos = f.proc.replace(/\D/g, "");
  return (digitos.length >= 4 && (x.numero || "").includes(digitos))
    || (x.partes || "").toLowerCase().includes(f.proc.toLowerCase()) || (x.numero_fmt || "").includes(f.proc);
}

// filtro Beatriz/Kazuza: a demanda é dela se ela for a responsável (ou, sem responsável, atuar no processo),
// ou se algum item da checklist estiver com ela
const temItemDe = (lista, advId) => (lista || []).some((c) => c.resp === `a:${advId}`);

function tarefasFiltradas() {
  const f = filtrosAgenda();
  const id = Number(f.adv) || null;
  return ag.tarefas.filter((t) => casaProcesso(f, t) && (!id || t.advogada_id === id
    || (!t.advogada_id && t.advogadas_processo.includes(id)) || temItemDe(t.checklist, id)));
}

// Itens de checklist com data e prazo fatal interno dos cards do quadro: entram na Agenda e na Lista por data.
// Fonte única: são lidos das próprias demandas (tarefas e cards); nada é copiado para a agenda.
function entradasAgenda() {
  return entradasDe(ag.tarefas, ag.cardsQuadro, filtrosAgenda());
}

// f = { adv: id da advogada ou "", proc: texto do filtro de processo }
function entradasDe(tarefas, cards, f) {
  const id = Number(f.adv) || null;
  const pais = [
    ...tarefas.filter((t) => t.status !== "concluido").map((t) => ({
      dono: "tarefa", id: t.id, nome: t.titulo, numero: t.numero, numero_fmt: t.numero_fmt, partes: t.partes,
      advs: t.advogada_id ? [t.advogada_id] : t.advogadas_processo, checklist: t.checklist, prazo: null })),
    ...cards.map((c) => ({
      dono: "card", id: c.id, nome: c.titulo, numero: c.numero, numero_fmt: c.numero_fmt, partes: c.partes,
      advs: c.advogadas_processo, checklist: c.checklist, prazo: c.prazo })),
  ];
  const itens = [], prazos = [];
  for (const p of pais.filter((x) => casaProcesso(f, x))) {
    for (const c of p.checklist) {
      // item com responsável: vale o responsável; sem responsável: vale quem é da demanda
      if (c.data && (!id || c.resp === `a:${id}` || (!c.resp && p.advs.includes(id)))) itens.push({ ...c, pai: p });
    }
    // prazo processual de card já aparece como a própria tarefa do processo; aqui só o interno
    if (p.prazo && p.prazo.tipo === "interno" && (!id || p.advs.includes(id) || temItemDe(p.checklist, id))) {
      prazos.push({ ...p.prazo, pai: p });
    }
  }
  return { itens, prazos };
}

async function marcarItem(dono, donoId, item, feito) {
  try {
    await api("/api/checklist/feito", { method: "POST", body: JSON.stringify({ dono, dono_id: donoId, item, feito }) });
  } catch (e) {
    toast("Erro: " + e.message);
  }
  recarregarTela();
}

// clicar num item ou prazo de card abre a demanda de onde ele veio
function abrirPai(dono, id, tarefas = ag.tarefas) {
  if (dono === "card") abrirCardPorId(id);
  else abrirTarefa(tarefas.find((t) => t.id === id));
}

// Depois de salvar algo: recarrega a tela aberta (Monitoramento, Agenda, Xablau…) e os selos do menu
function recarregarTela() {
  const carregar = TELAS[estado.tela];
  if (carregar) carregar().catch((e) => toast("Erro: " + e.message));
  carregarAlertas();
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
  const filtradas = tarefasFiltradas();
  const lista = filtradas.filter((t) => t.status !== "concluido");
  const feitas = ag.vendoFeitas;
  document.querySelectorAll("#ag-visao [data-visao]").forEach((b) => b.classList.toggle("ativa", !feitas && b.dataset.visao === ag.visao));
  $("#ag-concluidos").classList.toggle("ativa", feitas);
  $("#ag-concluidos").setAttribute("aria-pressed", feitas);
  $("#ag-kanban").hidden = feitas || ag.visao !== "kanban";
  $("#ag-lista").hidden = feitas || ag.visao !== "lista";
  $("#ag-feitas").hidden = !feitas;
  $("#ag-expandir").hidden = feitas || ag.visao !== "kanban";
  if (feitas) renderFeitas(filtradas.filter((t) => t.status === "concluido"));
  else if (ag.visao === "kanban") renderKanban(lista);
  else renderLista(lista, entradasAgenda());
  $("#ag-limpar").hidden = !Object.values(filtrosAgenda()).some(Boolean);
}

// ---------- cartão ----------
function botaoConcluir() {
  return `<button class="concluir" type="button" data-acao="concluir" title="Concluir" aria-label="Concluir">
    <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>`;
}

// Card contraído mostra só título + progresso da checklist (clique no card alterna; "Editar" ou duplo clique abre)
function cartaoHTML(t) {
  const advs = advogadasDaTarefa(t);
  const sug = t.status === "sugerido";
  const origem = { djen: "DJEN", sigilo: "sigiloso" }[t.origem];
  return `
    <article class="cartao u-${t.urgencia} ${ag.memoria.contraido(t.id) ? "contraido" : ""}" draggable="true" data-id="${t.id}">
      ${sug ? "" : botaoConcluir()}
      <div class="c-topo">
        ${sug ? `<input type="checkbox" class="c-sel" data-sel="${t.id}" aria-label="Selecionar">` : ""}
        <span class="c-urg">${rotuloUrgencia(t)}</span>
        ${t.prioridade === "alta" ? `<span class="c-tag prio">alta</span>` : ""}
        ${t.tipo === "audiencia" ? `<span class="c-tag">audiência</span>` : ""}
        ${origem ? `<span class="c-tag ${t.origem === "djen" ? "djen" : ""}">${origem}</span>` : ""}
      </div>
      <div class="c-cab"><span class="c-titulo">${esc(t.titulo)}</span>${progressoChecklist(t.checklist)}</div>
      ${t.numero ? `<button class="link c-proc" type="button" data-proc="${t.numero}">${esc(t.numero_fmt)}</button>
        ${t.partes ? `<div class="c-partes">${esc(t.partes)}</div>` : ""}` : ""}
      ${t.prazo_fatal ? `<div class="c-datas">${t.tipo === "audiencia" ? "" : marcaPrazo(t.prazo_tipo)}${t.tipo === "audiencia" ? "Data" : "Fatal"}: <b>${dataBr(t.prazo_fatal)}</b>${t.hora ? ` ${esc(t.hora)}` : ""}
        ${t.data_interna && t.data_interna !== t.prazo_fatal ? ` · interno ${dataBr(t.data_interna, false)}` : ""}</div>` : ""}
      <div class="c-rodape">
        ${advs.map(etiquetaAdv).join("")}${!t.advogada_id && advs.length > 1 ? `<span class="c-def">definir</span>` : ""}
        ${t.observacoes ? `<span class="c-check" title="${esc(t.observacoes)}">✎</span>` : ""}
        ${sug ? "" : `<button class="c-editar" type="button" data-acao="editar">Editar</button>`}
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
    if (status === "concluido") toast("Concluída: foi para Concluídos.");
  } catch (e) {
    toast("Erro: " + e.message);
  }
  recarregarTela();
}

// ---------- concluídos ----------
function renderFeitas(lista) {
  const ordenadas = [...lista].sort((a, b) => (b.concluido_em || "").localeCompare(a.concluido_em || ""));
  $("#ag-feitas").innerHTML = `
    <div class="feitas-cab"><h3>Concluídos <span class="qtd">${ordenadas.length}</span></h3>
      <button class="link pequeno" type="button" data-voltar>voltar</button></div>
    ${ordenadas.map((t) => `
      <div class="feita" data-fid="${t.id}">
        <div class="feita-txt">
          <span class="li-titulo">${esc(t.titulo)}</span>
          ${t.numero ? `<button class="link c-proc" type="button" data-proc="${t.numero}">${esc(t.numero_fmt)}</button>` : ""}
        </div>
        <span class="li-adv">${advogadasDaTarefa(t).map(etiquetaAdv).join("")}</span>
        <span class="feita-quando">${t.concluido_em ? "em " + dataBr(t.concluido_em, false) : ""}</span>
        <span class="feita-acoes">
          <button class="btn mini" type="button" data-restaurar>Restaurar</button>
          <button class="btn mini perigo" type="button" data-apagar>Excluir definitivamente</button>
        </span>
      </div>`).join("") || `<p class="vazio">Nada concluído${Object.values(filtrosAgenda()).some(Boolean) ? " com esses filtros" : " ainda"}.</p>`}`;
}

function alternarFeitas(mostrar = !ag.vendoFeitas) {
  ag.vendoFeitas = mostrar;
  renderAgenda();
}

async function restaurarTarefa(id) {
  try {
    const t = await api(`/api/agenda/${id}/restaurar`, { method: "POST" });
    toast(`Restaurada em “${NOME_STATUS[t.status] || t.status}”.`);
  } catch (e) {
    toast("Erro: " + e.message);
  }
  recarregarTela();
}

async function apagarDefinitivo(id) {
  const t = ag.tarefas.find((x) => x.id === id);
  if (!t || !confirm(`Excluir definitivamente “${t.titulo}”?\nNão dá para desfazer.`)) return;
  try {
    await api(`/api/agenda/${id}`, { method: "DELETE" });
    toast("Excluída definitivamente.");
  } catch (e) {
    toast("Erro: " + e.message);
  }
  recarregarTela();
}

async function emLote(ids, acao) {
  if (!ids.length) { toast("Selecione pelo menos um cartão."); return; }
  if (acao === "descartar" && !confirm(`Descartar ${ids.length} sugestão(ões)? A publicação não volta a gerar sugestão.`)) return;
  const r = await api("/api/agenda/lote", { method: "POST", body: JSON.stringify({ ids, acao }) });
  toast(`${r.alterados} ${acao === "confirmar" ? "confirmado(s): foram para A fazer" : "descartado(s)"}.`);
  recarregarTela();
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

// Item de checklist na agenda: leve (sem cor de fundo), com caixinha de feito; clicar no texto abre a demanda
function itemAgendaHTML(c, classe) {
  const quem = pessoaPorChave(c.resp);
  return `<div class="${classe} ${c.feito ? "feito" : ""}" data-dono="${c.pai.dono}" data-dono-id="${c.pai.id}" data-item="${esc(c.id)}"
      role="button" tabindex="0" title="${esc(c.texto)} · ${esc(c.pai.nome)}${quem ? " — " + esc(quem.nome_completo) : ""}">
    <input type="checkbox" class="ck-ag" ${c.feito ? "checked" : ""} aria-label="Feito: ${esc(c.texto)}">
    ${classe === "lista-ck" ? `<span class="it-hora">${esc(c.hora || "")}</span>` : ""}
    <span class="it-txt">${classe !== "lista-ck" && c.hora ? `<b>${esc(c.hora)}</b> ` : ""}${esc(c.texto)}<span class="it-pai"> · ${esc(c.pai.nome)}</span></span>
    ${classe === "lista-ck" ? `<span class="li-adv">${quem ? etiquetaPessoa(quem) : ""}</span>` : ""}
  </div>`;
}

// Prazo fatal interno de um card do quadro: destaque leve (contorno na cor da urgência, sem fundo)
function prazoCardHTML(p, classe) {
  const rotulo = `${marcaPrazo("interno")}${p.hora ? esc(p.hora) + " " : ""}${esc(p.descricao)}<span class="it-pai"> · ${esc(p.pai.nome)}</span>`;
  if (classe === "cal") {
    return `<button type="button" class="cal-chip cal-prazo-card u-${p.urgencia}" data-dono="card" data-dono-id="${p.pai.id}"
      title="Prazo fatal de ${esc(p.pai.nome)}">${rotulo}</button>`;
  }
  return `<div class="lista-item lista-prazo-card u-${p.urgencia}" data-dono="card" data-dono-id="${p.pai.id}" role="button" tabindex="0">
    <span></span><span class="c-urg">${rotuloUrgencia({ ...p, prazo_fatal: p.data })}</span>
    <span class="li-titulo">${rotulo}</span><span></span><span></span>
    <span class="li-status">${esc(typeof NOME_QUADRO === "string" ? NOME_QUADRO : "")}</span>
  </div>`;
}

// ---------- lista por data ----------
function renderLista(lista, { itens, prazos }) {
  const hoje = isoLocal(new Date());
  const grupos = new Map();
  const por = (k, html) => { if (!grupos.has(k)) grupos.set(k, []); grupos.get(k).push(html); };
  const chave = (data) => (!data ? "sem" : data < hoje ? "vencidos" : data);
  [...lista].sort((a, b) => (a.prazo_fatal || "9999").localeCompare(b.prazo_fatal || "9999")).forEach((t) => por(chave(t.prazo_fatal), `
    <div class="lista-item u-${t.urgencia}" data-id="${t.id}">
      ${t.status === "sugerido" ? "<span></span>" : botaoConcluir()}
      <span class="c-urg">${rotuloUrgencia(t)}</span>
      <span class="li-titulo">${t.tipo === "audiencia" ? "" : marcaPrazo(t.prazo_tipo)}${esc(t.titulo)}${t.hora && !t.titulo.includes(t.hora) ? ` · ${esc(t.hora)}` : ""}</span>
      ${t.numero ? `<button class="link c-proc" type="button" data-proc="${t.numero}">${esc(t.numero_fmt)}</button>` : "<span></span>"}
      <span class="li-adv">${advogadasDaTarefa(t).map(etiquetaAdv).join("")}</span>
      <span class="li-status">${NOME_STATUS[t.status] || t.status}${t.conferir ? " · ⚠ conferir" : ""}</span>
    </div>`));
  [...prazos].sort((a, b) => a.data.localeCompare(b.data)).forEach((p) => por(chave(p.data), prazoCardHTML(p, "lista")));
  // itens feitos saem da lista (continuam riscados no calendário e dentro da demanda)
  itens.filter((c) => !c.feito).sort((a, b) => (a.data + (a.hora || "99")).localeCompare(b.data + (b.hora || "99")))
    .forEach((c) => por(chave(c.data), itemAgendaHTML(c, "lista-ck")));
  const titulo = (k) => k === "sem" ? "Sem data" : k === "vencidos" ? "⚠ Vencidos" :
    `${dataBr(k)}${k === hoje ? " — hoje" : ""} <small>${k.slice(0, 4)}</small>`;
  const ordem = [...grupos.keys()].sort((a, b) => (a === "vencidos" ? -1 : b === "vencidos" ? 1 : a === "sem" ? 1 : b === "sem" ? -1 : a.localeCompare(b)));
  $("#ag-lista").innerHTML = ordem.map((k) => `
    <section class="lista-grupo"><h3>${titulo(k)}</h3>${grupos.get(k).join("")}</section>`).join("")
    || `<p class="vazio">Nenhuma tarefa com esses filtros.</p>`;
}

// ---------- editar / criar ----------
async function abrirTarefa(t, padrao = {}) {
  if (!t) {
    // Tarefa nova nasce com a checklist padrão (checklists_padrao.txt, lido na hora); modelo "processo" por padrão
    ag.modelos = await api("/api/checklist-padrao").catch(() => ({}));
    ag.modelo = "processo";
  }
  if (!estado.pessoas.length) await carregarPessoas();
  ag.editando = t || null;
  const x = t || { titulo: "", tipo: "tarefa", status: "a_fazer", prioridade: "media", ...padrao };
  ag.calculo = undefined; // só envia se recalcular
  $("#t-fatal").value = x.prazo_fatal || "";
  ag.ck.definir(t ? t.checklist : ag.modelos[ag.modelo]);
  $("#t-modelo").hidden = !!t;
  marcarModelo();
  $("#t-titulo-dlg").textContent = t ? (t.status === "sugerido" ? "Prazo sugerido" : "Editar") : "Nova tarefa";
  $("#t-titulo").value = x.titulo || "";
  $("#t-tipo").value = x.tipo || "tarefa";
  $("#t-status").innerHTML = COLUNAS.map(([k, n]) => `<option value="${k}" ${k === x.status ? "selected" : ""}>${n}</option>`).join("");
  $("#t-numero").value = x.numero_fmt || x.numero || "";
  $("#t-adv").innerHTML = `<option value="">— as duas / a definir —</option>` +
    estado.advogadas.map((a) => `<option value="${a.id}" ${a.id === x.advogada_id ? "selected" : ""}>${esc(a.nome)}</option>`).join("");
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
  $("#t-concluir").hidden = !t || t.status === "sugerido";
  rotuloTipoPrazo();
  $("#dlg-tarefa").showModal();
}

// Processual (veio do DJEN / foi calculado a partir da disponibilização) ou interno (data posta à mão)
function rotuloTipoPrazo() {
  const t = ag.editando;
  const tipo = (t && t.origem === "djen") || ag.calculo || (t && t.calculo) ? "processual" : "interno";
  $("#t-prazo-tipo").innerHTML = $("#t-fatal").value && $("#t-tipo").value !== "audiencia" ? `${marcaPrazo(tipo)}${tipo}` : "";
}

// Modelo da checklist de uma tarefa nova (processo / preventivo). Troca sem perguntar se ela ainda não mexeu.
function marcarModelo() {
  document.querySelectorAll("#t-modelo [data-modelo]").forEach((b) => b.classList.toggle("ativa", b.dataset.modelo === ag.modelo));
}

function trocarModelo(modelo) {
  if (modelo === ag.modelo) return;
  if (!ag.ck.igualA(ag.modelos[ag.modelo] || []) && !confirm("Trocar a checklist pelo outro modelo? O que você mudou nela se perde.")) return;
  ag.modelo = modelo;
  ag.ck.definir(ag.modelos[modelo]);
  marcarModelo();
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
    rotuloTipoPrazo();
    ag.ck.atualizar();
  } catch (e) {
    toast("Erro: " + e.message);
  }
}

function dadosDoDialogo() {
  const d = {
    titulo: $("#t-titulo").value.trim(), tipo: $("#t-tipo").value, status: $("#t-status").value,
    numero: $("#t-numero").value.replace(/\D/g, "") || null, advogada_id: Number($("#t-adv").value) || null,
    prazo_fatal: $("#t-fatal").value || null, data_interna: $("#t-interna").value || null, hora: $("#t-hora").value || null,
    prioridade: $("#t-prio").value, observacoes: $("#t-obs").value.trim() || null, checklist: ag.ck.valor(),
  };
  if (ag.calculo) d.calculo = ag.calculo;
  return d;
}

// status: null = salvar como está; "a_fazer" = confirmar sugestão; "concluido" = salvar e mandar para Concluídos
async function salvarTarefa(status = null) {
  const d = dadosDoDialogo();
  if (!d.titulo) { $("#t-titulo").focus(); return; }
  if (d.numero && d.numero.length !== 20) { toast("Número de processo incompleto (precisa de 20 dígitos)."); return; }
  if (status) d.status = status;
  try {
    if (ag.editando) await api(`/api/agenda/${ag.editando.id}`, { method: "PATCH", body: JSON.stringify(d) });
    else await api("/api/agenda", { method: "POST", body: JSON.stringify(d) });
    $("#dlg-tarefa").close();
    toast({ a_fazer: "Prazo confirmado: foi para A fazer.", concluido: "Concluída: foi para Concluídos." }[status] || "Salvo.");
    recarregarTela();
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
  recarregarTela();
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
    recarregarTela();
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
  badge.title = `${proximos} vencem hoje/amanhã, ${a.vencidos} vencidos`;
  // selo do Financeiro: parcelas vencidas e não pagas
  try {
    const f = await api("/api/financeiro/atrasadas");
    const fin = $("#qtd-aba-fin");
    fin.hidden = !f.atrasadas;
    fin.textContent = f.atrasadas;
    fin.title = `${f.atrasadas} parcela(s) em atraso`;
  } catch (_) { /* servidor antigo, sem financeiro: só não mostra o selo */ }
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
// Telas do app e o que carregar ao abrir cada uma (quadro.js, calendario.js e financeiro.js acrescentam as suas)
const TELAS = { processos: null, agenda: () => carregarAgenda() };
// Título e descrição no topo (Andamentos mostra as OABs; o nome do quadro vem de quadro.js)
const CABECALHOS = {
  processos: ["Andamentos Processuais", null],
  agenda: ["Monitoramento", "Prazos que o sistema cria para lembrar de monitorar, avaliar a pertinência e incluir no checklist do cliente."],
  quadro: ["Clientes", "Um cartão por cliente, com a checklist das demandas e a data de aniversário."],
  calendario: ["Agenda", "Tudo num calendário só: monitoramento, checklists dos clientes, aniversários e parcelas."],
  financeiro: ["Financeiro", "Honorários: entradas, parcelas, o que já entrou e o que falta receber."],
};

function atualizarCabecalho() {
  const [titulo, descricao] = CABECALHOS[estado.tela] || CABECALHOS.processos;
  $("#titulo-tela").textContent = titulo;
  $("#identidade").textContent = descricao ?? (estado.identidade || " ");
  document.title = `${titulo} · Meus processos`;
  // botões do topo que só fazem sentido para processos/publicações
  $("#btn-adicionar").hidden = estado.tela !== "processos";
  $("#btn-atualizar").hidden = $("#ultima").hidden = !["processos", "agenda"].includes(estado.tela);
}

function mostrarTela(tela) {
  if (!(tela in TELAS)) tela = "processos";
  estado.tela = tela;
  gravarPreferencia("tela", tela);
  document.querySelectorAll("[data-tela]").forEach((b) => {
    b.classList.toggle("ativa", b.dataset.tela === tela);
    if (b.dataset.tela === tela) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  Object.keys(TELAS).forEach((t) => { $(`#tela-${t}`).hidden = t !== tela; });
  atualizarCabecalho();
  fecharMenuGaveta();
  window.scrollTo(0, 0);
  if (TELAS[tela]) TELAS[tela]().catch((e) => toast("Erro: " + e.message));
}

// Ícone de Concluídos: abre/fecha a vista e aceita cartões arrastados do Kanban
function ligarConcluidos() {
  const icone = $("#ag-concluidos");
  icone.onclick = () => alternarFeitas();
  icone.addEventListener("dragover", (ev) => {
    if (ag.arrastando == null) return;
    ev.preventDefault();
    icone.classList.add("alvo");
  });
  icone.addEventListener("dragleave", () => icone.classList.remove("alvo"));
  icone.addEventListener("drop", (ev) => {
    ev.preventDefault();
    icone.classList.remove("alvo");
    const id = ag.arrastando ?? Number(ev.dataTransfer.getData("text/plain"));
    ag.arrastando = null;
    if (id) moverTarefa(id, "concluido");
  });
}

// Botões pouco usados (.ics, feriados, tipos de ato): aparecem ao passar o mouse na barra (CSS) ou,
// em tela de toque / pelo teclado, ao tocar na barra ou no "⋯". Tocar fora esconde de novo.
function ligarExtras() {
  const barra = $("#ag-topo"), mais = $("#ag-mais");
  const revelar = (sim) => {
    barra.classList.toggle("revelar", sim);
    mais.setAttribute("aria-expanded", sim);
  };
  mais.onclick = (ev) => { ev.stopPropagation(); revelar(!barra.classList.contains("revelar")); };
  let toque = false;
  barra.addEventListener("pointerdown", (ev) => { toque = ev.pointerType !== "mouse"; });
  barra.addEventListener("click", (ev) => {
    if (toque && !ev.target.closest("button, input, select, a")) revelar(true);
  });
  document.addEventListener("pointerdown", (ev) => { if (!barra.contains(ev.target)) revelar(false); });
  $("#ag-extras").addEventListener("click", (ev) => { if (ev.target.closest("button")) revelar(false); });
}

// ---------- eventos ----------
function ligarAgenda() {
  document.querySelectorAll("[data-tela]").forEach((b) => { b.onclick = () => mostrarTela(b.dataset.tela); });
  $("#alerta-prazos-ver").onclick = () => {
    ag.visao = "lista";
    mostrarTela("agenda");
  };
  $("#ag-visao").onclick = (ev) => {
    const b = ev.target.closest("[data-visao]");
    if (!b) return;
    ag.visao = b.dataset.visao;
    ag.vendoFeitas = false;
    gravarPreferencia("ag-visao", ag.visao);
    renderAgenda();
  };
  ligarConcluidos();
  ligarExtras();
  $("#ag-f-adv").onchange = renderAgenda;
  $("#ag-f-proc").oninput = renderAgenda;
  $("#ag-limpar").onclick = () => {
    ["#ag-f-adv", "#ag-f-proc"].forEach((s) => { $(s).value = ""; });
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
    if (ev.target.closest("[data-voltar]")) { alternarFeitas(false); return; }
    const feita = ev.target.closest("[data-fid]");
    if (feita) {
      const id = Number(feita.dataset.fid);
      if (ev.target.closest("[data-restaurar]")) restaurarTarefa(id);
      else if (ev.target.closest("[data-apagar]")) apagarDefinitivo(id);
      return;
    }
    // item de checklist ou prazo de card (calendário/lista): a caixinha marca feito; o resto abre a demanda
    const entrada = ev.target.closest("[data-dono]");
    if (entrada) {
      const donoId = Number(entrada.dataset.donoId);
      if (ev.target.classList.contains("ck-ag")) marcarItem(entrada.dataset.dono, donoId, entrada.dataset.item, ev.target.checked);
      else abrirPai(entrada.dataset.dono, donoId);
      return;
    }
    const alvo = ev.target.closest("[data-id]");
    if (!alvo) return;
    const t = ag.tarefas.find((x) => x.id === Number(alvo.dataset.id));
    const acao = ev.target.closest("[data-acao]");
    if (acao && acao.dataset.acao === "confirmar") emLote([t.id], "confirmar");
    else if (acao && acao.dataset.acao === "descartar") emLote([t.id], "descartar");
    else if (acao && acao.dataset.acao === "concluir") moverTarefa(t.id, "concluido");
    else if (acao || !alvo.classList.contains("cartao")) abrirTarefa(t); // "Editar", item da lista, chip do calendário
    else if (!ev.target.closest("a, button, input, label")) alternarCard(alvo, ag.memoria);
  });
  telaAgenda.addEventListener("keydown", (ev) => {
    const entrada = ev.target.closest("[data-dono]");
    if (entrada && ev.key === "Enter" && !ev.target.classList.contains("ck-ag")) abrirPai(entrada.dataset.dono, Number(entrada.dataset.donoId));
  });
  telaAgenda.addEventListener("dblclick", (ev) => {
    const c = ev.target.closest(".cartao");
    if (c && !ev.target.closest("a, button, input, label")) abrirTarefa(ag.tarefas.find((x) => x.id === Number(c.dataset.id)));
  });
  ligarExpandir($("#ag-expandir"), ag.memoria, "#ag-kanban .cartao");

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
  kanban.addEventListener("dragend", (ev) => {
    ev.target.closest(".cartao")?.classList.remove("arrastando");
    $("#ag-concluidos").classList.remove("alvo");
    ag.arrastando = null;
  });
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

  // diálogo da tarefa
  $("#t-salvar").onclick = () => salvarTarefa();
  $("#t-confirmar").onclick = () => salvarTarefa("a_fazer");
  $("#t-concluir").onclick = () => salvarTarefa("concluido");
  $("#t-excluir").onclick = excluirTarefa;
  $("#t-calcular").onclick = calcularNoDialogo;
  $("#t-abrir-proc").onclick = () => {
    const n = $("#t-numero").value.replace(/\D/g, "");
    if (n.length === 20) { $("#dlg-tarefa").close(); abrirPainel(n); }
  };
  // checklist avisa etapas marcadas depois do prazo fatal da tarefa
  ag.ck = criarChecklist($("#t-checklist"), { prazo: () => $("#t-fatal").value || null });
  $("#t-fatal").addEventListener("input", () => { ag.ck.atualizar(); rotuloTipoPrazo(); });
  $("#t-tipo").addEventListener("change", rotuloTipoPrazo);
  $("#t-modelo").onclick = (ev) => { const b = ev.target.closest("[data-modelo]"); if (b) trocarModelo(b.dataset.modelo); };

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
  // depois de todos os scripts (quadro.js registra a tela dele em TELAS)
  document.addEventListener("DOMContentLoaded", () => mostrarTela(location.hash.slice(1) || lerPreferencia("tela") || "processos"));
}

ligarAgenda();
