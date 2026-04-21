document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-confirm]").forEach((element) => {
    element.addEventListener("click", (event) => {
      const message = element.getAttribute("data-confirm");
      if (message && !window.confirm(message)) {
        event.preventDefault();
      }
    });
  });

  var whatsappBtn = document.getElementById("whatsapp-send-btn");
  if (whatsappBtn) {
    whatsappBtn.addEventListener("click", function () {
      var phone = document.getElementById("whatsapp_phone").value.trim().replace(/[\s\-()]/g, "");
      if (!phone) {
        alert("Please enter a WhatsApp phone number.");
        return;
      }
      if (!phone.startsWith("+")) phone = "+" + phone;

      var subject = document.getElementById("subject").value.trim();
      var body = document.getElementById("body_text").value.trim();

      var quoteRows = document.querySelectorAll("#whatsapp-quote-data tr");
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
          line += " — Qty: " + qty + " × $" + unit + " = *$" + total + "*";
          quoteLines.push(line);
        }
      });

      var lines = [];
      if (subject) lines.push("*" + subject + "*");
      if (body) lines.push(body);

      if (quoteLines.length > 0) {
        var grandTotal = document.getElementById("whatsapp-quote-total");
        var quoteBlock = "*Quote:*\n" + quoteLines.join("\n");
        if (grandTotal && grandTotal.value) quoteBlock += "\n\n*Total: $" + grandTotal.value + "*";
        lines.push(quoteBlock);
      }

      var message = lines.join("\n\n");
      var url = "https://wa.me/" + encodeURIComponent(phone.replace("+", "")) + "?text=" + encodeURIComponent(message);
      window.open(url, "_blank");
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
