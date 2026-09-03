(function () {
  "use strict";

  var LWC = window.LightweightCharts;
  var container = document.getElementById("financial-chart");
  if (!LWC || !container) return;

  var controls = {
    symbolSelect: document.getElementById("symbol-select"),
    symbolInput: document.getElementById("symbol-input"),
    interval: document.getElementById("interval-select"),
    reload: document.getElementById("reload-chart"),
    sma: document.getElementById("toggle-sma"),
    ema: document.getElementById("toggle-ema"),
    rsi: document.getElementById("toggle-rsi"),
    loading: document.getElementById("chart-loading"),
    tooltip: document.getElementById("chart-tooltip"),
    provider: document.getElementById("chart-provider"),
    bars: document.getElementById("chart-bars"),
    range: document.getElementById("chart-range"),
    status: document.getElementById("chart-status"),
    signalPanel: document.getElementById("efloud-signal-panel"),
    signalBadge: document.getElementById("efloud-signal-badge"),
    signalTitle: document.getElementById("efloud-signal-title"),
    signalNote: document.getElementById("efloud-signal-note"),
    signalReferences: document.getElementById("efloud-signal-references"),
    signalLevels: document.getElementById("efloud-signal-levels")
  };

  var chart = LWC.createChart(container, {
    autoSize: true,
    layout: {
      background: { type: "solid", color: "#ffffff" },
      textColor: "#667085",
      fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
      panes: { separatorColor: "#e4e7ec", separatorHoverColor: "#c7d7f5", enableResize: true }
    },
    grid: { vertLines: { color: "#f2f4f7" }, horzLines: { color: "#eef0f3" } },
    crosshair: { mode: LWC.CrosshairMode.Normal },
    rightPriceScale: { borderColor: "#dfe3e8", minimumWidth: 72 },
    timeScale: { borderColor: "#dfe3e8", timeVisible: true, secondsVisible: false, rightOffset: 4 },
    localization: { locale: "tr-TR" },
    attributionLogo: true
  });

  var candles = chart.addSeries(LWC.CandlestickSeries, {
    upColor: "#0b7a53", downColor: "#c43d32", borderVisible: false,
    wickUpColor: "#0b7a53", wickDownColor: "#c43d32"
  }, 0);
  var sma = chart.addSeries(LWC.LineSeries, { color: "#2563d9", lineWidth: 2, priceLineVisible: false, lastValueVisible: false }, 0);
  var ema = chart.addSeries(LWC.LineSeries, { color: "#a85b18", lineWidth: 2, priceLineVisible: false, lastValueVisible: false }, 0);
  var volume = chart.addSeries(LWC.HistogramSeries, { priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false }, 1);
  var rsi = chart.addSeries(LWC.LineSeries, { color: "#7c3aed", lineWidth: 2, priceLineVisible: false, lastValueVisible: true }, 2);
  var markers = LWC.createSeriesMarkers(candles, []);
  var payload = null;
  var priceLines = [];

  chart.panes()[0].setHeight(430);
  chart.panes()[1].setHeight(105);
  chart.panes()[2].setHeight(120);
  rsi.createPriceLine({ price: 70, color: "#e7a7a1", lineStyle: LWC.LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
  rsi.createPriceLine({ price: 30, color: "#9dd5b8", lineStyle: LWC.LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });

  function setIndicatorData() {
    if (!payload) return;
    sma.setData(controls.sma.checked ? payload.indicators.sma20 : []);
    ema.setData(controls.ema.checked ? payload.indicators.ema50 : []);
    rsi.setData(controls.rsi.checked ? payload.indicators.rsi14 : []);
  }

  function applyPriceLines(lines) {
    priceLines.forEach(function (line) { candles.removePriceLine(line); });
    priceLines = (lines || []).map(function (item) {
      return candles.createPriceLine({
        price: item.price, title: window.innerWidth < 640 ? "" : (item.title || ""), color: item.color || "#1f5fd0",
        lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true
      });
    });
  }

  function markerFromTrade(trade) {
    var isEntry = trade.kind === "entry";
    var isLong = trade.direction !== "short";
    var pointsUp = isEntry ? isLong : !isLong;
    return {
      time: trade.time,
      position: pointsUp ? "belowBar" : "aboveBar",
      color: trade.kind === "stop" ? "#a8261a" : (isEntry ? "#05713f" : "#7c3aed"),
      shape: pointsUp ? "arrowUp" : "arrowDown",
      text: trade.label || (isEntry ? "Giris" : "Cikis")
    };
  }

  function renderSignal(state) {
    controls.signalPanel.hidden = !state;
    if (!state) return;
    var latest = state.signals && state.signals.length ? state.signals[state.signals.length - 1] : null;
    var statusLabels = { active: "AKTIF SINYAL", managed: "1R ALINDI", closed_be: "KAPANDI", invalidated: "GECERSIZ" };
    controls.signalBadge.textContent = latest ? (statusLabels[latest.status] || latest.status) : "IZLENIYOR";
    controls.signalBadge.className = "signal-badge " + (latest && ["active", "managed"].indexOf(latest.status) >= 0 ? "is-positive" : (state.bias.indexOf("warning") >= 0 ? "is-warning" : ""));
    controls.signalTitle.textContent = latest
      ? "76.400 sweep/reclaim + 15dk yapi teyidi"
      : "Efloud BTC 15dk teyit motoru";
    controls.signalNote.textContent = latest
      ? latest.rationale + " Durum: " + (statusLabels[latest.status] || latest.status) + "."
      : state.note;
    controls.signalLevels.textContent = "Destek " + formatNumber(state.levels.support) +
      " · Geçersiz " + formatNumber(state.levels.invalidation) +
      " · Reclaim " + formatNumber(state.levels.reclaim);
    controls.signalReferences.innerHTML = "";
    (state.reference_charts || []).forEach(function (ref) {
      var link = document.createElement("a");
      link.href = ref.url;
      link.textContent = ref.timeframe + " referans grafik ↗";
      link.title = ref.role;
      if (ref.url.indexOf("http") === 0) {
        link.target = "_blank";
        link.rel = "noopener";
      }
      controls.signalReferences.appendChild(link);
    });
  }

  function loadChart() {
    var symbol = controls.symbolInput.value.trim().toUpperCase();
    controls.symbolInput.value = symbol;
    controls.loading.hidden = false;
    controls.loading.textContent = "Piyasa verisi yukleniyor...";
    controls.status.textContent = "Yukleniyor";
    controls.status.className = "";

    var url = "/api/charts/data?symbol=" + encodeURIComponent(symbol) + "&interval=" + encodeURIComponent(controls.interval.value);
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.json().then(function (body) {
          if (!response.ok) throw new Error(body.detail || "Veri alinamadi");
          return body;
        });
      })
      .then(function (data) {
        payload = data;
        candles.setData(data.candles);
        volume.setData(data.volume);
        setIndicatorData();
        applyPriceLines(data.price_lines);
        markers.setMarkers((data.trades || []).map(markerFromTrade));
        renderSignal(data.efloud_signal);
        chart.timeScale().fitContent();

        controls.provider.textContent = data.meta.provider;
        controls.bars.textContent = new Intl.NumberFormat("tr-TR").format(data.meta.bar_count);
        controls.range.textContent = formatDate(data.meta.first_bar) + " - " + formatDate(data.meta.last_bar);
        controls.status.textContent = data.meta.interval + " · en uzun ucretsiz test araligi";
        controls.loading.hidden = true;
      })
      .catch(function (error) {
        controls.loading.hidden = false;
        controls.loading.textContent = error.message;
        controls.status.textContent = error.message;
        controls.status.className = "chart-error";
      });
  }

  function formatDate(value) {
    return new Intl.DateTimeFormat("tr-TR", { dateStyle: "medium" }).format(new Date(value));
  }

  controls.symbolSelect.addEventListener("change", function () {
    controls.symbolInput.value = controls.symbolSelect.value;
    loadChart();
  });
  controls.interval.addEventListener("change", loadChart);
  controls.reload.addEventListener("click", loadChart);
  controls.symbolInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") loadChart();
  });
  [controls.sma, controls.ema, controls.rsi].forEach(function (control) {
    control.addEventListener("change", setIndicatorData);
  });

  chart.subscribeCrosshairMove(function (event) {
    var bar = event.seriesData.get(candles);
    if (!event.time || !bar) {
      controls.tooltip.hidden = true;
      return;
    }
    controls.tooltip.hidden = false;
    controls.tooltip.innerHTML = [
      "A <b>" + formatNumber(bar.open) + "</b>",
      "Y <b>" + formatNumber(bar.high) + "</b>",
      "D <b>" + formatNumber(bar.low) + "</b>",
      "K <b>" + formatNumber(bar.close) + "</b>"
    ].join(" ");
  });

  function formatNumber(value) {
    return new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 6 }).format(value);
  }

  loadChart();
  window.setInterval(function () {
    if (controls.symbolInput.value.trim().toUpperCase() === "BTC-USD" && controls.interval.value === "15m") loadChart();
  }, 60000);
})();
