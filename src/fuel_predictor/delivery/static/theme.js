/* Run before the stylesheet so a remembered dark theme never flashes light. */
(function () {
  "use strict";
  var key = "fuel-predictor-theme";
  var system = window.matchMedia("(prefers-color-scheme: dark)");
  var preference = "system";
  var choices = ["system", "light", "dark"];

  function readPreference() {
    try {
      var saved = window.localStorage.getItem(key);
      return choices.includes(saved) ? saved : "system";
    } catch (error) {
      return "system";
    }
  }

  function apply() {
    document.documentElement.dataset.theme = preference === "system"
      ? (system.matches ? "dark" : "light") : preference;
    document.querySelectorAll("[data-theme-select]").forEach(function (select) {
      select.value = preference;
    });
  }

  preference = readPreference();
  apply();
  system.addEventListener("change", apply);
  window.addEventListener("storage", function (event) {
    if (event.key === key || event.key === null) {
      preference = readPreference();
      apply();
    }
  });
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-theme-picker]").forEach(function (picker) {
      var select = picker.querySelector("[data-theme-select]");
      select.value = preference;
      select.addEventListener("change", function () {
        preference = select.value;
        try {
          window.localStorage.setItem(key, preference);
        } catch (error) {
          // The selection still works for this page when storage is unavailable.
        }
        apply();
      });
      picker.hidden = false;
    });
  });
})();
