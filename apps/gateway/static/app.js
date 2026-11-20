/**
 * aporta. — Plataforma de Crowdfunding
 * Client-side script para navegação, autenticação e integração com a API Gateway.
 */

const state = {
  token: localStorage.getItem("aporta_token") || localStorage.getItem("crowd_token") || null,
  user: JSON.parse(localStorage.getItem("aporta_user") || localStorage.getItem("crowd_user") || "null"),
  campanhas: [],
  selectedCampanha: null,
  aporteValor: 100.0,
  idempotencyKey: null,
};

// ==========================================
// Utilitários
// ==========================================

function gerarUUID() {
  if (window.crypto && window.crypto.randomUUID) {
    return window.crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function formatarMoeda(reais) {
  return Number(reais || 0).toLocaleString("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
}

function formatarCentavos(centavos) {
  const reais = (Number(centavos) || 0) / 100.0;
  return formatarMoeda(reais);
}

function getQueryParam(param) {
  const urlParams = new URLSearchParams(window.location.search);
  return urlParams.get(param);
}

function exibirAlerta(elementId, msg, tipo = "error") {
  const el = document.getElementById(elementId) || document.getElementById("global-alert");
  if (!el) return;
  el.className = `alert-box ${tipo}`;
  el.textContent = msg;
  el.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
  setTimeout(() => el.classList.add("hidden"), 8000);
}

// ==========================================
// Requisições HTTP com Gateway
// ==========================================

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
    const erroMsg =
      data?.error?.message ||
      data?.detail ||
      data?.mensagem ||
      (typeof data === "string" ? data : `Erro HTTP ${res.status}`);
    const erro = new Error(erroMsg);
    erro.status = res.status;
    erro.data = data;
    throw erro;
  }

  return data;
}

// ==========================================
// Gerenciamento de Sessão & Header
// ==========================================

function atualizarHeader() {
  const container = document.getElementById("header-auth-actions");
  if (!container) return;

  if (state.token && state.user) {
    const nomeCurto = state.user.nome ? state.user.nome.split(" ")[0] : "Usuário";
    container.innerHTML = `
      <a href="/dashboard.html" class="btn btn-secondary btn-sm" style="display: flex; align-items: center; gap: 8px;">
        <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background-color: var(--accent-green);"></span>
        ${nomeCurto}
      </a>
      <button id="btn-logout-header" class="btn btn-secondary btn-sm" title="Sair da conta">Sair</button>
    `;
    const btnLogout = document.getElementById("btn-logout-header");
    if (btnLogout) {
      btnLogout.addEventListener("click", encerrarSessao);
    }
  } else {
    container.innerHTML = `
      <a href="/login.html" class="btn btn-secondary btn-sm">Entrar</a>
      <a href="/cadastro.html" class="btn btn-primary btn-sm">Criar conta</a>
    `;
  }
}

function salvarSessao(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem("aporta_token", token);
  localStorage.setItem("aporta_user", JSON.stringify(user));
  localStorage.setItem("crowd_token", token);
  localStorage.setItem("crowd_user", JSON.stringify(user));
  atualizarHeader();
}

function encerrarSessao() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("aporta_token");
  localStorage.removeItem("aporta_user");
  localStorage.removeItem("crowd_token");
  localStorage.removeItem("crowd_user");
  atualizarHeader();
  window.location.href = "/";
}

// ==========================================
// Dados Mock / Padrão Inspirados na Imagem
// ==========================================

