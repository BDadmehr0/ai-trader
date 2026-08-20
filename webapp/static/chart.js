/**
 * Candlestick chart for the AI BTC Trader dashboard.
 *
 * Uses TradingView Lightweight Charts. Renders the OHLCV candles for the
 * selected pair/timeframe and overlays the current trade setup as coloured
 * price lines: Entry, Stop Loss, Take Profit 1 & 2 (plus support/resistance
 * as dashed lines).
 */
(function () {
  if (!window.LightweightCharts) {
    document.getElementById("priceChart").textContent =
      "نمودار به دلیل عدم بارگذاری کتابخانه نمایش داده نشد.";
    return;
  }

  const C = window.AI_TRADER_CHART;
  if (!C || !C.candles || C.candles.length === 0) {
    document.getElementById("priceChart").textContent =
      "داده‌ای برای نمایش نمودار موجود نیست.";
    return;
  }

  const el = document.getElementById("priceChart");
  const height = Math.max(360, Math.min(520, window.innerHeight * 0.5));
  el.style.height = height + "px";

  const chart = LightweightCharts.createChart(el, {
    layout: {
      background: { color: "#0d1117" },
      textColor: "#8b949e",
      fontFamily: "Vazirmatn, Tahoma, sans-serif",
    },
    grid: {
      vertLines: { color: "#161b22" },
      horzLines: { color: "#161b22" },
    },
    rightPriceScale: {
      borderColor: "#2d333b",
    },
    timeScale: {
      borderColor: "#2d333b",
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 6,
    },
    crosshair: {
      mode: LightweightCharts.CrosshairMode.Normal,
    },
  });

  // --- Volume histogram (bottom) ---
  const volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "volume",
    lastValueVisible: false,
  });
  chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

  const volData = C.candles.map((c) => ({
    time: c.time,
    value: c.volume,
    color: c.close >= c.open ? "rgba(63,185,80,0.35)" : "rgba(248,81,73,0.35)",
  }));
  volumeSeries.setData(volData);

  // --- Candles (main) ---
  const series = chart.addCandlestickSeries({
    upColor: "#3fb950",
    downColor: "#f85149",
    borderUpColor: "#3fb950",
    borderDownColor: "#f85149",
    wickUpColor: "#3fb950",
    wickDownColor: "#f85149",
  });
  series.setData(
    C.candles.map((c) => ({
      time: c.time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
  );
  chart.timeScale().fitContent();

  // =========================================================
  // Trade setup price lines
  // =========================================================
  const isLong = C.setup.signal === "LONG";
  const isShort = C.setup.signal === "SHORT";
  const legend = [];

  const hasTrade = isLong || isShort;
  const entry = C.setup.entry;
  const stop = C.setup.stop_loss;
  const tp1 = C.setup.take_profit_1;
  const tp2 = C.setup.take_profit_2;

  const fmt = (v) => v.toLocaleString("en-US", { maximumFractionDigits: 2 });

  if (hasTrade) {
    const entryColor = "#58a6ff";   // blue — entry
    const stopColor = "#f85149";    // red — stop loss
    const tpColor = "#3fb950";      // green — take profit

    // Entry — solid blue line
    addLine(series, entry, entryColor, "ورود Entry", 2, LightweightCharts.LineStyle.Solid);
    legend.push(["ورود (Entry)", entryColor, fmt(entry)]);

    // Stop loss — solid red
    addLine(series, stop, stopColor, "حد ضرر Stop", 2, LightweightCharts.LineStyle.Solid);
    legend.push(["حد ضرر (Stop Loss)", stopColor, fmt(stop)]);

    // TP1 — solid green
    addLine(series, tp1, tpColor, "هدف ۱ TP1", 2, LightweightCharts.LineStyle.Solid);
    legend.push(["هدف اول (TP1)", tpColor, fmt(tp1)]);

    // TP2 — dashed green
    addLine(series, tp2, tpColor, "هدف ۲ TP2", 1, LightweightCharts.LineStyle.Dashed);
    legend.push(["هدف دوم (TP2)", tpColor, fmt(tp2)]);
  }

  // Support / resistance — thin dashed grey/yellow lines
  addLine(series, C.levels.resistance_1, "#d29922", "مقاومت ۱", 1, LightweightCharts.LineStyle.Dashed);
  addLine(series, C.levels.resistance_2, "#d29922", "مقاومت ۲", 1, LightweightCharts.LineStyle.Dotted);
  addLine(series, C.levels.support_1, "#8b949e", "حمایت ۱", 1, LightweightCharts.LineStyle.Dashed);
  addLine(series, C.levels.support_2, "#8b949e", "حمایت ۲", 1, LightweightCharts.LineStyle.Dotted);

  // =========================================================
  // Legend
  // =========================================================
  const legendEl = document.getElementById("chartLegend");
  const items = legend.map(
    ([label, color, val]) =>
      `<span class="legend-item"><span class="legend-swatch" style="background:${color}"></span>${label}: <b>${val}</b></span>`
  );
  if (items.length) {
    legendEl.innerHTML = items.join("");
  } else {
    legendEl.innerHTML = '<span class="muted">در حال حاضر سیگنال معاملاتی فعالی وجود ندارد.</span>';
  }

  function addLine(series, price, color, title, width, lineStyle) {
    series.createPriceLine({
      price: price,
      color: color,
      lineWidth: width,
      lineStyle: lineStyle,
      axisLabelVisible: true,
      title: title,
    });
  }

  // Keep chart responsive.
  window.addEventListener("resize", () => {
    chart.applyOptions({ width: el.clientWidth });
  });
})();
