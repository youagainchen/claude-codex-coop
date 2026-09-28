(() => {
  const $ = id => document.getElementById(id);
  // 地址形如 #<令牌>&bg=aurora&run=<run_id>：令牌之后的参数可直接指定背景或打开某次调用。
  const [token, ...hashRest] = location.hash.slice(1).split('&');
  const hashParams = new URLSearchParams(hashRest.join('&'));
  const NAMES = {codex: 'Codex', claude: 'Claude'};
  const STATES = {queued: '排队', running: '运行中', completed: '完成', failed: '失败'};
  const KINDS = {routed_workflow: '协作', consultation: '咨询', debate: '辩论', implementation: '实施'};
  const CUSTOM = '__custom__';
  let data, pref = {}, saving = false, editing = false;

  async function api(path, body) {
    const response = await fetch('/api/' + path, {
      method: body ? 'POST' : 'GET', cache: 'no-store',
      headers: {Authorization: 'Bearer ' + token, ...(body ? {'Content-Type': 'application/json'} : {})},
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(20000)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '连接失败');
    return result;
  }
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function showError(e) { $('error').hidden = !e; $('error').textContent = e ? (e.message || String(e)) : ''; }

  // agent_settings 有三种写法：{codex:{model,effort}}、{agent,model,effort}、{model,effort}（实施=Codex）。
  function settingsOf(run) {
    const s = run.agent_settings || {};
    if (s.model || s.effort) return [[s.agent || 'codex', s.model, s.effort]];
    return Object.entries(s).filter(([, v]) => v && typeof v === 'object').map(([k, v]) => [k, v.model, v.effort]);
  }
  function describe(run) {
    return settingsOf(run).map(([a, m, e]) => (NAMES[a] || a) + ' · ' + (m || '默认') + ' · ' + (e || '默认')).join(' / ');
  }
  function elapsed(run) {
    const start = Date.parse(run.created_at);
    const end = run.state === 'completed' || run.state === 'failed' ? Date.parse(run.updated_at) : Date.now();
    if (!start || !end) return '';
    const sec = Math.max(0, Math.round((end - start) / 1000));
    const mm = String(Math.floor(sec / 60) % 60).padStart(2, '0'), ss = String(sec % 60).padStart(2, '0');
    return (sec >= 3600 ? Math.floor(sec / 3600) + ':' : '') + mm + ':' + ss;
  }
  function ago(iso) {
    const t = Date.parse(iso); if (!t) return '';
    const m = Math.round((Date.now() - t) / 60000);
    if (m < 1) return '刚刚';
    if (m < 60) return m + ' 分钟前';
    if (m < 1440) return Math.round(m / 60) + ' 小时前';
    return new Date(t).toLocaleDateString();
  }

  function fmtTokens(n) {
    if (n == null) return '—';
    return n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n);
  }
  // 重置时间显示具体时刻：今天/明天 HH:MM，更远显示 M/D HH:MM。
  function fmtReset(epoch) {
    if (!epoch) return '';
    const t = new Date(epoch * 1000), now = new Date();
    if (t <= now) return '已重置';
    const hm = String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0');
    const day = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const diff = Math.round((day(t) - day(now)) / 86400000);
    const when = diff === 0 ? '今天 ' : diff === 1 ? '明天 ' : (t.getMonth() + 1) + '/' + t.getDate() + ' ';
    return when + hm + ' 重置';
  }
  function limitRow(label, w) {
    const row = el('div', 'limit');
    const expired = w.resets_at && w.resets_at * 1000 < Date.now();
    const pct = expired ? 0 : Math.max(0, Math.min(100, Math.round(w.used_percent)));
    const bar = el('span', 'bar'), fill = el('i', pct >= 90 ? 'hot' : pct >= 70 ? 'warn' : '');
    fill.style.width = pct + '%'; bar.append(fill);
    const left = el('span'); left.append(label + ' ', el('b', '', pct + '%'));
    row.append(left, bar, el('span', '', fmtReset(w.resets_at)));
    return row;
  }
  // 卡片里模型下方：对方账户额度（Codex 会话日志里最近一次记录）+ 这一轮用掉的 token。
  function renderUsage(run) {
    const box = $('usage'); box.replaceChildren();
    const lim = data?.partner_limits;
    if (lim?.primary) box.append(limitRow('5 小时', lim.primary));
    if (lim?.secondary) box.append(limitRow('本周', lim.secondary));
    const [agent] = run ? (settingsOf(run)[0] || []) : [];
    const u = run?.usage_summary?.[agent || data?.partner_agent];
    if (u) {
      const cached = u.cached_input_tokens && u.input_tokens ? '（缓存 ' + Math.round(u.cached_input_tokens / u.input_tokens * 100) + '%）' : '';
      box.append(el('div', 'tokens', '本轮 输入 ' + fmtTokens(u.input_tokens) + cached + ' · 输出 ' + fmtTokens(u.output_tokens) +
        (u.reasoning_output_tokens ? ' · 思考 ' + fmtTokens(u.reasoning_output_tokens) : '')));
    }
    if (lim?.source === 'codex' && lim.observed_at) box.append(el('div', 'usage-note', '额度读自 Codex 最近一次会话记录 · ' + ago(lim.observed_at)));
    box.hidden = !box.children.length;
  }
  function renderNow() {
    if (!data) return;
    const runs = data.runs || [];
    const run = runs.find(r => r.state === 'running' || r.state === 'queued') || runs[0];
    const box = $('now');
    if (!run) {
      box.className = 'glass now idle';
      $('nowLabel').textContent = '协作伙伴';
      $('nowState').textContent = '空闲';
      $('nowAgent').textContent = NAMES[data.partner_agent] || data.partner_agent;
      const auto = (pref.selection || 'auto') === 'auto';
      $('nowModel').textContent = auto ? '自动选择' : (pref.model || '默认');
      $('nowEffort').textContent = auto ? '自动' : (pref.effort || '默认');
      $('nowMeta').textContent = '在左侧聊天里描述任务，调用时这里会实时显示。';
      renderUsage(null);
      return;
    }
    const live = run.state === 'running' || run.state === 'queued';
    box.className = 'glass now ' + (live ? 'live' : run.state === 'failed' ? 'failed' : 'done');
    $('nowLabel').textContent = live ? '正在调用' : '上一次调用 · ' + ago(run.updated_at);
    $('nowState').textContent = (STATES[run.state] || run.state) + ' ' + elapsed(run);
    const [agent, model, effort] = settingsOf(run)[0] || [data.partner_agent, '', ''];
    $('nowAgent').textContent = NAMES[agent] || agent;
    $('nowModel').textContent = run.actual_model && run.actual_model !== model ? run.actual_model : (model || '默认');
    $('nowModel').title = run.actual_model ? '请求的模型：' + (model || '默认') + '；实际运行：' + run.actual_model : '';
    $('nowEffort').textContent = effort || '默认';
    $('nowMeta').textContent = [KINDS[run.kind] || run.kind, run.mode, run.state === 'failed' ? run.error : run.route?.reason]
      .filter(Boolean).join(' · ');
    renderUsage(run);
  }

  function renderRuns() {
    const list = $('runs'); list.replaceChildren();
    const runs = data.runs || [];
    $('count').textContent = runs.length ? runs.length + ' 条' : '';
    if (!runs.length) { list.append(el('li', 'empty', '还没有调用记录。')); return; }
    for (const run of runs) {
      const li = el('li', 'run ' + (run.state || ''));
      li.title = '查看这次调用的对话';
      li.onclick = () => openDetail(run.run_id);
      li.append(el('span', 'dot'), el('span', 'what', describe(run) || (KINDS[run.kind] || '协作')),
        el('span', 'dur', (run.state === 'completed' ? '' : (STATES[run.state] || run.state) + ' ') + elapsed(run)),
        el('span', 'sub', [KINDS[run.kind] || run.kind, run.mode, ago(run.updated_at), run.state === 'failed' ? run.error : ''].filter(Boolean).join(' · ')));
      list.append(li);
    }
  }

  function currentModel() {
    return $('model').value === CUSTOM ? $('customModel').value.trim() : $('model').value;
  }
  function renderEfforts(preferred) {
    const model = data.partner.models.find(m => m.id === currentModel());
    const values = model?.efforts?.length ? model.efforts : data.partner_efforts;
    const pick = values.includes(preferred) ? preferred : (model?.default_effort && values.includes(model.default_effort) ? model.default_effort : values.includes('medium') ? 'medium' : values[0]);
    $('efforts').replaceChildren(...values.map(v => {
      const b = el('button', '', v); b.type = 'button'; b.dataset.effort = v;
      b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(v === pick));
      if (model?.default_effort === v) b.title = '该模型默认强度';
      return b;
    }));
    const src = data.partner.verified ? (data.partner.note || '来自 ' + (data.partner.source || 'CLI')) : (data.partner.note || '别名，实际型号以运行结果为准');
    $('modelHint').textContent = data.partner.models.length + ' 个模型 · ' + src;
  }
  function currentEffort() {
    return $('efforts').querySelector('[aria-checked=true]')?.dataset.effort || '';
  }
  function setSelection(sel) {
    for (const b of document.querySelectorAll('.segmented button')) b.setAttribute('aria-checked', String(b.dataset.sel === sel));
    $('manual').hidden = sel !== 'manual';
    $('autoHint').hidden = sel === 'manual';
  }
  // Claude 当协作伙伴时，命令行未登录就提示登录方法（插件固定使用命令行登录的 Claude 账号）。
  function renderLogin() {
    const hint = $('loginHint');
    const login = data.claude_login;
    hint.hidden = !(data.partner_agent === 'claude' && login && !login.logged_in);
    if (hint.hidden) return;
    const btn = el('button', 'login-btn', '登录 Claude CLI');
    btn.type = 'button';
    btn.onclick = async () => {
      btn.disabled = true;
      try { await api('claude-login', {}); btn.textContent = '已打开登录窗口，完成浏览器授权后稍等'; }
      catch (e) { showError(e); btn.disabled = false; }
    };
    hint.replaceChildren('Claude CLI 尚未登录，用与 Claude 桌面版相同的账号登录一次即可。', btn);
  }
  function renderSettings() {
    const models = data.partner.models;
    const known = models.some(m => m.id === pref.model);
    $('model').replaceChildren(
      ...models.map(m => new Option((m.label || m.id) + (m.default_effort ? '' : ''), m.id)),
      new Option('自定义模型 ID…', CUSTOM));
    $('model').value = pref.model ? (known ? pref.model : CUSTOM) : (models[0]?.id || CUSTOM);
    $('customModel').hidden = $('model').value !== CUSTOM;
    if (!known && pref.model) $('customModel').value = pref.model;
    renderEfforts(pref.effort);
    setSelection(pref.selection || 'auto');
    renderLogin();
  }

  function render(next) {
    data = next;
    pref = next.preferences || {};
    $('workspacePath').textContent = next.workspace;
    $('workspacePath').title = next.workspace;
    $('access').textContent = (NAMES[next.primary_agent] || next.primary_agent) + ' 主协调';
    $('enabled').disabled = false;
    $('enabled').setAttribute('aria-checked', String(next.collaboration_enabled));
    $('enabled').title = next.collaboration_enabled ? '自动协作：开（点击关闭）' : '自动协作：关（点击开启）';
    if (!editing && !saving) renderSettings();
    renderRuns(); renderNow();
  }

  async function refresh() {
    try { render(await api('state')); $('connection').className = 'conn on'; $('connection').textContent = '已连接'; showError(null); }
    catch (e) { $('connection').className = 'conn off'; $('connection').textContent = '连接中断'; showError(e); }
  }

  async function save() {
    if (!data) return;
    const sel = document.querySelector('.segmented [aria-checked=true]').dataset.sel;
    const body = {partner_selection: sel};
    if (sel === 'manual') {
      const model = currentModel();
      if (!model) { $('saveStatus').textContent = '请输入模型 ID'; return; }
      body.partner_model = model; body.partner_effort = currentEffort();
    }
    saving = true; $('saveStatus').textContent = '保存中…';
    try { await api('preferences', body); $('saveStatus').textContent = '已保存'; editing = false; }
    catch (e) { showError(e); $('saveStatus').textContent = '保存失败'; }
    finally { saving = false; await refresh(); setTimeout(() => { if ($('saveStatus').textContent === '已保存') $('saveStatus').textContent = ''; }, 1800); }
  }

  for (const b of document.querySelectorAll('.segmented button')) b.onclick = () => { setSelection(b.dataset.sel); save(); };
  $('model').onchange = () => {
    $('customModel').hidden = $('model').value !== CUSTOM;
    if ($('model').value === CUSTOM) { editing = true; $('customModel').focus(); return; }
    renderEfforts(currentEffort()); save();
  };
  $('customModel').oninput = () => { editing = true; };
  $('customModel').onchange = () => { renderEfforts(currentEffort()); save(); };
  $('efforts').onclick = e => {
    const b = e.target.closest('button'); if (!b) return;
    for (const x of $('efforts').children) x.setAttribute('aria-checked', String(x === b));
    save();
  };
  $('enabled').onclick = async () => {
    $('enabled').disabled = true;
    try { await api('mode', {enabled: $('enabled').getAttribute('aria-checked') !== 'true'}); await refresh(); }
    catch (e) { showError(e); } finally { $('enabled').disabled = false; }
  };

  // ---- 调用详情：协作 AI 的对话输出 ----
  function esc(t) { return String(t).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
  function inline(t) {
    return esc(t)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  }
  // 极简 Markdown：先整体转义再加标签，不引入外部库（面板 CSP 只允许本地脚本）。
  function markdown(src) {
    const lines = String(src).replace(/\r/g, '').split('\n'), out = [];
    let i = 0;
    const cells = row => row.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        const buf = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        i++; out.push('<pre><code>' + esc(buf.join('\n')) + '</code></pre>'); continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || '')) {
        const head = cells(line); i += 2; const body = [];
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) body.push(cells(lines[i++]));
        out.push('<div class="tbl"><table><thead><tr>' + head.map(c => '<th>' + inline(c) + '</th>').join('') + '</tr></thead><tbody>' +
          body.map(r => '<tr>' + r.map(c => '<td>' + inline(c) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>');
        continue;
      }
      const h = line.match(/^(#{1,4})\s+(.*)$/);
      if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
      if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line), items = [];
        const start = ordered ? parseInt(line, 10) : 1;  // 条目之间隔着段落时保留原编号
        while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''));
        out.push((ordered ? `<ol start="${start}">` : '<ul>') + items.map(t => '<li>' + inline(t) + '</li>').join('') + (ordered ? '</ol>' : '</ul>'));
        continue;
      }
      if (/^>\s?/.test(line)) {
        const buf = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ''));
        out.push('<blockquote>' + inline(buf.join(' ')) + '</blockquote>'); continue;
      }
      if (!line.trim()) { i++; continue; }
      const buf = [];
      while (i < lines.length && lines[i].trim() && !/^(```|#{1,4}\s|\s*([-*]|\d+\.)\s|>|\s*\|.*\|\s*$)/.test(lines[i])) buf.push(lines[i++]);
      if (!buf.length) buf.push(lines[i++]);
      out.push('<p>' + buf.map(inline).join('<br>') + '</p>');
    }
    return out.join('');
  }

  let detailId = null, detailTimer = 0, detailRun = null, detailCount = -1;
  async function loadDetail() {
    if (!detailId) return;
    let d;
    try { d = await api('run?id=' + encodeURIComponent(detailId)); showError(null); }
    catch (e) { showError(e); return; }
    detailRun = d.run;
    const [agent, model, effort] = settingsOf(d.run)[0] || ['', '', ''];
    $('detailAgent').textContent = (NAMES[agent] || agent || '协作') + ' · ' + (d.run.actual_model || model || '默认') + ' · ' + (effort || '默认');
    $('detailMeta').textContent = [KINDS[d.run.kind] || d.run.kind, d.run.mode, ago(d.run.created_at)].filter(Boolean).join(' · ');
    $('detailTask').textContent = d.task || '';
    renderDetailState();
    const live = d.run.state === 'running' || d.run.state === 'queued';
    if (d.entries.length !== detailCount || !live) {
      const box = $('transcript');
      const nearBottom = innerHeight + scrollY >= document.body.scrollHeight - 80;
      // 保留用户手动展开过的步骤组，刷新后不自动收起
      const opened = new Set([...box.querySelectorAll('details[open]')].map(x => x.dataset.key));
      box.replaceChildren();
      const groups = [];
      for (const e of d.entries) {
        if (e.kind === 'step') {
          const last = groups[groups.length - 1];
          if (last?.steps) last.steps.push(e.text); else groups.push({steps: [e.text]});
        } else groups.push(e);
      }
      groups.forEach((g, idx) => {
        if (g.steps) {
          const li = el('li'), det = el('details', 'steps'); det.dataset.key = 's' + idx;
          const tail = live && idx === groups.length - 1;
          if (tail) det.classList.add('live');
          const label = tail ? '正在' + g.steps[g.steps.length - 1] : '已执行 ' + g.steps.length + ' 步';
          const sum = el('summary'); sum.append(el('span', '', label)); det.append(sum);
          const ol = el('ol'); for (const t of g.steps) ol.append(el('li', 'entry-step', t)); det.append(ol);
          if (opened.has(det.dataset.key)) det.open = true;
          li.append(det); box.append(li); return;
        }
        const li = el('li', 'entry-' + g.kind);
        if (g.kind === 'message') { li.classList.add('md'); li.innerHTML = markdown(g.text); }
        else if (g.kind === 'reasoning') {
          const det = el('details'); det.dataset.key = 'r' + idx; det.append(el('summary', '', '思考'), el('div', '', g.text));
          if (opened.has(det.dataset.key)) det.open = true;
          li.append(det);
        } else li.textContent = g.text;
        box.append(li);
      });
      if (live) { const t = el('li', 'typing'); t.append(el('i'), el('i'), el('i')); box.append(t); }
      else if (!d.entries.length) box.append(el('li', 'empty', d.run.state === 'failed' ? (d.run.error || '这次调用失败了。') : '这次调用没有留下对话内容。'));
      if (live && (nearBottom || detailCount < 0)) scrollTo(0, document.body.scrollHeight);
      detailCount = d.entries.length;
    }
    clearTimeout(detailTimer);
    if (live) detailTimer = setTimeout(loadDetail, 1500);
  }
  function renderDetailState() {
    if (!detailRun) return;
    $('detailState').textContent = (STATES[detailRun.state] || detailRun.state) + ' ' + elapsed(detailRun);
  }
  function openDetail(runId) {
    if (!runId) return;
    detailId = runId; detailCount = -1; detailRun = null;
    $('transcript').replaceChildren(el('li', 'empty', '正在读取…'));
    $('detail').hidden = false; document.querySelector('main').classList.add('show-detail');
    scrollTo(0, 0); loadDetail();
  }
  function closeDetail() {
    detailId = null; clearTimeout(detailTimer);
    $('detail').hidden = true; document.querySelector('main').classList.remove('show-detail');
  }
  $('detailBack').onclick = closeDetail;
  addEventListener('keydown', e => { if (e.key === 'Escape' && detailId) closeDetail(); });
  $('now').onclick = () => {
    const runs = data?.runs || [];
    const run = runs.find(r => r.state === 'running' || r.state === 'queued') || runs[0];
    if (run) openDetail(run.run_id);
  };

  // 背景选择只是本机观感偏好，存 localStorage；读写失败时退回“跟随 App”。
  const BG_KEY = 'ai-coop:background';
  function applyBackground(name, remember = true) {
    window.AICoopBackground?.set(name);
    for (const b of $('bgMenu').children) b.setAttribute('aria-checked', String(b.dataset.bg === name));
    if (remember) { try { localStorage.setItem(BG_KEY, name); } catch {} }
  }
  const bgNames = window.AICoopBackground?.names || {plain: '纯色'};
  $('bgMenu').replaceChildren(...Object.entries(bgNames).map(([key, label]) => {
    const b = el('button', 'bg-option'); b.type = 'button'; b.dataset.bg = key; b.setAttribute('role', 'radio');
    b.append(el('i'), document.createTextNode(label));
    b.onclick = () => applyBackground(key);
    return b;
  }));
  $('bgButton').onclick = () => {
    const open = $('bgMenu').hidden;
    $('bgMenu').hidden = !open; $('bgButton').setAttribute('aria-expanded', String(open));
  };
  // 默认跟随 App 的浅色/深色；旧版的“纯色”并入“跟随 App”。
  let savedBg = 'system';
  try { savedBg = localStorage.getItem(BG_KEY) || 'system'; } catch {}
  const bgParam = hashParams.get('bg');
  if (bgNames[bgParam]) applyBackground(bgParam, false);  // 地址参数只影响本次打开，不改保存的偏好
  else applyBackground(bgNames[savedBg] ? savedBg : 'system');

  if (!token) { showError(new Error('面板地址缺少会话信息，请在聊天中重新打开 AI Coop。')); return; }
  refresh().then(() => { if (hashParams.get('run')) openDetail(hashParams.get('run')); });
  setInterval(() => { if (!saving) refresh(); }, 2000);
  setInterval(() => { renderNow(); renderDetailState(); }, 1000);
})();