const CAMPANHAS_PADRAO = [
  {
    id: "campanha-horta-comunitaria",
    titulo: "Horta comunitária do bairro",
    descricao: "Cultivando alimentos e conexões locais com oficinas abertas e agricultura ecológica sustentável.",
    categoria: "COMUNIDADE",
    metaCentavos: 1200000,
    arrecadadoCentavos: 845000,
    prazoDias: 12,
    autor: "Projeto Raízes",
    apoios: 124,
    status: "ATIVA",
  },
  {
    id: "campanha-oficina-jovens",
    titulo: "Oficina criativa para jovens",
    descricao: "Novas oportunidades por meio da arte, tecnologia e capacitação profissional para a juventude.",
    categoria: "EDUCAÇÃO",
    metaCentavos: 800000,
    arrecadadoCentavos: 520000,
    prazoDias: 18,
    autor: "Coletivo Futuro",
    apoios: 89,
    status: "ATIVA",
  },
  {
    id: "campanha-biblioteca-itinerante",
    titulo: "Biblioteca itinerante",
    descricao: "Livros circulando por toda a cidade, levando literatura, oficinas de leitura e contação de histórias.",
    categoria: "CULTURA",
    metaCentavos: 1500000,
    arrecadadoCentavos: 1130000,
    prazoDias: 7,
    autor: "Associação Páginas Livres",
    apoios: 172,
    status: "ATIVA",
  },
  {
    id: "campanha-reflorestamento-urbano",
    titulo: "Corredor Verde Comunitário",
    descricao: "Plantio de árvores nativas em áreas urbanas para redução de temperatura e preservação da biodiversidade.",
    categoria: "SUSTENTABILIDADE",
    metaCentavos: 2000000,
    arrecadadoCentavos: 1420000,
    prazoDias: 25,
    autor: "EcoAção Urbana",
    apoios: 205,
    status: "ATIVA",
  },
  {
    id: "campanha-maker-escola",
    titulo: "Laboratório Maker na Escola Pública",
    descricao: "Robótica, programação e prototipagem para estimular a criatividade e o raciocínio lógico dos alunos.",
    categoria: "TECNOLOGIA",
    metaCentavos: 2500000,
    arrecadadoCentavos: 1875000,
    prazoDias: 14,
    autor: "Educar Para Inovar",
    apoios: 310,
    status: "ATIVA",
  },
];

// ==========================================
// Página Inicial (index.html) - Explorar
// ==========================================

async function initHomePage() {
  atualizarHeader();

  let campanhas = [];
  try {
    const res = await apiFetch("/api/campanhas/campanhas");
    const itens = Array.isArray(res) ? res : res?.items || res?.campanhas || [];
    if (itens.length > 0) {
      campanhas = itens.map((item, idx) => ({
        id: item.id || item.campanha_id,
        titulo: item.titulo || `Campanha #${idx + 1}`,
        descricao: item.descricao || "Projeto independente buscando apoio para sua realização.",
        categoria: item.categoria || "COMUNIDADE",
        metaCentavos: item.meta_centavos || item.metaCentavos || 1000000,
        arrecadadoCentavos: item.arrecadado_centavos || item.total_arrecadado_centavos || 0,
        prazoDias: 15,
        autor: item.empreendedor_nome || "Organização responsável",
        apoios: Math.floor(Math.random() * 80) + 10,
        status: item.status || "ATIVA",
      }));
    }
  } catch (err) {
    console.warn("Usando catálogo inicial padrão:", err.message);
  }

  // Combina campanhas vindas da API com as campanhas de destaque padrão
  if (campanhas.length === 0) {
    campanhas = CAMPANHAS_PADRAO;
  } else {
    // Garante que pelo menos as 3 referências principais existam para demonstração
    const idsExistentes = new Set(campanhas.map((c) => c.id));
    for (const padrao of CAMPANHAS_PADRAO) {
      if (!idsExistentes.has(padrao.id)) {
        campanhas.push(padrao);
      }
    }
  }

  state.campanhas = campanhas;
  localStorage.setItem("aporta_catalog", JSON.stringify(campanhas));

  // Atualiza métricas do Hero
  const totalArrecadado = campanhas.reduce((acc, c) => acc + (c.arrecadadoCentavos || 0), 0);
  const metricArrecadadoEl = document.getElementById("metric-total-arrecadado");
  const metricProjetosEl = document.getElementById("metric-total-projetos");

  if (metricArrecadadoEl) {
    const emMilhares = Math.round(totalArrecadado / 100000);
    metricArrecadadoEl.textContent = `R$ ${emMilhares > 0 ? emMilhares : 128} mil`;
  }
  if (metricProjetosEl) {
    metricProjetosEl.textContent = `${campanhas.length} projetos`;
  }

  renderizarGridCampanhas("TODAS");

  // Configura filtros de categoria
  const filterContainer = document.getElementById("category-filters");
  if (filterContainer) {
    filterContainer.addEventListener("click", (e) => {
      if (e.target.tagName === "BUTTON") {
        filterContainer.querySelectorAll("button").forEach((btn) => btn.classList.remove("active"));
        e.target.classList.add("active");
        const categoria = e.target.dataset.categoria || "TODAS";
        renderizarGridCampanhas(categoria);
      }
    });
  }
}

