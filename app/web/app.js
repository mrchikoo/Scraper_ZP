/* Lead Outreach UI - vanilla JS, no dependencies. Talks to /api/* on the same origin. */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };
  var DEFAULT_SUBJECT = 'A quick idea to bring more customers to {{business_name}}';
  var DEFAULT_BODY = [
    'Hi {{business_name}} team,',
    '',
    'My name is {{my_name}} and I run {{my_business}}, a small marketing service.',
    '',
    'I came across your business online and had a few simple ideas that could help more local people find you and choose you, for example:',
    '',
    '- A tidier Google Maps listing with better photos and replies to reviews',
    '- Simple, regular Instagram and WhatsApp posts that bring in repeat customers',
    '- A small offer or campaign for your quiet days of the week',
    '',
    'I have attached a short PDF about my work. If any of this sounds useful, just reply to this email and I will share a free, no-obligation idea made for your business.',
    '',
    'Thank you for your time.',
    '',
    'Warm regards,',
    '{{my_name}}',
    '{{my_business}}',
    '{{my_phone}}',
    '{{my_website}}'
  ].join('\n');

  var S = null;            // settings from server
  var loaded = false;
  var hasPw = false;
  var smtpTested = null;   // null | true | false
  var areasMeta = { presets: [], business_types: [], city: '', country: '' };
  var leads = [];
  var logNext = 0;
  var lastState = 'idle';
  var online = true;
  var attachments = [];

  /* ---------- API ---------- */
  function api(method, path, body, isForm) {
    var opt = { method: method, headers: {} };
    if (body !== undefined) {
      if (isForm) { opt.body = body; }
      else { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
    }
    return fetch(path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok && !(j && j.message)) { throw new Error('HTTP ' + r.status); }
        setOnline(true);
        return j;
      });
    }, function (e) { setOnline(false); throw e; });
  }
  function setOnline(v) {
    if (v === online) return;
    online = v;
    $('offline').hidden = v;
    if (loaded) { if (v) showSave('', 'All changes saved'); else showSave('error', 'App not reachable'); }
  }

  /* ---------- helpers ---------- */
  function get(obj, path) { return path.split('.').reduce(function (o, k) { return o == null ? o : o[k]; }, obj); }
  function set(obj, path, val) {
    var k = path.split('.'), o = obj;
    for (var i = 0; i < k.length - 1; i++) { o[k[i]] = o[k[i]] || {}; o = o[k[i]]; }
    o[k[k.length - 1]] = val;
  }
  function debounce(fn, ms) { var t; var f = function () { var a = arguments; clearTimeout(t); t = setTimeout(function () { fn.apply(null, a); }, ms); }; f.cancel = function () { clearTimeout(t); }; return f; }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function icon(id, size) {
    var s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    s.setAttribute('width', size || 18); s.setAttribute('height', size || 18); s.setAttribute('aria-hidden', 'true');
    var u = document.createElementNS('http://www.w3.org/2000/svg', 'use'); u.setAttribute('href', '#' + id);
    s.appendChild(u); return s;
  }
  function fmtSize(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB'; }
  function friendlyErr() { return 'Could not reach the app. Please check it is still open and try again.'; }
  function busy(btn, on) { btn.classList.toggle('busy', on); btn.disabled = on; }

  /* ---------- save indicator + autosave ---------- */
  var saveSeq = 0;
  function showSave(state, text) {
    var s = $('saveState'); s.className = 'savestate ' + state; $('saveText').textContent = text;
  }
  var saveSoon = debounce(function () { saveNow(); }, 600);
  function queueSave() { if (!loaded) return; showSave('saving', 'Saving...'); saveSoon(); }

  function buildPayload() {
    var p = {
      profile: S.profile, email: { subject: S.email.subject, body: S.email.body },
      targeting: { city: S.targeting.city, country: S.targeting.country || '', business_types: S.targeting.business_types, areas: S.targeting.areas, segment: S.targeting.segment || 'any' },
      limits: S.limits, smtp: { email: S.smtp.email }
    };
    var pw = $('f-pass').value.trim();
    if (pw) p.smtp.app_password = pw;   // only if the user typed one
    return p;
  }
  function saveNow() {
    saveSoon.cancel();
    if (!loaded) return Promise.resolve(false);
    var my = ++saveSeq;
    var payload = buildPayload();
    showSave('saving', 'Saving...');
    return api('PUT', '/api/settings', payload).then(function (r) {
      if (my !== saveSeq) return r.ok !== false;
      showErrors(r.errors || {});
      var bad = r.errors && Object.keys(r.errors).length;
      if (r.ok === false || bad) { showSave('error', 'Please fix the highlighted items'); }
      else {
        showSave('', 'All changes saved');
        if (payload.smtp.app_password) { hasPw = true; $('f-pass').value = ''; smtpTested = null; setPwNote(); }
      }
      renderChecklist();
      return !bad && r.ok !== false;
    }, function () { showSave('error', 'Not saved - app not reachable'); return false; });
  }

  var ERR_MAP = { 'smtp.app_password': 'err-pass', 'targeting.areas': 'err-areas', 'targeting.business_types': 'err-types', 'email.attachments': 'err-file' };
  function showErrors(errors) {
    document.querySelectorAll('.field .err[data-auto]').forEach(function (e) { e.textContent = ''; });
    document.querySelectorAll('.invalid').forEach(function (e) { e.classList.remove('invalid'); e.removeAttribute('aria-invalid'); });
    ['err-pass', 'err-areas', 'err-types'].forEach(function (id) { $(id).textContent = ''; });
    Object.keys(errors).forEach(function (k) {
      var msg = errors[k], inp = document.querySelector('[data-field="' + k + '"]');
      if (!inp && k === 'smtp.app_password') inp = $('f-pass');
      if (!inp) { var tail = k.split('.').pop(); inp = document.querySelector('[data-field$=".' + tail + '"]'); }
      if (ERR_MAP[k]) { $(ERR_MAP[k]).textContent = msg; }
      else if (inp) {
        inp.classList.add('invalid'); inp.setAttribute('aria-invalid', 'true');
        var box = inp.closest('.field').querySelector('.err[data-auto]');
        if (box) box.textContent = msg;
      } else { $('err-run').textContent = msg; }
    });
  }

  /* ---------- bind plain fields ---------- */
  function bindFields() {
    document.querySelectorAll('[data-field]').forEach(function (inp) {
      var field = inp.closest('.field');
      var box = el('div', 'err'); box.setAttribute('data-auto', '1'); box.setAttribute('role', 'alert'); box.id = 'e-' + inp.id;
      field.appendChild(box); inp.setAttribute('aria-describedby', ((inp.getAttribute('aria-describedby') || '') + ' ' + box.id).trim());
      inp.addEventListener('input', function () {
        var v = inp.value;
        if (inp.dataset.num) { v = v === '' ? '' : Number(v); }
        set(S, inp.dataset.field, v);
        if (inp.dataset.field === 'smtp.email') smtpTested = null;
        queueSave(); renderChecklist();
        if (inp.dataset.field.indexOf('profile.') === 0 || inp.dataset.field.indexOf('email.') === 0) previewSoon();
      });
    });
    $('f-pass').addEventListener('input', function () { smtpTested = null; queueSave(); });
  }
  function fillFields() {
    document.querySelectorAll('[data-field]').forEach(function (inp) {
      var v = get(S, inp.dataset.field); inp.value = v == null ? '' : v;
    });
    setPwNote();
  }
  function setPwNote() {
    $('pwNote').textContent = hasPw ? 'Password saved. To change it, type a new one.' : '';
    $('f-pass').placeholder = hasPw ? 'Saved. Type here only to replace it' : '16-letter code from Google';
  }

  /* ---------- password show/hide ---------- */
  $('pwToggle').addEventListener('click', function () {
    var inp = $('f-pass'), show = inp.type === 'password';
    inp.type = show ? 'text' : 'password';
    this.setAttribute('aria-pressed', String(show));
    this.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });

  /* ---------- test connection ---------- */
  function showResult(id, ok, msg) { var r = $(id); r.className = 'result ' + (ok === null ? 'wait' : ok ? 'ok' : 'bad'); r.textContent = (ok === true ? 'Success: ' : '') + msg; }
  $('testSmtp').addEventListener('click', function () {
    var b = this;
    if (!S.smtp.email) { showResult('smtpResult', false, 'Please type your Gmail address first.'); $('f-email').focus(); return; }
    if (!hasPw && !$('f-pass').value.trim()) { showResult('smtpResult', false, 'Please paste your App Password first.'); $('f-pass').focus(); return; }
    busy(b, true); showResult('smtpResult', null, 'Checking with Gmail...');
    saveNow().then(function () { return api('POST', '/api/smtp/test'); }).then(function (r) {
      smtpTested = !!r.ok; showResult('smtpResult', !!r.ok, r.message || (r.ok ? 'Connected to Gmail.' : 'Could not connect.'));
      renderChecklist();
    }, function () { showResult('smtpResult', false, friendlyErr()); }).then(function () { busy(b, false); });
  });

  /* ---------- checklist ---------- */
  function renderChecklist() {
    if (!S) return;
    var p = S.profile || {}, e = S.email || {}, t = S.targeting || {};
    var items = [
      { id: 'sec-about', t: 'About you', ok: !!(p.full_name && p.business_name), s: 'Add your name and business name' },
      { id: 'sec-gmail', t: 'Gmail connection', ok: !!(S.smtp.email && hasPw), s: smtpTested === false ? 'Test failed. Check the code' : 'Add your Gmail and App Password' },
      { id: 'sec-email', t: 'Your email', ok: !!(e.subject && e.body), s: 'Write a subject and message' },
      { id: 'sec-target', t: 'Who to target', ok: !!(t.city && (t.areas || []).length && (t.business_types || []).length), s: 'Choose a city, then at least one area and business type' }
    ];
    var ol = $('checklist'); ol.textContent = '';
    var left = 0;
    items.forEach(function (it) {
      if (!it.ok) left++;
      var li = el('li', it.ok ? 'done' : ''), a = el('a'); a.href = '#' + it.id;
      var tick = el('span', 'tick'); tick.appendChild(icon('i-check', 14));
      var tx = el('span'); tx.appendChild(el('span', 't', it.t));
      var sm = el('small', '', it.ok ? (it.id === 'sec-gmail' && smtpTested ? 'Connected and tested' : 'Done') : it.s); tx.appendChild(sm);
      a.appendChild(tick); a.appendChild(tx); li.appendChild(a); ol.appendChild(li);
    });
    $('progressSummary').textContent = left === 0
      ? 'All set. You are ready to press Start in step 5.'
      : (left === 1 ? '1 step left before you can start.' : left + ' steps left before you can start.');
  }

  /* ---------- email editor ---------- */
  var body = $('f-body');
  document.querySelectorAll('.chip').forEach(function (c) {
    c.addEventListener('click', function () {
      var tag = '{{' + c.dataset.ph + '}}', s = body.selectionStart, e = body.selectionEnd;
      if (s == null) { s = e = body.value.length; }
      body.value = body.value.slice(0, s) + tag + body.value.slice(e);
      var pos = s + tag.length; body.focus(); body.setSelectionRange(pos, pos);
      body.dispatchEvent(new Event('input', { bubbles: true }));
    });
  });
  $('resetTpl').addEventListener('click', function () {
    if (body.value.trim() && !window.confirm('Replace your current subject and message with the sample email?')) return;
    $('f-subj').value = DEFAULT_SUBJECT; body.value = DEFAULT_BODY;
    $('f-subj').dispatchEvent(new Event('input', { bubbles: true })); body.dispatchEvent(new Event('input', { bubbles: true }));
  });

  var pvSeq = 0;
  var previewSoon = debounce(doPreview, 500);
  function doPreview() {
    if (!S) return;
    var my = ++pvSeq;
    api('POST', '/api/email/preview', { subject: S.email.subject || '', body: S.email.body || '', business_name: 'Sunrise Cafe' }).then(function (r) {
      if (my !== pvSeq) return;
      $('pvSubject').textContent = r.subject || '(no subject yet)';
      $('pvBody').textContent = r.text || '(write your message above to see it here)';
    }, function () { /* offline banner already shown */ });
  }

  /* ---------- attachments ---------- */
  function loadAttachments() {
    return api('GET', '/api/attachments').then(function (r) { attachments = Array.isArray(r) ? r : []; renderAttachments(); }, function () {});
  }
  function renderAttachments() {
    var ul = $('fileList'); ul.textContent = '';
    attachments.forEach(function (f) {
      var li = el('li'); li.appendChild(icon('i-file', 20));
      li.appendChild(el('span', 'nm', f.name)); li.appendChild(el('span', 'sz', fmtSize(f.size || 0)));
      var x = el('button', 'x'); x.type = 'button'; x.setAttribute('aria-label', 'Remove ' + f.name); x.appendChild(icon('i-x', 18));
      x.addEventListener('click', function () {
        api('DELETE', '/api/attachments/' + encodeURIComponent(f.name)).then(loadAttachments, function () { $('err-file').textContent = friendlyErr(); });
      });
      li.appendChild(x); ul.appendChild(li);
    });
    $('pvFiles').textContent = attachments.length ? 'Attached: ' + attachments.map(function (f) { return f.name; }).join(', ') : '';
  }
  function upload(file) {
    $('err-file').textContent = '';
    if (!/\.pdf$/i.test(file.name)) { $('err-file').textContent = 'Only PDF files can be attached. Please choose a .pdf file.'; return; }
    if (file.size > 10 * 1048576) { $('err-file').textContent = 'That file is bigger than 10 MB. Please use a smaller PDF.'; return; }
    var fd = new FormData(); fd.append('file', file);
    api('POST', '/api/attachments', fd, true).then(function (r) {
      if (r.ok === false) $('err-file').textContent = r.message || 'Could not add that file.';
      return loadAttachments();
    }, function () { $('err-file').textContent = friendlyErr(); });
  }
  var drop = $('drop'), fin = $('fileInput');
  drop.addEventListener('click', function () { fin.click(); });
  drop.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fin.click(); } });
  fin.addEventListener('change', function () { if (fin.files[0]) upload(fin.files[0]); fin.value = ''; });
  ['dragenter', 'dragover'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.add('over'); }); });
  ['dragleave', 'drop'].forEach(function (n) { drop.addEventListener(n, function (e) { e.preventDefault(); drop.classList.remove('over'); }); });
  drop.addEventListener('drop', function (e) { var f = e.dataTransfer.files[0]; if (f) upload(f); });
  window.addEventListener('dragover', function (e) { e.preventDefault(); });
  window.addEventListener('drop', function (e) { e.preventDefault(); });

  $('testSend').addEventListener('click', function () {
    var b = this;
    busy(b, true); showResult('testResult', null, 'Sending...');
    saveNow().then(function () { return api('POST', '/api/email/test-send'); }).then(function (r) {
      showResult('testResult', !!r.ok, r.message || (r.ok ? 'Sent. Please check your inbox.' : 'Could not send.'));
    }, function () { showResult('testResult', false, friendlyErr()); }).then(function () { busy(b, false); });
  });

  /* ---------- targeting ---------- */
  function renderTypes() {
    var box = $('typeList'); box.textContent = '';
    areasMeta.business_types.forEach(function (t) {
      var lb = el('label', 'check'), cb = el('input'); cb.type = 'checkbox'; cb.value = t.key;
      cb.checked = S.targeting.business_types.indexOf(t.key) > -1;
      cb.addEventListener('change', function () { toggle(S.targeting.business_types, t.key, cb.checked); $('err-types').textContent = ''; queueSave(); renderChecklist(); });
      lb.appendChild(cb); lb.appendChild(document.createTextNode(t.label)); box.appendChild(lb);
    });
    var known = areasMeta.business_types.map(function (t) { return t.key; });
    S.targeting.business_types.forEach(function (key) {
      if (known.indexOf(key) > -1) return;
      var lb = el('label', 'check'), cb = el('input'); cb.type = 'checkbox'; cb.value = key; cb.checked = true;
      cb.addEventListener('change', function () {
        if (!cb.checked) { toggle(S.targeting.business_types, key, false); renderTypes(); }
        queueSave(); renderChecklist();
      });
      lb.appendChild(cb); lb.appendChild(document.createTextNode(key + ' (your niche)')); box.appendChild(lb);
    });
  }
  function addNiche() {
    var v = $('nicheInput').value.trim().replace(/\s+/g, ' ').slice(0, 60);
    if (!v) return;
    toggle(S.targeting.business_types, v, true);
    $('nicheInput').value = ''; $('err-types').textContent = '';
    renderTypes(); queueSave(); renderChecklist();
  }
  $('nicheAdd').addEventListener('click', addNiche);
  $('nicheInput').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); addNiche(); } });
  function renderSegment() {
    var cur = S.targeting.segment || 'any';
    document.querySelectorAll('input[name=segment]').forEach(function (r) {
      r.checked = r.value === cur;
      r.onchange = function () { if (r.checked) { S.targeting.segment = r.value; queueSave(); } };
    });
  }
  function toggle(arr, v, on) { var i = arr.indexOf(v); if (on && i < 0) arr.push(v); if (!on && i > -1) arr.splice(i, 1); }
  // The list shown is the looked-up areas plus any area the user added by hand (kept across reloads).
  function allAreas() {
    var names = areasMeta.presets.map(function (a) { return a.name; });
    var extra = S.targeting.areas.filter(function (n) { return names.indexOf(n) < 0; }).map(function (n) { return { name: n }; });
    return areasMeta.presets.concat(extra);
  }
  function renderAreas() {
    var q = $('areaSearch').value.trim().toLowerCase(), box = $('areaList'); box.textContent = '';
    var list = allAreas();
    $('areaBox').hidden = !S.targeting.city;
    $('cityName').textContent = S.targeting.city || '';
    var shown = list.filter(function (a) { return !q || a.name.toLowerCase().indexOf(q) > -1; });
    shown.forEach(function (a) {
      var lb = el('label', 'check'), cb = el('input'); cb.type = 'checkbox';
      cb.checked = S.targeting.areas.indexOf(a.name) > -1;
      cb.addEventListener('change', function () { toggle(S.targeting.areas, a.name, cb.checked); $('err-areas').textContent = ''; updAreaCount(); queueSave(); renderChecklist(); });
      lb.appendChild(cb); lb.appendChild(document.createTextNode(a.name)); box.appendChild(lb);
    });
    if (!shown.length) box.appendChild(el('p', 'muted', list.length ? 'No areas match your search.' : 'No areas were listed for this place. Type an area name below and press Add.'));
    updAreaCount();
  }
  function updAreaCount() { $('areaCount').textContent = '(' + S.targeting.areas.length + ' of ' + allAreas().length + ' picked)'; }
  function findAreas() {
    var typed = $('cityInput').value.trim(), btn = $('cityFind'), st = $('cityStatus');
    if (!typed) { st.textContent = 'Please type a city or region first, for example "Pune".'; return; }
    busy(btn, true); st.textContent = 'Looking up areas in ' + typed + '...';
    api('GET', '/api/areas?city=' + encodeURIComponent(typed)).then(function (res) {
      if (res.error && !res.offline) { st.textContent = res.error; return; }   // place not found: change nothing
      var changed = (S.targeting.city || '').toLowerCase() !== (res.city || '').toLowerCase();
      if (changed) S.targeting.areas = [];   // areas from another place no longer apply
      S.targeting.city = res.city; S.targeting.country = res.country || '';
      areasMeta.presets = res.presets || []; areasMeta.city = res.city; areasMeta.country = res.country || '';
      $('cityInput').value = res.city; $('areaSearch').value = '';
      st.textContent = res.presets && res.presets.length
        ? 'Found ' + res.presets.length + ' areas in ' + res.city + (res.source === 'builtin' ? ' (offline list).' : '.') + ' Pick the ones you want.'
        : (res.error || 'I could not list areas for ' + res.city + '. You can add areas by name below.');
      renderAreas(); renderChecklist(); queueSave();
    }).catch(function () { st.textContent = 'Something went wrong while looking up areas. Please try again.'; }).then(function () { busy(btn, false); });
  }
  $('cityFind').addEventListener('click', findAreas);
  $('cityInput').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); findAreas(); } });
  function addCustomArea() {
    var v = $('areaCustom').value.trim(); if (!v) return;
    toggle(S.targeting.areas, v, true); $('areaCustom').value = ''; $('err-areas').textContent = '';
    renderAreas(); queueSave(); renderChecklist();
  }
  $('areaAdd').addEventListener('click', addCustomArea);
  $('areaCustom').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); addCustomArea(); } });
  $('areaSearch').addEventListener('input', renderAreas);
  function bulk(on) {
    var q = $('areaSearch').value.trim().toLowerCase();
    allAreas().forEach(function (a) { if (!q || a.name.toLowerCase().indexOf(q) > -1) toggle(S.targeting.areas, a.name, on); });
    renderAreas(); queueSave(); renderChecklist();
  }
  $('areaAll').addEventListener('click', function () { bulk(true); });
  $('areaNone').addEventListener('click', function () { bulk(false); });

  /* ---------- run ---------- */
  var modeLabels = { scrape: 'Finding businesses', send: 'Sending emails', both: 'Finding businesses and sending emails' };
  function pollStatus() {
    return api('GET', '/api/run/status').then(function (s) {
      renderStatus(s);
      if (s.state === 'running' || s.state === 'stopping' || lastState !== s.state) loadLeads();
      lastState = s.state;
    }, function () {});
  }
  function renderStatus(s) {
    var run = s.state === 'running', stop = s.state === 'stopping';
    var pill = $('statePill');
    pill.className = 'pill' + (run ? ' running' : stop ? ' stopping' : '');
    pill.textContent = run ? 'Running' : stop ? 'Stopping' : 'Ready';
    var t = run ? (modeLabels[s.mode] || 'Working') + (s.current_area ? ': ' + s.current_area : '...') :
            stop ? 'Finishing the current step, then stopping...' :
            (s.last_error ? 'Last run stopped: ' + s.last_error : 'Press Start when you are ready.');
    if (!run && !stop && s.last_error) pill.className = 'pill error';
    $('stateText').textContent = t;
    $('startBtn').disabled = run || stop; $('stopBtn').disabled = !(run);
    document.querySelectorAll('input[name=mode]').forEach(function (r) { r.disabled = run || stop; });
    var tot = s.areas_total || 0, dn = s.areas_done || 0, pct = tot ? Math.min(100, Math.round(dn / tot * 100)) : 0;
    $('progNum').textContent = dn + ' of ' + tot; $('progFill').style.width = pct + '%'; $('progBar').setAttribute('aria-valuenow', pct);
    $('stFound').textContent = s.leads_found || 0; $('stSent').textContent = s.sent_total || 0;
    var cap = s.daily_cap || (S && S.limits && S.limits.max_per_day) || 100, today = s.sent_today || 0, dp = Math.min(100, Math.round(today / cap * 100));
    $('stToday').textContent = today; $('stCap').textContent = cap;
    $('dayFill').style.width = dp + '%'; $('dayBar').setAttribute('aria-valuenow', dp); $('dayBar').classList.toggle('warnbar', dp >= 90);
    if (s.mode && !run && !stop) {} 
  }
  var logBox = $('log');
  function pollLogs() {
    return api('GET', '/api/run/logs?since=' + logNext).then(function (r) {
      if (typeof r.next === 'number') {
        if (r.next < logNext) { logBox.textContent = ''; }   // server restarted
        logNext = r.next;
      }
      if (!r.lines || !r.lines.length) return;
      if (logBox.querySelector('.muted')) logBox.textContent = '';
      var atEnd = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 40;
      r.lines.forEach(function (l) { logBox.appendChild(el('p', '', l)); });
      while (logBox.childNodes.length > 500) logBox.removeChild(logBox.firstChild);
      if (atEnd) logBox.scrollTop = logBox.scrollHeight;
    }, function () {});
  }
  $('startBtn').addEventListener('click', function () {
    var b = this, mode = document.querySelector('input[name=mode]:checked').value;
    $('err-run').textContent = ''; busy(b, true);
    saveNow().then(function () { return api('POST', '/api/run/start', { mode: mode }); }).then(function (r) {
      if (r.ok === false) $('err-run').textContent = r.message || 'Could not start. Please check the steps above.';
      return pollStatus();
    }, function () { $('err-run').textContent = friendlyErr(); }).then(function () { b.classList.remove('busy'); pollLogs(); });
  });
  $('stopBtn').addEventListener('click', function () {
    api('POST', '/api/run/stop').then(pollStatus, function () { $('err-run').textContent = friendlyErr(); });
  });

  /* ---------- results ---------- */
  var statusLabel = { 'new': 'Not emailed yet', sent: 'Sent', failed: 'Failed', excluded: "Don't email" };
  function loadLeads() {
    return api('GET', '/api/leads').then(function (r) { leads = Array.isArray(r) ? r : []; renderLeads(); }, function () {});
  }
  function renderLeads() {
    var f = $('resFilter').value, q = $('resSearch').value.trim().toLowerCase(), tb = $('resBody'); tb.textContent = '';
    var rows = leads.filter(function (l) {
      return (f === 'all' || l.status === f) && (!q || [l.business_name, l.email, l.area, l.website].join(' ').toLowerCase().indexOf(q) > -1);
    });
    $('resCount').textContent = leads.length ? 'Showing ' + rows.length + ' of ' + leads.length + (leads.length === 1 ? ' business.' : ' businesses.') : '';
    if (!rows.length) {
      var tr = el('tr', 'empty'), td = el('td', '', leads.length ? 'Nothing matches your filter.' : 'No businesses yet. Press Start in step 5 to find some.'); td.colSpan = 5; tr.appendChild(td); tb.appendChild(tr); return;
    }
    rows.forEach(function (l) {
      var tr = el('tr');
      var n = el('td'); n.appendChild(el('div', '', l.business_name || '(no name)'));
      if (l.website) { var w = el('div', 'small muted', l.website); n.appendChild(w); }
      tr.appendChild(n);
      tr.appendChild(el('td', 'em', l.email)); tr.appendChild(el('td', '', l.area || ''));
      var st = el('td'), bd = el('span', 'badge b-' + l.status, statusLabel[l.status] || l.status);
      st.appendChild(bd);
      if (l.status === 'sent' && l.sent_at) st.appendChild(el('div', 'small muted', l.sent_at.replace('T', ' ').slice(0, 16)));
      tr.appendChild(st);
      var ac = el('td');
      if (l.status !== 'excluded') {
        var b = el('button', 'mini', "Don't email"); b.type = 'button'; b.setAttribute('aria-label', "Don't email " + l.email);
        b.addEventListener('click', function () {
          api('POST', '/api/leads/exclude', { email: l.email }).then(loadLeads, function () { $('resCount').textContent = friendlyErr(); });
        });
        ac.appendChild(b);
      }
      tr.appendChild(ac); tb.appendChild(tr);
    });
  }
  $('resFilter').addEventListener('change', renderLeads);
  $('resSearch').addEventListener('input', renderLeads);
  $('resRefresh').addEventListener('click', loadLeads);

  /* ---------- boot ---------- */
  function normalise(s) {
    s = s || {};
    s.profile = Object.assign({ full_name: '', business_name: '', phone: '', website: '', services: '' }, s.profile);
    s.smtp = Object.assign({ email: '' }, s.smtp); delete s.smtp.app_password;
    s.email = Object.assign({ subject: '', body: '', attachments: [] }, s.email);
    s.targeting = Object.assign({ city: '', country: '', business_types: [], areas: [] }, s.targeting);
    s.targeting.business_types = s.targeting.business_types || []; s.targeting.areas = s.targeting.areas || [];
    s.limits = Object.assign({ max_per_day: 100 }, s.limits);
    return s;
  }
  var timers = false;
  function boot() {
    return Promise.all([api('GET', '/api/settings'), api('GET', '/api/areas'), api('GET', '/api/health').catch(function () { return {}; })]).then(function (res) {
      S = normalise(res[0]); hasPw = !!(res[0].smtp && res[0].smtp.has_app_password);
      areasMeta = Object.assign(areasMeta, res[1]);
      if (res[2].version) $('verText').textContent = 'Version ' + res[2].version + '.';
      if (res[2].chrome_found === false) { $('err-run').textContent = 'Google Chrome was not found on this computer. Finding businesses needs Chrome, so please install it first.'; }
      $('cityInput').value = S.targeting.city || '';
      var seeded = false;
      if (!S.email.body.trim()) { S.email.body = DEFAULT_BODY; seeded = true; }
      if (!S.email.subject.trim()) { S.email.subject = DEFAULT_SUBJECT; seeded = true; }
      fillFields(); renderTypes(); renderSegment(); renderAreas(); renderChecklist();
      loaded = true;
      if (seeded) saveNow();
      doPreview(); loadAttachments(); loadLeads(); pollStatus(); pollLogs();
      if (!timers) { timers = true; setInterval(function () { pollStatus(); pollLogs(); }, 2000); }
      if (!online) setOnline(true);
    });
  }
  function start() {
    boot().catch(function () { setOnline(false); });
  }
  bindFields();
  $('retryBtn').addEventListener('click', function () { var b = this; busy(b, true); boot().catch(function () { setOnline(false); }).then(function () { busy(b, false); }); });
  // while offline and not loaded, keep retrying quietly
  setInterval(function () { if (!loaded) start(); else if (!online) pollStatus(); }, 5000);
  start();
})();
