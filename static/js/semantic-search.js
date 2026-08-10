(() => {
  const root = document.querySelector("[data-live-search]");
  if (!root) return;
  const form = root.querySelector("[data-search-form]");
  const input = form.querySelector("input[type='search']");
  const results = root.querySelector("[data-live-results]");
  const serverResults = root.querySelector("[data-server-results]");
  const serverSummary = root.querySelector("[data-server-summary]");
  const serverLayout = root.querySelector("[data-server-layout]");
  const searchStart = root.querySelector("[data-search-start]");
  const status = root.querySelector("[data-live-status]");
  const method = root.querySelector("[data-live-method]");
  const serverMethod = root.querySelector("[data-server-method]");
  const expansionToggle = root.querySelector("[data-expansion-toggle]");
  const expansionDetails = root.querySelector("[data-expansion-details]");
  const filterControls = Array.from(root.querySelectorAll("[data-search-filter]"));
  const filterCount = root.querySelector("[data-filter-count]");
  const librarySelect = root.querySelector("[data-library-select]");
  const globalSaveStatus = root.querySelector("[data-save-global-status]");
  const isArabic = document.documentElement.lang.startsWith("ar");
  let timer;
  let controller;

  const csrfToken = () => root.dataset.csrfToken || "";

  const text = {
    searching: isArabic ? "جارٍ تشغيل الاسترجاع الهجين…" : "Running hybrid retrieval…",
    unavailable: isArabic ? "تعذر البحث الحي؛ بقيت نتائج البحث الاحتياطية ظاهرة." : "Live retrieval is unavailable; fallback results remain visible.",
    noResults: isArabic ? "لم يعثر الاسترجاع الحي على نتائج بهذه القيود." : "Live retrieval found no results with these filters.",
    semantic: "SPECTER2 + BM25 · RRF",
    sparse: isArabic ? "BM25 + TF-IDF · وضع احتياطي" : "BM25 + TF-IDF · fallback",
    expanded: isArabic ? "توسيع LLM تجريبي · RRF" : "Experimental LLM expansion · RRF",
    why: isArabic ? "لماذا حصلت على هذه الرتبة؟" : "Why it ranked",
    matchedTerms: isArabic ? "مصطلحات متطابقة" : "Matched terms",
    noTerms: isArabic ? "تقارب الرتب يدعم النتيجة دون تطابق مصطلحات مباشر." : "Rank evidence supports this result without a direct term match.",
    citations: isArabic ? "استشهاد" : "citations",
    inspect: isArabic ? "فحص الورقة" : "Inspect paper",
    save: isArabic ? "حفظ" : "Save",
    saved: isArabic ? "تم الحفظ" : "Saved",
    saveFailed: isArabic ? "تعذر الحفظ" : "Save failed",
    relevant: isArabic ? "ذات صلة" : "Relevant",
    notRelevant: isArabic ? "غير ذات صلة" : "Not relevant",
    feedbackSaved: isArabic ? "تم تسجيل حكمك." : "Your judgment was recorded.",
    expansionQuery: isArabic ? "الاستعلام الموسع" : "Expanded query",
    expansionFallback: isArabic ? "لم يُستخدم التوسيع؛ بقي ترتيب الأساس فعالًا." : "Expansion was not used; baseline ranking remained active.",
    filters: isArabic ? "مرشحات" : "filters",
    active: isArabic ? "نشطة" : "active",
    noComponentRanks: isArabic ? "لا تتوفر رتب مكونات لهذا المسار الاحتياطي." : "Component ranks are unavailable for this fallback path.",
  };

  const filterParams = () => {
    const params = new URLSearchParams();
    filterControls.forEach((control) => {
      if (control.type === "checkbox") {
        if (control.checked) params.set(control.name, control.value || "1");
      } else if (control.value.trim()) {
        params.set(control.name, control.value.trim());
      }
    });
    return params;
  };

  const updateFilterCount = () => {
    const count = Array.from(filterParams()).length;
    if (filterCount) filterCount.textContent = count ? `${count} ${text.active}` : "";
    return count;
  };

  const syncUrl = () => {
    const params = filterParams();
    const query = input.value.trim();
    if (query) params.set("query", query);
    const suffix = params.toString();
    window.history.replaceState({}, "", suffix ? `${form.action}?${suffix}` : form.action);
  };

  const sendInteraction = (payload, keepalive = false) => {
    if (!payload.request_id) return Promise.resolve(null);
    return fetch(root.dataset.interactionEndpoint, {
      method: "POST",
      credentials: "same-origin",
      keepalive,
      headers: {"Content-Type": "application/json", "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest"},
      body: JSON.stringify(payload),
    });
  };

  const articleUrl = (id, requestId, rank) => {
    const url = new URL(root.dataset.articleUrl.replace("__ARTICLE_ID__", encodeURIComponent(id)), window.location.origin);
    if (requestId) {
      url.searchParams.set("rid", requestId);
      url.searchParams.set("rank", rank);
    }
    return `${url.pathname}${url.search}`;
  };

  const attachClickTracking = (link, paper, requestId) => {
    link.addEventListener("click", () => {
      sendInteraction({event_type: "click", request_id: requestId, document_id: paper.id}, true).catch(() => {});
    });
  };

  const savePaper = async (button, articleId, requestId = "") => {
    if (!librarySelect?.value || !root.dataset.libraryEndpoint) return;
    const localStatus = button.closest(".result-card__actions")?.querySelector(".quick-save-status");
    button.disabled = true;
    const data = new FormData();
    data.set("article_id", articleId);
    data.set("library_id", librarySelect.value);
    data.set("csrfmiddlewaretoken", csrfToken());
    data.set("source", "search_results");
    if (requestId) data.set("request_id", requestId);
    try {
      const response = await fetch(root.dataset.libraryEndpoint, {method: "POST", body: data, headers: {"X-Requested-With": "XMLHttpRequest"}});
      if (!response.ok) throw new Error("save failed");
      button.textContent = text.saved;
      if (localStatus) localStatus.textContent = text.saved;
      if (globalSaveStatus) globalSaveStatus.textContent = text.saved;
    } catch {
      button.disabled = false;
      if (localStatus) localStatus.textContent = text.saveFailed;
      if (globalSaveStatus) globalSaveStatus.textContent = text.saveFailed;
    }
  };

  root.querySelectorAll("[data-quick-save]").forEach((button) => {
    button.addEventListener("click", () => savePaper(button, button.dataset.articleId));
  });

  const createFeedback = (paper, requestId) => {
    if (root.dataset.authenticated !== "true" || !requestId) return null;
    const feedback = document.createElement("div");
    feedback.className = "relevance-feedback";
    feedback.setAttribute("aria-label", isArabic ? "تقييم صلة الورقة" : "Rate paper relevance");
    const feedbackStatus = document.createElement("span");
    feedbackStatus.className = "relevance-feedback__status";
    feedbackStatus.setAttribute("aria-live", "polite");
    [[1, text.relevant], [-1, text.notRelevant]].forEach(([value, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "relevance-feedback__button";
      button.textContent = label;
      button.addEventListener("click", async () => {
        const response = await sendInteraction({event_type: "relevance", request_id: requestId, document_id: paper.id, relevance: value});
        if (!response?.ok) return;
        feedback.querySelectorAll("button").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
        feedbackStatus.textContent = text.feedbackSaved;
      });
      feedback.append(button);
    });
    feedback.append(feedbackStatus);
    return feedback;
  };

  const createExplanation = (paper) => {
    const evidence = document.createElement("div");
    evidence.className = "result-evidence";
    const heading = document.createElement("strong");
    heading.textContent = text.why;
    const ranks = document.createElement("div");
    ranks.className = "evidence-chips";
    const componentRanks = Object.entries(paper.explanation?.component_ranks || {});
    componentRanks.forEach(([component, rank]) => {
      const chip = document.createElement("span");
      chip.textContent = `${component.toUpperCase()} #${rank}`;
      ranks.append(chip);
    });
    const reason = document.createElement("span");
    reason.className = "result-evidence__reason";
    reason.textContent = paper.explanation?.matched_terms?.length
      ? `${text.matchedTerms}: ${paper.explanation.matched_terms.join(", ")}`
      : (componentRanks.length ? text.noTerms : text.noComponentRanks);
    evidence.append(heading, ranks, reason);
    return evidence;
  };

  const createCard = (paper, requestId) => {
    const card = document.createElement("article");
    card.className = "result-card result-card--live";
    const content = document.createElement("div");
    content.className = "result-card__content";
    const badges = document.createElement("div");
    badges.className = "result-card__badges";
    const rank = document.createElement("span");
    rank.textContent = `#${paper.rank}`;
    badges.append(rank);
    if (paper.paper_type) {
      const type = document.createElement("span");
      type.textContent = paper.paper_type;
      badges.append(type);
    }
    if (paper.is_open_access) {
      const oa = document.createElement("span");
      oa.className = "result-card__oa";
      oa.textContent = isArabic ? "● وصول مفتوح" : "● Open access";
      badges.append(oa);
    }
    if (paper.is_retracted) {
      const retracted = document.createElement("span");
      retracted.className = "result-card__retracted";
      retracted.textContent = isArabic ? "مسحوبة" : "Retracted";
      badges.append(retracted);
    }
    const heading = document.createElement("h2");
    const link = document.createElement("a");
    link.href = articleUrl(paper.id, requestId, paper.rank);
    link.textContent = paper.title;
    attachClickTracking(link, paper, requestId);
    heading.append(link);
    const authors = document.createElement("p");
    authors.className = "result-card__authors";
    authors.textContent = (paper.authors || []).join(", ");
    const meta = document.createElement("div");
    meta.className = "result-card__meta";
    [paper.year, paper.venue, `${paper.citation_count || 0} ${text.citations}`].filter(Boolean).forEach((value) => {
      const item = document.createElement("span");
      item.textContent = value;
      meta.append(item);
    });
    const abstract = document.createElement("p");
    abstract.className = "result-card__abstract";
    abstract.textContent = paper.abstract || "";
    content.append(badges, heading, authors, meta, abstract, createExplanation(paper));
    const feedback = createFeedback(paper, requestId);
    if (feedback) content.append(feedback);
    const actions = document.createElement("div");
    actions.className = "result-card__actions";
    const view = document.createElement("a");
    view.className = "button button--secondary button--small";
    view.href = articleUrl(paper.id, requestId, paper.rank);
    view.textContent = text.inspect;
    attachClickTracking(view, paper, requestId);
    actions.append(view);
    if (root.dataset.authenticated === "true" && librarySelect) {
      const save = document.createElement("button");
      save.type = "button";
      save.className = "button button--ghost button--small";
      save.textContent = text.save;
      save.addEventListener("click", () => savePaper(save, paper.id, requestId));
      actions.append(save);
    }
    if (paper.doi) {
      const doi = document.createElement("a");
      doi.className = "result-card__doi";
      doi.href = `https://doi.org/${paper.doi}`;
      doi.target = "_blank";
      doi.rel = "noopener noreferrer";
      doi.textContent = "DOI ↗";
      actions.append(doi);
    }
    const saveStatus = document.createElement("span");
    saveStatus.className = "quick-save-status";
    saveStatus.setAttribute("role", "status");
    saveStatus.setAttribute("aria-live", "polite");
    actions.append(saveStatus);
    card.append(content, actions);
    return card;
  };

  const run = async () => {
    const query = input.value.trim();
    if (query.length < 3) return;
    controller?.abort();
    controller = new AbortController();
    status.textContent = text.searching;
    method.hidden = true;
    root.setAttribute("aria-busy", "true");
    try {
      const url = new URL(root.dataset.endpoint, window.location.origin);
      url.searchParams.set("q", query);
      url.searchParams.set("limit", "10");
      url.searchParams.set("expansion", expansionToggle?.checked ? "on" : "off");
      filterParams().forEach((value, key) => url.searchParams.set(key, value));
      const response = await fetch(url, {signal: controller.signal, headers: {"X-Requested-With": "XMLHttpRequest"}});
      if (!response.ok) throw new Error("search failed");
      const payload = await response.json();
      if (input.value.trim() !== query) return;
      const fragment = document.createDocumentFragment();
      payload.results.forEach((paper) => fragment.append(createCard(paper, payload.request_id)));
      results.replaceChildren(fragment);
      results.hidden = false;
      if (serverResults) serverResults.hidden = true;
      if (serverSummary) serverSummary.hidden = true;
      if (serverLayout) serverLayout.hidden = true;
      if (searchStart) searchStart.hidden = true;
      serverMethod?.remove();
      method.hidden = false;
      const methodLabel = payload.experiment?.arm === "llm_expansion" ? text.expanded : (payload.semantic_enabled ? text.semantic : text.sparse);
      const activeFilterCount = Object.keys(payload.filters || {}).length;
      method.textContent = activeFilterCount ? `${methodLabel} · ${activeFilterCount} ${text.filters}` : methodLabel;
      if (expansionDetails) {
        const experiment = payload.experiment || {};
        const lines = [`${experiment.status || "not_selected"} · ${experiment.model || "—"} · ${Math.round(experiment.latency_ms || 0)} ms`];
        if (experiment.expanded_query) lines.push(`${text.expansionQuery}: ${experiment.expanded_query}`);
        else if (expansionToggle?.checked) lines.push(text.expansionFallback);
        expansionDetails.textContent = lines.join("\n");
        expansionDetails.hidden = !expansionToggle?.checked;
      }
      status.textContent = payload.results.length ? `${payload.results.length} ${isArabic ? "نتيجة مرتبة" : "ranked results"}` : text.noResults;
      sendInteraction({event_type: "impression", request_id: payload.request_id, document_ids: payload.results.map((paper) => paper.id)}).catch(() => {});
    } catch (error) {
      if (error.name !== "AbortError") status.textContent = text.unavailable;
    } finally {
      root.removeAttribute("aria-busy");
    }
  };

  input.addEventListener("input", () => {
    clearTimeout(timer);
    if (input.value.trim().length < 3) {
      status.textContent = "";
      method.hidden = true;
      return;
    }
    timer = setTimeout(run, 420);
  });
  form.addEventListener("submit", (event) => {
    if (input.value.trim().length >= 3) {
      event.preventDefault();
      clearTimeout(timer);
      syncUrl();
      run();
    }
  });
  filterControls.forEach((control) => {
    control.addEventListener("change", () => {
      updateFilterCount();
      syncUrl();
      if (input.value.trim().length >= 3) run();
    });
  });
  expansionToggle?.addEventListener("change", () => {
    if (input.value.trim().length >= 3) run();
  });
  updateFilterCount();
  if (input.value.trim().length >= 3) run();
})();