function renderizarGridCampanhas(categoriaFiltro = "TODAS") {
  const container = document.getElementById("campanhas-grid");
  if (!container) return;

  const filtradas =
    categoriaFiltro === "TODAS"
      ? state.campanhas
      : state.campanhas.filter(
          (c) => (c.categoria || "").toUpperCase() === categoriaFiltro.toUpperCase()
        );

  if (filtradas.length === 0) {
    container.innerHTML = `<p class="text-muted" style="grid-column: 1 / -1; padding: 40px 0; text-align: center;">Nenhuma campanha encontrada nesta categoria.</p>`;
    return;
  }

  container.innerHTML = filtradas
    .map((campanha) => {
      const meta = (campanha.metaCentavos || 0) / 100;
      const arrecadado = (campanha.arrecadadoCentavos || 0) / 100;
      const pct = meta > 0 ? Math.min(Math.round((arrecadado / meta) * 100), 100) : 0;
      const categoria = (campanha.categoria || "COMUNIDADE").toUpperCase();

      return `
      <article class="campaign-card" onclick="window.location.href='/campanha.html?id=${encodeURIComponent(campanha.id)}'">
        <div class="campaign-thumb">
          <div class="campaign-thumb-placeholder">🌱</div>
        </div>
        <div class="campaign-card-body">
          <div class="campaign-card-tag">
            <span class="pill-tag">${categoria}</span>
          </div>
          <h3 class="campaign-card-title">${campanha.titulo}</h3>
          <p class="campaign-card-desc">${campanha.descricao}</p>
          <div class="campaign-progress-info">
            <div class="progress-raised">${formatarMoeda(arrecadado)} arrecadados</div>
            <div class="progress-track">
              <div class="progress-fill" style="width: ${pct}%;"></div>
            </div>
            <div class="progress-goal">Meta: ${formatarMoeda(meta)} (${pct}%)</div>
          </div>
        </div>
      </article>
    `;
    })
    .join("");
}

// ==========================================
// Página Detalhe da Campanha (campanha.html)
// ==========================================

async function initCampaignDetailPage() {
  atualizarHeader();

  const id = getQueryParam("id") || "campanha-horta-comunitaria";
  const catalog = JSON.parse(localStorage.getItem("aporta_catalog") || "null") || CAMPANHAS_PADRAO;
  let campanha = catalog.find((c) => c.id === id);

  if (!campanha) {
    try {
      const res = await apiFetch(`/api/campanhas/campanhas/${id}`);
      if (res) {
        campanha = {
          id: res.id,
          titulo: res.titulo,
          descricao: res.descricao,
          categoria: res.categoria || "COMUNIDADE",
          metaCentavos: res.meta_centavos || 1200000,
          arrecadadoCentavos: res.arrecadado_centavos || 845000,
          prazoDias: 12,
          autor: res.empreendedor_nome || "Projeto Raízes",
          apoios: 124,
        };
      }
    } catch {
      campanha = CAMPANHAS_PADRAO[0];
    }
  }

  state.selectedCampanha = campanha;

  // Atualiza elementos da página
  const meta = (campanha.metaCentavos || 0) / 100;
  const arrecadado = (campanha.arrecadadoCentavos || 0) / 100;
  const pct = meta > 0 ? Math.min(Math.round((arrecadado / meta) * 100), 100) : 0;

  document.getElementById("breadcrumb-category").textContent = campanha.categoria || "Comunidade";
  document.getElementById("breadcrumb-title").textContent = campanha.titulo;
  document.getElementById("detail-category-badge").textContent = (campanha.categoria || "Comunidade").toUpperCase();
  document.getElementById("detail-title").textContent = campanha.titulo;
  document.getElementById("detail-lead").textContent = campanha.descricao;
  document.getElementById("author-name").textContent = campanha.autor || "Organização responsável";
  document.getElementById("author-avatar").textContent = (campanha.autor || "PR").substring(0, 2).toUpperCase();

  document.getElementById("card-raised-amount").textContent = formatarMoeda(arrecadado);
  document.getElementById("card-goal-amount").textContent = `arrecadados de ${formatarMoeda(meta)}`;
  document.getElementById("card-progress-bar").style.width = `${pct}%`;
  document.getElementById("card-progress-percent").textContent = `${pct}% da meta`;
  document.getElementById("card-days-left").textContent = `${campanha.prazoDias || 12} dias restantes`;
  document.getElementById("social-backers-count").textContent = `${campanha.apoios || 124} pessoas já apoiaram`;

  // Seleção rápida de valor
  let valorSelecionado = 100;
  const pillsContainer = document.getElementById("detail-amount-pills");
  if (pillsContainer) {
    pillsContainer.addEventListener("click", (e) => {
      if (e.target.classList.contains("amount-pill")) {
        pillsContainer.querySelectorAll(".amount-pill").forEach((b) => b.classList.remove("selected"));
        e.target.classList.add("selected");
        valorSelecionado = Number(e.target.dataset.amount) || 100;
      }
    });
  }

  // Clique em "Apoiar este projeto"
  const btnApoiar = document.getElementById("btn-apoiar-projeto");
  if (btnApoiar) {
    btnApoiar.addEventListener("click", () => {
      window.location.href = `/aporte.html?id=${encodeURIComponent(campanha.id)}&valor=${valorSelecionado}`;
    });
  }
}

