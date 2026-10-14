"use strict";
// Agenda: calendário único. Junta, sem copiar nada, o que já existe em cada lugar:
// - Monitoramento: prazo fatal e data interna das tarefas, e os itens com data das checklists delas;
// - CLIENTES: itens com data das checklists dos cards e o prazo fatal interno do card;
// - Aniversários: "Parabenizar <cliente>" todo ano, com "feito" por ano;
// - Financeiro: lembrete de cada parcela 1 dia depois do vencimento, para conferir se foi paga (a parcial, pelo que falta).
// Usa helpers de app.js, agenda.js (dataBr, itemAgendaHTML, prazoCardHTML, entradasDe, abrirTarefa…) e quadro.js.

const FONTES = ["monitoramento", "clientes", "aniversarios", "financeiro"];
const cal = { ref: new Date(), modo: "mes", dados: null, feriados: [], fontes: lerFontesCalendario() };

function lerFontesCalendario() {
  try {
    const v = JSON.parse(lerPreferencia("cal-fontes") || "null");
    if (Array.isArray(v)) return new Set(v.filter((f) => FONTES.includes(f)));
  } catch (_) { /* preferência corrompida: mostra tudo */ }
  return new Set(FONTES);
}

// Dias visíveis: o mês inteiro em semanas completas (domingo a sábado), ou uma semana
function periodoCalendario() {
  const ref = cal.ref;
  let ini, dias;
  if (cal.modo === "mes") {
    ini = inicioSemana(new Date(ref.getFullYear(), ref.getMonth(), 1));
    const fimMes = new Date(ref.getFullYear(), ref.getMonth() + 1, 0);
    dias = Math.ceil((Math.round((fimMes - ini) / 864e5) + 1) / 7) * 7;
  } else {
    ini = inicioSemana(ref);
    dias = 7;
  }
  return Array.from({ length: dias }, (_, i) => isoLocal(new Date(ini.getFullYear(), ini.getMonth(), ini.getDate() + i)));
}

async function carregarCalendario() {
  const datas = periodoCalendario();
  const de = datas[0], ate = datas[datas.length - 1];
  const [d, feriados] = await Promise.all([api(`/api/calendario?de=${de}&ate=${ate}`), feriadosNoPeriodo(de, ate)]);
  if (!estado.advogadas.length) await carregarEstado();
  cal.dados = d;
  cal.feriados = feriados;
  estado.pessoas = d.pessoas || estado.pessoas;
  const sel = $("#cal-adv"), atual = sel.value;
  sel.innerHTML = `<option value="">Todas as advogadas</option>` +
    estado.advogadas.map((a) => `<option value="${a.id}" ${String(a.id) === atual ? "selected" : ""}>${esc(a.nome)}</option>`).join("");
  renderCalendarioUnico(datas);
}

// tarefa do monitoramento é "dela" se ela é a responsável, se (sem responsável) atua no processo, ou se tem item com ela
function tarefaDaAdvogada(t, id) {
  return !id || t.advogada_id === id || (!t.advogada_id && t.advogadas_processo.includes(id)) || temItemDe(t.checklist, id);
}

function aniversarioHTML(a) {
  return `<div class="cal-item cal-aniv ${a.feito ? "feito" : ""}" data-aniv="${esc(a.chave)}" data-card="${a.card_id}"
      role="button" tabindex="0" title="Aniversário de ${esc(a.cliente)} — clique para abrir o cliente">
    <input type="checkbox" class="ck-aniv" ${a.feito ? "checked" : ""} aria-label="Já parabenizei ${esc(a.cliente)}">
    <span class="it-txt">🎂 Parabenizar ${esc(a.cliente)}</span></div>`;
}

function parcelaHTML(p) {
  const parcial = p.status === "parcial";
  const situacao = p.pago ? `paga em ${dataBrCompleta(p.pago_em)}` : [
    parcial ? `pago ${reais(p.pago_valor)} de ${reais(p.valor)} — falta ${reais(p.falta)}` : "",
    p.situacao === "atrasada" ? `em atraso há ${p.dias_atraso} dia(s)` : ""].filter(Boolean).join(" · ");
  return `<div class="cal-item cal-parc ${p.pago ? "feito" : ""} ${!p.pago && p.situacao === "atrasada" ? "atrasada" : ""}"
      data-parcela="${p.id}" data-lanc="${p.lancamento_id}" role="button" tabindex="0"
      title="Conferir pagamento: ${esc(p.cliente)}${p.inadimplente ? " (inadimplente)" : ""} · ${p.numero === 0 ? "entrada" : "parcela " + esc(p.rotulo)} de ${reais(p.valor)}, venceu em ${dataBrCompleta(p.vencimento)}${situacao ? " — " + situacao : ""}">
    <input type="checkbox" class="ck-parc" ${p.pago ? "checked" : ""} ${parcial ? "data-parcial" : ""} aria-label="Paga: ${esc(p.cliente)} ${esc(p.rotulo)}">
    <span class="it-txt"><b class="it-rs">R$</b> ${esc(p.cliente)} · ${p.numero === 0 ? "entrada" : esc(p.rotulo)} · ${parcial ? `falta ${reais(p.falta)}` : reais(p.valor)}</span></div>`;
}

