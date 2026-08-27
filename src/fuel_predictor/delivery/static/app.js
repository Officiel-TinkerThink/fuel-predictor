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

  // The ids are `field-<name>`: that is what the form-field macro emits. This
  // block queried `#activity_mode` and `#lifting_hours`, so the guard below was
  // always false and the toggle never ran — the field stayed visible for
  // transport-only trips and never became required. Nothing caught it because
  // the Python suite asserts against server-rendered HTML and never executes
  // this file.
  // Lifting-hours only applies to some activity modes. Without JS the field
  // just stays visible and optional; the server is the real source of truth
  // for whether it's required (DailyOperationValidationError), so hiding it
  // here is convenience only, never validation.
  var mode = document.querySelector("#field-activity_mode");
  var lifting = document.querySelector("#field-lifting_hours");
  var liftingField = document.querySelector("#lifting-field");
  if (mode && lifting && liftingField) {
    var syncLifting = function () {
      var applies = mode.value === "lifting" || mode.value === "transport_and_lifting";
      lifting.required = applies;
      liftingField.hidden = !applies;
      if (!applies) {
        lifting.value = "";
      }
    };
    mode.addEventListener("change", syncLifting);
    syncLifting();
  }

  // Ordered stop-sequence rows: add / remove / move up / move down.
  // Without JS, the two rows rendered by the server are still submittable as-is.
  var sequence = document.querySelector("#stop-sequence");
  var addStop = document.querySelector("#add-stop");
  if (sequence && addStop) {
    var stopControlsHtml = function (index) {
      return (
        '<div class="stop-controls">' +
        '<button type="button" data-action="up" aria-label="Naikkan urutan pemberhentian ' +
        (index + 1) +
        '">↑</button>' +
        '<button type="button" data-action="down" aria-label="Turunkan urutan pemberhentian ' +
        (index + 1) +
        '">↓</button>' +
        '<button type="button" data-action="remove" aria-label="Hapus pemberhentian ' +
        (index + 1) +
        '">Hapus</button>' +
        "</div>"
      );
    };
    var refreshStopControls = function () {
      Array.prototype.forEach.call(sequence.children, function (row, index) {
        var controls = row.querySelector(".stop-controls");
        if (controls) {
          controls.outerHTML = stopControlsHtml(index);
        }
      });
    };
    var newStopRow = function () {
      var row = document.createElement("div");
      row.className = "stop-row";
      var field = document.createElement("div");
      field.className = "field";
      var label = document.createElement("label");
      label.textContent = "Pemberhentian";
      var input = document.createElement("input");
      input.name = "stop_sequence";
      input.type = "text";
      input.autocomplete = "off";
      label.appendChild(input);
      field.appendChild(label);
      row.appendChild(field);
      var controls = document.createElement("div");
      controls.innerHTML = stopControlsHtml(sequence.children.length);
      row.appendChild(controls.firstChild);
      return row;
    };
    addStop.addEventListener("click", function () {
      var row = newStopRow();
      sequence.appendChild(row);
      refreshStopControls();
      row.querySelector("input").focus();
    });
    sequence.addEventListener("click", function (event) {
      var button = event.target.closest("button[data-action]");
      if (!button) {
        return;
      }
      var row = button.closest(".stop-row");
      if (button.dataset.action === "remove") {
        row.remove();
      } else if (button.dataset.action === "up" && row.previousElementSibling) {
        sequence.insertBefore(row, row.previousElementSibling);
      } else if (button.dataset.action === "down" && row.nextElementSibling) {
        sequence.insertBefore(row.nextElementSibling, row);
      }
      refreshStopControls();
    });
  }
})();