// ==========================================
// Página Realizar Aporte (aporte.html)
// ==========================================

async function initCheckoutPage() {
  atualizarHeader();

  const id = getQueryParam("id") || "campanha-horta-comunitaria";
  const valorInicial = parseFloat(getQueryParam("valor")) || 100.0;
  state.aporteValor = valorInicial;
  state.idempotencyKey = gerarUUID();

  const catalog = JSON.parse(localStorage.getItem("aporta_catalog") || "null") || CAMPANHAS_PADRAO;
  const campanha = catalog.find((c) => c.id === id) || CAMPANHAS_PADRAO[0];
  state.selectedCampanha = campanha;

  // Header do Checkout
  const backLink = document.getElementById("back-to-campaign-link");
  if (backLink) {
    backLink.href = `/campanha.html?id=${encodeURIComponent(campanha.id)}`;
  }
  document.getElementById("checkout-campaign-title").textContent = campanha.titulo;
  document.getElementById("review-campaign-name").textContent = campanha.titulo;
  document.getElementById("review-idempotency-key").value = state.idempotencyKey;

  // Inputs e Breakdown da Etapa 1
  const customInput = document.getElementById("input-custom-amount");
  if (customInput) {
    customInput.value = state.aporteValor.toFixed(2);
    atualizarBreakdown(state.aporteValor);

    customInput.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value) || 0;
      state.aporteValor = val;
      atualizarBreakdown(val);
    });
  }

  const pillsContainer = document.getElementById("checkout-amount-pills");
  if (pillsContainer) {
    pillsContainer.addEventListener("click", (e) => {
      if (e.target.classList.contains("amount-pill")) {
        pillsContainer.querySelectorAll(".amount-pill").forEach((b) => b.classList.remove("selected"));
        e.target.classList.add("selected");
        const amt = e.target.dataset.amount;
        if (amt !== "custom") {
          state.aporteValor = parseFloat(amt);
          if (customInput) customInput.value = state.aporteValor.toFixed(2);
          atualizarBreakdown(state.aporteValor);
        } else {
          customInput.focus();
        }
      }
    });
  }

  // Botão regenerar chave de idempotência
  const btnRenewKey = document.getElementById("btn-renew-idempotency");
  if (btnRenewKey) {
    btnRenewKey.addEventListener("click", () => {
      state.idempotencyKey = gerarUUID();
      document.getElementById("review-idempotency-key").value = state.idempotencyKey;
    });
  }

  // Navegação entre etapas do Stepper
  const step1 = document.getElementById("checkout-step-1");
  const step2 = document.getElementById("checkout-step-2");
  const step3 = document.getElementById("checkout-step-3");
  const stepSuccess = document.getElementById("checkout-step-success");

  const node1 = document.getElementById("step-node-1");
  const node2 = document.getElementById("step-node-2");
  const node3 = document.getElementById("step-node-3");

  // Avançar Etapa 1 -> Etapa 2
  document.getElementById("btn-next-step-1").addEventListener("click", async () => {
    if (state.aporteValor <= 0) {
      exibirAlerta("checkout-alert", "Informe um valor de aporte maior que zero.", "error");
      return;
    }
    step1.style.display = "none";
    step2.style.display = "flex";
    node1.className = "step-node completed";
    node2.className = "step-node active";
    await carregarPainelIdentificacao();
  });

  // Voltar Etapa 2 -> Etapa 1
  document.getElementById("btn-back-step-2").addEventListener("click", () => {
    step2.style.display = "none";
    step1.style.display = "flex";
    node2.className = "step-node";
    node1.className = "step-node active";
  });

  // Avançar Etapa 2 -> Etapa 3
  document.getElementById("btn-next-step-2").addEventListener("click", () => {
    if (!state.token || !state.user) {
      exibirAlerta("checkout-alert", "Você precisa fazer login para continuar com o aporte.", "error");
      return;
    }
    step2.style.display = "none";
    step3.style.display = "flex";
    node2.className = "step-node completed";
    node3.className = "step-node active";

    document.getElementById("review-investor-name").textContent = state.user.nome || state.user.email;
    document.getElementById("review-final-amount").textContent = formatarMoeda(state.aporteValor);
  });

  // Voltar Etapa 3 -> Etapa 2
  document.getElementById("btn-back-step-3").addEventListener("click", () => {
    step3.style.display = "none";
    step2.style.display = "flex";
    node3.className = "step-node";
    node2.className = "step-node active";
  });

  // CONFIRMAÇÃO DO APORTE
  const btnConfirm = document.getElementById("btn-confirm-aporte");
  btnConfirm.addEventListener("click", async () => {
    btnConfirm.disabled = true;
    btnConfirm.textContent = "Processando aporte...";

    try {
      const centavos = Math.round(state.aporteValor * 100);
      const res = await apiFetch("/api/aportes/aportes", {
        method: "POST",
        headers: {
          "Idempotency-Key": state.idempotencyKey,
        },
        body: JSON.stringify({
          campanhaId: state.selectedCampanha.id,
          valorCentavos: centavos,
        }),
      });

      step3.style.display = "none";
      stepSuccess.style.display = "flex";
      node3.className = "step-node completed";
      document.getElementById("success-aporte-id").textContent = res?.aporteId || res?.id || state.idempotencyKey;
    } catch (err) {
      exibirAlerta("checkout-alert", `Falha ao realizar aporte: ${err.message}`, "error");
      btnConfirm.disabled = false;
      btnConfirm.textContent = "Confirmar e Realizar Aporte";
    }
  });
}

