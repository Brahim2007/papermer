(() => {
  const arabic = document.documentElement.lang.startsWith("ar");

  const authorsToggle = document.querySelector("[data-authors-toggle]");
  const extraAuthors = document.querySelector("[data-authors-extra]");
  if (authorsToggle && extraAuthors) {
    authorsToggle.addEventListener("click", () => {
      const expanded = authorsToggle.getAttribute("aria-expanded") === "true";
      authorsToggle.setAttribute("aria-expanded", String(!expanded));
      extraAuthors.hidden = expanded;
      authorsToggle.textContent = expanded
        ? authorsToggle.dataset.showLabel
        : authorsToggle.dataset.hideLabel;
    });
  }

  const copyButton = document.querySelector("[data-copy-value]");
  const copyStatus = document.querySelector("[data-copy-status]");
  if (copyButton && copyStatus) {
    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(copyButton.dataset.copyValue);
        copyStatus.textContent = arabic ? "تم نسخ DOI." : "DOI copied.";
      } catch {
        copyStatus.textContent = arabic
          ? "تعذر النسخ. حدد DOI من تفاصيل النشر."
          : "Copy failed. Select the DOI from publication details.";
      }
    });
  }

  const form = document.querySelector(".save-paper-form");
  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    const status = form.querySelector(".form-status");
    const data = new FormData();
    data.set("article_id", form.dataset.articleId);
    data.set("library_id", form.elements.library_id.value);
    data.set("csrfmiddlewaretoken", form.elements.csrfmiddlewaretoken.value);
    const requestId = new URLSearchParams(window.location.search).get("rid");
    if (requestId) data.set("request_id", requestId);
    button.disabled = true;
    status.textContent = "";
    try {
      const response = await fetch(form.dataset.endpoint, {
        method: "POST",
        body: data,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) throw new Error("save failed");
      status.textContent = arabic
        ? "تم حفظ الورقة في المكتبة."
        : "Paper saved to your library.";
    } catch {
      status.textContent = arabic
        ? "تعذر حفظ الورقة. حاول مرة أخرى."
        : "The paper could not be saved. Please try again.";
    } finally {
      button.disabled = false;
    }
  });
})();
