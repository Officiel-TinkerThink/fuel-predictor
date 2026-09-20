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

  // Lifting-hours only applies to some activity modes. The ids are
  // `field-<name>`: that is what the form-field macro emits, and querying
  // `#activity_mode` instead once left the guard permanently false so the
  // toggle never ran. Without JS the server still renders the field whenever
  // the chosen mode includes lifting, and it is the real source of truth for
  // whether the value is required (DailyOperationValidationError) — hiding it
  // here is convenience only, never validation.
  var lifting = document.querySelector("#field-lifting_hours");
  var liftingField = document.querySelector("#lifting-field");
  var activityMode = document.querySelector("#field-activity_mode");
  if (lifting && liftingField && activityMode) {
    var LIFTING_MODES = ["lifting", "transport_and_lifting"];
    var syncLifting = function () {
      var applies = LIFTING_MODES.indexOf(activityMode.value) !== -1;
      lifting.required = applies;
      liftingField.hidden = !applies;
      if (!applies) {
        lifting.value = "";
      }
    };
    activityMode.addEventListener("change", syncLifting);
    syncLifting();
  }

  // Ordered stop-sequence rows: add, remove, and drag to reorder.
  // Without JS the rows the server rendered are still submittable as-is; the
  // departure point is always the first row and never moves.
  var sequence = document.querySelector("#stop-sequence");
  var addStop = document.querySelector("#add-stop");
  if (sequence && addStop) {
    var rows = function () {
      return Array.prototype.slice.call(sequence.children);
    };

    // Markers run A, 1, 2, 3 …: "A" is the departure point, the numbers are
    // the stops after it, matching the order that gets submitted.
    var refreshStops = function () {
      rows().forEach(function (row, index) {
        var marker = row.querySelector(".stop-marker");
        if (marker) {
          marker.textContent = index === 0 ? "A" : String(index);
        }
        var remove = row.querySelector('button[data-action="remove"]');
        if (remove) {
          remove.setAttribute("aria-label", "Hapus pemberhentian " + index);
        }
      });
      updateRouteDistance();
    };

    // The map draws via Google's keyless embed, which needs no API key and
    // costs nothing to call - it already shows its own distance/time badge.
    // The real road distance is billed per call, so it is fetched exactly
    // once per operation, server-side, only when the planner saves
    // (CreateDailyOperation calls the routing provider then), never here on
    // every stop edit. There is deliberately no separate distance readout on
    // this panel any more: a second, differently-sourced number next to the
    // map's own badge read as a discrepancy, not extra information.
    var mapImage = document.querySelector("#route-map");
    var statusLine = document.querySelector("#route-status");

    var chosenStops = function () {
      return rows()
        .map(function (row) {
          return row.querySelector('select[name="stop_sequence"]');
        })
        .filter(function (select) {
          return select && select.value;
        })
        .map(function (select) {
          return select.value;
        });
    };

    var chosenPoints = function () {
      var points = [];
      rows().forEach(function (row) {
        var select = row.querySelector('select[name="stop_sequence"]');
        var option = select && select.selectedOptions ? select.selectedOptions[0] : null;
        if (!option || !option.dataset || option.dataset.lat === undefined) {
          return;
        }
        var lat = parseFloat(option.dataset.lat);
        var lon = parseFloat(option.dataset.lon);
        if (isFinite(lat) && isFinite(lon)) {
          points.push([lat, lon]);
        }
      });
      return points;
    };

    // Google's keyless embed: origin, then each following stop chained with
    // "+to:", so the drawn route keeps the planner's order.
    var embedUrl = function (points) {
      var origin = points[0][0] + "," + points[0][1];
      var rest = points.slice(1).map(function (point) {
        return point[0] + "," + point[1];
      });
      return (
        "https://maps.google.com/maps?saddr=" +
        encodeURIComponent(origin) +
        "&daddr=" +
        encodeURIComponent(rest.join(" to:")) +
        "&output=embed"
      );
    };

    var showEmptyRoute = function (message) {
      if (mapImage) {
        mapImage.hidden = true;
        mapImage.removeAttribute("src");
      }
      if (statusLine) {
        statusLine.textContent = message;
      }
    };

    var updateRouteDistance = function () {
      var stops = chosenStops();
      var points = chosenPoints();
      if (stops.length < 2 || points.length < 2) {
        showEmptyRoute("Pilih minimal dua lokasi untuk menggambar rute.");
        return;
      }

      // The map itself needs no API key: Google's embed draws the route from
      // the coordinates the location catalog already gave us.
      if (mapImage) {
        mapImage.src = embedUrl(points);
        mapImage.hidden = false;
      }
      if (statusLine) {
        statusLine.textContent = "Rute Google Maps, dalam urutan yang dimasukkan.";
      }
    };

    // A new row is cloned from an existing stop so it inherits the location
    // catalog without restating it here.
    var newStopRow = function () {
      var template = sequence.querySelector(".stop-row:not(.stop-row--start)");
      if (!template) {
        return null;
      }
      var row = template.cloneNode(true);
      row.classList.remove("stop-row--dragging");
      row.removeAttribute("style");
      Array.prototype.slice.call(row.querySelectorAll("select")).forEach(function (select) {
        select.selectedIndex = 0;
      });
      return row;
    };

    addStop.addEventListener("click", function () {
      var row = newStopRow();
      if (!row) {
        return;
      }
      sequence.appendChild(row);
      refreshStops();
      var select = row.querySelector('select[name="stop_sequence"]');
      if (select) {
        select.focus();
      }
    });

    sequence.addEventListener("click", function (event) {
      var button = event.target.closest('button[data-action="remove"]');
      if (!button) {
        return;
      }
      // One stop after the departure point is the minimum a route can have.
      if (sequence.children.length <= 2) {
        return;
      }
      button.closest(".stop-row").remove();
      refreshStops();
    });

    sequence.addEventListener("change", function (event) {
      if (event.target.name === "stop_sequence") {
        updateRouteDistance();
      }
    });

    // Drag to reorder. Only the stops after the departure point move, so the
    // route always starts where the planner said it starts.
    //
    // The dragged row follows the pointer; the rows it passes slide out of the
    // way. Markers are renumbered as it goes, but the map is redrawn once,
    // when the row is dropped: reloading the embed on every pointer move is
    // what made the old drag stutter.
    var drag = null;

    var slideRows = function (before) {
      rows().forEach(function (row) {
        var oldTop = before.get(row);
        if (row === drag.row || oldTop === undefined) {
          return;
        }
        var delta = oldTop - row.getBoundingClientRect().top;
        if (Math.abs(delta) > 0.5) {
          row.style.transition = "none";
          row.style.transform = "translateY(" + delta + "px)";
          requestAnimationFrame(function () {
            requestAnimationFrame(function () {
              row.style.transition = "transform 160ms ease-out";
              row.style.transform = "";
              window.setTimeout(function () {
                row.style.transition = "";
              }, 180);
            });
          });
        }
      });
    };

    var renumber = function () {
      rows().forEach(function (row, index) {
        var marker = row.querySelector(".stop-marker");
        if (marker) {
          marker.textContent = index === 0 ? "A" : String(index);
        }
      });
    };

    var moveTo = function (target) {
      var before = new Map();
      rows().forEach(function (row) {
        before.set(row, row.getBoundingClientRect().top);
      });
      var draggedTop = before.get(drag.row);
      var draggedIndex = rows().indexOf(drag.row);
      var targetIndex = rows().indexOf(target);
      if (targetIndex < draggedIndex) {
        sequence.insertBefore(drag.row, target);
      } else {
        sequence.insertBefore(drag.row, target.nextElementSibling);
      }
      // The row's slot moved under it; shift the origin so the row stays
      // exactly where the pointer holds it, without a jump.
      drag.originY += drag.row.getBoundingClientRect().top - draggedTop;
      drag.row.style.transform = "translateY(" + (drag.lastY - drag.originY) + "px)";
      renumber();
      slideRows(before);
      drag.moved = true;
    };

    var onPointerMove = function (event) {
      if (!drag) {
        return;
      }
      drag.lastY = event.clientY;
      drag.row.style.transform = "translateY(" + (event.clientY - drag.originY) + "px)";
      // Swap only once the pointer has crossed the middle of a neighbour, so
      // rows of different heights cannot flip back and forth on the boundary.
      var candidates = rows().slice(1);
      for (var index = 0; index < candidates.length; index += 1) {
        var candidate = candidates[index];
        if (candidate === drag.row) {
          continue;
        }
        var box = candidate.getBoundingClientRect();
        var middle = box.top + box.height / 2;
        var above = candidates.indexOf(candidate) < candidates.indexOf(drag.row);
        if ((above && event.clientY < middle) || (!above && event.clientY > middle)) {
          moveTo(candidate);
          return;
        }
      }
    };

    var endDrag = function () {
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", endDrag);
      document.removeEventListener("pointercancel", endDrag);
      window.removeEventListener("blur", endDrag);
      if (!drag) {
        return;
      }
      var row = drag.row;
      var moved = drag.moved;
      drag = null;
      row.classList.remove("stop-row--dragging");
      // Settle into the slot, then clear the inline styles so the row is
      // plain again for the next drag or a clone.
      row.style.transition = "transform 120ms ease-out";
      row.style.transform = "";
      window.setTimeout(function () {
        row.style.transition = "";
      }, 140);
      if (moved) {
        refreshStops();
      }
    };

    sequence.addEventListener("pointerdown", function (event) {
      var handle = event.target.closest('[data-action="drag"]');
      if (!handle || event.button !== 0) {
        return;
      }
      event.preventDefault();
      var row = handle.closest(".stop-row");
      drag = { row: row, originY: event.clientY, lastY: event.clientY, moved: false };
      row.classList.add("stop-row--dragging");
      row.style.transition = "none";
      // Capture the pointer so the release reaches us even when the button
      // comes up outside the window; a drag that never ends left the row
      // faded and reordering on every later mouse move.
      if (handle.setPointerCapture) {
        try {
          handle.setPointerCapture(event.pointerId);
        } catch (error) {
          // Not capturable (synthetic event, unsupported browser): the
          // document listeners below still end an ordinary drag.
        }
      }
      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", endDrag);
      document.addEventListener("pointercancel", endDrag);
      window.addEventListener("blur", endDrag);
    });

    refreshStops();
  }

  // The fallback distance only applies when the planner is entering it by
  // hand; a route-sourced distance is computed from the stops instead.
  var distanceSource = document.querySelector("#field-distance_source");
  var manualDistance = document.querySelector("#manual-distance");
  if (distanceSource && manualDistance) {
    var syncDistanceSource = function () {
      var manual = distanceSource.value === "manual";
      manualDistance.hidden = !manual;
      var input = manualDistance.querySelector("input");
      if (input) {
        input.required = manual;
      }
    };
    distanceSource.addEventListener("change", syncDistanceSource);
    syncDistanceSource();
  }
})();
