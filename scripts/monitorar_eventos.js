/**
 * Script para injeção no contexto da página (Playwright: page.add_init_script ou evaluate).
 * Monitora eventos de mouse, pointer e scroll; registra elemento alvo, coordenadas e timestamp.
 * Loga no console com prefixo [MonitorEventos] e expõe window.downloadEventLogs() para baixar JSON.
 *
 * Uso no Playwright (antes de navegar ou após):
 *   await page.add_init_script(path="scripts/monitorar_eventos.js");
 *   // ou
 *   await page.evaluate(await fs.promises.readFile("scripts/monitorar_eventos.js", "utf8"));
 *
 * Após interação, no console do browser ou via page.evaluate("window.downloadEventLogs()")
 * para disparar o download do JSON (ou page.evaluate("JSON.stringify(window.__eventLogs)") para obter o texto).
 */

(function () {
  if (window.__eventLogsInjected) return;
  window.__eventLogsInjected = true;

  var logs = [];

  function safe(obj, key, def) {
    try {
      var v = obj && obj[key];
      return v !== undefined && v !== null ? v : def;
    } catch (e) {
      return def;
    }
  }

  function getElementInfo(el) {
    if (!el || !el.tagName) return null;
    var rect = el.getBoundingClientRect && el.getBoundingClientRect();
    return {
      tagName: el.tagName,
      id: el.id || null,
      className: typeof el.className === "string" ? el.className.slice(0, 200) : null,
      dataTestId: el.getAttribute ? el.getAttribute("data-testid") : null,
      innerText: (el.innerText || "").slice(0, 100),
      rect: rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null,
    };
  }

  function pushAndLog(ev) {
    logs.push(ev);
    console.log("[MonitorEventos]", JSON.stringify(ev));
  }

  function onMouse(name, e) {
    var target = e.target;
    pushAndLog({
      type: name,
      ts: Date.now(),
      clientX: e.clientX,
      clientY: e.clientY,
      pageX: e.pageX,
      pageY: e.pageY,
      button: e.button,
      target: getElementInfo(target),
    });
  }

  function onScroll(e) {
    var target = e.target;
    pushAndLog({
      type: "scroll",
      ts: Date.now(),
      scrollTop: target.scrollTop,
      scrollLeft: target.scrollLeft,
      target: getElementInfo(target),
    });
  }

  ["click", "mousedown", "mouseup"].forEach(function (name) {
    document.addEventListener(name, function (e) {
      onMouse(name, e);
    }, true);
  });

  ["pointerdown", "pointerup"].forEach(function (name) {
    document.addEventListener(name, function (e) {
      onMouse(name, e);
    }, true);
  });

  document.addEventListener("scroll", onScroll, true);

  window.__eventLogs = logs;

  window.downloadEventLogs = function () {
    var json = JSON.stringify(logs, null, 2);
    var blob = new Blob([json], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "event_logs.json";
    a.click();
    URL.revokeObjectURL(a.href);
    return logs.length;
  };

  console.log("[MonitorEventos] Injetado. Use window.downloadEventLogs() para baixar os logs em JSON.");
})();
