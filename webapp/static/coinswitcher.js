/**
 * Professional coin selector for the top bar.
 * Acts like a trading terminal symbol selector.
 */
(function () {
  const COINS = window.AI_TRADER_COINS || [];

  const selector = document.getElementById("symbolSelector");
  const dropdown = document.getElementById("symbolDropdown");
  const list = document.getElementById("symbolList");
  const input = document.getElementById("symbolSearchInput");
  const selIcon = document.getElementById("selIcon");
  const selName = document.getElementById("selName");
  const selSub = document.getElementById("selSub");
  const selArrow = document.getElementById("selArrow");

  if (!selector || !dropdown || !list) return;

  let activeIndex = -1;
  let allCoins = [];

  // Build full coin list from window coins + extras
  function initCoins() {
    const extra = [
      "BTC","ETH","BNB","SOL","XRP","ADA","DOGE","DOT","LTC","LINK",
      "AVAX","MATIC","TRX","SHIB","UNI","ATOM","XLM","ETC","FIL","NEAR",
      "APT","SUI","ARB","OP","PEPE","TON","AAVE","CRV","INJ","SEI",
      "WLD","MEME","BONK","FLOKI","KAS","JUP","JTO","PYTH","TIA","RUNE"
    ];
    allCoins = Array.from(new Set([...extra, ...COINS]));
  }
  initCoins();

  function openDropdown() {
    dropdown.classList.remove("hidden");
    selArrow?.classList.add("rotate-180");
    input.focus();
    activeIndex = -1;
    render();
  }

  function closeDropdown() {
    dropdown.classList.add("hidden");
    selArrow?.classList.remove("rotate-180");
    activeIndex = -1;
  }

  function goTo(symbol) {
    const tf = new URLSearchParams(window.location.search).get("tf") || "1h";
    window.location.href = "/?symbol=" + encodeURIComponent(symbol) + "&tf=" + encodeURIComponent(tf);
  }

  function render() {
    const q = input.value.trim().toUpperCase();
    let items;

    if (!q) {
      // Show popular first
      items = allCoins.slice(0, 40);
    } else {
      items = allCoins.filter(c => c.startsWith(q) || c.includes(q)).slice(0, 40);
    }

    list.innerHTML = "";
    if (items.length === 0) {
      const div = document.createElement("div");
      div.className = "dd-empty";
      div.textContent = "No coins found";
      list.appendChild(div);
      return;
    }

    items.forEach((coin, idx) => {
      const div = document.createElement("div");
      div.className = "dd-item" + (idx === activeIndex ? " active" : "");
      div.innerHTML = `
        <span class="dd-item-icon">${coin.charAt(0)}</span>
        <span class="dd-item-name">${coin}</span>
        <span class="dd-item-full">${coin}/USDT</span>
      `;
      div.addEventListener("click", () => goTo(coin));
      div.addEventListener("mousemove", () => {
        activeIndex = idx;
        paint();
      });
      div.dataset.index = idx;
      list.appendChild(div);
    });
  }

  function paint() {
    const items = list.querySelectorAll(".dd-item");
    items.forEach((el, idx) => {
      el.classList.toggle("active", idx === activeIndex);
    });
  }

  // Selector click
  selector.addEventListener("click", (e) => {
    if (!dropdown.classList.contains("hidden")) {
      closeDropdown();
    } else {
      openDropdown();
    }
  });

  // Search input
  input.addEventListener("input", () => {
    activeIndex = -1;
    render();
  });

  input.addEventListener("keydown", (e) => {
    const items = list.querySelectorAll(".dd-item");
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
      const idx = activeIndex >= 0 ? activeIndex : 0;
      const item = items[idx];
      if (item) {
        const name = item.querySelector(".dd-item-name")?.textContent;
        if (name) goTo(name);
      }
    } else if (e.key === "Escape") {
      closeDropdown();
      input.blur();
    }
  });

  // Close on outside click
  document.addEventListener("click", (e) => {
    if (!selector.contains(e.target)) closeDropdown();
  });

  // Initial render
  activeIndex = -1;
})();