/* Controlador da UI do REDVAULT — apenas progressive enhancement. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  // Difficulty keys arrive from the API as slugs; labels are shown in pt-BR.
  const DIFFICULTY = { beginner: "Iniciante", easy: "Fácil", medium: "Médio", hard: "Difícil", insane: "Insano" };
  const difficultyLabel = (value) => DIFFICULTY[value] || value;

  function toast(message, kind = "ok", timeout = 4200) {
    const stack = $("#toast-stack");
    if (!stack) return;
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = message;
    stack.appendChild(el);
    setTimeout(() => {
      el.style.opacity = "0";
      el.style.transition = "opacity .2s";
      setTimeout(() => el.remove(), 220);
    }, timeout);
  }

  async function postJSON(url, data = {}) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(data),
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) { /* empty */ }
    if (!response.ok) {
      if (response.status === 401) {
        window.location.href = `/login?next=${encodeURIComponent(location.pathname)}`;
        throw new Error("Sessão expirada");
      }
      throw new Error(payload.detail || `Falha na requisição (${response.status})`);
    }
    return payload;
  }

  /* ---------------------------- navigation / menus ---------------------------- */
  const sidebar = $("#sidebar");
  const scrim = $("#sidebar-scrim");
  const menuToggle = $("#menu-toggle");

  function setDrawer(open) {
    sidebar?.classList.toggle("open", open);
    scrim?.classList.toggle("visible", open);
    menuToggle?.setAttribute("aria-expanded", String(open));
    document.body.style.overflow = open ? "hidden" : "";
  }
  menuToggle?.addEventListener("click", () => setDrawer(!sidebar?.classList.contains("open")));
  scrim?.addEventListener("click", () => setDrawer(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar?.classList.contains("open")) setDrawer(false);
  });
  // Any navigation inside the drawer closes it.
  $$(".nav-item", sidebar || document).forEach((link) => link.addEventListener("click", () => setDrawer(false)));
  window.addEventListener("resize", () => {
    if (window.innerWidth > 1120) setDrawer(false);
  });

  /* Collapsible sidebar (desktop): the state lives on <html> so the pre-paint
     script can restore it before the first frame. */
  const collapseBtn = $("#sidebar-collapse");
  function setCollapsed(collapsed) {
    document.documentElement.classList.toggle("is-collapsed", collapsed);
    try { localStorage.setItem("rv:sidebar", collapsed ? "collapsed" : "expanded"); } catch (_) { /* ignore */ }
    collapseBtn?.setAttribute("aria-expanded", String(!collapsed));
    collapseBtn?.setAttribute("aria-label", collapsed ? "Expandir navegação" : "Recolher navegação");
  }
  collapseBtn?.addEventListener("click", () => setCollapsed(!document.documentElement.classList.contains("is-collapsed")));
  if (collapseBtn) collapseBtn.setAttribute("aria-expanded", String(!document.documentElement.classList.contains("is-collapsed")));

  const userButton = $("#user-button");
  const userDropdown = $("#user-dropdown");
  const setUserMenu = (open) => {
    userDropdown?.classList.toggle("open", open);
    userButton?.setAttribute("aria-expanded", String(open));
  };
  userButton?.addEventListener("click", (event) => {
    event.stopPropagation();
    setUserMenu(!userDropdown?.classList.contains("open"));
  });
  document.addEventListener("click", (event) => {
    if (userDropdown && !userDropdown.contains(event.target) && !userButton?.contains(event.target)) {
      setUserMenu(false);
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && userDropdown?.classList.contains("open")) {
      setUserMenu(false);
      userButton?.focus();
    }
  });

  $$(".flash-close").forEach((button) => {
    button.addEventListener("click", () => button.closest(".flash")?.remove());
  });

  /* ------------------------------- command palette --------------------------- */
  const backdrop = $("#palette-backdrop");
  const paletteInput = $("#palette-input");
  const paletteResults = $("#palette-results");
  let paletteTimer = null;
  let paletteItems = [];
  let paletteIndex = 0;

  function openPalette() {
    if (!backdrop) return;
    backdrop.hidden = false;
    document.body.style.overflow = "hidden";
    setTimeout(() => paletteInput?.focus(), 20);
  }
  function closePalette() {
    if (!backdrop) return;
    backdrop.hidden = true;
    document.body.style.overflow = "";
    if (paletteInput) paletteInput.value = "";
    paletteResults.innerHTML = '<div class="palette-hint">Digite ao menos 2 caracteres. Os resultados ficam locais.</div>';
    paletteItems = [];
  }
  $("#search-trigger")?.addEventListener("click", openPalette);
  backdrop?.addEventListener("click", (event) => { if (event.target === backdrop) closePalette(); });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      backdrop?.hidden ? openPalette() : closePalette();
    }
    if (event.key === "Escape") closePalette();
  });

  function renderPalette(data) {
    paletteResults.innerHTML = "";
    paletteItems = [];
    const addGroup = (label) => {
      const div = document.createElement("div");
      div.className = "palette-group";
      div.textContent = label;
      paletteResults.appendChild(div);
    };
    if (data.challenges?.length) {
      addGroup("ALVOS");
      data.challenges.forEach((item) => {
        const a = document.createElement("a");
        a.className = "palette-item";
        a.href = item.url;
        a.innerHTML = `<span>${escapeHTML(item.title)}</span><small>${escapeHTML(item.category)} · ${escapeHTML(difficultyLabel(item.difficulty))}</small>`;
        paletteResults.appendChild(a);
        paletteItems.push(a);
      });
    }
    if (data.articles?.length) {
      addGroup("ACADEMIA");
      data.articles.forEach((item) => {
        const a = document.createElement("a");
        a.className = "palette-item";
        a.href = item.url;
        a.innerHTML = `<span>${escapeHTML(item.title)}</span><small>${escapeHTML(item.category)}</small>`;
        paletteResults.appendChild(a);
        paletteItems.push(a);
      });
    }
    if (!paletteItems.length) {
      paletteResults.innerHTML = '<div class="palette-hint">Nenhum resultado local para esta busca.</div>';
    }
    paletteIndex = 0;
  }

  function escapeHTML(value) {
    return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }

  paletteInput?.addEventListener("input", () => {
    clearTimeout(paletteTimer);
    const query = paletteInput.value.trim();
    if (query.length < 2) {
      paletteResults.innerHTML = '<div class="palette-hint">Digite ao menos 2 caracteres. Os resultados ficam locais.</div>';
      paletteItems = [];
      return;
    }
    paletteTimer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`, { credentials: "same-origin" });
        if (!response.ok) throw new Error("busca falhou");
        renderPalette(await response.json());
      } catch (error) {
        paletteResults.innerHTML = `<div class="palette-hint">${escapeHTML(error.message)}</div>`;
      }
    }, 180);
  });
  paletteInput?.addEventListener("keydown", (event) => {
    if (!paletteItems.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      paletteIndex = (paletteIndex + (event.key === "ArrowDown" ? 1 : -1) + paletteItems.length) % paletteItems.length;
      paletteItems.forEach((item, index) => item.classList.toggle("active", index === paletteIndex));
      paletteItems[paletteIndex].scrollIntoView({ block: "nearest" });
    }
    if (event.key === "Enter") {
      event.preventDefault();
      paletteItems[paletteIndex]?.click();
    }
  });

  /* --------------------------------- clipboard ------------------------------- */
  $$("[data-copy]").forEach((button) => {
    button.addEventListener("click", async () => {
      const value = button.dataset.copy || "";
      try {
        await navigator.clipboard.writeText(value);
        button.classList.add("copied");
        setTimeout(() => button.classList.remove("copied"), 1400);
        toast("Copiado para a área de transferência.", "ok", 1600);
      } catch (_) {
        toast("Área de transferência indisponível neste navegador.", "error");
      }
    });
  });

  /* --------------------------------- filters --------------------------------- */
  $$(".js-auto-submit").forEach((field) => {
    field.addEventListener("change", () => field.form?.submit());
  });

  /* --------------------------------- hint unlock ----------------------------- */
  $$(".js-unlock-hint").forEach((button) => {
    button.addEventListener("click", async () => {
      const slug = button.dataset.slug;
      const level = button.dataset.level;
      button.disabled = true;
      button.textContent = "DESBLOQUEANDO…";
      try {
        const data = await postJSON(`/api/challenges/${slug}/hints/${level}`);
        const card = button.closest(".hint-card");
        card?.classList.add("unlocked");
        const body = $(".hint-body", card);
        if (body) body.innerHTML = data.body;
        const actions = $(".hint-actions", card);
        if (actions) actions.remove();
        const cost = $(".hint-cost", card);
        if (cost) { cost.textContent = "USADO"; cost.classList.add("paid"); }
        const used = $("#hints-used");
        if (used) used.textContent = data.hints_used;
        const penalty = $("#hint-penalty");
        if (penalty) penalty.textContent = `-${data.hint_penalty} XP`;
        toast(`Hint ${data.level} desbloqueado (−${data.cost} XP).`, "info");
        maybeShowSolution();
      } catch (error) {
        button.disabled = false;
        button.textContent = "DESBLOQUEAR HINT";
        toast(error.message, "error");
      }
    });
  });

  function maybeShowSolution() {
    const total = Number($("#hint-total")?.dataset.total || 0);
    const unlocked = $$(".hint-card.unlocked").length;
    const gate = $("#solution-gate");
    const button = $("#solution-unlock");
    if (gate && button && total > 0 && unlocked >= total) {
      gate.querySelector(".solution-locked-copy").hidden = true;
      button.hidden = false;
    }
  }
  maybeShowSolution();

  $("#solution-unlock")?.addEventListener("click", async () => {
    const button = $("#solution-unlock");
    const slug = button.dataset.slug;
    button.disabled = true;
    button.textContent = "DESCRIPTOGRAFANDO…";
    try {
      const data = await postJSON(`/api/challenges/${slug}/solution`);
      const gate = $("#solution-gate");
      if (gate) gate.hidden = true;
      const slot = $("#solution-slot");
      if (slot) {
        slot.hidden = false;
        const walkthrough = $("#solution-walkthrough");
        const root = $("#solution-root");
        const mitigation = $("#solution-mitigation");
        if (walkthrough) walkthrough.innerHTML = data.walkthrough;
        if (root) root.innerHTML = data.root_cause;
        if (mitigation) mitigation.innerHTML = data.mitigation;
      }
      toast("Walkthrough desbloqueado. O XP é reduzido se você concluir depois de ler.", "info", 5200);
    } catch (error) {
      button.disabled = false;
      button.textContent = "DESBLOQUEAR WALKTHROUGH";
      toast(error.message, "error");
    }
  });

  /* --------------------------------- flag submit ----------------------------- */
  $$(".js-flag-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const slug = form.dataset.slug;
      const input = $('input[name="value"]', form);
      const key = form.dataset.flag;
      const result = $(".flag-result", form.closest(".flag-row"));
      const button = $("button[type=submit]", form);
      const value = input.value.trim();
      if (!value) return;
      button.disabled = true;
      button.textContent = "…";
      try {
        const data = await postJSON(`/api/challenges/${slug}/flags`, { flag_key: key, value });
        if (result) {
          result.className = `flag-result ${data.correct ? "ok" : "err"}`;
          result.textContent = data.correct ? `✓ ${data.message}${data.newly_completed ? ` +${data.xp_awarded} XP` : ""}` : `✕ ${data.message}`;
        }
        if (data.correct) {
          input.disabled = true;
          button.textContent = "CAPTURADA";
          button.classList.add("btn-ghost");
          const row = form.closest(".flag-row");
          row?.classList.add("solved");
          const state = $(".flag-state", row);
          if (state) { state.classList.add("solved"); state.innerHTML = "● CAPTURADA"; }
          $$("#solved-count, .js-solved-count").forEach((counter) => {
            counter.textContent = String(Number(counter.textContent) + 1);
          });
          if (data.achievements?.length) data.achievements.forEach((name) => toast(`Conquista: ${name}`, "ok", 5200));
          if (data.completed) {
            toast(`Alvo concluído. +${data.xp_awarded || 0} XP`, "ok", 5000);
            setTimeout(() => window.location.reload(), 1300);
          } else if (data.remaining?.length) {
            toast(`Capturada. Faltam: ${data.remaining.join(", ")}`, "info", 4200);
          }
        } else {
          button.disabled = false;
          button.textContent = "ENVIAR";
        }
      } catch (error) {
        if (result) { result.className = "flag-result err"; result.textContent = `✕ ${error.message}`; }
        button.disabled = false;
        button.textContent = "ENVIAR";
        toast(error.message, "error");
      }
    });
  });

  /* --------------------------------- lab control ----------------------------- */
  const labPanel = $("#lab-control");
  let labPoll = null;

  function setLabUI(data) {
    if (!labPanel) return;
    const state = $(".lab-state", labPanel);
    const url = $(".lab-url span", labPanel);
    const open = $(".js-lab-open", labPanel);
    const start = $(".js-lab-start", labPanel);
    const stop = $(".js-lab-stop", labPanel);
    const reset = $(".js-lab-reset", labPanel);
    const active = Boolean(data.active);
    labPanel.classList.toggle("live", active);
    if (state) {
      state.className = `lab-state ${active ? "live" : ""}`;
      state.innerHTML = `<span class="status-dot"></span>${active ? "EM EXECUÇÃO" : "PARADO"}`;
    }
    if (url) url.textContent = active ? data.url : "não está rodando";
    if (open) { open.hidden = !active; open.href = active ? data.url : "#"; }
    if (start) start.hidden = active;
    if (stop) stop.hidden = !active;
    if (reset) reset.hidden = !active;
    // "Reset" restarts the lab in place. ``stop()`` hides these buttons as a
    // side effect, so re-enable them here: after a reset the target is live
    // again and the operator must be able to stop or reset it once more.
    if (stop && active) stop.disabled = false;
    if (reset && active) reset.disabled = false;
    const port = $("#lab-port");
    if (port) port.textContent = active ? `:${data.port}` : "—";
    const started = $("#lab-started");
    if (started && data.started_at) started.textContent = new Date(data.started_at).toLocaleTimeString();
    // The start button is hidden by setLabUI once the lab is live, so it must be
    // re-enabled here: if the lab is stopped later it becomes clickable again.
    if (start && active) { start.disabled = false; start.textContent = "INICIAR LAB"; }
  }

  async function labAction(action) {
    if (!labPanel) return;
    const slug = labPanel.dataset.slug;
    const button = $(`.js-lab-${action}`, labPanel);
    if (action === "reset" && !window.confirm("Reiniciar este lab? Todo o estado interno e as evidências de objetivo serão destruídos.")) return;
    if (button) { button.disabled = true; button.textContent = action === "start" ? "PROVISIONANDO…" : "PROCESSANDO…"; }
    try {
      if (action === "start") {
        const state = $(".lab-state", labPanel);
        if (state) { state.className = "lab-state starting"; state.innerHTML = '<span class="status-dot"></span>PROVISIONANDO'; }
      }
      const data = await postJSON(`/api/challenges/${slug}/${action}`);
      setLabUI(data);
      toast(action === "start" ? "Lab provisionado. O alvo está no ar." : action === "reset" ? "Lab reiniciado em estado limpo." : "Lab parado.", "ok");
      if (action === "start") {
        clearInterval(labPoll);
        let attempts = 0;
        labPoll = setInterval(async () => {
          attempts += 1;
          try {
            const response = await fetch(`/api/challenges/${slug}/status`, { credentials: "same-origin" });
            const status = await response.json();
            setLabUI(status);
            // Poll until the lab answers, not until the row says "active": the
            // process takes a second or two to bind its port, and a click on
            // "abrir alvo" before that lands on a closed port.
            if (!status.active || attempts > 20) clearInterval(labPoll);
          } catch (_) {
            clearInterval(labPoll);
            if (button) { button.disabled = false; button.textContent = "INICIAR LAB"; }
            toast("Não foi possível confirmar o estado do lab. Recarregue a página.", "error", 6000);
          }
        }, 1000);
      }
    } catch (error) {
      toast(error.message, "error", 6000);
      if (button) { button.disabled = false; button.textContent = action === "start" ? "INICIAR LAB" : action === "stop" ? "PARAR" : "RESET"; }
      const state = $(".lab-state", labPanel);
      if (state) { state.className = "lab-state"; state.innerHTML = '<span class="status-dot"></span>PARADO'; }
    }
  }

  $$(".js-lab-start").forEach((button) => button.addEventListener("click", () => labAction("start")));
  $$(".js-lab-stop").forEach((button) => button.addEventListener("click", () => labAction("stop")));
  $$(".js-lab-reset").forEach((button) => button.addEventListener("click", () => labAction("reset")));

  /* -------------------------------- activity time ---------------------------- */
  const challengeSlug = document.body.dataset.challengeSlug;
  if (challengeSlug && csrf) {
    const heartbeat = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const data = await postJSON(`/api/challenges/${challengeSlug}/heartbeat`, { seconds: 30 });
        const elapsed = $("#time-spent");
        if (elapsed) elapsed.textContent = formatDuration(data.time_spent_seconds);
      } catch (_) { /* session ended; ignore */ }
    };
    setInterval(heartbeat, 30000);
  }

  function formatDuration(seconds) {
    seconds = Number(seconds || 0);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
  }

  /* ---------------------------------- notes ---------------------------------- */
  const saveNotes = $(".js-save-notes");
  if (saveNotes) {
    saveNotes.addEventListener("click", async () => {
      const slug = saveNotes.dataset.slug;
      const notes = $("#notes-area")?.value || "";
      const status = $(".notes-status");
      saveNotes.disabled = true;
      try {
        await postJSON(`/api/challenges/${slug}/notes`, { notes });
        if (status) status.textContent = "salvo agora";
        toast("Anotações do operador salvas.", "ok", 2200);
      } catch (error) {
        toast(error.message, "error");
      } finally {
        saveNotes.disabled = false;
      }
    });
  }

  /* ------------------------------ confirmations ------------------------------ */
  $$("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  /* ------------------------------- environment actions ----------------------- */
  $$(".js-env-action").forEach((button) => {
    button.addEventListener("click", async () => {
      const slug = button.dataset.slug;
      const action = button.dataset.action;
      if (action === "reset" && !window.confirm("Reiniciar este lab? O estado interno e as evidências de objetivo serão destruídos.")) return;
      button.disabled = true;
      const oldText = button.textContent;
      button.textContent = "PROCESSANDO…";
      try {
        await postJSON(`/api/challenges/${slug}/${action}`);
        toast(action === "reset" ? "Lab reiniciado. Recarregando o estado do ambiente." : "Lab parado.", "ok");
        setTimeout(() => window.location.reload(), 500);
      } catch (error) {
        toast(error.message, "error");
        button.disabled = false;
        button.textContent = oldText;
      }
    });
  });

  /* --------------------------------- print ---------------------------------- */
  // Certificado de trilha: `onclick` inline é bloqueado pela CSP.
  $$(".js-print").forEach((button) => button.addEventListener("click", () => window.print()));

  /* ------------------------------ toggles (trilhas) --------------------------- */
  // Movido dos templates (learning_paths.html e learning_path_detail.html):
  // script inline é bloqueado pela CSP, que só libera o hash do pre-paint da
  // sidebar. Assim os botões "Nova trilha" e "Notas" voltam a funcionar.
  $$("[data-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const el = document.getElementById(btn.getAttribute("data-toggle"));
      if (!el) return;
      el.hidden = !el.hidden;
      if (btn.hasAttribute("aria-expanded")) btn.setAttribute("aria-expanded", String(!el.hidden));
      if (!el.hidden) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  });
  if (location.hash && location.hash.indexOf("#act-") === 0) {
    const target = document.querySelector(location.hash);
    if (target) {
      target.classList.add("is-focused");
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  /* ------------------------------- env refresh ------------------------------- */
  if (document.body.dataset.page === "environments") {
    setInterval(async () => {
      try {
        const response = await fetch("/api/labs", { credentials: "same-origin" });
        if (response.ok) {
          const data = await response.json();
          const counter = $("#active-env-count");
          // The template renders "(n)"; keep the parentheses the JS otherwise drops.
          if (counter) counter.textContent = `(${data.labs.length})`;
        }
      } catch (_) { /* ignore */ }
    }, 15000);
  }
})();
