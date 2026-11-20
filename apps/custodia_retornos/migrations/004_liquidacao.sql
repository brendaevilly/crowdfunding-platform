-- Controla a liquidação de cada campanha.
-- A chave primária impede liquidação duplicada.

CREATE TABLE IF NOT EXISTS custodia_liquidacoes (
    campanha_id TEXT PRIMARY KEY,
    resultado TEXT NOT NULL
        CHECK (resultado IN ('SUCESSO', 'FALHA')),
    valor_bruto INTEGER NOT NULL
        CHECK (valor_bruto >= 0),
    taxa_plataforma INTEGER NOT NULL DEFAULT 0
        CHECK (taxa_plataforma >= 0),
    valor_liquido INTEGER NOT NULL DEFAULT 0
        CHECK (valor_liquido >= 0),
    liquidada_em TEXT NOT NULL,

    CHECK (
        valor_bruto = taxa_plataforma + valor_liquido
        OR resultado = 'FALHA'
    ),

    FOREIGN KEY (campanha_id)
        REFERENCES custodia_resultados(campanha_id)
);

-- Cada aporte pode ser devolvido apenas uma vez.

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_custodia_devolucao_aporte
ON custodia_movimentacoes(aporte_id)
WHERE tipo = 'DEVOLUCAO';

-- Cada campanha pode ter uma única liberação.

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_custodia_liberacao_campanha
ON custodia_movimentacoes(campanha_id)
WHERE tipo = 'LIBERACAO';


-- A taxa é uma saída financeira distinta da liberação ao empreendedor.
-- Como SQLite não permite alterar um CHECK diretamente,
-- registramos a taxa em tabela própria, sem modificar o histórico.

CREATE TABLE IF NOT EXISTS custodia_taxas (
    campanha_id TEXT PRIMARY KEY,
    valor INTEGER NOT NULL CHECK (valor >= 0),
    criada_em TEXT NOT NULL,
    FOREIGN KEY (campanha_id)
        REFERENCES custodia_liquidacoes(campanha_id)
);
