/**
 * Aplicação Frontend para Plataforma de Crowdfunding.
 * Consome os microsserviços através da API Gateway (/api/*).
 */

const state = {
  token: localStorage.getItem("crowd_token") || null,
  user: JSON.parse(localStorage.getItem("crowd_user") || "null"),
  campanhas: [],
};

// ==========================================
// Utilitários
// ==========================================

function gerarUUID() {
  if (window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function formatarCentavos(centavos) {
  const reais = (Number(centavos) || 0) / 100.0;
  return reais.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function exibirAlerta(msg, tipo = "error") {
  const el = document.getElementById("global-alert");
  el.className = `alert alert-${tipo}`;
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 6000);
}

async function apiFetch(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }

  const res = await fetch(path, { ...options, headers });
  let data = null;
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    data = await res.json().catch(() => null);
  }

  if (!res.ok) {
    const erroMsg = data?.error?.message || data?.detail || `Erro HTTP ${res.status}`;
    const erro = new Error(erroMsg);
    erro.status = res.status;
    erro.data = data;
    throw erro;
  }

  return data;
}

// ==========================================
// Sessão e Interface de Usuário
// ==========================================

function atualizarBarraSessao() {
  const sessionInfo = document.getElementById("session-info");
  const btnLogout = document.getElementById("btn-logout");

  if (state.token && state.user) {
    sessionInfo.innerHTML = `Conectado como <strong>${state.user.nome || state.user.email}</strong> <span class="badge badge-subtle">${state.user.perfil}</span>`;
    btnLogout.classList.remove("hidden");
  } else {
    sessionInfo.textContent = "Não autenticado";
    btnLogout.classList.add("hidden");
  }
}

function salvarSessao(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem("crowd_token", token);
  localStorage.setItem("crowd_user", JSON.stringify(user));
  atualizarBarraSessao();
}

function encerrarSessao() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("crowd_token");
  localStorage.removeItem("crowd_user");
  atualizarBarraSessao();
  exibirAlerta("Você saiu da sessão.", "success");
}

// ==========================================
// Cadastro e Login
// ==========================================

async function handleCadastro(e) {
  e.preventDefault();
  const feedback = document.getElementById("cad-feedback");
  feedback.textContent = "Cadastrando...";
  feedback.className = "feedback";

  const nome = document.getElementById("cad-nome").value.trim();
  const email = document.getElementById("cad-email").value.trim();
  const senha = document.getElementById("cad-senha").value;
  const perfil = document.getElementById("cad-perfil").value;

  try {
    const res = await apiFetch("/api/identidade/usuarios", {
      method: "POST",
      body: JSON.stringify({ nome, email, senha, perfil }),
    });

    feedback.className = "feedback alert-success";
    feedback.textContent = `Cadastro realizado com sucesso! ID: ${res.id}. Faça login para prosseguir.`;
    document.getElementById("form-cadastro").reset();
  } catch (err) {
    feedback.className = "feedback alert-error";
    feedback.textContent = `Erro no cadastro: ${err.message}`;
  }
}

async function handleLogin(e) {
  e.preventDefault();
  const feedback = document.getElementById("login-feedback");
  feedback.textContent = "Autenticando...";
  feedback.className = "feedback";

  const email = document.getElementById("login-email").value.trim();
  const senha = document.getElementById("login-senha").value;

  try {
    const res = await apiFetch("/api/identidade/login", {
      method: "POST",
      body: JSON.stringify({ email, senha }),
    });

    const token = res.access_token || res.token;
    // Decodifica JWT payload básico
    let userInfo = { email, perfil: "INVESTIDOR" };
    try {
      const payloadBase64 = token.split(".")[1];
      const payload = JSON.parse(atob(payloadBase64));
      userInfo.id = payload.sub;
      userInfo.perfil = payload.perfil || "INVESTIDOR";
      userInfo.nome = payload.nome || email;
    } catch (_) {}

    salvarSessao(token, userInfo);
    feedback.className = "feedback alert-success";
    feedback.textContent = "Autenticado com sucesso!";

    // Consulta KYC e carrega campanhas
    carregarStatusKYC();
    carregarCampanhas();
  } catch (err) {
    feedback.className = "feedback alert-error";
    feedback.textContent = `Erro no login: ${err.message}`;
  }
}

