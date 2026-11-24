'use strict';

// ---------------------------------------------------------------- helpers
const $ = (s, el = document) => el.querySelector(s);
const app = $('#app');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(r.status + ' ' + path);
  return r.json();
};
const fmtDate = (d) => {
  if (!d) return 'TBA';
  const [y, m, dd] = d.split('-').map(Number);
  return new Date(y, m - 1, dd).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
};
const scoreColor = (s) => (s >= 84 ? 'var(--good)' : s >= 75 ? 'var(--mid)' : 'var(--bad)');
const players = (n) => (n ? 'up to ' + n : n === 0 ? 'no' : '?');
const store = {
  get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } },
};

// Genre glyphs (24x24 stroke paths) and colours
const GENRE = {
  'Action': ['#ff7a45', 'M13 2L4 14h7l-1 8 9-12h-7z'],
  'Adventure': ['#8fd3ff', 'M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15M15 6v15'],
  'Arcade': ['#b18cff', 'M12 3a3 3 0 1 0 0 6a3 3 0 1 0 0-6M12 9v6M4 15h16v5H4z'],
  'Card Game': ['#5fd38a', 'M3 7h11v14H3zM8 3h13v14h-2'],
  'Creation': ['#ffd23f', 'M14 4l6 6-9 9H5v-6zM12 6l6 6'],
  'Fighting': ['#ff5d8a', 'M4 4l12 12M14 18l4-4M20 4L8 16M6 14l4 4M3 21l3-3M21 21l-3-3'],
  'First-Person Shooter': ['#3ee8b5', 'M12 2v5M12 17v5M2 12h5M17 12h5M12 7a5 5 0 1 0 0 10a5 5 0 1 0 0-10'],
  'Horror': ['#c9b6ff', 'M5 21V10a7 7 0 0 1 14 0v11l-2.3-1.6L14.3 21 12 19.4 9.7 21l-2.4-1.6zM9 10h.01M15 10h.01'],
  'Interactive Story': ['#f4a261', 'M2 5h8a2 2 0 0 1 2 2v13a2 2 0 0 0-2-2H2zM22 5h-8a2 2 0 0 0-2 2v13a2 2 0 0 1 2-2h8z'],
  'MMO': ['#38bdf8', 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M2 12h20M12 2c3.5 3 3.5 17 0 20M12 2c-3.5 3-3.5 17 0 20'],
  'Music': ['#e85dff', 'M9 18V5l11-2v13M9 18a3 3 0 1 1-6 0a3 3 0 1 1 6 0M20 16a3 3 0 1 1-6 0a3 3 0 1 1 6 0'],
  'Platformer': ['#5cc8ff', 'M3 20h5v-5h5v-5h5V5h3'],
  'Puzzle': ['#a3e635', 'M4 4h6v2a2 2 0 1 0 4 0V4h6v6h-2a2 2 0 1 0 0 4h2v6H4z'],
  'Racing': ['#ff5d5d', 'M5 21V4h14l-3 5 3 5H5'],
  'Real-Time Strategy': ['#94a3b8', 'M4 21V8h3v3h3V8h4v3h3V8h3v13zM10 21v-5h4v5'],
  'Roguelike': ['#fb7185', 'M4 4h16v16H4zM8.5 8.5h.01M15.5 15.5h.01M12 12h.01'],
  'RPG': ['#818cf8', 'M14.5 3H21v6.5L9 21.5l-6-6zM5 13l6 6M3 21l3-3'],
  'Simulation': ['#4ade80', 'M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2'],
  'Sports': ['#22c55e', 'M7 4h10v5a5 5 0 0 1-10 0zM7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4M12 14v4M8 21h8'],
  'Strategy': ['#e7e5e4', 'M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18'],
  'Survival': ['#f97316', 'M3 20L12 4l9 16zM12 4v16M8 20l4-6 4 6'],
  'Third-Person Shooter': ['#f472b6', 'M12 3a3 3 0 1 0 0 6a3 3 0 1 0 0-6M6 21v-4a6 6 0 0 1 12 0v4M17 9h5M19.5 6.5v5'],
  'Turn-Based Strategy': ['#fbbf24', 'M6 2h12M6 22h12M7 2c0 6 10 6 10 10S7 16 7 22M17 2c0 6-10 6-10 10s10 4 10 10'],
  'Vehicle Combat': ['#84cc16', 'M2 15h20v4H2zM6 15v-4h10v4M16 12.5h6'],
  'Other': ['#a3a9b6', 'M12 2a10 10 0 1 0 0 20a10 10 0 1 0 0-20M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01'],
};
const genreColor = (g) => (GENRE[g] || GENRE.Other)[0];
const glyph = (g, size = 22) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${(GENRE[g] || GENRE.Other)[1]}"/></svg>`;
const ICON = {
  check: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5L20 7"/></svg>',
  plus: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
  up: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"/></svg>',
  down: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M6 13l6 6 6-6"/></svg>',
  back: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg>',
  yt: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ff6b5e" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 7.5a3 3 0 0 1 2.1-2.1C6.5 5 12 5 12 5s5.5 0 7.4.4a3 3 0 0 1 2.1 2.1c.5 1.9.5 4.5.5 4.5s0 2.6-.5 4.5a3 3 0 0 1-2.1 2.1C17.5 19 12 19 12 19s-5.5 0-7.4-.4a3 3 0 0 1-2.1-2.1C2 14.6 2 12 2 12s0-2.6.5-4.5z"/><path d="M10 9l5 3-5 3z"/></svg>',
};

let META = null;
let renderToken = 0;

// ---------------------------------------------------------------- routing
function parseHash() {
  const h = location.hash.replace(/^#/, '') || '/';
  const [path, qs] = h.split('?');
  const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
  return { parts, params: new URLSearchParams(qs || '') };
}
function go(path, params) {
  const qs = params && params.toString();
  location.hash = '#' + path + (qs ? '?' + qs : '');
}

window.addEventListener('hashchange', route);
async function route() {
  const token = ++renderToken;
  const { parts, params } = parseHash();
  if (!META) META = await api('/api/meta').catch(() => ({ genres: [], platforms: [] }));
  if (token !== renderToken) return;
  const qInput = $('#q');
  if (parts[0] !== 'search' && document.activeElement !== qInput) qInput.value = '';
  window.scrollTo(0, 0);
  if (!parts.length) return renderHome();
  if (parts[0] === 'genre') return renderList(token, parts[1], params);
  if (parts[0] === 'search') {
    if (document.activeElement !== qInput) qInput.value = params.get('q') || '';
    return renderList(token, null, params);
  }
  if (parts[0] === 'game') return renderGame(token, +parts[1]);
  if (parts[0] === 'status') return renderStatus(token);
  renderHome();
}

// ---------------------------------------------------------------- home
function renderHome() {
  const g = META.genres;
  if (!g.length) {
    app.innerHTML = `<div class="hero"><h1>No games yet</h1>
      <p>The database is empty. The first import starts automatically and takes a while (OpenCritic, Co-optimus and PEGI are crawled slowly). Watch it on the <a href="#/status">Data</a> page.</p></div>`;
    return;
  }
  const total = g.reduce((a, x) => a + x.count, 0);
  app.innerHTML = `
    <div class="hero"><h1>Pick a genre</h1>
      <p>Co-op games for PC, PS4, PS5, Switch and Switch 2. A game with several genres shows up in each of them.</p></div>
    <div class="tiles">${g.map(tile).join('')}</div>`;
  void total;
}
function tile(x) {
  const c = genreColor(x.name);
  const imgs = x.images.slice(0, 3);
  return `<a class="tile${imgs.length ? '' : ' empty'}" href="#/genre/${encodeURIComponent(x.name)}" style="background:${c}22">
    <div class="collage n${imgs.length >= 3 ? 3 : imgs.length}">${imgs.map((u) => `<img src="${esc(u)}" alt="" loading="lazy" referrerpolicy="no-referrer">`).join('')}</div>
    <div class="tint" style="background:${c}"></div>
    <span class="glyph" style="background:${c}">${glyph(x.name)}</span>
    <div class="label"><span class="name">${esc(x.name)}</span><span class="count" style="background:${c}">${x.count}</span></div>
  </a>`;
}

// ---------------------------------------------------------------- list (genre or search)
const SORTS = [['score', 'Score'], ['name', 'Name'], ['date', 'Release date']];
const DEFAULT_SORT = { genre: { sort: 'score', dir: 'desc' }, search: { sort: 'name', dir: 'asc' } };

function listState(genre, params) {
  const kind = genre ? 'genre' : 'search';
  const saved = store.get('sort.' + kind, DEFAULT_SORT[kind]);
  const csv = (k) => (params.get(k) || '').split(',').filter(Boolean);
  return {
    kind, genre,
    q: params.get('q') || '',
    genres: csv('genres'),
    modes: csv('modes'),
    pegi: +params.get('pegi') || 0,
    unrated: params.get('unrated') === '1',
    plats: csv('plats'),
    yf: +params.get('yf') || 0,
    yt: +params.get('yt') || 0,
    played: params.get('played') || '',
    sort: params.get('sort') || saved.sort,
    dir: params.get('dir') || saved.dir,
  };
}
function stateToParams(s) {
  const p = new URLSearchParams();
  if (s.q) p.set('q', s.q);
  if (s.genres.length) p.set('genres', s.genres.join(','));
  if (s.modes.length) p.set('modes', s.modes.join(','));
  if (s.pegi) p.set('pegi', s.pegi);
  if (s.unrated) p.set('unrated', '1');
  if (s.plats.length) p.set('plats', s.plats.join(','));
  if (s.yf) p.set('yf', s.yf);
  if (s.yt) p.set('yt', s.yt);
  if (s.played) p.set('played', s.played);
  p.set('sort', s.sort);
  p.set('dir', s.dir);
  return p;
}
function apiParams(s, offset) {
  const p = new URLSearchParams();
  if (s.q) p.set('q', s.q);
  const genres = s.genre ? [s.genre, ...s.genres.filter((g) => g !== s.genre)] : s.genres;
  if (genres.length) p.set('genres', genres.join(','));
  s.modes.forEach((m) => p.set(m, 'true'));
  if (s.pegi) { p.set('max_pegi', s.pegi); if (s.unrated) p.set('include_unrated', 'true'); }
  if (s.plats.length) p.set('platforms', s.plats.join(','));
  if (s.yf) p.set('year_from', s.yf);
  if (s.yt) p.set('year_to', s.yt);
  if (s.played === 'hide') p.set('hide_played', 'true');
  if (s.played === 'only') p.set('only_played', 'true');
  p.set('sort', s.sort);
  p.set('dir', s.dir);
  p.set('limit', 60);
  p.set('offset', offset);
  return p;
}
function apply(s) {
  store.set('sort.' + s.kind, { sort: s.sort, dir: s.dir });
  go(s.genre ? '/genre/' + encodeURIComponent(s.genre) : '/search', stateToParams(s));
}

async function renderList(token, genre, params) {
  const s = listState(genre, params);
  const title = genre || (s.played === 'only' ? 'Played games' : s.q ? `Results for “${s.q}”` : 'All games');
  const years = [];
  for (let y = (META.year_max || new Date().getFullYear()); y >= (META.year_min || 1990); y--) years.push(y);
  const pill = (on, attrs, label, cls = '') => `<button type="button" class="pill ${cls}" aria-pressed="${on}" ${attrs}>${esc(label)}</button>`;
  app.innerHTML = `
    <a class="back" href="#/">${ICON.back} All genres</a>
    <div class="list-head">
      <div><h1>${genre ? `<span style="color:${genreColor(genre)}">${glyph(genre, 30)}</span> ` : ''}${esc(title)}</h1><p class="count" id="count">Loading…</p></div>
      <div class="sortbar">
        <span class="lbl">Sort by</span>
        ${SORTS.map(([k, l]) => pill(s.sort === k, `data-sort="${k}"`, l)).join('')}
        <button type="button" class="pill" id="dirBtn" aria-label="Sort direction">${s.dir === 'asc' ? ICON.up + ' Ascending' : ICON.down + ' Descending'}</button>
      </div>
    </div>
    <div class="filters">
      ${genre ? '' : `<div class="frow"><span class="lbl">Genres</span>${META.genres.map((g) => pill(s.genres.includes(g.name), `data-genre="${esc(g.name)}"`, g.name, 'sm')).join('')}</div>`}
      <div class="frow">
        <div class="fgroup"><span class="lbl" style="width:auto">Mode</span>
          ${[['online', 'Online'], ['couch', 'Couch'], ['lan', 'LAN']].map(([k, l]) => pill(s.modes.includes(k), `data-mode="${k}"`, l)).join('')}</div>
        <div class="fgroup"><span class="lbl" style="width:auto">Platform</span>
          ${META.platforms.map((p) => pill(s.plats.includes(p), `data-plat="${esc(p)}"`, p)).join('')}</div>
      </div>
      <div class="frow">
        <div class="fgroup"><span class="lbl" style="width:auto">Max PEGI</span>
          ${[0, 3, 7, 12, 16, 18].map((a) => pill(s.pegi === a, `data-pegi="${a}"`, a ? String(a) : 'Any')).join('')}
          ${s.pegi ? `<label class="check"><input type="checkbox" id="unrated" ${s.unrated ? 'checked' : ''}> include unrated</label>` : ''}</div>
        <div class="fgroup"><span class="lbl" style="width:auto">Released</span>
          <select class="sel" id="yf" aria-label="Released from year"><option value="0">from any</option>${years.slice().reverse().map((y) => `<option ${y === s.yf ? 'selected' : ''}>${y}</option>`).join('')}</select>
          <select class="sel" id="yt" aria-label="Released to year"><option value="0">to any</option>${years.map((y) => `<option ${y === s.yt ? 'selected' : ''}>${y}</option>`).join('')}</select></div>
        <div class="fgroup"><span class="lbl" style="width:auto">Played</span>
          ${[['', 'All'], ['hide', 'Hide'], ['only', 'Only']].map(([k, l]) => pill(s.played === k, `data-played="${k}"`, l)).join('')}</div>
        <button type="button" class="linkbtn" id="reset">Reset filters</button>
      </div>
    </div>
    <div class="grid" id="grid"></div>
    <div class="more" id="more"></div>`;

  app.querySelectorAll('[data-sort]').forEach((b) => b.onclick = () => apply({ ...s, sort: b.dataset.sort }));
  $('#dirBtn').onclick = () => apply({ ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' });
  const toggle = (arr, v) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]);
  app.querySelectorAll('[data-genre]').forEach((b) => b.onclick = () => apply({ ...s, genres: toggle(s.genres, b.dataset.genre) }));
  app.querySelectorAll('[data-mode]').forEach((b) => b.onclick = () => apply({ ...s, modes: toggle(s.modes, b.dataset.mode) }));
  app.querySelectorAll('[data-plat]').forEach((b) => b.onclick = () => apply({ ...s, plats: toggle(s.plats, b.dataset.plat) }));
  app.querySelectorAll('[data-pegi]').forEach((b) => b.onclick = () => apply({ ...s, pegi: +b.dataset.pegi }));
  app.querySelectorAll('[data-played]').forEach((b) => b.onclick = () => apply({ ...s, played: b.dataset.played }));
  if ($('#unrated')) $('#unrated').onchange = (e) => apply({ ...s, unrated: e.target.checked });
  $('#yf').onchange = (e) => apply({ ...s, yf: +e.target.value });
  $('#yt').onchange = (e) => apply({ ...s, yt: +e.target.value });
  $('#reset').onclick = () => apply({ ...s, q: '', genres: [], modes: [], pegi: 0, unrated: false, plats: [], yf: 0, yt: 0, played: '' });

  let offset = 0;
  const load = async () => {
    const res = await api('/api/games?' + apiParams(s, offset));
    if (token !== renderToken) return;
    $('#count').textContent = `${res.total.toLocaleString('en')} ${res.total === 1 ? 'game' : 'games'}`;
    if (!res.total) {
      $('#grid').outerHTML = '<p class="empty-note" id="grid">No games match these filters.</p>';
      $('#more').innerHTML = '';
      return;
    }
    $('#grid').insertAdjacentHTML('beforeend', res.items.map(card).join(''));
    bindPlayed($('#grid'));
    offset += res.items.length;
    $('#more').innerHTML = offset < res.total ? `<button type="button" class="btn" id="moreBtn">Show more (${(res.total - offset).toLocaleString('en')} left)</button>` : '';
    if ($('#moreBtn')) $('#moreBtn').onclick = load;
  };
  load().catch((e) => { $('#count').textContent = 'Failed to load: ' + e.message; });
}

function card(g) {
  return `<article class="card${g.played ? ' played' : ''}" data-id="${g.id}">
    <a class="cover" href="#/game/${g.id}">
      ${g.image ? `<img src="${esc(g.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<span class="noimg">${esc(g.name)}</span>`}
      ${g.score ? `<span class="score" style="background:${scoreColor(g.score)}">${g.score}</span>` : '<span class="score none">n/a</span>'}
      ${g.played ? `<span class="badge-played">${ICON.check} Played</span>` : ''}
    </a>
    <div class="card-body">
      <div class="card-title"><a href="#/game/${g.id}">${esc(g.name)}</a>${g.pegi ? `<span class="pegi p${g.pegi}" title="PEGI age rating">PEGI ${g.pegi}</span>` : ''}</div>
      <div class="meta"><span>${fmtDate(g.release_date)}</span><span>·</span><span>${esc(g.genres.join(', '))}</span></div>
      <div class="meta">${esc(g.platforms.join(' · '))}</div>
      <div class="coop">
        <div><span class="k">Online</span><span class="v${g.online ? '' : ' no'}">${players(g.online)}</span></div>
        <div><span class="k">Couch</span><span class="v${g.couch ? '' : ' no'}">${players(g.couch)}</span></div>
        <div><span class="k">LAN</span><span class="v${g.lan ? '' : ' no'}">${players(g.lan)}</span></div>
      </div>
      ${playButton(g)}
    </div>
  </article>`;
}
function playButton(g) {
  return `<button type="button" class="play-btn" data-played-id="${g.id}" aria-pressed="${g.played}">${g.played ? ICON.check + ' Played' : ICON.plus + ' Mark as played'}</button>`;
}
function bindPlayed(root) {
  root.querySelectorAll('[data-played-id]:not([data-bound])').forEach((b) => {
    b.dataset.bound = '1';
    b.onclick = async () => {
      const id = b.dataset.playedId;
      const on = b.getAttribute('aria-pressed') !== 'true';
      b.disabled = true;
      try {
        await api('/api/played/' + id, { method: on ? 'PUT' : 'DELETE' });
        b.setAttribute('aria-pressed', on);
        b.innerHTML = on ? ICON.check + ' Played' : ICON.plus + ' Mark as played';
        const cardEl = b.closest('.card');
        if (cardEl) {
          cardEl.classList.toggle('played', on);
          const cover = cardEl.querySelector('.cover');
          const badge = cover.querySelector('.badge-played');
          if (on && !badge) cover.insertAdjacentHTML('beforeend', `<span class="badge-played">${ICON.check} Played</span>`);
          if (!on && badge) badge.remove();
        }
        refreshStatus();
      } finally { b.disabled = false; }
    };
  });
}

// ---------------------------------------------------------------- game page
async function renderGame(token, id) {
  app.innerHTML = '<p class="muted">Loading…</p>';
  let g;
  try { g = await api('/api/games/' + id); } catch (e) { app.innerHTML = '<p class="empty-note">Game not found.</p>'; return; }
  if (token !== renderToken) return;
  const yt = 'https://www.youtube.com/results?search_query=' + encodeURIComponent(g.name + ' co-op gameplay');
  const trailers = g.trailers || [];
  app.innerHTML = `
    <a class="back" href="javascript:history.back()">${ICON.back} Back</a>
    <div class="game-hero">
      ${g.banner ? `<img class="bg" src="${esc(g.banner)}" alt="" referrerpolicy="no-referrer">` : ''}
      <div class="in">
        <div><h1>${esc(g.name)}</h1><div class="meta" style="margin-top:8px;font-size:14px">${fmtDate(g.release_date)} · ${esc(g.platforms.join(' · '))}</div></div>
        ${g.score ? `<span class="big-score" style="background:${scoreColor(g.score)}">${g.score}</span>` : ''}
      </div>
    </div>
    <div class="cols">
      <div class="main">
        <div class="video" id="video">${trailers.length ? iframe(trailers[0].id) : '<div class="none">No trailer on OpenCritic</div>'}</div>
        ${trailers.length > 1 ? `<div class="trailers">${trailers.map((t, i) => `<button type="button" class="pill sm" aria-pressed="${i === 0}" data-yt="${esc(t.id)}">${esc(t.name || 'Trailer ' + (i + 1))}</button>`).join('')}</div>` : ''}
        <div><a class="btn" href="${yt}" target="_blank" rel="noopener">${ICON.yt} Co-op gameplay on YouTube</a></div>
        ${g.description ? `<div class="panel"><h2>About</h2><div class="desc">${esc(g.description)}</div></div>` : ''}
      </div>
      <aside class="side">
        ${playButton(g)}
        <div class="panel facts">
          <div><div class="k">OpenCritic</div><div>${g.score ?? 'n/a'}</div></div>
          <div><div class="k">Age rating</div><div>${g.pegi ? 'PEGI ' + g.pegi : 'unknown'}</div></div>
          <div><div class="k">Released</div><div>${fmtDate(g.release_date)}</div></div>
          <div><div class="k">Platforms</div><div>${esc(g.platforms.join(', '))}</div></div>
          <div style="grid-column:1/-1"><div class="k">Genres</div><div class="tags" style="margin-top:4px">${g.genres.map((x) => `<a class="tag" href="#/genre/${encodeURIComponent(x)}">${esc(x)}</a>`).join('')}</div></div>
        </div>
        <div class="panel"><h2>Co-op</h2>
          ${g.coop.length ? `<table class="cooptab"><thead><tr><th>Platform</th><th>Online</th><th>Couch</th><th>LAN</th></tr></thead><tbody>
            ${g.coop.map((c) => `<tr><td><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.platform)}</a></td><td>${c.online || '—'}</td><td>${c.couch || '—'}</td><td>${c.lan || '—'}</td></tr>`).join('')}
          </tbody></table>
          ${g.features.length ? `<div class="tags" style="margin-top:10px">${g.features.map((f) => `<span class="tag">${esc(f)}</span>`).join('')}</div>` : ''}`
          : '<p class="muted" style="margin:0">Co-op tag from OpenCritic only; Co-optimus has no details for this game.</p>'}
        </div>
        <a href="${esc(g.url)}" target="_blank" rel="noopener">View on OpenCritic</a>
      </aside>
    </div>`;
  bindPlayed(app);
  app.querySelectorAll('[data-yt]').forEach((b) => b.onclick = () => {
    $('#video').innerHTML = iframe(b.dataset.yt);
    app.querySelectorAll('[data-yt]').forEach((x) => x.setAttribute('aria-pressed', x === b));
  });
}
function iframe(id) {
  return `<iframe src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?rel=0" title="Trailer" allow="accelerometer; encrypted-media; gyroscope; picture-in-picture; fullscreen" allowfullscreen loading="lazy" referrerpolicy="strict-origin-when-cross-origin"></iframe>`;
}

