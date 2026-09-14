(function () {
  "use strict";

  const STORAGE_KEY = "planbasket-lang";
  const DEFAULT_LOCALE = "ko-KR";

  function normalize(locale) {
    const value = String(locale || "").toLowerCase();

    if (value.startsWith("en")) {
      return "en-US";
    }

    return DEFAULT_LOCALE;
  }

  window.TF_LOCALE = Object.freeze({
    get() {
      try {
        return normalize(localStorage.getItem(STORAGE_KEY));
      } catch {
        return DEFAULT_LOCALE;
      }
    },

    set(locale) {
      const normalized = normalize(locale);
      const storageValue = normalized === "en-US" ? "en" : "ko";

      try {
        localStorage.setItem(STORAGE_KEY, storageValue);
      } catch {
        // Keep the page usable when browser storage is unavailable.
      }

      return normalized;
    },

    isEnglish() {
      return this.get() === "en-US";
    }
  });
})();
