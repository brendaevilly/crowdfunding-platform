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
