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

  initPipelineBoards();

  document.querySelectorAll("[data-whatsapp-scroll]").forEach((scroller) => {
    scroller.scrollTop = scroller.scrollHeight;
  });

  document.body.addEventListener("htmx:beforeSwap", (event) => {
    const el = event.detail && event.detail.target;
    if (el && el.hasAttribute && el.hasAttribute("data-whatsapp-scroll")) {
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      el.dataset.stickBottom = nearBottom ? "1" : "0";
    }
  });
  document.body.addEventListener("htmx:afterSwap", (event) => {
    const el = event.detail && event.detail.target;
    if (el && el.hasAttribute && el.hasAttribute("data-whatsapp-scroll") && el.dataset.stickBottom !== "0") {
      el.scrollTop = el.scrollHeight;
    }
  });
});

function csrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta && meta.getAttribute("content")) {
    return meta.getAttribute("content");
  }
  try {
    const headers = JSON.parse(document.body.getAttribute("hx-headers") || "{}");
    return headers["X-CSRFToken"] || "";
  } catch (error) {
    return "";
  }
}

function refreshPipelineColumn(column) {
  if (!column) return;
  const count = column.querySelectorAll("[data-pipeline-card]").length;
  const badge = column.querySelector("[data-pipeline-count]");
  const empty = column.querySelector("[data-pipeline-empty]");
  if (badge) badge.textContent = String(count);
  if (empty) empty.hidden = count > 0;
}

function showPipelineStatus(board, message, isError) {
  const status = document.querySelector("[data-pipeline-status]");
  if (!status) return;
  status.textContent = message;
  status.classList.remove("d-none", "alert-success", "alert-danger");
  status.classList.add(isError ? "alert-danger" : "alert-success");
  window.clearTimeout(showPipelineStatus.timer);
  showPipelineStatus.timer = window.setTimeout(() => {
    status.classList.add("d-none");
  }, 3500);
}

function initPipelineBoards() {
  if (typeof Sortable === "undefined") return;

  document.querySelectorAll("[data-pipeline-board]").forEach((board) => {
    const field = board.getAttribute("data-pipeline-field") || "stage";
    const lists = board.querySelectorAll("[data-pipeline-cards]");

    lists.forEach((list) => {
      const column = list.closest("[data-pipeline-column]");
      const locked = column && column.getAttribute("data-locked") === "true";

      new Sortable(list, {
        group: {
          name: "pipeline-" + (board.getAttribute("data-pipeline-field") || "stage"),
          pull: (to, from, dragEl) => dragEl.getAttribute("data-locked") !== "true",
          put: () => !locked,
        },
        animation: 150,
        handle: "[data-pipeline-handle]",
        draggable: "[data-pipeline-card]",
        filter: "a, button, select, input, textarea",
        preventOnFilter: false,
        ghostClass: "sortable-ghost",
        chosenClass: "sortable-chosen",
        onMove: (event) => {
          const targetColumn = event.to.closest("[data-pipeline-column]");
          const dragEl = event.dragged;
          if (!targetColumn || !dragEl) return true;
          if (targetColumn.getAttribute("data-locked") === "true") return false;
          if (dragEl.getAttribute("data-locked") === "true") return false;
          return true;
        },
        onStart: () => {
          board.querySelectorAll("[data-pipeline-column]:not([data-locked])").forEach((item) => {
            item.classList.add("is-drop-target");
          });
        },
        onEnd: (event) => {
          board.querySelectorAll("[data-pipeline-column]").forEach((item) => {
            item.classList.remove("is-drop-target");
          });

          const card = event.item;
          const fromColumn = event.from.closest("[data-pipeline-column]");
          const toColumn = event.to.closest("[data-pipeline-column]");
          refreshPipelineColumn(fromColumn);
          refreshPipelineColumn(toColumn);

          if (!toColumn || event.from === event.to) return;

          const nextValue = toColumn.getAttribute("data-stage");
          const updateUrl = card.getAttribute("data-update-url");
          if (!nextValue || !updateUrl) return;

          card.classList.add("is-saving");
          const body = new URLSearchParams();
          body.set(field, nextValue);

          fetch(updateUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/x-www-form-urlencoded",
              "X-CSRFToken": csrfToken(),
              "X-Requested-With": "XMLHttpRequest",
              Accept: "application/json",
            },
            body: body.toString(),
            credentials: "same-origin",
          })
            .then((response) =>
              response.json().then((payload) => ({ ok: response.ok && payload.ok !== false, payload }))
            )
            .then(({ ok, payload }) => {
              card.classList.remove("is-saving");
              if (!ok) {
                event.from.insertBefore(card, event.from.children[event.oldIndex] || null);
                refreshPipelineColumn(fromColumn);
                refreshPipelineColumn(toColumn);
                showPipelineStatus(board, payload.error || "Could not update pipeline.", true);
                return;
              }
              if (payload.probability !== undefined) {
                const probability = card.querySelector("[data-pipeline-probability]");
                if (probability) probability.textContent = payload.probability + "%";
              }
              showPipelineStatus(board, "Moved to " + (toColumn.querySelector("h2")?.textContent || nextValue) + ".");
            })
            .catch(() => {
              card.classList.remove("is-saving");
              event.from.insertBefore(card, event.from.children[event.oldIndex] || null);
              refreshPipelineColumn(fromColumn);
              refreshPipelineColumn(toColumn);
              showPipelineStatus(board, "Could not update pipeline.", true);
            });
        },
      });
    });
  });
}
