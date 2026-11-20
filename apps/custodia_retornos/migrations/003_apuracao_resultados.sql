ALTER TABLE custodia_contas
ADD COLUMN empreendedor_id TEXT;

CREATE TABLE custodia_investidores (
    campanha_id TEXT NOT NULL,
    investidor_id TEXT NOT NULL,
    PRIMARY KEY (campanha_id, investidor_id),
    FOREIGN KEY (campanha_id)
        REFERENCES custodia_contas(campanha_id)
);

CREATE TABLE custodia_resultados (
    campanha_id TEXT PRIMARY KEY,
    resultado TEXT NOT NULL
        CHECK (resultado IN ('SUCESSO', 'FALHA')),
    valor_arrecadado INTEGER NOT NULL
        CHECK (valor_arrecadado >= 0),
    encerrada_em TEXT NOT NULL,
    FOREIGN KEY (campanha_id)
        REFERENCES custodia_contas(campanha_id)
);

CREATE INDEX idx_custodia_prazos
ON custodia_contas(prazo_fim);