function renderCalendarioUnico(datas) {
  const ref = cal.ref, d = cal.dados;
  if (!d) return;
  if (cal.modo === "mes") {
    const mes = MESES[ref.getMonth()];
    $("#cal-titulo").textContent = `${mes[0].toUpperCase() + mes.slice(1)} de ${ref.getFullYear()}`;
  } else {
    $("#cal-titulo").textContent = `${dataBr(datas[0], false)} a ${dataBr(datas[6], false)}/${datas[6].slice(0, 4)}`;
  }
  document.querySelectorAll("#cal-modo [data-modo]").forEach((b) => b.classList.toggle("ativa", b.dataset.modo === cal.modo));
  document.querySelectorAll("#cal-fontes [data-fonte]").forEach((b) => b.setAttribute("aria-pressed", cal.fontes.has(b.dataset.fonte)));

  const adv = Number($("#cal-adv").value) || null;
  const ver = (f) => cal.fontes.has(f);
  const tarefas = d.tarefas.filter((t) => t.status !== "concluido" && t.status !== "descartado" && tarefaDaAdvogada(t, adv));
  const { itens, prazos } = entradasDe(d.tarefas, d.cards, { adv: adv || "", proc: "" });
  const agrupar = (xs, campo = "data") => xs.reduce((m, x) => (x[campo] && (m[x[campo]] ||= []).push(x), m), {});
  const fatais = ver("monitoramento") ? agrupar(tarefas, "prazo_fatal") : {};
  const internas = ver("monitoramento") ? agrupar(tarefas.filter((t) => t.data_interna !== t.prazo_fatal), "data_interna") : {};
  const itensDia = agrupar(itens.filter((c) => ver(c.pai.dono === "card" ? "clientes" : "monitoramento")));
  const prazosDia = ver("clientes") ? agrupar(prazos) : {};
  const anivDia = ver("aniversarios") ? agrupar(d.aniversarios) : {};
  const parcDia = ver("financeiro") ? agrupar(d.parcelas) : {};
  const hoje = isoLocal(new Date());

  $("#cal-grade").className = `cal-grade ${cal.modo}`;
  $("#cal-grade").innerHTML = SEMANA.map((s) => `<div class="cal-cab">${s}</div>`).join("") + datas.map((iso) => {
    const dt = new Date(iso + "T12:00:00");
    const fora = cal.modo === "mes" && dt.getMonth() !== ref.getMonth();
    const fer = cal.feriados.filter((f) => f.data === iso);
    const chips = (fatais[iso] || []).map((t) =>
      `<button type="button" class="cal-chip u-${t.urgencia}" data-id="${t.id}" title="${esc(t.titulo)}${t.numero_fmt ? " — " + esc(t.numero_fmt) : ""}">${t.tipo === "audiencia" ? "" : marcaPrazo(t.prazo_tipo)}${t.hora && !t.titulo.includes(t.hora) ? esc(t.hora) + " " : ""}${esc(t.titulo)}</button>`);
    const ints = (internas[iso] || []).map((t) =>
      `<button type="button" class="cal-chip interno" data-id="${t.id}" title="Data interna: ${esc(t.titulo)}">↳ ${esc(t.titulo)}</button>`);
    const pzs = (prazosDia[iso] || []).map((p) => prazoCardHTML(p, "cal"));
    const anivs = (anivDia[iso] || []).map(aniversarioHTML);
    const parcs = (parcDia[iso] || []).map(parcelaHTML);
    const its = (itensDia[iso] || []).sort((a, b) => (a.hora || "99").localeCompare(b.hora || "99")).map((c) => itemAgendaHTML(c, "cal-item"));
    // no mês, dia cheio mostra os 4 primeiros e "+N mais" (abre o resto ali mesmo)
    const todos = [...chips, ...pzs, ...ints, ...anivs, ...parcs, ...its];
    const limite = cal.modo === "mes" && todos.length > 5 ? 4 : todos.length;
    const resto = todos.length - limite;
    return `<div class="cal-dia ${fora ? "fora" : ""} ${iso === hoje ? "hoje" : ""} ${fer.length || dt.getDay() % 6 === 0 ? "nao-util" : ""}" data-dia="${iso}">
      <div class="cal-num">${dt.getDate()}</div>
      ${fer.map((f) => `<div class="cal-fer" title="${esc(f.descricao)}${f.tribunais ? " — " + esc(f.tribunais) : ""}${f.comarca ? " — " + esc(f.comarca) : ""}">${esc(f.descricao)}${f.tribunais ? ` <small>(${esc(f.tribunais.length > 12 ? "alguns tribunais" : f.tribunais)})</small>` : ""}</div>`).join("")}
      ${todos.slice(0, limite).join("")}
      ${resto ? `<div class="cal-resto" hidden>${todos.slice(limite).join("")}</div>
        <button type="button" class="cal-mais" data-mais aria-expanded="false">+${resto} mais</button>` : ""}
    </div>`;
  }).join("");
  document.querySelectorAll("#cal-grade .ck-parc[data-parcial]").forEach((c) => { c.indeterminate = true; });
}

