"use strict";
// Editor de checklist reutilizável (tarefas da agenda e cards do quadro). Usa esc() e estado.pessoas (app.js).
// Item = { id, texto, feito, data, hora, resp }. Marca/desmarca, arrasta pela alça para reordenar (mouse, toque,
// ou ↑/↓ no teclado), edita o texto no lugar, exclui e adiciona. Data, horário e responsável ficam num detalhe que
// abre por item (clique no ícone ou nas etiquetas). Não salva sozinho: quem usa lê .valor() na hora de salvar.

const ICONE_ALCA = `<svg viewBox="0 0 10 16" width="10" height="16" aria-hidden="true"><g fill="currentColor">
  <circle cx="2.5" cy="3" r="1.4"/><circle cx="7.5" cy="3" r="1.4"/><circle cx="2.5" cy="8" r="1.4"/>
  <circle cx="7.5" cy="8" r="1.4"/><circle cx="2.5" cy="13" r="1.4"/><circle cx="7.5" cy="13" r="1.4"/></g></svg>`;
const ICONE_QUANDO = `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor"
  stroke-width="1.4" stroke-linecap="round"><rect x="2" y="3" width="12" height="11" rx="2"/><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3"/></svg>`;

const novoIdItem = () => Math.random().toString(36).slice(2, 10);
const diaMes = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : "");

// Item que veio do Monitoramento (ou de "+ Nova tarefa") guarda a ligação com a tarefa (origem_id) e o tipo dela
// (prazo, audiência, tarefa), só para mostrar: o servidor confere a ligação ao salvar
function itemLimpo(c) {
  const obj = typeof c === "object" && c ? c : {};
  const data = obj.data || null;
  return {
    id: obj.id || novoIdItem(), texto: String(typeof c === "object" ? obj.texto ?? "" : c),
    feito: !!obj.feito, data, hora: data && obj.hora ? obj.hora : null, resp: obj.resp || null,
    origem_id: obj.origem_id || null, tipo: obj.tipo || null, prazo_tipo: obj.prazo_tipo || null,
  };
}

const NOME_TIPO_ITEM = { prazo: "prazo", audiencia: "audiência", tarefa: "tarefa" };

