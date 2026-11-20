-- Estrutura inicial do módulo de Retornos.
-- A distribuição de retornos será implementada em issue posterior.

CREATE TABLE IF NOT EXISTS retornos_distribuicoes (
    distribuicao_id TEXT PRIMARY KEY,
    campanha_id TEXT NOT NULL,
    criada_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (campanha_id)
        REFERENCES custodia_contas(campanha_id)
);
