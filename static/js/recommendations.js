(() => {
  const root = document.querySelector("[data-recommendations]");
  if (!root) return;
  const results = root.querySelector("[data-results]");
  const loading = root.querySelector("[data-loading]");
  const empty = root.querySelector("[data-empty]");
  const error = root.querySelector("[data-error]");
  const pagination = root.querySelector("[data-pagination]");
  const count = root.querySelector("[data-result-count]");
  const loadMore = root.querySelector("[data-load-more]");
  const pageSize = 15;
  let papers = [];
  let visible = 0;

  const methodLabel = (method) =>
    method === "profile_tfidf_rrf" ? "Profile retrieval · RRF" : "Rank fusion";

  const buildExplanation = (explanation = {}) => {
    const details = document.createElement("details");
    details.className = "result-explanation recommendation-explanation";
    const summary = document.createElement("summary");
    summary.textContent = document.documentElement.lang.startsWith("ar")
      ? "لماذا أوصينا بهذه الورقة؟"
      : "Why was this recommended?";
    const body = document.createElement("div");
    body.className = "result-explanation__body";
    const intro = document.createElement("p");
    intro.textContent =
      explanation.reason_code === "multiple_profile_signals"
        ? (document.documentElement.lang.startsWith("ar")
            ? "ظهرت الورقة عبر أكثر من إشارة في ملفك البحثي."
            : "This paper appeared for multiple signals in your research profile.")
        : (document.documentElement.lang.startsWith("ar")
            ? "ظهرت الورقة عبر إشارة محددة في ملفك البحثي."
            : "This paper appeared for a specific signal in your research profile.");
    const chips = document.createElement("div");
    chips.className = "evidence-chips";
    (explanation.signals || []).forEach((signal) => {
      const chip = document.createElement("span");
      chip.textContent = `${signal.label} · #${signal.rank}`;
      chips.append(chip);
    });
    body.append(intro, chips);
    details.append(summary, body);
    return details;
  };

  const buildItem = (paper, index) => {
    const item = document.createElement("li");
    item.className = "paper-list__item recommendation-item";
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
    meta.className = "recommendation-method";
    meta.textContent = methodLabel(paper.method);
    content.append(heading, meta, buildExplanation(paper.explanation));
    item.append(rank, content);
    return item;
  };

  const renderMore = () => {
    const next = Math.min(visible + pageSize, papers.length);
    const fragment = document.createDocumentFragment();
    for (let index = visible; index < next; index += 1) fragment.append(buildItem(papers[index], index));
    results.append(fragment);
    visible = next;
    pagination.hidden = visible >= papers.length;
  };

  const load = async () => {
    loading.hidden = false;
    empty.hidden = true;
    error.hidden = true;
    pagination.hidden = true;
    results.replaceChildren();
    visible = 0;
    try {
      const response = await fetch(root.dataset.endpoint, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      if (!response.ok) throw new Error("request failed");
      papers = await response.json();
      loading.hidden = true;
      count.textContent = papers.length
        ? `${papers.length} ${document.documentElement.lang.startsWith("ar") ? "ورقة" : "papers"}`
        : "";
      if (!papers.length) {
        empty.hidden = false;
        return;
      }
      renderMore();
    } catch {
      loading.hidden = true;
      error.hidden = false;
    }
  };

  loadMore.addEventListener("click", renderMore);
  root.querySelector("[data-retry]").addEventListener("click", load);
  load();
})();
