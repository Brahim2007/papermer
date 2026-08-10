(function () {
  "use strict";

  const toggle = document.querySelector("[data-nav-toggle]");
  const navigation = document.querySelector("[data-site-navigation]");
  if (toggle && navigation) {
    const closeNavigation = function (returnFocus) {
      toggle.setAttribute("aria-expanded", "false");
      toggle.classList.remove("nav-toggle--open");
      navigation.classList.remove("primary-nav--open");
      if (returnFocus) toggle.focus();
    };

    toggle.addEventListener("click", function () {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      navigation.classList.toggle("primary-nav--open", !expanded);
      toggle.classList.toggle("nav-toggle--open", !expanded);
    });

    navigation.addEventListener("click", function (event) {
      if (event.target.closest("a") && window.innerWidth <= 1040) {
        closeNavigation(false);
      }
    });

    document.addEventListener("click", function (event) {
      if (
        toggle.getAttribute("aria-expanded") === "true" &&
        !navigation.contains(event.target) &&
        !toggle.contains(event.target)
      ) {
        closeNavigation(false);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") {
        closeNavigation(true);
      }
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 1040) closeNavigation(false);
    });
  }

  document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      const input = document.getElementById(button.dataset.passwordToggle);
      if (!input) return;
      const showing = input.type === "text";
      input.type = showing ? "password" : "text";
      button.setAttribute("aria-pressed", String(!showing));
      button.textContent = showing
        ? button.dataset.showLabel
        : button.dataset.hideLabel;
    });
  });

  document.querySelectorAll("details").forEach(function (details) {
    details.addEventListener("toggle", function () {
      if (!details.open) return;
      document.querySelectorAll("details[open]").forEach(function (other) {
        if (other !== details) other.removeAttribute("open");
      });
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    const openMenu = document.querySelector(".site-header details[open]");
    if (!openMenu) return;
    openMenu.removeAttribute("open");
    const summary = openMenu.querySelector("summary");
    if (summary) summary.focus();
  });
})();
