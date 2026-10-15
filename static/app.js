"use strict";

// ---------- utilidades ----------
const $ = (s) => document.querySelector(s);
const estado = {
  processos: [], filtros: { tribunais: [] }, aberto: null, sincronizando: false, aba: "tudo", mostrouFim: false,
  advogadas: [], contadores: {}, advogada: lerPreferencia("advogada"), // "" = todas
  pessoas: [], // responsáveis nos itens de checklist: advogadas ("a:<id>") + equipe ("p:<id>")
};

function pessoaPorChave(chave) {
  return chave ? estado.pessoas.find((p) => p.chave === chave) : null;
}

async function carregarPessoas() {
  try { estado.pessoas = await api("/api/pessoas"); } catch (_) { /* sem a lista, os itens só não mostram o nome */ }
}

function lerPreferencia(chave) {
  try { return localStorage.getItem(chave) || ""; } catch (_) { return ""; }
}
function gravarPreferencia(chave, valor) {
  try { localStorage.setItem(chave, valor); } catch (_) { /* navegador sem armazenamento: só não lembra */ }
}

// Cards expandidos/contraídos (agenda e quadro): um modo geral + exceções por card, lembrados neste navegador
function memoriaCards(chave) {
  let s = { contraidos: false, excecoes: [] };
  try { s = { ...s, ...JSON.parse(lerPreferencia(chave) || "{}") }; } catch (_) { /* preferência corrompida: padrão */ }
  const excecoes = new Set(s.excecoes);
  const gravar = () => gravarPreferencia(chave, JSON.stringify({ contraidos: s.contraidos, excecoes: [...excecoes] }));
  return {
    get todosContraidos() { return s.contraidos; },
    contraido: (id) => s.contraidos !== excecoes.has(id),
    alternar(id) {
      if (!excecoes.delete(id)) excecoes.add(id);
      gravar();
      return s.contraidos !== excecoes.has(id);
    },
    definirTodos(contrair) { s.contraidos = contrair; excecoes.clear(); gravar(); },
  };
}

function alternarCard(el, memoria) {
  el.classList.toggle("contraido", memoria.alternar(Number(el.dataset.id)));
}

// Botão "Contrair todos / Expandir todos": muda todos os cards visíveis e zera as escolhas individuais
function ligarExpandir(botao, memoria, seletor) {
  const rotulo = () => { botao.textContent = memoria.todosContraidos ? "Expandir todos" : "Contrair todos"; };
  botao.onclick = () => {
    memoria.definirTodos(!memoria.todosContraidos);
    document.querySelectorAll(seletor).forEach((c) => c.classList.toggle("contraido", memoria.todosContraidos));
    rotulo();
  };
  rotulo();
}

