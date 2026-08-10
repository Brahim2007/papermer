(function () {
  "use strict";

  const root = document.querySelector("[data-onboarding]");
  if (!root) return;

  const tabs = Array.from(root.querySelectorAll("[data-step]"));
  const panels = Array.from(root.querySelectorAll("[data-panel]"));
  const previousButton = root.querySelector("[data-previous]");
  const nextButton = root.querySelector("[data-next]");
  const stepLabel = root.querySelector("[data-step-label]");
  const status = root.querySelector("[data-status]");
  const strengthBar = root.querySelector("[data-strength-bar]");
  const strengthLabel = root.querySelector("[data-strength-label]");
  let currentStep = 0;

  const labels = {
    next: nextButton.textContent.trim(),
    finish: document.documentElement.lang.startsWith("ar")
      ? "عرض توصياتي"
      : "View my recommendations",
    saving: document.documentElement.lang.startsWith("ar")
      ? "جارٍ الحفظ…"
      : "Saving…",
    saved: document.documentElement.lang.startsWith("ar")
      ? "تم حفظ تفضيلاتك."
      : "Your preference was saved.",
    error: document.documentElement.lang.startsWith("ar")
      ? "تعذر الحفظ. حاول مرة أخرى."
      : "Could not save. Please try again.",
    emptyKeyword: document.documentElement.lang.startsWith("ar")
      ? "لم تُضف كلمات مفتاحية بعد."
      : "No keywords added yet.",
    emptyAuthor: document.documentElement.lang.startsWith("ar")
      ? "لم تُضف مؤلفين بعد."
      : "No authors added yet.",
  };

  function setStep(index, focusTab) {
    currentStep = Math.max(0, Math.min(index, tabs.length - 1));
    tabs.forEach(function (tab, tabIndex) {
      const active = tabIndex === currentStep;
      tab.setAttribute("aria-selected", String(active));
      tab.setAttribute("tabindex", active ? "0" : "-1");
      if (active && focusTab) tab.focus();
    });
    panels.forEach(function (panel, panelIndex) {
      const active = panelIndex === currentStep;
      panel.hidden = !active;
      panel.classList.toggle("onboarding-panel--active", active);
    });
    previousButton.disabled = currentStep === 0;
    nextButton.textContent =
      currentStep === tabs.length - 1 ? labels.finish : labels.next;
    stepLabel.textContent = document.documentElement.lang.startsWith("ar")
      ? `الخطوة ${currentStep + 1} من ${tabs.length}`
      : `Step ${currentStep + 1} of ${tabs.length}`;
  }

  function selectedCount() {
    return root.querySelectorAll(
      '[data-preference-type][aria-pressed="true"], [data-selected-value]'
    ).length;
  }

  function updateStrength() {
    const percent = Math.min(100, selectedCount() * 12);
    strengthBar.style.width = `${percent}%`;
    strengthLabel.textContent = `${percent}%`;
  }

  function showStatus(message, isError) {
    status.textContent = message;
    status.classList.toggle("onboarding-status--error", Boolean(isError));
  }

  async function postPreference(type, value, add) {
    const url =
      type === "topic"
        ? root.dataset.topicUrl
        : type === "keyword"
          ? root.dataset.keywordUrl
          : root.dataset.authorUrl;
    const body = new URLSearchParams();
    body.set("add", add ? "1" : "0");
    if (type === "topic") {
      body.set("tag", value);
    } else {
      const key = type === "keyword" ? "keywords" : "authors";
      body.set("data", JSON.stringify({ [key]: value }));
    }

    showStatus(labels.saving, false);
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "X-CSRFToken": root.dataset.csrfToken,
      },
      body: body.toString(),
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("Preference request failed");
    showStatus(labels.saved, false);
  }

  function tagElement(type, value) {
    const wrapper = document.createElement("span");
    wrapper.className = "selected-tag";
    wrapper.dataset.selectedValue = value;
    wrapper.append(document.createTextNode(value));

    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.removeType = type;
    remove.dataset.value = value;
    remove.setAttribute("aria-label", `Remove ${value}`);
    remove.textContent = "×";
    wrapper.append(remove);
    return wrapper;
  }

  function refreshEmptyState(type) {
    const list = root.querySelector(`[data-selected-list="${type}"]`);
    const tags = list.querySelectorAll("[data-selected-value]");
    const existingEmpty = list.querySelector("[data-empty]");
    if (tags.length && existingEmpty) existingEmpty.remove();
    if (!tags.length && !existingEmpty) {
      const empty = document.createElement("span");
      empty.className = "selected-empty";
      empty.dataset.empty = "";
      empty.textContent =
        type === "keyword" ? labels.emptyKeyword : labels.emptyAuthor;
      list.append(empty);
    }
  }

  tabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      setStep(Number(tab.dataset.step), false);
    });
    tab.addEventListener("keydown", function (event) {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      setStep(currentStep + direction, true);
    });
  });

  previousButton.addEventListener("click", function () {
    setStep(currentStep - 1, false);
  });

  nextButton.addEventListener("click", function () {
    if (currentStep === tabs.length - 1) {
      window.location.assign(root.dataset.finishUrl);
      return;
    }
    setStep(currentStep + 1, false);
  });

  root.querySelectorAll('[data-preference-type="topic"]').forEach(function (chip) {
    chip.addEventListener("click", async function () {
      const wasSelected = chip.getAttribute("aria-pressed") === "true";
      chip.disabled = true;
      try {
        await postPreference("topic", chip.dataset.value, !wasSelected);
        chip.setAttribute("aria-pressed", String(!wasSelected));
        updateStrength();
      } catch (error) {
        showStatus(labels.error, true);
      } finally {
        chip.disabled = false;
      }
    });
  });

  root.querySelectorAll("[data-tag-form]").forEach(function (form) {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();
      const type = form.dataset.tagForm;
      const input = form.querySelector("input");
      const value = input.value.trim().replace(/\s+/g, " ");
      if (!value) {
        input.focus();
        return;
      }
      const list = root.querySelector(`[data-selected-list="${type}"]`);
      const duplicate = Array.from(
        list.querySelectorAll("[data-selected-value]")
      ).some(function (tag) {
        return tag.dataset.selectedValue.toLowerCase() === value.toLowerCase();
      });
      if (duplicate) {
        input.select();
        return;
      }

      form.querySelector("button").disabled = true;
      try {
        await postPreference(type, value, true);
        list.append(tagElement(type, value));
        input.value = "";
        refreshEmptyState(type);
        updateStrength();
      } catch (error) {
        showStatus(labels.error, true);
      } finally {
        form.querySelector("button").disabled = false;
        input.focus();
      }
    });
  });

  root.addEventListener("click", async function (event) {
    const button = event.target.closest("[data-remove-type]");
    if (!button) return;
    button.disabled = true;
    try {
      await postPreference(
        button.dataset.removeType,
        button.dataset.value,
        false
      );
      const type = button.dataset.removeType;
      button.closest("[data-selected-value]").remove();
      refreshEmptyState(type);
      updateStrength();
    } catch (error) {
      button.disabled = false;
      showStatus(labels.error, true);
    }
  });

  setStep(0, false);
  updateStrength();
})();
