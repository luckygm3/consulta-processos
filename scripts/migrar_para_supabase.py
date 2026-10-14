"""Copia os dados do banco antigo (db/processos.sqlite3) para o Postgres do Supabase, sem perder nada.

Antes: rode supabase/schema.sql no SQL Editor do Supabase (cria as tabelas, vazias).

Uso (na pasta do projeto):
    .venv\\Scripts\\python scripts\\migrar_para_supabase.py --email 130678/PR=beatriz@exemplo.com --email 130152/PR=kazuza@exemplo.com
    (acrescente --simular para fazer tudo e desfazer no fim: só confere)

Banco de outro computador (feche o app antigo lá e traga a pasta db inteira + o config.json):
    ... --sqlite C:\\dados-dela\\db\\processos.sqlite3 --config C:\\dados-dela\\config.json --email ... --email ...
Se o Supabase já tiver dados (ex.: de uma migração de teste), --substituir apaga tudo e copia este banco no lugar,
na mesma transação: se algo falhar ou não conferir, o Supabase fica como estava. Rode antes com --simular.

Conexão: variável MIGRACAO_DATABASE_URL (ou DATABASE_URL) no .env, com o usuário "postgres" (dono das tabelas:
a RLS não se aplica a ele). Use a string "Session pooler" (porta 5432) do Supabase.

O que acontece:
- tudo numa transação só: se algo falhar, nada fica pela metade no Supabase;
- ids preservados (links entre processos, tarefas, cards e parcelas continuam iguais);
- checklists (que eram JSON dentro da tarefa/card) viram linhas em checklist_itens;
- no fim, confere tabela por tabela (e itens de checklist, e soma das parcelas); se não bater, desfaz tudo;
- o arquivo SQLite não é alterado (fica como backup): a leitura é feita numa cópia, junto com o -wal (o app antigo
  usava WAL; o que foi registrado por último pode estar só nele);
- a "impressão digital" do banco copiado fica no Supabase: o app avisa, no computador que tiver um banco antigo
  diferente, que há dados fora do Supabase.
"""
import argparse
import json
import os
import platform
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import psycopg  # noqa: E402

from app import banco_antigo, config, db, financeiro  # noqa: E402  (config carrega o .env)

# tabelas com id próprio (sequência a acertar depois de copiar com os ids antigos)
COM_ID = ["advogadas", "advogados_cooperacao", "pessoas", "tarefas", "clientes", "checklist_itens", "lancamentos",
          "parcelas", "pagamentos", "feriados",
          "tipos_ato", "sync_erros"]
DADOS = ["advogadas", "processos", "comunicacoes", "tarefas", "clientes", "lancamentos"]  # "destino vazio" = sem estes
META_IGNORADA = {"schema_versao", "sync_trava", "sync_estado"}  # controle do banco antigo / de uma sincronização em curso


class Copia:
    def __init__(self, origem: sqlite3.Connection, destino: psycopg.Connection):
        db.preparar(destino)  # datas e JSON como texto, como o app lê
        self.o, self.d = origem, destino
        self.avisos: list[str] = []
        self.meta_novas: list[str] = []  # chaves que a migração acrescenta (não existiam no banco antigo)
        self.contagem: dict[str, tuple[int, int]] = {}  # tabela -> (origem, destino)

    # --- leitura do SQLite (tolerante a bancos de versões antigas) ----------------------
    def tem(self, tabela: str) -> bool:
        return bool(self.o.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabela,)).fetchone())

    def linhas(self, tabela: str) -> list[dict]:
        return [dict(r) for r in self.o.execute(f"SELECT * FROM {tabela}")] if self.tem(tabela) else []

    # --- conversões ------------------------------------------------------------------
    def data(self, valor, onde: str):
        if valor in (None, ""):
            return None
        try:
            return date.fromisoformat(str(valor)[:10]).isoformat()
        except ValueError:
            self.avisos.append(f"{onde}: data inválida {valor!r} gravada como vazia")
            return None

    def momento(self, valor, onde: str):
        if valor in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(valor)).isoformat()
        except ValueError:
            return self.data(valor, onde)

    def hora(self, valor, onde: str):
        if valor in (None, ""):
            return None
        v = str(valor)[:5]
        try:
            datetime.strptime(v, "%H:%M")
            return v
        except ValueError:
            self.avisos.append(f"{onde}: horário inválido {valor!r} gravado como vazio")
            return None

    def json_(self, valor, onde: str):
        if valor in (None, ""):
            return None
        try:
            return json.dumps(json.loads(valor), ensure_ascii=False)
        except (TypeError, ValueError):
            self.avisos.append(f"{onde}: JSON inválido gravado como vazio")
            return None

    @staticmethod
    def bool_(valor, padrao=False):
        return padrao if valor is None else bool(valor)

    # --- escrita --------------------------------------------------------------------
    def inserir(self, tabela: str, linhas: list[dict], origem_qtd: int | None = None):
        if linhas:
            cols = list(linhas[0])
            with self.d.cursor() as cur:
                cur.executemany(f"INSERT INTO {tabela}({','.join(cols)}) VALUES({','.join(['%s'] * len(cols))})",
                                [tuple(x[c] for c in cols) for x in linhas])
        self.contagem[tabela] = (len(linhas) if origem_qtd is None else origem_qtd, None)


