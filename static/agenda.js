"use strict";
// Monitoramento: as sugestões do sistema (prazos e audiências lidos das publicações, verificação semanal dos processos
// sigilosos) aguardando aprovação. Aprovada, a sugestão vira um item do checklist do cliente (e daí aparece na Agenda);
// rejeitada, sai daqui. Também ficam aqui o diálogo de tarefa (usado ainda pela Agenda e pelo painel do processo para
// criar uma tarefa direto no cliente), os feriados, os tipos de ato e o alerta de prazos.
// Usa utilidades de app.js ($, api, esc, toast, fmtData, estado, abrirPainel...).

const SEMANA = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"];
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
  "novembro", "dezembro"];

const ag = {
  tarefas: [], cardsQuadro: [], editando: null, calculo: undefined, feriadosCache: {}, clienteEscolhido: false,
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
    || (x.partes || "").toLowerCase().includes(f.proc.toLowerCase()) || (x.numero_fmt || "").includes(f.proc)
    || (x.nome || "").toLowerCase().includes(f.proc.toLowerCase());
}

// filtro Beatriz/Kazuza: a demanda é dela se ela for a responsável (ou, sem responsável, atuar no processo),
// ou se algum item da checklist estiver com ela
const temItemDe = (lista, advId) => (lista || []).some((c) => c.resp === `a:${advId}`);

function tarefasFiltradas() {
  const f = filtrosAgenda();
  const id = Number(f.adv) || null;
  return ag.tarefas.filter((t) => casaProcesso(f, t) && (!id || t.advogada_id === id
    || (!t.advogada_id && t.advogadas_processo.includes(id))));
}

