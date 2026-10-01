# Meus processos

Página única, local e gratuita, com todos os processos das advogadas (uma ou mais OABs) em todos os tribunais.
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

## Instalar num Mac

1. **Instale o Python (uma vez só):** abra https://www.python.org/downloads/, clique no botão amarelo
   “Download Python 3.x”, abra o arquivo `.pkg` baixado e siga o instalador (ele pede a senha do Mac).
   O Python que já vem no Mac é antigo demais e não serve.
2. No GitHub, clique em **Code → Download ZIP**. O Safari normalmente já descompacta; se não, dê dois cliques no ZIP.
   Mova a pasta para **Documentos** (para não se perder na pasta Downloads).
3. Abra a pasta e dê dois cliques em **`abrir-no-mac.command`**.
   - Na primeira vez o Mac bloqueia (“não pode ser aberto porque é de um desenvolvedor não identificado” ou
     “a Apple não pôde verificar…”). Clique em **OK/Concluído**, vá em **Ajustes do Sistema → Privacidade e Segurança**,
     role até o fim e clique em **Abrir Mesmo Assim** (no macOS 14 ou anterior, também funciona Control+clique
     no arquivo → **Abrir** → **Abrir**). Depois disso, os dois cliques funcionam direto.
   - Se preferir evitar o aviso: abra o app **Terminal**, digite `sh ` (com um espaço no fim), arraste o arquivo
     `run.sh` da pasta para dentro da janela do Terminal e aperte Enter.
4. Na primeira vez ele prepara tudo (1–3 min) e abre o navegador em http://127.0.0.1:8000. Clique em **Atualizar tudo**.

## Como rodar no dia a dia

**Windows:** dois cliques em `run.bat`. **Mac:** dois cliques em `abrir-no-mac.command`. **Linux:** `sh run.sh`.
O navegador abre sozinho. **Deixe a janela preta (Terminal) aberta** enquanto usa o app; para encerrar, feche-a.

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

- **Atualizar tudo**: busca publicações no DJEN pela OAB de cada advogada e, em seguida, consulta cada processo no DataJud.
  Cada processo fica vinculado a quem o encontrou; se aparecer para as duas, fica com as duas.
  A primeira vez busca os últimos 180 dias (ajustável em ⚙); depois, só o que é novo.
- **Adicionar processos**: cole vários números CNJ ou importe um CSV/TXT (os números são achados no meio do texto)
  e escolha de quem são (uma advogada ou ambas).
- **Filtro por advogada** (Todas / cada uma), com contadores, combinável com os demais filtros. A etiqueta colorida
  na tabela mostra quem atua em cada processo.
- **NOVO** marca processos com publicação ou movimento capturado depois da última vez que você marcou como visto.
- Clique num processo para ver a linha do tempo (publicações + movimentos) e o texto completo das publicações.

## Agenda e prazos (aba “Agenda”)

> **Prazos calculados automaticamente são sugestões. Confirme sempre no processo e no calendário do tribunal.**

- Três visões: **Kanban** (Sugeridos → A fazer → Em andamento → Aguardando terceiros → Concluído; arraste os cartões),
  **Calendário** (mês/semana, com feriados) e **Lista por data**. Filtros por advogada, processo, status e período.
- Cores por urgência: vermelho = vencido; laranja = vence hoje/próximo dia útil; amarelo = até 5 dias úteis; verde = folgado.
- **+ Nova tarefa**: qualquer tarefa, com ou sem processo, com checklist, prioridade e observações. No painel de um
  processo há o atalho **+ Tarefa / prazo**. O quadro “Calcular prazo” calcula o fatal a partir da disponibilização.
- **Verificar prazos** (sem IA): lê as publicações do DJEN ainda não analisadas, procura expressões como “prazo de
  quinze (15) dias”, “em 48 horas”, “5 dias úteis”, “manifeste-se”, “contestar”, “intime-se para”, reconhece o ato
  (contestação, apelação, embargos de declaração…) e cria cartões em **Sugeridos** com o trecho original, o link da
  publicação e a memória de cálculo. **Confirmar** (um ou em lote) leva para “A fazer”; **Descartar** guarda a decisão
  (a publicação não sugere de novo). Detecções incertas vêm marcadas “conferir manualmente”. Por padrão, publicações
  cujo prazo já venceu não viram cartão (há uma opção para incluí-las). Audiências com data no texto também viram cartão.
