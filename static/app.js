"use strict";

// ---------- utilidades ----------
const $ = (s) => document.querySelector(s);
const estado = {
  processos: [], filtros: { tribunais: [], orgaos: [] }, aberto: null, poll: null, aba: "tudo", mostrouFim: false,
  advogadas: [], contadores: {}, advogada: lerPreferencia("advogada"), // "" = todas
};

function lerPreferencia(chave) {
  try { return localStorage.getItem(chave) || ""; } catch (_) { return ""; }
}
function gravarPreferencia(chave, valor) {
  try { localStorage.setItem(chave, valor); } catch (_) { /* navegador sem armazenamento: só não lembra */ }
}

async function api(url, opcoes = {}) {
  const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opcoes });
  if (!r.ok) {
    let msg = `Erro ${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* resposta sem JSON */ }
    throw new Error(msg);
  }
  return r.json();
}

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
  $("#identidade").textContent = estado.advogadas.length
    ? estado.advogadas.map((a) => `${a.nome} · OAB ${a.oab_numero}/${a.oab_uf}`).join("   |   ")
    : [e.nome, e.oab && `OAB ${e.oab}`].filter(Boolean).join(" · ");
  $("#ultima").textContent = e.ultima_atualizacao ? `Última atualização: ${fmtDataHora(e.ultima_atualizacao)}` : "Ainda não atualizado";
  $("#aviso-chave").hidden = e.tem_chave;
  if (e.sync.rodando) acompanharSync();
  else mostrarResultado(e.sync, false);
}

// ---------- lista ----------
function filtrosAtuais() {
  return {
    q: $("#f-q").value.trim(), tribunal: $("#f-tribunal").value, orgao: $("#f-orgao").value,
    de: $("#f-de").value, ate: $("#f-ate").value, novidades: $("#f-novidades").checked ? "true" : "",
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
  const selT = $("#f-tribunal"), selO = $("#f-orgao");
  const t = selT.value, o = selO.value;
  selT.innerHTML = `<option value="">Todos os tribunais</option>` +
    estado.filtros.tribunais.map((x) => `<option ${x === t ? "selected" : ""}>${esc(x)}</option>`).join("");
  const orgaos = [...new Set(estado.filtros.orgaos.filter((x) => !t || x.tribunal === t).map((x) => x.orgao))];
  selO.innerHTML = `<option value="">Todas as varas / órgãos</option>` +
    orgaos.map((x) => `<option ${x === o ? "selected" : ""}>${esc(x)}</option>`).join("");
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
        <div class="num"><span class="n">${esc(p.numero_fmt)}</span>${p.novo ? `<span class="selo">NOVO</span>` : ""}${p.origem === "manual" ? `<span class="selo manual">manual</span>` : ""}</div>
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

  const vazio = $("#vazio");
  vazio.hidden = n > 0;
  if (!n) {
    const temFiltro = Object.values(filtrosAtuais()).some(Boolean);
    vazio.innerHTML = temFiltro
      ? "Nenhum processo com esses filtros."
      : "Nenhum processo ainda. Clique em <strong>Atualizar tudo</strong> para buscar suas publicações no DJEN, ou em <strong>Adicionar processos</strong>.";
  }
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
  ].filter(([, v]) => v);

  const eventos = p.eventos;
  const qtd = { tudo: eventos.length, djen: eventos.filter((e) => e.fonte === "djen").length };
  qtd.datajud = qtd.tudo - qtd.djen;

  $("#p-corpo").innerHTML = `
    <div class="painel-acoes">
      <button class="btn ${p.novo ? "primario" : ""}" type="button" id="pa-visto" ${p.novo ? "" : "disabled"}>${p.novo ? "✓ Marcar como visto" : "✓ Visto"}</button>
      <button class="btn" type="button" id="pa-atualizar">⟳ Atualizar este processo</button>
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
  $("#pa-remover").onclick = () => removerProcesso(p);
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

function acompanharSync() {
  if (estado.poll) return;
  $("#progresso").hidden = false;
  $("#resultado-sync").hidden = true;
  const btn = $("#btn-atualizar");
  btn.disabled = true;
  btn.textContent = "Atualizando…";
  let ciclos = 0;
  const passo = async () => {
    let s;
    try {
      s = await api("/api/sync");
    } catch (_) {
      return; // servidor ocupado: tenta de novo no próximo ciclo
    }
    const pct = s.total ? Math.round((100 * s.atual) / s.total) : 3;
    $("#prog-fase").textContent = s.fase || "Preparando…";
    const unidade = s.fase && s.fase.includes("DataJud") ? "processos" : "períodos";
    $("#prog-conta").textContent = s.total ? `${s.atual} de ${s.total} ${unidade}` : "";
    $("#prog-barra").style.width = `${Math.max(pct, 3)}%`;
    $("#prog-msg").textContent = s.mensagem || "";
    if (++ciclos % 5 === 0) carregarProcessos(); // mostra processos novos enquanto atualiza
    if (!s.rodando) {
      clearInterval(estado.poll);
      estado.poll = null;
      $("#progresso").hidden = true;
      btn.disabled = false;
      btn.textContent = "⟳ Atualizar tudo";
      mostrarResultado(s, true);
      carregarProcessos();
      carregarEstado();
      if (estado.aberto) abrirPainel(estado.aberto);
    }
  };
  estado.poll = setInterval(passo, 1000);
  passo();
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
  $("#dlg-config").showModal();
}

async function salvarConfig() {
  const corpo = { backfill_dias: Number($("#cfg-dias").value) || 180 };
  const chave = $("#cfg-chave").value.trim();
  if (chave) corpo.datajud_api_key = chave;
  corpo.advogadas = [...document.querySelectorAll(".cfg-adv")].map((d) => ({
    oab_numero: d.dataset.oab, oab_uf: d.dataset.uf,
    nome: d.querySelector(".cfg-adv-nome").value.trim(), cor: d.querySelector(".cfg-adv-cor").value,
  }));
  try {
    await api("/api/config", { method: "POST", body: JSON.stringify(corpo) });
    $("#dlg-config").close();
    toast(chave ? "Chave salva. Clique em “Atualizar tudo” para buscar as movimentações." : "Configurações salvas.");
    carregarEstado();
    carregarProcessos();
  } catch (e) {
    toast("Erro ao salvar: " + e.message);
  }
}

// ---------- eventos ----------
function ligarEventos() {
  $("#btn-atualizar").onclick = atualizarTudo;
  $("#btn-adicionar").onclick = abrirAdicionar;
  $("#btn-config").onclick = abrirConfig;
  document.querySelectorAll("[data-abrir-config]").forEach((b) => { b.onclick = abrirConfig; });
  $("#add-enviar").onclick = enviarAdicionar;
  $("#add-arquivo").onchange = lerArquivo;
  $("#cfg-salvar").onclick = salvarConfig;
  $("#btn-vistos").onclick = async () => {
    await api("/api/visto-todos" + (estado.advogada ? `?advogada=${estado.advogada}` : ""), { method: "POST" });
    toast("Tudo marcado como visto.");
    carregarProcessos();
  };

  let espera;
  $("#f-q").oninput = () => { clearTimeout(espera); espera = setTimeout(carregarProcessos, 250); };
  ["#f-tribunal", "#f-orgao", "#f-de", "#f-ate", "#f-novidades"].forEach((s) => { $(s).onchange = carregarProcessos; });
  $("#f-tribunal").addEventListener("change", () => { $("#f-orgao").value = ""; });
  $("#btn-limpar").onclick = () => {
    ["#f-q", "#f-tribunal", "#f-orgao", "#f-de", "#f-ate"].forEach((s) => { $(s).value = ""; });
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

ligarEventos();
carregarEstado().catch((e) => toast("Erro: " + e.message));
carregarProcessos().catch((e) => toast("Erro: " + e.message));
