/* Progressive enhancement only (ADR 0007).
   Every workflow below already works without JavaScript; this adds convenience. */

(function () {
  "use strict";

  // Move focus to the error summary so a screen reader announces the failure.
  var summary = document.getElementById("ringkasan-kesalahan");
  if (summary) {
    summary.focus();
  }

  // Phone-width menu. The <html class="js"> hook in base.html is what hides
  // the drawer, so a browser with no script never loses its navigation.
  var navToggle = document.querySelector(".nav-toggle");
  var navHeader = document.querySelector(".app__nav");
  if (navToggle && navHeader) {
    navToggle.addEventListener("click", function () {
      var open = navHeader.classList.toggle("app__nav--open");
      navToggle.setAttribute("aria-expanded", open ? "true" : "false");
      // The button says what it does next, so the way out is plain.
      navToggle.textContent = open ? "Tutup" : "Menu";
    });
  }

  // Folding sidebar groups. The server opens the group that holds the current
  // page; this remembers the ones the person unfolded themselves so they stay
  // open on the next page. Applying that memory is base.html's inline script,
  // which has to run before the sidebar's scroll offset is restored; this is
  // only the half that records a change. Storage can be refused, hence guards.
  var NAV_STATE = "nav-groups-open";
  var readOpenGroups = function () {
    try {
      return JSON.parse(window.localStorage.getItem(NAV_STATE) || "[]");
    } catch (error) {
      return [];
    }
  };
  document.querySelectorAll("details[data-nav-group]").forEach(function (group) {
    var name = group.getAttribute("data-nav-group");
    group.addEventListener("toggle", function () {
      var remembered = readOpenGroups().filter(function (item) {
        return item !== name;
      });
      if (group.open) {
        remembered.push(name);
      }
      try {
        window.localStorage.setItem(NAV_STATE, JSON.stringify(remembered));
      } catch (error) {
        // Private mode or storage disabled: the menu still works, it just forgets.
      }
    });
  });

  // Sidebar scroll offset. Every menu click is a full page load, so without
  // this the list rebuilds at the top and the item just clicked walks away
  // from the pointer. base.html restores the offset inline, before the first
  // paint; this is the half that records it.
  var navScroller = document.querySelector("[data-nav-scroll]");
  if (navScroller) {
    var pending = null;
    var rememberScroll = function () {
      try {
        window.sessionStorage.setItem("nav-scroll", String(navScroller.scrollTop));
      } catch (error) {
        // Private mode or storage disabled: the sidebar just starts at the top.
      }
    };
    navScroller.addEventListener("scroll", function () {
      // Debounced, so a flick of the wheel is one write rather than thirty.
      window.clearTimeout(pending);
      pending = window.setTimeout(rememberScroll, 100);
    });
    // A click can navigate before the debounce fires, so record it on the
    // way out too.
    window.addEventListener("pagehide", rememberScroll);
  }

  // Show the password. The field keeps its name and value throughout - only
  // the type changes - so a half-typed password survives the switch, and the
  // button reverts to hidden state on the next page like any other load.
  document.querySelectorAll("[data-password-reveal]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("data-password-reveal"));
    if (!input) {
      return;
    }
    button.hidden = false;
    button.addEventListener("click", function () {
      var revealed = input.type === "text";
      input.type = revealed ? "password" : "text";
      button.setAttribute("aria-pressed", revealed ? "false" : "true");
      var label = revealed ? "Tampilkan kata sandi" : "Sembunyikan kata sandi";
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
    });
  });

  // Recording actual fuel: say which waiting operation the typed code is, and
  // warn - without blocking - when the litres are far from its allocation,
  // which is nearly always a typo or the wrong operation. The waiting list's
  // rows carry what is needed; the server stays the authority on the code.
  var codeInput = document.querySelector("#field-operation_id");
  var chosenBox = document.querySelector("[data-chosen-operation]");
  if (codeInput && chosenBox) {
    var waiting = Array.prototype.slice.call(document.querySelectorAll("li[data-ref-id]"));
    var notWaiting = document.querySelector("[data-code-not-waiting]");
    var litresInput = document.querySelector("#field-actual_fuel_liters");
    var litresWarning = document.querySelector("[data-litres-warning]");
    var chosenAllocation = null;
    var normalise = function (value) { return value.replace(/\s+/g, "").toUpperCase(); };
    var formatLitres = function (value) { return value.toLocaleString("id-ID", { maximumFractionDigits: 2 }); };
    var checkLitres = function () {
      if (!litresInput || !litresWarning) { return; }
      var litres = parseFloat((litresInput.value || "").replace(",", "."));
      var far = chosenAllocation && litres > 0 && (litres > chosenAllocation * 2 || litres < chosenAllocation * 0.4);
      litresWarning.hidden = !far;
      if (far) {
        litresWarning.textContent = formatLitres(litres) + " L jauh dari alokasi " + formatLitres(chosenAllocation)
          + " L untuk operasi ini. Periksa lagi angka dan kodenya sebelum menyimpan.";
      }
    };
    var showChosen = function () {
      var typed = normalise(codeInput.value || "");
      var match = null;
      waiting.forEach(function (row) {
        if (typed && (row.getAttribute("data-ref") === typed || row.getAttribute("data-ref-id") === typed)) {
          match = row;
        }
      });
      chosenBox.hidden = !match;
      chosenAllocation = match ? parseFloat(match.getAttribute("data-allocation")) : null;
      if (match) {
        chosenBox.querySelector("[data-chosen-vehicle]").textContent = match.getAttribute("data-vehicle");
        chosenBox.querySelector("[data-chosen-route]").textContent = match.getAttribute("data-route");
        chosenBox.querySelector("[data-chosen-when]").textContent = match.getAttribute("data-when");
        chosenBox.querySelector("[data-chosen-allocation]").textContent = formatLitres(chosenAllocation);
      }
      // Only once the code looks complete (date and time typed), so the note
      // does not nag on every keystroke.
      if (notWaiting) { notWaiting.hidden = Boolean(match) || typed.length < 11; }
      checkLitres();
    };
    codeInput.addEventListener("input", showChosen);
    if (litresInput) { litresInput.addEventListener("input", checkLitres); }
    showChosen();
  }

  // Arriving with the operation already chosen (a "Catat" link), the only
  // thing left to type is the litres, so start there.
  var chosenOperation = document.querySelector("#field-operation_id");
  var actualLitres = document.querySelector("#field-actual_fuel_liters");
  if (chosenOperation && actualLitres && chosenOperation.value && !actualLitres.value && !summary) {
    actualLitres.focus();
  }

  // Copy buttons stay hidden until the script runs, since without it they
  // could not do anything. The label confirms briefly, then returns.
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    if (!navigator.clipboard) {
      return;
    }
    button.hidden = false;
    var label = button.textContent;
    button.addEventListener("click", function () {
      navigator.clipboard.writeText(button.getAttribute("data-copy")).then(function () {
        button.textContent = "Tersalin";
        window.setTimeout(function () {
          button.textContent = label;
        }, 1500);
      });
    });
  });

  // One submission per click. A second click while the first is on its way
  // sent the form twice - two operations for one job, the second coded -2.
  // The button says it is working; going back to the page (the browser's
  // back-forward cache) makes it usable again.
  document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (form.hasAttribute("data-submitting")) {
        event.preventDefault();
        return;
      }
      form.setAttribute("data-submitting", "");
      var button = event.submitter || form.querySelector('button[type="submit"], button:not([type])');
      if (button) {
        button.setAttribute("aria-busy", "true");
        button.setAttribute("data-label", button.textContent);
        button.textContent = "Memproses…";
      }
    });
  });
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted) {
      return;
    }
    document.querySelectorAll("form[data-submitting]").forEach(function (form) {
      form.removeAttribute("data-submitting");
      form.querySelectorAll('[aria-busy="true"]').forEach(function (button) {
        button.removeAttribute("aria-busy");
        button.textContent = button.getAttribute("data-label") || button.textContent;
      });
    });
  });

  // File pickers become a drop zone that names the chosen file. The real
  // input stays underneath and covers the zone, so clicking, the keyboard
  // and screen readers all work on it; without this script the browser's
  // own picker shows instead (see .file-drop in app.css).
  document.querySelectorAll("[data-file-drop]").forEach(function (zone) {
    var input = zone.querySelector('input[type="file"]');
    var name = zone.querySelector("[data-file-name]");
    if (!input || !name) {
      return;
    }
    var empty = name.textContent;
    var show = function () {
      var file = input.files && input.files[0];
      name.textContent = file ? file.name + " · " + Math.max(1, Math.round(file.size / 1024)) + " KB" : empty;
      zone.classList.toggle("file-drop--chosen", Boolean(file));
    };
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach(function (type) {
      zone.addEventListener(type, function () { zone.classList.add("file-drop--over"); });
    });
    ["dragleave", "drop"].forEach(function (type) {
      zone.addEventListener(type, function () { zone.classList.remove("file-drop--over"); });
    });
    show();
  });

  // "Print all slips" on a bulk result: print the slips section alone.
  var printSlips = document.querySelector("[data-print-slips]");
  if (printSlips && document.querySelector("[data-slip-batch]")) {
    printSlips.hidden = false;
    printSlips.addEventListener("click", function () {
      document.documentElement.classList.add("printing-slips");
      window.print();
    });
    window.addEventListener("afterprint", function () {
      document.documentElement.classList.remove("printing-slips");
    });
  }

  // A dialog the server rendered open (a rejected submission) becomes a real
  // modal, so it gets its backdrop and its focus trap like one opened here.
  document.querySelectorAll("dialog[open]").forEach(function (dialog) {
    if (typeof dialog.showModal === "function") {
      dialog.removeAttribute("open");
      dialog.showModal();
    }
  });

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

  // Show the chosen filename for a file input outside a drop zone (which
  // names the file itself, and must not have its format hint overwritten).
  document.querySelectorAll('input[type="file"]:not([data-file-drop] input)').forEach(function (input) {
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

    // Only a unit that can lift may be planned with lifting. The list comes
    // from the fleet catalog; the server refuses lifting for anything else,
    // so this only spares the planner a rejected form.
    var gate = document.querySelector("[data-lifting-vehicles]");
    var vehicle = document.querySelector("#field-vehicle");
    if (gate && vehicle) {
      var liftingVehicles = JSON.parse(gate.getAttribute("data-lifting-vehicles") || "[]");
      var syncCapacity = function () {
        var canLift = liftingVehicles.indexOf(vehicle.value) !== -1;
        Array.prototype.forEach.call(activityMode.options, function (option) {
          if (LIFTING_MODES.indexOf(option.value) !== -1) {
            option.disabled = !canLift;
          }
        });
        if (!canLift && LIFTING_MODES.indexOf(activityMode.value) !== -1) {
          activityMode.value = "transport";
          syncLifting();
        }
      };
      vehicle.addEventListener("change", syncCapacity);
      syncCapacity();
    }
  }

  // The same unit leaves the same pool most days. Remember the last vehicle
  // and departure point in this browser and offer them when the form is
  // otherwise empty; a value the server sent back (a rejected submission)
  // always wins. Storage can be missing or refused, hence the guards.
  var operationForm = document.querySelector('form[action="/operasi-harian"]');
  if (operationForm) {
    var LAST_PLAN = "last-operation-plan";
    var vehicleSelect = operationForm.querySelector("#field-vehicle");
    var departureInput = operationForm.querySelector('input[name="stop_sequence"]');
    try {
      var remembered = JSON.parse(window.localStorage.getItem(LAST_PLAN) || "null");
      if (remembered) {
        if (vehicleSelect && !vehicleSelect.value && remembered.vehicle) {
          vehicleSelect.value = remembered.vehicle;
        }
        if (departureInput && !departureInput.value && remembered.departure) {
          departureInput.value = remembered.departure;
          departureInput.dispatchEvent(new Event("input", { bubbles: true }));
        }
      }
    } catch (error) {
      // Nothing remembered; the form simply starts empty.
    }
    operationForm.addEventListener("submit", function () {
      try {
        window.localStorage.setItem(
          LAST_PLAN,
          JSON.stringify({
            vehicle: vehicleSelect ? vehicleSelect.value : "",
            departure: departureInput ? departureInput.value.trim() : "",
          })
        );
      } catch (error) {
        // Private mode or storage disabled: next time starts empty again.
      }
    });
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
    var mapCanvas = document.querySelector("#route-canvas");
    var statusLine = document.querySelector("#route-status");

    // Stops are typed into inputs backed by one shared <datalist>; the
    // coordinates live on its options, read once into a map keyed the same
    // way the server matches names (trimmed, case-insensitive).
    var coordinates = {};
    var catalog = document.querySelector("#katalog-lokasi");
    if (catalog) {
      Array.prototype.slice.call(catalog.options).forEach(function (option) {
        var lat = parseFloat(option.dataset.lat);
        var lon = parseFloat(option.dataset.lon);
        if (isFinite(lat) && isFinite(lon)) {
          coordinates[option.value.trim().toLowerCase()] = [lat, lon];
        }
      });
    }

    var stopInputs = function () {
      return rows()
        .map(function (row) {
          return row.querySelector('input[name="stop_sequence"]');
        })
        .filter(function (input) {
          return input;
        });
    };

    var chosenStops = function () {
      return stopInputs()
        .map(function (input) {
          return input.value.trim();
        })
        .filter(function (value) {
          return value;
        });
    };

    var chosenPoints = function () {
      var points = [];
      chosenStops().forEach(function (name) {
        var point = coordinates[name.toLowerCase()];
        if (point) {
          points.push(point);
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
      if (mapCanvas) {
        mapCanvas.hidden = true;
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
      if (mapCanvas) {
        mapCanvas.hidden = false;
      }
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
      Array.prototype.slice.call(row.querySelectorAll("input")).forEach(function (input) {
        input.value = "";
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
      var input = row.querySelector('input[name="stop_sequence"]');
      if (input) {
        input.focus();
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

    // "input" rather than "change": picking from the datalist and typing a
    // full name both fire it, so the map follows without waiting for blur.
    sequence.addEventListener("input", function (event) {
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

})();
