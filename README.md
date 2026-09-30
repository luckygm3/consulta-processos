# Meus processos

Página única, local e gratuita, com todos os processos da advogada em todos os tribunais.
Roda só no seu computador (http://127.0.0.1:8000). Sem login, sem nuvem, sem certificado digital.

## Instalar num computador novo (Windows)

1. Na página do repositório no GitHub, clique em **Code → Download ZIP**.
2. Clique com o botão direito no ZIP baixado → **Extrair tudo…** e escolha uma pasta (ex.: Documentos).
   Não rode direto de dentro do ZIP.
3. Abra a pasta extraída e dê dois cliques em **`run.bat`**.
   - Se o Windows mostrar “O Windows protegeu o computador”, clique em **Mais informações → Executar assim mesmo**.
   - Se o computador não tiver Python, o `run.bat` pergunta se pode instalar: responda **S** e aguarde.
4. Na primeira vez ele prepara tudo (1–3 min, precisa de internet) e abre o navegador em http://127.0.0.1:8000.
5. Clique em **Atualizar tudo**. A primeira busca (últimos 180 dias) leva uns 5 minutos.

(Quem tem git pode usar `git clone` em vez do ZIP.)

## Como rodar no dia a dia

**Windows:** dois cliques em `run.bat`. O navegador abre sozinho.
**Deixe a janela preta aberta** enquanto usa o app; para encerrar, feche-a.

**Linux/Mac:** `sh run.sh` (requer Python 3.11+).

## Chave do DataJud

O DataJud (CNJ) fornece classe, assuntos, órgão julgador e as movimentações. A chave é pública, gratuita e igual
para todo mundo; **a atual já vem no `config.json`**. O CNJ troca a chave de tempos em tempos. Se aparecer
“Chave do DataJud recusada”:

1. Abra https://datajud-wiki.cnj.jus.br/api-publica/acesso
2. Copie o texto que aparece depois de `APIKey` (uma sequência longa terminada em `==`).
3. No app, clique em **⚙** → cole em “Chave pública do DataJud” → **Salvar**.

(Alternativa: criar um arquivo `.env` com `DATAJUD_API_KEY=...`, que tem prioridade sobre o `config.json`.)

O DJEN (publicações) não precisa de chave.

## Uso

- **Atualizar tudo**: busca publicações no DJEN pela OAB e, em seguida, consulta cada processo no DataJud.
  A primeira vez busca os últimos 180 dias (ajustável em ⚙); depois, só o que é novo.
- **Adicionar processos**: cole vários números CNJ ou importe um CSV/TXT (os números são achados no meio do texto).
- **NOVO** marca processos com publicação ou movimento capturado depois da última vez que você marcou como visto.
- Clique num processo para ver a linha do tempo (publicações + movimentos) e o texto completo das publicações.

## Configuração (`config.json`)

| campo | significado |
|---|---|
| `oab_numero`, `oab_uf`, `nome_advogado` | quem é buscado no DJEN |
| `datajud_api_key` | chave pública do DataJud |
| `backfill_dias` | quantos dias buscar na primeira atualização (padrão 180) |
| `janela_dias` | tamanho de cada consulta ao DJEN (padrão 30) |
| `buscar_tambem_por_nome` | também busca por nome, além da OAB (padrão `false`; nos testes os resultados foram iguais) |
| `porta` | porta local (padrão 8000) |

## Limitações

- A busca automática só encontra processos com **publicação no DJEN** em que a OAB aparece. Processos sem intimação
  recente (ou de tribunais/sistemas que não publicam no DJEN) precisam ser adicionados manualmente.
- **Sem dados públicos (possível segredo de justiça)**: o DataJud não retorna processos sigilosos. Também pode acontecer
  com processos muito recentes, que o CNJ ainda não indexou (o DataJud costuma ter alguns dias ou semanas de atraso).
- O DataJud é consultado no tribunal de origem do número CNJ. Um recurso que subiu para STJ/TST aparece com os dados do
  tribunal de origem.
- STF e conselhos (CNJ, CJF, CSJT) não publicam no DataJud.
- As duas APIs são públicas e às vezes ficam lentas ou sobrecarregadas (erros 429/500/504). O app repete a consulta
  automaticamente; o que falhar aparece em “problemas nesta atualização” e é tentado de novo na próxima vez.
  Sob carga, o DataJud às vezes responde “pela metade” (parte do índice falha); nesse caso o processo **não** é marcado
  como sem dados, e sim como “não respondeu por completo”, e é consultado de novo na próxima atualização.
- Uma atualização completa leva de 3 a 6 minutos (o DataJud demora de 5 a 40 s por consulta).
- O DataJud não informa nomes das partes; elas vêm das publicações do DJEN.

## Arquivos

```
app/        código (FastAPI): djen.py, datajud.py, cnj.py, sync.py, db.py, texto.py, main.py
static/     interface (HTML/CSS/JS puro)
db/         banco SQLite (processos.sqlite3) — apague para recomeçar do zero; não vai para o git
logs/       app.log (erros de rede e dos tribunais)
config.json configuração editável
```
