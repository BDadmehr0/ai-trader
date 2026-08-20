/**
 * Professional Candlestick Chart with Overlay Controls
 *
 * Uses TradingView Lightweight Charts with toggleable layers.
 */
(function () {
  if (!window.LightweightCharts) {
    document.getElementById("priceChart").textContent =
      "Chart library failed to load.";
    return;
  }

  const C = window.AI_TRADER_CHART;
  if (!C || !C.candles || C.candles.length === 0) {
    document.getElementById("priceChart").textContent =
      "No chart data available.";
    return;
  }

  // State of overlay layers
  const layerState = {
    candles: true,
    volume: true,
    ema: true,
    rsi: false,
    macd: false,
    signals: true,
    levels: true,
    entries: true,
  };

  const el = document.getElementById("priceChart");
  const height = Math.max(380, Math.min(560, window.innerHeight * 0.5));
  el.style.height = height + "px";

  // ===================== CREATE CHART =====================
  const chart = LightweightCharts.createChart(el, {
    layout: {
      background: { color: "#0b0e11" },
      textColor: "#848e9c",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
    },
    grid: {
      vertLines: { color: "#1e2329" },
      horzLines: { color: "#1e2329" },
    },
    rightPriceScale: { borderColor: "#2b3139" },
    timeScale: {
      borderColor: "#2b3139",
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 6,
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
  });

  // ===================== VOLUME (bottom panel) =====================
  const volumeSeries = chart.addHistogramSeries({
    priceFormat: { type: "volume" },
    priceScaleId: "volume",
    lastValueVisible: false,
  });
  chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

  const volData = C.candles.map((c) => ({
    time: c.time,
    value: c.volume,
    color: c.close >= c.open ? "rgba(14,203,129,0.3)" : "rgba(246,70,93,0.3)",
  }));
  volumeSeries.setData(volData);

  // ===================== CANDLESTICK =====================
  const candleSeries = chart.addCandlestickSeries({
    upColor: "#0ecb81",
    downColor: "#f6465d",
    borderUpColor: "#0ecb81",
    borderDownColor: "#f6465d",
    wickUpColor: "#0ecb81",
    wickDownColor: "#f6465d",
  });
  candleSeries.setData(
    C.candles.map((c) => ({
      time: c.time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }))
  );
  chart.timeScale().fitContent();

  // ===================== EMA LINES =====================
  // Approximate EMAs from OHLCV data
  function calcEMA(data, period) {
    if (data.length < period) return [];
    const k = 2 / (period + 1);
    let ema = data[0].close;
    const result = [{ time: data[0].time, value: ema }];
    for (let i = 1; i < data.length; i++) {
      ema = data[i].close * k + ema * (1 - k);
      result.push({ time: data[i].time, value: ema });
    }
    return result;
  }

  const ema20Data = calcEMA(C.candles, 20);
  const ema50Data = calcEMA(C.candles, 50);
  const ema200Data = calcEMA(C.candles, 200);

  const ema20Series = chart.addLineSeries({
    color: "#1e80ff",
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    title: "EMA20",
  });
  ema20Series.setData(ema20Data);

  const ema50Series = chart.addLineSeries({
    color: "#f0b90b",
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    title: "EMA50",
  });
  ema50Series.setData(ema50Data);

  const ema200Series = chart.addLineSeries({
    color: "#a26bff",
    lineWidth: 1,
    priceLineVisible: false,
    lastValueVisible: false,
    title: "EMA200",
  });
  ema200Series.setData(ema200Data);

  // ===================== RSI PANEL =====================
  function calcRSI(data, period) {
    if (data.length < period + 1) return [];
    const prices = data.map(c => c.close);
    const changes = prices.slice(1).map((p, i) => p - prices[i]);
    let gains = changes.map(c => c > 0 ? c : 0);
    let losses = changes.map(c => c < 0 ? -c : 0);
    let avgGain = gains.slice(0, period).reduce((a, b) => a + b, 0) / period;
    let avgLoss = losses.slice(0, period).reduce((a, b) => a + b, 0) / period;
    const rsiValues = [];
    for (let i = period; i < changes.length; i++) {
      avgGain = (avgGain * (period - 1) + gains[i]) / period;
      avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
      const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
      const rsi = 100 - 100 / (1 + rs);
      rsiValues.push({ time: data[i + 1].time, value: rsi });
    }
    return rsiValues;
  }

  const rsiSeries = chart.addLineSeries({
    color: "#a26bff",
    lineWidth: 1,
    priceScaleId: "rsi",
    lastValueVisible: false,
    title: "RSI",
  });
  chart.priceScale("rsi").applyOptions({
    scaleMargins: { top: 0.65, bottom: 0.35 },
    visible: false,
  });

  const rsiData = calcRSI(C.candles, 14);
  if (rsiData.length > 0) rsiSeries.setData(rsiData);

  // RSI overbought/oversold lines
  var rsiOverSeries = chart.addLineSeries({
    color: "rgba(246,70,93,0.3)",
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    priceScaleId: "rsi",
    lastValueVisible: false,
  });
  rsiOverSeries.setData(rsiData.map(function(d) { return { time: d.time, value: 70 }; }));

  var rsiUnderSeries = chart.addLineSeries({
    color: "rgba(14,203,129,0.3)",
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    priceScaleId: "rsi",
    lastValueVisible: false,
  });
  rsiUnderSeries.setData(rsiData.map(function(d) { return { time: d.time, value: 30 }; }));;

  // =================== MACD PANEL =====================
  // Simple MACD approximation
  function calcMACD(data, fast, slow, signal) {
    if (data.length < slow + signal) return [];
    const emaF = calcEMA(data, fast);
    const emaS = calcEMA(data, slow);
    const macdLine = [];
    for (let i = 0; i < Math.min(emaF.length, emaS.length); i++) {
      if (emaF[i] && emaS[i]) {
        macdLine.push({ time: emaF[i].time, value: emaF[i].value - emaS[i].value });
      }
    }
    // Signal line from macd
    if (macdLine.length < signal) return [];
    const k = 2 / (signal + 1);
    let sig = macdLine[0].value;
    const signalLine = [{ time: macdLine[0].time, value: sig }];
    for (let i = 1; i < macdLine.length; i++) {
      sig = macdLine[i].value * k + sig * (1 - k);
      signalLine.push({ time: macdLine[i].time, value: sig });
    }
    // Histogram
    const hist = [];
    for (let i = 0; i < macdLine.length && i < signalLine.length; i++) {
      hist.push({ time: macdLine[i].time, value: macdLine[i].value - signalLine[i].value });
    }
    return { macd: macdLine, signal: signalLine, hist: hist };
  }

  var macdScaleId = "macd";
  var macdData = calcMACD(C.candles, 12, 26, 9);

  const macdSeries = chart.addLineSeries({
    color: "#1e80ff",
    lineWidth: 1,
    priceScaleId: macdScaleId,
    lastValueVisible: false,
    title: "MACD",
  });
  chart.priceScale(macdScaleId).applyOptions({
    scaleMargins: { top: 0.65, bottom: 0.35 },
    visible: false,
  });

  if (macdData && macdData.macd.length > 0) {
    macdSeries.setData(macdData.macd);

    // Signal line
    const macdSignalSeries = chart.addLineSeries({
      color: "#f0b90b",
      lineWidth: 1,
      priceScaleId: macdScaleId,
      lastValueVisible: false,
    });
    macdSignalSeries.setData(macdData.signal);

    // Histogram
    const macdHistSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: macdScaleId,
      lastValueVisible: false,
    });
    macdHistSeries.setData(
      macdData.hist.map(h => ({
        time: h.time,
        value: h.value,
        color: h.value >= 0 ? "rgba(14,203,129,0.5)" : "rgba(246,70,93,0.5)",
      }))
    );

    // Store for toggle
    window.__macdSignalSeries = macdSignalSeries;
    window.__macdHistSeries = macdHistSeries;
  }

  // ===================== SIGNAL / LEVEL LINES =====================
  const isLong = C.signal === "LONG";
  const isShort = C.signal === "SHORT";
  const hasTrade = isLong || isShort;

  // Semi-transparent blocks for buy/sell zones
  if (hasTrade) {
    const entry = C.setup.entry;
    const stop = C.setup.stop_loss;
    const tp1 = C.setup.take_profit_1;

    // Entry line
    candleSeries.createPriceLine({
      price: ntry,
      color: "rgba(14,203,129,0.8)",
      lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true,
      title: "Entry",
    });

    // Stop loss zone (red block from entry to stop)
    if (isLong && stop < entry) {
      createZone(candleSeries, entry, stop, "rgba(246,70,93,0.1)");
    } else if (isShort && stop > entry) {
      createZone(candleSeries, entry, stop, "rgba(246,70,93,0.1)");
    }

    // Take profit zone (green block from entry to TP1)
    if (isLong && tp1 > entry) {
      createZone(candleSeries, entry, tp1, "rgba(14,203,129,0.08)");
    } else if (isShort && tp1 < entry) {
      createZone(candleSeries, tp1, entry, "rgba(14,203,129,0.08)");
    }
  }

  // Support / Resistance lines
  if (C.levels) {
    const r1 = C.levels.resistance_1;
    const r2 = C.levels.resistance_2;
    const s1 = C.levels.support_1;
    const s2 = C.levels.support_2;

    createLevelLine(candleSeries, r1, "#f6465d", "R1", LightweightCharts.LineStyle.Dashed);
    createLevelLine(candleSeries, r2, "#f6465d", "R2", LightweightCharts.LineStyle.Dotted);
    createLevelLine(candleSeries, s1, "#0ecb81", "S1", LightweightCharts.LineStyle.Dashed);
    createLevelLine(candleSeries, s2, "#0ecb81", "S2", LightweightCharts.LineStyle.Dotted);
  }

  // Helper: create a price line
  function createLevelLine(series, price, color, title, style) {
    if (!price || price <= 0) return;
    series.createPriceLine({
      price: price,
      color: color,
      lineWidth: 1,
      lineStyle: style,
      axisLabelVisible: true,
      title: title,
    });
  }

  // Helper: create semi-transparent zone between two prices
  function createZone(series, top, bottom, color) {
    if (top === bottom) return;
    const range = Math.abs(top - bottom);
    if (range < 0.01) return;
    // Use a price line at mid with very thick width + transparency effect
    series.createPriceLine({
      price: (top + bottom) / 2,
      color: color,
      lineWidth: 20,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: false,
    });
  }

  // ===================== LAYER TOGGLES (global function) =====================
  window.toggleLayer = function(btn) {
    const layer = btn.dataset.layer;
    layerState[layer] = !layerState[layer];
    btn.classList.toggle("active");
    appyLayerState();
  };

  function appyLayerState() {
    // Candles
    candleSeries.applyOptions({ visible: layerState.candles });

    // Volume
    olumeSeries.applyOptions({ visible: layerState.volume });

    // EMA
    ema20Series.pplyOptions({ visible: layerState.ema });
    ema50Series.applyOptions({ visible: layerState.ema });
    ema200Series.applyOptions({ visible: layerState.ema });

    // RSI
    rsiSeries.applylyOptions({ visible: layerState.rsi });
    chart.priceScale("rsi").applyOptions({ visible: layerState.rsi });

    // MACD
    macdSeries.applylyOptions({ visible: layerState.macd });
    chart.priceScale("macd").applyOptions({ visible: layerState.macd });
    if (window.__macdSignalSeries) {
      window.__macdSignalSeries.applyOptions({ visible: layerState.macd });
    }
    if (window.__macdHistSeries) {
      window.__macdHistSeries.applyOptions({ visible: layerState.macd });
    }
  }

  // ===================== LEGEND =====================
  function buildLegend() {
    const el = document.getElementById("chartLegend");
    const items = [];
    if (hasTrade) {
      const entry = C.setup.entry;
      const stop = C.setup.stop_loss;
      const tp1 = C.setup.take_profit_1;
      items.pushh(`<span class="leg-item"><span class="leg-swatch" style="background:var(--green)"></span>Entry: <b>${entry.toLocaleString()}</b></span>`);
      items.pushh(`<span class="leg-item"><span class="leg-swatch" style="background:var(--red)"></span>Stop: <b>${stop.toLocaleString()}</b></span>`);
      items.pushh(`<span class="leg-item"><span class="leg-swatch" style="background:var(--green)"></span>TP1: <b>${tp1.toLocaleString()}</b></span>`);
    }
    if (C.levels) {
      items.push(`<span class="leg-item"><span class="leg-swatch" style="background:var(--red)"></span>R: ${C.levels.resistance_1.toLocaleString()}</span>`)
      items.push(`<span class="leg-item"><span class="leg-swatch" style="background:var(--green)"></span>S: ${C.levels.support_1.toLocaleString()}</span>`);
    }
    el.innerHTML = items.join("") || '<span class="muted">No active signals</span>';
  }
  buildLegend();

  // ===================== RESIZE =====================
  window.addEventListener("resize", () => {
    chart.applyOptions({ width: el.clientWidth });
  });

  // ==================== READY =====================
  // Initial appy of layer state
  applyLayerState();
})();