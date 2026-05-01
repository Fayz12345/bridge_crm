document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-confirm]").forEach((element) => {
    element.addEventListener("click", (event) => {
      const message = element.getAttribute("data-confirm");
      if (message && !window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

  document.querySelectorAll("[data-select-all]").forEach((toggle) => {
    toggle.addEventListener("change", () => {
      const group = toggle.getAttribute("data-select-all");
      if (!group) return;
      document
        .querySelectorAll('[data-checkbox-group="' + group + '"]')
        .forEach((checkbox) => {
          checkbox.checked = toggle.checked;
        });
    });
  });

  function bindWhatsappButton(config) {
    config.button.addEventListener("click", function () {
      var phoneInput = document.getElementById(config.phoneInputId);
      var subjectInput = document.getElementById(config.subjectId);
      var bodyInput = document.getElementById(config.bodyId);
      var totalInput = document.getElementById(config.totalId);
      var quoteRows = document.querySelectorAll(config.rowsSelector);
      var currency = config.currency || "$";

      if (!phoneInput || !subjectInput || !bodyInput) {
        return;
      }

      var phone = phoneInput.value.trim().replace(/[\s\-()]/g, "");
      if (!phone) {
        alert("Please enter a WhatsApp phone number.");
        return;
      }
      if (!phone.startsWith("+")) phone = "+" + phone;

      var subject = subjectInput.value.trim();
      var body = bodyInput.value.trim();
      var quoteLines = [];
      quoteRows.forEach(function (row) {
        var item = row.dataset.item;
        var spec = row.dataset.spec;
        var qty = row.dataset.qty;
        var unit = row.dataset.unit;
        var total = row.dataset.total;
        if (item) {
          var line = "• " + item;
          if (spec && spec !== "— · —") line += " (" + spec + ")";
          line += " — Qty: " + qty + " × " + currency + " " + unit + " = *" + currency + " " + total + "*";
          quoteLines.push(line);
        }
      });

      var lines = [];
      if (subject) lines.push("*" + subject + "*");
      if (body) lines.push(body);

      if (quoteLines.length > 0) {
        var quoteBlock = "*Quote:*\n" + quoteLines.join("\n");
        if (totalInput && totalInput.value) quoteBlock += "\n\n*Total: " + currency + " " + totalInput.value + "*";
        lines.push(quoteBlock);
      }

      var message = lines.join("\n\n");
      var url = "https://wa.me/" + encodeURIComponent(phone.replace("+", "")) + "?text=" + encodeURIComponent(message);
      window.open(url, "_blank");
    });
  }

  document.querySelectorAll(".js-whatsapp-send").forEach(function (button) {
    bindWhatsappButton({
      button: button,
      phoneInputId: button.dataset.phoneInputId,
      subjectId: button.dataset.subjectId,
      bodyId: button.dataset.bodyId,
      rowsSelector: button.dataset.rowsSelector,
      totalId: button.dataset.totalId,
      currency: button.dataset.currency || "$",
    });
  });

  var whatsappBtn = document.getElementById("whatsapp-send-btn");
  if (whatsappBtn) {
    bindWhatsappButton({
      button: whatsappBtn,
      phoneInputId: "whatsapp_phone",
      subjectId: "subject",
      bodyId: "body_text",
      rowsSelector: "#whatsapp-quote-data tr",
      totalId: "whatsapp-quote-total",
      currency: "$",
    });
  }

  document.querySelectorAll(".password-toggle").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = document.getElementById(btn.getAttribute("data-target"));
      if (input) input.type = input.type === "password" ? "text" : "password";
    });
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/crm/static/service-worker.js").catch(() => {});
  }
});
