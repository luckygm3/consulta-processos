"use strict";
// Agenda: calendário único. Junta, sem copiar nada, o que já existe em cada lugar:
// - Prazos e tarefas (fonte "monitoramento"): itens dos clientes que vieram de uma sugestão aprovada no Monitoramento
//   ou de "+ Nova tarefa", com a cor da urgência;
// - Checklists dos clientes: os outros itens com data dos cards e o prazo fatal interno do card;
// - Aniversários: "Parabenizar <cliente>" todo ano, com "feito" por ano;
// - Financeiro: lembrete de cada parcela 1 dia depois do vencimento, para conferir se foi paga (a parcial, pelo que falta).
// Sugestões ainda não aprovadas não aparecem. Usa helpers de app.js, agenda.js (dataBr, itemAgendaHTML, prazoCardHTML,
// entradasDe, abrirTarefa…) e quadro.js.

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
  const { itens, prazos } = entradasDe(d.cards, { adv: adv || "", proc: "" });
  const agrupar = (xs, campo = "data") => xs.reduce((m, x) => (x[campo] && (m[x[campo]] ||= []).push(x), m), {});
  // tarefa (veio do Monitoramento ou de "+ Nova tarefa") primeiro, com a cor da urgência; depois os itens comuns
  const tarefasDia = ver("monitoramento") ? agrupar(itens.filter((c) => c.tipo)) : {};
  const itensDia = ver("clientes") ? agrupar(itens.filter((c) => !c.tipo)) : {};
  const prazosDia = ver("clientes") ? agrupar(prazos) : {};
  const anivDia = ver("aniversarios") ? agrupar(d.aniversarios) : {};
  const parcDia = ver("financeiro") ? agrupar(d.parcelas) : {};
  const hoje = isoLocal(new Date());

  $("#cal-grade").className = `cal-grade ${cal.modo}`;
  $("#cal-grade").innerHTML = SEMANA.map((s) => `<div class="cal-cab">${s}</div>`).join("") + datas.map((iso) => {
    const dt = new Date(iso + "T12:00:00");
    const fora = cal.modo === "mes" && dt.getMonth() !== ref.getMonth();
    const fer = cal.feriados.filter((f) => f.data === iso);
    const porHora = (xs) => (xs || []).sort((a, b) => (a.hora || "99").localeCompare(b.hora || "99")).map(itemAgendaHTML);
    const tfs = porHora(tarefasDia[iso]);
    const pzs = (prazosDia[iso] || []).map(prazoCardHTML);
    const anivs = (anivDia[iso] || []).map(aniversarioHTML);
    const parcs = (parcDia[iso] || []).map(parcelaHTML);
    const its = porHora(itensDia[iso]);
    // no mês, dia cheio mostra os 4 primeiros e "+N mais" (abre o resto ali mesmo)
    const todos = [...tfs, ...pzs, ...anivs, ...parcs, ...its];
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
      else abrirPai(entrada.dataset.dono, donoId);
    }
  });
  tela.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter" || ev.target.matches("input")) return;
    const el = ev.target.closest("[data-aniv], [data-parcela], [data-dono]");
    if (el) el.click();
  });
  // tarefa nova: vai direto para o checklist de um cliente (dois cliques num dia já trazem a data)
  const advFiltro = () => Number($("#cal-adv").value) || null;
  $("#cal-nova").onclick = () => abrirTarefa(null, { advogada_id: advFiltro() });
  $("#cal-grade").addEventListener("dblclick", (ev) => {
    const dia = ev.target.closest("[data-dia]");
    if (dia && !ev.target.closest("[data-dono], [data-aniv], [data-parcela]")) {
      abrirTarefa(null, { prazo_fatal: dia.dataset.dia, advogada_id: advFiltro() });
    }
  });
  $("#cal-ics").onclick = exportarIcs;
}

// ---------- exportar .ics (Google Agenda) ----------
// Exporta as tarefas dos clientes ainda não feitas (as aprovadas no Monitoramento e as de "+ Nova tarefa") e os prazos
// fatais internos dos cards, da advogada do filtro (ou de todas). Itens comuns de checklist ficam de fora.
function exportarIcs() {
  if (!cal.dados) return;
  const adv = Number($("#cal-adv").value) || null;
  const { itens, prazos } = entradasDe(cal.dados.cards, { adv: adv || "", proc: "" });
  const eventos = [
    ...itens.filter((c) => c.tipo && !c.feito).map((c) => ({
      uid: `item-${c.pai.id}-${c.id}`, data: c.data, hora: c.hora, pai: c.pai,
      titulo: (c.tipo === "prazo" ? "PRAZO: " : "") + c.texto, resp: pessoaPorChave(c.resp)?.nome_completo })),
    ...prazos.map((p) => ({ uid: `prazo-card-${p.pai.id}`, data: p.data, hora: p.hora, pai: p.pai,
      titulo: "PRAZO: " + p.descricao })),
  ];
  if (!eventos.length) { toast("Nada para exportar (só entram tarefas com data ainda não feitas)."); return; }
  const blob = new Blob([gerarIcs(eventos)], { type: "text/calendar;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `prazos-${isoLocal(new Date())}.ics`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  toast(`${eventos.length} evento(s) exportado(s)${adv ? " (só da advogada do filtro)" : ""}. No Google Agenda: Configurações → Importar e exportar → Importar.`);
}

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

function gerarIcs(eventos) {
  const agora = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
  const dia = (iso) => iso.replace(/-/g, "");
  const seguinte = (iso) => isoLocal(new Date(new Date(iso + "T12:00:00").getTime() + 864e5)).replace(/-/g, "");
  const linhas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//processos-local//agenda//PT-BR", "CALSCALE:GREGORIAN",
    "X-WR-CALNAME:Prazos e tarefas"];
  eventos.forEach((e) => {
    const desc = [`Cliente: ${e.pai.nome}`, e.pai.numero_fmt && `Processo ${e.pai.numero_fmt}`, e.pai.partes,
      e.resp && `Responsável: ${e.resp}`,
      "Prazos calculados automaticamente são sugestões. Confirme sempre no processo e no calendário do tribunal."]
      .filter(Boolean).join("\n");
    const ev = ["BEGIN:VEVENT", `UID:${e.uid}@processos-local`, `DTSTAMP:${agora}`];
    if (e.hora) {
      const [h, m] = e.hora.split(":").map(Number);
      ev.push(`DTSTART:${dia(e.data)}T${e.hora.replace(":", "")}00`,
        `DTEND:${dia(e.data)}T${String(Math.min(h + 1, 23)).padStart(2, "0")}${String(m).padStart(2, "0")}00`);
    } else {
      ev.push(`DTSTART;VALUE=DATE:${dia(e.data)}`, `DTEND;VALUE=DATE:${seguinte(e.data)}`);
    }
    ev.push(`SUMMARY:${icsTexto(e.titulo + " — " + e.pai.nome)}`, `DESCRIPTION:${icsTexto(desc)}`, "TRANSP:TRANSPARENT", "END:VEVENT");
    linhas.push(...ev);
  });
  linhas.push("END:VCALENDAR");
  return linhas.map(icsDobrar).join("\r\n") + "\r\n";
}

ligarCalendario();