async function marcarAniversario(chave, feito) {
  try {
    await api("/api/lembretes", { method: "POST", body: JSON.stringify({ chave, feito }) });
  } catch (e) {
    toast("Erro: " + e.message);
  }
  recarregarTela();
}

// Marcar lança o que falta com a data de hoje (parcial ou não); desmarcar apaga os pagamentos da parcela
async function marcarParcelaPaga(id, pago) {
  const p = cal.dados.parcelas.find((x) => x.id === id);
  if (!pago && p && p.pagamentos.length > 1
    && !confirm(`Apagar os ${p.pagamentos.length} pagamentos desta parcela (${reais(p.pago_valor)})?`)) {
    recarregarTela();
    return;
  }
  try {
    await api(`/api/financeiro/parcelas/${id}/pagar`, { method: "POST", body: JSON.stringify({ pago }) });
    toast(!pago ? "Parcela desmarcada." : p?.status === "parcial" ? `Parcela quitada: lançado o que faltava (${reais(p.falta)}) com a data de hoje.`
      : "Parcela marcada como paga hoje. Para outro valor ou data, use o + no Financeiro.");
  } catch (e) {
    toast("Erro: " + e.message);
  }
  recarregarTela();
}

function ligarCalendario() {
  TELAS.calendario = () => carregarCalendario();
  document.querySelectorAll("[data-cal]").forEach((b) => {
    b.onclick = () => {
      const passo = Number(b.dataset.cal), r = cal.ref;
      if (!passo) cal.ref = new Date();
      else if (cal.modo === "mes") cal.ref = new Date(r.getFullYear(), r.getMonth() + passo, 1);
      else cal.ref = new Date(r.getFullYear(), r.getMonth(), r.getDate() + 7 * passo);
      carregarCalendario().catch((e) => toast("Erro: " + e.message));
    };
  });
  $("#cal-modo").onclick = (ev) => {
    const b = ev.target.closest("[data-modo]");
    if (!b || b.dataset.modo === cal.modo) return;
    cal.modo = b.dataset.modo;
    carregarCalendario().catch((e) => toast("Erro: " + e.message));
  };
  $("#cal-adv").onchange = () => renderCalendarioUnico(periodoCalendario());
  $("#cal-fontes").onclick = (ev) => {
    const b = ev.target.closest("[data-fonte]");
    if (!b) return;
    const f = b.dataset.fonte;
    if (!cal.fontes.delete(f)) cal.fontes.add(f);
    gravarPreferencia("cal-fontes", JSON.stringify([...cal.fontes]));
    renderCalendarioUnico(periodoCalendario());
  };

  const tela = $("#tela-calendario");
  tela.addEventListener("click", (ev) => {
    const alvo = ev.target;
    const mais = alvo.closest("[data-mais]");
    if (mais) {
      const resto = mais.previousElementSibling, abrir = resto.hidden;
      resto.hidden = !abrir;
      mais.setAttribute("aria-expanded", abrir);
      mais.textContent = abrir ? "mostrar menos" : `+${resto.children.length} mais`;
      return;
    }
    const aniv = alvo.closest("[data-aniv]");
    if (aniv) {
      if (alvo.classList.contains("ck-aniv")) marcarAniversario(aniv.dataset.aniv, alvo.checked);
      else abrirCardPorId(Number(aniv.dataset.card));
      return;
    }
    const parc = alvo.closest("[data-parcela]");
    if (parc) {
      if (alvo.classList.contains("ck-parc")) marcarParcelaPaga(Number(parc.dataset.parcela), alvo.checked);
      else abrirLancamentoPorId(Number(parc.dataset.lanc));
      return;
    }
    const entrada = alvo.closest("[data-dono]");
    if (entrada) {
      const donoId = Number(entrada.dataset.donoId);
      if (alvo.classList.contains("ck-ag")) marcarItem(entrada.dataset.dono, donoId, entrada.dataset.item, alvo.checked);
      else abrirPai(entrada.dataset.dono, donoId, cal.dados.tarefas);
      return;
    }
    const chip = alvo.closest("[data-id]");
    if (chip) abrirTarefa(cal.dados.tarefas.find((t) => t.id === Number(chip.dataset.id)));
  });
  tela.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" || ev.target.matches("input")) return;
    const el = ev.target.closest("[data-aniv], [data-parcela], [data-dono]");
    if (el) el.click();
  });
  $("#cal-grade").addEventListener("dblclick", (ev) => {
    const dia = ev.target.closest("[data-dia]");
    if (dia && !ev.target.closest("[data-id], [data-dono], [data-aniv], [data-parcela]")) {
      abrirTarefa(null, { prazo_fatal: dia.dataset.dia, data_interna: dia.dataset.dia });
    }
  });
}

ligarCalendario();