// Itens de checklist com data e prazo fatal interno dos cards de Clientes: o que vai para a Agenda. Fonte única: são
// lidos dos próprios cards (as tarefas aprovadas no Monitoramento são itens deles); nada é copiado para a agenda.
// f = { adv: id da advogada ou "", proc: texto do filtro de processo }
function entradasDe(cards, f) {
  const id = Number(f.adv) || null;
  const pais = cards.map((c) => ({
    dono: "card", id: c.id, nome: c.titulo, numero: c.numero, numero_fmt: c.numero_fmt, partes: c.partes,
    advs: c.advogadas_processo, checklist: c.checklist, prazo: c.prazo }));
  const itens = [], prazos = [];
  for (const p of pais.filter((x) => casaProcesso(f, x))) {
    for (const c of p.checklist) {
      // item com responsável: vale o responsável; sem responsável: vale quem é da demanda
      if (c.data && (!id || c.resp === `a:${id}` || (!c.resp && p.advs.includes(id)))) itens.push({ ...c, pai: p });
    }
    // prazo processual do card já aparece como o próprio item do prazo; aqui só o interno
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

// clicar num item ou prazo de card abre o card (cliente) de onde ele veio
function abrirPai(dono, id) {
  if (dono === "card") abrirCardPorId(id);
}

// Depois de salvar algo: recarrega a tela aberta (Monitoramento, Agenda, Clientes…) e os selos do menu
function recarregarTela() {
  const carregar = TELAS[estado.tela];
  if (carregar) carregar().catch((e) => toast("Erro: " + e.message));
  carregarAlertas();
}

function preencherProcessos() {
  const procs = new Map();
  ag.tarefas.forEach((t) => t.numero && procs.set(t.numero_fmt, t.partes));
  estado.processos.forEach((p) => procs.set(p.numero_fmt, partesTexto(p)));
  $("#ag-processos").innerHTML = [...procs].map(([n, p]) => `<option value="${esc(n)}">${esc(p || "")}</option>`).join("");
}

function preencherFiltrosAgenda() {
  const sel = $("#ag-f-adv"), atual = sel.value;
  sel.innerHTML = `<option value="">Todas as advogadas</option>` +
    estado.advogadas.map((a) => `<option value="${a.id}" ${String(a.id) === atual ? "selected" : ""}>${esc(a.nome)}</option>`).join("");
  preencherProcessos();
}

// Para onde a sugestão vai ao ser aprovada: o cliente escolhido, o card do processo, ou um card novo para o processo
const cardDoProcesso = (numero, cards = ag.cardsQuadro) =>
  numero ? cards.filter((c) => c.numero === numero).sort((a, b) => a.id - b.id)[0] || null : null;

function destinoDe(t) {
  const escolhido = t.cliente_id && ag.cardsQuadro.find((c) => c.id === t.cliente_id);
  const card = escolhido || cardDoProcesso(t.numero);
  if (card) return { nome: card.titulo, novo: false };
  return t.numero ? { nome: "novo cliente (criado ao aprovar)", novo: true } : { nome: "escolha o cliente (Editar)", falta: true };
}

// ---------- lista de sugestões ----------
function renderAgenda() {
  const lista = tarefasFiltradas();
  const hoje = isoLocal(new Date());
  const grupos = new Map();
  const chave = (data) => (!data ? "sem" : data < hoje ? "vencidos" : data);
  [...lista].sort((a, b) => (a.prazo_fatal || "9999").localeCompare(b.prazo_fatal || "9999")).forEach((t) => {
    const k = chave(t.prazo_fatal);
    if (!grupos.has(k)) grupos.set(k, []);
    grupos.get(k).push(linhaSugestao(t));
  });
  const titulo = (k) => k === "sem" ? "Sem data" : k === "vencidos" ? "⚠ Vencidos" :
    `${dataBr(k)}${k === hoje ? " — hoje" : ""} <small>${k.slice(0, 4)}</small>`;
  const ordem = [...grupos.keys()].sort((a, b) => (a === "vencidos" ? -1 : b === "vencidos" ? 1 : a === "sem" ? 1 : b === "sem" ? -1 : a.localeCompare(b)));
  const filtrado = Object.values(filtrosAgenda()).some(Boolean);
  $("#ag-lista").innerHTML = ordem.map((k) => `
    <section class="lista-grupo"><h3>${titulo(k)}</h3>${grupos.get(k).join("")}</section>`).join("")
    || `<p class="vazio">${filtrado ? "Nenhuma sugestão com esses filtros." : `Nenhuma sugestão aguardando aprovação.<br>
        <small>Depois de “Atualizar tudo”, use “Verificar prazos” para ler as publicações novas.</small>`}</p>`;
  $("#ag-lote").hidden = !lista.length;
  $("#ag-sel-todos").checked = false;
  $("#ag-limpar").hidden = !filtrado;
}

function linhaSugestao(t) {
  const origem = { djen: "DJEN", sigilo: "sigiloso" }[t.origem];
  const destino = destinoDe(t);
  const interna = t.data_interna && t.data_interna !== t.prazo_fatal ? ` · interno ${dataBr(t.data_interna, false)}` : "";
  return `
    <div class="sug u-${t.urgencia}" data-id="${t.id}">
      <input type="checkbox" class="c-sel" data-sel="${t.id}" aria-label="Selecionar “${esc(t.titulo)}”">
      <span class="c-urg">${rotuloUrgencia(t)}</span>
      <div class="sug-txt">
        <div class="li-titulo">${t.tipo === "prazo" ? marcaPrazo(t.prazo_tipo) : ""}${esc(t.titulo)}
          ${t.tipo === "audiencia" ? `<span class="c-tag">audiência</span>` : ""}
          ${origem ? `<span class="c-tag ${t.origem === "djen" ? "djen" : ""}">${origem}</span>` : ""}</div>
        <div class="sug-sub">${t.prazo_fatal ? `${t.tipo === "audiencia" ? "Data" : "Fatal"} <b>${dataBr(t.prazo_fatal)}</b>${t.hora ? " " + esc(t.hora) : ""}${interna}` : "Sem data"}
          ${t.numero ? ` · <button class="link c-proc" type="button" data-proc="${t.numero}">${esc(t.numero_fmt)}</button>` : ""}
          ${t.partes ? ` · <span class="c-partes">${esc(t.partes)}</span>` : ""}</div>
        <div class="sug-destino ${destino.falta ? "falta" : ""}" title="Ao aprovar, vai para o checklist deste cliente">→ checklist de ${esc(destino.nome)}</div>
        ${t.conferir ? `<div class="c-aviso">⚠ conferir manualmente</div>` : ""}
      </div>
      <span class="li-adv">${advogadasDaTarefa(t).map(etiquetaAdv).join("")}</span>
      <span class="sug-acoes">
        <button class="btn mini primario" type="button" data-acao="aprovar">✓ Aprovar</button>
        <button class="btn mini" type="button" data-acao="editar">Editar</button>
        <button class="btn mini perigo" type="button" data-acao="rejeitar">Rejeitar</button>
      </span>
    </div>`;
}

async function aprovar(ids, clienteId = null) {
  if (!ids.length) { toast("Selecione pelo menos uma sugestão."); return; }
  try {
    const r = await api("/api/agenda/aprovar", { method: "POST", body: JSON.stringify({ ids, cliente_id: clienteId }) });
    const partes = [];
    if (r.aprovadas) partes.push(`${r.aprovadas} aprovada(s): foram para o checklist do cliente e aparecem na Agenda.`);
    if (r.sem_cliente) partes.push(`${r.sem_cliente} sem processo ficaram aqui: abra em Editar e escolha o cliente.`);
    toast(partes.join(" ") || "Nada aprovado (já tinham saído do Monitoramento?).");
  } catch (e) {
    toast("Erro: " + e.message);
  }
  recarregarTela();
}

async function rejeitar(ids) {
  if (!ids.length) { toast("Selecione pelo menos uma sugestão."); return; }
  if (!confirm(`Rejeitar ${ids.length > 1 ? `${ids.length} sugestões` : "esta sugestão"}? Sai do Monitoramento e não vai para o cliente (a publicação não volta a sugerir).`)) return;
  try {
    const r = await api("/api/agenda/rejeitar", { method: "POST", body: JSON.stringify({ ids }) });
    toast(`${r.rejeitadas} rejeitada(s).`);
  } catch (e) {
    toast("Erro: " + e.message);
  }
  recarregarTela();
}

// ---------- calendário (helpers usados por calendario.js) ----------
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

// Item de checklist na agenda, com caixinha de feito; clicar no texto abre o cliente. Tarefa que veio do
// Monitoramento (prazo, audiência…) leva a cor da urgência; item comum fica leve (sem cor de fundo).
function itemAgendaHTML(c) {
  const quem = pessoaPorChave(c.resp);
  const tarefa = c.tipo ? `cal-tarefa u-${c.urgencia || "sem_data"}` : "";
  const marca = c.tipo === "prazo" ? marcaPrazo(c.prazo_tipo) : "";
  return `<div class="cal-item ${tarefa} ${c.feito ? "feito" : ""}" data-dono="${c.pai.dono}" data-dono-id="${c.pai.id}" data-item="${esc(c.id)}"
      role="button" tabindex="0" title="${esc(c.texto)} · ${esc(c.pai.nome)}${quem ? " — " + esc(quem.nome_completo) : ""}">
    <input type="checkbox" class="ck-ag" ${c.feito ? "checked" : ""} aria-label="Feito: ${esc(c.texto)}">
    <span class="it-txt">${marca}${c.hora ? `<b>${esc(c.hora)}</b> ` : ""}${esc(c.texto)}<span class="it-pai"> · ${esc(c.pai.nome)}</span></span>
  </div>`;
}

// Prazo fatal interno de um card de Clientes: destaque leve (contorno na cor da urgência, sem fundo)
function prazoCardHTML(p) {
  return `<button type="button" class="cal-chip cal-prazo-card u-${p.urgencia}" data-dono="card" data-dono-id="${p.pai.id}"
    title="Prazo fatal de ${esc(p.pai.nome)}">${marcaPrazo("interno")}${p.hora ? esc(p.hora) + " " : ""}${esc(p.descricao)}<span class="it-pai"> · ${esc(p.pai.nome)}</span></button>`;
}

// ---------- diálogo: sugestão (ajustar, aprovar, rejeitar) ou tarefa nova (vai direto para o cliente) ----------
async function abrirTarefa(t, padrao = {}) {
  if (!estado.pessoas.length) await carregarPessoas();
  if (!t || !ag.cardsQuadro.length) {  // tarefa nova pode ser aberta da Agenda ou do painel: lê os clientes na hora
    try { ag.cardsQuadro = (await api("/api/quadro")).cards; } catch (_) { /* sem a lista, escolhe pelo processo */ }
  }
  preencherProcessos();
  ag.editando = t || null;
  ag.clienteEscolhido = !!(t && t.cliente_id);
  const x = t || { titulo: "", tipo: "tarefa", ...padrao };
  ag.calculo = undefined; // só envia se recalcular
  $("#t-titulo-dlg").textContent = t ? "Sugestão do sistema" : "Nova tarefa";
  $("#t-titulo").value = x.titulo || "";
  $("#t-tipo").value = x.tipo || "tarefa";
  $("#t-numero").value = x.numero_fmt || x.numero || "";
  $("#t-adv").innerHTML = `<option value="">— as duas / a definir —</option>` +
    estado.advogadas.map((a) => `<option value="${a.id}" ${a.id === x.advogada_id ? "selected" : ""}>${esc(a.nome)}</option>`).join("");
  $("#t-fatal").value = x.prazo_fatal || "";
  $("#t-hora").value = x.hora || "";
  opcoesCliente(x.cliente_id);
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
  $("#t-obs").hidden = !x.observacoes;
  $("#t-obs").textContent = x.observacoes || "";
  $("#t-explica").textContent = t
    ? "Aprovar põe esta tarefa no checklist do cliente (com a data, o horário e a responsável) e ela passa a aparecer na Agenda. Rejeitar tira do Monitoramento."
    : "A tarefa entra direto no checklist do cliente (sem passar pelo Monitoramento) e aparece na Agenda na data escolhida.";
  $("#t-excluir").hidden = !t;
  $("#t-salvar").hidden = !t;
  $("#t-confirmar").textContent = t ? "✓ Aprovar" : "Adicionar ao cliente";
  $("#t-erro").hidden = true;
  rotuloTipoPrazo();
  $("#dlg-tarefa").showModal();
  if (!t) $("#t-titulo").focus();
}

// Clientes para escolher: o do processo vem marcado (sem card, a opção vazia cria um ao aprovar)
function opcoesCliente(escolhido) {
  const numero = $("#t-numero").value.replace(/\D/g, "");
  const doProcesso = numero.length === 20 ? cardDoProcesso(numero) : null;
  const atual = escolhido ?? (ag.clienteEscolhido ? Number($("#t-cliente").value) || null : doProcesso?.id ?? null);
  const vazio = numero.length === 20 ? (doProcesso ? "— o cliente do processo —" : "— novo cliente para este processo —")
    : "— escolha o cliente —";
  const cards = [...ag.cardsQuadro].sort((a, b) => a.titulo.localeCompare(b.titulo, "pt-BR"));
  $("#t-cliente").innerHTML = `<option value="">${vazio}</option>` + cards.map((c) =>
    `<option value="${c.id}" ${c.id === atual ? "selected" : ""}>${esc(c.titulo)}${c.numero_fmt ? " — " + esc(c.numero_fmt) : ""}</option>`).join("");
}

// Processual (veio do DJEN / foi calculado a partir da disponibilização) ou interno (data posta à mão)
function rotuloTipoPrazo() {
  const t = ag.editando;
  const tipo = (t && t.origem === "djen") || ag.calculo || (t && t.calculo) ? "processual" : "interno";
  const interna = (ag.calculo && ag.calculo.interno) || (t && t.data_interna);
  $("#t-prazo-tipo").innerHTML = $("#t-fatal").value && $("#t-tipo").value === "prazo"
    ? `${marcaPrazo(tipo)}${tipo}${interna && interna !== $("#t-fatal").value ? ` · interno ${dataBr(interna, false)}` : ""}` : "";
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
    if ($("#t-tipo").value === "tarefa") $("#t-tipo").value = "prazo";
    renderMemoria(ag.calculo);
    rotuloTipoPrazo();
  } catch (e) {
    toast("Erro: " + e.message);
  }
}

function dadosDoDialogo() {
  const d = {
    titulo: $("#t-titulo").value.trim(), tipo: $("#t-tipo").value,
    numero: $("#t-numero").value.replace(/\D/g, "") || null, cliente_id: Number($("#t-cliente").value) || null,
    advogada_id: Number($("#t-adv").value) || null, prazo_fatal: $("#t-fatal").value || null, hora: $("#t-hora").value || null,
  };
  if (ag.calculo) {
    d.calculo = ag.calculo;
    d.data_interna = ag.calculo.interno || null;
  }
  return d;
}

function erroNoDialogo(msg) {
  $("#t-erro").textContent = msg;
  $("#t-erro").hidden = false;
}

// aprovar: false = só salvar a sugestão (continua no Monitoramento); true = salvar e aprovar (vai para o cliente)
async function salvarTarefa(aprovarTambem) {
  const d = dadosDoDialogo();
  if (!d.titulo) { $("#t-titulo").focus(); return; }
  if (d.numero && d.numero.length !== 20) { erroNoDialogo("Número de processo incompleto (precisa de 20 dígitos)."); return; }
  if (!d.numero && !d.cliente_id) { erroNoDialogo("Escolha o cliente (a tarefa não tem processo)."); $("#t-cliente").focus(); return; }
  const t = ag.editando;
  try {
    if (!t) {
      const r = await api("/api/agenda", { method: "POST", body: JSON.stringify(d) });
      toast(`Tarefa adicionada ao checklist de ${r.cliente}.`);
    } else {
      await salvarConferindo(`/api/agenda/${t.id}`, "PATCH", d, t, "Esta sugestão foi alterada");
      if (aprovarTambem) {
        const r = await api("/api/agenda/aprovar", { method: "POST", body: JSON.stringify({ ids: [t.id], cliente_id: d.cliente_id }) });
        if (!r.aprovadas) throw new Error("Não aprovada: ela já tinha saído do Monitoramento (aprovada ou rejeitada em outra aba?).");
        toast("Aprovada: foi para o checklist do cliente e aparece na Agenda.");
      } else {
        toast("Sugestão salva (continua aguardando aprovação).");
      }
    }
    $("#dlg-tarefa").close();
    recarregarTela();
  } catch (e) {
    erroNoDialogo(e.message);
  }
}

async function rejeitarNoDialogo() {
  const t = ag.editando;
  if (!t || !confirm("Rejeitar esta sugestão? Sai do Monitoramento e não vai para o cliente (a publicação não volta a sugerir).")) return;
  try {
    await api("/api/agenda/rejeitar", { method: "POST", body: JSON.stringify({ ids: [t.id] }) });
    $("#dlg-tarefa").close();
    toast("Rejeitada.");
    recarregarTela();
  } catch (e) {
    erroNoDialogo(e.message);
  }
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
      ${r.ja_vencidos ? `<div>${r.ja_vencidos} com prazo já vencido não viraram sugestão (marque a opção acima para incluí-los).</div>` : ""}
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

// ---------- alertas ----------
async function carregarAlertas() {
  let a;
  try { a = await api("/api/agenda/alertas"); } catch (_) { return; }
  const proximos = a.hoje + a.amanha;
  const partes = [];
  if (proximos) partes.push(`<strong>${proximos}</strong> ${proximos === 1 ? "prazo vence" : "prazos vencem"} hoje/amanhã`);
  if (a.vencidos) partes.push(`<strong>${a.vencidos}</strong> ${a.vencidos === 1 ? "vencido" : "vencidos"}`);
  if (a.sugeridos) partes.push(`${a.sugeridos} ${a.sugeridos === 1 ? "sugestão aguardando" : "sugestões aguardando"} aprovação no Monitoramento`);
  $("#alerta-prazos").hidden = !partes.length;
  $("#alerta-prazos").classList.toggle("grave", !!(proximos || a.vencidos));
  $("#alerta-prazos-texto").innerHTML = "⏰ " + partes.join(", ") + ".";
  ag.alertas = a;
  // selo do Monitoramento: quantas sugestões esperam aprovação
  const badge = $("#qtd-aba-agenda");
  badge.hidden = !a.sugeridos;
  badge.textContent = a.sugeridos;
  badge.title = `${a.sugeridos} sugestão(ões) aguardando aprovação`;
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
    toast("Feriado salvo. Prazos já sugeridos não mudam sozinhos: recalcule na sugestão se precisar.");
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
  agenda: ["Monitoramento", "Sugestões do sistema (prazos, audiências, verificações) aguardando aprovação. Aprovada, a tarefa vai para o checklist do cliente e aparece na Agenda."],
  quadro: ["Clientes", "Um cartão por cliente (cada processo ganha o seu), com o checklist das demandas e a data de aniversário."],
  calendario: ["Agenda", "Tudo num calendário só: tarefas e checklists dos clientes, aniversários e parcelas."],
  financeiro: ["Financeiro", "Honorários: entradas, parcelas, o que já entrou e o que falta receber."],
};

function atualizarCabecalho() {
  const [titulo, descricao] = CABECALHOS[estado.tela] || CABECALHOS.processos;
  $("#titulo-tela").textContent = titulo;
  $("#identidade").textContent = descricao ?? (estado.identidade || " ");
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

// Botões pouco usados (feriados, tipos de ato): aparecem ao passar o mouse na barra (CSS) ou,
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
    if (toque && !ev.target.closest("button, input, select, a, label")) revelar(true);
  });
  document.addEventListener("pointerdown", (ev) => { if (!barra.contains(ev.target)) revelar(false); });
  $("#ag-extras").addEventListener("click", (ev) => { if (ev.target.closest("button")) revelar(false); });
}

