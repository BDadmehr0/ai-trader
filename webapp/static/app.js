/* Shared UI helpers: toast + JSON API calls. */
(function () {
  const toastEl = document.getElementById("toast");
  let timer = null;

  function toast(message, kind) {
    if (!toastEl) {
      console.log("[toast]", message);
      return;
    }
    toastEl.textContent = message;
    toastEl.className = "toast show " + (kind || "");
    clearTimeout(timer);
    timer = setTimeout(() => (toastEl.className = "toast"), 4200);
  }

  async function call(path, options) {
    const opts = Object.assign({ headers: { "Content-Type": "application/json" } }, options || {});
    let response;
    try {
      response = await fetch(path, opts);
    } catch (error) {
      throw new Error("network error: " + error.message);
    }
    const text = await response.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : {};
    } catch (error) {
      throw new Error("bad response from server (" + response.status + ")");
    }
    if (!response.ok && data && data.errors) {
      const detail = Object.entries(data.errors).map(([k, v]) => `${k}: ${v}`).join("; ");
      throw new Error(detail || data.message || "rejected");
    }
    if (!response.ok) throw new Error((data && (data.error || data.message)) || "HTTP " + response.status);
    return data;
  }

  const api = {
    get: (path) => call(path),
    post: (path, body) =>
      call(path, { method: "POST", body: body === undefined ? "{}" : JSON.stringify(body) }),
  };

  function fmt(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    return Number(value).toLocaleString(undefined, {
      minimumFractionDigits: digits === undefined ? 2 : digits,
      maximumFractionDigits: digits === undefined ? 2 : digits,
    });
  }

  window.aiTrader = { toast, api, fmt };
})();
