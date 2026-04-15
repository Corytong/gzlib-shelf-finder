const EXAMPLES = {
  novels: "活着\n百年孤独\n小王子",
  mixed: "算法导论\n深入理解计算机系统\nJavaScript高级程序设计",
  tech: "算法导论\n操作系统概念\n计算机网络"
};

const RECOMMENDATION_BATCH_SIZE = 16;

const bookEntryShell = document.querySelector("#book-entry-shell");
const bookChipList = document.querySelector("#book-chip-list");
const bookEntry = document.querySelector("#book-entry");
const authorInput = document.querySelector("#author-input");
const fuzzyToggle = document.querySelector("#fuzzy-toggle");
const librarySelect = document.querySelector("#library-select");
const searchButton = document.querySelector("#search-button");
const resultsList = document.querySelector("#results-list");
const summaryText = document.querySelector("#summary-text");
const foundCount = document.querySelector("#found-count");
const holdingCount = document.querySelector("#holding-count");
const loanableCount = document.querySelector("#loanable-count");
const sourceNote = document.querySelector("#source-note");
const recommendationList = document.querySelector("#recommendation-list");
const refreshRecommendationsButton = document.querySelector("#refresh-recommendations");

let bookTitles = [];
let recommendations = [];
let recommendationCursor = 0;

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.getAttribute("data-example");
    setTitles(parseQueries(EXAMPLES[key] || ""));
    bookEntry.focus();
  });
});

bookEntry.addEventListener("keydown", (event) => {
  if (["Enter", ",", "，", "、", ";", "；", "Tab"].includes(event.key)) {
    event.preventDefault();
    commitDraftTitle();
    return;
  }

  if (event.key === "Backspace" && !bookEntry.value && bookTitles.length) {
    bookTitles = bookTitles.slice(0, -1);
    renderTitleChips();
  }
});

bookEntry.addEventListener("blur", () => {
  commitDraftTitle();
});

bookEntry.addEventListener("paste", (event) => {
  const text = event.clipboardData?.getData("text") || "";
  if (!/[\n,，;；、]+/g.test(text)) {
    return;
  }

  event.preventDefault();
  addTitles(parseQueries(text));
});

bookChipList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove-index]");
  if (!button) {
    return;
  }

  const index = Number(button.getAttribute("data-remove-index"));
  if (Number.isNaN(index)) {
    return;
  }

  bookTitles = bookTitles.filter((_, itemIndex) => itemIndex !== index);
  renderTitleChips();
  bookEntry.focus();
});

bookEntryShell.addEventListener("click", () => {
  bookEntry.focus();
});

authorInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") {
    return;
  }

  event.preventDefault();
  triggerLookup();
});

recommendationList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-recommend-index]");
  if (!button) {
    return;
  }

  const index = Number(button.getAttribute("data-recommend-index"));
  const recommendation = recommendations[index];
  if (!recommendation) {
    return;
  }

  setTitles([recommendation.title]);
  authorInput.value = "";
  triggerLookup();
});

refreshRecommendationsButton.addEventListener("click", () => {
  rotateRecommendations();
});

searchButton.addEventListener("click", () => {
  triggerLookup();
});

boot().catch((error) => {
  renderError(error.message || "初始化失败。");
});

async function boot() {
  await loadLibraries();
  loadRecommendations().catch(() => {
    renderRecommendationFallback("暂时无法载入推荐图书。");
  });
  renderEmpty("等待输入书名后开始查询。");
}

async function loadLibraries() {
  const response = await fetch("/api/libraries");
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error || "无法加载广州图书馆馆别列表。");
  }

  librarySelect.innerHTML = payload.libraries
    .map((library) => {
      const label = `${library.simpleName} (${library.libcode})`;
      return `<option value="${escapeHtml(library.libcode)}">${escapeHtml(label)}</option>`;
    })
    .join("");

  librarySelect.value = "GT";
}

async function loadRecommendations() {
  renderRecommendationFallback("正在载入推荐图书。");

  const response = await fetch("/api/recommendations");
  const payload = await response.json();

  if (!response.ok) {
    throw new Error(payload.error || "推荐图书加载失败。");
  }

  recommendations = Array.isArray(payload.items) ? payload.items : [];
  recommendationCursor = 0;
  renderRecommendations();
}

