"use strict";
// Financeiro: painel (cards de resumo, inadimplentes, próximas parcelas), tabela de parcelas filtrável, visão por
// cliente e o formulário de lançamento (entrada + parcelas mensais editáveis). Valores sempre em centavos.
// Usa app.js (api, esc, toast, reais, lerReais, dataBrCompleta, partesTexto…) e agenda.js (MESES, TELAS…).

const fin = {
  mes: isoLocal(new Date()).slice(0, 7), dados: null, aba: lerPreferencia("fin-aba") === "clientes" ? "clientes" : "parcelas",
  filtro: "todas", editando: null, linhas: [], editadas: false,
};
const SITUACAO = { paga: "Paga", pendente: "A vencer", atrasada: "Atrasada" };

const mesTexto = (aaaamm) => {
  const nome = MESES[Number(aaaamm.slice(5, 7)) - 1];
  return `${nome[0].toUpperCase() + nome.slice(1)} de ${aaaamm.slice(0, 4)}`;
};
const nomeMes = (aaaamm) => MESES[Number(aaaamm.slice(5, 7)) - 1];
const chaveCliente = (nome) => (nome || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();

function somarMeses(iso, n) {
  const [a, m, d] = iso.split("-").map(Number);
  const alvo = new Date(a, m - 1 + n, 1);
  const ultimo = new Date(alvo.getFullYear(), alvo.getMonth() + 1, 0).getDate();
  return isoLocal(new Date(alvo.getFullYear(), alvo.getMonth(), Math.min(d, ultimo)));
}

function quandoVence(iso) {
  const dias = Math.round((new Date(iso + "T12:00:00") - new Date(isoLocal(new Date()) + "T12:00:00")) / 864e5);
  return dias === 0 ? "hoje" : dias === 1 ? "amanhã" : `em ${dias} dias`;
}

// ---------- carregar e painel ----------
async function carregarFinanceiro() {
  fin.dados = await api(`/api/financeiro?mes=${fin.mes}`);
  renderFinanceiro();
}

function renderFinanceiro() {
  const d = fin.dados;
  if (!d) return;
  const r = d.resumo;
  $("#fin-mes-titulo").textContent = mesTexto(fin.mes);
  const mes = nomeMes(fin.mes);
  const card = (titulo, valor, sub, classe = "") =>
    `<div class="fin-card ${classe}"><div class="fin-card-tit">${titulo}</div><div class="fin-card-valor">${valor}</div><div class="fin-card-sub">${sub}</div></div>`;
  const qtdLanc = d.lancamentos.filter((l) => l.falta > 0).length;
  $("#fin-cards").innerHTML = [
    card(`A receber em ${mes}`, reais(r.a_receber_mes.pendente),
      r.a_receber_mes.previsto ? `${r.a_receber_mes.qtd_pendente} parcela(s) em aberto · ${reais(r.a_receber_mes.pago)} já pago de ${reais(r.a_receber_mes.previsto)}` : "nada vence neste mês", "destaque"),
    card(`Recebido em ${mes}`, reais(r.recebido_mes), "pela data do pagamento"),
    card(`Recebido em ${fin.mes.slice(0, 4)}`, reais(r.recebido_ano), "no ano todo"),
    card("Total a receber", reais(r.total_a_receber), qtdLanc ? `em ${qtdLanc} lançamento(s)` : "nada em aberto"),
    card("Em atraso", reais(r.em_atraso.valor),
      r.em_atraso.parcelas ? `${r.em_atraso.parcelas} parcela(s) · ${r.em_atraso.clientes} cliente(s)` : "ninguém em atraso",
      r.em_atraso.valor ? "alerta" : ""),
  ].join("");

  $("#fin-inad").innerHTML = r.inadimplentes.map((g) => `
    <button type="button" class="fin-linha" data-lanc="${g.lancamentos[0]}">
      <span class="fl-nome">${esc(g.cliente)}</span>
      <span class="fl-valor ruim">${reais(g.valor)}</span>
      <span class="fl-det">${g.parcelas} parcela(s) · <b>${g.dias_atraso} dia(s) de atraso</b> · desde ${dataBrCompleta(g.desde)}</span>
    </button>`).join("") || `<p class="nada">Ninguém em atraso.</p>`;

  $("#fin-proximas").innerHTML = r.proximas.map((p) => `
    <button type="button" class="fin-linha" data-lanc="${p.lancamento_id}">
      <span class="fl-nome">${esc(p.cliente)} <small>${p.numero === 0 ? "entrada" : esc(p.rotulo)}</small></span>
      <span class="fl-valor">${reais(p.valor)}</span>
      <span class="fl-det">${dataBrCompleta(p.vencimento)} · ${quandoVence(p.vencimento)}</span>
    </button>`).join("") || `<p class="nada">Nenhuma parcela a vencer.</p>`;

  document.querySelectorAll("#fin-aba [data-aba]").forEach((b) => b.classList.toggle("ativa", b.dataset.aba === fin.aba));
  document.querySelectorAll("#fin-filtro [data-f]").forEach((b) => b.classList.toggle("ativa", b.dataset.f === fin.filtro));
  $("#fin-so-mes").closest("label").hidden = fin.aba !== "parcelas";
  if (fin.aba === "parcelas") renderParcelas();
  else renderPorCliente();
}

// ---------- tabela de parcelas ----------
function casaBusca(l) {
  const q = $("#fin-busca").value.trim();
  if (!q) return true;
  const digitos = q.replace(/\D/g, "");
  return chaveCliente(l.cliente).includes(chaveCliente(q)) || (l.partes || "").toLowerCase().includes(q.toLowerCase())
    || (digitos.length >= 4 && (l.numero || "").includes(digitos));
}

function renderParcelas() {
  const soMes = $("#fin-so-mes").checked;
  const passa = {
    todas: () => true, pagas: (p) => p.pago, pendentes: (p) => !p.pago, atrasadas: (p) => p.situacao === "atrasada",
  }[fin.filtro];
  const linhas = fin.dados.lancamentos.filter(casaBusca)
    .flatMap((l) => l.parcelas.map((p) => ({ ...p, l })))
    .filter((p) => passa(p) && (!soMes || p.vencimento.slice(0, 7) === fin.mes))
    .sort((a, b) => a.vencimento.localeCompare(b.vencimento) || a.l.cliente.localeCompare(b.l.cliente));
  if (!linhas.length) {
    $("#fin-tabela").innerHTML = `<p class="vazio">${fin.dados.lancamentos.length
      ? "Nenhuma parcela com esses filtros." : "Nenhum lançamento ainda. Clique em <strong>+ Novo lançamento</strong>."}</p>`;
    return;
  }
  const total = linhas.reduce((s, p) => s + p.valor, 0);
  $("#fin-tabela").innerHTML = `
    <div class="tabela-rolagem fin-rolagem"><table class="tabela compacta fin-tabela">
      <thead><tr><th>Paga</th><th>Vencimento</th><th>Cliente</th><th>Parcela</th><th class="num">Valor</th><th>Situação</th><th>Pago em</th><th></th></tr></thead>
      <tbody>${linhas.map((p) => `
        <tr class="s-${p.situacao}" data-parcela="${p.id}">
          <td><input type="checkbox" class="fin-paga" ${p.pago ? "checked" : ""} aria-label="Paga: ${esc(p.l.cliente)} ${esc(p.rotulo)}"></td>
          <td>${dataBrCompleta(p.vencimento)}</td>
          <td><span class="ft-cli">${esc(p.l.cliente)}</span>${p.l.numero_fmt ? `<small class="ft-proc">${esc(p.l.numero_fmt)}</small>` : ""}</td>
          <td>${p.numero === 0 ? "Entrada" : esc(p.rotulo)}</td>
          <td class="num">${reais(p.valor)}</td>
          <td><span class="sit sit-${p.situacao}">${SITUACAO[p.situacao]}${p.situacao === "atrasada" ? ` · ${p.dias_atraso} dia(s)` : ""}</span></td>
          <td>${p.pago ? `<input type="date" class="campo fin-pago-em" value="${p.pago_em || ""}" aria-label="Data do pagamento">` : ""}</td>
          <td><button class="link pequeno" type="button" data-lanc="${p.lancamento_id}">abrir</button></td>
        </tr>`).join("")}</tbody>
      <tfoot><tr><td colspan="4">${linhas.length} parcela(s)</td><td class="num"><b>${reais(total)}</b></td><td colspan="3"></td></tr></tfoot>
    </table></div>`;
}

async function marcarPaga(id, pago, pagoEm) {
  try {
    await api(`/api/financeiro/parcelas/${id}/pagar`, { method: "POST", body: JSON.stringify({ pago, pago_em: pagoEm || null }) });
  } catch (e) {
    toast("Erro: " + e.message);
  }
  recarregarTela();
}

// ---------- por cliente: quanto falta receber ----------
function renderPorCliente() {
  const grupos = new Map();
  for (const l of fin.dados.lancamentos.filter(casaBusca)) {
    const k = chaveCliente(l.cliente);
    if (!grupos.has(k)) grupos.set(k, { cliente: l.cliente, total: 0, recebido: 0, falta: 0, atrasado: 0, proximo: null, lancs: [] });
    const g = grupos.get(k);
    g.total += l.valor_total;
    g.recebido += l.recebido;
    g.falta += l.falta;
    g.atrasado += l.atrasado;
    if (l.proximo_vencimento && (!g.proximo || l.proximo_vencimento < g.proximo)) g.proximo = l.proximo_vencimento;
    g.lancs.push(l);
  }
  const passa = { todas: () => true, pagas: (g) => !g.falta, pendentes: (g) => g.falta > 0, atrasadas: (g) => g.atrasado > 0 }[fin.filtro];
  const lista = [...grupos.values()].filter(passa).sort((a, b) => b.falta - a.falta || a.cliente.localeCompare(b.cliente));
  if (!lista.length) {
    $("#fin-tabela").innerHTML = `<p class="vazio">${fin.dados.lancamentos.length ? "Nenhum cliente com esses filtros." : "Nenhum lançamento ainda."}</p>`;
    return;
  }
  const soma = (campo) => lista.reduce((s, g) => s + g[campo], 0);
  $("#fin-tabela").innerHTML = `
    <div class="tabela-rolagem fin-rolagem"><table class="tabela compacta fin-tabela">
      <thead><tr><th>Cliente</th><th class="num">Total</th><th class="num">Recebido</th><th class="num">Falta receber</th><th class="num">Em atraso</th><th>Próximo vencimento</th><th>Lançamentos</th></tr></thead>
      <tbody>${lista.map((g) => {
        const pct = g.total ? Math.min(100, Math.round((100 * g.recebido) / g.total)) : 0;
        return `<tr>
          <td><span class="ft-cli">${esc(g.cliente)}</span><span class="fin-progresso" title="${pct}% recebido"><span style="width:${pct}%"></span></span></td>
          <td class="num">${reais(g.total)}</td>
          <td class="num">${reais(g.recebido)}</td>
          <td class="num"><b>${reais(g.falta)}</b></td>
          <td class="num ${g.atrasado ? "ruim" : ""}">${g.atrasado ? reais(g.atrasado) : "—"}</td>
          <td>${g.proximo ? dataBrCompleta(g.proximo) : "—"}</td>
          <td>${g.lancs.map((l) => `<button class="link pequeno" type="button" data-lanc="${l.id}">${l.numero_fmt ? esc(l.numero_fmt) : `lançamento ${l.id}`}</button>`).join("<br>")}</td>
        </tr>`;
      }).join("")}</tbody>
      <tfoot><tr><td>${lista.length} cliente(s)</td><td class="num">${reais(soma("total"))}</td><td class="num">${reais(soma("recebido"))}</td>
        <td class="num"><b>${reais(soma("falta"))}</b></td><td class="num">${reais(soma("atrasado"))}</td><td colspan="2"></td></tr></tfoot>
    </table></div>`;
}

// ---------- formulário de lançamento ----------
async function abrirLancamento(l) {
  fin.editando = l || null;
  $("#lc-titulo-dlg").textContent = l ? "Lançamento" : "Novo lançamento";
  $("#lc-cliente").value = l?.cliente || "";
  $("#lc-total").value = l ? reais(l.valor_total) : "";
  $("#lc-entrada").value = l?.entrada ? reais(l.entrada) : "";
  $("#lc-parcela").value = l?.valor_parcela ? reais(l.valor_parcela) : "";
  $("#lc-qtd").value = l ? l.qtd_parcelas : "";
  $("#lc-entrada-data").value = l?.entrada_data || "";
  const p1 = l?.parcelas.find((p) => p.numero === 1);
  $("#lc-primeiro").value = p1?.vencimento || "";
  $("#lc-obs").value = l?.observacoes || "";
  fin.linhas = (l?.parcelas || []).map(({ numero, vencimento, valor, pago, pago_em }) => ({ numero, vencimento, valor, pago: !!pago, pago_em }));
  // vencimentos já mexidos à mão (diferentes do "1 por mês")? então não regera sozinho
  fin.editadas = !!p1 && fin.linhas.some((p) => p.numero > 0 && p.vencimento !== somarMeses(p1.vencimento, p.numero - 1));
  $("#lc-excluir").hidden = !l;
  $("#lc-erro").hidden = true;
  renderLinhas();
  $("#dlg-lancamento").showModal();
  if (!l) $("#lc-cliente").focus();

  // listas de apoio: processos (para o select) e nomes de clientes já usados (Xablau e lançamentos)
  const [procs, quadroDados] = await Promise.all([
    api("/api/processos").then((d) => d.processos).catch(() => []),
    api("/api/quadro").catch(() => ({ cards: [] })),
  ]);
  const sel = $("#lc-processo");
  const ordenados = [...procs].sort((a, b) => partesTexto(a).localeCompare(partesTexto(b)));
  sel.innerHTML = `<option value="">— sem processo —</option>` + ordenados.map((p) =>
    `<option value="${p.numero}">${esc(p.numero_fmt)}${partesTexto(p) ? " — " + esc(partesTexto(p)) : ""}</option>`).join("")
    + (l?.numero && !procs.some((p) => p.numero === l.numero) ? `<option value="${l.numero}">${esc(l.numero_fmt)} (fora da lista)</option>` : "");
  sel.value = l?.numero || "";
  const nomes = new Set([...quadroDados.cards.map((c) => c.titulo), ...(fin.dados?.lancamentos || []).map((x) => x.cliente)]);
  $("#lc-clientes").innerHTML = [...nomes].sort().map((n) => `<option value="${esc(n)}">`).join("");
}

async function abrirLancamentoPorId(id) {
  try {
    if (!fin.dados || !fin.dados.lancamentos.some((l) => l.id === id)) fin.dados = await api(`/api/financeiro?mes=${fin.mes}`);
  } catch (e) {
    toast("Erro: " + e.message);
    return;
  }
  const l = fin.dados.lancamentos.find((x) => x.id === id);
  if (l) abrirLancamento(l);
  else toast("Lançamento não encontrado (foi excluído?).");
}

const valorCampo = (sel) => lerReais($(sel).value);

// Gera os vencimentos: entrada (data própria) + 1 parcela por mês a partir da 1ª data. Mantém "paga" de quem já tinha.
function gerarLinhas() {
  const antigas = new Map(fin.linhas.map((p) => [p.numero, p]));
  const qtd = Math.max(0, Math.min(360, parseInt($("#lc-qtd").value, 10) || 0));
  const primeiro = $("#lc-primeiro").value, valor = valorCampo("#lc-parcela") ?? 0;
  const linhas = linhaEntrada(antigas.get(0));
  if (primeiro && qtd) {
    for (let i = 0; i < qtd; i++) {
      const velha = antigas.get(i + 1);
      linhas.push({ numero: i + 1, vencimento: somarMeses(primeiro, i), valor, pago: velha?.pago || false, pago_em: velha?.pago_em || null });
    }
  }
  fin.linhas = linhas;
  fin.editadas = false;
  renderLinhas();
}

// Linha da entrada: sempre igual aos campos "valor da entrada" e "data de pagamento da entrada". Num lançamento novo,
// com a data de hoje ou passada, já nasce marcada como paga nessa data (dá para desmarcar).
function linhaEntrada(velha) {
  const valor = valorCampo("#lc-entrada"), data = $("#lc-entrada-data").value;
  if (!valor || !data) return [];
  const pagaPadrao = !fin.editando && data <= isoLocal(new Date());
  return [{ numero: 0, vencimento: data, valor, pago: velha ? velha.pago : pagaPadrao, pago_em: velha ? velha.pago_em : (pagaPadrao ? data : null) }];
}

function atualizarEntrada() {
  const resto = fin.linhas.filter((p) => p.numero > 0);
  fin.linhas = [...linhaEntrada(fin.linhas.find((p) => p.numero === 0)), ...resto];
  renderLinhas();
}

// Campos que mudam os vencimentos: regera sozinho, a não ser que ela já tenha mexido nos vencimentos à mão
function camposParcelasMudaram() {
  if (fin.editadas) {
    $("#lc-regerar").hidden = false;
    conferir();
  } else {
    gerarLinhas();
  }
}

function renderLinhas() {
  $("#lc-regerar").hidden = !fin.editadas;
  const qtd = parseInt($("#lc-qtd").value, 10) || 0;
  $("#lc-linhas").innerHTML = fin.linhas.map((p, i) => `
    <tr data-i="${i}" class="${p.pago ? "s-paga" : ""}">
      <td>${p.numero === 0 ? "Entrada" : `${p.numero}/${qtd || fin.linhas.filter((x) => x.numero > 0).length}`}</td>
      <td>${p.numero === 0 ? `${dataBrCompleta(p.vencimento)} <small class="ajuda">(data da entrada)</small>`
        : `<input type="date" class="campo lc-venc" value="${p.vencimento}" aria-label="Vencimento da parcela ${p.numero}">`}</td>
      <td>${p.numero === 0 ? reais(p.valor)
        : `<input type="text" class="campo dinheiro lc-valor" inputmode="decimal" value="${reais(p.valor)}" aria-label="Valor da parcela ${p.numero}">`}</td>
      <td><input type="checkbox" class="lc-paga" ${p.pago ? "checked" : ""} aria-label="Paga"></td>
      <td><input type="date" class="campo lc-pago-em" value="${p.pago_em || ""}" ${p.pago ? "" : "disabled"} aria-label="Data do pagamento"></td>
    </tr>`).join("") || `<tr><td colspan="5" class="nada">Preencha a entrada e/ou a quantidade de parcelas e a 1ª data.</td></tr>`;
  conferir();
}

// Conferência: entrada + parcelas = total. Se não bater, explica a diferença e oferece os ajustes.
function conferir() {
  const total = valorCampo("#lc-total"), entrada = valorCampo("#lc-entrada");
  const parcelas = fin.linhas.filter((p) => p.numero > 0);
  const qtd = parseInt($("#lc-qtd").value, 10) || 0;
  const somaParcelas = parcelas.length ? parcelas.reduce((s, p) => s + p.valor, 0) : (valorCampo("#lc-parcela") || 0) * qtd;
  const caixa = $("#lc-conf");
  const recebido = fin.linhas.filter((p) => p.pago).reduce((s, p) => s + p.valor, 0);
  const previsto = fin.linhas.reduce((s, p) => s + p.valor, 0);
  $("#lc-saldo").innerHTML = fin.linhas.length
    ? `Recebido <b>${reais(recebido)}</b> · Falta receber <b>${reais(previsto - recebido)}</b>` : "";
  if (total === null || entrada === null || [...document.querySelectorAll("#form-lancamento .dinheiro")].some((c) => lerReais(c.value) === null)) {
    caixa.className = "lc-conf ruim";
    caixa.textContent = "Valor inválido: use o formato 1.234,56.";
    return null;
  }
  if (!total) { caixa.className = "lc-conf"; caixa.textContent = ""; return 0; }
  const iguais = parcelas.length && parcelas.every((p) => p.valor === parcelas[0].valor);
  const conta = !qtd ? `entrada ${reais(entrada)}`
    : `entrada ${reais(entrada)} + ${iguais || !parcelas.length ? `${qtd} × ${reais(parcelas[0]?.valor ?? valorCampo("#lc-parcela"))}` : `parcelas ${reais(somaParcelas)}`}`;
  const dif = total - entrada - somaParcelas;
  if (!dif) {
    caixa.className = "lc-conf ok";
    caixa.textContent = `✓ Confere: ${conta} = ${reais(total)}`;
    return 0;
  }
  const pode = qtd > 0 && total - entrada >= 0;
  caixa.className = "lc-conf ruim";
  caixa.innerHTML = `⚠ Não fecha: ${esc(conta)} = <b>${reais(entrada + somaParcelas)}</b>, mas o total é <b>${reais(total)}</b>
    (${dif > 0 ? "faltam" : "sobram"} ${reais(Math.abs(dif))}).
    <span class="lc-ajustes">
      <button class="btn mini" type="button" data-ajuste="total">Usar ${reais(entrada + somaParcelas)} como total</button>
      ${pode ? `<button class="btn mini" type="button" data-ajuste="parcelas">Recalcular parcelas: (total − entrada) ÷ ${qtd}</button>` : ""}
    </span>`;
  return dif;
}

function ajustar(tipo) {
  const entrada = valorCampo("#lc-entrada") || 0, total = valorCampo("#lc-total") || 0;
  if (tipo === "total") {
    const soma = entrada + (fin.linhas.some((p) => p.numero > 0)
      ? fin.linhas.filter((p) => p.numero > 0).reduce((s, p) => s + p.valor, 0)
      : (valorCampo("#lc-parcela") || 0) * (parseInt($("#lc-qtd").value, 10) || 0));
    $("#lc-total").value = reais(soma);
  } else {
    // divide em partes iguais; os centavos que sobram vão para a última parcela
    const qtd = parseInt($("#lc-qtd").value, 10) || 0;
    const base = Math.floor((total - entrada) / qtd), resto = total - entrada - base * qtd;
    $("#lc-parcela").value = reais(base);
    if (!fin.linhas.some((p) => p.numero > 0)) gerarLinhas();
    const parcelas = fin.linhas.filter((p) => p.numero > 0);
    parcelas.forEach((p, i) => { p.valor = base + (i === parcelas.length - 1 ? resto : 0); });
    if (resto) toast(`A última parcela fica com ${reais(base + resto)} para fechar os centavos.`);
  }
  renderLinhas();
}

async function salvarLancamento() {
  const erro = (msg) => { $("#lc-erro").textContent = msg; $("#lc-erro").hidden = false; };
  $("#lc-erro").hidden = true;
  const cliente = $("#lc-cliente").value.trim();
  if (!cliente) { $("#lc-cliente").focus(); erro("Informe o nome do cliente."); return; }
  const dif = conferir();
  if (dif === null) { erro("Há um valor inválido (use o formato 1.234,56)."); return; }
  const total = valorCampo("#lc-total"), entrada = valorCampo("#lc-entrada");
  const qtd = parseInt($("#lc-qtd").value, 10) || 0;
  if (!total) { $("#lc-total").focus(); erro("Informe o valor total."); return; }
  if (entrada && !$("#lc-entrada-data").value) { $("#lc-entrada-data").focus(); erro("Informe a data de pagamento da entrada."); return; }
  if (fin.linhas.filter((p) => p.numero > 0).length !== qtd) {
    if (!$("#lc-primeiro").value && qtd) { $("#lc-primeiro").focus(); erro("Informe o vencimento da 1ª parcela."); return; }
    erro("A quantidade de parcelas mudou: clique em “Regerar vencimentos”.");
    return;
  }
  if (dif && !confirm(`Entrada + parcelas não fecham o total (${dif > 0 ? "faltam" : "sobram"} ${reais(Math.abs(dif))}).\nSalvar assim mesmo?`)) return;
  const d = {
    cliente, numero: $("#lc-processo").value || null, valor_total: total, entrada, entrada_data: $("#lc-entrada-data").value || null,
    valor_parcela: valorCampo("#lc-parcela") || 0, qtd_parcelas: qtd, observacoes: $("#lc-obs").value.trim() || null,
    parcelas: fin.linhas.map((p) => ({ numero: p.numero, vencimento: p.vencimento, valor: p.valor, pago: p.pago, pago_em: p.pago ? p.pago_em : null })),
  };
  try {
    if (fin.editando) await api(`/api/financeiro/lancamentos/${fin.editando.id}`, { method: "PUT", body: JSON.stringify(d) });
    else await api("/api/financeiro/lancamentos", { method: "POST", body: JSON.stringify(d) });
    $("#dlg-lancamento").close();
    toast(fin.editando ? "Lançamento salvo." : "Lançamento criado: os vencimentos já estão na Agenda.");
    recarregarTela();
  } catch (e) {
    erro(e.message);
  }
}

async function excluirLancamento() {
  const l = fin.editando;
  if (!l || !confirm(`Excluir o lançamento de ${l.cliente} e todas as parcelas?\nNão dá para desfazer.`)) return;
  try {
    await api(`/api/financeiro/lancamentos/${l.id}`, { method: "DELETE" });
    $("#dlg-lancamento").close();
    toast("Lançamento excluído.");
    recarregarTela();
  } catch (e) {
    toast("Erro: " + e.message);
  }
}

// ---------- eventos ----------
function ligarFinanceiro() {
  TELAS.financeiro = () => carregarFinanceiro();
  document.querySelectorAll("[data-fin-mes]").forEach((b) => {
    b.onclick = () => {
      const passo = Number(b.dataset.finMes);
      fin.mes = passo ? somarMeses(fin.mes + "-01", passo).slice(0, 7) : isoLocal(new Date()).slice(0, 7);
      carregarFinanceiro().catch((e) => toast("Erro: " + e.message));
    };
  });
  $("#fin-novo").onclick = () => abrirLancamento(null);
  $("#fin-aba").onclick = (ev) => {
    const b = ev.target.closest("[data-aba]");
    if (!b) return;
    fin.aba = b.dataset.aba;
    gravarPreferencia("fin-aba", fin.aba);
    renderFinanceiro();
  };
  $("#fin-filtro").onclick = (ev) => {
    const b = ev.target.closest("[data-f]");
    if (!b) return;
    fin.filtro = b.dataset.f;
    renderFinanceiro();
  };
  $("#fin-busca").oninput = renderFinanceiro;
  $("#fin-so-mes").onchange = renderFinanceiro;

  const tela = $("#tela-financeiro");
  tela.addEventListener("click", (ev) => {
    const lanc = ev.target.closest("[data-lanc]");
    if (lanc) { abrirLancamentoPorId(Number(lanc.dataset.lanc)); return; }
    if (ev.target.classList.contains("fin-paga")) {
      const id = Number(ev.target.closest("[data-parcela]").dataset.parcela);
      marcarPaga(id, ev.target.checked);
    }
  });
  tela.addEventListener("change", (ev) => {
    if (!ev.target.classList.contains("fin-pago-em") || !ev.target.value) return;
    marcarPaga(Number(ev.target.closest("[data-parcela]").dataset.parcela), true, ev.target.value);
  });

  // formulário
  const form = $("#form-lancamento");
  form.addEventListener("focusout", (ev) => {
    // valores em R$: formata ao sair do campo (1500 -> R$ 1.500,00)
    if (!ev.target.classList.contains("dinheiro")) return;
    const v = lerReais(ev.target.value);
    if (v !== null && ev.target.value.trim()) ev.target.value = reais(v);
  });
  $("#lc-total").addEventListener("input", conferir);
  $("#lc-entrada").addEventListener("input", atualizarEntrada);
  $("#lc-entrada-data").addEventListener("input", atualizarEntrada);
  ["#lc-parcela", "#lc-qtd", "#lc-primeiro"].forEach((s) => $(s).addEventListener("input", camposParcelasMudaram));
  $("#lc-regerar").onclick = () => {
    if (confirm("Refazer os vencimentos (1 por mês a partir da 1ª data)? As datas e valores mudados à mão se perdem; o que já está marcado como pago continua.")) gerarLinhas();
  };
  $("#lc-conf").onclick = (ev) => { const b = ev.target.closest("[data-ajuste]"); if (b) ajustar(b.dataset.ajuste); };
  $("#lc-linhas").addEventListener("change", (ev) => {
    const tr = ev.target.closest("tr[data-i]");
    if (!tr) return;
    const p = fin.linhas[Number(tr.dataset.i)];
    const el = ev.target;
    if (el.classList.contains("lc-venc") && el.value) { p.vencimento = el.value; fin.editadas = true; renderLinhas(); }
    if (el.classList.contains("lc-valor")) {
      const v = lerReais(el.value);
      if (v === null) { el.focus(); toast("Valor inválido: use o formato 1.234,56."); return; }
      p.valor = v;
      fin.editadas = true;
      renderLinhas();
    }
    if (el.classList.contains("lc-paga")) {
      p.pago = el.checked;
      p.pago_em = el.checked ? (p.pago_em || isoLocal(new Date())) : null;
      renderLinhas();
    }
    if (el.classList.contains("lc-pago-em")) { p.pago_em = el.value || isoLocal(new Date()); }
  });
  $("#lc-salvar").onclick = salvarLancamento;
  $("#lc-excluir").onclick = excluirLancamento;
}

ligarFinanceiro();
