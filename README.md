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

O **menu lateral** tem as cinco telas: **Andamentos Processuais**, **Monitoramento**, **Clientes**,
**Agenda** e **Financeiro**, além de **Configurações** no pé. O selo vermelho no Monitoramento conta prazos que
vencem hoje/amanhã ou já venceram; no Financeiro, parcelas em atraso. **Recolher** deixa só os ícones (o app lembra);
em tela estreita (celular) o menu vira uma gaveta aberta pelo **☰**.

### Andamentos Processuais

- **Atualizar tudo**: busca publicações no DJEN pela OAB de cada advogada e, em seguida, consulta cada processo no DataJud.
  Cada processo fica vinculado a quem o encontrou; se aparecer para as duas, fica com as duas.
  A primeira vez busca os últimos 180 dias (ajustável em ⚙); depois, só o que é novo.
- **Adicionar processos**: cole vários números CNJ ou importe um CSV/TXT (os números são achados no meio do texto)
  e escolha de quem são (uma advogada ou ambas).
- **Filtro por advogada** (Todas / cada uma), com contadores, combinável com os demais filtros. A etiqueta colorida
  na tabela mostra quem atua em cada processo.
- **NOVO** marca processos com publicação ou movimento capturado depois da última vez que você marcou como visto.
- Clique num processo para ver a linha do tempo (publicações + movimentos) e o texto completo das publicações.
- **Processos em cooperação**: processo em que consta um dos advogados de cooperação (⚙; já vem com Jessica Delmoni,
  OAB 13043/AL). Casa pela OAB dos advogados das publicações; quando a publicação não traz OAB, pelo nome (sem
  acento/maiúscula). A marcação é refeita a cada atualização e quando a lista muda. Com **Ocultar processos em
  cooperação** ligado (padrão), eles somem dos Andamentos, dos contadores e do filtro por advogada, do Monitoramento e
  da Agenda, mesmo que a Beatriz ou a Kazuza também atuem; ao lado da contagem, “X processos em cooperação ocultos ·
  mostrar” liga/desliga na hora. Nada é apagado. No painel do processo, a caixa **Processo em cooperação** marca ou
  desmarca à mão (vale por cima da detecção automática).

## Monitoramento (prazos)

> **Prazos calculados automaticamente são sugestões. Confirme sempre no processo e no calendário do tribunal.**

Prazos que o sistema cria para lembrar de monitorar, avaliar a pertinência e incluir no checklist do cliente
(era a aba “Agenda”; o calendário dela passou para a tela **Agenda**, que junta tudo).

- Duas visões: **Kanban** (Sugeridos → A fazer → Em andamento → Aguardando terceiros; arraste os cartões) e
  **Lista por data**. Filtros por advogada e por processo.
- **Concluídos**: o ícone ao lado das visões. Conclua pelo círculo do cartão (aparece ao passar o mouse), pela lista,
  pelo botão **✓ Concluir** da tarefa, ou arrastando o cartão até o ícone. Lá dentro: **Restaurar** (volta para a
  coluna de onde saiu) ou **Excluir definitivamente**.
- **Contrair todos / Expandir todos** (Kanban): card contraído mostra só o título e o progresso da checklist. Clicar
  num card contrai/expande só ele; para abrir a tarefa, use **Editar** (aparece ao passar o mouse) ou dois cliques.
  O app lembra o estado.
- **Exportar .ics**, **Feriados** e **Tipos de ato** ficam escondidos: aparecem ao passar o mouse na barra da agenda
  (ou ao tocar no **⋯**).
- Cores por urgência: vermelho = vencido; laranja = vence hoje/próximo dia útil; amarelo = até 5 dias úteis; verde = folgado.
- **+ Nova tarefa**: qualquer tarefa, com ou sem processo, com checklist, prioridade e observações. No painel de um
  processo há o atalho **+ Tarefa / prazo**. O quadro “Calcular prazo” calcula o fatal a partir da disponibilização.
- **Checklist (estilo Trello)**, nas tarefas e nos cards do quadro de clientes. Cada item tem texto, feito/não feito
  e, opcionais, **data**, **horário** (só com data) e **responsável** — clique no ícone do item (ou nas etiquetas dele)
  para abrir esses campos. Arraste pela alça para reordenar; edite, exclua e adicione itens. Progresso discreto (“3/17”).
  - **Responsáveis**: as advogadas e as pessoas da **Equipe** (⚙ Configurações → Equipe; vale na hora).
  - **Na agenda**: todo item com data aparece na **Agenda** e na **Lista por data**, no dia/horário dele, como
    “Elaboração do Mérito · Fulano” (nome da demanda), mais leve que os prazos. A caixinha marca como feito — é o mesmo
    item do card/tarefa (nada é copiado), então vale nos dois lugares. Clicar no texto abre a demanda. Itens sem data
    ficam só dentro dela; itens feitos saem da lista (no calendário ficam riscados). O Kanban não mostra itens.
  - **Filtro Beatriz/Kazuza**: considera também o responsável do item (item dela aparece no filtro dela; a demanda
    também aparece se tiver algum item com ela).