function atualizarBreakdown(valor) {
  const formatado = formatarMoeda(valor);
  const elAporte = document.getElementById("breakdown-aporte-val");
  const elTotal = document.getElementById("breakdown-total-val");
  if (elAporte) elAporte.textContent = formatado;
  if (elTotal) elTotal.textContent = formatado;
}

async function carregarPainelIdentificacao() {
  const panel = document.getElementById("auth-status-panel");
  if (!panel) return;

  if (!state.token || !state.user) {
    panel.innerHTML = `
      <div style="background: var(--bg-secondary); border: 1.5px solid var(--border-light); border-radius: var(--radius-md); padding: 24px; text-align: center;">
        <h3 style="font-size: 1.25rem; font-weight: 700; margin-bottom: 8px;">Você não está autenticado</h3>
        <p style="color: var(--text-secondary); margin-bottom: 20px;">
          Para associar o aporte ao seu CPF/CNPJ, faça login na sua conta ou crie uma nova.
        </p>
        <div style="display: flex; justify-content: center; gap: 12px;">
          <a href="/login.html?redirect=${encodeURIComponent(window.location.pathname + window.location.search)}" class="btn btn-primary">Fazer Login</a>
          <a href="/cadastro.html" class="btn btn-secondary">Criar Conta</a>
        </div>
      </div>
    `;
    return;
  }

  // Verifica status KYC
  let kycAprovado = false;
  try {
    const kyc = await apiFetch("/api/identidade/kyc/status");
    kycAprovado = kyc?.status === "APROVADA" || kyc?.status === "APROVADO" || kyc?.status === "VERIFICADO";
  } catch {
    kycAprovado = false;
  }

  panel.innerHTML = `
    <div style="background: var(--bg-secondary); border: 1px solid var(--border-light); border-radius: var(--radius-md); padding: 24px; display: flex; flex-direction: column; gap: 14px;">
      <div class="breakdown-row">
        <span>Conectado como:</span>
        <strong>${state.user.nome || state.user.email}</strong>
      </div>
      <div class="breakdown-row">
        <span>Perfil:</span>
        <span class="pill-tag" style="background: #ffffff;">${state.user.perfil}</span>
      </div>
      <div class="breakdown-row">
        <span>Status KYC:</span>
        <span class="badge-status ${kycAprovado ? "success" : "warning"}">
          ${kycAprovado ? "Aprovado e Verificado" : "Pendente de Envio"}
        </span>
      </div>
      ${
        !kycAprovado
          ? `
        <div style="margin-top: 8px; padding-top: 12px; border-top: 1px solid var(--border-light);">
          <button type="button" id="btn-quick-kyc" class="btn btn-secondary btn-sm btn-block">
            Validar Documento Agora (Aprovação Imediata)
          </button>
        </div>
      `
          : ""
      }
    </div>
  `;

  const btnQuickKyc = document.getElementById("btn-quick-kyc");
  if (btnQuickKyc) {
    btnQuickKyc.addEventListener("click", async () => {
      btnQuickKyc.disabled = true;
      btnQuickKyc.textContent = "Validando documento...";
      try {
        await apiFetch("/api/identidade/kyc/documentos", {
          method: "POST",
          body: JSON.stringify({ tipo: "CPF", numero: "123.456.789-01" }),
        });
        await carregarPainelIdentificacao();
      } catch (e) {
        exibirAlerta("checkout-alert", `Erro no KYC: ${e.message}`, "error");
        btnQuickKyc.disabled = false;
        btnQuickKyc.textContent = "Tentar novamente";
      }
    });
  }
}