// Chamada à API com o token do login (auth.js). 401/403 levam de volta à tela de login.
async function api(url, opcoes = {}) {
  const token = await tokenAtual();
  const r = await fetch(url, {
    ...opcoes, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
  });
  if (!r.ok) {
    let msg = `Erro ${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* resposta sem JSON */ }
    if (r.status === 401 || r.status === 403) sessaoRecusada(r.status, msg, token);
    throw Object.assign(new Error(msg), { status: r.status });
  }
  return r.json();
}

// Salva um card, tarefa ou lançamento que já existe mandando a versão que a tela leu (atualizado_em). Se outra
// pessoa (ou outra aba) salvou depois, o servidor recusa (409) para não apagar o que ela fez, e aqui se pergunta:
// salvar mesmo assim, ou não salvar. Não salvando, o diálogo fica como está (nada do que foi digitado se perde) e a
// tela recarrega por trás, para que fechar e abrir de novo mostre a versão atual.
async function salvarConferindo(url, metodo, dados, lido, aviso) {
  try {
    return await api(url, { method: metodo, body: JSON.stringify({ ...dados, versao: lido.atualizado_em ?? null }) });
  } catch (e) {
    if (e.status !== 409) throw e;
  }
  if (!confirm(`${aviso} por outra pessoa (ou em outra aba) enquanto você editava.\n\n`
    + "OK = salvar mesmo assim (o que foi mudado lá se perde)\n"
    + "Cancelar = não salvar agora (o que você digitou continua aqui)")) {
    recarregarTela();
    throw new Error("Não salvo: isto foi alterado enquanto você editava. Feche e abra de novo para ver a versão atual.");
  }
  return api(url, { method: metodo, body: JSON.stringify(dados) });
}

const esperar = (ms) => new Promise((ok) => setTimeout(ok, ms));

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function isoLocal(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtData(iso) {
  if (!iso) return "";
  const dia = iso.slice(0, 10);
  const hoje = new Date();
  const ontem = new Date(Date.now() - 864e5);
  if (dia === isoLocal(hoje)) return "hoje";
  if (dia === isoLocal(ontem)) return "ontem";
  const [a, m, d] = dia.split("-");
  return `${d}/${m}/${a}`;
}

// dd/mm/aaaa (sem "hoje"/"ontem"), para o financeiro e o calendário
function dataBrCompleta(iso) {
  if (!iso) return "";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

// Valores em centavos (inteiros) -> "R$ 1.234,56"
const FORMATO_REAIS = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
function reais(centavos) {
  return FORMATO_REAIS.format((Number(centavos) || 0) / 100).replace(/ /g, " ");
}

// "R$ 1.234,56", "1234,56", "1.500" (mil e quinhentos) ou "1500.5" -> centavos; vazio = 0; inválido = null
function lerReais(texto) {
  let s = String(texto ?? "").replace(/R\$|\s/g, "");
  if (!s) return 0;
  if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
  else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, "");
  if (!/^\d+(\.\d{0,2})?$/.test(s)) return null;
  return Math.round(parseFloat(s) * 100);
}

function fmtDataHora(iso) {
  if (!iso) return "";
  const hora = iso.length > 10 ? iso.slice(11, 16) : "";
  return fmtData(iso) + (hora && hora !== "00:00" ? ` às ${hora}` : "");
}

function recente(iso) {
  return iso && (Date.now() - new Date(iso.slice(0, 10) + "T12:00:00").getTime()) < 3 * 864e5;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3500);
}

const SEM_DADOS = "sem dados públicos (possível segredo de justiça)";

// ---------- estado geral ----------
async function carregarEstado() {
  const e = await api("/api/estado");
  estado.advogadas = e.advogadas || [];
  estado.identidade = estado.advogadas.length
    ? estado.advogadas.map((a) => `${a.nome} · OAB ${a.oab_numero}/${a.oab_uf}`).join("   |   ")
    : [e.nome, e.oab && `OAB ${e.oab}`].filter(Boolean).join(" · ");
  atualizarCabecalho(); // subtítulo do topo: as OABs nos Andamentos, a descrição da tela nas outras
  $("#ultima").textContent = e.ultima_atualizacao ? `Última atualização: ${fmtDataHora(e.ultima_atualizacao)}` : "Ainda não atualizado";
  $("#aviso-chave").hidden = e.tem_chave;
  $("#aviso-banco-local").hidden = e.banco_local !== "pendente";
  if (e.sync.rodando) acompanharSync();
  else mostrarResultado(e.sync, false);
}

// ---------- lista ----------
function filtrosAtuais() {
  return {
    q: $("#f-q").value.trim(), tribunal: $("#f-tribunal").value, novidades: $("#f-novidades").checked ? "true" : "",
    advogada: estado.advogada,
  };
}

async function carregarProcessos() {
  const f = filtrosAtuais();
  const params = new URLSearchParams(Object.entries(f).filter(([, v]) => v));
  const d = await api("/api/processos?" + params);
  estado.processos = d.processos;
  estado.filtros = d.filtros;
  estado.advogadas = d.filtros.advogadas || [];
  estado.contadores = d.contadores || {};
  estado.cooperacao = d.cooperacao || { ocultar: false, qtd: 0 };
  if (estado.advogada && !estado.advogadas.some((a) => String(a.id) === estado.advogada)) {
    escolherAdvogada(""); // advogada lembrada não existe mais no config.json
    return;
  }
  preencherFiltros();
  renderTabela();
  $("#btn-limpar").hidden = !Object.values(f).some(Boolean);
}

function advogadaPorId(id) {
  return estado.advogadas.find((a) => a.id === id);
}

function primeiroNome(a) {
  return (a.nome || "").split(/\s+/)[0] || a.nome;
}

// Etiqueta colorida com o nome de quem atua no processo
function etiquetaAdv(a) {
  return `<span class="etq-adv" style="--cor:${esc(a.cor)}" title="${esc(a.nome)} · OAB ${esc(a.oab_numero)}/${esc(a.oab_uf)}">${esc(primeiroNome(a))}</span>`;
}

// Etiqueta do responsável por um item de checklist: advogada com a cor dela; outras pessoas em cinza
function etiquetaPessoa(p) {
  const adv = p.advogada_id && advogadaPorId(p.advogada_id);
  return adv ? etiquetaAdv(adv) : `<span class="etq-adv" style="--cor:#5a6270" title="${esc(p.nome_completo)}">${esc(p.nome)}</span>`;
}

function escolherAdvogada(id) {
  estado.advogada = id;
  gravarPreferencia("advogada", id);
  carregarProcessos();
}

function preencherAdvogadas() {
  const caixa = $("#f-advogada");
  caixa.hidden = estado.advogadas.length < 2;
  if (caixa.hidden) return;
  const conta = (k) => {
    const c = estado.contadores[k] || { total: 0, novos: 0 };
    return `<span class="qtd">${c.total}</span>${c.novos ? `<span class="qtd-novos" title="com novidades">${c.novos} novo${c.novos > 1 ? "s" : ""}</span>` : ""}`;
  };
  const botoes = [["", "Todas", null, "todas"], ...estado.advogadas.map((a) => [String(a.id), primeiroNome(a), a.cor, a.id])];
  caixa.innerHTML = botoes.map(([id, rotulo, cor, k]) => `
    <button type="button" data-adv="${id}" class="${estado.advogada === id ? "ativa" : ""}" aria-pressed="${estado.advogada === id}">
      ${cor ? `<span class="bolinha" style="background:${esc(cor)}"></span>` : ""}${esc(rotulo)} ${conta(k)}
    </button>`).join("");
}

function preencherFiltros() {
  preencherAdvogadas();
  const selT = $("#f-tribunal"), t = selT.value;
  selT.innerHTML = `<option value="">Todos os tribunais</option>` +
    estado.filtros.tribunais.map((x) => `<option ${x === t ? "selected" : ""}>${esc(x)}</option>`).join("");
}

function partesTexto(p) {
  const nome = (lista) => (lista && lista.length ? lista[0] + (lista.length > 1 ? " e outros" : "") : "");
  const a = nome(p.partes.ativo), r = nome(p.partes.passivo);
  return a && r ? `${a} × ${r}` : a || r || "";
}

function celulaMov(p) {
  if (p.ult_mov_data) {
    return `<div class="data ${recente(p.ult_mov_data) ? "recente" : ""}">${fmtDataHora(p.ult_mov_data)}</div>
            <div class="trecho">${esc(p.ult_mov_texto)}</div>`;
  }
  const msg = {
    sem_dados: SEM_DADOS, sem_alias: "tribunal não publica no DataJud",
    erro: "DataJud não respondeu por completo; será consultado de novo na próxima atualização",
  }[p.datajud_status] || "—";
  return `<span class="${p.datajud_status ? "sem-dados" : "nada"}">${msg}</span>`;
}

function celulaPub(p) {
  if (!p.ult_pub_data) return `<span class="nada">—</span>`;
  return `<div class="data ${recente(p.ult_pub_data) ? "recente" : ""}">${fmtData(p.ult_pub_data)}</div>
          <div class="trecho">${esc(p.ult_pub_texto)}</div>`;
}

function renderTabela() {
  const lista = estado.processos;
  $("#linhas").innerHTML = lista.map((p) => `
    <tr data-num="${p.numero}" class="${p.novo ? "novo" : ""} ${p.numero === estado.aberto ? "ativa" : ""}">
      <td data-rotulo="Processo">
        <div class="num"><span class="n">${esc(p.numero_fmt)}</span>${p.novo ? `<span class="selo">NOVO</span>` : ""}${p.origem === "manual" ? `<span class="selo manual">manual</span>` : ""}${p.cooperacao ? `<span class="selo manual" title="Processo em cooperação">cooperação</span>` : ""}</div>
        <div class="partes">${esc(partesTexto(p))}</div>
        ${estado.advogadas.length > 1 ? `<div class="etqs">${p.advogadas.map(advogadaPorId).filter(Boolean).map(etiquetaAdv).join("")}</div>` : ""}
        ${p.novo ? `<button class="link pequeno visto-btn" type="button" data-visto="${p.numero}">marcar como visto</button>` : ""}
      </td>
      <td data-rotulo="Tribunal">${esc(p.tribunal)}</td>
      <td data-rotulo="Vara / Órgão">${esc(p.orgao) || `<span class="nada">—</span>`}</td>
      <td data-rotulo="Classe">${esc(p.classe) || `<span class="nada">—</span>`}</td>
      <td data-rotulo="Últ. movimentação">${celulaMov(p)}</td>
      <td data-rotulo="Últ. publicação">${celulaPub(p)}</td>
    </tr>`).join("");

  const novos = lista.filter((p) => p.novo).length;
  const n = lista.length;
  $("#contagem").textContent = `${n} ${n === 1 ? "processo" : "processos"}` + (novos ? ` · ${novos} com novidades` : "");
  $("#btn-vistos").hidden = !novos;
  avisoCooperacao();

  const vazio = $("#vazio");
  vazio.hidden = n > 0;
  if (!n) {
    const temFiltro = Object.values(filtrosAtuais()).some(Boolean);
    vazio.innerHTML = temFiltro
      ? "Nenhum processo com esses filtros."
      : "Nenhum processo ainda. Clique em <strong>Atualizar tudo</strong> para buscar suas publicações no DJEN, ou em <strong>Adicionar processos</strong>.";
  }
}

// Aviso discreto ao lado da contagem: quantos processos em cooperação estão ocultos (ou na lista), com o atalho
// para ligar/desligar a opção das Configurações
function avisoCooperacao() {
  const { ocultar, qtd } = estado.cooperacao || {};
  const aviso = $("#coop-aviso");
  aviso.hidden = !qtd;
  if (!qtd) return;
  aviso.innerHTML = ocultar
    ? `${qtd} ${qtd === 1 ? "processo em cooperação oculto" : "processos em cooperação ocultos"} · <button class="link pequeno" type="button" data-coop="0">mostrar</button>`
    : `${qtd} em cooperação na lista · <button class="link pequeno" type="button" data-coop="1">ocultar</button>`;
}

async function ocultarCooperacao(ocultar) {
  try {
    await api("/api/config", { method: "POST", body: JSON.stringify({ ocultar_cooperacao: ocultar }) });
    toast(ocultar ? "Processos em cooperação ocultos." : "Processos em cooperação aparecendo de novo.");
  } catch (e) {
    toast("Erro: " + e.message);
  }
  carregarProcessos();
  carregarAlertas();
}

async function marcarCooperacao(p, valor) {
  try {
    await api(`/api/processos/${p.numero}/cooperacao`, { method: "POST", body: JSON.stringify({ cooperacao: valor }) });
  } catch (e) {
    toast("Erro: " + e.message);
    return;
  }
  toast(valor && estado.cooperacao?.ocultar ? "Marcado como cooperação: some da lista enquanto a opção estiver ligada."
    : valor ? "Marcado como processo em cooperação." : "Desmarcado: não é processo em cooperação.");
  carregarProcessos();
  carregarAlertas();
  abrirPainel(p.numero);
}

// Explica no painel de onde vem a marcação (à mão ou qual advogado de cooperação consta)
function origemCooperacao(p) {
  const quem = p.cooperacao_por;
  const nome = quem ? esc(quem.nome || "advogado de cooperação") + (quem.oab_numero ? ` (OAB ${esc(quem.oab_numero)}${quem.oab_uf ? "/" + esc(quem.oab_uf) : ""})` : "") : "";
  if (p.cooperacao_manual !== null && p.cooperacao_manual !== undefined) {
    return p.cooperacao ? "marcado à mão" : `desmarcado à mão${nome ? ` · consta ${nome}` : ""}`;
  }
  return nome ? `consta ${nome}` : "";
}

async function marcarVisto(numero) {
  await api(`/api/processos/${numero}/visto`, { method: "POST" });
  const p = estado.processos.find((x) => x.numero === numero);
  if (p) p.novo = false;
  renderTabela();
  carregarProcessos(); // atualiza os contadores por advogada
  if (estado.aberto === numero) abrirPainel(numero);
}

// ---------- painel lateral ----------
async function abrirPainel(numero) {
  estado.aberto = numero;
  document.querySelectorAll("#linhas tr").forEach((tr) => tr.classList.toggle("ativa", tr.dataset.num === numero));
  const painel = $("#painel");
  if (!painel.classList.contains("aberto")) {
    $("#p-numero").textContent = "…";
    $("#p-sub").textContent = "";
    $("#p-corpo").innerHTML = `<p class="nada">Carregando…</p>`;
  }
  painel.classList.add("aberto");
  painel.setAttribute("aria-hidden", "false");
  $("#fundo").hidden = false;
  try {
    const p = await api(`/api/processos/${numero}`);
    if (estado.aberto === numero) renderPainel(p);
  } catch (e) {
    $("#p-corpo").innerHTML = `<div class="nota erro">${esc(e.message)}</div>`;
  }
}

function fecharPainel() {
  estado.aberto = null;
  $("#painel").classList.remove("aberto");
  $("#painel").setAttribute("aria-hidden", "true");
  $("#fundo").hidden = true;
  document.querySelectorAll("#linhas tr.ativa").forEach((tr) => tr.classList.remove("ativa"));
}

function renderPainel(p) {
  $("#p-numero").textContent = p.numero_fmt;
  $("#p-copiar").dataset.num = p.numero_fmt;
  $("#p-sub").textContent = [p.tribunal, p.grau, p.orgao].filter(Boolean).join(" · ");

  const notas = {
    sem_dados: `DataJud: ${SEM_DADOS}. As publicações do DJEN aparecem abaixo.`,
    sem_alias: "Este tribunal não publica dados no DataJud; só as publicações do DJEN estão disponíveis.",
    erro: p.datajud_msg || "A última consulta ao DataJud falhou.",
  };
  let nota = "";
  if (notas[p.datajud_status]) {
    nota = `<div class="nota ${p.datajud_status === "erro" ? "erro" : ""}">${esc(notas[p.datajud_status])}</div>`;
  } else if (!p.datajud_status) {
    nota = `<div class="nota">DataJud ainda não consultado para este processo.</div>`;
  } else if (p.datajud_msg) {
    nota = `<div class="nota erro">${esc(p.datajud_msg)}</div>`;
  }

  const lista = (xs) => xs && xs.length ? xs.map(esc).join("<br>") : "";
  const partes = [
    p.partes.ativo?.length ? `<strong>Polo ativo:</strong> ${lista(p.partes.ativo)}` : "",
    p.partes.passivo?.length ? `<strong>Polo passivo:</strong> ${lista(p.partes.passivo)}` : "",
    p.partes.outros?.length ? `<strong>Outros:</strong> ${lista(p.partes.outros)}` : "",
  ].filter(Boolean).join("<br>");
  const instancias = p.instancias.length > 1
    ? p.instancias.map((i) => `${esc(i.grau)} — ${esc(i.orgao || "")}${i.classe ? ` (${esc(i.classe)})` : ""}`).join("<br>") : "";
  const linhasFicha = [
    ["Classe", esc(p.classe)],
    ["Assuntos", esc(p.assuntos.join("; "))],
    ["Partes", partes],
    ["Órgão julgador", esc(p.orgao)],
    ["Instâncias", instancias],
    ["Ajuizamento", fmtData(p.data_ajuizamento)],
    ["Sistema", esc(p.sistema)],
    ["Advogada(s)", p.advogadas.map(advogadaPorId).filter(Boolean).map((a) => `${etiquetaAdv(a)} ${esc(a.nome)}`).join("<br>")],
    ["Origem", p.origem === "manual" ? "Adicionado manualmente" : "Encontrado pelas publicações do DJEN"],
    ["DataJud consultado", fmtDataHora(p.datajud_em)],
    ["Cooperação", `<label class="chk"><input type="checkbox" id="pa-coop" ${p.cooperacao ? "checked" : ""}> Processo em cooperação</label>
      <div class="ajuda pa-coop-ajuda">${origemCooperacao(p)}</div>`],
    ["Contagem de prazos", `<select id="pa-contagem" class="campo mini">
      <option value="">padrão (dias úteis, ou o do tipo de ato)</option>
      <option value="uteis" ${p.contagem === "uteis" ? "selected" : ""}>sempre dias úteis</option>
      <option value="corridos" ${p.contagem === "corridos" ? "selected" : ""}>sempre dias corridos</option></select>`],
  ].filter(([, v]) => v);

  const eventos = p.eventos;
  const qtd = { tudo: eventos.length, djen: eventos.filter((e) => e.fonte === "djen").length };
  qtd.datajud = qtd.tudo - qtd.djen;

  $("#p-corpo").innerHTML = `
    <div class="painel-acoes">
      <button class="btn ${p.novo ? "primario" : ""}" type="button" id="pa-visto" ${p.novo ? "" : "disabled"}>${p.novo ? "✓ Marcar como visto" : "✓ Visto"}</button>
      <button class="btn" type="button" id="pa-atualizar">⟳ Atualizar este processo</button>
      <button class="btn" type="button" id="pa-tarefa" title="Vai direto para o checklist do cliente deste processo">+ Tarefa / prazo</button>
      ${(p.clientes || []).map((c) => `<button class="btn" type="button" data-pa-cliente="${c.id}" title="Abrir o cliente (card em Clientes)">👤 ${esc(c.nome)}</button>`).join("")}
      <button class="btn perigo" type="button" id="pa-remover">Remover da lista</button>
    </div>
    ${nota}
    <dl class="ficha">${linhasFicha.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>
    <div class="linha-titulo">
      <h3>Linha do tempo</h3>
      <div class="abas" role="tablist">
        ${[["tudo", "Tudo"], ["djen", "Publicações"], ["datajud", "Movimentos"]].map(([k, r]) =>
          `<button type="button" data-aba="${k}" class="${estado.aba === k ? "ativa" : ""}">${r} (${qtd[k]})</button>`).join("")}
      </div>
    </div>
    <ol class="tempo" id="tempo"></ol>`;

  $("#pa-visto").onclick = () => marcarVisto(p.numero);
  $("#pa-atualizar").onclick = () => atualizarUm(p.numero);
  $("#pa-tarefa").onclick = () => abrirTarefa(null, {
    numero: p.numero, numero_fmt: p.numero_fmt, tipo: "prazo",
    advogada_id: p.advogadas.length === 1 ? p.advogadas[0] : null,
  });
  $("#p-corpo").querySelectorAll("[data-pa-cliente]").forEach((b) => { b.onclick = () => abrirCardPorId(Number(b.dataset.paCliente)); });
  $("#pa-contagem").onchange = async (ev) => {
    await api(`/api/processos/${p.numero}/contagem`, { method: "POST", body: JSON.stringify({ contagem: ev.target.value }) });
    toast("Contagem salva: vale para os próximos cálculos deste processo.");
  };
  $("#pa-remover").onclick = () => removerProcesso(p);
  $("#pa-coop").onchange = (ev) => marcarCooperacao(p, ev.target.checked);
  $("#p-corpo").querySelectorAll("[data-aba]").forEach((b) => {
    b.onclick = () => {
      estado.aba = b.dataset.aba;
      $("#p-corpo").querySelectorAll("[data-aba]").forEach((x) => x.classList.toggle("ativa", x === b));
      renderTempo(eventos);
    };
  });
  renderTempo(eventos);
}

function renderTempo(eventos) {
  const lista = eventos.filter((e) => estado.aba === "tudo" || e.fonte === estado.aba);
  const ol = $("#tempo");
  if (!lista.length) {
    ol.innerHTML = `<li class="nada">Nada por aqui.</li>`;
    return;
  }
  ol.innerHTML = lista.map((e) => {
    const djen = e.fonte === "djen";
    const titulo = djen && e.documento && e.documento !== e.titulo ? `${e.titulo} — ${e.documento}` : e.titulo;
    const fonte = djen ? "Publicação · DJEN" : `Movimento · DataJud${e.grau ? " · " + e.grau : ""}`;
    return `
      <li class="evento ${e.fonte} ${e.novo ? "novo" : ""}">
        <div class="ev-cab">
          <span class="ev-data">${fmtDataHora(e.data)}</span>
          <span class="ev-fonte">${fonte}</span>
          ${e.novo ? `<span class="selo">NOVO</span>` : ""}
        </div>
        <div class="ev-titulo">${esc(titulo)}${!djen && e.complementos ? ` <span class="ev-det">— ${esc(e.complementos)}</span>` : ""}</div>
        ${e.orgao ? `<div class="ev-det">${esc(e.orgao)}</div>` : ""}
        ${djen && e.destinatarios?.length ? `<div class="ev-det">Destinatários: ${esc(e.destinatarios.join(", "))}</div>` : ""}
        ${djen && e.resumo ? `<div class="ev-resumo">${esc(e.resumo)}</div>` : ""}
        ${djen && e.texto ? `
          <div class="ev-texto" hidden>${esc(e.texto)}</div>
          <div class="ev-links">
            <button class="link" type="button" data-expandir>Ler publicação completa</button>
            ${e.link ? `<a href="${esc(e.link)}" target="_blank" rel="noopener">Ver documento no tribunal ↗</a>` : ""}
          </div>` : ""}
      </li>`;
  }).join("");
}

async function atualizarUm(numero) {
  const b = $("#pa-atualizar");
  b.disabled = true;
  b.textContent = "Consultando o DataJud…";
  try {
    const r = await api(`/api/processos/${numero}/atualizar`, { method: "POST" });
    toast(r.mensagem);
  } catch (e) {
    toast("Erro: " + e.message);
  }
  await carregarProcessos();
  if (estado.aberto === numero) abrirPainel(numero);
}

async function removerProcesso(p) {
  const aviso = p.origem === "manual" ? "" :
    "\n\nObs.: se houver nova publicação no DJEN com seu nome, ele volta a aparecer.";
  if (!confirm(`Remover o processo ${p.numero_fmt} da lista?${aviso}`)) return;
  await api(`/api/processos/${p.numero}`, { method: "DELETE" });
  fecharPainel();
  toast("Processo removido.");
  carregarProcessos();
}

// ---------- sincronização ----------
async function atualizarTudo() {
  try {
    await api("/api/sync", { method: "POST" });
  } catch (e) {
    toast("Erro ao iniciar: " + e.message);
    return;
  }
  acompanharSync();
}

// A atualização roda em passos curtos no servidor (cabe no limite de tempo da Vercel): a tela pede um passo
// atrás do outro até acabar. Fechar a tela só pausa; "Atualizar tudo" (ou abrir o app de novo) continua.
async function acompanharSync() {
  if (estado.sincronizando) return;
  estado.sincronizando = true;
  $("#progresso").hidden = false;
  $("#resultado-sync").hidden = true;
  const btn = $("#btn-atualizar");
  btn.disabled = true;
  btn.textContent = "Atualizando…";
  let s = null, falhas = 0, passos = 0;
  try {
    for (;;) {
      try {
        s = await api("/api/sync/passo", { method: "POST" });
        falhas = 0;
      } catch (e) {
        if (e.status === 401 || e.status === 403) break; // voltou para o login; o estado fica salvo para continuar depois
        if (++falhas >= 5) { toast(`A atualização parou (${e.message}). Clique em Atualizar tudo para continuar.`); break; }
        await esperar(3000 * falhas);
        continue;
      }
      const pct = s.total ? Math.round((100 * s.atual) / s.total) : 3;
      $("#prog-fase").textContent = s.fase || "Preparando…";
      const unidade = s.fase && s.fase.includes("DataJud") ? "processos" : "períodos";
      $("#prog-conta").textContent = s.total ? `${s.atual} de ${s.total} ${unidade}` : "";
      $("#prog-barra").style.width = `${Math.max(pct, 3)}%`;
      $("#prog-msg").textContent = s.ocupado ? "Continuando a atualização iniciada em outra janela…" : s.mensagem || "";
      if (!s.rodando) break;
      if (s.ocupado) await esperar(3000);
      if (++passos % 3 === 0) carregarProcessos(); // mostra processos novos enquanto atualiza
    }
  } finally {
    estado.sincronizando = false;
    $("#progresso").hidden = true;
    btn.disabled = false;
    btn.textContent = "⟳ Atualizar tudo";
    if (s && !s.rodando) mostrarResultado(s, true);
    carregarProcessos();
    carregarEstado();
    if (estado.aberto) abrirPainel(estado.aberto);
  }
}

function mostrarResultado(s, acabouDeRodar) {
  const erros = s.erros || [];
  if (!s.fim || (!acabouDeRodar && !erros.length && !estado.mostrouFim)) {
    $("#resultado-sync").hidden = true;
    return;
  }
  if (acabouDeRodar) estado.mostrouFim = true;
  $("#resultado-sync").hidden = false;
  $("#res-texto").textContent = `${fmtDataHora(s.fim)} — ${s.resumo || "concluída"}`;
  const det = $("#res-erros");
  det.hidden = !erros.length;
  if (!erros.length) return;
  $("#res-erros-titulo").textContent = `⚠ ${erros.length} ${erros.length === 1 ? "problema" : "problemas"} nesta atualização (clique para ver)`;
  const grupos = {};
  erros.forEach((e) => { (grupos[[e.fonte, e.tribunal].filter(Boolean).join(" · ")] ||= []).push(e.mensagem); });
  $("#res-erros-lista").innerHTML = Object.entries(grupos).map(([g, msgs]) =>
    `<div class="erro-grupo"><h4>${esc(g)}</h4><ul>${msgs.map((m) => `<li>${esc(m)}</li>`).join("")}</ul></div>`).join("");
}

// ---------- adicionar processos ----------
function abrirAdicionar() {
  $("#add-texto").value = "";
  $("#add-arquivo").value = "";
  $("#add-arquivo-nome").textContent = "";
  $("#add-resultado").hidden = true;
  // Escolha da advogada: cada uma e "ambas/todas"; começa em quem está no filtro (ou na primeira)
  const advs = estado.advogadas;
  $("#add-advogadas").hidden = advs.length < 2;
  const opcoes = advs.map((a) => [String(a.id), `${etiquetaAdv(a)} ${esc(a.nome)}`]);
  if (advs.length > 1) opcoes.push([advs.map((a) => a.id).join(","), advs.length === 2 ? "Ambas" : "Todas"]);
  const marcada = advs.some((a) => String(a.id) === estado.advogada) ? estado.advogada : opcoes[0]?.[0];
  $("#add-adv-opcoes").innerHTML = opcoes.map(([v, rotulo]) =>
    `<label class="chk"><input type="radio" name="add-adv" value="${v}" ${v === marcada ? "checked" : ""}> ${rotulo}</label>`).join("");
  $("#dlg-adicionar").showModal();
  $("#add-texto").focus();
}

async function lerArquivo(ev) {
  const arq = ev.target.files[0];
  if (!arq) return;
  const texto = await arq.text();
  const area = $("#add-texto");
  area.value = (area.value ? area.value + "\n" : "") + texto;
  $("#add-arquivo-nome").textContent = arq.name;
}

async function enviarAdicionar() {
  const texto = $("#add-texto").value;
  const btn = $("#add-enviar");
  if (!texto.trim()) { $("#add-texto").focus(); return; }
  btn.disabled = true;
  try {
    const escolha = document.querySelector('input[name="add-adv"]:checked');
    const advogadas = escolha ? escolha.value.split(",").map(Number) : [];
    const r = await api("/api/processos/adicionar", { method: "POST", body: JSON.stringify({ texto, advogadas }) });
    const nomes = advogadas.map(advogadaPorId).filter(Boolean).map(primeiroNome).join(" e ");
    const partes = [];
    if (!r.encontrados) partes.push(`<div class="ruim">Nenhum número de processo (formato CNJ) foi encontrado no texto.</div>`);
    if (r.novos.length) partes.push(`<div><strong>${r.novos.length}</strong> ${r.novos.length === 1 ? "processo adicionado" : "processos adicionados"}${nomes ? ` para ${esc(nomes)}` : ""}${r.consultando ? " — consultando o DataJud…" : ""}</div>`);
    if (r.existentes.length) partes.push(`<div>${r.existentes.length} já ${r.existentes.length === 1 ? "estava" : "estavam"} na lista${nomes ? ` (agora vinculado${r.existentes.length > 1 ? "s" : ""} também a ${esc(nomes)})` : ""}.</div>`);
    if (r.invalidos.length) partes.push(`<div class="ruim">Número(s) com dígito verificador inválido (confira se foram digitados certo):<ul>${r.invalidos.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`);
    $("#add-resultado").innerHTML = partes.join("");
    $("#add-resultado").hidden = false;
    if (r.novos.length || r.existentes.length) {
      $("#add-texto").value = "";
      carregarProcessos();
      if (r.consultando) acompanharSync();
    }
  } catch (e) {
    $("#add-resultado").innerHTML = `<div class="ruim">Erro: ${esc(e.message)}</div>`;
    $("#add-resultado").hidden = false;
  } finally {
    btn.disabled = false;
  }
}

// ---------- configurações ----------
async function abrirConfig() {
  const c = await api("/api/config");
  $("#cfg-ident").textContent = "";
  $("#cfg-advogadas").innerHTML = (c.advogadas || []).map((a) => `
    <div class="cfg-adv" data-oab="${esc(a.oab_numero)}" data-uf="${esc(a.oab_uf)}">
      <input type="color" class="cfg-adv-cor" value="${esc(a.cor)}" title="Cor da etiqueta" aria-label="Cor de ${esc(a.nome)}">
      <input type="text" class="campo cfg-adv-nome" value="${esc(a.nome)}" aria-label="Nome da advogada">
      <span class="ajuda">OAB ${esc(a.oab_numero)}/${esc(a.oab_uf)}</span>
    </div>`).join("");
  $("#cfg-chave").value = "";
  $("#cfg-chave-status").textContent = c.tem_chave
    ? `Chave configurada (termina em …${c.chave_final}). Cole uma nova só se quiser substituir.`
    : "Nenhuma chave configurada ainda.";
  $("#cfg-dias").value = c.backfill_dias;
  $("#cfg-coop-ocultar").checked = !!c.ocultar_cooperacao;
  $("#cfg-coop").innerHTML = "";
  (c.advogados_cooperacao || []).forEach(linhaCooperacao);
  await carregarPessoas();
  renderEquipe();
  $("#dlg-config").showModal();
}

// Uma linha da lista de advogados de cooperação (nome + OAB + UF)
function linhaCooperacao(a = {}) {
  $("#cfg-coop").insertAdjacentHTML("beforeend", `
    <div class="cfg-coop-linha">
      <input type="text" class="campo cfg-coop-nome" value="${esc(a.nome || "")}" placeholder="Nome" aria-label="Nome do advogado">
      <input type="text" class="campo cfg-coop-oab" value="${esc(a.oab_numero || "")}" placeholder="OAB" aria-label="Número da OAB">
      <input type="text" class="campo cfg-coop-uf" value="${esc(a.oab_uf || "")}" placeholder="UF" maxlength="2" aria-label="UF da OAB">
      <button type="button" class="ck-del" data-coop-remover title="Tirar da lista" aria-label="Tirar da lista">×</button>
    </div>`);
}

function renderEquipe() {
  const equipe = estado.pessoas.filter((p) => !p.advogada_id && p.ativo);
  $("#cfg-pessoas").innerHTML = equipe.map((p) => `
    <span class="cfg-pessoa">${esc(p.nome)}<button type="button" class="ck-del" data-remover-pessoa="${p.chave.slice(2)}"
      title="Tirar da lista" aria-label="Tirar ${esc(p.nome)} da lista">×</button></span>`).join("")
    || `<span class="ajuda">Ninguém além das advogadas.</span>`;
}

async function alterarEquipe(url, opcoes) {
  try {
    estado.pessoas = await api(url, opcoes);
    renderEquipe();
  } catch (e) {
    toast("Erro: " + e.message);
  }
}

async function salvarConfig() {
  const corpo = { backfill_dias: Number($("#cfg-dias").value) || 180 };
  const chave = $("#cfg-chave").value.trim();
  if (chave) corpo.datajud_api_key = chave;
  corpo.advogadas = [...document.querySelectorAll(".cfg-adv")].map((d) => ({
    oab_numero: d.dataset.oab, oab_uf: d.dataset.uf,
    nome: d.querySelector(".cfg-adv-nome").value.trim(), cor: d.querySelector(".cfg-adv-cor").value,
  }));
  corpo.ocultar_cooperacao = $("#cfg-coop-ocultar").checked;
  corpo.advogados_cooperacao = [...document.querySelectorAll(".cfg-coop-linha")].map((d) => ({
    nome: d.querySelector(".cfg-coop-nome").value.trim(), oab_numero: d.querySelector(".cfg-coop-oab").value.trim(),
    oab_uf: d.querySelector(".cfg-coop-uf").value.trim(),
  })).filter((a) => a.nome || a.oab_numero);
  try {
    await api("/api/config", { method: "POST", body: JSON.stringify(corpo) });
    $("#dlg-config").close();
    toast(chave ? "Chave salva. Clique em “Atualizar tudo” para buscar as movimentações." : "Configurações salvas.");
    carregarEstado();
    carregarProcessos();
    carregarAlertas();
  } catch (e) {
    toast("Erro ao salvar: " + e.message);
  }
}

// ---------- menu lateral ----------
// Computador: recolhe para só ícones (lembrado neste navegador). Tela estreita: vira gaveta, aberta pelo ☰.
const telaEstreita = () => matchMedia("(max-width: 900px)").matches;

function recolherMenu(recolher) {
  document.body.classList.toggle("sb-recolhida", recolher);
  $("#sb-recolher").setAttribute("aria-expanded", !recolher);
  $("#sb-recolher").title = recolher ? "Expandir menu" : "Recolher menu";
  $("#sb-recolher").setAttribute("aria-label", $("#sb-recolher").title);
  gravarPreferencia("menu-recolhido", recolher ? "1" : "");
}

function abrirMenuGaveta(abrir) {
  document.body.classList.toggle("sb-aberta", abrir);
  $("#sb-fundo").hidden = !abrir;
  $("#sb-abrir").setAttribute("aria-expanded", abrir);
  if (abrir) $("#sidebar .sb-item.ativa")?.focus();
}

function fecharMenuGaveta() {
  if (document.body.classList.contains("sb-aberta")) abrirMenuGaveta(false);
}

function ligarMenu() {
  recolherMenu(lerPreferencia("menu-recolhido") === "1");
  $("#sb-recolher").onclick = () => recolherMenu(!document.body.classList.contains("sb-recolhida"));
  $("#sb-abrir").onclick = () => abrirMenuGaveta(true);
  $("#sb-fundo").onclick = fecharMenuGaveta;
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && telaEstreita()) fecharMenuGaveta(); });
}

// ---------- eventos ----------
function ligarEventos() {
  ligarMenu();
  $("#btn-atualizar").onclick = atualizarTudo;
  $("#btn-adicionar").onclick = abrirAdicionar;
  $("#btn-config").onclick = () => { fecharMenuGaveta(); abrirConfig(); };
  document.querySelectorAll("[data-abrir-config]").forEach((b) => { b.onclick = abrirConfig; });
  $("#add-enviar").onclick = enviarAdicionar;
  $("#add-arquivo").onchange = lerArquivo;
  $("#cfg-salvar").onclick = salvarConfig;
  $("#cfg-coop-add").onclick = () => { linhaCooperacao(); $("#cfg-coop .cfg-coop-linha:last-child .cfg-coop-nome").focus(); };
  $("#cfg-coop").onclick = (ev) => { if (ev.target.closest("[data-coop-remover]")) ev.target.closest(".cfg-coop-linha").remove(); };
  $("#coop-aviso").onclick = (ev) => { const b = ev.target.closest("[data-coop]"); if (b) ocultarCooperacao(b.dataset.coop === "1"); };
  const addPessoa = () => {
    const nome = $("#cfg-pessoa-nova").value.trim();
    if (!nome) return;
    $("#cfg-pessoa-nova").value = "";
    alterarEquipe("/api/pessoas", { method: "POST", body: JSON.stringify({ nome }) });
  };
  $("#cfg-pessoa-add").onclick = addPessoa;
  $("#cfg-pessoa-nova").onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); addPessoa(); } };
  $("#cfg-pessoas").onclick = (ev) => {
    const b = ev.target.closest("[data-remover-pessoa]");
    if (b) alterarEquipe(`/api/pessoas/${b.dataset.removerPessoa}`, { method: "DELETE" });
  };
  $("#btn-vistos").onclick = async () => {
    await api("/api/visto-todos" + (estado.advogada ? `?advogada=${estado.advogada}` : ""), { method: "POST" });
    toast("Tudo marcado como visto.");
    carregarProcessos();
  };

  let espera;
  $("#f-q").oninput = () => { clearTimeout(espera); espera = setTimeout(carregarProcessos, 250); };
  ["#f-tribunal", "#f-novidades"].forEach((s) => { $(s).onchange = carregarProcessos; });
  $("#btn-limpar").onclick = () => {
    ["#f-q", "#f-tribunal"].forEach((s) => { $(s).value = ""; });
    $("#f-novidades").checked = false;
    escolherAdvogada("");
  };
  $("#f-advogada").onclick = (ev) => {
    const b = ev.target.closest("[data-adv]");
    if (b) escolherAdvogada(b.dataset.adv);
  };

  $("#linhas").onclick = (ev) => {
    const visto = ev.target.closest("[data-visto]");
    if (visto) { ev.stopPropagation(); marcarVisto(visto.dataset.visto); return; }
    const tr = ev.target.closest("tr[data-num]");
    if (tr) abrirPainel(tr.dataset.num);
  };
  $("#p-fechar").onclick = fecharPainel;
  $("#fundo").onclick = fecharPainel;
  $("#p-copiar").onclick = async (ev) => {
    try { await navigator.clipboard.writeText(ev.target.dataset.num); toast("Número copiado."); }
    catch (_) { toast(ev.target.dataset.num); }
  };
  $("#p-corpo").addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-expandir]");
    if (!b) return;
    const texto = b.closest(".evento").querySelector(".ev-texto");
    texto.hidden = !texto.hidden;
    b.textContent = texto.hidden ? "Ler publicação completa" : "Recolher publicação";
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && estado.aberto && !document.querySelector("dialog[open]")) fecharPainel();
  });
}

// Chamado por auth.js depois do login: carrega os dados e abre a tela lembrada
function iniciarApp() {
  carregarPessoas();
  carregarEstado().catch((e) => toast("Erro: " + e.message));
  carregarProcessos().catch((e) => toast("Erro: " + e.message));
  carregarAlertas();
  mostrarTela(location.hash.slice(1) || lerPreferencia("tela") || "processos");
}

// Duas pessoas usando ao mesmo tempo: ao voltar para esta aba (ou janela), recarrega a tela aberta para mostrar o que
// a outra fez. Não recarrega com um diálogo aberto ou com algo sendo digitado (a edição em andamento não se perde),
// durante o "Atualizar tudo" (que recarrega sozinho no fim), nem mais de uma vez a cada 15 s.
let ultimaVolta = 0;
function aoVoltar() {
  if (document.visibilityState !== "visible" || !sessao.entrou || estado.sincronizando) return;
  if (document.querySelector("dialog[open]") || document.activeElement?.matches("input, textarea, select")) return;
  if (Date.now() - ultimaVolta < 15e3) return;
  ultimaVolta = Date.now();
  if (estado.tela === "processos") carregarProcessos().catch(() => {});
  recarregarTela();
}

ligarEventos();
document.addEventListener("visibilitychange", aoVoltar);
window.addEventListener("focus", aoVoltar);
