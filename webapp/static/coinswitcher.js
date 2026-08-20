/**
 * Searchable coin switcher for the top bar.
 * Allows switching between well-known USDT pairs and searching for any other.
 */
(function () {
  const COINS = window.AI_TRADER_COINS || [];

  const input = document.getElementById("coinInput");
  const list = document.getElementById("coinList");
  const clearBtn = document.getElementById("coinClear");
  const popularHead = document.getElementById("popularHead");
  const search = document.getElementById("coinSearch");

  if (!input || !list) return;

  let activeIndex = -1;

  // The full pool of coins: popular first, then an alphabetically sorted set
  // so anything searchable exists as a suggestion.
  const all = Array.from(new Set([...COINS, ...defaultPool().sort()]));

  function defaultPool() {
    const extra = [
      "1INCH", "1000SATS", "AAVE", "ACE", "ACH", "ACT", "AGIX", "AIOZ",
      "ALGO", "ALT", "ANKR", "API3", "AR", "ARKM", "ARPA", "ASTR", "AUCTION",
      "AXL", "AXS", "BABYDOGE", "BADGER", "BAKE", "BAL", "BAND", "BCH",
      "BIGTIME", "BLUR", "BLZ", "BNX", "BOME", "BONK", "BTT", "C98", "CAKE",
      "CETUS", "CFX", "CHZ", "CKB", "COMP", "CORE", "CVX", "CYBER", "DASH",
      "DYDX", "DYM", "EGLD", "ENJ", "ENS", "EOS", "ETC", "FLOKI", "FLOW",
      "FLR", "FORT", "FTM", "FXS", "GALA", "GAS", "GLM", "GMT", "GRT",
      "HNT", "HYPE", "ICX", "ID", "ILV", "IMX", "IOTA", "JASMY", "JTO",
      "JUP", "KAS", "KAVA", "KDA", "KSM", "LDO", "LINA", "LOOM", "LRC",
      "LSK", "MAGIC", "MANA", "MASK", "MKR", "MNT", "MORPHO", "MOVR",
      "MUBARAK", "NEO", "NKN", "NMR", "NTRN", "OCEAN", "OM", "ONE", "ONG",
      "ONT", "ORCA", "ORDI", "PENDLE", "PEOPLE", "PHB", "PIXEL", "POL",
      "POLYX", "POWR", "PYTH", "QTUM", "RARE", "RENDER", "RIF", "RONIN",
      "RUNE", "RVN", "SAND", "SATS", "SCR", "SEI", "SKL", "SLP", "SNX",
      "SOL", "SSV", "STEEM", "STORJ", "STX", "SUSHI", "SWEAT", "SXP",
      "TAO", "THETA", "TIA", "TLM", "TWT", "UMA", "USDD", "USTC", "VET",
      "VIC", "W", "WAVES", "WBTC", "WLD", "XEC", "XEM", "XMR", "XTZ",
      "YGG", "ZEC", "ZEN", "ZIL", "ZRO", "ZRX",
    ];
    return extra;
  }

  function open() {
    list.hidden = false;
    input.focus();
  }

  function close() {
    list.hidden = true;
    activeIndex = -1;
  }

  function goTo(symbol) {
    // Preserve any timeframe currently selected.
    const tf = new URLSearchParams(window.location.search).get("tf") || "1h";
    window.location.href = `/?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}`;
  }

  function render(items) {
    list.innerHTML = "";
    if (items.length === 0) {
      const li = document.createElement("li");
      li.className = "coin-empty";
      li.textContent = "رمزارزی پیدا نشد";
      list.appendChild(li);
      return;
    }
    items.forEach((c, idx) => {
      const li = document.createElement("li");
      li.className = "coin-item" + (idx === activeIndex ? " active" : "");
      li.textContent = c;
      li.dataset.symbol = c;
      li.addEventListener("click", () => goTo(c));
      li.addEventListener("mousemove", () => {
        activeIndex = idx;
        paint();
      });
      list.appendChild(li);
    });
  }

  function paint() {
    const items = list.querySelectorAll(".coin-item");
    items.forEach((li, idx) => {
      li.classList.toggle("active", idx === activeIndex);
    });
  }

  function currentFilter() {
    return input.value.trim().toUpperCase();
  }

  function refresh() {
    const q = currentFilter();
    if (!q) {
      render(all.slice(0, 12));
      popularHead.textContent = "پرمعامله‌ترین";
      popularHead.hidden = false;
      return;
    }
    popularHead.textContent = "نتایج جستجو";
    popularHead.hidden = false;
    const matches = all.filter((c) => c.startsWith(q)).slice(0, 12);
    render(matches);
  }

  input.addEventListener("focus", () => {
    activeIndex = -1;
    refresh();
    open();
  });

  input.addEventListener("input", () => {
    activeIndex = -1;
    refresh();
    open();
  });

  input.addEventListener("keydown", (e) => {
    const items = list.querySelectorAll(".coin-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, items.length - 1);
      paint();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      paint();
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = items[activeIndex >= 0 ? activeIndex : 0];
      if (item) goTo(item.dataset.symbol);
    } else if (e.key === "Escape") {
      close();
      input.blur();
    }
  });

  clearBtn.addEventListener("click", () => {
    input.value = "";
    activeIndex = -1;
    refresh();
    input.focus();
  });

  document.addEventListener("click", (e) => {
    if (!search.contains(e.target)) close();
  });

  // Show a hint hint by default.
  activeIndex = -1;
})();