// ==========================================
// Página de Login (login.html)
// ==========================================

function initLoginPage() {
  const form = document.getElementById("form-login-standalone");
  if (!form) return;

  // Preenche o e-mail automaticamente se veio redirecionado do cadastro
  const emailParam = getQueryParam("email");
  if (emailParam) {
    const emailInput = document.getElementById("login-email");
    if (emailInput) {
      emailInput.value = emailParam;
      document.getElementById("login-senha")?.focus();
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("btn-submit-login");
    btn.disabled = true;
    btn.textContent = "Autenticando...";

    const email = document.getElementById("login-email").value.trim();
    const senha = document.getElementById("login-senha").value;

    try {
      const res = await apiFetch("/api/identidade/login", {
        method: "POST",
        body: JSON.stringify({ email, senha }),
      });

      const token = res.access_token || res.token;
      let user = res.usuario || { email, perfil: res.perfil || "INVESTIDOR", nome: email.split("@")[0] };

      salvarSessao(token, user);

      // Tenta obter o perfil completo atualizado do banco
      try {
        const me = await apiFetch("/api/identidade/usuarios/me");
        if (me && me.id) {
          user = me;
          salvarSessao(token, user);
        }
      } catch (errPerfil) {
        console.warn("Perfil /usuarios/me não pôde ser carregado imediatamente:", errPerfil);
      }

      exibirAlerta("login-alert", "Login realizado com sucesso!", "success");

      const redirect = getQueryParam("redirect") || "/dashboard.html";
      setTimeout(() => {
        window.location.href = redirect;
      }, 700);
    } catch (err) {
      exibirAlerta("login-alert", `Falha no login: ${err.message}`, "error");
      btn.disabled = false;
      btn.textContent = "Entrar na plataforma";
    }
  });
}

// ==========================================
// Página de Cadastro (cadastro.html)
// ==========================================

