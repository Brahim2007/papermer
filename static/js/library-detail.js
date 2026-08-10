(() => {
  const section = document.querySelector("[data-library-recommendations]");
  if (!section) return;
  const loading = section.querySelector("[data-loading]");
  const results = section.querySelector("[data-results]");
  const empty = section.querySelector("[data-empty]");
  const error = section.querySelector("[data-error]");

  const buildItem = (paper, index) => {
    const item = document.createElement("li");
    item.className = "paper-list__item";
    const rank = document.createElement("div");
    rank.className = "paper-list__rank";
    rank.setAttribute("aria-hidden", "true");
    rank.textContent = String(index + 1).padStart(2, "0");
    const content = document.createElement("div");
    const heading = document.createElement("h3");
    const link = document.createElement("a");
    link.href = `/article/${encodeURIComponent(paper.id)}/`;
    link.textContent = paper.title || "";
    heading.append(link);
    const meta = document.createElement("p");
    meta.textContent = [paper.year, paper.source].filter(Boolean).join(" · ");
    const summary = document.createElement("p");
    summary.className = "paper-list__summary";
    summary.textContent = paper.summary || "";
    content.append(heading, meta, summary);
    item.append(rank, content);
    return item;
  };

  fetch(section.dataset.endpoint, { headers: { "X-Requested-With": "XMLHttpRequest" } })
    .then((response) => {
      if (!response.ok) throw new Error("request failed");
      return response.json();
    })
    .then((papers) => {
      loading.hidden = true;
      if (!papers.length) {
        empty.hidden = false;
        return;
      }
      const fragment = document.createDocumentFragment();
      papers.slice(0, 20).forEach((paper, index) => fragment.append(buildItem(paper, index)));
      results.append(fragment);
    })
    .catch(() => {
      loading.hidden = true;
      error.hidden = false;
    });
})();
