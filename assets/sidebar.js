(() => {
  const $ = id => document.getElementById(id);
  // 地址形如 #<令牌>&bg=aurora&run=<run_id>：令牌之后的参数可直接指定背景或打开某次调用。
  const [token, ...hashRest] = location.hash.slice(1).split('&');
  const hashParams = new URLSearchParams(hashRest.join('&'));
  const NAMES = {codex: 'Codex', claude: 'Claude'};
  // 界面文案：默认跟随浏览器语言（zh* 为中文，其余英文），可由地址参数 lang= 或外观菜单切换。
  const I18N = {
    zh: {
      states: {queued: '排队', running: '运行中', completed: '完成', failed: '失败'},
      kinds: {routed_workflow: '协作', consultation: '咨询', debate: '辩论', implementation: '实施'},
      bg: {system: '跟随 App', aurora: '极光', galaxy: '星河', horizon: '地平线'},
      connecting: '连接中', connected: '已连接', disconnected: '连接中断', connectFailed: '连接失败',
      background: '切换外观', bgGroup: '背景', autoCollab: '自动协作',
      autoOn: '自动协作：开（点击关闭）', autoOff: '自动协作：关（点击开启）',
      partner: '协作伙伴', idle: '空闲', idleMeta: '在左侧聊天里描述任务，调用时这里会实时显示。',
      autoPick: '自动选择', auto: '自动', dflt: '默认', calling: '正在调用', lastCall: '上一次调用 · ',
      requested: '请求的模型：', actual: '；实际运行：',
      next: '下一次调用', selMode: '模型选择方式', manual: '手动指定',
      autoHint: '主协调按任务类型挑选模型与推理强度。', model: '模型', customPh: '输入完整模型 ID',
      effort: '推理强度', customModel: '自定义模型 ID…', modelDefault: '该模型默认强度',
      models: n => n + ' 个模型 · ', from: s => '来自 ' + s, alias: '别名，实际型号以运行结果为准',
      recent: '最近调用', count: n => n + ' 条', noRuns: '还没有调用记录。', openRun: '查看这次调用的对话',
      collab: '协作', task: '任务', back: '返回', loading: '正在读取…', thinking: '思考',
      doing: s => '正在' + s, steps: n => '已执行 ' + n + ' 步',
      failedRun: '这次调用失败了。', emptyRun: '这次调用没有留下对话内容。',
      primary: n => n + ' 主协调',
      needModel: '请输入模型 ID', saving: '保存中…', saved: '已保存', saveFailed: '保存失败',
      login: '登录 Claude CLI', loginOpened: '已打开登录窗口，完成浏览器授权后稍等',
      loginHint: 'Claude CLI 尚未登录，用与 Claude 桌面版相同的账号登录一次即可。',
      h5: '5 小时', week: '本周', resetDone: '已重置', today: '今天 ', tomorrow: '明天 ', reset: ' 重置', resetPre: '',
      turn: '本轮 输入 ', cached: p => '（缓存 ' + p + '%）', out: ' · 输出 ', reasoning: ' · 思考 ',
      limitNote: '额度读自 Codex 最近一次会话记录 · ',
      justNow: '刚刚', minAgo: m => m + ' 分钟前', hourAgo: h => h + ' 小时前',
      noToken: '面板地址缺少会话信息，请在聊天中重新打开 AI Coop。'
    },
    en: {
      states: {queued: 'Queued', running: 'Running', completed: 'Done', failed: 'Failed'},
      kinds: {routed_workflow: 'Collab', consultation: 'Consult', debate: 'Debate', implementation: 'Implement'},
      bg: {system: 'Auto', aurora: 'Aurora', galaxy: 'Galaxy', horizon: 'Horizon'},
      connecting: 'Connecting', connected: 'Connected', disconnected: 'Disconnected', connectFailed: 'Connection failed',
      background: 'Appearance', bgGroup: 'Background', autoCollab: 'Auto collaboration',
      autoOn: 'Auto collaboration: on (click to turn off)', autoOff: 'Auto collaboration: off (click to turn on)',
      partner: 'Partner', idle: 'Idle', idleMeta: 'Describe a task in the chat; calls show up here live.',
      autoPick: 'Auto', auto: 'Auto', dflt: 'default', calling: 'Calling now', lastCall: 'Last call · ',
      requested: 'Requested: ', actual: '; actually ran: ',
      next: 'Next call', selMode: 'Model selection', manual: 'Manual',
      autoHint: 'The coordinator picks the model and reasoning effort for each task.', model: 'Model', customPh: 'Full model ID',
      effort: 'Reasoning effort', customModel: 'Custom model ID…', modelDefault: 'Default for this model',
      models: n => n + (n === 1 ? ' model · ' : ' models · '), from: s => 'from ' + s, alias: 'aliases; the actual model is shown after a run',
      recent: 'Recent calls', count: n => String(n), noRuns: 'No calls yet.', openRun: 'Open this call',
      collab: 'Collab', task: 'Task', back: 'Back', loading: 'Loading…', thinking: 'Reasoning',
      doing: s => s + '…', steps: n => n + (n === 1 ? ' step' : ' steps') + ' run',
      failedRun: 'This call failed.', emptyRun: 'This call left no transcript.',
      primary: n => n + ' coordinates',
      needModel: 'Enter a model ID', saving: 'Saving…', saved: 'Saved', saveFailed: 'Save failed',
      login: 'Sign in to Claude CLI', loginOpened: 'Sign-in window opened; finish in the browser, then wait a moment',
      loginHint: 'Claude CLI is not signed in. Sign in once with the same account as the Claude desktop app.',
      h5: '5h', week: 'Week', resetDone: 'reset', today: 'today ', tomorrow: 'tomorrow ', reset: '', resetPre: 'resets ',
      turn: 'This call: in ', cached: p => ' (' + p + '% cached)', out: ' · out ', reasoning: ' · reasoning ',
      limitNote: 'Limits from the latest Codex session log · ',
      justNow: 'just now', minAgo: m => m + ' min ago', hourAgo: h => h + ' h ago',
      noToken: 'The panel URL is missing its session token. Reopen AI Coop from the chat.'
    }
  };
  // 服务端固定的中文文案（报错、路由理由）在英文界面下换成对应英文；其余原样显示。
  const SERVER_TEXT = {'面板会话已失效，请重新打开 AI Coop': 'Panel session expired. Reopen AI Coop from the chat.',
    '找不到这次调用的记录': 'This call could not be found.',
    '用户手动指定协作 AI 模型': 'Model chosen manually',
    '协作 AI 负责代码实施或验证，使用偏执行的 Codex 配置。': 'Implementation or verification: execution-oriented Codex settings.',
    '任务包含决策权衡，增加协作 AI 的推理强度。': 'Decision with trade-offs: higher reasoning effort.',
    '使用 Codex 的均衡咨询配置。': 'Balanced Codex consultation settings.',
    '任务需要审查、写作或权衡，增加协作 AI 的推理强度。': 'Review, writing or trade-offs: higher reasoning effort.',
    '使用 Claude 的均衡咨询配置。': 'Balanced Claude consultation settings.',
    '宿主进程已退出，这一轮已中断': 'The host process exited; this call was interrupted.'};
  const tr = text => (lang === 'en' && SERVER_TEXT[text]) || text;
  // 详情步骤的固定前缀由服务端以中文生成（运行/搜索/调用工具），英文界面只替换前缀，命令本身原样保留。
  const STEP_PREFIX = [[/^运行 /, 'Run '], [/^搜索 /, 'Search '], [/^调用工具 /, 'Tool '], [/^工具 /, 'Tool ']];
  const trStep = text => lang === 'en' ? STEP_PREFIX.reduce((t, [re, en]) => t.replace(re, en), text) : text;
  const LANG_KEY = 'ai-coop:lang';
  let lang = hashParams.get('lang');
  if (!I18N[lang]) { try { lang = localStorage.getItem(LANG_KEY); } catch {} }
  if (!I18N[lang]) lang = /^zh/i.test(navigator.language || '') ? 'zh' : 'en';
  let T = I18N[lang], STATES = T.states, KINDS = T.kinds;
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
    if (!response.ok) throw new Error(tr(result.error) || T.connectFailed);
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
    return settingsOf(run).map(([a, m, e]) => (NAMES[a] || a) + ' · ' + (m || T.dflt) + ' · ' + (e || T.dflt)).join(' / ');
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
    if (m < 1) return T.justNow;
    if (m < 60) return T.minAgo(m);
    if (m < 1440) return T.hourAgo(Math.round(m / 60));
    return new Date(t).toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en');
  }

  function fmtTokens(n) {
    if (n == null) return '—';
    return n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(1) + 'k' : String(n);
  }
  // 重置时间显示具体时刻：今天/明天 HH:MM，更远显示 M/D HH:MM。
  function fmtReset(epoch) {
    if (!epoch) return '';
    const t = new Date(epoch * 1000), now = new Date();
    if (t <= now) return T.resetDone;
    const hm = String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0');
    const day = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const diff = Math.round((day(t) - day(now)) / 86400000);
    const when = diff === 0 ? T.today : diff === 1 ? T.tomorrow : (t.getMonth() + 1) + '/' + t.getDate() + ' ';
    return T.resetPre + when + hm + T.reset;
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
    if (lim?.primary) box.append(limitRow(T.h5, lim.primary));
    if (lim?.secondary) box.append(limitRow(T.week, lim.secondary));
    const [agent] = run ? (settingsOf(run)[0] || []) : [];
    const u = run?.usage_summary?.[agent || data?.partner_agent];
    if (u) {
      const cached = u.cached_input_tokens && u.input_tokens ? T.cached(Math.round(u.cached_input_tokens / u.input_tokens * 100)) : '';
      box.append(el('div', 'tokens', T.turn + fmtTokens(u.input_tokens) + cached + T.out + fmtTokens(u.output_tokens) +
        (u.reasoning_output_tokens ? T.reasoning + fmtTokens(u.reasoning_output_tokens) : '')));
    }
    if (lim?.source === 'codex' && lim.observed_at) box.append(el('div', 'usage-note', T.limitNote + ago(lim.observed_at)));
    box.hidden = !box.children.length;
  }
  function renderNow() {
    if (!data) return;
    const runs = data.runs || [];
    const run = runs.find(r => r.state === 'running' || r.state === 'queued') || runs[0];
    const box = $('now');
    if (!run) {
      box.className = 'glass now idle';
      $('nowLabel').textContent = T.partner;
      $('nowState').textContent = T.idle;
      $('nowAgent').textContent = NAMES[data.partner_agent] || data.partner_agent;
      const auto = (pref.selection || 'auto') === 'auto';
      $('nowModel').textContent = auto ? T.autoPick : (pref.model || T.dflt);
      $('nowEffort').textContent = auto ? T.auto : (pref.effort || T.dflt);
      $('nowMeta').textContent = T.idleMeta;
      renderUsage(null);
      return;
    }
    const live = run.state === 'running' || run.state === 'queued';
    box.className = 'glass now ' + (live ? 'live' : run.state === 'failed' ? 'failed' : 'done');
    $('nowLabel').textContent = live ? T.calling : T.lastCall + ago(run.updated_at);
    $('nowState').textContent = (STATES[run.state] || run.state) + ' ' + elapsed(run);
    const [agent, model, effort] = settingsOf(run)[0] || [data.partner_agent, '', ''];
    $('nowAgent').textContent = NAMES[agent] || agent;
    $('nowModel').textContent = run.actual_model && run.actual_model !== model ? run.actual_model : (model || T.dflt);
    $('nowModel').title = run.actual_model ? T.requested + (model || T.dflt) + T.actual + run.actual_model : '';
    $('nowEffort').textContent = effort || T.dflt;
    $('nowMeta').textContent = [KINDS[run.kind] || run.kind, run.mode, run.state === 'failed' ? tr(run.error) : tr(run.route?.reason)]
      .filter(Boolean).join(' · ');
    renderUsage(run);
  }

  function renderRuns() {
    const list = $('runs'); list.replaceChildren();
    const runs = data.runs || [];
    $('count').textContent = runs.length ? T.count(runs.length) : '';
    if (!runs.length) { list.append(el('li', 'empty', T.noRuns)); return; }
    for (const run of runs) {
      const li = el('li', 'run ' + (run.state || ''));
      li.title = T.openRun;
      li.onclick = () => openDetail(run.run_id);
      li.append(el('span', 'dot'), el('span', 'what', describe(run) || (KINDS[run.kind] || T.collab)),
        el('span', 'dur', (run.state === 'completed' ? '' : (STATES[run.state] || run.state) + ' ') + elapsed(run)),
        el('span', 'sub', [KINDS[run.kind] || run.kind, run.mode, ago(run.updated_at), run.state === 'failed' ? tr(run.error) : ''].filter(Boolean).join(' · ')));
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
      if (model?.default_effort === v) b.title = T.modelDefault;
      return b;
    }));
    // 服务端说明只有中文；英文界面按来源自行组织。
    const note = lang === 'zh' ? data.partner.note : '';
    const src = note || (data.partner.verified ? T.from(data.partner.source || 'CLI') : T.alias);
    $('modelHint').textContent = T.models(data.partner.models.length) + src;
  }
  function currentEffort() {
    return $('efforts').querySelector('[aria-checked=true]')?.dataset.effort || '';
  }
  function setSelection(sel) {
    for (const b of document.querySelectorAll('#selMode button')) b.setAttribute('aria-checked', String(b.dataset.sel === sel));
    $('manual').hidden = sel !== 'manual';
    $('autoHint').hidden = sel === 'manual';
  }
  // Claude 当协作伙伴时，命令行未登录就提示登录方法（插件固定使用命令行登录的 Claude 账号）。
  function renderLogin() {
    const hint = $('loginHint');
    const login = data.claude_login;
    hint.hidden = !(data.partner_agent === 'claude' && login && !login.logged_in);
    if (hint.hidden) return;
    const btn = el('button', 'login-btn', T.login);
    btn.type = 'button';
    btn.onclick = async () => {
      btn.disabled = true;
      try { await api('claude-login', {}); btn.textContent = T.loginOpened; }
      catch (e) { showError(e); btn.disabled = false; }
    };
    hint.replaceChildren(T.loginHint, btn);
  }
  function renderSettings() {
    const models = data.partner.models;
    const known = models.some(m => m.id === pref.model);
    $('model').replaceChildren(
      ...models.map(m => new Option((m.label || m.id) + (m.default_effort ? '' : ''), m.id)),
      new Option(T.customModel, CUSTOM));
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
    $('access').textContent = T.primary(NAMES[next.primary_agent] || next.primary_agent);
    $('enabled').disabled = false;
    $('enabled').setAttribute('aria-checked', String(next.collaboration_enabled));
    $('enabled').title = next.collaboration_enabled ? T.autoOn : T.autoOff;
    if (!editing && !saving) renderSettings();
    renderRuns(); renderNow();
  }

  // 连接状态与保存提示都记状态键，换语言时按键重绘文字。
  let conn = 'connecting', saveState = '';
  function paintConn() {
    $('connection').className = 'conn' + (conn === 'connected' ? ' on' : conn === 'disconnected' ? ' off' : '');
    $('connection').textContent = T[conn];
  }
  function setSave(key) { saveState = key; $('saveStatus').textContent = key ? T[key] : ''; }
  async function refresh() {
    try { render(await api('state')); conn = 'connected'; showError(null); }
    catch (e) { conn = 'disconnected'; showError(e); }
    paintConn();
  }

  async function save() {
    if (!data) return;
    const sel = document.querySelector('#selMode [aria-checked=true]').dataset.sel;
    const body = {partner_selection: sel};
    if (sel === 'manual') {
      const model = currentModel();
      if (!model) { setSave('needModel'); return; }
      body.partner_model = model; body.partner_effort = currentEffort();
    }
    saving = true; setSave('saving');
    try { await api('preferences', body); setSave('saved'); editing = false; }
    catch (e) { showError(e); setSave('saveFailed'); }
    finally { saving = false; await refresh(); setTimeout(() => { if (saveState === 'saved') setSave(''); }, 1800); }
  }

  for (const b of document.querySelectorAll('#selMode button')) b.onclick = () => { setSelection(b.dataset.sel); save(); };
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
    $('detailAgent').textContent = (NAMES[agent] || agent || T.collab) + ' · ' + (d.run.actual_model || model || T.dflt) + ' · ' + (effort || T.dflt);
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
          const label = tail ? T.doing(trStep(g.steps[g.steps.length - 1])) : T.steps(g.steps.length);
          const sum = el('summary'); sum.append(el('span', '', label)); det.append(sum);
          const ol = el('ol'); for (const t of g.steps) ol.append(el('li', 'entry-step', trStep(t))); det.append(ol);
          if (opened.has(det.dataset.key)) det.open = true;
          li.append(det); box.append(li); return;
        }
        const li = el('li', 'entry-' + g.kind);
        if (g.kind === 'message') { li.classList.add('md'); li.innerHTML = markdown(g.text); }
        else if (g.kind === 'reasoning') {
          const det = el('details'); det.dataset.key = 'r' + idx; det.append(el('summary', '', T.thinking), el('div', '', g.text));
          if (opened.has(det.dataset.key)) det.open = true;
          li.append(det);
        } else li.textContent = g.text;
        box.append(li);
      });
      if (live) { const t = el('li', 'typing'); t.append(el('i'), el('i'), el('i')); box.append(t); }
      else if (!d.entries.length) box.append(el('li', 'empty', d.run.state === 'failed' ? (tr(d.run.error) || T.failedRun) : T.emptyRun));
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
    $('transcript').replaceChildren(el('li', 'empty', T.loading));
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
    for (const b of $('bgMenu').querySelectorAll('.bg-option')) b.setAttribute('aria-checked', String(b.dataset.bg === name));
    if (remember) { try { localStorage.setItem(BG_KEY, name); } catch {} }
  }
  const bgNames = window.AICoopBackground?.names || {system: ''};
  const langSwitch = el('div', 'lang-switch'); langSwitch.setAttribute('role', 'radiogroup'); langSwitch.setAttribute('aria-label', 'Language');
  for (const [key, label] of [['zh', '中文'], ['en', 'English']]) {
    const b = el('button', '', label); b.type = 'button'; b.dataset.lang = key; b.setAttribute('role', 'radio');
    b.onclick = () => { setLang(key); closeBgMenu(); };
    langSwitch.append(b);
  }
  $('bgMenu').replaceChildren(...Object.keys(bgNames).map(key => {
    const b = el('button', 'bg-option'); b.type = 'button'; b.dataset.bg = key; b.setAttribute('role', 'radio');
    b.append(el('i'), el('span'));
    b.onclick = () => { applyBackground(key); closeBgMenu(); };
    return b;
  }), langSwitch);
  // 静态文案用 data-i18n（文本）、data-i18n-title、data-i18n-aria、data-i18n-ph 标记键名。
  function applyStatic() {
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    for (const n of document.querySelectorAll('[data-i18n]')) n.textContent = T[n.dataset.i18n];
    for (const n of document.querySelectorAll('[data-i18n-title]')) n.title = T[n.dataset.i18nTitle];
    for (const n of document.querySelectorAll('[data-i18n-aria]')) n.setAttribute('aria-label', T[n.dataset.i18nAria]);
    for (const n of document.querySelectorAll('[data-i18n-ph]')) n.placeholder = T[n.dataset.i18nPh];
    for (const b of $('bgMenu').querySelectorAll('.bg-option')) b.lastChild.textContent = T.bg[b.dataset.bg] || bgNames[b.dataset.bg];
    for (const b of langSwitch.children) b.setAttribute('aria-checked', String(b.dataset.lang === lang));
  }
  function setLang(next) {
    lang = next; T = I18N[lang]; STATES = T.states; KINDS = T.kinds;
    try { localStorage.setItem(LANG_KEY, lang); } catch {}
    applyStatic(); paintConn(); setSave(saveState);
    if (data) {
      render(data);
      // 正在编辑时 render 不重建表单：只翻译文案，保留未保存的模型选择与自定义 ID。
      if (editing || saving) {
        const custom = $('model').querySelector('option[value="' + CUSTOM + '"]');
        if (custom) custom.textContent = T.customModel;
        renderEfforts(currentEffort()); renderLogin();
      }
    }
    if (detailId) { detailCount = -1; loadDetail(); }
  }
  applyStatic();
  // 外观菜单选完即收起；点菜单外或按 Esc 也收起。
  function closeBgMenu() { $('bgMenu').hidden = true; $('bgButton').setAttribute('aria-expanded', 'false'); }
  $('bgButton').onclick = () => {
    const open = $('bgMenu').hidden;
    $('bgMenu').hidden = !open; $('bgButton').setAttribute('aria-expanded', String(open));
  };
  addEventListener('click', e => { if (!$('bgMenu').hidden && !e.target.closest('#bgMenu, #bgButton')) closeBgMenu(); });
  addEventListener('keydown', e => { if (e.key === 'Escape') closeBgMenu(); });
  // 默认跟随 App 的浅色/深色；旧版的“纯色”并入“跟随 App”。
  let savedBg = 'system';
  try { savedBg = localStorage.getItem(BG_KEY) || 'system'; } catch {}
  const bgParam = hashParams.get('bg');
  if (bgNames[bgParam]) applyBackground(bgParam, false);  // 地址参数只影响本次打开，不改保存的偏好
  else applyBackground(bgNames[savedBg] ? savedBg : 'system');

  if (!token) { showError(new Error(T.noToken)); return; }
  refresh().then(() => { if (hashParams.get('run')) openDetail(hashParams.get('run')); });
  setInterval(() => { if (!saving) refresh(); }, 2000);
  setInterval(() => { renderNow(); renderDetailState(); }, 1000);
})();
