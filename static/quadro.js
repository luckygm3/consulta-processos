"use strict";
// Quadro de clientes (kanban estilo Trello). Usa app.js (api, esc, toast, memoriaCards, abrirPainel…),
// checklist.js (criarChecklist, progressoChecklist) e agenda.js (TELAS).

const NOME_QUADRO = "CLIENTES"; // nome da aba na tela: para renomear, troque só aqui

const qd = {
  colunas: [], cards: [], tipos: {}, tipo: "processo", editando: null, coluna: null, arrastando: null, ck: null,
  memoria: memoriaCards("cards-quadro"), modelos: {}, prazoProc: null,
};
const MODELO_DO_TIPO = { processo: "processo", inicial: "processo", preventivo: "preventivo" }; // petição inicial usa a de processo

async function carregarQuadro() {
  let d;
  try {
    d = await api("/api/quadro");
    if (!estado.pessoas.length) await carregarPessoas();
  } catch (e) {
    // "Not Found" = servidor ainda com o código antigo (a tela nova é lida da pasta, o servidor só ao reiniciar)
    $("#qd-expandir").hidden = true;
    $("#qd-kanban").innerHTML = `<p class="vazio">Não foi possível abrir o quadro (${esc(e.message)}).<br>
      Se o app acabou de ser atualizado, feche a janela do app e abra de novo.</p>`;
    return;
  }
  Object.assign(qd, { colunas: d.colunas, cards: d.cards, tipos: d.tipos });
  renderQuadro();
}

// ---------- quadro ----------
function renderQuadro() {
  $("#qd-expandir").hidden = !qd.cards.length;
  $("#qd-kanban").innerHTML = qd.colunas.map((col) => {
    const cards = qd.cards.filter((c) => c.coluna_id === col.id);
    return `
      <section class="coluna" data-col="${col.id}">
        <header class="col-cab">
          <h3><button type="button" class="qd-nome ${col.nome ? "" : "vazio"}" data-renomear title="Clique para ${col.nome ? "renomear" : "dar um nome"}">${col.nome ? esc(col.nome) : "Nomear coluna"}</button>
            ${cards.length ? `<span class="qtd">${cards.length}</span>` : ""}</h3>
        </header>
        <div class="col-cartoes">${cards.map(cardHTML).join("")}</div>
        <button type="button" class="qd-add" data-novo>+ Adicionar cliente</button>
      </section>`;
  }).join("");
}

// Linha do prazo fatal no card: pontinho (processual cheio / interno vazado), o quê e quando; cor só se apertado
function prazoLinhaHTML(p) {
  if (!p) return "";
  const urg = ["vencido", "hoje", "amanha"].includes(p.urgencia) ? `u-${p.urgencia}` : "";
  return `<div class="c-prazo ${urg}">${marcaPrazo(p.tipo)}${esc(p.descricao)} · <b>${dataBr(p.data)}</b>${p.hora ? " " + esc(p.hora) : ""}${p.sugerido ? " <span class=\"it-pai\">(sugerido)</span>" : ""}</div>`;
}

// Contraído: só nome + progresso. Expandido: processo (ou tipo), partes, prazo fatal e o próximo item da checklist.
function cardHTML(c) {
  const proximo = proximoItem(c.checklist);
  const tarde = c.prazo ? etapasDepoisDoPrazo(c.checklist, c.prazo.data) : 0;
  const vinculo = c.tipo !== "processo" ? `<div class="c-tipo">${esc(qd.tipos[c.tipo] || c.tipo)}</div>`
    : c.cadastrado ? `<button class="link c-proc" type="button" data-proc="${c.numero}">${esc(c.numero_fmt)}</button>`
      : `<div class="c-proc">${esc(c.numero_fmt)}</div>`;
  return `
    <article class="cartao qd-card ${qd.memoria.contraido(c.id) ? "contraido" : ""}" draggable="true" data-id="${c.id}">
      <div class="c-cab"><span class="c-titulo">${esc(c.titulo)}${c.inadimplente ? ` <span class="selo selo-inad" title="Marcado como inadimplente no Financeiro">inadimplente</span>` : ""}</span>${progressoChecklist(c.checklist)}</div>
      ${vinculo}
      ${c.tipo === "processo" && c.partes ? `<div class="c-partes">${esc(c.partes)}</div>` : ""}
      ${prazoLinhaHTML(c.prazo)}
      ${proximo ? `<div class="c-proximo"><span>Próximo:</span> ${esc(proximo.texto)}${proximo.data ? ` <span>· ${dataBr(proximo.data, false)}</span>` : ""}</div>` : ""}
      ${anivLinhaHTML(c.aniversario)}
      ${tarde ? `<div class="c-tarde">${tarde} ${tarde > 1 ? "etapas" : "etapa"} depois do prazo fatal</div>` : ""}
      <div class="c-rodape"><button class="c-editar" type="button" data-editar>Editar</button></div>
    </article>`;
}

