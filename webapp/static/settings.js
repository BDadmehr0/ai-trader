/*
 * Settings page logic: schema-driven form, dirty tracking, validation
 * feedback, live probes (news / model / data), CSV upload and the optimizer.
 */
(function () {
  const form = document.getElementById("settingsForm");
  if (!form) return;

  const { toast, api } = window.aiTrader;
  const initial = JSON.parse(document.getElementById("initialValues").textContent);
  const saveBadge = document.getElementById("changedCount");

  // ============================ fields ==============================
  function fields() {
    return Array.from(form.querySelectorAll("[data-key]"));
  }

  function readValue(el) {
    if (el.type === "checkbox") return el.checked;
    return el.value;
  }

  function currentValues() {
    const values = {};
    fields().forEach((el) => {
      values[el.dataset.key] = readValue(el);
    });
    return values;
  }

  function norm(value) {
    if (value === true) return "1";
    if (value === false) return "0";
    if (value === null || value === undefined) return "";
    const text = String(value).trim();
    if (text.startsWith("[") || text.startsWith("{")) {
      try {
        return JSON.stringify(JSON.parse(text));
      } catch (error) {
        return text;
      }
    }
    const asNumber = Number(text);
    if (text !== "" && !Number.isNaN(asNumber)) return String(asNumber);
    return text;
  }

  function refreshDirty() {
    const values = currentValues();
    let changed = 0;
    fields().forEach((el) => {
      const key = el.dataset.key;
      const isChanged = norm(values[key]) !== norm(el.dataset.default);
      el.closest(".field")?.classList.toggle("changed", isChanged);
      if (isChanged) changed += 1;
    });
    if (saveBadge) {
      saveBadge.textContent = changed ? `${changed} changed` : "no changes";
      saveBadge.classList.toggle("is-on", changed > 0);
    }
    document.getElementById("saveButton").disabled = changed === 0;
    return changed;
  }

  form.addEventListener("input", (event) => {
    const el = event.target;
    // keep number + range pairs in sync
    const pair = el.dataset.pair;
    if (pair) {
      const other = form.querySelector(`[data-key="${pair}"]`) || form.querySelector(`[data-pair="${el.dataset.key}"]`);
      if (other && other.value !== el.value) other.value = el.value;
    }
    if (el.dataset.key) {
      clearFieldError(el.dataset.key);
      refreshDirty();
    }
  });
  form.addEventListener("change", refreshDirty);

  function showErrors(errors) {
    Object.entries(errors || {}).forEach(([key, message]) => {
      const el = form.querySelector(`[data-key="${key}"]`);
      const box = el ? el.closest(".field") : null;
      if (box) {
        box.classList.add("invalid");
        let note = box.querySelector(".field-error");
        if (!note) {
          note = document.createElement("div");
          note.className = "field-error";
          box.appendChild(note);
        }
        note.textContent = message;
      }
    });
  }

  function clearFieldError(key) {
    const el = form.querySelector(`[data-key="${key}"]`);
    const box = el ? el.closest(".field") : null;
    if (box) {
      box.classList.remove("invalid");
      const note = box.querySelector(".field-error");
      if (note) note.remove();
    }
  }

  // ============================ tabs =================================
  const tabs = document.querySelectorAll(".tab");
  function openTab(id) {
    tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === id));
    document.querySelectorAll(".group-panel").forEach((panel) => {
      const active = panel.id === `group-${id}`;
      panel.classList.toggle("active", active);
      panel.classList.toggle("hidden", !active);
    });
    if (id) history.replaceState(null, "", `#${id}`);
  }
  tabs.forEach((tab) => tab.addEventListener("click", (event) => {
    event.preventDefault();
    openTab(tab.dataset.tab);
  }));
  openTab((location.hash || "").slice(1) || (tabs[0] && tabs[0].dataset.tab));

  // ============================ save =================================
  async function save() {
    const values = currentValues();
    const changed = {};
    Object.entries(values).forEach(([key, value]) => {
      if (norm(value) !== norm(initial[key])) changed[key] = value;
    });
    if (!Object.keys(changed).length) {
      toast("nothing to save");
      return false;
    }
    try {
      const result = await api.post("/api/settings", { values: changed });
      Object.assign(initial, values);
      fields().forEach((el) => {
        if (el.dataset.key in values) el.dataset.default = String(values[el.dataset.key]);
      });
      refreshDirty();
      toast(`saved ${Object.keys(changed).length} setting(s) → ${result.file}`, "ok");
      return true;
    } catch (error) {
      toast(error.message, "error");
      if (/^[\w_]+:/.test(error.message)) {
        const errors = {};
        error.message.split("; ").forEach((part) => {
          const index = part.indexOf(": ");
          if (index > 0) errors[part.slice(0, index)] = part.slice(index + 2);
        });
        showErrors(errors);
      }
      return false;
    }
  }

  document.getElementById("saveButton").addEventListener("click", save);
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      save();
    }
  });

  document.getElementById("revertButton").addEventListener("click", () => location.reload());

  document.getElementById("resetButton").addEventListener("click", async () => {
    if (!confirm("Reset every setting to the built-in defaults? data/settings.json will be deleted.")) return;
    try {
      await api.post("/api/settings/reset", {});
      toast("settings reset — reloading", "ok");
      setTimeout(() => location.reload(), 600);
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // ============================ export / import ======================
  document.getElementById("exportButton")?.addEventListener("click", () => {
    window.open("/api/settings/export", "_blank");
  });

  const importBox = document.getElementById("importBox");
  document.getElementById("importButton")?.addEventListener("click", async () => {
    const text = (importBox?.value || "").trim();
    if (!text) return toast("paste the JSON first", "error");
    try {
      const result = await api.post("/api/settings/import", { json: text });
      toast(`imported ${result.applied} values`, "ok");
      setTimeout(() => location.reload(), 700);
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // ============================ probes ===============================
  function resultBox(name) {
    return document.querySelector(`[data-result="${name}"]`);
  }

  async function runProbe(path, target, render) {
    const box = resultBox(target);
    if (box) box.innerHTML = '<div class="probe loading">running…</div>';
    const payload = { values: currentValues(), symbol: document.getElementById("probeSymbol")?.value };
    try {
      const data = await api.post(path, payload);
      if (box) box.innerHTML = render(data);
      return data;
    } catch (error) {
      if (box) box.innerHTML = `<div class="probe error">${error.message}</div>`;
      return null;
    }
  }

  document.querySelectorAll("[data-probe]").forEach((button) => {
    button.addEventListener("click", () => {
      const kind = button.dataset.probe;
      if (kind === "llm") {
        runProbe("/api/settings/test/llm", "llm", (data) => {
          const rows = (data.results || []).map((row) =>
            `<li><span class="${row.score > 0.05 ? "win" : row.score < -0.05 ? "loss" : "muted"}">${(row.score >= 0 ? "+" : "") + row.score.toFixed(2)}</span>
             <b>${row.method}</b> — ${row.headline}${row.reason ? ` <span class="muted">(${row.reason})</span>` : ""}</li>`).join("");
          const ping = data.ping || {};
          return `<div class="probe ${data.ok ? "ok" : "error"}">
            <div>engine: <b>${data.provider}</b> · model: <b>${data.model || "—"}</b> · ${ping.latency_ms || "?"} ms</div>
            <div class="muted">${ping.detail || data.detail || ""}</div>
            ${data.hint ? `<div class="warn-text">💡 ${data.hint}</div>` : ""}
            <ul class="probe-list">${rows}</ul>
            ${data.stats ? `<div class="muted tiny">cached ${data.stats.cached || 0} · requested ${data.stats.requested || 0} · fallbacks ${data.stats.fallbacks || 0} · llm ${data.stats.llm_ms || 0} ms</div>` : ""}
          </div>`;
        });
      } else if (kind === "news") {
        runProbe("/api/settings/test/news", "news", (data) => {
          const news = data.news || {};
          const items = (news.items || []).slice(0, 8).map((item) =>
            `<li><span class="${item.score > 0.05 ? "win" : item.score < -0.05 ? "loss" : "muted"}">${(item.score >= 0 ? "+" : "") + item.score.toFixed(2)}</span>
             <a class="text-accent hover:underline" href="${item.url}" target="_blank" rel="noopener">${item.headline}</a>
             <span class="muted">${item.source} · ${item.method}</span></li>`).join("");
          return `<div class="probe ${news.available ? "ok" : "error"}">
            <div><b>${news.bias || "—"} ${news.sentiment !== undefined ? news.sentiment.toFixed(2) : ""}</b>
              · status ${news.status} · provider ${news.provider} · ${news.item_count} items · conf ${news.confidence}%</div>
            ${news.fear_greed ? `<div class="muted">Fear &amp; Greed ${news.fear_greed.value} (${news.fear_greed.label})</div>` : ""}
            <ul class="probe-list">${items || '<li class="muted">no headlines matched</li>'}</ul>
            ${(news.notes || []).length ? `<div class="muted tiny">${news.notes.join(" · ")}</div>` : ""}
          </div>`;
        });
      } else if (kind === "derivatives") {
        const box = resultBox("derivatives");
        if (box) box.innerHTML = '<div class="probe loading">asking futures endpoints…</div>';
        api.get("/api/derivatives?refresh=1")
          .then((data) => {
            if (!box) return;
            const rows = Object.entries(data)
              .filter(([key]) => !["factors", "notes", "gates"].includes(key))
              .map(([key, value]) => `<li><span class="muted">${key}</span> ${typeof value === "number" ? value.toFixed(4).replace(/0+$/, "") : value}</li>`)
              .join("");
            box.innerHTML = `<div class="probe ${data.available ? "ok" : "error"}">
              <div>${data.available ? `score ${data.score} · ${data.crowd_state}` : "not available (" + data.status + ")"}</div>
              <ul class="probe-list">${(data.factors || []).map((f) => `<li>${f}</li>`).join("") || '<li class="muted">no positioning factors</li>'}</ul>
              ${(data.notes || []).length ? `<div class="muted tiny">${data.notes.join(" · ")}</div>` : ""}
              <details><summary class="muted tiny">raw</summary><pre class="tiny font-mono whitespace-pre-wrap">${rows}</pre></details></div>`;
          })
          .catch((error) => box && (box.innerHTML = `<div class="probe error">${error.message}</div>`));
      } else if (kind === "data") {
        runProbe("/api/settings/test/data", "data", (data) => {
          const frames = Object.entries(data.timeframes || {}).map(([tf, row]) =>
            `<li><b>${tf}</b> · ${row.rows} candles · ${row.start} → ${row.end} · last ${row.last_close}</li>`).join("");
          const csv = data.csv
            ? `<div class="csv-profile"><b>${data.csv.ok ? "CSV ok" : "CSV problem"}</b>
                ${data.csv.ok ? `${data.csv.rows} rows · native ${data.csv.timeframe} · ${data.csv.span_days} days · ${data.csv.change_pct}% change` : data.csv.error}
               </div>` : "";
          return `<div class="probe ${data.ok ? "ok" : "error"}">
            <div>source: <b>${data.source}</b> · live: ${data.live ? "yes" : "no"}${data.error ? " · " + data.error : ""}</div>
            <div class="muted tiny">supported: ${(data.supported_timeframes || []).join(", ")}</div>
            <ul class="probe-list">${frames}</ul>${csv}
          </div>`;
        });
      }
    });
  });

  // ============================ csv upload ===========================
  const uploadForm = document.getElementById("uploadForm");

  async function uploadCsv() {
    if (!uploadForm) return;
    const fileInput = uploadForm.querySelector('input[type="file"]');
    if (!fileInput.files.length) return toast("pick a .csv first", "error");

    const body = new FormData();
    body.append("file", fileInput.files[0]);
    body.append("timeframe", uploadForm.querySelector('[name="timeframe"]').value || "");
    if (uploadForm.querySelector('[name="activate"]').checked) body.append("activate", "1");

    try {
      const response = await fetch("/api/data/upload", { method: "POST", body });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || (data.errors && Object.values(data.errors).join("; ")) || "upload failed");
      toast(`loaded ${data.file} (${data.profile.rows} candles)`, "ok");
      const pathField = form.querySelector('[data-key="csv_path"]');
      if (pathField) {
        pathField.value = data.file;
        pathField.dispatchEvent(new Event("input", { bubbles: true }));
      }
      refreshDirty();
      loadFiles();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  uploadForm?.querySelector("[data-upload]")?.addEventListener("click", uploadCsv);
  uploadForm?.querySelector('input[name="timeframe"]')?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      uploadCsv();
    }
  });

  async function loadFiles() {
    const list = document.getElementById("csvFiles");
    if (!list) return;
    try {
      const data = await api.get("/api/data/files");
      if (!data.files.length) {
        list.innerHTML = '<div class="muted tiny">no uploaded files yet</div>';
        return;
      }
      list.innerHTML = data.files
        .map(
          (file) => `<div class="csv-row ${data.current === file.path ? "active" : ""}">
            <button class="csv-use" data-path="${file.path}">${data.current === file.path ? "✓ active" : "use"}</button>
            <span class="csv-name">${file.name}</span>
            <span class="muted tiny">${file.size_kb} KB · ${file.modified}</span>
          </div>`
        )
        .join("");
      list.querySelectorAll(".csv-use").forEach((button) =>
        button.addEventListener("click", async () => {
          try {
            await api.post("/api/data/use", { path: button.dataset.path });
            toast("data source switched to " + button.dataset.path, "ok");
            setTimeout(() => location.reload(), 500);
          } catch (error) {
            toast(error.message, "error");
          }
        })
      );
    } catch (error) {
      list.innerHTML = `<div class="muted tiny">${error.message}</div>`;
    }
  }

  document.getElementById("csvClear")?.addEventListener("click", async () => {
    try {
      await api.post("/api/data/use", { clear: true });
      toast("back to exchange/auto source", "ok");
      setTimeout(() => location.reload(), 500);
    } catch (error) {
      toast(error.message, "error");
    }
  });

  loadFiles();

  // ============================ scoring preview ======================
  function updateWeightBars() {
    const weights = {};
    document.querySelectorAll('[data-key^="weight_"]').forEach((el) => {
      weights[el.dataset.key.replace("weight_", "")] = Number(el.value) || 0;
    });
    const total = Object.values(weights).reduce((sum, value) => sum + value, 0) || 1;
    const box = document.getElementById("weightBars");
    if (!box) return;
    box.innerHTML = Object.entries(weights)
      .sort((a, b) => b[1] - a[1])
      .map(
        ([name, value]) => `<div class="wrow">
          <span class="wlabel">${name}</span>
          <span class="wtrack"><span class="wfill" style="width:${((value / total) * 100).toFixed(1)}%"></span></span>
          <span class="wpct">${((value / total) * 100).toFixed(0)}%</span>
        </div>`
      )
      .join("");
  }
  document.querySelectorAll('[data-key^="weight_"]').forEach((el) => el.addEventListener("input", updateWeightBars));
  updateWeightBars();

  document.getElementById("calibrationBox")?.addEventListener("click", async () => {
    try {
      const data = await api.get("/api/journal?recalc=1");
      const cal = data.calibration || {};
      const rows = Object.entries(cal.components || {}).map(([name, row]) =>
        `<li><b>${name}</b> ic ${row.ic} × ${cal.multipliers[name] || 1.0} <span class="muted">(${row.samples} samples)</span></li>`).join("");
      document.getElementById("calibrationDetails").innerHTML =
        `<div class="probe ${cal.meta.active ? "ok" : ""}">${cal.meta.note || `${cal.meta.samples} evaluated signals · win rate ${cal.meta.win_rate ?? "—"}`}</div>
         <ul class="probe-list">${rows || '<li class="muted">not enough data yet</li>'}</ul>`;
    } catch (error) {
      toast(error.message, "error");
    }
  });

  // ============================ optimizer ============================
  const optimizeButton = document.getElementById("optimizeRun");
  optimizeButton?.addEventListener("click", async () => {
    const rangesEl = form.querySelector('[data-key="optimizer_ranges"]');
    let ranges = rangesEl ? rangesEl.value : "";
    if (ranges && typeof ranges === "string" && ranges.trim()) {
      try {
        ranges = JSON.parse(ranges);
      } catch (error) {
        return toast("optimizer ranges must be valid JSON", "error");
      }
    } else {
      ranges = {};
    }

    optimizeButton.disabled = true;
    optimizeButton.textContent = "searching…";
    const box = document.getElementById("optimizeResults");
    box.innerHTML = '<div class="probe loading">building candles and running trials — this can take a while…</div>';

    try {
      await save().catch(() => false);
      const data = await api.post("/api/backtest/optimize", {
        trials: Number(form.querySelector('[data-key="optimizer_trials"]').value) || 12,
        mode: form.querySelector('[data-key="optimizer_mode"]').value,
        objective: form.querySelector('[data-key="optimizer_objective"]').value,
        ranges: ranges,
        symbol: document.getElementById("probeSymbol")?.value,
      });
      renderTrials(data);
    } catch (error) {
      box.innerHTML = `<div class="probe error">${error.message}</div>`;
    } finally {
      optimizeButton.disabled = false;
      optimizeButton.textContent = "run optimizer";
    }
  });

  function renderTrials(data) {
    const box = document.getElementById("optimizeResults");
    if (!data || !data.trials || !data.trials.length) {
      box.innerHTML = `<div class="probe error">${(data && data.error) || "no trials produced trades — widen the ranges or add more candles"}</div>`;
      return;
    }
    const rows = data.trials
      .slice(0, 12)
      .map((trial, index) => {
        const params = Object.entries(trial.params)
          .map(([key, value]) => `<span class="pchip">${key}=${value}</span>`)
          .join("");
        return `<tr class="${index === 0 ? "best" : ""}">
          <td>${index + 1}</td>
          <td class="params-cell">${params}</td>
          <td>${trial.train_objective}</td>
          <td>${trial.test_objective > -1e8 ? trial.test_objective : "n/a"}</td>
          <td>${(trial.train || {}).total_trades || 0}/${(trial.test || {}).total_trades || 0}</td>
          <td>${((trial.train || {}).win_rate || 0).toFixed(0)}%</td>
          <td>${((trial.test || {}).total_return || 0).toFixed(2)}%</td>
          <td><button class="mini-btn apply" data-index="${index}">apply</button></td>
        </tr>`;
      })
      .join("");

    box.innerHTML = `
      <div class="probe ok">${data.trials.length} trials on ${data.rows} candles
        (train ${data.train_rows} / test ${data.test_rows}) · objective <b>${data.objective}</b> · overfit gap ${data.overfit_gap ?? "—"}</div>
      <div class="table-wrap"><table class="data-table opt-table">
        <thead><tr><th>#</th><th>parameters</th><th>train</th><th>test</th><th>trades t/x</th><th>win</th><th>test return</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <div class="muted tiny">tip: trust the <b>test</b> column; a big positive train score with a negative test score is curve-fitting.</div>`;

    box.querySelectorAll(".apply").forEach((button) =>
      button.addEventListener("click", async () => {
        const trial = data.trials[Number(button.dataset.index)];
        try {
          const result = await api.post("/api/backtest/apply", { params: trial.params });
          toast(result.ok ? "best parameters saved" : "saved with warnings", result.ok ? "ok" : "error");
          setTimeout(() => location.reload(), 700);
        } catch (error) {
          toast(error.message, "error");
        }
      })
    );
  }

  refreshDirty();
})();