function triggerLookup() {
  runLookup().catch((error) => {
    renderError(error.message || "查询失败，请稍后重试。");
  });
}

async function runLookup() {
  commitDraftTitle();
  const titles = getAllTitles();
  const author = normalizeInputTitle(authorInput.value);
  if (!titles.length && !author) {
    renderEmpty("请输入书名或作者后开始查询。");
    return;
  }

  setLoadingState(true);

  const response = await fetch("/api/plan-route", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      titles,
      libcode: librarySelect.value,
      author,
      fuzzy: fuzzyToggle.checked
    })
  });

  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "广州图书馆数据查询失败。");
  }

  renderSummary(payload);
  renderResults(payload.items, payload.missing, payload.selectedLibrary);
  renderSource(payload.meta, payload.selectedLibrary);
  setLoadingState(false);
}

function parseQueries(rawText) {
  return rawText
    .split(/[\n,，;；、]+/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeInputTitle(title) {
  return String(title).replace(/\s+/g, " ").trim();
}

function addTitles(titles) {
  const nextTitles = [...bookTitles];

  titles
    .map(normalizeInputTitle)
    .filter(Boolean)
    .forEach((title) => {
      if (!nextTitles.includes(title)) {
        nextTitles.push(title);
      }
    });

  bookTitles = nextTitles;
  bookEntry.value = "";
  renderTitleChips();
}

function setTitles(titles) {
  bookTitles = [];
  addTitles(titles);
}

function commitDraftTitle() {
  addTitles(parseQueries(bookEntry.value));
}

function getAllTitles() {
  const draftTitles = parseQueries(bookEntry.value);
  if (!draftTitles.length) {
    return [...bookTitles];
  }

  return [...bookTitles, ...draftTitles]
    .map(normalizeInputTitle)
    .filter((title, index, list) => title && list.indexOf(title) === index);
}

function renderTitleChips() {
  bookChipList.innerHTML = bookTitles
    .map((title, index) => {
      return `
        <span class="book-chip">
          <span>${escapeHtml(title)}</span>
          <button type="button" data-remove-index="${index}" aria-label="删除 ${escapeHtml(title)}">×</button>
        </span>
      `;
    })
    .join("");
}

function setLoadingState(isLoading) {
  searchButton.disabled = isLoading;
  refreshRecommendationsButton.disabled = isLoading;
  librarySelect.disabled = isLoading;
  authorInput.disabled = isLoading;
  fuzzyToggle.disabled = isLoading;
  bookEntry.disabled = isLoading;
  searchButton.textContent = isLoading ? "正在查询..." : "查询馆藏位置";
}

function renderSummary(payload) {
  foundCount.textContent = String(payload.items.length);
  holdingCount.textContent = String(payload.totalHoldingCount);
  loanableCount.textContent = String(payload.totalLoanableCount);

  const parts = [
    `当前馆别：${payload.selectedLibrary.simpleName}。`,
    payload.queryMode === "author-only"
      ? `当前按作者查询，匹配到 ${payload.items.length} 本。`
      : `共输入 ${payload.queryCount} 本书，匹配到 ${payload.items.length} 本。`,
    `累计可借复本 ${payload.totalLoanableCount} 册。`
  ];

  if (payload.queryOptions?.author) {
    parts.push(`作者筛选：${payload.queryOptions.author}。`);
  }

  parts.push(payload.queryOptions?.fuzzy ? "已启用模糊查询。" : "当前为精确查询。");

  if (payload.missing.length) {
    parts.push(`未匹配：${payload.missing.join("、")}。`);
  }

  summaryText.innerHTML = `
    ${escapeHtml(parts.join(""))}
    <span class="status-chip ${payload.missing.length ? "warning" : "success"}">
      ${payload.missing.length ? "部分匹配" : "全部匹配"}
    </span>
  `;
}

function renderResults(items, missing, selectedLibrary) {
  if (!items.length && !missing.length) {
    resultsList.innerHTML = '<p class="empty-state">暂无查询结果。</p>';
    return;
  }

  const cards = items.map((item, index) => {
    const addressText = item.holdings.map((holding) => holding.addressSummary || holding.addressLabel).join("、");
    const authorLine = item.author
      ? `<p class="result-meta"><span class="meta-label">作者：</span>${escapeHtml(item.author)}</p>`
      : "";

    return `
      <article class="result-card">
        <div class="result-row">
          <div class="result-index">${index + 1}</div>
          <div class="result-body">
            <h3 class="result-title">${escapeHtml(item.title)}</h3>
            ${authorLine}
            <p class="result-meta"><span class="meta-label">可借总量：</span>${escapeHtml(`${item.totalLoanableCount} 册`)}</p>
            <p class="result-meta"><span class="meta-label">地址：</span><span class="address-inline">${escapeHtml(addressText)}</span></p>
            <p class="result-meta"><span class="meta-label">馆藏地点：</span>${escapeHtml(selectedLibrary.simpleName)}</p>
          </div>
        </div>
        <div class="result-tags">
          <span class="tag">位置数：${item.holdings.length}</span>
          <a class="tag link-tag" href="${escapeHtml(item.opacUrl)}" target="_blank" rel="noreferrer">打开官方详情</a>
        </div>
      </article>
    `;
  });

  const missingCard = missing.length
    ? `
      <article class="result-card">
        <h3 class="result-title">未匹配书名</h3>
        <div class="result-tags">
          ${missing.map((title) => `<span class="tag">${escapeHtml(title)}</span>`).join("")}
        </div>
      </article>
    `
    : "";

  resultsList.innerHTML = `${cards.join("")}${missingCard}`;
}

function renderSource(meta, library) {
  sourceNote.innerHTML = `
    数据来源：<a href="${escapeHtml(meta.catalogBaseUrl)}" target="_blank" rel="noreferrer">广州图书馆联合目录 OPAC</a>
    <span> | 馆别：${escapeHtml(library.simpleName)}</span>
    <span> | 查询时间：${escapeHtml(meta.generatedAt)}</span>
  `;
}

function renderRecommendations() {
  if (!recommendations.length) {
    renderRecommendationFallback("暂无推荐图书。");
    return;
  }

  const batch = getRecommendationBatch();
  recommendationList.innerHTML = batch
    .map((item) => {
      return `
        <button class="recommend-card" type="button" data-recommend-index="${item.index}">
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(item.author || "推荐图书")}</span>
        </button>
      `;
    })
    .join("");
}

function getRecommendationBatch() {
  if (!recommendations.length) {
    return [];
  }

  const items = [];
  for (let offset = 0; offset < Math.min(RECOMMENDATION_BATCH_SIZE, recommendations.length); offset += 1) {
    const index = (recommendationCursor + offset) % recommendations.length;
    items.push({
      ...recommendations[index],
      index
    });
  }

  return items;
}

function rotateRecommendations() {
  if (!recommendations.length) {
    return;
  }

  recommendationCursor = (recommendationCursor + RECOMMENDATION_BATCH_SIZE) % recommendations.length;
  renderRecommendations();
}

function renderRecommendationFallback(message) {
  recommendationList.innerHTML = `<p class="empty-state">${escapeHtml(message)}</p>`;
}

function renderError(message) {
  setLoadingState(false);
  foundCount.textContent = "0";
  holdingCount.textContent = "0";
  loanableCount.textContent = "0";
  summaryText.innerHTML = `${escapeHtml(message)} <span class="status-chip warning">查询失败</span>`;
  resultsList.innerHTML = '<p class="empty-state">暂时无法获取馆藏位置，请稍后重试。</p>';
  sourceNote.textContent = "当前未获取到广州图书馆实时数据。";
}

function renderEmpty(message) {
  foundCount.textContent = "0";
  holdingCount.textContent = "0";
  loanableCount.textContent = "0";
  summaryText.textContent = message;
  resultsList.innerHTML = '<p class="empty-state">还没有查询结果。</p>';
  sourceNote.textContent = "等待查询广州图书馆联合目录。";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
