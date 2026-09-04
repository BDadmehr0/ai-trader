/*
 * Candlestick chart with server-computed overlays.
 *
 * The indicator values come from the same Python code that produced the
 * signal (analysis/indicators.py) instead of a browser approximation, so what
 * you see is literally what the model saw. Layers are toggled from the chart
 * toolbar; sub-panes (RSI / MACD / ADX) share the price scale system.
 */
(function () {
  const el = document.getElementById("priceChart");
  const C = window.AI_TRADER_CHART;

  if (!window.LightweightCharts) {
    if (el) el.textContent = "Chart library failed to load (offline?).";
    return;
  }
  if (!C || !C.candles || !C.candles.length) {
    if (el) el.textContent = "No chart data available.";
    return;
  }

  const COLORS = {
    up: "#0ecb81",
    down: "#f6465d",
    blue: "#1e80ff",
    yellow: "#f0b90b",
    purple: "#a26bff",
    grid: "#1e2329",
    border: "#2b3139",
    text: "#848e9c",
  };

  const layers = {
    candles: true,
    volume: true,
    ema: true,
    bb: false,
    vwap: true,
    supertrend: true,
    rsi: false,
    macd: false,
    adx: false,
    signals: true,
    levels: true,
    entries: true,
  };

  const O = C.overlays || {};

  // ============================ chart ==============================
  const height = Math.max(400, Math.min(620, window.innerHeight * 0.55));
  const chart = LightweightCharts.createChart(el, {
    height: height,
    layout: {
      background: { color: "#0b0e11" },
      textColor: COLORS.text,
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    },
    grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
    rightPriceScale: { borderColor: COLORS.border },
    timeScale: { borderColor: COLORS.border, timeVisible: true, secondsVisible: false, rightOffset: 5 },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    localization: { priceFormatter: (price) => (Math.abs(price) >= 1000 ? price.toLocaleString() : price.toLocaleString(undefined, { maximumFractionDigits: 6 })) },
  });

  // ============================ candles =============================
  const candles = chart.addCandlestickSeries({
    upColor: COLORS.up,
    downColor: COLORS.down,
    borderUpColor: COLORS.up,
    borderDownColor: COLORS.down,
    wickUpColor: COLORS.up,
    wickDownColor: COLORS.down,
  });
  candles.setData(C.candles.map((c) => ({ time: c.time, open: c.open, high: c.high, low: c.low, close: c.close })));

  // ============================ volume ==============================
  const volume = chart.addHistogramSeries({ priceScaleId: "volume", lastValueVisible: false, priceFormat: { type: "volume" } });
  volume.setData(C.candles.map((c) => ({ time: c.time, value: c.volume, color: c.close >= c.open ? "rgba(14,203,129,0.35)" : "rgba(246,70,93,0.35)" })));
  chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } });

  // ============================ lines ===============================
  function line(name, options, data) {
    if (!data || !data.length) return null;
    const series = chart.addLineSeries(Object.assign({ priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }, options));
    series.setData(data);
    return series;
  }

  const series = {
    emaFast: line(null, { color: COLORS.blue, lineWidth: 1, title: "EMA fast" }, O.emaFast),
    emaMid: line(null, { color: COLORS.yellow, lineWidth: 1, title: "EMA mid" }, O.emaMid),
    emaSlow: line(null, { color: COLORS.purple, lineWidth: 1, title: "EMA slow" }, O.emaSlow),
    bbUpper: line(null, { color: "rgba(160,170,190,0.55)", lineWidth: 1, title: "BB upper" }, O.bbUpper),
    bbMid: line(null, { color: "rgba(160,170,190,0.3)", lineWidth: 1, lineStyle: 2 }, O.bbMid),
    bbLower: line(null, { color: "rgba(160,170,190,0.55)", lineWidth: 1, title: "BB lower" }, O.bbLower),
    vwap: line(null, { color: "#ff9f43", lineWidth: 2, title: "VWAP" }, O.vwap),
    stUp: line(null, { color: COLORS.up, lineWidth: 2 }, O.superTrendUp),
    stDown: line(null, { color: COLORS.down, lineWidth: 2 }, O.superTrendDown),
  };

  // ============================ sub-panes ===========================
  function pane(scaleId, top, bottom, visible) {
    chart.priceScale(scaleId).applyOptions({
      scaleMargins: { top: top, bottom: bottom },
      visible: !!visible,
      borderColor: COLORS.border,
    });
    return scaleId;
  }

  const rsiScale = pane("rsi", 0.72, 0.02, false);
  const macdScale = pane("macd", 0.72, 0.02, false);
  const adxScale = pane("adx", 0.72, 0.02, false);

  const rsi = line("rsi", { color: COLORS.purple, lineWidth: 1, priceScaleId: rsiScale, title: "RSI" }, O.rsi);
  const rsiOB = rsi && line("rsiOb", { color: "rgba(246,70,93,0.35)", lineWidth: 1, lineStyle: 2, priceScaleId: rsiScale },
    O.rsi.map((p) => ({ time: p.time, value: 70 })));
  const rsiOS = rsi && line("rsiOs", { color: "rgba(14,203,129,0.35)", lineWidth: 1, lineStyle: 2, priceScaleId: rsiScale },
    O.rsi.map((p) => ({ time: p.time, value: 30 })));

  const macdLine = line("macd", { color: COLORS.blue, lineWidth: 1, priceScaleId: macdScale, title: "MACD" }, O.macd);
  const macdSignal = line("macdSig", { color: COLORS.yellow, lineWidth: 1, priceScaleId: macdScale }, O.macdSignal);
  const macdHist = O.macdHist && O.macdHist.length
    ? (() => {
        const hist = chart.addHistogramSeries({ priceScaleId: macdScale, lastValueVisible: false });
        hist.setData(O.macdHist.map((p) => ({ time: p.time, value: p.value, color: p.value >= 0 ? "rgba(14,203,129,0.5)" : "rgba(246,70,93,0.5)" })));
        return hist;
      })()
    : null;

  const adx = line("adx", { color: "#e0d13f", lineWidth: 1, priceScaleId: adxScale, title: "ADX" }, O.adx);
  const adxLevel = adx && line("adxLevel", { color: "rgba(224,209,63,0.35)", lineWidth: 1, lineStyle: 2, priceScaleId: adxScale },
    O.adx.map((p) => ({ time: p.time, value: 20 })));

  // ============================ markers =============================
  if (layers.signals && O.markers && O.markers.length) {
    candles.setMarkers(O.markers);
  }

  // ==================== trade levels + zones ========================
  const priceLines = [];

  function priceLine(seriesRef, price, color, title, style, width) {
    if (!price || price <= 0) return;
    const lineRef = seriesRef.createPriceLine({
      price: price,
      color: color,
      lineWidth: width || 1,
      lineStyle: style === undefined ? LightweightCharts.LineStyle.Dashed : style,
      axisLabelVisible: true,
      title: title,
    });
    priceLines.push(lineRef);
  }

  const setup = C.setup || {};
  const levels = C.levels || {};
  const isLong = C.signal === "LONG";
  const isShort = C.signal === "SHORT";
  const hasTrade = isLong || isShort;

  if (layers.entries && hasTrade) {
    priceLine(candles, setup.entry, "rgba(30,128,255,0.9)", "Entry", LightweightCharts.LineStyle.Solid, 2);
    priceLine(candles, setup.stop_loss, "rgba(246,70,93,0.9)", "SL", LightweightCharts.LineStyle.Solid, 2);
    priceLine(candles, setup.take_profit_1, "rgba(14,203,129,0.9)", "TP1", LightweightCharts.LineStyle.Solid, 2);
    priceLine(candles, setup.take_profit_2, "rgba(14,203,129,0.5)", "TP2", LightweightCharts.LineStyle.Dotted, 1);
  }

  const zones = (levels.zones || []).filter((z) => z && z.price > 0);
  if (layers.levels) {
    if (zones.length) {
      zones.forEach((zone) =>
        priceLine(candles, zone.price, zone.type === "RESISTANCE" ? "rgba(246,70,93,0.6)" : "rgba(14,203,129,0.6)",
          `${zone.type[0]}${zone.touches ? "×" + zone.touches : ""}`, LightweightCharts.LineStyle.Dotted, 1)
      );
    } else {
      priceLine(candles, levels.resistance_1, "rgba(246,70,93,0.6)", "R1", LightweightCharts.LineStyle.Dashed, 1);
      priceLine(candles, levels.resistance_2, "rgba(246,70,93,0.35)", "R2", LightweightCharts.LineStyle.Dotted, 1);
      priceLine(candles, levels.support_1, "rgba(14,203,129,0.6)", "S1", LightweightCharts.LineStyle.Dashed, 1);
      priceLine(candles, levels.support_2, "rgba(14,203,129,0.35)", "S2", LightweightCharts.LineStyle.Dotted, 1);
    }
  }

  // ============================ layer toggles =======================
  const group = (refs, visible) => refs.forEach((ref) => ref && ref.applyOptions({ visible: visible }));

  function applyState() {
    candles.applyOptions({ visible: layers.candles });
    group([volume], layers.volume);
    chart.priceScale("volume").applyOptions({ visible: layers.volume });
    group([series.emaFast, series.emaMid, series.emaSlow], layers.ema);
    group([series.bbUpper, series.bbMid, series.bbLower], layers.bb);
    group([series.vwap], layers.vwap);
    group([series.stUp, series.stDown], layers.supertrend);
    group([rsi, rsiOB, rsiOS], layers.rsi);
    chart.priceScale("rsi").applyOptions({ visible: layers.rsi });
    group([macdLine, macdSignal, macdHist], layers.macd);
    chart.priceScale("macd").applyOptions({ visible: layers.macd });
    group([adx, adxLevel], layers.adx);
    chart.priceScale("adx").applyOptions({ visible: layers.adx });
    if (candles.setMarkers) candles.setMarkers(layers.signals ? (O.markers || []) : []);
    priceLines.forEach((ref) => ref.applyOptions({ visible: layers.levels || layers.entries }));
  }

  document.querySelectorAll(".ovbtn").forEach((button) => {
    button.addEventListener("click", () => {
      const name = button.dataset.layer;
      if (!(name in layers)) return;
      layers[name] = !layers[name];
      button.classList.toggle("active", layers[name]);
      applyState();
      buildLegend();
    });
  });

  // ============================ legend ==============================
  const byTime = new Map();
  ["emaFast", "emaMid", "emaSlow", "rsi", "adx", "vwap", "bbUpper", "bbLower"].forEach((key) => {
    (O[key] || []).forEach((point) => {
      const row = byTime.get(point.time) || {};
      row[key] = point.value;
      byTime.set(point.time, row);
    });
  });

  function short(price) {
    if (price === null || price === undefined) return "—";
    const abs = Math.abs(price);
    return abs >= 1000 ? price.toLocaleString(undefined, { maximumFractionDigits: 1 })
      : abs >= 1 ? price.toFixed(3) : price.toPrecision(4);
  }

  function buildLegend(row, candle) {
    const el = document.getElementById("chartLegend");
    if (!el) return;
    const items = [];
    const summary = O.summary || {};
    const data = candle || C.candles[C.candles.length - 1];

    items.push(`<span class="leg-item"><b>${C.symbol}</b> ${C.tf}</span>`);
    if (data) {
      items.push(`<span class="leg-item ${data.close >= data.open ? "up" : "down"}">O ${short(data.open)} H ${short(data.high)} L ${short(data.low)} C ${short(data.close)}</span>`);
    }
    if (layers.ema) items.push(`<span class="leg-item"><span class="leg-swatch" style="background:${COLORS.blue}"></span>EMA ${short((row || {}).emaFast || summary.ema_fast)}</span>`);
    if (layers.vwap) items.push(`<span class="leg-item"><span class="leg-swatch" style="background:#ff9f43"></span>VWAP ${short((row || {}).vwap)} (${short(summary.vwap_dist_pct)}% gap)</span>`);
    if (layers.rsi) items.push(`<span class="leg-item"><span class="leg-swatch" style="background:${COLORS.purple}"></span>RSI ${short((row || {}).rsi || summary.rsi)}</span>`);
    if (layers.adx) items.push(`<span class="leg-item"><span class="leg-swatch" style="background:#e0d13f"></span>ADX ${short((row || {}).adx || summary.adx)}</span>`);
    if (layers.supertrend) items.push(`<span class="leg-item">SuperTrend ${summary.supertrend_dir > 0 ? "↑" : "↓"}</span>`);
    if (hasTrade) {
      items.push(`<span class="leg-item"><span class="leg-swatch" style="background:${COLORS.blue}"></span>Entry ${short(setup.entry)}</span>`);
      items.push(`<span class="leg-item"><span class="leg-swatch" style="background:${COLORS.down}"></span>SL ${short(setup.stop_loss)} (${setup.stop_distance_pct}%)</span>`);
      items.push(`<span class="leg-item"><span class="leg-swatch" style="background:${COLORS.up}"></span>TP1 ${short(setup.take_profit_1)} · 1:${(setup.risk_reward_1 || 0).toFixed(2)}R</span>`);
    }
    items.push(`<span class="leg-item muted">${C.source}${C.live ? " · live" : " · not live"}</span>`);
    el.innerHTML = items.join("");
  }

  chart.subscribeCrosshairMove((param) => {
    if (!param || !param.time || !param.seriesData) return buildLegend();
    const candle = param.seriesData.get(candles);
    buildLegend(byTime.get(param.time), candle);
  });

  buildLegend();
  applyState();
  chart.timeScale().fitContent();

  window.addEventListener("resize", () => chart.applyOptions({ width: el.clientWidth }));
})();
