-- Schema do banco SQLite antigo (versão 8: pagamentos parciais, inadimplente, cooperação). Só para testes.
CREATE TABLE IF NOT EXISTS processos (
    numero            TEXT PRIMARY KEY,      -- 20 dígitos
    tribunal          TEXT,
    alias             TEXT,                  -- índice do DataJud (ex.: tjpr)
    origem            TEXT,                  -- 'djen' ou 'manual'
    orgao             TEXT,
    classe            TEXT,
    assuntos          TEXT,                  -- JSON (lista de nomes)
    grau              TEXT,
    data_ajuizamento  TEXT,
    sistema           TEXT,
    instancias        TEXT,                  -- JSON com um resumo por grau retornado pelo DataJud
    partes            TEXT,                  -- JSON {"ativo": [...], "passivo": [...], "outros": [...]}
    datajud_status    TEXT,                  -- NULL, ok, sem_dados, erro, sem_alias
    datajud_msg       TEXT,
    datajud_em        TEXT,
    ult_mov_data      TEXT,
    ult_mov_texto     TEXT,
    ult_pub_data      TEXT,
    ult_pub_texto     TEXT,
    ult_atividade     TEXT,
    novidade_em       TEXT,                  -- quando algo novo foi capturado
    visto_em          TEXT,                  -- quando a advogada marcou como visto
    busca             TEXT,                  -- texto normalizado para busca
    criado_em         TEXT,
    cooperacao        INTEGER NOT NULL DEFAULT 0, -- 1 = consta advogado de cooperação (marcado a cada sincronização)
    cooperacao_manual INTEGER                -- marcação à mão (1/0), vale por cima da automática; NULL = automática
);
CREATE TABLE IF NOT EXISTS comunicacoes (
    hash              TEXT PRIMARY KEY,
    djen_id           INTEGER,
    numero            TEXT NOT NULL,
    tribunal          TEXT,
    orgao             TEXT,
    tipo              TEXT,
    tipo_documento    TEXT,
    classe            TEXT,
    data_disp         TEXT,                  -- YYYY-MM-DD
    texto             TEXT,                  -- texto limpo (sem HTML)
    texto_original    TEXT,                  -- original do DJEN, só quando era diferente
    link              TEXT,
    destinatarios     TEXT,                  -- JSON
    advogados         TEXT,                  -- JSON
    busca             TEXT,
    capturado_em      TEXT
);
CREATE INDEX IF NOT EXISTS ix_com_numero ON comunicacoes(numero, data_disp);
CREATE TABLE IF NOT EXISTS movimentos (
    chave             TEXT PRIMARY KEY,
    numero            TEXT NOT NULL,
    grau              TEXT,
    codigo            INTEGER,
    data_hora         TEXT,
    nome              TEXT,
    complementos      TEXT,
    orgao             TEXT,
    capturado_em      TEXT
);
CREATE INDEX IF NOT EXISTS ix_mov_numero ON movimentos(numero, data_hora);
CREATE TABLE IF NOT EXISTS meta (
    chave             TEXT PRIMARY KEY,
    valor             TEXT
);
CREATE TABLE IF NOT EXISTS sync_erros (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_id           TEXT,
    quando            TEXT,
    fonte             TEXT,
    tribunal          TEXT,
    mensagem          TEXT
);
CREATE TABLE IF NOT EXISTS advogadas (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    oab_numero        TEXT NOT NULL,
    oab_uf            TEXT NOT NULL,
    nome              TEXT,
    cor               TEXT,
    UNIQUE(oab_numero, oab_uf)
);
CREATE TABLE IF NOT EXISTS processo_advogada (     -- N:N: um processo pode ser de mais de uma advogada
    numero            TEXT NOT NULL,
    advogada_id       INTEGER NOT NULL,
    origem            TEXT,                  -- 'djen', 'manual' ou 'migracao'
    criado_em         TEXT,
    PRIMARY KEY (numero, advogada_id)
);
CREATE INDEX IF NOT EXISTS ix_pa_advogada ON processo_advogada(advogada_id);
CREATE TABLE IF NOT EXISTS comunicacao_advogada (  -- qual busca por OAB trouxe cada publicação
    hash              TEXT NOT NULL,
    advogada_id       INTEGER NOT NULL,
    PRIMARY KEY (hash, advogada_id)
);
CREATE TABLE IF NOT EXISTS feriados (            -- calendário forense editável (feriados, suspensões, recesso)
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio            TEXT NOT NULL,         -- YYYY-MM-DD (ou MM-DD se recorrente)
    fim               TEXT,                  -- idem; NULL = um dia só
    descricao         TEXT NOT NULL,
    tipo              TEXT NOT NULL,         -- feriado | suspensao | recesso | expediente_reduzido
    tribunais         TEXT,                  -- siglas separadas por vírgula; vazio = todos
    comarca           TEXT,                  -- vazio = todas; senão casa com o nome do órgão do processo
    recorrente        INTEGER DEFAULT 0,     -- 1 = repete todo ano (datas em MM-DD)
    origem            TEXT,                  -- 'padrao' (pré-preenchido, conferir) ou 'manual'
    ativo             INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_feriados_inicio ON feriados(inicio);
CREATE TABLE IF NOT EXISTS tipos_ato (           -- tabela editável: palavras-chave -> nome do ato e prazo padrão
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ordem             INTEGER,
    nome              TEXT NOT NULL,
    palavras          TEXT NOT NULL,         -- separadas por ';' (comparadas sem acento e em minúsculas)
    dias              INTEGER,
    contagem          TEXT,                  -- uteis | corridos
    justica           TEXT,                  -- vazio = qualquer; 'trabalho' = só TRT/TST
    ativo             INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS tarefas (             -- cartões da agenda/kanban
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo            TEXT NOT NULL,
    tipo              TEXT DEFAULT 'tarefa', -- prazo | tarefa | audiencia
    status            TEXT DEFAULT 'a_fazer',-- sugerido | a_fazer | andamento | aguardando | concluido | descartado
    numero            TEXT,                  -- processo vinculado (opcional)
    advogada_id       INTEGER,               -- responsável (NULL = as duas / a definir)
    prazo_fatal       TEXT,
    data_interna      TEXT,
    hora              TEXT,                  -- audiências
    prioridade        TEXT DEFAULT 'media',  -- alta | media | baixa
    observacoes       TEXT,
    checklist         TEXT,                  -- JSON [{"id", "texto", "feito", "data", "hora", "resp"}] (ver checklist.py)
    origem            TEXT DEFAULT 'manual', -- manual | djen | sigilo
    comunicacao_hash  TEXT,
    trecho            TEXT,                  -- trecho da publicação que gerou a sugestão
    calculo           TEXT,                  -- JSON: memória de cálculo
    conferir          INTEGER DEFAULT 0,     -- 1 = detecção incerta, conferir manualmente
    aviso             TEXT,
    criado_em         TEXT,
    atualizado_em     TEXT,
    concluido_em      TEXT,
    status_anterior   TEXT                   -- coluna de onde saiu ao ser concluída (para restaurar)
);
CREATE INDEX IF NOT EXISTS ix_tarefas_status ON tarefas(status, prazo_fatal);
CREATE TABLE IF NOT EXISTS tarefas_geradas (     -- tarefas automáticas já criadas: não recria, mesmo se excluída
    chave             TEXT PRIMARY KEY,      -- ex.: sigilo:<numero>:<segunda-feira da semana>
    criado_em         TEXT
);
CREATE TABLE IF NOT EXISTS quadro_colunas (      -- quadro de clientes: 5 colunas fixas, nomeadas por ela na tela
    id                INTEGER PRIMARY KEY,
    posicao           INTEGER NOT NULL,
    nome              TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS quadro_cards (        -- cards de cliente do quadro
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    coluna_id         INTEGER NOT NULL,
    posicao           INTEGER NOT NULL DEFAULT 0,
    titulo            TEXT NOT NULL,
    tipo              TEXT NOT NULL DEFAULT 'processo', -- processo | inicial (petição inicial) | preventivo (consultoria)
    numero            TEXT,                  -- processo vinculado (só quando tipo = processo)
    checklist         TEXT,                  -- JSON [{"id", "texto", "feito", "data", "hora", "resp"}]
    criado_em         TEXT,
    atualizado_em     TEXT,
    prazo_descricao   TEXT,                  -- prazo fatal interno (cards sem processo); o processual vem da agenda
    prazo_data        TEXT,
    prazo_hora        TEXT,
    aniversario       TEXT                   -- AAAA-MM-DD; gera "Parabenizar <cliente>" todo ano na Agenda
);
CREATE INDEX IF NOT EXISTS ix_quadro_cards ON quadro_cards(coluna_id, posicao);
CREATE TABLE IF NOT EXISTS pessoas (             -- responsáveis nos itens da checklist, além das advogadas
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    nome              TEXT NOT NULL,
    ativo             INTEGER DEFAULT 1,     -- 0 = removida da lista (itens antigos ainda mostram o nome)
    criado_em         TEXT
);
CREATE TABLE IF NOT EXISTS comunicacao_analise ( -- publicações já varridas por "Verificar prazos" (não duplica)
    hash              TEXT PRIMARY KEY,
    analisado_em      TEXT,
    resultado         TEXT,                  -- prazo | sem_prazo | ja_vencido | erro
    detalhe           TEXT
);
CREATE TABLE IF NOT EXISTS lancamentos (         -- financeiro: um contrato de honorários (entrada + parcelas)
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    cliente           TEXT NOT NULL,         -- nome por extenso
    numero            TEXT,                  -- processo vinculado (opcional)
    valor_total       INTEGER NOT NULL,      -- valores em centavos (sem erro de arredondamento)
    entrada           INTEGER NOT NULL DEFAULT 0,
    entrada_data      TEXT,
    valor_parcela     INTEGER NOT NULL DEFAULT 0,
    qtd_parcelas      INTEGER NOT NULL DEFAULT 0,
    observacoes       TEXT,
    inadimplente      INTEGER NOT NULL DEFAULT 0, -- 1 = fora da renda do mês (continua no total a receber)
    criado_em         TEXT,
    atualizado_em     TEXT
);
CREATE TABLE IF NOT EXISTS parcelas (            -- entrada (numero 0) e parcelas (1..n) de cada lançamento
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    lancamento_id     INTEGER NOT NULL,
    numero            INTEGER NOT NULL,
    vencimento        TEXT NOT NULL,         -- AAAA-MM-DD (o lembrete no calendário cai no dia seguinte)
    valor             INTEGER NOT NULL,      -- centavos
    pago              INTEGER NOT NULL DEFAULT 0, -- resumo da tabela pagamentos: 1 = quitada (pago >= valor)
    pago_em           TEXT                   -- data do pagamento que quitou
);
CREATE INDEX IF NOT EXISTS ix_parcelas ON parcelas(lancamento_id, numero);
CREATE INDEX IF NOT EXISTS ix_parcelas_venc ON parcelas(vencimento);
CREATE TABLE IF NOT EXISTS pagamentos (           -- histórico de pagamentos (parciais ou não) de cada parcela
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    parcela_id        INTEGER NOT NULL,
    valor             INTEGER NOT NULL,      -- centavos
    data              TEXT NOT NULL,         -- AAAA-MM-DD
    criado_em         TEXT
);
CREATE INDEX IF NOT EXISTS ix_pagamentos ON pagamentos(parcela_id);
CREATE TABLE IF NOT EXISTS lembretes_feitos (    -- lembretes calculados (ex.: aniversário) marcados como feitos
    chave             TEXT PRIMARY KEY,      -- ex.: aniv:<card>:<ano>
    feito_em          TEXT
);
