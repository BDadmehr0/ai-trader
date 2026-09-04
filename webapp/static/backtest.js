/*
 * Backtest page: equity curve + "optimise on this data" without leaving the page.
 */
(function () {
  const { toast, api } = window.aiTrader;

  // ==================== equity curve ====================
  const el = document.getElementById("equityChart");
  const data = window.AI_TRADER_EQUITY;

  if (el && window.LightweightCharts && Array.isArray(data) && data.length) {
    const chart = LightweightCharts.createChart(el, {
      height: 260,
      layout: { background: { color: "#0b0e11" }, textColor: "#848e9c" },
      grid: { vertLines: { color: "#1e2329" }, horzLines: { color: "#1e2329" } },
      rightPriceScale: { borderColor: "#2b3139" },
      timeScale: { borderColor: "#2b3139", timeVisible: true },
    });
    const series = chart.addAreaSeries({
      lineColor: "#1e80ff",
      topColor: "rgba(30,128,255,0.35)",
      bottomColor: "rgba(30,128,255,0.02)",
      lineWidth: 2,
    });
    series.setData(data.filter((point) => point.time).map((point) => ({ time: point.time, value: point.equity })));
    chart.timeScale().fitContent();
    window.addEventListener("resize", () => chart.applyOptions({ width: el.clientWidth }));
  }

  // ==================== re-run ====================
  document.getElementById("btRun")?.addEventListener("click", () => location.reload());

  // ==================== optimizer ====================
  const button = document.getElementById("btOptimize");
  const box = document.getElementById("optimizeResults");
  const status = document.getElementById("optimizeStatus");

  button?.addEventListener("click", async () => {
    button.disabled = true;
    if (status) status.textContent = "searching…";
    if (box) box.innerHTML = '<div class="probe loading">running walk-forward trials on the current data source…</div>';
    try {
      const data = await api.post("/api/backtest/optimize", {});
      render(data);
      if (status) status.textContent = `${(data.trials || []).length} trials done`;
    } catch (error) {
      if (box) box.innerHTML = `<div class="probe error">${error.message}</div>`;
      if (status) status.textContent = "failed";
    } finally {
      button.disabled = false;
    }
  });

  function render(data) {
    if (!data || !data.trials || !data.trials.length) {
      box.innerHTML = `<div class="probe error">${(data && data.error) || "no usable trials"}</div>`;
      return;
    }
    const rows = data.trials.slice(0, 10).map((trial, index) => {
      const chips = Object.entries(trial.params)
        .map(([key, value]) => `<span class="pchip">${key}=${value}</span>`)
        .join("");
      return `<tr class="${index === 0 ? "best" : ""}">
        <td>${index + 1}</td>
        <td class="params-cell">${chips}</td>
        <td>${trial.train_objective}</td>
        <td>${trial.test_objective > -1e8 ? trial.test_objective : "n/a"}</td>
        <td>${(trial.train || {}).total_trades || 0} / ${(trial.test || {}).total_trades || 0}</td>
        <td>${((trial.train || {}).win_rate || 0).toFixed(0)}%</td>
        <td>${((trial.test || {}).total_return || 0).toFixed(2)}%</td>
        <td>${((trial.test || {}).max_drawdown || 0).toFixed(2)}%</td>
        <td><button class="mini-btn apply" data-index="${index}">apply</button></td>
      </tr>`;
    }).join("");

    box.innerHTML = `
      <div class="probe ${Math.abs(data.overfit_gap || 0) < 40 ? "ok" : "error"}">
        objective <b>${data.objective}</b> · ${data.trials.length} trials · source ${data.source}
        · train ${data.train_rows} / test ${data.test_rows} candles · overfit gap ${data.overfit_gap ?? "—"}
      </div>
      <div class="table-wrap"><table class="data-table opt-table">
        <thead><tr><th>#</th><th>parameters</th><th>train score</th><th>test score</th><th>trades</th><th>win</th><th>test return</th><th>test DD</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <div class="muted tiny">«apply» ذخیره‌اش می‌کند در data/settings.json؛ بعد از آن هم داشبورد و هم بک‌تست با همان پارامترها کار می‌کنند.</div>`;

    box.querySelectorAll(".apply").forEach((node) =>
      node.addEventListener("click", async () => {
        const trial = data.trials[Number(node.dataset.index)];
        try {
          await api.post("/api/backtest/apply", { params: trial.params });
          toast("parameters saved — reloading", "ok");
          setTimeout(() => location.reload(), 700);
        } catch (error) {
          toast(error.message, "error");
        }
      })
    );
  }
})();