const cardPorId = (id) => qd.cards.find((c) => c.id === Number(id));

// Aniversário no card: dd/mm discreto; destaque leve quando é hoje ou nos próximos 7 dias
function diasAteAniversario(iso, hoje = new Date()) {
  const h = new Date(hoje.getFullYear(), hoje.getMonth(), hoje.getDate());
  const [, m, d] = iso.split("-").map(Number);
  const dia = (ano) => {
    const bissexto = (ano % 4 === 0 && ano % 100 !== 0) || ano % 400 === 0;
    return new Date(ano, m - 1, m === 2 && d === 29 && !bissexto ? 28 : d);
  };
  let prox = dia(h.getFullYear());
  if (prox < h) prox = dia(h.getFullYear() + 1);
  return Math.round((prox - h) / 864e5);
}

function anivLinhaHTML(iso) {
  if (!iso) return "";
  const n = diasAteAniversario(iso);
  const quando = n === 0 ? " · <b>hoje!</b>" : n === 1 ? " · amanhã" : n <= 7 ? ` · em ${n} dias` : "";
  return `<div class="c-aniv ${n <= 7 ? "perto" : ""}" title="Aniversário">🎂 ${iso.slice(8, 10)}/${iso.slice(5, 7)}${quando}</div>`;
}

// ---------- nome das colunas (clica e escreve; Enter salva, Esc desiste) ----------
function renomearColuna(botao) {
  const col = qd.colunas.find((c) => c.id === Number(botao.closest(".coluna").dataset.col));
  const campo = document.createElement("input");
  Object.assign(campo, { className: "campo qd-nome-campo", value: col.nome, placeholder: "Nome da coluna", maxLength: 60 });
  campo.setAttribute("aria-label", "Nome da coluna");
  botao.replaceWith(campo);
  campo.focus();
  campo.select();
  let feito = false;
  const fim = async (salvar) => {
    if (feito) return;
    feito = true;
    const nome = campo.value.trim();
    if (salvar && nome !== col.nome) {
      try {
        await api(`/api/quadro/colunas/${col.id}`, { method: "PUT", body: JSON.stringify({ nome }) });
        col.nome = nome;
      } catch (e) {
        toast("Erro: " + e.message);
      }
    }
    renderQuadro();
  };
  campo.onkeydown = (ev) => {
    if (ev.key === "Enter") { ev.preventDefault(); fim(true); }
    if (ev.key === "Escape") { ev.preventDefault(); fim(false); }
  };
  campo.onblur = () => fim(true);
}

// ---------- arrastar: entre colunas e dentro da coluna (uma linha azul mostra onde vai cair) ----------
function ligarArrasteQuadro() {
  const kanban = $("#qd-kanban");
  const marca = document.createElement("div");
  marca.className = "qd-marca";
  const listaSob = (ev) => ev.target.closest(".coluna")?.querySelector(".col-cartoes");

  kanban.addEventListener("dragstart", (ev) => {
    const c = ev.target.closest(".qd-card");
    if (!c) return;
    qd.arrastando = Number(c.dataset.id);
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", c.dataset.id);
    requestAnimationFrame(() => c.classList.add("arrastando")); // depois da "foto" do arraste
  });
  kanban.addEventListener("dragover", (ev) => {
    const lista = listaSob(ev);
    if (!lista || qd.arrastando == null) return;
    ev.preventDefault();
    const antes = [...lista.querySelectorAll(".qd-card:not(.arrastando)")]
      .find((c) => ev.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2);
    if (antes) { if (marca.nextElementSibling !== antes) lista.insertBefore(marca, antes); }
    else if (lista.lastElementChild !== marca) lista.appendChild(marca);
  });
  kanban.addEventListener("drop", (ev) => {
    const lista = listaSob(ev);
    if (!lista || qd.arrastando == null) return;
    ev.preventDefault();
    const id = qd.arrastando;
    const ids = [...lista.children]
      .filter((e) => e === marca || (e.classList.contains("qd-card") && Number(e.dataset.id) !== id))
      .map((e) => (e === marca ? id : Number(e.dataset.id)));
    if (!ids.includes(id)) ids.push(id);
    marca.remove();
    moverCard(id, Number(lista.closest(".coluna").dataset.col), ids);
  });
  kanban.addEventListener("dragend", (ev) => {
    marca.remove();
    ev.target.closest(".qd-card")?.classList.remove("arrastando");
    qd.arrastando = null;
  });
}