- **Checklists padrão** (`checklists_padrao.txt`, um arquivo só): seção `[processo]` (as 17 etapas do contencioso) e
  `[preventivo]` (consultoria). No quadro, o tipo do card escolhe a lista (petição inicial usa a de processo); numa
  tarefa nova da agenda, “Modelo da checklist” escolhe (padrão: processo). Edite o arquivo para trocar as listas;
  vale para as próximas demandas. Sugestões do DJEN e verificações semanais não recebem checklist.
- **Prazo fatal: processual × interno.** Pontinho **cheio** = processual (veio do processo: publicação do DJEN,
  “Verificar prazos” ou “Calcular prazo”); pontinho **vazado** = interno (data posta à mão). Se algum item tiver data
  depois do prazo fatal da demanda, aparece um aviso discreto (não bloqueia).
- **Processos sigilosos**: toda segunda-feira, cada processo que o DataJud não detalha ganha a tarefa
  “Verificar processo sigiloso nº …” em A fazer (sem duplicar: concluída ou excluída, só volta na segunda seguinte; se a
  da semana anterior ainda estiver aberta, não cria outra). Critério: o DataJud respondeu por completo e não trouxe o
  processo (“sem dados públicos”), ou trouxe com nível de sigilo maior que zero. Não entram no alerta de prazos.
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

## Clientes

Para renomear a aba, troque a constante `NOME_QUADRO` no começo de `static/quadro.js`.

- **Aniversário** do cliente (campo no card): a Agenda mostra **“Parabenizar <cliente>”** todo ano nesse dia, com
  caixinha de feito (vale só para aquele ano; no ano seguinte aparece de novo). Quem nasceu em 29/02 é lembrado em 28/02
  nos anos comuns. O card mostra o dia e destaca quando faltam 7 dias ou menos.

- Kanban de clientes com o mesmo visual da agenda: **5 colunas** que nascem sem nome. Clique em “Nomear coluna” para
  dar o nome (ex.: Trabalhista, Pro bono); clique de novo para renomear. Enter salva, Esc desiste.
- **+ Adicionar cliente** no pé de cada coluna. O card nasce com a checklist padrão do tipo e tem um **tipo**: *Com processo*
  (escolha entre os processos cadastrados, pelo número ou pelo nome da parte, ou digite um número CNJ), *Petição
  inicial* ou *Preventivo / consultoria* (sem processo). Quando virar processo, abra o card, mude o tipo e vincule.
- **Prazo fatal do card**: com processo, é o **processual** — vem sozinho da agenda (o próximo prazo em aberto daquele
  processo; sem prazo futuro, o vencido mais recente ainda aberto). Sem processo (petição inicial, preventivo), é um
  **interno** que você digita no card (o quê, data e, se quiser, horário); ele aparece na agenda com destaque leve e
  entra no aviso de prazos ao abrir o app.
- Arraste os cards entre colunas ou dentro da mesma coluna (uma linha azul mostra onde vão cair).
- Expandido, o card mostra o processo (clique para abrir), as partes e o próximo item da checklist; contraído, só o
  nome e o progresso. Mesmo botão **Contrair todos / Expandir todos** da agenda.

## Agenda (calendário único)

Um calendário só, por mês ou por semana, com feriados. Junta, sem copiar nada (marcar feito vale na origem):

- **Monitoramento**: prazo fatal (cor da urgência) e data interna (contorno tracejado) das tarefas, e os itens com data
  das checklists delas;
- **Checklists dos clientes**: itens com data dos cards de Clientes e o prazo fatal interno do card;
- **Aniversários**: “Parabenizar <cliente>”, todo ano;
- **Financeiro**: cada parcela (e a entrada) aparece **1 dia depois do vencimento**, para conferir se foi paga; a
  parcial aparece com o **valor que falta**. A caixinha lança o que falta com a data de hoje (para outro valor ou
  data, use o **+** no Financeiro); em atraso fica em vermelho.

Os botões acima do calendário ligam e desligam cada origem (o app lembra); o filtro de advogada vale para o
Monitoramento e as checklists. Dia com muita coisa mostra 4 itens e “+N mais”. Clicar num item abre a tarefa, o card
ou o lançamento de onde ele veio; dois cliques num dia criam uma tarefa de monitoramento com essa data.

