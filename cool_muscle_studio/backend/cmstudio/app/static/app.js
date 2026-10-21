/* Cool Muscle Studio — terminal (étape 1). Toutes les URL sont relatives (ingress). */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const api = (path) => new URL(path, document.baseURI).toString();

  const state = {
    ref: null, info: null, ponts: [], slug: null, ws: null, events: [], expert: false,
    history: [], histIdx: -1, suggestions: [], suggestSel: -1, pont: null,
  };
  const MAX_LINES = 3000;

  // ------------------------------------------------------------ utilitaires
  async function getJSON(path) {
    const r = await fetch(api(path));
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
  async function postJSON(path, body) {
    const r = await fetch(api(path), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const text = await r.text();
    if (!r.ok) throw new Error(text || r.statusText);
    return text ? JSON.parse(text) : {};
  }
  function fmtTime(t) {
    const d = new Date(t * 1000);
    return d.toLocaleTimeString("fr-FR", { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
  }
  function notify(msg, isError) {
    const li = document.createElement("div");
    li.className = "line " + (isError ? "err" : "state");
    li.innerHTML = `<span class="t">${fmtTime(Date.now() / 1000)}</span><span class="ms"></span><span class="tag">APP</span><span class="text">${CML.esc(msg)}</span>`;
    $("log").appendChild(li);
    scrollLog();
  }
  function scrollLog() {
    const log = $("log");
    log.scrollTop = log.scrollHeight;
  }
  function storageKey(k) { return `cms:${state.slug}:${k}`; }

  // ------------------------------------------------------------ rendu des lignes
  function classify(ev) {
    const cls = ["line", ev.type];
    if (ev.type === "tx") {
      if (ev.origin === "LOCAL") cls.push("local");
      else if (state.pont && ev.origin === state.pont.my_client) cls.push("mine");
      else cls.push("other");
    }
    if (ev.type === "rx") {
      if (ev.echo) cls.push("echo");
      if (/^Ux\./.test(ev.line)) cls.push("ux");
    }
    return cls.join(" ");
  }
  function tagOf(ev) {
    switch (ev.type) {
      case "rx": return ev.echo ? "RX écho" : "RX";
      case "tx": return "TX " + (ev.origin === "LOCAL" ? "ESP32" : ev.origin + (state.pont && ev.origin === state.pont.my_client ? " (moi)" : ""));
      case "state": return "ÉTAT";
      case "refused": return "REFUS";
      case "err": return "ERREUR";
      case "conn": return "PONT";
      default: return ev.type.toUpperCase();
    }
  }
  function textOf(ev) {
    switch (ev.type) {
      case "state": return `mode ${ev.mode === "MAINT" ? "maintenance" : "normal"}${ev.busy ? ", en mouvement" : ""}${ev.origin === "hello" ? " (connexion)" : ""}`;
      case "refused": return `maintenance refusée : ${{ MOVING: "mouvement en cours", STARTUP: "démarrage en cours", ALARM: "moteur en alarme" }[ev.line] || ev.line}`;
      case "err": return `${ev.code} ${ev.line}`;
      case "conn": return ev.origin === "connecte" ? "connecté au pont" : "déconnecté du pont";
      default: return ev.line;
    }
  }
  function visible(ev) {
    if (!$("f-local").checked && ev.type === "tx" && ev.origin === "LOCAL") return false;
    if (!$("f-echo").checked && ev.type === "rx" && ev.echo) return false;
    const q = $("f-search").value.trim().toLowerCase();
    if (q && !textOf(ev).toLowerCase().includes(q)) return false;
    return true;
  }
  function render(ev) {
    const div = document.createElement("div");
    div.className = classify(ev);
    div.dataset.seq = ev.seq;
    const text = textOf(ev);
    const body = (ev.type === "rx" || ev.type === "tx") ? CML.highlight(text) : CML.esc(text);
    div.innerHTML = `<span class="t">${fmtTime(ev.t)}</span><span class="ms">${ev.ms != null ? ev.ms : ""}</span><span class="tag">${CML.esc(tagOf(ev))}</span><span class="text">${body}</span>`;
    div.classList.toggle("hidden", !visible(ev));
    return div;
  }
  function appendEvent(ev) {
    state.events.push(ev);
    if (state.events.length > MAX_LINES) state.events.shift();
    const log = $("log");
    const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 30;
    log.appendChild(render(ev));
    while (log.children.length > MAX_LINES) log.removeChild(log.firstChild);
    if (atBottom) scrollLog();
  }
  function rerender() {
    const log = $("log");
    log.innerHTML = "";
    for (const ev of state.events) log.appendChild(render(ev));
    scrollLog();
  }

  // ------------------------------------------------------------ état du pont
  function applyState(p) {
    state.pont = p;
    const conn = $("conn-badge");
    conn.textContent = p.connected ? "connecté" : "déconnecté" + (p.last_error ? ` (${p.last_error})` : "");
    conn.className = "badge " + (p.connected ? "" : "off");
    const mode = $("mode-badge");
    mode.textContent = p.mode === "MAINT" ? "MAINTENANCE" : "normal";
    mode.className = "badge " + (p.mode === "MAINT" ? "maint" : "");
    $("busy-badge").classList.toggle("hidden", !p.busy);
    $("maint-btn").textContent = p.mode === "MAINT" ? "Quitter la maintenance" : "Mode maintenance";
    $("maint-btn").classList.toggle("active", p.mode === "MAINT");
    $("maint-btn").disabled = !p.connected;
    $("detect-btn").disabled = !p.connected;
    $("send-btn").disabled = !p.connected;
  }
  function updateFromEvent(ev) {
    if (!state.pont) return;
    if (ev.type === "state") { state.pont.mode = ev.mode; state.pont.busy = ev.busy; state.pont.connected = true; applyState(state.pont); }
    if (ev.type === "conn") { state.pont.connected = ev.origin === "connecte"; applyState(state.pont); }
  }

  // ------------------------------------------------------------ websocket
  function connectWS() {
    if (state.ws) { state.ws.onclose = null; state.ws.close(); state.ws = null; }
    const url = new URL(`api/ponts/${state.slug}/ws`, document.baseURI);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(url.toString());
    state.ws = ws;
    ws.onmessage = (m) => {
      const data = JSON.parse(m.data);
      if (data.type === "snapshot") {
        state.events = [];
        applyState(data.pont);
        for (const ev of data.historique) state.events.push(ev);
        rerender();
        return;
      }
      if (data.type === "pong") return;
      appendEvent(data);
      updateFromEvent(data);
      if (data.type === "tx" && state.pont && !state.pont.my_client && data.origin !== "LOCAL") {
        // le serveur apprend notre nom de client ; on le relit bientôt
        setTimeout(refreshState, 300);
      }
    };
    ws.onclose = () => { notify("liaison avec le serveur perdue, nouvelle tentative…", true); setTimeout(() => { if (state.ws === ws) connectWS(); }, 2000); };
  }
  async function refreshState() {
    try {
      const before = state.pont && state.pont.my_client;
      applyState(await getJSON(`api/ponts/${state.slug}`));
      if (state.pont.my_client && state.pont.my_client !== before) rerender();  // « (moi) » sur nos lignes
    } catch (e) { /* ignoré */ }
  }

  // ------------------------------------------------------------ envoi
  function needsConfirm(line) {
    if (state.expert) return false;
    if (CML.isReadOnly(line)) return false;
    return true;
  }
  async function send(line, origine) {
    line = line.trim();
    if (!line) return;
    if (needsConfirm(line) && !line.startsWith("*")) {
      const ok = await confirmDialog(line);
      if (!ok) { notify("envoi annulé"); return; }
    }
    try {
      await postJSON(`api/ponts/${state.slug}/tx`, { ligne: line, origine: origine || "terminal" });
      pushHistory(line);
      loadJournal();
    } catch (e) {
      notify(`refusé : ${e.message}`, true);
    }
  }
  function confirmDialog(line) {
    const infos = CML.describe(line, state.ref);
    const danger = infos.map((i) => i.danger);
    const titre = danger.includes("mouvement") ? "Cette commande peut faire bouger le moteur"
      : danger.includes("memoire") ? "Cette commande modifie la mémoire du moteur"
      : danger.includes("arret") ? "Cette commande arrête ou désactive le moteur"
      : "Cette commande modifie la configuration du moteur";
    $("confirm-title").textContent = titre;
    $("confirm-text").textContent = infos.map((i) => i.nom + (i.note ? ` — ${i.note}` : "")).join(" ; ");
    $("confirm-line").textContent = line;
    const warn = infos.map((i) => i.warn).filter(Boolean).join(" ");
    const k = infos.find((i) => i.k);
    let warnText = warn;
    if (k && k.k && k.valeur != null) {
      const p = k.k;
      if (p.min != null && k.valeur < p.min) warnText += ` Valeur ${k.valeur} sous le minimum ${p.min}.`;
      if (p.max != null && k.valeur > p.max) warnText += ` Valeur ${k.valeur} au-dessus du maximum ${p.max}.`;
      if (p.valeurs && Object.keys(p.valeurs).length && !(k.valeur in p.valeurs)) warnText += ` Valeur ${k.valeur} non admise pour K${p.k}.`;
    }
    $("confirm-warn").textContent = warnText;
    $("confirm-warn").classList.toggle("hidden", !warnText);
    if (state.pont && state.pont.mode !== "MAINT") {
      $("confirm-warn").textContent = "Le pont est en mode normal : cette écriture sera refusée. Activez d'abord le mode maintenance. " + warnText;
      $("confirm-warn").classList.remove("hidden");
    }
    return new Promise((resolve) => {
      const dlg = $("confirm");
      dlg.returnValue = "cancel";
      dlg.onclose = () => resolve(dlg.returnValue === "ok");
      dlg.showModal();
    });
  }

  // ------------------------------------------------------------ historique et complétion
  function loadHistory() {
    try { state.history = JSON.parse(localStorage.getItem(storageKey("historique")) || "[]"); } catch (e) { state.history = []; }
    state.histIdx = state.history.length;
  }
  function pushHistory(line) {
    state.history = state.history.filter((h) => h !== line);
    state.history.push(line);
    if (state.history.length > 200) state.history.shift();
    state.histIdx = state.history.length;
    try { localStorage.setItem(storageKey("historique"), JSON.stringify(state.history)); } catch (e) { /* ignoré */ }
  }
  function currentToken(value, caret) {
    const before = value.slice(0, caret);
    const start = before.lastIndexOf(",") + 1;
    return { start, text: before.slice(start).trimStart(), lead: before.slice(start).length - before.slice(start).trimStart().length };
  }
  function buildSuggestions(token) {
    const t = token.toUpperCase();
    if (!t) return [];
    const out = [];
    const ref = state.ref;
    if (t.startsWith("K")) {
      for (const p of ref.parametres_k) {
        const key = `K${p.k}`;
        if (key.startsWith(t) || (t.length > 1 && key === t)) out.push({ cmd: key, desc: `${p.nom}${p.unite && p.unite !== "-" ? " [" + p.unite + "]" : ""}${p.min != null ? ` ${p.min}..${p.max}` : ""}${p.defaut != null ? `, défaut ${p.defaut}` : ""}`, title: p.avertissement || "" });
      }
    }
    if (t.startsWith("?")) {
      for (const q of ref.requetes) if (q.cmd.toUpperCase().startsWith(t)) out.push({ cmd: q.cmd, desc: q.retour });
    }
    for (const c of ref.commandes) {
      const key = c.cmd.replace(/[#n]$/, "").replace(/=$/, "");
      if (key && key.toUpperCase().startsWith(t)) out.push({ cmd: c.cmd, desc: `${c.nom} (${c.danger})`, title: c.note || c.syntaxe || "" });
    }
    if (/^[PSAMTVNRH]$/.test(t)) {
      const fam = ref.registres.find((r) => r.lettre === t);
      if (fam) out.push({ cmd: `${t}n`, desc: `${fam.nom} (${fam.indices})${fam.unite ? " [" + fam.unite + "]" : ""}` });
    }
    return out.slice(0, 10);
  }
  function showSuggestions() {
    const input = $("cmd");
    const tok = currentToken(input.value, input.selectionStart);
    state.suggestions = buildSuggestions(tok.text);
    const ul = $("suggest");
    ul.innerHTML = "";
    if (!state.suggestions.length) { ul.classList.add("hidden"); state.suggestSel = -1; return; }
    state.suggestions.forEach((s, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="cmd">${CML.esc(s.cmd)}</span><span class="desc">${CML.esc(s.desc)}</span>`;
      if (s.title) li.title = s.title;
      li.onmousedown = (e) => { e.preventDefault(); acceptSuggestion(i); };
      ul.appendChild(li);
    });
    state.suggestSel = 0;
    ul.children[0].classList.add("sel");
    ul.classList.remove("hidden");
  }
  function acceptSuggestion(i) {
    const s = state.suggestions[i];
    if (!s) return;
    const input = $("cmd");
    const tok = currentToken(input.value, input.selectionStart);
    let text = s.cmd.replace(/[#n]$/, "");
    const after = input.value.slice(input.selectionStart);
    input.value = input.value.slice(0, tok.start + tok.lead) + text + after;
    input.selectionStart = input.selectionEnd = tok.start + tok.lead + text.length;
    $("suggest").classList.add("hidden");
    state.suggestions = [];
    updatePreview();
    input.focus();
  }
  function updatePreview() {
    const v = $("cmd").value;
    $("preview").innerHTML = v ? CML.highlight(v) : '<span class="muted">tapez une commande CML, ↑/↓ historique, Tab complète</span>';
  }

  // ------------------------------------------------------------ actions
  async function toggleMaint() {
    const on = !(state.pont && state.pont.mode === "MAINT");
    $("maint-btn").disabled = true;
    try {
      const r = await postJSON(`api/ponts/${state.slug}/maintenance`, { actif: on });
      if (!r.ok) notify(`maintenance refusée : ${{ MOVING: "mouvement en cours", STARTUP: "démarrage en cours", ALARM: "moteur en alarme", TIMEOUT: "pas de réponse du pont" }[r.info] || r.info}`, true);
    } catch (e) { notify(e.message, true); }
    $("maint-btn").disabled = false;
    refreshState();
  }
  async function detect() {
    $("detect-btn").disabled = true;
    $("motors").innerHTML = '<li class="muted">détection en cours (jusqu\'à 15 identifiants)…</li>';
    try {
      const r = await postJSON(`api/ponts/${state.slug}/detecter?max=15`);
      $("motors").innerHTML = r.moteurs.length ? r.moteurs.map((m) => `<li><b>Moteur ${m.id}</b> — <code>${CML.esc(m.info)}</code></li>`).join("") : '<li class="muted">aucun moteur n\'a répondu</li>';
    } catch (e) { $("motors").innerHTML = `<li class="warn">${CML.esc(e.message)}</li>`; }
    $("detect-btn").disabled = false;
  }
  async function loadJournal() {
    try {
      const j = await getJSON("api/journal?limit=15");
      $("journal").innerHTML = j.length ? j.map((e) => `<li><span class="muted">${CML.esc(e.t.slice(11, 19))}</span> <code>${CML.esc(e.ligne)}</code> <span class="muted">${CML.esc(e.utilisateur)}</span></li>`).join("") : '<li class="muted">aucune écriture</li>';
    } catch (e) { /* ignoré */ }
  }
  function exportLog() {
    const lines = state.events.filter(visible).map((ev) => `${new Date(ev.t * 1000).toISOString()}\t${ev.ms != null ? ev.ms : ""}\t${tagOf(ev)}\t${textOf(ev)}`);
    const blob = new Blob(["horodatage\tms_esp32\ttype\tligne\n" + lines.join("\n") + "\n"], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `cool-muscle-${state.slug}-${new Date().toISOString().replace(/[:.]/g, "-")}.txt`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  // ------------------------------------------------------------ initialisation
  function selectBridge(slug) {
    state.slug = slug;
    loadHistory();
    state.expert = localStorage.getItem(storageKey("expert")) === "1" || (state.info && state.info.mode_expert);
    $("expert").checked = state.expert;
    connectWS();
    refreshState();
  }
  async function init() {
    state.ref = await getJSON("api/reference");
    state.info = await getJSON("api/info");
    $("version").textContent = "v" + state.info.version;
    $("user").textContent = state.info.utilisateur ? state.info.utilisateur : "";
    state.ponts = await getJSON("api/ponts");
    const sel = $("bridge-select");
    sel.innerHTML = state.ponts.map((p) => `<option value="${p.slug}">${CML.esc(p.nom)} (${CML.esc(p.hote)}:${p.port})</option>`).join("");
    if (!state.ponts.length) { notify("aucun pont configuré : ajoutez-en dans les options de l'app", true); return; }
    sel.onchange = () => selectBridge(sel.value);
    selectBridge(state.ponts[0].slug);
    loadJournal();

    const input = $("cmd");
    input.addEventListener("input", () => { updatePreview(); showSuggestions(); });
    input.addEventListener("keydown", (e) => {
      const ul = $("suggest");
      if (!ul.classList.contains("hidden")) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          const n = state.suggestions.length;
          state.suggestSel = (state.suggestSel + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
          [...ul.children].forEach((li, i) => li.classList.toggle("sel", i === state.suggestSel));
          return;
        }
        if (e.key === "Tab") { e.preventDefault(); acceptSuggestion(state.suggestSel); return; }
        if (e.key === "Escape") { ul.classList.add("hidden"); return; }
      }
      if (e.key === "Enter") {
        e.preventDefault();
        ul.classList.add("hidden");
        const line = input.value;
        input.value = "";
        updatePreview();
        send(line);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (state.histIdx > 0) { state.histIdx--; input.value = state.history[state.histIdx] || ""; updatePreview(); }
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        if (state.histIdx < state.history.length) { state.histIdx++; input.value = state.history[state.histIdx] || ""; updatePreview(); }
      }
    });
    $("send-btn").onclick = () => { const line = input.value; input.value = ""; updatePreview(); send(line); };
    $("estop-btn").onclick = () => { send("*", "arret-urgence"); $("estop-info").textContent = "arrêt d'urgence envoyé à " + new Date().toLocaleTimeString("fr-FR"); };
    $("estop-cancel-btn").onclick = () => send("*1", "arret-urgence");
    $("maint-btn").onclick = toggleMaint;
    $("detect-btn").onclick = detect;
    $("clear-btn").onclick = () => { state.events = []; $("log").innerHTML = ""; };
    $("export-btn").onclick = exportLog;
    for (const id of ["f-local", "f-echo"]) $(id).onchange = rerender;
    $("f-search").oninput = rerender;
    $("f-wrap").onchange = () => $("log").classList.toggle("wrap", $("f-wrap").checked);
    $("expert").onchange = () => { state.expert = $("expert").checked; localStorage.setItem(storageKey("expert"), state.expert ? "1" : "0"); };
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && e.ctrlKey) $("estop-btn").click(); });
    input.focus();
  }
  init().catch((e) => notify(`initialisation impossible : ${e.message}`, true));
})();