def copiar(c: Copia, emails: dict[str, str]):
    o = c
    # advogadas (do banco antigo; se não houver a tabela, do config.json antigo)
    advs = o.linhas("advogadas") or [{"id": i, **a} for i, a in enumerate(config.advogadas_do_arquivo(), start=1)]
    o.inserir("advogadas", [{"id": a["id"], "nome": a.get("nome") or f"OAB {a['oab_numero']}/{a['oab_uf']}",
                             "oab_numero": a["oab_numero"], "oab_uf": a["oab_uf"],
                             "cor": a.get("cor") or config.CORES[0],
                             "email": emails.get(f"{a['oab_numero']}/{a['oab_uf']}".upper())} for a in advs])
    o.inserir("pessoas", [{"id": p["id"], "nome": p["nome"], "ativo": o.bool_(p.get("ativo"), True),
                           "criado_em": o.momento(p.get("criado_em"), "pessoas") or datetime.now().isoformat()}
                          for p in o.linhas("pessoas")])

    procs = o.linhas("processos")
    o.inserir("processos", [{
        "numero": p["numero"], "tribunal": p.get("tribunal"), "alias": p.get("alias"), "origem": p.get("origem"),
        "orgao": p.get("orgao"), "classe": p.get("classe"), "assuntos": o.json_(p.get("assuntos"), f"processo {p['numero']}"),
        "grau": p.get("grau"), "data_ajuizamento": o.data(p.get("data_ajuizamento"), f"processo {p['numero']}"),
        "sistema": p.get("sistema"), "instancias": o.json_(p.get("instancias"), f"processo {p['numero']}"),
        "partes": o.json_(p.get("partes"), f"processo {p['numero']}"), "datajud_status": p.get("datajud_status"),
        "datajud_msg": p.get("datajud_msg"), "datajud_em": o.momento(p.get("datajud_em"), "processos"),
        "ult_mov_data": o.momento(p.get("ult_mov_data"), "processos"), "ult_mov_texto": p.get("ult_mov_texto"),
        "ult_pub_data": o.data(p.get("ult_pub_data"), "processos"), "ult_pub_texto": p.get("ult_pub_texto"),
        "ult_atividade": o.momento(p.get("ult_atividade"), "processos"),
        "novidade_em": o.momento(p.get("novidade_em"), "processos"), "visto_em": o.momento(p.get("visto_em"), "processos"),
        "contagem": p.get("contagem") or None, "busca": p.get("busca"),
        "cooperacao": o.bool_(p.get("cooperacao")),
        "cooperacao_manual": None if p.get("cooperacao_manual") is None else bool(p["cooperacao_manual"]),
        "criado_em": o.momento(p.get("criado_em"), "processos") or datetime.now().isoformat(),
    } for p in procs])
    o.inserir("processo_advogada", [{"numero": x["numero"], "advogada_id": x["advogada_id"], "origem": x.get("origem"),
                                     "criado_em": o.momento(x.get("criado_em"), "processo_advogada") or datetime.now().isoformat()}
                                    for x in o.linhas("processo_advogada")])
    o.inserir("comunicacoes", [{
        "hash": x["hash"], "djen_id": x.get("djen_id"), "numero": x["numero"], "tribunal": x.get("tribunal"),
        "orgao": x.get("orgao"), "tipo": x.get("tipo"), "tipo_documento": x.get("tipo_documento"), "classe": x.get("classe"),
        "data_disp": o.data(x.get("data_disp"), "comunicacoes"), "texto": x.get("texto"), "texto_original": x.get("texto_original"),
        "link": x.get("link"), "destinatarios": o.json_(x.get("destinatarios"), "comunicacoes"),
        "advogados": o.json_(x.get("advogados"), "comunicacoes"), "busca": x.get("busca"),
        "capturado_em": o.momento(x.get("capturado_em"), "comunicacoes") or datetime.now().isoformat(),
    } for x in o.linhas("comunicacoes")])
    o.inserir("comunicacao_advogada", [{"hash": x["hash"], "advogada_id": x["advogada_id"]} for x in o.linhas("comunicacao_advogada")])
    o.inserir("comunicacao_analise", [{"hash": x["hash"], "analisado_em": o.momento(x.get("analisado_em"), "analise"),
                                       "resultado": x.get("resultado"), "detalhe": x.get("detalhe")}
                                      for x in o.linhas("comunicacao_analise")])
    o.inserir("movimentos", [{
        "chave": x["chave"], "numero": x["numero"], "grau": x.get("grau"), "codigo": x.get("codigo"),
        "data_hora": o.momento(x.get("data_hora"), "movimentos"), "nome": x.get("nome"), "complementos": x.get("complementos"),
        "orgao": x.get("orgao"), "capturado_em": o.momento(x.get("capturado_em"), "movimentos") or datetime.now().isoformat(),
    } for x in o.linhas("movimentos")])

    itens: list[dict] = []
    tarefas = o.linhas("tarefas")
    o.inserir("tarefas", [{
        "id": t["id"], "titulo": t["titulo"], "tipo": t.get("tipo") or "tarefa", "status": t.get("status") or "a_fazer",
        "status_anterior": t.get("status_anterior"), "numero": t.get("numero") or None, "advogada_id": t.get("advogada_id"),
        "prazo_fatal": o.data(t.get("prazo_fatal"), f"tarefa {t['id']}"),
        "data_interna": o.data(t.get("data_interna"), f"tarefa {t['id']}"), "hora": o.hora(t.get("hora"), f"tarefa {t['id']}"),
        "prioridade": t.get("prioridade") or "media", "observacoes": t.get("observacoes"), "origem": t.get("origem") or "manual",
        "comunicacao_hash": t.get("comunicacao_hash"), "trecho": t.get("trecho"),
        "calculo": o.json_(t.get("calculo"), f"tarefa {t['id']}"), "conferir": o.bool_(t.get("conferir")), "aviso": t.get("aviso"),
        "criado_em": o.momento(t.get("criado_em"), "tarefas") or datetime.now().isoformat(),
        "atualizado_em": o.momento(t.get("atualizado_em"), "tarefas"),
        "concluido_em": o.momento(t.get("concluido_em"), "tarefas"),
    } for t in tarefas])
    itens += _itens(o, "tarefa_id", tarefas)
    o.inserir("tarefas_geradas", [{"chave": x["chave"], "criado_em": o.momento(x.get("criado_em"), "tarefas_geradas")
                                   or datetime.now().isoformat()} for x in o.linhas("tarefas_geradas")])

    for col in o.linhas("quadro_colunas"):  # as 5 colunas já existem (schema.sql): só copia os nomes
        c.d.execute("""INSERT INTO clientes_colunas(id, posicao, nome) VALUES(%s, %s, %s)
                       ON CONFLICT (id) DO UPDATE SET posicao=excluded.posicao, nome=excluded.nome""",
                    (col["id"], col["posicao"], col.get("nome") or ""))
    cards = o.linhas("quadro_cards")
    o.inserir("clientes", [{
        "id": q["id"], "coluna_id": q["coluna_id"], "posicao": q.get("posicao") or 0, "nome": q["titulo"],
        "tipo": q.get("tipo") or "processo", "numero": q.get("numero") or None, "prazo_descricao": q.get("prazo_descricao"),
        "prazo_data": o.data(q.get("prazo_data"), f"card {q['id']}"), "prazo_hora": o.hora(q.get("prazo_hora"), f"card {q['id']}"),
        "aniversario": o.data(q.get("aniversario"), f"card {q['id']}"),
        "criado_em": o.momento(q.get("criado_em"), "clientes") or datetime.now().isoformat(),
        "atualizado_em": o.momento(q.get("atualizado_em"), "clientes"),
    } for q in cards])
    itens += _itens(o, "cliente_id", cards)
    for i, item in enumerate(itens, start=1):
        item["id"] = i
    o.inserir("checklist_itens", itens)  # itens sem texto (que o app já ignorava) não entram: viram aviso

    nomes = {}  # lançamento ligado ao card de Clientes de mesmo nome (como o app faz ao salvar)
    for q in cards:
        nomes.setdefault(financeiro.chave_cliente(q["titulo"]), []).append(q["id"])
    lancs = o.linhas("lancamentos")
    o.inserir("lancamentos", [{
        "id": x["id"], "cliente": x["cliente"],
        "cliente_id": (lambda ids: ids[0] if len(ids) == 1 else None)(nomes.get(financeiro.chave_cliente(x["cliente"]), [])),
        "numero": x.get("numero") or None, "valor_total": x["valor_total"], "entrada": x.get("entrada") or 0,
        "entrada_data": o.data(x.get("entrada_data"), f"lançamento {x['id']}"), "valor_parcela": x.get("valor_parcela") or 0,
        "qtd_parcelas": x.get("qtd_parcelas") or 0, "observacoes": x.get("observacoes"),
        "inadimplente": o.bool_(x.get("inadimplente")),
        "criado_em": o.momento(x.get("criado_em"), "lancamentos") or datetime.now().isoformat(),
        "atualizado_em": o.momento(x.get("atualizado_em"), "lancamentos"),
    } for x in lancs])

    # Pagamentos: banco com histórico (v7+) copia a tabela; banco v6 transforma cada parcela paga num pagamento do
    # valor cheio na data em que foi paga (igual à atualização do próprio app). "Paga" e "pago em" são recalculados
    # a partir do histórico, como o app faz.
    parcelas = o.linhas("parcelas")
    if o.tem("pagamentos"):
        pagamentos = [{"id": g["id"], "parcela_id": g["parcela_id"], "valor": g["valor"],
                       "data": o.data(g["data"], f"pagamento {g['id']}"),
                       "criado_em": o.momento(g.get("criado_em"), "pagamentos") or datetime.now().isoformat()}
                      for g in o.linhas("pagamentos")]
        qtd_origem = len(pagamentos)
    else:
        pagamentos = [{"id": i, "parcela_id": x["id"], "valor": x["valor"],
                       "data": o.data(x.get("pago_em"), f"parcela {x['id']}") or o.data(x["vencimento"], "parcela"),
                       "criado_em": datetime.now().isoformat()}
                      for i, x in enumerate((x for x in parcelas if x.get("pago") and x["valor"] > 0), start=1)]
        qtd_origem = len(pagamentos)
    por_parcela: dict[int, list[dict]] = {}
    for g in sorted(pagamentos, key=lambda g: (g["data"], g["id"])):
        por_parcela.setdefault(g["parcela_id"], []).append(g)
    linhas_parcelas = []
    for x in parcelas:
        _, quitou = financeiro.quitacao(x["valor"], por_parcela.get(x["id"], []))
        if bool(quitou) != bool(x.get("pago")):
            o.avisos.append(f"parcela {x['id']}: situação recalculada pelos pagamentos ({'paga' if quitou else 'em aberto'})")
        linhas_parcelas.append({"id": x["id"], "lancamento_id": x["lancamento_id"], "numero": x["numero"],
                                "vencimento": o.data(x["vencimento"], f"parcela {x['id']}"), "valor": x["valor"],
                                "pago": bool(quitou), "pago_em": quitou})
    o.inserir("parcelas", linhas_parcelas)
    o.inserir("pagamentos", pagamentos, origem_qtd=qtd_origem)

    o.inserir("feriados", [{
        "id": f["id"], "inicio": f["inicio"], "fim": f.get("fim") or None, "descricao": f["descricao"], "tipo": f["tipo"],
        "tribunais": f.get("tribunais") or "", "comarca": f.get("comarca") or "", "recorrente": o.bool_(f.get("recorrente")),
        "origem": f.get("origem"), "ativo": o.bool_(f.get("ativo"), True),
    } for f in o.linhas("feriados")])
    o.inserir("tipos_ato", [{
        "id": t["id"], "ordem": t.get("ordem"), "nome": t["nome"], "palavras": t["palavras"], "dias": t.get("dias"),
        "contagem": t.get("contagem") or None, "justica": t.get("justica") or "", "ativo": o.bool_(t.get("ativo"), True),
    } for t in o.linhas("tipos_ato")])
    o.inserir("lembretes_feitos", [{"chave": x["chave"], "feito_em": o.momento(x.get("feito_em"), "lembretes")
                                    or datetime.now().isoformat()} for x in o.linhas("lembretes_feitos")])
    meta = o.linhas("meta")
    o.inserir("meta", [{"chave": m["chave"], "valor": m["valor"]} for m in meta if m["chave"] not in META_IGNORADA],
              origem_qtd=len([m for m in meta if m["chave"] not in META_IGNORADA]))
    # Cooperação: a lista e o "ocultar" ficavam no config.json; agora ficam no banco (tabela e ajuste da tela)
    lista = config.cooperacao_do_arquivo()
    o.inserir("advogados_cooperacao", [{"id": i, **a} for i, a in enumerate(lista, start=1)])
    o.d.execute("INSERT INTO meta(chave, valor) VALUES('cooperacao_semeada', %s)", (datetime.now().isoformat(),))
    o.meta_novas.append("cooperacao_semeada")
    arquivo = config._arquivo()
    if "ocultar_cooperacao" in arquivo:
        o.d.execute("INSERT INTO meta(chave, valor) VALUES('ajuste:ocultar_cooperacao', %s)",
                    (json.dumps(bool(arquivo["ocultar_cooperacao"])),))
        o.meta_novas.append("ajuste:ocultar_cooperacao")
    if not procs or "cooperacao" not in procs[0]:  # banco antigo sem a marcação: faz agora, com a lista
        marcados = db.atualizar_cooperacao(db.Conexao(o.d), lista=lista)
        o.avisos.append(f"cooperação: {marcados} processo(s) marcado(s) pela lista de advogados de cooperação")
    o.inserir("sync_erros", [{
        "id": e["id"], "sync_id": e.get("sync_id"), "quando": o.momento(e.get("quando"), "sync_erros") or datetime.now().isoformat(),
        "fonte": e.get("fonte"), "tribunal": e.get("tribunal"), "mensagem": e.get("mensagem"),
    } for e in o.linhas("sync_erros")])


