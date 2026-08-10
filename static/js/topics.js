(() => {
  const root = document.querySelector("[data-topic-preferences]");
  if (!root) return;
  const selectedList = root.querySelector("[data-selected-list]");
  const status = root.querySelector("[data-topic-status]");
  const csrf = root.querySelector("[name='csrfmiddlewaretoken']").value;
  const isArabic = document.documentElement.lang.startsWith("ar");
  let pending = false;

  const findChoice = (topic) =>
    [...root.querySelectorAll("[data-topic]")].find((button) => button.dataset.topic === topic);

  const renderSelected = (topic, add) => {
    root.querySelector("[data-no-topics]")?.remove();
    const existing = [...selectedList.querySelectorAll("[data-selected-topic]")].find(
      (button) => button.dataset.selectedTopic === topic,
    );
    if (add && !existing) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "selected-topic";
      button.dataset.selectedTopic = topic;
      const label = document.createElement("span");
      label.textContent = topic;
      const icon = document.createElement("span");
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = "×";
      const assistive = document.createElement("span");
      assistive.className = "sr-only";
      assistive.textContent = isArabic ? "إزالة الموضوع" : "Remove topic";
      button.append(label, icon, assistive);
      selectedList.append(button);
    }
    if (!add) existing?.remove();
    if (!selectedList.querySelector("[data-selected-topic]")) {
      const empty = document.createElement("div");
      empty.className = "empty-inline";
      empty.dataset.noTopics = "";
      empty.textContent = isArabic ? "لم تختر موضوعات بعد." : "No topics selected yet.";
      selectedList.append(empty);
    }
  };

  const updateTopic = async (topic, add) => {
    if (pending) return;
    pending = true;
    status.textContent = isArabic ? "جارٍ الحفظ…" : "Saving…";
    const data = new URLSearchParams({ tag: topic, add: add ? "1" : "0", csrfmiddlewaretoken: csrf });
    try {
      const response = await fetch(root.dataset.endpoint, {
        method: "POST",
        body: data,
        headers: { "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) throw new Error("request failed");
      const choice = findChoice(topic);
      if (choice) {
        choice.classList.toggle("is-selected", add);
        choice.setAttribute("aria-pressed", String(add));
        choice.querySelector("[data-choice-icon]").textContent = add ? "✓" : "+";
      }
      renderSelected(topic, add);
      status.textContent = isArabic ? "تم تحديث ملفك البحثي." : "Your research profile was updated.";
    } catch {
      status.textContent = isArabic ? "تعذر حفظ التغيير." : "The change could not be saved.";
    } finally {
      pending = false;
    }
  };

  root.addEventListener("click", (event) => {
    const choice = event.target.closest("[data-topic]");
    if (choice) updateTopic(choice.dataset.topic, choice.getAttribute("aria-pressed") !== "true");
    const selected = event.target.closest("[data-selected-topic]");
    if (selected) updateTopic(selected.dataset.selectedTopic, false);
  });
})();