async function moverCard(id, coluna, ids) {
  ids.forEach((cid, i) => Object.assign(cardPorId(cid) || {}, { coluna_id: coluna, posicao: i + 1 }));
  qd.cards.sort((a, b) => a.coluna_id - b.coluna_id || a.posicao - b.posicao);
  renderQuadro();
  try {
    await api("/api/quadro/ordem", { method: "POST", body: JSON.stringify({ coluna_id: coluna, ids }) });
  } catch (e) {
    toast("Erro: " + e.message);
    carregarQuadro();
  }
}

// ---------- card: criar / editar ----------
// O tipo decide o prazo fatal (com processo: o processual, vindo da agenda; sem processo: um interno, digitado)
// e, num card novo, qual checklist padrão ele recebe (troca sozinho enquanto ela não mexer na lista)
function escolherTipo(tipo) {
  const antes = qd.tipo;
  qd.tipo = tipo;
  document.querySelectorAll("#qc-tipo [data-tipo]").forEach((b) => {
    b.classList.toggle("ativa", b.dataset.tipo === tipo);
    b.setAttribute("aria-pressed", b.dataset.tipo === tipo);
  });
  $("#qc-proc-caixa").hidden = tipo !== "processo";
  $("#qc-prazo-proc").hidden = tipo !== "processo";
  $("#qc-prazo-int").hidden = tipo === "processo";
  const novoModelo = MODELO_DO_TIPO[tipo], velho = MODELO_DO_TIPO[antes];
  if (!qd.editando && novoModelo !== velho && qd.ck.igualA(qd.modelos[velho] || [])) qd.ck.definir(qd.modelos[novoModelo]);
  if (tipo === "processo") buscarPrazoProcessual();
  else qd.ck.atualizar();
}

// prazo fatal da demanda para o aviso "etapa depois do prazo"
function prazoDoCard() {
  return qd.tipo === "processo" ? qd.prazoProc?.data || null : $("#qc-prazo-data").value || null;
}

// mostra no diálogo o prazo processual que o card terá (o próximo prazo deste processo na agenda)
let esperaPrazo;
function buscarPrazoProcessual() {
  clearTimeout(esperaPrazo);
  esperaPrazo = setTimeout(async () => {
    const numero = $("#qc-numero").value.replace(/\D/g, "");
    qd.prazoProc = null;
    if (numero.length === 20) qd.prazoProc = await api(`/api/quadro/prazo-processo?numero=${numero}`).catch(() => null);
    if (qd.prazoProc && !qd.prazoProc.data) qd.prazoProc = null;
    const p = qd.prazoProc;
    $("#qc-prazo-proc").innerHTML = p
      ? `${marcaPrazo("processual")}${esc(p.descricao)} · <b>${dataBr(p.data)}</b>${p.hora ? " " + esc(p.hora) : ""}${p.sugerido ? " (sugerido, ainda não confirmado)" : ""}
         <span class="ajuda">vem da Agenda (prazo em aberto deste processo)</span>`
      : `<span class="ajuda">${numero.length === 20 ? "Nenhum prazo deste processo na Agenda. Use “Verificar prazos” ou crie o prazo na Agenda." : "Escolha o processo para ver o prazo dele."}</span>`;
    qd.ck.atualizar();
  }, 200);
}

async function abrirCard(c, coluna) {
  if (!c) qd.modelos = await api("/api/checklist-padrao").catch(() => ({})); // lido na hora (checklists_padrao.txt)
  if (!estado.pessoas.length) await carregarPessoas();
  qd.editando = c || null;
  qd.coluna = coluna ?? c?.coluna_id;
  qd.tipo = c?.tipo || "processo";
  $("#qc-titulo-dlg").textContent = c ? "Cliente" : "Novo cliente";
  $("#qc-titulo").value = c?.titulo || "";
  $("#qc-aniv").value = c?.aniversario || "";
  $("#qc-numero").value = c?.numero_fmt || "";
  $("#qc-prazo-desc").value = c?.prazo_descricao || "";
  $("#qc-prazo-data").value = c?.prazo_data || "";
  $("#qc-prazo-hora").value = c?.prazo_hora || "";
  qd.ck.definir(c ? c.checklist : qd.modelos[MODELO_DO_TIPO[qd.tipo]]);
  escolherTipo(qd.tipo);
  $("#qc-erro").hidden = true;
  $("#qc-excluir").hidden = !c;
  $("#dlg-card").showModal();
  if (!c) $("#qc-titulo").focus();
  // processos já cadastrados (todos, sem os filtros da aba Processos) para escolher pelo número ou pela parte
  try {
    const d = await api("/api/processos?incluir_cooperacao=true");
    $("#qc-processos").innerHTML = d.processos.map((p) => `<option value="${esc(p.numero_fmt)}">${esc(partesTexto(p))}</option>`).join("");
  } catch (_) { /* sem a lista, ainda dá para digitar o número */ }
}