// ---------- eventos ----------
function ligarAgenda() {
  document.querySelectorAll("[data-tela]").forEach((b) => { b.onclick = () => mostrarTela(b.dataset.tela); });
  // "ver" do alerta: sugestões esperando vão para o Monitoramento; senão, a Agenda (onde estão os prazos aprovados)
  $("#alerta-prazos-ver").onclick = () => mostrarTela(ag.alertas && ag.alertas.sugeridos ? "agenda" : "calendario");
  ligarExtras();
  $("#ag-f-adv").onchange = renderAgenda;
  $("#ag-f-proc").oninput = renderAgenda;
  $("#ag-limpar").onclick = () => {
    ["#ag-f-adv", "#ag-f-proc"].forEach((s) => { $(s).value = ""; });
    renderAgenda();
  };
  $("#ag-verificar").onclick = () => { $("#v-resultado").hidden = true; $("#dlg-verificar").showModal(); };
  $("#v-rodar").onclick = rodarVerificacao;
  $("#ag-feriados").onclick = abrirFeriados;
  $("#ag-tipos").onclick = abrirTipos;

  // seleção e ações em lote
  const selecionadas = () => [...document.querySelectorAll("#ag-lista .c-sel:checked")].map((c) => Number(c.dataset.sel));
  $("#ag-sel-todos").onchange = (ev) => document.querySelectorAll("#ag-lista .c-sel").forEach((c) => { c.checked = ev.target.checked; });
  $("#ag-lote").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-lote]");
    if (!b) return;
    if (b.dataset.lote === "aprovar") aprovar(selecionadas());
    else rejeitar(selecionadas());
  });

  // linhas: aprovar, editar, rejeitar, abrir processo; clique no resto da linha abre a sugestão
  $("#ag-lista").addEventListener("click", (ev) => {
    const proc = ev.target.closest("[data-proc]");
    if (proc) { ev.stopPropagation(); abrirPainel(proc.dataset.proc); return; }
    if (ev.target.closest(".c-sel")) return;
    const linha = ev.target.closest("[data-id]");
    if (!linha) return;
    const t = ag.tarefas.find((x) => x.id === Number(linha.dataset.id));
    if (!t) return;
    const acao = ev.target.closest("[data-acao]")?.dataset.acao;
    if (acao === "aprovar") aprovar([t.id]);
    else if (acao === "rejeitar") rejeitar([t.id]);
    else if (!ev.target.closest("a, input, label") && (acao || !ev.target.closest("button"))) abrirTarefa(t);
  });

  // diálogo da tarefa
  $("#t-salvar").onclick = () => salvarTarefa(false);
  $("#t-confirmar").onclick = () => salvarTarefa(true);
  $("#t-excluir").onclick = rejeitarNoDialogo;
  $("#t-calcular").onclick = calcularNoDialogo;
  $("#t-abrir-proc").onclick = () => {
    const n = $("#t-numero").value.replace(/\D/g, "");
    if (n.length === 20) { $("#dlg-tarefa").close(); abrirPainel(n); }
  };
  $("#t-fatal").addEventListener("input", rotuloTipoPrazo);
  $("#t-tipo").addEventListener("change", rotuloTipoPrazo);
  $("#t-numero").addEventListener("input", () => opcoesCliente());
  $("#t-cliente").addEventListener("change", () => { ag.clienteEscolhido = true; });

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
}

ligarAgenda();
