"use strict";
// Login pelo Supabase Auth (e-mail e senha). A tela só conhece a URL do projeto e a chave pública "anon" (vêm de
// /api/publico); a sessão fica guardada pelo supabase-js e o token vai em cada chamada à API (ver api() em app.js).
// Fluxos: entrar, sair, "esqueci a senha" (e-mail com link) e definir nova senha ao voltar pelo link.

const sessao = { cliente: null, entrou: false, recusado: null }; // recusado: último token que a API não aceitou

async function tokenAtual() {
  if (!sessao.cliente) return null;
  const { data } = await sessao.cliente.auth.getSession(); // renova sozinho se estiver perto de expirar
  return data.session ? data.session.access_token : null;
}

function mostrarLogin(modo = "entrar", mensagem = "", ruim = false) {
  document.body.classList.add("deslogada");
  $("#login").hidden = false;
  $("#login-entrar").hidden = modo !== "entrar";
  $("#login-nova-senha").hidden = modo !== "nova-senha";
  $("#login-sem-acesso").hidden = modo !== "sem-acesso";
  const msg = $("#login-msg");
  msg.textContent = mensagem;
  msg.hidden = !mensagem;
  msg.classList.toggle("ruim", ruim);
  const foco = { entrar: "#login-email", "nova-senha": "#login-senha-nova" }[modo];
  if (foco) setTimeout(() => $(foco).focus(), 50);
}

function esconderLogin() {
  document.body.classList.remove("deslogada");
  $("#login").hidden = true;
}

// A API recusou o token (401) ou a conta não é de uma das advogadas (403). O supabase-js reenvia a sessão guardada
// (SIGNED_IN) quando a aba volta a ficar visível: com o token anotado em sessao.recusado, ela não reabre o app.
function sessaoRecusada(status, mensagem, token) {
  if (token) sessao.recusado = token;
  sessao.entrou = false; // o próximo login carrega tudo de novo
  if (status === 403) {
    $("#login-sem-acesso-txt").textContent = mensagem;
    mostrarLogin("sem-acesso");
    return;
  }
  mostrarLogin("entrar", mensagem || "Sessão expirada. Entre de novo.", true);
  sessao.cliente.auth.signOut({ scope: "local" }).catch(() => {}); // esquece a sessão que o servidor não aceita mais
}

async function entrarNoApp(s) {
  if (s.access_token === sessao.recusado) return; // a mesma sessão que a API já recusou
  esconderLogin();
  $("#sb-usuaria").textContent = s.user.email || "";
  $("#btn-sair").title = `Sair (${s.user.email || ""})`;
  if (!sessao.entrou) {
    sessao.entrou = true;
    iniciarApp();
  }
}

async function enviarLogin(ev) {
  ev.preventDefault();
  const botao = $("#login-botao");
  botao.disabled = true;
  botao.textContent = "Entrando…";
  const { error } = await sessao.cliente.auth.signInWithPassword({
    email: $("#login-email").value.trim(), password: $("#login-senha").value,
  });
  botao.disabled = false;
  botao.textContent = "Entrar";
  if (error) {
    const msg = /invalid login/i.test(error.message) ? "E-mail ou senha incorretos." :
      /not confirmed/i.test(error.message) ? "Confirme o e-mail antes de entrar (veja a caixa de entrada)." : error.message;
    mostrarLogin("entrar", msg, true);
  }
  // sucesso: o evento SIGNED_IN (onAuthStateChange) abre o app
}

async function esqueciSenha() {
  const email = $("#login-email").value.trim();
  if (!email) { mostrarLogin("entrar", "Escreva seu e-mail acima e clique de novo em “Esqueci minha senha”.", true); return; }
  const { error } = await sessao.cliente.auth.resetPasswordForEmail(email, { redirectTo: location.origin + location.pathname });
  mostrarLogin("entrar", error ? error.message : `Se ${email} tiver acesso, chega um e-mail com o link para criar uma senha nova.`, !!error);
}

async function salvarNovaSenha(ev) {
  ev.preventDefault();
  const senha = $("#login-senha-nova").value;
  if (senha.length < 8) { mostrarLogin("nova-senha", "Use pelo menos 8 caracteres.", true); return; }
  const { error } = await sessao.cliente.auth.updateUser({ password: senha });
  if (error) { mostrarLogin("nova-senha", error.message, true); return; }
  toast("Senha nova salva.");
  const { data: s } = await sessao.cliente.auth.getSession();
  if (s.session) entrarNoApp(s.session); else mostrarLogin("entrar", "Senha nova salva. Entre com ela.");
}

async function sair() {
  sessao.entrou = false;
  await sessao.cliente.auth.signOut();
  location.hash = "";
  location.reload(); // limpa tudo o que estava carregado na tela
}

async function iniciarAuth() {
  let cfg;
  try {
    const r = await fetch("/api/publico");
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `Erro ${r.status}`);
    cfg = await r.json();
  } catch (e) {
    mostrarLogin("entrar", `O servidor não respondeu (${e.message}). Confira se o app está rodando e se o .env tem as chaves do Supabase.`, true);
    return;
  }
  if (!window.supabase) {
    mostrarLogin("entrar", "Não foi possível carregar o login (sem internet?). Recarregue a página.", true);
    return;
  }
  sessao.cliente = window.supabase.createClient(cfg.supabase_url, cfg.supabase_anon_key, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
  sessao.cliente.auth.onAuthStateChange((evento, s) => {
    if (evento === "PASSWORD_RECOVERY") { mostrarLogin("nova-senha"); return; }
    if (evento === "SIGNED_OUT" || !s) { // sem sessão, ou ela acabou (ex.: não deu para renovar)
      if (sessao.entrou) mostrarLogin("entrar", "Sessão expirada. Entre de novo.", true);
      else if (!sessao.recusado) mostrarLogin("entrar"); // após uma recusa, a tela de login já está com o aviso
      sessao.entrou = false;
      return;
    }
    if (["INITIAL_SESSION", "SIGNED_IN"].includes(evento) && !$("#login-nova-senha").hidden) return; // trocando a senha
    if (["INITIAL_SESSION", "SIGNED_IN"].includes(evento)) setTimeout(() => entrarNoApp(s), 0); // fora do callback
  });
}

function ligarAuth() {
  $("#login-entrar").addEventListener("submit", enviarLogin);
  $("#login-nova-senha").addEventListener("submit", salvarNovaSenha);
  $("#login-esqueci").onclick = esqueciSenha;
  $("#login-sair").onclick = sair;
  $("#btn-sair").onclick = sair;
  iniciarAuth();
}

ligarAuth();