async function salvarCard() {
  const d = {
    titulo: $("#qc-titulo").value.trim(), tipo: qd.tipo, checklist: qd.ck.valor(),
    numero: qd.tipo === "processo" ? $("#qc-numero").value : null,
    prazo_descricao: $("#qc-prazo-desc").value.trim(), prazo_data: $("#qc-prazo-data").value, prazo_hora: $("#qc-prazo-hora").value,
    aniversario: $("#qc-aniv").value || null,
  };
  if (!d.titulo) { $("#qc-titulo").focus(); return; }
  try {
    if (qd.editando) await api(`/api/quadro/cards/${qd.editando.id}`, { method: "PATCH", body: JSON.stringify(d) });
    else await api("/api/quadro/cards", { method: "POST", body: JSON.stringify({ ...d, coluna_id: qd.coluna }) });
    $("#dlg-card").close();
    recarregarTela(); // CLIENTES, ou a tela de onde o card foi aberto (Monitoramento, Agenda)
  } catch (e) {
    $("#qc-erro").textContent = e.message;
    $("#qc-erro").hidden = false;
  }
}

async function excluirCard() {
  const c = qd.editando;
  if (!c || !confirm(`Excluir o card “${c.titulo}”?\nNão dá para desfazer.`)) return;
  await api(`/api/quadro/cards/${c.id}`, { method: "DELETE" });
  $("#dlg-card").close();
  toast("Card excluído.");
  recarregarTela();
}

// Abre um card a partir da agenda (item da checklist ou prazo fatal do card). Sempre relê o quadro: um item pode ter
// sido marcado na agenda depois da última leitura, e salvar o card com a cópia antiga desfaria isso.
async function abrirCardPorId(id) {
  try {
    const d = await api("/api/quadro");
    Object.assign(qd, { colunas: d.colunas, cards: d.cards, tipos: d.tipos });
  } catch (e) {
    toast("Erro: " + e.message);
    return;
  }
  const c = cardPorId(id);
  if (c) abrirCard(c);
  else toast("Card não encontrado (foi excluído?).");
}

// ---------- eventos ----------
function ligarQuadro() {
  // menu lateral e topo
  const nome = NOME_QUADRO;
  $("#sb-rotulo-quadro").textContent = nome;
  document.querySelector('.sb-item[data-tela="quadro"]').title = nome;
  CABECALHOS.quadro[0] = nome;
  TELAS.quadro = () => carregarQuadro();
  qd.ck = criarChecklist($("#qc-checklist"), { prazo: prazoDoCard });
  $("#qc-numero").addEventListener("input", buscarPrazoProcessual);
  $("#qc-prazo-data").addEventListener("input", () => qd.ck.atualizar());
  ligarExpandir($("#qd-expandir"), qd.memoria, "#qd-kanban .qd-card");
  ligarArrasteQuadro();

  const tela = $("#tela-quadro");
  tela.addEventListener("click", (ev) => {
    const proc = ev.target.closest("[data-proc]");
    if (proc) { abrirPainel(proc.dataset.proc); return; }
    const nome = ev.target.closest("[data-renomear]");
    if (nome) { renomearColuna(nome); return; }
    const novo = ev.target.closest("[data-novo]");
    if (novo) { abrirCard(null, Number(novo.closest(".coluna").dataset.col)); return; }
    const card = ev.target.closest(".qd-card");
    if (!card) return;
    if (ev.target.closest("[data-editar]")) abrirCard(cardPorId(card.dataset.id));
    else if (!ev.target.closest("a, button, input")) alternarCard(card, qd.memoria);
  });
  tela.addEventListener("dblclick", (ev) => {
    const card = ev.target.closest(".qd-card");
    if (card && !ev.target.closest("a, button, input")) abrirCard(cardPorId(card.dataset.id));
  });

  $("#qc-tipo").onclick = (ev) => { const b = ev.target.closest("[data-tipo]"); if (b) escolherTipo(b.dataset.tipo); };
  $("#qc-titulo").onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); salvarCard(); } };
  $("#qc-numero").onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); salvarCard(); } };
  $("#qc-salvar").onclick = salvarCard;
  $("#qc-excluir").onclick = () => excluirCard().catch((e) => toast("Erro: " + e.message));
}

ligarQuadro();