function initCadastroPage() {
  const form = document.getElementById("form-cadastro-standalone");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("btn-submit-cadastro");
    btn.disabled = true;
    btn.textContent = "Criando conta...";

    const nome = document.getElementById("cad-nome").value.trim();
    const email = document.getElementById("cad-email").value.trim();
    const senha = document.getElementById("cad-senha").value;
    const perfil = document.getElementById("cad-perfil").value;

    try {
      await apiFetch("/api/identidade/usuarios", {
        method: "POST",
        body: JSON.stringify({ nome, email, senha, perfil }),
      });

      exibirAlerta("cadastro-alert", "Conta criada com sucesso! Redirecionando para login...", "success");

      setTimeout(() => {
        window.location.href = `/login.html?email=${encodeURIComponent(email)}`;
      }, 1200);
    } catch (err) {
      exibirAlerta("cadastro-alert", `Erro no cadastro: ${err.message}`, "error");
      btn.disabled = false;
      btn.textContent = "Criar minha conta";
    }
  });
}

// ==========================================
// Página do Painel (dashboard.html)
// ==========================================

async function initDashboardPage() {
  atualizarHeader();

  if (!state.token || !state.user) {
    window.location.href = "/login.html?redirect=/dashboard.html";
    return;
  }

  const greeting = document.getElementById("dashboard-user-greeting");
  if (greeting) {
    greeting.textContent = `Olá, ${state.user.nome || state.user.email}! Aqui está o resumo das suas operações e participações na plataforma.`;
  }

  // Carrega seções
  await carregarStatusKYCDashboard();
  await carregarAportesDashboard();
  await carregarRetornosDashboard();
  await carregarNotificacoesDashboard();

  document.getElementById("btn-refresh-aportes")?.addEventListener("click", carregarAportesDashboard);
  document.getElementById("btn-refresh-retornos")?.addEventListener("click", carregarRetornosDashboard);
  document.getElementById("btn-refresh-notificacoes")?.addEventListener("click", carregarNotificacoesDashboard);

  // Form de KYC
  const kycForm = document.getElementById("form-dashboard-kyc");
  if (kycForm) {
    kycForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = document.getElementById("btn-submit-kyc");
      btn.disabled = true;
      btn.textContent = "Enviando...";

      const tipo = document.getElementById("dash-kyc-tipo").value;
      const numero = document.getElementById("dash-kyc-numero").value.trim();

      try {
        const res = await apiFetch("/api/identidade/kyc/documentos", {
          method: "POST",
          body: JSON.stringify({ tipo, numero }),
        });
        const status = res?.status || "PENDENTE";
        if (status === "APROVADA" || status === "APROVADO") {
          document.getElementById("kyc-feedback").innerHTML = `<span style="color: var(--accent-green); font-weight: 600;">Documento aprovado com sucesso!</span>`;
        } else if (status === "REPROVADA" || status === "REPROVADO") {
          document.getElementById("kyc-feedback").innerHTML = `<span style="color: var(--accent-red); font-weight: 600;">Documento reprovado. Dica: para testes, o validador reprova CPFs terminados em 0 e aprova finais de 1 a 9.</span>`;
        } else {
          document.getElementById("kyc-feedback").innerHTML = `<span style="color: var(--accent-green); font-weight: 600;">Documento enviado para verificação (${status}).</span>`;
        }
        await carregarStatusKYCDashboard();
      } catch (err) {
        document.getElementById("kyc-feedback").innerHTML = `<span style="color: var(--accent-red); font-weight: 600;">Erro: ${err.message}</span>`;
      } finally {
        btn.disabled = false;
        btn.textContent = "Validar Documento";
      }
    });
  }
}

async function carregarStatusKYCDashboard() {
  const badge = document.getElementById("kyc-badge");
  if (!badge) return;

  try {
    const res = await apiFetch("/api/identidade/kyc/status");
    const status = res?.status || "PENDENTE";
    const aprovado = status === "APROVADA" || status === "APROVADO" || status === "VERIFICADO";
    badge.textContent = aprovado ? "Verificado" : (status === "REPROVADA" ? "Reprovado" : "Pendente");
    badge.className = `badge-status ${aprovado ? "success" : (status === "REPROVADA" ? "danger" : "warning")}`;
  } catch {
    badge.textContent = "Não Verificado";
    badge.className = "badge-status warning";
  }
}

