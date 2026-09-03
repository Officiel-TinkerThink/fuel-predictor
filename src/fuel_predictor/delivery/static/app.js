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
  var lifting = document.querySelector("#field-lifting_hours");
  var liftingField = document.querySelector("#lifting-field");
  var stopsContainer = document.querySelector("#stop-sequence");
  if (lifting && liftingField && stopsContainer) {
    var LIFTING_ACTIVITIES = ["Muat", "Bongkar"];
    var syncLifting = function () {
      var applies = Array.prototype.slice
        .call(stopsContainer.querySelectorAll('select[name="stop_activity"]'))
        .some(function (select) {
          return LIFTING_ACTIVITIES.indexOf(select.value) !== -1;
        });
      lifting.required = applies;
      liftingField.hidden = !applies;
      if (!applies) {
        lifting.value = "";
      }
    };
    // Delegated, so rows added after load are covered too.
    stopsContainer.addEventListener("change", function (event) {
      if (event.target.name === "stop_activity") {
        syncLifting();
      }
    });
    document.addEventListener("claude:stops-changed", syncLifting);
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
      // Rows added or removed can change whether any stop lifts, which is what
      // decides if the lifting-hours field applies.
      document.dispatchEvent(new CustomEvent("claude:stops-changed"));
    };

    // The panel shows the real Google Maps route when a routing key is
    // configured. The app fetches it server-side, so the API key never
    // reaches this page. The map itself needs no key; only the road distance
    // does, so without one the readout falls back to a straight-line estimate,
    // marked so it cannot be mistaken for a road distance.
    var previewPanel = document.querySelector(".route-preview");
    var previewEnabled = !!previewPanel && previewPanel.dataset.routePreview === "on";
    var mapImage = document.querySelector("#route-map");
    var statusLine = document.querySelector("#route-status");
    var readout = document.querySelector("#route-distance");
    var routeTimer = null;

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

    var straightLineKm = function () {
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
      if (points.length < 2) {
        return null;
      }
      var total = 0;
      for (var index = 1; index < points.length; index += 1) {
        total += haversineKm(points[index - 1], points[index]);
      }
      return total;
    };

    var showEmptyRoute = function (message) {
      if (mapImage) {
        mapImage.hidden = true;
        mapImage.removeAttribute("src");
      }
      if (statusLine) {
        statusLine.textContent = message;
      }
      var estimate = straightLineKm();
      if (readout) {
        readout.textContent =
          estimate === null ? "—" : "±" + estimate.toFixed(1).replace(".", ",") + " km";
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

      // The road distance does need the Routes API. Without it, fall back to
      // a straight-line estimate, marked so it cannot be mistaken for one.
      var estimate = straightLineKm();
      var fallbackLabel =
        estimate === null ? "—" : "±" + estimate.toFixed(1).replace(".", ",") + " km";
      if (!previewEnabled) {
        if (readout) {
          readout.textContent = fallbackLabel;
        }
        return;
      }
      var query = stops
        .map(function (stop) {
          return "lokasi=" + encodeURIComponent(stop);
        })
        .join("&");
      window.clearTimeout(routeTimer);
      routeTimer = window.setTimeout(function () {
        fetch("/prediksi/rute?" + query, { headers: { Accept: "application/json" } })
          .then(function (response) {
            return response.ok ? response.json() : Promise.reject(response);
          })
          .then(function (data) {
            if (readout) {
              readout.textContent = String(data.jarak_km).replace(".", ",") + " km";
            }
          })
          .catch(function () {
            if (readout) {
              readout.textContent = fallbackLabel;
            }
          });
      }, 400);
    };

    var haversineKm = function (from, to) {
      var radians = Math.PI / 180;
      var earthRadiusKm = 6371;
      var dLat = (to[0] - from[0]) * radians;
      var dLon = (to[1] - from[1]) * radians;
      var a =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(from[0] * radians) *
          Math.cos(to[0] * radians) *
          Math.sin(dLon / 2) *
          Math.sin(dLon / 2);
      return 2 * earthRadiusKm * Math.asin(Math.min(1, Math.sqrt(a)));
    };

    // A new row is cloned from an existing stop so it inherits the location
    // catalog and the activity list without restating either here.
    var newStopRow = function () {
      var template = sequence.querySelector(".stop-row:not(.stop-row--start)");
      if (!template) {
        return null;
      }
      var row = template.cloneNode(true);
      row.classList.remove("stop-row--dragging");
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
    var dragged = null;

    var playFlip = function (before) {
      rows().forEach(function (row) {
        var oldTop = before.get(row);
        if (oldTop === undefined) {
          return;
        }
        var delta = oldTop - row.getBoundingClientRect().top;
        if (Math.abs(delta) > 0.5) {
          row.style.transition = "none";
          row.style.transform = "translateY(" + delta + "px)";
          requestAnimationFrame(function () {
            requestAnimationFrame(function () {
              row.style.transition = "transform 550ms cubic-bezier(.4,0,.2,1)";
              row.style.transform = "";
            });
          });
        }
      });
    };

    var moveTo = function (target) {
      if (!dragged || target === dragged || target === sequence.firstElementChild) {
        return;
      }
      var before = new Map();
      rows().forEach(function (row) {
        before.set(row, row.getBoundingClientRect().top);
      });
      var draggedIndex = rows().indexOf(dragged);
      var targetIndex = rows().indexOf(target);
      if (targetIndex < draggedIndex) {
        sequence.insertBefore(dragged, target);
      } else {
        sequence.insertBefore(dragged, target.nextElementSibling);
      }
      refreshStops();
      playFlip(before);
    };

    var onPointerMove = function (event) {
      if (!dragged) {
        return;
      }
      var candidates = rows().slice(1);
      for (var index = 0; index < candidates.length; index += 1) {
        var box = candidates[index].getBoundingClientRect();
        if (event.clientY >= box.top && event.clientY <= box.bottom) {
          moveTo(candidates[index]);
          return;
        }
      }
    };

    var endDrag = function () {
      if (dragged) {
        dragged.classList.remove("stop-row--dragging");
        dragged = null;
      }
      document.removeEventListener("pointermove", onPointerMove);
      document.removeEventListener("pointerup", endDrag);
    };

    sequence.addEventListener("pointerdown", function (event) {
      var handle = event.target.closest('[data-action="drag"]');
      if (!handle) {
        return;
      }
      event.preventDefault();
      dragged = handle.closest(".stop-row");
      dragged.classList.add("stop-row--dragging");
      document.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerup", endDrag);
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
