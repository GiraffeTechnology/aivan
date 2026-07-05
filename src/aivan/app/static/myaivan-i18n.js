/* myaivan UI i18n.
 *
 * English is the system/canonical language (all markup defaults to English).
 * The active language defaults to the visitor's system/browser language and
 * can be switched anytime via the 🌐 selector; the choice is persisted.
 * Non-builtin languages are translated server-side through
 * giraffe-language-skill and fail soft to English.
 */
(function () {
  "use strict";

  var LANG_KEY = "myaivan.lang";
  var catalogStrings = {};
  var currentLang = "en";

  function normalize(tag) {
    return String(tag || "en").toLowerCase().split("-")[0].split("_")[0] || "en";
  }

  function defaultLang() {
    return normalize(localStorage.getItem(LANG_KEY) || navigator.language || "en");
  }

  function t(key, fallback) {
    return catalogStrings[key] || fallback || key;
  }

  function applyToDom() {
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var value = catalogStrings[el.dataset.i18n];
      if (value) el.textContent = value;
    });
    document.querySelectorAll("[data-i18n-title]").forEach(function (el) {
      var value = catalogStrings[el.dataset.i18nTitle];
      if (value) el.title = value;
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      var value = catalogStrings[el.dataset.i18nPlaceholder];
      if (value) el.placeholder = value;
    });
    document.documentElement.lang = currentLang;
  }

  function populateSwitcher(languages) {
    var select = document.getElementById("lang-select");
    if (!select || select.options.length) return;
    Object.keys(languages).forEach(function (code) {
      var opt = document.createElement("option");
      opt.value = code;
      opt.textContent = languages[code];
      select.appendChild(opt);
    });
    select.value = currentLang;
    select.addEventListener("change", function () {
      setLang(select.value);
    });
  }

  async function loadCatalog(lang) {
    try {
      var resp = await fetch("/api/myaivan/i18n/" + encodeURIComponent(lang));
      if (!resp.ok) throw new Error(String(resp.status));
      var data = await resp.json();
      currentLang = data.lang || lang;
      catalogStrings = data.strings || {};
      applyToDom();
      populateSwitcher(data.languages || { en: "English", zh: "中文" });
      var select = document.getElementById("lang-select");
      if (select) select.value = currentLang;
      document.dispatchEvent(new CustomEvent("myaivan:lang", { detail: { lang: currentLang } }));
    } catch (e) {
      // Fail soft: English markup stays as-is.
      currentLang = "en";
    }
  }

  function setLang(lang) {
    var normalized = normalize(lang);
    localStorage.setItem(LANG_KEY, normalized);
    loadCatalog(normalized);
  }

  window.MyaivanI18n = { t: t, setLang: setLang, lang: function () { return currentLang; } };

  document.addEventListener("DOMContentLoaded", function () {
    loadCatalog(defaultLang());
  });
})();
