(() => {
  const boxes = document.querySelectorAll('[data-search-index]');
  if (!boxes.length) return;

  const escapeHtml = (value) => String(value || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');

  const normalize = (value) => String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();

  const snippet = (text, terms) => {
    const source = String(text || '');
    const lower = source.toLowerCase();
    let pos = -1;
    for (const term of terms) {
      pos = lower.indexOf(term);
      if (pos >= 0) break;
    }
    if (pos < 0) pos = 0;
    const start = Math.max(0, pos - 48);
    const end = Math.min(source.length, pos + 150);
    let out = source.slice(start, end).trim();
    if (start > 0) out = '…' + out;
    if (end < source.length) out += '…';
    return out;
  };

  const score = (item, terms) => {
    const title = normalize(item.title);
    const path = normalize(item.path);
    const body = normalize(`${item.description || ''} ${item.text || ''}`);
    let total = 0;
    for (const term of terms) {
      if (!term) continue;
      if (title.includes(term)) total += 10;
      if (path.includes(term)) total += 6;
      if (body.includes(term)) total += 2;
      if (!title.includes(term) && !path.includes(term) && !body.includes(term)) return 0;
    }
    return total;
  };

  const filterItems = (items, activeFilter) => {
    const visible = items.filter((item) => !item.search_excluded);
    if (!activeFilter || activeFilter === 'all') return visible;
    return visible.filter((item) => item.filter === activeFilter);
  };

  const render = (resultsEl, inputEl, items, indexUrl, activeFilter) => {
    const scopedItems = filterItems(items, activeFilter);
    const query = normalize(inputEl.value);
    if (!query) {
      const label = activeFilter === 'all' ? '전체 문서' : activeFilter === 'wiki' ? '위키' : activeFilter === 'active' ? '최신 기준 문서' : activeFilter === 'ops' ? '운영 문서' : activeFilter === 'history' ? '설계 이력' : '보관 문서';
      resultsEl.innerHTML = `<p class="search-empty">${escapeHtml(label)}에서 검색어를 입력하면 관련 문서가 여기에 표시됩니다.</p>`;
      return;
    }
    const terms = query.split(' ').filter(Boolean);
    const results = scopedItems
      .map((item) => ({ item, score: score(item, terms) }))
      .filter((row) => row.score > 0)
      .sort((a, b) => b.score - a.score || a.item.title.localeCompare(b.item.title, 'ko'))
      .slice(0, 12);

    if (!results.length) {
      resultsEl.innerHTML = `<p class="search-empty">'${escapeHtml(query)}' 검색 결과가 없습니다.</p>`;
      return;
    }

    resultsEl.innerHTML = '<ol>' + results.map(({ item }) => {
      const href = new URL(item.url, indexUrl).pathname;
      return `<li>
        <a href="${escapeHtml(href)}">
          <strong>${escapeHtml(item.title)}</strong>
          <span class="search-path">${escapeHtml(item.group)} · ${escapeHtml(item.path)}</span>
          <span class="search-snippet">${escapeHtml(snippet(item.text || item.description || '', terms))}</span>
        </a>
      </li>`;
    }).join('') + '</ol>';
  };

  boxes.forEach(async (box) => {
    const input = box.querySelector('#doc-search-input');
    const results = box.querySelector('#doc-search-results');
    const filterButtons = Array.from(box.querySelectorAll('[data-search-filter]'));
    if (!input || !results) return;

    let activeFilter = 'all';
    const indexUrl = new URL(box.dataset.searchIndex, window.location.href);
    results.innerHTML = '<p class="search-empty">검색 인덱스를 불러오는 중...</p>';
    try {
      const response = await fetch(indexUrl);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const items = await response.json();
      render(results, input, items, indexUrl, activeFilter);
      input.addEventListener('input', () => render(results, input, items, indexUrl, activeFilter));
      filterButtons.forEach((button) => {
        button.addEventListener('click', () => {
          activeFilter = button.dataset.searchFilter || 'all';
          filterButtons.forEach((b) => b.classList.toggle('active', b === button));
          render(results, input, items, indexUrl, activeFilter);
        });
      });
    } catch (error) {
      results.innerHTML = `<p class="search-empty error">검색 인덱스를 불러오지 못했습니다: ${escapeHtml(error.message)}</p>`;
    }
  });
})();