- **Tipos de ato**: tabela editável (palavras-chave → nome do ato e prazo padrão). O prazo padrão só é usado quando o
  texto não traz o número de dias; sem nenhuma indicação, vale o CPC art. 218 §3º (5 dias).
- **Feriados**: tabela editável por tribunal ou comarca (feriado municipal: preencha a comarca como aparece no nome da
  vara). Vem pré-preenchida para o ano passado e os próximos dois anos — **confira com o calendário oficial do tribunal**.
- **Exportar .ics**: gera um arquivo para importar no Google Agenda (Configurações → Importar e exportar). Exporta todas
  ou só as filtradas; sugestões não confirmadas ficam de fora.
- Ao abrir o app, uma faixa avisa quantos prazos vencem hoje/amanhã e quantos estão vencidos.

### Regras do cálculo (`app/prazos.py`)

1. **Publicação**: com a regra padrão `"djen"`, considera-se publicada no 1º dia útil seguinte à disponibilização
   (Lei 11.419/2006, art. 4º §3º; Res. CNJ 455/2022). Com `"disponibilizacao"`, no próprio dia.
2. **Início**: 1º dia útil seguinte à publicação — exclui o dia do começo e inclui o do vencimento (CPC art. 224).
3. **Dias úteis** por padrão (CPC art. 219). Dá para usar **dias corridos** por tipo de ato ou por processo (no painel).
   Em dias corridos, se o último dia não for útil, prorroga para o próximo dia útil.
4. Não contam: fins de semana, feriados e suspensões da tabela (filtrados pelo tribunal e pela comarca do processo)
   e o **recesso de 20/12 a 20/01** (CPC art. 220), que suspende a contagem.
5. Dias de **expediente reduzido** (ex.: Quarta-feira de Cinzas) contam, mas começo/vencimento nesses dias são
   prorrogados (CPC art. 224 §1º).
6. **Data interna** = N dias úteis antes do fatal (padrão 2).
7. Prazo em horas é convertido em dias corridos e marcado para conferência. Prazo em dobro não é aplicado
   automaticamente (só um aviso quando o texto menciona).

Testes do cálculo e da detecção: `.venv\Scripts\python -m unittest discover -s tests -t . -v`
(no Mac/Linux: `.venv/bin/python -m unittest discover -s tests -t . -v`).

## Configuração (`config.json`)

| campo | significado |
|---|---|
| `advogadas` | lista de quem é buscado no DJEN: `nome`, `oab_numero`, `oab_uf`, `cor` (nome e cor também mudam em ⚙). O formato antigo (`oab_numero`, `oab_uf`, `nome_advogado` soltos) continua aceito |
| `datajud_api_key` | chave pública do DataJud |
| `backfill_dias` | quantos dias buscar na primeira atualização (padrão 180) |
| `janela_dias` | tamanho de cada consulta ao DJEN (padrão 30) |
| `buscar_tambem_por_nome` | também busca por nome, além da OAB (padrão `false`; nos testes os resultados foram iguais). Só vale para nomes com nome e sobrenome |
| `porta` | porta local (padrão 8000) |
| `prazos_regra_publicacao` | `"djen"` (publicação = 1º dia útil após a disponibilização, padrão) ou `"disponibilizacao"` |
| `prazos_dias_internos` | data interna sugerida: quantos dias úteis antes do prazo fatal (padrão 2) |
| `prazos_contagem_padrao` | `"uteis"` (padrão) ou `"corridos"` |

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
app/        código (FastAPI): djen.py, datajud.py, cnj.py, sync.py, db.py, texto.py, main.py;
            agenda: prazos.py (calendário e cálculo), extrair.py (regex), agenda.py, rotas_agenda.py
static/     interface (HTML/CSS/JS puro; agenda.js = aba Agenda)
tests/      testes do cálculo de prazos e da detecção no texto
db/         banco SQLite (processos.sqlite3) — apague para recomeçar do zero; não vai para o git.
            Antes de mudar a estrutura do banco, o app guarda uma cópia (processos.sqlite3.bak-AAAAMMDD)
logs/       app.log (erros de rede e dos tribunais)
config.json configuração editável
```