// ==========================================
// KYC (Verificação de Identidade)
// ==========================================

async function carregarStatusKYC() {
  const badge = document.getElementById("kyc-status-badge");
  if (!state.token) {
    badge.className = "badge badge-warning";
    badge.textContent = "Não autenticado";
    return;
  }

  try {
    const res = await apiFetch("/api/identidade/kyc/status");
    const status = res.status || "PENDENTE";
    badge.textContent = status;
    if (status === "APROVADO") {
      badge.className = "badge badge-success";
    } else if (status === "REPROVADO") {
      badge.className = "badge badge-danger";
    } else {
      badge.className = "badge badge-warning";
    }
  } catch (err) {
    badge.className = "badge badge-warning";
    badge.textContent = err.status === 404 ? "NÃO INICIADO" : "PENDENTE";
  }
}

async function handleEnviarKYC(e) {
  e.preventDefault();
  const feedback = document.getElementById("kyc-feedback");
  if (!state.token) {
    exibirAlerta("Faça login antes de enviar documentos KYC.");
    return;
  }

  feedback.textContent = "Enviando documento...";
  feedback.className = "feedback";

  const tipo = document.getElementById("kyc-tipo").value;
  const numero = document.getElementById("kyc-numero").value.trim();

  try {
    const res = await apiFetch("/api/identidade/kyc/documentos", {
      method: "POST",
      body: JSON.stringify({ tipo, numero }),
    });

    feedback.className = "feedback alert-success";
    feedback.textContent = `Documento enviado! Status KYC atual: ${res.status}`;
    carregarStatusKYC();
  } catch (err) {
    feedback.className = "feedback alert-error";
    feedback.textContent = `Erro ao enviar KYC: ${err.message}`;
  }
}

// ==========================================
// Campanhas Ativas
// ==========================================

async function carregarCampanhas() {
  const container = document.getElementById("campanhas-container");
  container.innerHTML = "<p class='text-muted'>Carregando campanhas ativas...</p>";

  try {
    const campanhas = await apiFetch("/api/campanhas");
    state.campanhas = campanhas || [];

    if (!campanhas || campanhas.length === 0) {
      container.innerHTML = "<p class='text-muted'>Nenhuma campanha ativa no momento.</p>";
      return;
    }

    container.innerHTML = campanhas
      .map((c) => {
        const meta = c.meta || 0;
        const arrecadado = c.valorArrecadado || c.valor_arrecadado || 0;
        const percentual = meta > 0 ? Math.min(100, Math.round((arrecadado / meta) * 100)) : 0;
        const atingida = c.metaAtingida || c.meta_atingida;

        return `
        <div class="card campanha-card">
          <div>
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span class="badge ${c.status === 'PUBLICADA' ? 'badge-success' : 'badge-subtle'}">${c.status}</span>
              ${atingida ? '<span class="badge badge-success">Meta Atingida!</span>' : ''}
            </div>
            <h3 style="margin-top:0.5rem;">${c.titulo}</h3>
            <p class="text-muted" style="margin-bottom:0.75rem;">${c.descricao || ''}</p>
            
            <div>
              <small class="text-muted">Progresso: ${percentual}% (${formatarCentavos(arrecadado)} de ${formatarCentavos(meta)})</small>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${percentual}%;"></div>
              </div>
            </div>
          </div>

          <div style="margin-top:1.25rem;">
            <button class="btn btn-primary w-100 btn-sm" onclick="selecionarCampanhaParaAporte('${c.id}')">
              Aportar Nesta Campanha
            </button>
          </div>
        </div>
      `;
      })
      .join("");
  } catch (err) {
    container.innerHTML = `<p class="alert-error">Erro ao carregar campanhas: ${err.message}</p>`;
  }
}

window.selecionarCampanhaParaAporte = function (campanhaId) {
  document.getElementById("aporte-campanha-id").value = campanhaId;
  novaChaveIdempotencia();
  trocarAba("tab-aporte");
};

// ==========================================
// Aportes
// ==========================================

function novaChaveIdempotencia() {
  document.getElementById("aporte-idempotency-key").value = gerarUUID();
}

