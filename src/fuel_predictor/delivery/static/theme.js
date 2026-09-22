/* Run before the stylesheet so a remembered dark theme never flashes light. */
(function () {
  "use strict";
  /* A page that fixes its own appearance - the signed-out ones - keeps it.
     Nothing here reads, writes or overrides a preference there. */
  if (document.documentElement.hasAttribute("data-theme-locked")) {
    return;
  }
  var key = "fuel-predictor-theme";
  var system = window.matchMedia("(prefers-color-scheme: dark)");
  var choices = ["light", "dark"];
  /* Null means nobody has flipped the switch yet, so the system decides. */
  var preference = null;

  function readPreference() {
    try {
      var saved = window.localStorage.getItem(key);
      return choices.includes(saved) ? saved : null;
    } catch (error) {
      return null;
    }
  }

  function currentTheme() {
    return preference || (system.matches ? "dark" : "light");
  }

  function apply() {
    var theme = currentTheme();
    document.documentElement.dataset.theme = theme;
    /* The label names the destination, because that is what the one visible
       glyph is showing. */
    var next = theme === "dark" ? "Ganti ke mode terang" : "Ganti ke mode gelap";
    document.querySelectorAll("[data-theme-toggle]").forEach(function (toggle) {
      toggle.setAttribute("aria-label", next);
      toggle.setAttribute("title", next);
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
    document.querySelectorAll("[data-theme-toggle]").forEach(function (toggle) {
      toggle.addEventListener("click", function () {
        preference = currentTheme() === "dark" ? "light" : "dark";
        try {
          window.localStorage.setItem(key, preference);
        } catch (error) {
          // The switch still works for this page when storage is unavailable.
        }
        apply();
      });
      toggle.hidden = false;
    });
    apply();
  });
})();