// ---------------------------------------------------------------- status page
async function renderStatus(token) {
  let prevKey = null;
  const draw = async () => {
    const st = await api('/api/status');
    if (token !== renderToken) return false;
    // Re-render only on change so a chosen import file is not wiped by the poll.
    const key = JSON.stringify(st);
    if (key === prevKey) return st.running;
    prevKey = key;
    const pct = st.total ? Math.round((+st.done / +st.total) * 100) : null;
    app.innerHTML = `
      <a class="back" href="#/">${ICON.back} Home</a>
      <h1>Data</h1>
      <div class="status-grid">
        <div class="panel stat"><div class="muted">Games</div><div class="n">${st.games.toLocaleString('en')}</div></div>
        <div class="panel stat"><div class="muted">Played</div><div class="n">${st.played}</div></div>
        <div class="panel stat"><div class="muted">Last update</div><div style="margin-top:6px">${st.last_update_at ? new Date(st.last_update_at).toLocaleString('en-GB') : 'never'}</div><div class="muted" style="font-size:13px">${esc(st.last_result || '')}</div></div>
        <div class="panel stat"><div class="muted">Auto update</div><div style="margin-top:6px">${st.interval_hours > 0 ? 'every ' + st.interval_hours + ' h' : 'off'}</div></div>
      </div>
      <div class="panel">
        ${st.running
          ? `<h2>Updating · ${esc(st.step || '')} ${st.done ? `(${st.done}${st.total ? ' / ' + st.total : ''})` : ''}</h2>
             ${pct !== null ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ''}
             <div style="margin-top:14px"><button type="button" class="btn" id="stopBtn">Stop</button></div>`
          : `<h2>Update the database</h2>
             <p class="muted" style="margin:0 0 12px">Quick update: new games, co-op data, scores of recent games, missing PEGI ratings. Full refresh re-crawls the whole OpenCritic catalog and every game page (hours).</p>
             <div style="display:flex;gap:10px;flex-wrap:wrap"><button type="button" class="btn primary" id="updBtn">Update now</button><button type="button" class="btn" id="fullBtn">Full refresh</button></div>`}
      </div>
      ${Object.keys(st.last_stats || {}).length ? `<div class="panel" style="margin-top:14px"><h2>Last run</h2><pre class="stats">${esc(JSON.stringify(st.last_stats, null, 1).replace(/[{}"]/g, '').trim())}</pre></div>` : ''}
      <div class="panel" style="margin-top:14px">
        <h2>Import Co-optimus data from your browser</h2>
        <p class="muted" style="margin:0 0 10px">Use this when Co-optimus blocks the server (HTTP 403 from Cloudflare). It takes about 10 minutes.</p>
        <ol class="muted" style="margin:0 0 12px;padding-left:20px">
          <li>Open <a href="https://www.co-optimus.com/games.php" target="_blank" rel="noopener">co-optimus.com/games.php</a> in a normal browser tab.</li>
          <li>Open the developer console (Cmd+Option+J in Chrome), paste the script, press Enter. The console shows progress; when it finishes, the browser downloads <b>coopt.json</b>.</li>
          <li>Choose that file below and press Import.</li>
        </ol>
        <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
          <button type="button" class="btn" id="copySnippet">Copy script</button>
          <input type="file" id="cooptFile" accept="application/json,.json" aria-label="coopt.json file">
          <button type="button" class="btn primary" id="importBtn" ${st.running ? 'disabled' : ''}>Import</button>
          <span class="muted" id="importMsg"></span>
        </div>
        <pre class="stats" style="max-height:160px;overflow:auto;background:#0f1115;padding:10px;border-radius:8px;border:1px solid var(--line)">${esc(COOPT_SNIPPET)}</pre>
      </div>`;
    $('#copySnippet').onclick = async () => {
      try { await navigator.clipboard.writeText(COOPT_SNIPPET); $('#copySnippet').textContent = 'Copied'; } catch (e) { $('#copySnippet').textContent = 'Select the text and copy'; }
    };
    $('#importBtn').onclick = async () => {
      const file = $('#cooptFile').files[0];
      if (!file) { $('#importMsg').textContent = 'Choose coopt.json first'; return; }
      $('#importMsg').textContent = 'Uploading…';
      try {
        const r = await fetch('/api/import/cooptimus', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: await file.text() });
        const j = await r.json();
        $('#importMsg').textContent = r.ok ? `Importing ${j.rows.toLocaleString('en')} rows…` : (j.detail || 'Import failed');
        if (r.ok) setTimeout(draw, 1500);
      } catch (e) { $('#importMsg').textContent = 'Import failed: ' + e.message; }
    };
    if ($('#updBtn')) $('#updBtn').onclick = async () => { await api('/api/update', { method: 'POST' }); draw(); };
    if ($('#fullBtn')) $('#fullBtn').onclick = async () => { if (confirmFull()) { await api('/api/update?full=true', { method: 'POST' }); draw(); } };
    if ($('#stopBtn')) $('#stopBtn').onclick = async () => { await api('/api/update/stop', { method: 'POST' }); draw(); };
    return st.running;
  };
  const loop = async () => {
    const running = await draw().catch(() => false);
    if (token === renderToken) setTimeout(loop, running ? 2000 : 10000);
  };
  loop();
}
// Runs in the browser console on co-optimus.com and downloads coopt.json for /api/import/cooptimus
const COOPT_SNIPPET = `(async () => {
  const SYSTEMS = { 'PC': 4, 'PS4': 22, 'PS5': 30, 'Switch': 28, 'Switch 2': 34 };
  const num = (t) => (/^\\d+$/.test(t.trim()) ? +t.trim() : 0);
  const out = [];
  for (const [platform, system] of Object.entries(SYSTEMS)) {
    let page = 1, last = 1;
    while (page <= last) {
      const html = await (await fetch('/ajax/ajax_games.php?system=' + system + '&page=' + page)).text();
      const doc = new DOMParser().parseFromString(html, 'text/html');
      doc.querySelectorAll('a[onclick]').forEach((a) => {
        const m = (a.getAttribute('onclick') || '').match(/setPage\\('(\\d+)'\\)/);
        if (m) last = Math.max(last, +m[1]);
      });
      const rows = [...doc.querySelectorAll('tr.result_row')];
      if (!rows.length) break;
      for (const tr of rows) {
        const td = [...tr.children];
        if (td.length < 7 || !/^\\d+$/.test(tr.id)) continue;
        const features = [];
        td[4].querySelectorAll('.features-icon').forEach((a) => {
          const t = (a.title || '').trim();
          if (/Players? in Co-Op/.test(t)) return;
          const f = t.replace(/^Supports\\s+/, '').replace(/\\s+Co-Op$/, '');
          if (f) features.push(f);
        });
        const d = td[6].textContent.trim().match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})/);
        out.push({
          platform, coopt_id: +tr.id,
          title: (td[0].querySelector('strong') || {}).textContent?.trim(),
          genre: (td[0].querySelector('label') || {}).textContent?.trim() || null,
          online: num(td[1].textContent), couch: num(td[2].textContent), lan: num(td[3].textContent),
          features, release: d ? d[3] + '-' + d[1] + '-' + d[2] : null,
        });
      }
      console.log(platform, 'page', page, 'of', last, '-', out.length, 'rows');
      page++;
      await new Promise((r) => setTimeout(r, 300));
    }
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out)], { type: 'application/json' }));
  a.download = 'coopt.json';
  a.click();
  console.log('Done:', out.length, 'rows saved to coopt.json');
})();`;

function confirmFull() {
  return window.confirm('Full refresh takes several hours. Start it?');
}

// ---------------------------------------------------------------- header
let searchTimer = null;
$('#q').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const { parts, params } = parseHash();
    const p = parts[0] === 'search' ? params : new URLSearchParams();
    if (e.target.value.trim()) p.set('q', e.target.value.trim()); else p.delete('q');
    go('/search', p);
  }, 250);
});
$('#searchForm').addEventListener('submit', (e) => e.preventDefault());

let lastRunning = null;
async function refreshStatus() {
  try {
    const st = await api('/api/status');
    $('#playedCount').textContent = st.played;
    const dot = $('#statusDot');
    dot.className = 'dot ' + (st.running ? 'run' : (st.last_result || '').startsWith('error') ? 'err' : st.games ? 'ok' : '');
    $('#statusLink').title = st.running ? 'Updating: ' + (st.step || '') : 'Database status';
    if (lastRunning && !st.running) { META = null; if (!parseHash().parts.length) route(); }
    lastRunning = st.running;
  } catch (e) { /* server unreachable */ }
}
setInterval(refreshStatus, 15000);
refreshStatus();
route();
