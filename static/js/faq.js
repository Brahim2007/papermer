(function () {
  "use strict";

  const search = document.querySelector("[data-faq-search]");
  if (!search) return;

  const items = Array.from(document.querySelectorAll("[data-faq-item]"));
  const groups = Array.from(document.querySelectorAll("[data-faq-group]"));
  const clear = document.querySelector("[data-faq-clear]");
  const status = document.querySelector("[data-faq-status]");
  const empty = document.querySelector("[data-faq-empty]");

  const normalized = function (value) {
    return value.toLocaleLowerCase().trim();
  };

  const update = function () {
    const query = normalized(search.value);
    let visibleCount = 0;

    items.forEach(function (item) {
      const matches = !query || normalized(item.textContent).includes(query);
      item.hidden = !matches;
      if (matches) visibleCount += 1;
    });

    groups.forEach(function (group) {
      group.hidden = !group.querySelector("[data-faq-item]:not([hidden])");
    });

    if (clear) clear.hidden = !query;
    if (empty) empty.hidden = visibleCount !== 0;
    if (status) {
      status.textContent = query
        ? visibleCount
          ? visibleCount + " " + status.dataset.resultsLabel
          : status.dataset.emptyLabel
        : status.dataset.allLabel;
    }
  };

  if (status) status.dataset.allLabel = status.textContent.trim();
  search.addEventListener("input", update);
  if (clear) {
    clear.addEventListener("click", function () {
      search.value = "";
      update();
      search.focus();
    });
  }
})();