def _lista(valor) -> list:
    try:
        lista = json.loads(valor) if valor else []
        return lista if isinstance(lista, list) else []
    except ValueError:
        return []


def _itens(o: Copia, coluna: str, donos: list[dict]) -> list[dict]:
    """Checklist JSON (formato do app antigo) -> linhas de checklist_itens, na mesma ordem."""
    from app.checklist import normalizar
    advs = {r[0] for r in o.d.execute("SELECT id FROM advogadas")}
    pessoas = {r[0] for r in o.d.execute("SELECT id FROM pessoas")}
    saida = []
    for dono in donos:
        brutos = _lista(dono.get("checklist"))
        normalizados = normalizar(brutos)
        if len(normalizados) != len(brutos):
            o.avisos.append(f"{coluna.split('_')[0]} {dono['id']}: {len(brutos) - len(normalizados)} item(ns) de checklist sem texto descartado(s)")
        for pos, c in enumerate(normalizados, start=1):
            tipo, _, num = (c["resp"] or "").partition(":")
            saida.append({"tarefa_id": dono["id"] if coluna == "tarefa_id" else None,
                          "cliente_id": dono["id"] if coluna == "cliente_id" else None,
                          "item_id": c["id"], "posicao": pos, "texto": c["texto"], "feito": c["feito"],
                          "data": c["data"], "hora": c["hora"],
                          "advogada_id": int(num) if tipo == "a" and int(num) in advs else None,
                          "pessoa_id": int(num) if tipo == "p" and int(num) in pessoas else None})
    return saida