// prazo: função que devolve a data (AAAA-MM-DD) do prazo fatal da demanda, para avisar etapas marcadas depois dele
function criarChecklist(raiz, { titulo = "Checklist", prazo = () => null } = {}) {
  let itens = [];
  let aberto = null; // id do item com o detalhe (data/hora/responsável) visível
  raiz.classList.add("ck");
  raiz.innerHTML = `
    <div class="ck-cab"><span class="ck-titulo">${esc(titulo)}</span><span class="ck-prog"></span><span class="ck-aviso"></span></div>
    <ul class="ck-lista"></ul>
    <input type="text" class="ck-novo" placeholder="+ Adicionar item" aria-label="Novo item da checklist" autocomplete="off">`;
  const ul = raiz.querySelector(".ck-lista"), novo = raiz.querySelector(".ck-novo");

  // etapa ainda aberta marcada para depois do prazo fatal (feita não importa mais; prazo e audiência têm data própria)
  const tarde = (c) => { const p = prazo(); return !!(!c.feito && !c.tipo && c.data && p && c.data > p); };

  function cabecalho() {
    const feitos = itens.filter((c) => c.feito).length;
    raiz.querySelector(".ck-prog").textContent = itens.length ? `${feitos}/${itens.length}` : "";
    const n = itens.filter(tarde).length;
    raiz.querySelector(".ck-aviso").textContent = n ? `${n} ${n > 1 ? "etapas" : "etapa"} depois do prazo fatal` : "";
  }

  function metaHTML(c) {
    const pessoa = pessoaPorChave(c.resp);
    const partes = [];
    if (c.tipo) {
      const marca = c.tipo === "prazo" && typeof marcaPrazo === "function" ? marcaPrazo(c.prazo_tipo) : "";
      partes.push(`<span class="ck-orig" title="Veio do Monitoramento (ou de “+ Nova tarefa”)">${marca}${NOME_TIPO_ITEM[c.tipo] || c.tipo}</span>`);
    }
    if (c.data) {
      const aviso = tarde(c) ? `Depois do prazo fatal (${diaMes(prazo())})` : "Data e responsável";
      partes.push(`<button type="button" class="ck-chip ${tarde(c) ? "tarde" : ""}" data-det title="${aviso}">${diaMes(c.data)}${c.hora ? " " + c.hora : ""}</button>`);
    }
    if (pessoa) partes.push(`<button type="button" class="ck-chip ck-quem" data-det title="Responsável: ${esc(pessoa.nome_completo)}">${esc(pessoa.nome)}</button>`);
    if (!c.data && !pessoa) partes.push(`<button type="button" class="ck-det" data-det title="Data e responsável" aria-label="Data e responsável">${ICONE_QUANDO}</button>`);
    return partes.join("");
  }

  function detalheHTML(c) {
    const opcoes = (estado.pessoas || []).filter((p) => p.ativo || p.chave === c.resp)
      .map((p) => `<option value="${p.chave}" ${p.chave === c.resp ? "selected" : ""}>${esc(p.nome_completo)}</option>`).join("");
    return `<div class="ck-detalhe">
      <label>Data <input type="date" class="campo ck-data" value="${c.data || ""}"></label>
      <label>Hora <input type="time" class="campo ck-hora" value="${c.hora || ""}" ${c.data ? "" : "disabled"}></label>
      <label>Responsável <select class="campo ck-resp"><option value="">ninguém</option>${opcoes}</select></label>
    </div>`;
  }

  function render(focar) {
    ul.innerHTML = itens.map((c, i) => `
      <li class="ck-item ${c.feito ? "feito" : ""} ${aberto === c.id ? "aberto" : ""}" data-i="${i}">
        <button type="button" class="ck-alca" title="Arrastar para reordenar" aria-label="Mover “${esc(c.texto)}” (setas para cima e para baixo)">${ICONE_ALCA}</button>
        <input type="checkbox" class="ck-feito" ${c.feito ? "checked" : ""} aria-label="Feito: ${esc(c.texto)}">
        <input type="text" class="ck-texto" value="${esc(c.texto)}" aria-label="Texto do item" autocomplete="off">
        <span class="ck-meta">${metaHTML(c)}</span>
        <button type="button" class="ck-del" title="Excluir item" aria-label="Excluir “${esc(c.texto)}”">×</button>
        ${aberto === c.id ? detalheHTML(c) : ""}
      </li>`).join("");
    cabecalho();
    if (focar) ul.querySelector(`[data-i="${focar[0]}"] ${focar[1]}`)?.focus();
  }

  const liDe = (el) => el.closest(".ck-item");
  const indice = (el) => Number(liDe(el).dataset.i);
  // atualiza só as etiquetas do item (não redesenha: não tira o foco de quem está digitando a data)
  const atualizarMeta = (li) => { li.querySelector(".ck-meta").innerHTML = metaHTML(itens[Number(li.dataset.i)]); cabecalho(); };

  ul.addEventListener("change", (ev) => {
    const el = ev.target, c = itens[indice(el)];
    if (el.classList.contains("ck-feito")) {
      c.feito = el.checked;
      liDe(el).classList.toggle("feito", el.checked);
      atualizarMeta(liDe(el));
    } else if (el.classList.contains("ck-texto")) {
      const texto = el.value.trim();
      if (texto) c.texto = texto;
      else { itens.splice(indice(el), 1); render(); } // apagar todo o texto = excluir o item
    } else if (el.classList.contains("ck-resp")) {
      c.resp = el.value || null;
      atualizarMeta(liDe(el));
    }
  });
  ul.addEventListener("input", (ev) => {
    const el = ev.target, li = liDe(el);
    if (!li) return;
    const c = itens[Number(li.dataset.i)];
    if (el.classList.contains("ck-texto")) c.texto = el.value;
    if (el.classList.contains("ck-data")) {
      c.data = el.value || null;
      if (!c.data) c.hora = null;
      const hora = li.querySelector(".ck-hora");
      hora.disabled = !c.data;
      if (!c.data) hora.value = "";
      atualizarMeta(li);
    }
    if (el.classList.contains("ck-hora")) { c.hora = (c.data && el.value) || null; atualizarMeta(li); }
  });
  ul.addEventListener("keydown", (ev) => {
    const el = ev.target;
    if (el.matches(".ck-texto, .ck-data, .ck-hora") && ev.key === "Enter") { ev.preventDefault(); el.blur(); }
    if (el.classList.contains("ck-alca") && (ev.key === "ArrowUp" || ev.key === "ArrowDown")) {
      ev.preventDefault();
      const i = indice(el), j = i + (ev.key === "ArrowUp" ? -1 : 1);
      if (j < 0 || j >= itens.length) return;
      [itens[i], itens[j]] = [itens[j], itens[i]];
      render([j, ".ck-alca"]);
    }
  });
  ul.addEventListener("click", (ev) => {
    const det = ev.target.closest("[data-det]");
    if (det) {
      const c = itens[indice(det)];
      aberto = aberto === c.id ? null : c.id;
      render(aberto ? [indice(det), ".ck-data"] : null);
      return;
    }
    const del = ev.target.closest(".ck-del");
    if (!del) return;
    const i = indice(del);
    itens.splice(i, 1);
    render(itens.length ? [Math.min(i, itens.length - 1), ".ck-del"] : null);
  });

  // adicionar: Enter no campo de baixo (o que ficar digitado sem Enter também entra ao salvar)
  novo.addEventListener("keydown", (ev) => {
    if (ev.key !== "Enter") return;
    ev.preventDefault();
    const texto = novo.value.trim();
    if (!texto) return;
    itens.push(itemLimpo(texto));
    novo.value = "";
    render();
  });

  // arrastar pela alça: pointer events (funciona com mouse e com o dedo); rola o diálogo perto das bordas
  ul.addEventListener("pointerdown", (ev) => {
    const alca = ev.target.closest(".ck-alca");
    if (!alca || ev.button > 0) return;
    ev.preventDefault();
    if (ul.contains(document.activeElement)) document.activeElement.blur(); // grava edição pendente
    const li = liDe(alca);
    const caixa = areaRolavel(ul);
    let y = ev.clientY, quadro;
    li.classList.add("arrastando");
    ul.classList.add("ordenando");
    // ouve no document (não com setPointerCapture): mover o <li> no DOM soltaria a captura no meio do arraste
    const reposicionar = () => {
      const alvo = [...ul.children].find((x) => x !== li && y < x.getBoundingClientRect().top + x.offsetHeight / 2);
      if (alvo) { if (li.nextElementSibling !== alvo) ul.insertBefore(li, alvo); }
      else if (ul.lastElementChild !== li) ul.appendChild(li);
    };
    const rolar = () => {
      const r = caixa === document.scrollingElement ? { top: 0, bottom: innerHeight } : caixa.getBoundingClientRect();
      const v = y < r.top + 48 ? -10 : y > r.bottom - 48 ? 10 : 0;
      if (v) { caixa.scrollTop += v; reposicionar(); }
      quadro = requestAnimationFrame(rolar);
    };
    const mover = (e) => {
      if (e.pointerId !== ev.pointerId) return;
      e.preventDefault();
      y = e.clientY;
      reposicionar();
    };
    const soltar = (e) => {
      if (e.pointerId !== ev.pointerId) return;
      cancelAnimationFrame(quadro);
      document.removeEventListener("pointermove", mover);
      document.removeEventListener("pointerup", soltar);
      document.removeEventListener("pointercancel", soltar);
      ul.classList.remove("ordenando");
      const ordem = [...ul.children].map((x) => Number(x.dataset.i));
      itens = ordem.map((i) => itens[i]);
      render([ordem.indexOf(Number(li.dataset.i)), ".ck-alca"]);
    };
    document.addEventListener("pointermove", mover);
    document.addEventListener("pointerup", soltar);
    document.addEventListener("pointercancel", soltar);
    quadro = requestAnimationFrame(rolar);
  });

  return {
    definir(lista) {
      itens = (lista || []).map(itemLimpo);
      aberto = null;
      novo.value = "";
      render();
    },
    // acrescenta itens no fim (ex.: a checklist padrão num card que foi criado sozinho, vazio)
    adicionar(lista) {
      itens.push(...(lista || []).map(itemLimpo));
      render();
    },
    valor() {
      const pendente = novo.value.trim();
      return [...itens, ...(pendente ? [itemLimpo(pendente)] : [])]
        .map((c) => ({ ...c, texto: c.texto.trim() })).filter((c) => c.texto);
    },
    // o prazo fatal (ou a lista de pessoas) mudou: refaz avisos e etiquetas sem perder o que foi digitado
    atualizar() { ul.querySelectorAll(".ck-item").forEach(atualizarMeta); cabecalho(); },
    // ainda é exatamente o modelo padrão (mesmos textos, nada marcado, sem data nem responsável)? Então dá para
    // trocar de modelo sem perder nada
    igualA(textos) {
      const v = this.valor();
      return JSON.stringify(v.map((c) => c.texto)) === JSON.stringify(textos || []) && !v.some((c) => c.feito || c.data || c.resp);
    },
  };
}

// Progresso discreto para o card ("3/17"); vazio se não houver checklist
function progressoChecklist(lista) {
  if (!lista || !lista.length) return "";
  return `<span class="c-prog" title="Checklist">${lista.filter((c) => c.feito).length}/${lista.length}</span>`;
}

function proximoItem(lista) {
  return (lista || []).find((c) => !c.feito) || null;
}

// Etapas ainda abertas marcadas para depois do prazo fatal (aviso discreto, não bloqueia)
function etapasDepoisDoPrazo(lista, prazoData) {
  return prazoData ? (lista || []).filter((c) => !c.feito && !c.tipo && c.data && c.data > prazoData).length : 0;
}

function areaRolavel(el) {
  for (let p = el.parentElement; p; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY;
    if ((o === "auto" || o === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return document.scrollingElement;
}
