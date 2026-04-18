document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-confirm]").forEach((element) => {
    element.addEventListener("click", (event) => {
      const message = element.getAttribute("data-confirm");
      if (message && !window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/crm/static/service-worker.js").catch(() => {});
  }
});