def finalizar(destino: psycopg.Connection):
    """Próximos ids continuam depois dos copiados; logins que já existem ficam vinculados às advogadas."""
    for t in COM_ID:
        destino.execute(f"SELECT setval(pg_get_serial_sequence('public.{t}', 'id'), GREATEST((SELECT MAX(id) FROM {t}), 1))")
    destino.execute("""UPDATE advogadas a SET user_id = u.id FROM auth.users u
                       WHERE a.email = lower(u.email) AND u.email_confirmed_at IS NOT NULL""")


# --substituir: tudo menos clientes_colunas (as 5 colunas fixas do quadro, que só voltam a ficar sem nome)
LIMPAR = ["advogadas", "advogados_cooperacao", "pessoas", "processos", "processo_advogada", "comunicacoes",
          "comunicacao_advogada", "comunicacao_analise", "movimentos", "tarefas", "tarefas_geradas", "clientes",
          "checklist_itens", "lancamentos", "parcelas", "pagamentos", "feriados", "tipos_ato", "lembretes_feitos",
          "meta", "sync_erros"]


def limpar(destino: psycopg.Connection) -> dict[str, int]:
    """Esvazia o Supabase dentro da transação da cópia (se algo falhar depois, o rollback devolve tudo).
    Devolve quantas linhas cada tabela tinha."""
    antes = {t: destino.execute(f"SELECT count(*) FROM public.{t}").fetchone()[0] for t in LIMPAR}
    destino.execute("TRUNCATE " + ", ".join(f"public.{t}" for t in LIMPAR) + " RESTART IDENTITY")
    destino.execute("UPDATE public.clientes_colunas SET nome = '', posicao = id")
    return antes


