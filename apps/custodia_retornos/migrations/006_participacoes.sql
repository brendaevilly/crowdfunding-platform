-- Registra os aportes necessários para calcular as participações.
CREATE TABLE IF NOT EXISTS retornos_aportes (
    aporte_id TEXT PRIMARY KEY,
    campanha_id TEXT NOT NULL,
    investidor_id TEXT NOT NULL,
    valor INTEGER NOT NULL CHECK (valor > 0),
    confirmado_em TEXT NOT NULL,

    FOREIGN KEY (campanha_id)
        REFERENCES custodia_contas(campanha_id)
);

CREATE INDEX IF NOT EXISTS idx_retornos_aportes_campanha
ON retornos_aportes(campanha_id);

CREATE INDEX IF NOT EXISTS idx_retornos_aportes_investidor
ON retornos_aportes(investidor_id);

-- Uma única distribuição por campanha.
CREATE UNIQUE INDEX IF NOT EXISTS
    ux_retornos_distribuicoes_campanha
ON retornos_distribuicoes(campanha_id);

-- Participações dos investidores na campanha.
-- percentual_unidades utiliza escala de 1.000.000.
-- 1.000.000 representa 100% (fração 1).
CREATE TABLE IF NOT EXISTS retornos_participacoes (
    participacao_id TEXT PRIMARY KEY,
    campanha_id TEXT NOT NULL,
    investidor_id TEXT NOT NULL,
    valor_aportado INTEGER NOT NULL CHECK (valor_aportado > 0),
    percentual_unidades INTEGER NOT NULL
        CHECK (
            percentual_unidades >= 0
            AND percentual_unidades <= 1000000
        ),
    criada_em TEXT NOT NULL,

    UNIQUE (campanha_id, investidor_id),

    FOREIGN KEY (campanha_id)
        REFERENCES custodia_contas(campanha_id)
);

CREATE INDEX IF NOT EXISTS idx_retornos_participacoes_investidor
ON retornos_participacoes(investidor_id);

-- Participações são imutáveis após sua criação.
CREATE TRIGGER IF NOT EXISTS
    trg_retornos_participacoes_nao_atualizar
BEFORE UPDATE ON retornos_participacoes
BEGIN
    SELECT RAISE(ABORT, 'Participacoes sao imutaveis');
END;

CREATE TRIGGER IF NOT EXISTS
    trg_retornos_participacoes_nao_excluir
BEFORE DELETE ON retornos_participacoes
BEGIN
    SELECT RAISE(ABORT, 'Participacoes nao podem ser excluidas');
END;
