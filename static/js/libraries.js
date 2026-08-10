(() => {
  const openDialog = (dialog) => {
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  };

  document.querySelectorAll("[data-dialog-open]").forEach((button) => {
    button.addEventListener("click", () => {
      const dialog = document.getElementById(button.dataset.dialogOpen);
      if (dialog) openDialog(dialog);
    });
  });

  document.querySelectorAll("[data-dialog-close]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog")?.close());
  });

  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  const submitJsonForm = async (form) => {
    const response = await fetch(form.dataset.endpoint, {
      method: "POST",
      body: new FormData(form),
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    if (!response.ok) throw new Error("request failed");
    return response.json();
  };

  const createForm = document.getElementById("create-library-form");
  createForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = createForm.querySelector("button[type='submit']");
    const status = createForm.querySelector(".form-status");
    button.disabled = true;
    status.textContent = "";
    try {
      await submitJsonForm(createForm);
      window.location.reload();
    } catch {
      status.textContent = document.documentElement.lang.startsWith("ar")
        ? "تعذر إنشاء المكتبة."
        : "The library could not be created.";
      button.disabled = false;
    }
  });

  const deleteDialog = document.getElementById("delete-library-dialog");
  const deleteForm = document.getElementById("delete-library-form");
  document.querySelectorAll("[data-delete-library]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteForm.elements.lib_id.value = button.dataset.deleteLibrary;
      deleteDialog.querySelector("[data-delete-message]").textContent =
        document.documentElement.lang.startsWith("ar")
          ? `سيتم حذف مكتبة «${button.dataset.libraryName}» نهائيًا.`
          : `“${button.dataset.libraryName}” will be permanently deleted.`;
      openDialog(deleteDialog);
    });
  });

  deleteForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = deleteForm.querySelector("button[type='submit']");
    const status = deleteForm.querySelector(".form-status");
    button.disabled = true;
    status.textContent = "";
    try {
      await submitJsonForm(deleteForm);
      document.querySelector(`[data-library-card="${CSS.escape(deleteForm.elements.lib_id.value)}"]`)?.remove();
      deleteDialog.close();
      if (!document.querySelector("[data-library-card]")) window.location.reload();
    } catch {
      status.textContent = document.documentElement.lang.startsWith("ar")
        ? "تعذر حذف المكتبة."
        : "The library could not be deleted.";
      button.disabled = false;
    }
  });
})();