def registrar_origem(c: Copia, caminho: Path, impressao: str):
    """Guarda de onde veio o conteúdo do Supabase; o app compara com o banco antigo de cada computador."""
    valor = {"impressao": impressao, "arquivo": str(caminho), "computador": platform.node(),
             "quando": datetime.now().isoformat(timespec="seconds")}
    c.d.execute("INSERT INTO meta(chave, valor) VALUES(%s, %s) ON CONFLICT (chave) DO UPDATE SET valor = excluded.valor",
                (banco_antigo.CHAVE_META, json.dumps(valor, ensure_ascii=False)))
    c.meta_novas.append(banco_antigo.CHAVE_META)


def conferir(c: Copia) -> bool:
    ok = True
    print(f"\n{'tabela':24} {'antigo':>8} {'Supabase':>9}")
    for tabela, (antes, _) in c.contagem.items():
        depois = c.d.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
        if tabela == "meta":
            depois -= len(c.meta_novas)
        marca = "" if antes == depois else "   <-- NÃO BATE"
        ok &= antes == depois
        print(f"{tabela:24} {antes:>8} {depois:>9}{marca}")
    soma_o = c.o.execute("SELECT COALESCE(SUM(valor), 0) FROM parcelas").fetchone()[0] if c.tem("parcelas") else 0
    soma_d = c.d.execute("SELECT COALESCE(SUM(valor), 0) FROM parcelas").fetchone()[0]
    print(f"{'soma das parcelas (¢)':24} {soma_o:>8} {soma_d:>9}{'' if soma_o == soma_d else '   <-- NÃO BATE'}")
    return ok and soma_o == soma_d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sqlite", default=str(config.DB_PATH), help="banco antigo (padrão: db/processos.sqlite3)")
    ap.add_argument("--email", action="append", default=[], metavar="OAB/UF=email",
                    help="e-mail de login de cada advogada, ex.: 130678/PR=beatriz@exemplo.com (pode repetir)")
    ap.add_argument("--simular", action="store_true", help="faz tudo, confere e desfaz (não grava nada)")
    ap.add_argument("--config", help="config.json do computador de onde veio o banco (lista de cooperação e "
                                     "'ocultar'); padrão: o desta pasta")
    ap.add_argument("--substituir", action="store_true",
                    help="se o Supabase já tiver dados, apaga e copia este banco no lugar (na mesma transação)")
    args = ap.parse_args()

    emails = {}
    for par in args.email:
        oab, _, email = par.partition("=")
        if not email or "@" not in email:
            sys.exit(f"--email inválido: {par!r} (use OAB/UF=email)")
        emails[oab.strip().upper()] = email.strip().lower()
    url = os.environ.get("MIGRACAO_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Falta MIGRACAO_DATABASE_URL (ou DATABASE_URL) no .env — veja o README.")
    caminho = Path(args.sqlite).resolve()
    if not caminho.exists():
        sys.exit(f"Banco antigo não encontrado: {caminho}")
    if args.config:
        config.CONFIG_PATH = Path(args.config).resolve()  # cooperação e "ocultar" do computador de onde veio o banco
        if not config.CONFIG_PATH.exists():
            sys.exit(f"config.json não encontrado: {config.CONFIG_PATH}")
    extras = [f.name for f in banco_antigo.arquivos(caminho)[1:]]
    print(f"Banco antigo: {caminho}" + (f" (com {', '.join(extras)}: incluído na leitura)" if extras else ""))
    print(f"Configuração: {config.CONFIG_PATH}")

    with banco_antigo.copia(caminho) as origem, psycopg.connect(url, prepare_threshold=None) as destino:
        try:
            destino.execute("SET LOCAL TIME ZONE 'America/Sao_Paulo'")  # horários do banco antigo são de Brasília
        except psycopg.errors.InvalidParameterValue:
            destino.rollback()
            destino.execute("SET LOCAL TIME ZONE '<-03>+03'")
        if not destino.execute("SELECT to_regclass('public.advogadas')").fetchone()[0]:
            sys.exit("As tabelas não existem no Supabase: rode supabase/schema.sql no SQL Editor primeiro.")
        cheias = [t for t in DADOS if destino.execute(f"SELECT EXISTS (SELECT 1 FROM {t})").fetchone()[0]]
        if cheias and not args.substituir:
            sys.exit(f"O Supabase já tem dados ({', '.join(cheias)}). Para trocar tudo pelo conteúdo deste banco, rode "
                     "de novo com --substituir (primeiro junto com --simular).")
        if cheias:
            antes = limpar(destino)
            print("Substituindo o que estava no Supabase:",
                  ", ".join(f"{t} {n}" for t, n in antes.items() if n and t in DADOS + ["movimentos", "parcelas"]))
        impressao = banco_antigo.impressao(origem)
        c = Copia(origem, destino)
        try:
            copiar(c, emails)
        except psycopg.errors.InsufficientPrivilege as e:
            sys.exit(f"Sem permissão ({e.diag.message_primary}). Use a conexão do usuário postgres (dono das tabelas).")
        registrar_origem(c, caminho, impressao)
        finalizar(destino)
        ok = conferir(c)
        for aviso in c.avisos:
            print("aviso:", aviso)
        sem_email = [r[0] for r in destino.execute("SELECT nome FROM advogadas WHERE email IS NULL")]
        if not ok:
            destino.rollback()
            sys.exit("\nAs contagens não bateram: nada foi gravado no Supabase" + (" (nem apagado)." if cheias else "."))
        if args.simular:
            destino.rollback()
            print("\nSimulação: tudo conferido, nada foi gravado" + (" nem apagado." if cheias else "."))
        else:
            destino.commit()
            print("\nMigração concluída e conferida. O arquivo antigo continua intacto em", caminho)
        if sem_email:
            print("Atenção: sem e-mail de login (ninguém entra por elas ainda):", ", ".join(sem_email),
                  "— cadastre o e-mail no SQL Editor (README, seção 1, passo 6).")


if __name__ == "__main__":
    main()