async function handleAporte(e) {
  e.preventDefault();
  const feedback = document.getElementById("aporte-feedback");

  if (!state.token || !state.user?.id) {
    exibirAlerta("Você precisa estar autenticado como Investidor para realizar aportes.");
    trocarAba("tab-auth");
    return;
  }

  const campanhaId = document.getElementById("aporte-campanha-id").value.trim();
  const valorReais = parseFloat(document.getElementById("aporte-valor").value);
  const idempotencyKey = document.getElementById("aporte-idempotency-key").value.trim();

  if (!campanhaId || isNaN(valorReais) || valorReais <= 0) {
    feedback.className = "feedback alert-error";
    feedback.textContent = "Preencha uma campanha válida e valor superior a R$ 0,00.";
    return;
  }

  const valorCentavos = Math.round(valorReais * 100);

  feedback.textContent = "Enviando aporte com chave de idempotência...";
  feedback.className = "feedback";

  try {
    const res = await apiFetch("/api/aportes", {
      method: "POST",
      headers: {
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({
        campanhaId: campanhaId,
        investidorId: state.user.id,
        valor: valorCentavos,
      }),
    });

    feedback.className = "feedback alert-success";
    feedback.textContent = `Aporte realizado com sucesso! ID: ${res.id || res.aporteId || 'confirmado'}. Valor: ${formatarCentavos(valorCentavos)}.`;

    // Atualiza lista de campanhas e histórico
    carregarCampanhas();
    carregarMeusAportes();
    carregarNotificacoes();
    novaChaveIdempotencia();
  } catch (err) {
    feedback.className = "feedback alert-error";
    feedback.textContent = `Falha no aporte: ${err.message}`;
  }
}

// ==========================================
// Histórico e Notificações
// ==========================================

async function carregarMeusAportes() {
  const container = document.getElementById("tabela-aportes-container");
  if (!state.token) {
    container.innerHTML = "<p class='text-muted'>Autentique-se para visualizar seus aportes.</p>";
    return;
  }

  container.innerHTML = "<p class='text-muted'>Carregando histórico de aportes...</p>";

  try {
    const res = await apiFetch("/api/aportes/meus");
    const lista = res.aportes || res.itens || (Array.isArray(res) ? res : []);

    if (lista.length === 0) {
      container.innerHTML = "<p class='text-muted'>Nenhum aporte realizado até o momento.</p>";
      return;
    }

    container.innerHTML = `
      <table style="width:100%; border-collapse:collapse; font-size:0.9rem;">
        <thead>
          <tr style="border-bottom:2px solid var(--border); text-align:left;">
            <th style="padding:0.5rem 0;">Campanha</th>
            <th style="padding:0.5rem 0;">Valor</th>
            <th style="padding:0.5rem 0;">Status</th>
            <th style="padding:0.5rem 0;">Data</th>
          </tr>
        </thead>
        <tbody>
          ${lista
            .map(
              (a) => `
            <tr style="border-bottom:1px solid var(--border);">
              <td style="padding:0.5rem 0; font-family:monospace; font-size:0.8rem;">${(a.campanhaId || a.campanha_id || '').slice(0, 8)}...</td>
              <td style="padding:0.5rem 0; font-weight:600;">${formatarCentavos(a.valor)}</td>
              <td style="padding:0.5rem 0;"><span class="badge badge-success">${a.status || 'CONFIRMADO'}</span></td>
              <td style="padding:0.5rem 0; color:var(--text-muted);">${new Date(a.criadoEm || a.criado_em || a.confirmadoEm || Date.now()).toLocaleDateString('pt-BR')}</td>
            </tr>
          `
            )
            .join("")}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = `<p class="alert-error">Erro ao carregar aportes: ${err.message}</p>`;
  }
}

async function carregarNotificacoes() {
  const container = document.getElementById("lista-notificacoes-container");
  if (!state.token) {
    container.innerHTML = "<p class='text-muted'>Autentique-se para visualizar suas notificações.</p>";
    return;
  }

  container.innerHTML = "<p class='text-muted'>Carregando notificações...</p>";

  try {
    const lista = await apiFetch("/api/notificacoes");

    if (!lista || lista.length === 0) {
      container.innerHTML = "<p class='text-muted'>Nenhuma notificação encontrada.</p>";
      return;
    }

    container.innerHTML = lista
      .map(
        (n) => `
        <div class="notification-item ${n.lida ? 'lida' : ''}">
          <div>
            <strong>${n.titulo}</strong>
            <p style="font-size:0.85rem; color:var(--text-main); margin-top:0.2rem;">${n.mensagem}</p>
            <small class="text-muted">${n.criadoEm ? new Date(n.criadoEm).toLocaleString('pt-BR') : ''}</small>
          </div>
          <div>
            ${
              !n.lida
                ? `<button class="btn btn-sm btn-outline" onclick="marcarNotificacaoComoLida('${n.id}')">Marcar Lida</button>`
                : '<span class="badge badge-subtle">Lida</span>'
            }
          </div>
        </div>
      `
      )
      .join("");
  } catch (err) {
    container.innerHTML = `<p class="alert-error">Erro ao carregar notificações: ${err.message}</p>`;
  }
}

window.marcarNotificacaoComoLida = async function (id) {
  try {
    await apiFetch(`/api/notificacoes/${id}/lida`, { method: "POST" });
    carregarNotificacoes();
  } catch (err) {
    exibirAlerta(`Falha ao marcar notificação como lida: ${err.message}`);
  }
};

// ==========================================
// Troca de Abas
// ==========================================

function trocarAba(tabId) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });
  document.querySelectorAll(".tab-content").forEach((tab) => {
    tab.classList.toggle("active", tab.id === tabId);
  });
}

// ==========================================
// Inicialização
// ==========================================

document.addEventListener("DOMContentLoaded", () => {
  atualizarBarraSessao();
  novaChaveIdempotencia();

  // Tabs
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => trocarAba(btn.dataset.tab));
  });

  // Event Listeners
  document.getElementById("btn-logout").addEventListener("click", encerrarSessao);
  document.getElementById("form-cadastro").addEventListener("submit", handleCadastro);
  document.getElementById("form-login").addEventListener("submit", handleLogin);
  document.getElementById("form-kyc").addEventListener("submit", handleEnviarKYC);
  document.getElementById("btn-atualizar-kyc").addEventListener("click", carregarStatusKYC);
  document.getElementById("btn-carregar-campanhas").addEventListener("click", carregarCampanhas);
  document.getElementById("btn-gerar-chave").addEventListener("click", novaChaveIdempotencia);
  document.getElementById("form-aporte").addEventListener("submit", handleAporte);
  document.getElementById("btn-atualizar-meus-aportes").addEventListener("click", carregarMeusAportes);
  document.getElementById("btn-atualizar-notificacoes").addEventListener("click", carregarNotificacoes);

  // Carga inicial
  carregarCampanhas();
  if (state.token) {
    carregarStatusKYC();
    carregarMeusAportes();
    carregarNotificacoes();
  }
});

// ==========================================
// PAINEL DO EMPREENDEDOR - ISSUE #33
// ==========================================

state.minhasCampanhas = [];

function obterIdUsuarioToken() {
  try {
    const partes = state.token.split(".");
    const payload = JSON.parse(atob(
      partes[1].replace(/-/g, "+").replace(/_/g, "/")
    ));
    return payload.sub;
  } catch {
    throw new Error("Não foi possível identificar o usuário autenticado.");
  }
}

function escaparHTML(valor) {
  return String(valor ?? "").replace(/[&<>"']/g, caractere => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[caractere]);
}

function dataParaCampo(valor) {
  if (!valor) return "";
  const data = new Date(valor);
  const deslocamento = data.getTimezoneOffset();
  return new Date(data.getTime() - deslocamento * 60000)
    .toISOString().slice(0, 16);
}

function prepararDadosCampanha() {
  const meta = Number(document.getElementById("campanha-meta").value);

  if (!Number.isFinite(meta) || meta <= 0) {
    throw new Error("Informe uma meta válida.");
  }

  const inicio = new Date(
    document.getElementById("campanha-inicio").value
  );
  const fim = new Date(
    document.getElementById("campanha-fim").value
  );

  if (
    !Number.isFinite(inicio.getTime()) ||
    !Number.isFinite(fim.getTime()) ||
    fim <= inicio
  ) {
    throw new Error("A data final deve ser posterior à inicial.");
  }

  return {
    titulo: document.getElementById("campanha-titulo").value.trim(),
    descricao: document.getElementById("campanha-descricao").value.trim(),
    meta: Math.round(meta * 100),
    prazoInicio: inicio.toISOString(),
    prazoFim: fim.toISOString()
  };
}

function limparFormularioCampanha() {
  document.getElementById("form-campanha").reset();
  document.getElementById("campanha-id").value = "";
  document.getElementById("campanha-versao").value = "";

  document.querySelector("#form-campanha button[type='submit']")
    .textContent = "Salvar rascunho";
}

async function carregarMinhasCampanhas() {
  const container = document.getElementById("minhas-campanhas-container");

  try {
    if (!state.token || !state.user) {
      throw new Error("Faça login para acessar suas campanhas.");
    }

    if (state.user.perfil !== "EMPREENDEDOR") {
      throw new Error("Esta área é exclusiva para empreendedores.");
    }

    container.innerHTML = '<p>Carregando campanhas...</p>';

    const usuarioId = obterIdUsuarioToken();

    const campanhas = await apiFetch(
      "/api/campanhas?limite=100"
    );

    state.minhasCampanhas = campanhas.filter(
      campanha => campanha.empreendedorId === usuarioId
    );

    if (!state.minhasCampanhas.length) {
      container.innerHTML =
        '<p class="text-muted">Você ainda não possui campanhas.</p>';
      return;
    }

    container.innerHTML = state.minhasCampanhas.map(campanha => {
      const meta = Number(campanha.meta) || 0;
      const arrecadado = Number(campanha.valorArrecadado) || 0;
      const percentual = meta > 0
        ? Math.min(100, arrecadado / meta * 100)
        : 0;

      const podeEditar = campanha.status === "RASCUNHO";
      const podeSubmeter = campanha.status === "RASCUNHO";

      return `
        <article class="card mt-4">
          <h3>${escaparHTML(campanha.titulo)}</h3>

          <p>${escaparHTML(campanha.descricao)}</p>

          <p><strong>Status:</strong>
            <span class="badge badge-subtle">
              ${escaparHTML(campanha.status)}
            </span>
          </p>

          <p><strong>Meta:</strong> ${formatarCentavos(meta)}</p>

          <p><strong>Arrecadado:</strong>
            ${formatarCentavos(arrecadado)}
          </p>

          <div class="progress-container"
               style="height:12px;background:#e5e7eb;border-radius:8px;overflow:hidden;">
            <div style="width:${percentual}%;height:100%;background:#2563eb;"></div>
          </div>

          <p>${percentual.toFixed(1)}% da meta alcançada</p>

          <p><strong>Prazo final:</strong>
            ${escaparHTML(new Date(campanha.prazoFim).toLocaleString("pt-BR"))}
          </p>

          <small class="text-muted">ID: ${escaparHTML(campanha.id)}</small>

          <div class="mt-4">
            ${podeEditar ? `
              <button class="btn btn-outline"
                data-acao="editar"
                data-id="${escaparHTML(campanha.id)}">
                Editar
              </button>
            ` : ""}

            ${podeSubmeter ? `
              <button class="btn btn-primary"
                data-acao="submeter"
                data-id="${escaparHTML(campanha.id)}">
                Submeter para moderação
              </button>
            ` : ""}
          </div>
        </article>
      `;
    }).join("");

  } catch (erro) {
    container.textContent = erro.message;
  }
}

async function handleSalvarCampanha(e) {
  e.preventDefault();

  const feedback = document.getElementById("campanha-feedback");

  try {
    if (!state.token || state.user?.perfil !== "EMPREENDEDOR") {
      throw new Error("Entre com uma conta de empreendedor.");
    }

    const dados = prepararDadosCampanha();
    const campanhaId = document.getElementById("campanha-id").value;

    const resultado = await apiFetch(
      campanhaId
        ? `/api/campanhas/${encodeURIComponent(campanhaId)}`
        : "/api/campanhas",
      {
        method: campanhaId ? "PUT" : "POST",
        body: JSON.stringify(dados)
      }
    );

    feedback.textContent = campanhaId
      ? "Campanha atualizada com sucesso!"
      : "Rascunho criado com sucesso!";

    feedback.className = "feedback success";

    limparFormularioCampanha();
    await carregarMinhasCampanhas();

  } catch (erro) {
    feedback.textContent = erro.message;
    feedback.className = "feedback error";
  }
}

function editarCampanha(id) {
  const campanha = state.minhasCampanhas.find(
    item => item.id === id
  );

  if (!campanha) {
    exibirAlerta("Campanha não encontrada.", "error");
    return;
  }

  if (campanha.status !== "RASCUNHO") {
    exibirAlerta("Somente rascunhos podem ser editados.", "error");
    return;
  }

  document.getElementById("campanha-id").value = campanha.id;
  document.getElementById("campanha-titulo").value = campanha.titulo;
  document.getElementById("campanha-descricao").value = campanha.descricao;
  document.getElementById("campanha-meta").value =
    (campanha.meta / 100).toFixed(2);
  document.getElementById("campanha-inicio").value =
    dataParaCampo(campanha.prazoInicio);
  document.getElementById("campanha-fim").value =
    dataParaCampo(campanha.prazoFim);

  document.querySelector("#form-campanha button[type='submit']")
    .textContent = "Salvar alterações";

  document.getElementById("form-campanha").scrollIntoView({
    behavior: "smooth"
  });
}

async function submeterCampanha(id) {
  if (!confirm("Deseja enviar esta campanha para moderação?")) return;

  try {
    await apiFetch(
      `/api/campanhas/${encodeURIComponent(id)}/submeter`,
      { method: "POST" }
    );

    exibirAlerta("Campanha enviada para moderação!", "success");
    await carregarMinhasCampanhas();

  } catch (erro) {
    exibirAlerta(erro.message, "error");
  }
}

async function handleDistribuirRetornos(e) {
  e.preventDefault();

  const feedback = document.getElementById("retorno-feedback");

  try {
    if (!state.token || state.user?.perfil !== "EMPREENDEDOR") {
      throw new Error("Acesso exclusivo para empreendedores.");
    }

    const campanhaId = document.getElementById(
      "retorno-campanha-id"
    ).value.trim();

    const valor = Number(
      document.getElementById("retorno-valor").value
    );

    if (!campanhaId || !Number.isFinite(valor) || valor <= 0) {
      throw new Error("Informe a campanha e um valor válido.");
    }

    const resultado = await apiFetch(
      `/api/retornos/campanhas/${encodeURIComponent(campanhaId)}/distribuir`,
      {
        method: "POST",
        body: JSON.stringify({
          valorTotal: Math.round(valor * 100)
        })
      }
    );

    feedback.textContent =
      `Distribuição realizada! Total: ${formatarCentavos(resultado.valorTotal)}.`;

    feedback.className = "feedback success";
    document.getElementById("form-distribuir-retornos").reset();

  } catch (erro) {
    feedback.textContent = erro.message;
    feedback.className = "feedback error";
  }
}

// ==========================================
// EVENTOS DO PAINEL DO EMPREENDEDOR
// ==========================================

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("form-campanha")
    .addEventListener("submit", handleSalvarCampanha);

  document.getElementById("btn-cancelar-edicao")
    .addEventListener("click", limparFormularioCampanha);

  document.getElementById("btn-atualizar-empreendedor")
    .addEventListener("click", carregarMinhasCampanhas);

  document.getElementById("form-distribuir-retornos")
    .addEventListener("submit", handleDistribuirRetornos);

  document.getElementById("minhas-campanhas-container")
    .addEventListener("click", async evento => {
      const botao = evento.target.closest("button[data-acao]");
      if (!botao) return;

      const id = botao.dataset.id;

      if (botao.dataset.acao === "editar") {
        editarCampanha(id);
      }

      if (botao.dataset.acao === "submeter") {
        await submeterCampanha(id);
      }
    });
});

// ==========================================
// PAINEL ADMINISTRATIVO - ISSUE #33
// ==========================================

function escaparHTMLAdmin(valor) {
  return String(valor ?? "").replace(/[&<>"']/g, caractere => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  })[caractere]);
}

function feedbackAdmin(id, mensagem, erro = false) {
  const elemento = document.getElementById(id);
  elemento.textContent = mensagem;
  elemento.className = erro
    ? "feedback feedback-error"
    : "feedback feedback-success";
}

async function carregarFilaModeracao() {
  const container = document.getElementById(
    "fila-moderacao-container"
  );

  container.textContent = "Carregando campanhas...";

  try {
    const campanhas = await apiFetch(
      "/api/campanhas?limite=100"
    );

    const pendentes = campanhas.filter(campanha => {
      const status = String(campanha.status || "").toUpperCase();

      return status.includes("MODER")
        || status.includes("ANALISE")
        || status === "PENDENTE";
    });

    if (!pendentes.length) {
      container.textContent =
        "Nenhuma campanha aguardando moderação.";
      return;
    }

    container.innerHTML = pendentes.map(campanha => `
      <article class="card mt-4">
        <h4>${escaparHTMLAdmin(campanha.titulo)}</h4>
        <p>${escaparHTMLAdmin(campanha.descricao)}</p>
        <p><strong>ID:</strong> ${escaparHTMLAdmin(campanha.id)}</p>
        <p><strong>Empreendedor:</strong>
          ${escaparHTMLAdmin(campanha.empreendedorId)}</p>
        <p><strong>Meta:</strong>
          ${formatarCentavos(campanha.meta)}</p>
        <p><strong>Status:</strong>
          ${escaparHTMLAdmin(campanha.status)}</p>

        <button class="btn btn-success"
          data-admin-acao="aprovar"
          data-id="${escaparHTMLAdmin(campanha.id)}">
          Aprovar
        </button>

        <button class="btn btn-danger"
          data-admin-acao="reprovar"
          data-id="${escaparHTMLAdmin(campanha.id)}">
          Reprovar
        </button>
      </article>
    `).join("");

  } catch (erro) {
    container.textContent = erro.message;
  }
}

async function moderarCampanha(id, acao) {
  try {
    let body = {};

    if (acao === "reprovar") {
      const motivo = prompt("Informe o motivo da reprovação:");

      if (!motivo || !motivo.trim()) return;

      body = { motivo: motivo.trim() };
    }

    const confirmado = confirm(
      `Deseja realmente ${acao} esta campanha?`
    );

    if (!confirmado) return;

    await apiFetch(
      `/api/campanhas/${encodeURIComponent(id)}/${acao}`,
      {
        method: "POST",
        body: JSON.stringify(body)
      }
    );

    exibirAlerta(
      `Campanha ${acao === "aprovar" ? "aprovada" : "reprovada"} com sucesso!`,
      "success"
    );

    await carregarFilaModeracao();

  } catch (erro) {
    exibirAlerta(erro.message);
  }
}

async function alterarBloqueioUsuario(bloquear) {
  const id = document.getElementById(
    "admin-usuario-id"
  ).value.trim();

  const motivo = document.getElementById(
    "admin-motivo-bloqueio"
  ).value.trim();

  if (!id) {
    feedbackAdmin(
      "admin-usuario-feedback",
      "Informe o ID do usuário.",
      true
    );
    return;
  }

  try {
    await apiFetch(
      `/api/identidade/usuarios/${encodeURIComponent(id)}/${bloquear ? "bloquear" : "desbloquear"}`,
      {
        method: "POST",
        body: JSON.stringify({ motivo })
      }
    );

    feedbackAdmin(
      "admin-usuario-feedback",
      bloquear
        ? "Usuário bloqueado com sucesso!"
        : "Usuário desbloqueado com sucesso!"
    );

  } catch (erro) {
    feedbackAdmin(
      "admin-usuario-feedback",
      erro.message,
      true
    );
  }
}

async function carregarFilaKYC() {
  const container = document.getElementById("fila-kyc-lista");

  container.textContent = "Carregando verificações pendentes...";

  try {
    const verificacoes = await apiFetch(
      "/api/identidade/kyc/admin/verificacoes/pendentes"
    );

    if (!verificacoes.length) {
      container.innerHTML =
        '<p class="text-muted">Nenhuma verificação pendente.</p>';
      return;
    }

    container.innerHTML = verificacoes.map(verificacao => `
      <article class="card mt-4">
        <h4>Verificação de identidade</h4>

        <p><strong>ID da verificação:</strong>
          ${escaparHTMLAdmin(verificacao.verificacaoId)}</p>

        <p><strong>ID do usuário:</strong>
          ${escaparHTMLAdmin(verificacao.usuarioId)}</p>

        <p><strong>Documento:</strong>
          ${escaparHTMLAdmin(verificacao.documentoTipo || "Não informado")}</p>

        <p><strong>Solicitado em:</strong>
          ${escaparHTMLAdmin(
            new Date(verificacao.criadoEm).toLocaleString("pt-BR")
          )}</p>

        <p><strong>Status:</strong>
          ${escaparHTMLAdmin(verificacao.status)}</p>

        <button class="btn btn-success"
          data-kyc-acao="APROVADA"
          data-id="${escaparHTMLAdmin(verificacao.usuarioId)}">
          Aprovar KYC
        </button>

        <button class="btn btn-danger"
          data-kyc-acao="REPROVADA"
          data-id="${escaparHTMLAdmin(verificacao.usuarioId)}">
          Reprovar KYC
        </button>
      </article>
    `).join("");

  } catch (erro) {
    container.textContent = erro.message;
  }
}

async function decidirKYC(usuarioId, status) {
  const acao = status === "APROVADA" ? "aprovar" : "reprovar";

  if (!confirm(`Deseja realmente ${acao} esta verificação KYC?`)) {
    return;
  }

  try {
    await apiFetch(
      `/api/identidade/kyc/admin/verificacoes/${encodeURIComponent(usuarioId)}/decisao`,
      {
        method: "POST",
        body: JSON.stringify({ status })
      }
    );

    feedbackAdmin(
      "admin-kyc-feedback",
      `Verificação KYC ${acao} com sucesso!`
    );

    await carregarFilaKYC();

  } catch (erro) {
    feedbackAdmin(
      "admin-kyc-feedback",
      erro.message,
      true
    );
  }
}

// Eventos do painel administrativo.
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btn-atualizar-admin")
    .addEventListener("click", () => {
      carregarFilaModeracao();
      carregarFilaKYC();
    });

  document.getElementById("btn-atualizar-kyc-admin")
    .addEventListener("click", carregarFilaKYC);

  document.getElementById("form-bloquear-usuario")
    .addEventListener("submit", evento => {
      evento.preventDefault();
      alterarBloqueioUsuario(true);
    });

  document.getElementById("btn-desbloquear-usuario")
    .addEventListener("click", () => {
      alterarBloqueioUsuario(false);
    });

  document.getElementById("fila-kyc-lista")
    .addEventListener("click", evento => {
      const botao = evento.target.closest("button[data-kyc-acao]");

      if (!botao) return;

      decidirKYC(
        botao.dataset.id,
        botao.dataset.kycAcao
      );
    });

  document.getElementById("fila-moderacao-container")
    .addEventListener("click", evento => {
      const botao = evento.target.closest(
        "button[data-admin-acao]"
      );

      if (!botao) return;

      moderarCampanha(
        botao.dataset.id,
        botao.dataset.adminAcao
      );
    });
});

// ==========================================
// PAINEL DEV - CONTROLE DO RELÓGIO - ISSUE #33
// ==========================================

async function handleAvancarRelogio(evento) {
  evento.preventDefault();

  const campo = document.getElementById("clock-segundos");
  const feedback = document.getElementById("clock-feedback");
  const botao = evento.submitter;

  const segundos = Number(campo.value);

  if (!Number.isFinite(segundos) || segundos <= 0) {
    feedbackAdmin(
      "clock-feedback",
      "Informe uma quantidade de segundos maior que zero.",
      true
    );
    return;
  }

  if (botao) botao.disabled = true;

  feedback.textContent = "Avançando relógio...";

  try {
    const resultado = await apiFetch(
      "/api/retornos/_dev/clock/advance",
      {
        method: "POST",
        body: JSON.stringify({ seconds: segundos })
      }
    );

    const dataFormatada = new Date(resultado.now)
      .toLocaleString("pt-BR");

    feedbackAdmin(
      "clock-feedback",
      `Relógio avançado com sucesso! Nova data: ${dataFormatada}. Campanhas apuradas: ${resultado.apuradas}.`
    );

  } catch (erro) {
    feedbackAdmin(
      "clock-feedback",
      erro.message,
      true
    );
  } finally {
    if (botao) botao.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("form-avancar-relogio")
    .addEventListener("submit", handleAvancarRelogio);
});
