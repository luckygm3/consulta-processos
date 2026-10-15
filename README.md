# Meus processos

Os processos das advogadas (uma ou mais OABs) em todos os tribunais, com prazos, clientes, agenda e financeiro.
Os dados ficam no **Supabase** (banco Postgres na nuvem) e só entra quem faz **login com e-mail e senha** e está
cadastrada como advogada (hoje: Beatriz e Kazuza). O app roda no computador (http://127.0.0.1:8000) ou hospedado na
**Vercel** (um endereço https para abrir de qualquer lugar, inclusive no celular). Os dois podem ser usados ao mesmo
tempo, porque o banco é o mesmo. Não precisa de certificado digital.

## Como funciona

```
navegador ── login (e-mail e senha, chave pública "anon") ──► Supabase Auth
   │ token da sessão em cada chamada
   ▼
app (FastAPI: run.py no computador, ou função na Vercel) ── confere o token ──► Supabase Auth
   │ conecta como "authenticated", com o token de quem está logada
   ▼
Postgres do Supabase ── RLS: só as advogadas cadastradas leem e gravam
```

- A tela só conhece a URL do projeto e a chave pública **anon** (feita para ficar no navegador).
- A senha do banco (`DATABASE_URL`) fica só no servidor (`.env` ou variáveis da Vercel). A chave `service_role`
  (secret) não é usada em lugar nenhum.
- **RLS em todas as tabelas**: as duas advogadas veem e editam tudo; qualquer outra conta, mesmo logada, não vê nada
  (a tela mostra “Esta conta não tem acesso”). O filtro por advogada continua sendo da tela, não de permissão.

## 1. Criar o projeto no Supabase (uma vez só)

1. Crie uma conta em https://supabase.com e clique em **New project**. Nome: `processos`. **Database Password**:
   gere uma senha forte e guarde (vai no `.env`). **Region**: *South America (São Paulo)*.
   Nas opções de segurança: **desmarque “Enable Data API”** (o app não usa a API REST automática: a tela só usa o
   login, e o servidor fala direto com o banco; desligada, a chave anon não abre caminho nenhum até as tabelas) e
   **marque “Enable automatic RLS”** (rede de proteção: tabela nova já nasce com RLS). “Automatically expose new
   tables” só aparece com a Data API ligada; se ligar a Data API um dia, deixe essa desmarcada.
2. **SQL Editor → New query**: cole o arquivo [`supabase/schema.sql`](supabase/schema.sql) inteiro e clique em
   **Run**. Ele cria as tabelas, a RLS (políticas) e os gatilhos. Pode rodar de novo sem estragar nada: é assim que
   se aplica uma versão nova do schema.
3. **Authentication → Sign In / Providers**: deixe **Email** ligado e **desligue “Allow new users to sign up”**
   (ninguém cria conta sozinho).
4. **Authentication → Users → Add user → Create new user**: e-mail e senha da Beatriz, com **Auto Confirm User**
   marcado. Repita para a Kazuza. (Cada uma pode trocar a senha depois em “Esqueci minha senha”.)
5. **Authentication → URL Configuration**: em *Site URL*, o endereço do app (o da Vercel, quando existir; até lá,
   `http://127.0.0.1:8000`). Em *Redirect URLs*, adicione `http://127.0.0.1:8000/**`, `http://localhost:8000/**` e,
   quando existir, `https://SEU-APP.vercel.app/**`. É para onde leva o link do e-mail “Esqueci minha senha”.
6. **Quem pode entrar** = tabela `advogadas` com o e-mail do login. **Com a migração** (seção 3), o `--email` já faz
   isso. **Sem migração** (banco novo, do zero), rode no SQL Editor, com os e-mails de verdade:
   ```sql
   insert into public.advogadas (nome, oab_numero, oab_uf, cor, email) values
     ('Beatriz Daffara', '130678', 'PR', '#41ecb9', 'email-da-beatriz@exemplo.com'),
     ('Kazuza',          '130152', 'PR', '#c144ee', 'email-da-kazuza@exemplo.com')
   on conflict (oab_numero, oab_uf) do update set email = excluded.email;
   ```
   O login é ligado à advogada pelo e-mail, sozinho, quando o e-mail é cadastrado ou quando a conta é criada (o que
   vier por último).
7. **Connect** (botão no topo do projeto) ou **Project Settings → API Keys**: copie a *Project URL*, a chave pública
   (**anon**, ou a nova *publishable*) e as *connection strings* **Transaction pooler** (porta 6543) e
   **Session pooler** (porta 5432), trocando `[YOUR-PASSWORD]` pela senha do passo 1. Elas vão no `.env`.

## 2. Configurar o `.env`

Copie `.env.example` para `.env` (na mesma pasta do app) e preencha:

| variável | o que é | quem usa |
|---|---|---|
| `SUPABASE_URL` | Project URL (`https://….supabase.co`) | tela (login) e servidor |
| `SUPABASE_ANON_KEY` | chave pública anon/publishable | tela (login) e servidor |
| `DATABASE_URL` | connection string *Transaction pooler* (porta 6543) | servidor |
| `MIGRACAO_DATABASE_URL` | connection string *Session pooler* (porta 5432) | só o script de migração |
| `DATAJUD_API_KEY` | opcional: chave do DataJud (tem prioridade sobre a salva em ⚙) | servidor |

O `.env` está no `.gitignore`: **nunca** vai para o GitHub. Não cole a `service_role`/secret key em lugar nenhum.

## 3. Migrar os dados atuais (uma vez só)

O script copia tudo do banco antigo (`db/processos.sqlite3`) para o Supabase: processos, publicações, movimentos,
tarefas e checklists, clientes, lançamentos, parcelas e pagamentos, feriados, tipos de ato, equipe, ajustes da tela e
advogados de cooperação. Os ids são mantidos, então os vínculos continuam iguais. As checklists, que eram JSON dentro
da tarefa ou do card, viram linhas da tabela `checklist_itens`.

1. Faça a seção 1 (passos 1–5) e o `.env`. Use o computador onde o app rodava (onde está a pasta `db/`) e abra o
   `run.bat` uma vez, para criar o ambiente `.venv` (ele vai avisar se faltar algo no `.env`).
2. Simule. Faz tudo, confere e desfaz (troque pelos e-mails de login reais):
   ```
   .venv\Scripts\python scripts\migrar_para_supabase.py --simular --email 130678/PR=email-da-beatriz@exemplo.com --email 130152/PR=email-da-kazuza@exemplo.com
   ```
   (no Mac/Linux: `.venv/bin/python scripts/migrar_para_supabase.py …`)
3. Se terminar com “tudo conferido”, rode o mesmo comando **sem** `--simular`.

- É tudo numa transação só. A conferência compara tabela por tabela, os itens de checklist e a soma das parcelas: se
  algo falhar ou não bater, nada fica gravado no Supabase.
- Só roda com o Supabase vazio, para não duplicar nada (ou com `--substituir`, abaixo).
- O arquivo SQLite não é alterado. Guarde a pasta `db/` como backup.

### Trazer os dados de outro computador

Quando quem usa a versão antiga no dia a dia é outro computador, os dados **dele** é que precisam ir para o
Supabase, e isso deve acontecer **antes** da troca de versão lá. O `git pull` não apaga nada: a pasta `db` e o
`config.json` daquele computador nunca vão para o git. Mas a versão nova só mostra o que está no Supabase.

1. No computador dela, **feche o app** (a janela preta). A partir daqui, ninguém usa mais a versão antiga.
2. Copie a **pasta `db` inteira** e o **`config.json`** (por ZIP, pendrive ou Drive). A pasta inteira é necessária
   porque o que foi registrado por último pode estar só no `processos.sqlite3-wal`. Guarde também uma cópia de
   segurança.
3. No computador que tem o `.env`, extraia **fora da pasta do projeto** (ex.: `C:\dados-beatriz\`) e simule:
   ```
   .venv\Scripts\python scripts\migrar_para_supabase.py --simular --substituir --sqlite C:\dados-beatriz\db\processos.sqlite3 --config C:\dados-beatriz\config.json --email 130678/PR=EMAIL-DA-BEATRIZ --email 130152/PR=EMAIL-DA-KAZUZA
   ```
   `--substituir` troca o que já estiver no Supabase (ex.: uma migração de teste) pelo conteúdo desse banco, numa
   transação só: se algo falhar ou não conferir, o Supabase fica como estava. Cuidado: ele apaga também o que já
   tiver sido cadastrado direto na versão nova.
4. Conferido (“tudo conferido”), rode o mesmo comando **sem** `--simular`.
5. Só então, no computador dela: `git pull` (ou o ZIP novo numa pasta nova), o `.env` e o `run.bat`. Ou ela passa a
   usar o endereço da Vercel.

**Aviso automático.** A migração guarda no Supabase uma “impressão digital” do banco copiado. O app novo, rodando num
computador que ainda tem a pasta `db`, compara com ela. Se o conteúdo for diferente (banco que não foi migrado, cópia
feita sem o `-wal` ou a versão antiga usada depois da migração), aparece uma faixa vermelha em todas as telas. Nesse
caso, não apague a pasta: refaça a migração com o banco atualizado. Num computador cujos dados não importam (de
teste), renomeie a pasta `db` para `db-antigo` e a faixa some.

Nunca rode `git clean -x` (ou `-X`) na pasta do app: ele apaga os arquivos ignorados pelo git, e a pasta `db` é um
deles.

## 4. Rodar no computador

1. Baixe o código: no GitHub, **Code → Download ZIP** e extraia numa pasta (ex.: Documentos). Não rode de dentro do
   ZIP. Quem tem git pode usar `git clone`.
2. Coloque o `.env` na pasta (seção 2).
3. **Windows:** dois cliques em **`run.bat`**. Se aparecer “O Windows protegeu o computador”, clique em
   **Mais informações → Executar assim mesmo**. Se não houver Python, o `run.bat` pergunta se pode instalar:
   responda **S**.
   **Mac:** instale o Python de https://www.python.org/downloads/ (o que vem no Mac é antigo demais) e dê dois cliques
   em **`abrir-no-mac.command`**. Na primeira vez o Mac bloqueia: vá em **Ajustes do Sistema → Privacidade e
   Segurança**, role até o fim e clique em **Abrir Mesmo Assim**. Outra opção é abrir o Terminal, digitar `sh ` e
   arrastar o `run.sh` para a janela.
   **Linux:** `sh run.sh`.
4. Na primeira vez ele prepara tudo (1–3 min, precisa de internet) e abre http://127.0.0.1:8000 na tela de login.
   **Deixe a janela preta (Terminal) aberta** enquanto usa; para encerrar, feche-a.

## 5. Hospedar na Vercel

1. Com o código no GitHub (o `.env` não vai junto), entre em https://vercel.com → **Add New → Project** e importe o
   repositório. *Framework Preset*: **Other**. Não precisa mexer em build nem output: o `vercel.json` já configura
   a função Python (`api/index.py`), a região São Paulo (`gru1`) e até 60 s por requisição.
2. Em **Environment Variables**, coloque `SUPABASE_URL`, `SUPABASE_ANON_KEY` e `DATABASE_URL` (*Transaction pooler*,
   porta 6543). `DATAJUD_API_KEY` é opcional; `MIGRACAO_DATABASE_URL` não é usada lá.
3. **Deploy**. Abra `https://SEU-APP.vercel.app` e entre.
4. No Supabase, em **Authentication → URL Configuration**, coloque esse endereço em *Site URL* e em *Redirect URLs*.

Cada `git push` na `main` publica sozinho uma versão nova. Mudou o `supabase/schema.sql`? Rode-o de novo no SQL
Editor antes (ou junto) do deploy.

- **Atualizar tudo** roda em passos de até ~45 s (por causa do limite da Vercel), e a tela encadeia os passos sozinha.
  O ponto onde parou fica no banco: fechar a aba só pausa, e “Atualizar tudo” continua dali. Se duas abas clicarem
  ao mesmo tempo, uma acompanha a outra.
- A região `gru1` (São Paulo) é importante: o DJEN e o DataJud às vezes recusam acessos de fora do Brasil.
- Erros de rede e dos tribunais: no computador, em `logs/app.log`; na Vercel, em **Project → Logs**.
- Planos: o *Hobby* (grátis) da Vercel é para uso pessoal e não comercial; para o escritório, o indicado é o *Pro*.
  No Supabase, o plano *Free* pausa o projeto depois de uma semana sem nenhum acesso (reative no painel).

## Acesso e senhas

- **Sair**: botão no pé do menu lateral (mostra o e-mail de quem está logada).
- **Esqueci minha senha** (na tela de login): chega um e-mail com um link; ao voltar pelo link, a tela pede a senha
  nova. Pelo painel: **Authentication → Users → ⋯ → Send password recovery**.
- **Incluir uma advogada**: crie a usuária (seção 1, passo 4) e cadastre a linha dela em `advogadas` (passo 6). A
  OAB dela passa a ser buscada no DJEN na próxima atualização.
- **Tirar o acesso**: `update public.advogadas set email = null where oab_numero = '…';` ou apague a usuária em
  Authentication → Users. Os processos dela continuam no banco.

### As duas usando ao mesmo tempo

- Ao voltar para a aba (ou para a janela) do app, a tela aberta recarrega sozinha e mostra o que a outra fez. Não
  recarrega com um card, tarefa ou lançamento aberto, nem com algo sendo digitado.
- Se as duas abrirem o **mesmo** card, tarefa ou lançamento e uma salvar primeiro, quem salvar depois vê o aviso
  “foi alterado por outra pessoa (ou em outra aba) enquanto você editava”, em vez de apagar sem saber o que a outra
  fez. **OK** salva mesmo assim (o que a outra mudou se perde); **Cancelar** não salva e deixa o que foi digitado no
  diálogo (feche e abra de novo para ver a versão atual). Vale também para um item da checklist marcado na Agenda e
  para um pagamento lançado na tabela do Financeiro enquanto o diálogo estava aberto.
- Mexer em itens diferentes ao mesmo tempo não dá aviso nenhum.

## Chave do DataJud

O DataJud (CNJ) fornece classe, assuntos, órgão julgador e as movimentações. A chave é pública, gratuita e igual
para todo mundo; **a atual já vem no `config.json`**. O CNJ troca a chave de tempos em tempos. Se aparecer
“Chave do DataJud recusada”:

1. Abra https://datajud-wiki.cnj.jus.br/api-publica/acesso
2. Copie o texto que aparece depois de `APIKey` (uma sequência longa terminada em `==`).
3. No app, clique em **⚙** → cole em “Chave pública do DataJud” → **Salvar**. Fica guardada no banco e vale no
   computador e na Vercel.

(Alternativa: `DATAJUD_API_KEY=...` no `.env` ou nas variáveis da Vercel, que tem prioridade sobre as outras.)

O DJEN (publicações) não precisa de chave.

## Uso

O **menu lateral** tem as cinco telas: **Andamentos Processuais**, **Monitoramento**, **Clientes**,
**Agenda** e **Financeiro**, além de **Configurações** no pé. O selo vermelho no Monitoramento conta as sugestões
aguardando aprovação; no Financeiro, parcelas em atraso. **Recolher** deixa só os ícones (o app lembra);
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

## Dados interligados: processo → cliente → checklist → Agenda

- **Todo processo tem um cliente.** Processo captado pela OAB da Beatriz ou da Kazuza (DJEN, em “Atualizar tudo”) ou
  incluído em “Adicionar processos” já ganha um card em **Clientes**, no topo da 1ª coluna, com o nome das partes como
  nome provisório e o selo **completar dados**. É um card por processo, mesmo que o cliente se repita (quem tem um
  processo trabalhista e outro de família tem dois cards). Processo em cooperação não ganha card. Card excluído não
  volta sozinho (só se uma tarefa daquele processo for aprovada no Monitoramento, para o prazo não se perder).
- **Tarefa do sistema passa pelo Monitoramento.** Prazos e audiências lidos das publicações e a verificação semanal
  dos processos sigilosos chegam como **sugestões**. **Aprovar** põe a tarefa no checklist do cliente (com a data, o
  horário e a responsável), e daí ela aparece na Agenda. **Rejeitar** tira do Monitoramento (e a publicação não sugere
  de novo). O que você cria (“+ Nova tarefa”, “+ Tarefa / prazo” no painel do processo, ou um item digitado no card)
  vai direto para o cliente, sem aprovação.
- **Na primeira abertura depois desta versão** (uma vez só): cada processo já cadastrado ganha o seu card, e as
  tarefas do Kanban antigo do Monitoramento vão para os clientes. As sugeridas continuam no Monitoramento, aguardando
  aprovação. As já confirmadas (A fazer, Em andamento, Aguardando) entram aprovadas no checklist do cliente do processo.
  Uma tarefa criada à mão sem processo, ou com checklist própria, vira um card de cliente com aquela checklist. As
  concluídas ficam guardadas no banco, fora de vista.

## Monitoramento (sugestões para aprovar)

> **Prazos calculados automaticamente são sugestões. Confirme sempre no processo e no calendário do tribunal.**

Lista de passagem: só o que o sistema sugeriu e ainda espera a sua decisão, agrupado por data (vencidos primeiro).

- Cada linha mostra a urgência, o prazo (fatal e interno), o processo, as partes, a responsável e **para o checklist
  de qual cliente ela vai** ao ser aprovada. **✓ Aprovar**, **Editar** (ajustar título, data, horário, responsável,
  recalcular o prazo ou escolher outro cliente antes de aprovar) e **Rejeitar**. Em lote: marque as caixinhas (ou
  “todas”) e use **Aprovar selecionadas** / **Rejeitar selecionadas**. Filtros por advogada e por processo.
- Sugestão sem processo precisa de um cliente escolhido (em Editar) para ser aprovada.
- **Feriados** e **Tipos de ato** ficam escondidos: aparecem ao passar o mouse na barra (ou ao tocar no **⋯**).
- Cores por urgência: vermelho = vencido; laranja = vence hoje/próximo dia útil; amarelo = até 5 dias úteis; verde = folgado.
- **Prazo fatal: processual × interno.** Pontinho **cheio** = processual (veio do processo: publicação do DJEN,
  “Verificar prazos” ou “Calcular prazo”); pontinho **vazado** = interno (data posta à mão).
- **Processos sigilosos**: toda segunda-feira, cada processo que o DataJud não detalha ganha a sugestão
  “Verificar processo sigiloso nº …” (sem duplicar: rejeitada, ou aprovada e marcada como feita, só volta na segunda
  seguinte; se a da semana anterior ainda estiver aberta, não cria outra). Aprovada de novo, reaproveita o item da
  semana anterior no checklist do cliente, em vez de empilhar um por semana. Critério: o DataJud respondeu por completo
  e não trouxe o processo (“sem dados públicos”), ou trouxe com nível de sigilo maior que zero. Não entram no alerta
  de prazos.
- **Verificar prazos** (sem IA): lê as publicações do DJEN ainda não analisadas, procura expressões como “prazo de
  quinze (15) dias”, “em 48 horas”, “5 dias úteis”, “manifeste-se”, “contestar”, “intime-se para”, reconhece o ato
  (contestação, apelação, embargos de declaração…) e cria sugestões com o trecho original, o link da publicação e a
  memória de cálculo. Detecções incertas vêm marcadas “conferir manualmente”. Por padrão, publicações cujo prazo já
  venceu não viram sugestão (há uma opção para incluí-las). Audiências com data no texto também viram sugestão.
- **Tipos de ato**: tabela editável (palavras-chave → nome do ato e prazo padrão). O prazo padrão só é usado quando o
  texto não traz o número de dias; sem nenhuma indicação, vale o CPC art. 218 §3º (5 dias).
- **Feriados**: tabela editável por tribunal ou comarca (feriado municipal: preencha a comarca como aparece no nome da
  vara). Vem pré-preenchida para o ano passado e os próximos dois anos — **confira com o calendário oficial do tribunal**.
- Ao abrir o app, uma faixa avisa quantos prazos (aprovados ou ainda sugeridos) vencem hoje/amanhã, quantos estão
  vencidos e quantas sugestões esperam aprovação.

## Clientes

Para renomear a aba, troque a constante `NOME_QUADRO` no começo de `static/quadro.js`.

- **Aniversário** do cliente (campo no card): a Agenda mostra **“Parabenizar <cliente>”** todo ano nesse dia, com
  caixinha de feito (vale só para aquele ano; no ano seguinte aparece de novo). Quem nasceu em 29/02 é lembrado em 28/02
  nos anos comuns. O card mostra o dia e destaca quando faltam 7 dias ou menos.

- Kanban de clientes com o mesmo visual da agenda: **5 colunas** que nascem sem nome. Clique em “Nomear coluna” para
  dar o nome (ex.: Trabalhista, Pro bono); clique de novo para renomear. Enter salva, Esc desiste.
- **Cards criados sozinhos** (um por processo, veja “Dados interligados”) nascem sem checklist e com o selo
  **completar dados**: abra, confira o nome do cliente, preencha o que faltar e salve (o selo sai). **+ Inserir
  checklist padrão** traz a lista do tipo do card.
- **+ Adicionar cliente** no pé de cada coluna. O card nasce com a checklist padrão do tipo e tem um **tipo**: *Com processo*
  (escolha entre os processos cadastrados, pelo número ou pelo nome da parte, ou digite um número CNJ), *Petição
  inicial* ou *Preventivo / consultoria* (sem processo). Quando virar processo, abra o card, mude o tipo e vincule.
- **Checklist (estilo Trello)**. Cada item tem texto, feito/não feito e, opcionais, **data**, **horário** (só com data)
  e **responsável**: clique no ícone do item (ou nas etiquetas dele) para abrir esses campos. Arraste pela alça para
  reordenar; edite, exclua e adicione itens. Progresso discreto (“3/17”).
  - As tarefas aprovadas no Monitoramento (e as de “+ Nova tarefa”) são itens como os outros, com uma etiqueta do
    tipo (prazo, audiência, tarefa). Dá para mudar a data ou o texto no card; o prazo do card acompanha.
  - **Responsáveis**: as advogadas e as pessoas da **Equipe** (⚙ Configurações → Equipe; vale na hora).
  - **Na Agenda**: todo item com data aparece no dia/horário dele, como “Elaboração do Mérito · Fulano”. A caixinha
    marca como feito: é o mesmo item do card (nada é copiado), então vale nos dois lugares. Itens sem data ficam só
    dentro do card.
  - Se uma etapa comum tiver data depois do prazo fatal do card, aparece um aviso discreto (não bloqueia).
- **Checklists padrão** (`checklists_padrao.txt`, um arquivo só): seção `[processo]` (as 17 etapas do contencioso) e
  `[preventivo]` (consultoria). O tipo do card escolhe a lista (petição inicial usa a de processo). Edite o arquivo
  para trocar as listas; vale para os próximos cards.
- **Prazo fatal do card**: com processo, é o **processual**: o próximo prazo em aberto daquele processo (item de prazo
  ainda não feito no checklist, ou sugestão ainda no Monitoramento, marcada “aguardando aprovação”); sem prazo futuro,
  o vencido mais recente ainda aberto. Sem processo (petição inicial, preventivo), é um **interno** que você digita no
  card (o quê, data e, se quiser, horário); ele aparece na agenda com destaque leve e entra no aviso de prazos ao abrir
  o app.
- O card mostra quantas sugestões daquele processo ainda esperam no Monitoramento (clique para ir até elas). No painel
  do processo, o botão com o nome do cliente abre o card.
- Arraste os cards entre colunas ou dentro da mesma coluna (uma linha azul mostra onde vão cair).
- Expandido, o card mostra o processo (clique para abrir), as partes e o próximo item da checklist; contraído, só o
  nome e o progresso. Mesmo botão **Contrair todos / Expandir todos** da agenda.

## Agenda (calendário único)

Um calendário só, por mês ou por semana, com feriados. Junta, sem copiar nada (marcar feito vale na origem):

- **Prazos e tarefas**: as tarefas dos clientes (aprovadas no Monitoramento ou criadas em “+ Nova tarefa”), na cor da
  urgência. Sugestões ainda não aprovadas não aparecem;
- **Checklists dos clientes**: os outros itens com data dos cards e o prazo fatal interno do card;
- **Aniversários**: “Parabenizar <cliente>”, todo ano;
- **Financeiro**: cada parcela (e a entrada) aparece **1 dia depois do vencimento**, para conferir se foi paga; a
  parcial aparece com o **valor que falta**. A caixinha lança o que falta com a data de hoje (para outro valor ou
  data, use o **+** no Financeiro); em atraso fica em vermelho.

Os botões acima do calendário ligam e desligam cada origem (o app lembra); o filtro de advogada vale para as tarefas e
as checklists. Dia com muita coisa mostra 4 itens e “+N mais”. Clicar num item abre o card ou o lançamento de onde ele
veio.

- **+ Nova tarefa** (ou dois cliques num dia, que já trazem a data): escolha o cliente (ou o processo, que escolhe o
  cliente dele), título, tipo, data, horário e responsável. Vai direto para o checklist do cliente. O quadro
  “Calcular prazo” calcula o fatal a partir da disponibilização. No painel de um processo, **+ Tarefa / prazo** faz o
  mesmo, já com o processo.
- **Exportar .ics**: arquivo para importar no Google Agenda (Configurações → Importar e exportar), com as tarefas dos
  clientes ainda não feitas e os prazos internos dos cards (só da advogada do filtro, se houver).

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

Testes do cálculo e da detecção: veja a seção **Testes**.

## Testes

```
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m unittest discover -s tests -t . -v
```

(no Mac/Linux: `.venv/bin/python …`). O `requirements-dev.txt` instala o **pgserver**, um Postgres local onde os
testes montam um “Supabase de mentira” (papéis `anon`/`authenticated`, `auth.users`, `auth.uid()`) e rodam o
`supabase/schema.sql` de verdade. Assim testam também a RLS, a migração e a sincronização em passos, sem tocar no
Supabase real. Sem o pgserver, os testes de banco são pulados.

## Configuração

O que muda pela tela (**⚙**) fica guardado no banco e vale em qualquer lugar onde o app rode: nome e cor das
advogadas, chave do DataJud, dias da primeira busca, ocultar processos em cooperação, lista de advogados de
cooperação e equipe. Quem pode entrar (e-mail e OAB das advogadas) só muda pelo SQL Editor (seção 1, passo 6).

O `config.json` guarda os padrões:

| campo | significado |
|---|---|
| `datajud_api_key` | chave pública do DataJud (padrão; a salva em ⚙ e a `DATAJUD_API_KEY` do ambiente têm prioridade) |
| `backfill_dias` | quantos dias buscar na primeira atualização (padrão 180; também em ⚙) |
| `janela_dias` | tamanho de cada consulta ao DJEN (padrão 30) |
| `buscar_tambem_por_nome` | também busca por nome, além da OAB (padrão `false`; nos testes os resultados foram iguais). Só vale para nomes com nome e sobrenome |
| `porta` | porta local (padrão 8000) |
| `prazos_regra_publicacao` | `"djen"` (publicação = 1º dia útil após a disponibilização, padrão) ou `"disponibilizacao"` |
| `prazos_dias_internos` | data interna sugerida: quantos dias úteis antes do prazo fatal (padrão 2) |
| `prazos_contagem_padrao` | `"uteis"` (padrão) ou `"corridos"` |
| `advogadas` | só para a migração: lista usada se o banco antigo não tiver a tabela de advogadas |

## Limitações

- A busca automática só encontra processos com **publicação no DJEN** em que a OAB aparece. Processos sem intimação
  recente (ou de tribunais/sistemas que não publicam no DJEN) precisam ser adicionados manualmente.
- **Sem dados públicos (possível segredo de justiça)**: o DataJud não retorna processos sigilosos. Também pode acontecer
  com processos muito recentes, que o CNJ ainda não indexou (o DataJud costuma ter alguns dias ou semanas de atraso).
- O DataJud é consultado no tribunal de origem do número CNJ. Um recurso que subiu para STJ/TST aparece com os dados do
  tribunal de origem.
- STF e conselhos (CNJ, CJF, CSJT) não publicam no DataJud.
- As duas APIs são públicas e às vezes ficam lentas ou sobrecarregadas (erros 429/500/504). O app repete a consulta
  automaticamente. Um lote que não responde em 3 passos seguidos aparece em “problemas nesta atualização” e é tentado
  de novo na próxima vez.
  Sob carga, o DataJud às vezes responde “pela metade” (parte do índice falha); nesse caso o processo **não** é marcado
  como sem dados, e sim como “não respondeu por completo”, e é consultado de novo na próxima atualização.
- Uma atualização completa leva de 3 a 6 minutos (o DataJud demora de 5 a 40 s por consulta); com o DataJud
  sobrecarregado, mais.
- O DataJud não informa nomes das partes; elas vêm das publicações do DJEN.

## Arquivos

```
app/        código (FastAPI): djen.py, datajud.py, cnj.py, sync.py (atualização em passos), db.py (Postgres),
            auth.py (confere o login), tempo.py (limite de tempo dos passos), texto.py, main.py,
            banco_antigo.py (lê o SQLite antigo com o -wal e avisa se ele tem dados fora do Supabase);
            agenda: prazos.py (calendário e cálculo), extrair.py (regex), agenda.py, rotas_agenda.py;
            quadro de clientes: quadro.py (inclui aniversários), rotas_quadro.py; checklist.py (itens, "feito" e equipe);
            interligar.py (cliente de cada processo; sugestão aprovada vira item do checklist; migração do Kanban antigo);
            financeiro: financeiro.py, rotas_financeiro.py
static/     interface (HTML/CSS/JS puro; auth.js = login; app.js = Andamentos e menu lateral; agenda.js = Monitoramento;
            quadro.js = Clientes; calendario.js = Agenda; financeiro.js = Financeiro;
            checklist.js = editor de checklist reutilizável)
supabase/   schema.sql: tabelas, RLS e gatilhos (colar no SQL Editor)
scripts/    migrar_para_supabase.py: copia o banco antigo (SQLite) para o Supabase
api/        index.py: entrada da Vercel (o vercel.json manda tudo para ela)
tests/      testes do cálculo de prazos, da detecção no texto, da agenda, do quadro, dos dados interligados, do
            financeiro, do acesso (RLS), da migração e da sincronização
db/         banco antigo (SQLite), de antes do Supabase: só a origem da migração e backup; não vai para o git
            (renomeie para db-antigo num computador cujos dados não importam, para não ver o aviso vermelho)
logs/       app.log (erros de rede e dos tribunais), só quando roda no computador
.env        chaves e senha do banco (copie de .env.example); nunca vai para o git
config.json padrões editáveis
checklists_padrao.txt  checklists padrão por modelo: [processo] e [preventivo] (um item por linha)
```
