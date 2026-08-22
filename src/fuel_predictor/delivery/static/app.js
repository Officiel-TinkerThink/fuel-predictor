/* Progressive enhancement only (ADR 0007).
   Every workflow below already works without JavaScript; this adds convenience. */

(function () {
  "use strict";

  // Move focus to the error summary so a screen reader announces the failure.
  var summary = document.getElementById("ringkasan-kesalahan");
  if (summary) {
    summary.focus();
  }

  // Confirmation dialogs. Without JavaScript the dialog stays in the page and its
  // form still submits, so the destructive action remains reachable.
  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!(target instanceof Element)) {
      return;
    }

    var openId = target.getAttribute("data-dialog");
    if (openId) {
      var dialog = document.getElementById(openId);
      if (dialog && typeof dialog.showModal === "function") {
        event.preventDefault();
        dialog.showModal();
      }
      return;
    }

    var closeId = target.getAttribute("data-dialog-close");
    if (closeId) {
      var closing = document.getElementById(closeId);
      if (closing && typeof closing.close === "function") {
        event.preventDefault();
        closing.close();
      }
    }
  });

  // Client-side table filtering. The server already returns the full table.
  document.querySelectorAll("[data-table-filter]").forEach(function (input) {
    var table = document.getElementById(input.getAttribute("data-table-filter"));
    if (!table) {
      return;
    }
    var status = document.getElementById(input.getAttribute("aria-describedby"));
    input.addEventListener("input", function () {
      var needle = input.value.trim().toLowerCase();
      var shown = 0;
      table.querySelectorAll("tbody tr").forEach(function (row) {
        var match = needle === "" || row.textContent.toLowerCase().indexOf(needle) !== -1;
        row.hidden = !match;
        if (match) {
          shown += 1;
        }
      });
      if (status) {
        status.textContent = needle === "" ? "" : shown + " baris cocok.";
      }
    });
  });

  // Show the chosen filename for file inputs, which otherwise read as "No file chosen".
  document.querySelectorAll('input[type="file"]').forEach(function (input) {
    input.addEventListener("change", function () {
      var hint = document.getElementById("hint-" + input.getAttribute("name"));
      if (hint && input.files && input.files.length > 0) {
        hint.textContent = "Berkas dipilih: " + input.files[0].name;
      }
    });
  });
})();