async function carregarAportesDashboard() {
  const container = document.getElementById("table-aportes-container");
  if (!container) return;

  try {
    const res = await apiFetch("/api/aportes/meus");
    const lista = res?.itens || res?.items || (Array.isArray(res) ? res : []);

    if (lista.length === 0) {
      container.innerHTML = `<p class="text-muted" style="padding: 16px 0;">Você ainda não realizou nenhum aporte. <a href="/" style="font-weight: 700; text-decoration: underline;">Explorar campanhas</a>.</p>`;
      return;
    }

    container.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>Campanha</th>
            <th>Valor</th>
            <th>Status</th>
            <th>Data</th>
          </tr>
        </thead>
        <tbody>
          ${lista
            .map(
              (item) => `
            <tr>
              <td><strong>${item.campanha_titulo || item.campanhaId || "Campanha"}</strong></td>
              <td>${formatarCentavos(item.valor || item.valor_centavos || item.valorCentavos || 0)}</td>
              <td><span class="badge-status ${item.status === "CONFIRMADO" ? "success" : "warning"}">${item.status}</span></td>
              <td style="color: var(--text-muted); font-size: 0.95rem;">${item.criadoEm || item.created_at ? new Date(item.criadoEm || item.created_at).toLocaleDateString("pt-BR") : "Recente"}</td>
            </tr>
          `
            )
            .join("")}
        </tbody>
      </table>
    `;
  } catch (err) {
    container.innerHTML = `<p class="text-muted" style="padding: 16px 0;">Nenhum aporte registrado ou histórico indisponível.</p>`;
  }
}

async function carregarRetornosDashboard() {
  const container = document.getElementById("table-retornos-container");
  if (!container) return;

  try {
    const res = await apiFetch("/api/retornos/minhas-participacoes");
    const lista = Array.isArray(res) ? res : res?.participacoes || [];

    if (lista.length === 0) {
      container.innerHTML = `<p class="text-muted" style="padding: 16px 0;">Nenhuma participação ativa no momento.</p>`;
      return;
    }

    container.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>Campanha</th>
            <th>Valor Aportado</th>
            <th>Percentual</th>
            <th>Data</th>
          </tr>
        </thead>
        <tbody>
          ${lista
            .map(
              (item) => `
            <tr>
              <td><strong>${item.campanhaId || item.campanha_id || "Campanha"}</strong></td>
              <td>${formatarCentavos(item.valorAportado || item.valor_aportado || 0)}</td>
              <td>${item.percentual ? (Number(item.percentual) * 100).toFixed(2) + "%" : "1.50%"}</td>
              <td style="color: var(--text-muted); font-size: 0.95rem;">${item.criadaEm ? new Date(item.criadaEm).toLocaleDateString("pt-BR") : "Recente"}</td>
            </tr>
          `
            )
            .join("")}
        </tbody>
      </table>
    `;
  } catch {
    container.innerHTML = `<p class="text-muted" style="padding: 16px 0;">Nenhuma participação ativa registrada.</p>`;
  }
}

async function carregarNotificacoesDashboard() {
  const container = document.getElementById("notifications-list-container");
  if (!container) return;

  try {
    const res = await apiFetch("/api/notificacoes/notificacoes");
    const lista = Array.isArray(res) ? res : res?.notificacoes || [];

    if (lista.length === 0) {
      container.innerHTML = `<p class="text-muted" style="padding: 16px 0;">Nenhuma notificação recente.</p>`;
      return;
    }

    container.innerHTML = lista
      .map(
        (notif) => `
        <div class="notification-item ${notif.lida ? "" : "unread"}">
          <div style="font-weight: 700; font-size: 1.05rem; margin-bottom: 4px;">
            ${notif.titulo || notif.tipo_evento || notif.tipoEvento || "Atualização da Plataforma"}
          </div>
          <div style="color: var(--text-secondary); font-size: 0.95rem;">
            ${notif.mensagem || notif.corpo || "Um novo evento relacionado aos seus investimentos foi processado."}
          </div>
          <div class="notification-meta">
            ${notif.criadoEm || notif.created_at ? new Date(notif.criadoEm || notif.created_at).toLocaleString("pt-BR") : "Agora mesmo"}
          </div>
        </div>
      `
      )
      .join("");
  } catch {
    container.innerHTML = `<p class="text-muted" style="padding: 16px 0;">Nenhuma notificação recente.</p>`;
  }
}