## Financeiro

- **+ Novo lançamento**: nome do cliente (por extenso; sugere os nomes de Clientes), processo vinculado (opcional),
  valor total, valor da entrada, valor das parcelas, quantidade de parcelas, data de pagamento da entrada e
  vencimento da 1ª parcela. Os vencimentos são gerados **um por mês** a partir da 1ª data (31/01 → 28/02 → 31/03) e
  podem ser mudados um a um, inclusive o valor de cada parcela. Depois de mexer à mão, mudar a quantidade ou a 1ª data
  não apaga suas edições: aparece **Regerar vencimentos**.
- **Conferência**: entrada + parcelas tem de dar o total. Se não der, o formulário mostra a diferença e oferece
  **Usar … como total** ou **Recalcular parcelas** ((total − entrada) ÷ quantidade; os centavos que sobram vão para a
  última). Dá para salvar mesmo sem fechar, com confirmação.
- **Pagamento parcial**: o **+** em cada parcela (na tabela ou no lançamento) abre um mini-formulário com o valor pago
  e a data. Cada pagamento entra no **histórico** da parcela (não sobrescreve o anterior) e pode ser editado (✎) ou
  excluído (✕). A parcela mostra “pago R$ X de R$ Y — falta R$ Z” e fica **pendente** (nada pago), **parcial** ou
  **paga** (pago ≥ valor). A parcial continua aberta: o restante segue no vencimento, no atraso e na Agenda.
- **Paga**: caixinha em cada parcela (no lançamento, na tabela ou na Agenda). Marcar lança o que falta com a data de
  hoje; desmarcar apaga os pagamentos da parcela (com mais de um, pergunta antes). Entrada com data de hoje ou passada
  já nasce paga nessa data (dá para desmarcar). O saldo (recebido / falta receber) é recalculado na hora.
- **Cliente inadimplente**: caixa no lançamento, “Não contabilizar na renda do mês”. Marcada, as parcelas saem do
  *a receber no mês*, do previsto, do *em atraso* e do selo do menu, mas continuam no cadastro e no *total a receber*.
  O nome ganha o selo “inadimplente” no Financeiro e no card de Clientes de mesmo nome. Desmarcar volta tudo ao normal.
- **Painel**: cards com *a receber no mês* (com ‹ › para outros meses; parcial conta pelo que falta),
  *recebido no mês* e *recebido no ano* (pela data de cada pagamento), *total a receber* e *em atraso*; os blocos
  **Em atraso** (parcelas vencidas e não pagas, com valor e dias de atraso, por cliente), **Inadimplentes** (os
  clientes marcados, com o valor em atraso de cada um) e **Próximas parcelas**. Embaixo, a tabela de **Parcelas** (Todas / Pendentes / Pagas / Atrasadas, busca e
  “só vencimentos do mês”) e a visão **Por cliente** (total, recebido, quanto falta, em atraso e próximo vencimento).
- Valores em R$ (digite `1500`, `1.500` ou `1.500,00`); guardados em centavos, sem erro de arredondamento.

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
| `ocultar_cooperacao` | `true` (padrão) esconde os processos em cooperação; `false` mostra (também muda em ⚙) |
| `advogados_cooperacao` | advogados de cooperação: `nome`, `oab_numero`, `oab_uf` (padrão: Jessica Delmoni, 13043/AL; edite em ⚙) |

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
            agenda: prazos.py (calendário e cálculo), extrair.py (regex), agenda.py, rotas_agenda.py;
            quadro de clientes: quadro.py (inclui aniversários), rotas_quadro.py; checklist.py (itens, "feito" e equipe);
            financeiro: financeiro.py, rotas_financeiro.py
static/     interface (HTML/CSS/JS puro; app.js = Andamentos e menu lateral; agenda.js = Monitoramento;
            quadro.js = Clientes; calendario.js = Agenda; financeiro.js = Financeiro;
            checklist.js = editor de checklist reutilizável)
tests/      testes do cálculo de prazos, da detecção no texto, da agenda, do quadro e do financeiro
db/         banco SQLite (processos.sqlite3) — apague para recomeçar do zero; não vai para o git.
            Antes de mudar a estrutura do banco, o app guarda uma cópia (processos.sqlite3.bak-AAAAMMDD)
logs/       app.log (erros de rede e dos tribunais)
config.json configuração editável
checklists_padrao.txt  checklists padrão por modelo: [processo] e [preventivo] (um item por linha)
```
