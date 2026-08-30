(function () {
  'use strict';
  function init() {
  var BRIEF = document.body.dataset.briefId || location.pathname;
  var isMac = /Mac|iP(hone|ad|od)/.test(navigator.platform || navigator.userAgent);
  var MOD = isMac ? '\u2318' : 'Ctrl-';
  /* Stroke SVGs rather than glyphs: the old \u21F2 / \u2194 pair for width read as
     "resize window", not "narrow column vs full bleed". Rails + arrows say it. */
  function svg(body) {
    return '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
      'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + '</svg>';
  }
  var ICON = {
    goFull: svg('<path d="M2.5 4v16"/><path d="M21.5 4v16"/><path d="M10 12H5.5"/><path d="m8 9-3 3 3 3"/><path d="M14 12h4.5"/><path d="m16 9 3 3-3 3"/>'),
    goFixed: svg('<path d="M2.5 4v16"/><path d="M21.5 4v16"/><path d="M5.5 12H10"/><path d="m7.5 9 3 3-3 3"/><path d="M18.5 12H14"/><path d="m16.5 9-3 3 3 3"/>'),
    auto: svg('<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 0 0 16Z" fill="currentColor" stroke="none"/>'),
    light: svg('<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2"/><path d="M12 19.5v2"/><path d="M2.5 12h2"/><path d="M19.5 12h2"/><path d="m5.3 5.3 1.4 1.4"/><path d="m17.3 17.3 1.4 1.4"/><path d="m18.7 5.3-1.4 1.4"/><path d="m6.7 17.3-1.4 1.4"/>'),
    dark: svg('<path d="M20.5 14.3A8.6 8.6 0 0 1 9.7 3.5a8.6 8.6 0 1 0 10.8 10.8Z"/>'),
    comment: svg('<path d="M20.5 11.8a7.8 7.8 0 0 1-7.8 7.8H8.4L4 22.3v-4.6a7.8 7.8 0 0 1-.5-2.7v-3.2A7.8 7.8 0 0 1 11.3 4h1.4a7.8 7.8 0 0 1 7.8 7.8Z"/>'),
    copy: svg('<rect x="9" y="9" width="11.5" height="11.5" rx="2.2"/><path d="M15.5 5.6A2.2 2.2 0 0 0 13.4 3.5H5.7a2.2 2.2 0 0 0-2.2 2.2v7.7a2.2 2.2 0 0 0 2.1 2.1"/>'),
    download: svg('<path d="M12 3.5v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M4 20.5h16"/>')
  };
  /* No title-attribute tooltips: they are slow, unstyleable and invisible to
     touch. data-tip renders through CSS, and carries the keyboard shortcut. */
  function tip(el, text, key) {
    if (!el) return;
    el.setAttribute('data-tip', text + (key ? '  \u00b7  ' + key : ''));
    el.setAttribute('aria-label', text + (key ? ' (' + key + ')' : ''));
  }
  /* bootstrap chrome if the page didn't include it */
  if (!document.querySelector('.topbar')) {
    var tb = document.createElement('div');
    tb.className = 'topbar';
    tb.innerHTML = '<h1></h1><a class="progress" id="progress"></a>' +
      '<button class="btn icon" id="cmtBtn" type="button"></button>' +
      '<button class="btn icon" id="widthBtn" type="button"></button>' +
      '<button class="btn icon" id="themeBtn" type="button"></button>' +
      '<span class="btncombo">' +
      '<button class="btn icon" id="copyBtn" type="button"></button>' +
      '<button class="btn icon" id="downloadBtn" type="button"></button>' +
      '</span>';
    tb.querySelector('h1').textContent = document.title;
    document.body.insertBefore(tb, document.body.firstChild);
  }
  /* ── shared UI prefs: theme (system/light/dark) + width (fixed/full) ── */
  var ui = { theme: 'auto', width: 'fixed', rate: 1 };
  try { ui = Object.assign(ui, JSON.parse(localStorage.getItem('briefUI') || '{}')); } catch {}
  var THEMES = ['auto', 'light', 'dark'];
  var TICON = { auto: '\u25D0', light: '\u2600\uFE0E', dark: '\u263E' };
  var TLABEL = { auto: 'Theme: system', light: 'Theme: light', dark: 'Theme: dark' };
  function applyUI() {
    if (ui.theme === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', ui.theme);
    document.body.classList.toggle('fullwidth', ui.width === 'full');
    var tbn = document.getElementById('themeBtn'), wbn = document.getElementById('widthBtn');
    if (tbn) {
      tbn.innerHTML = ICON[ui.theme === 'auto' ? 'auto' : ui.theme];
      tip(tbn, TLABEL[ui.theme] + ' \u2014 click to switch');
    }
    if (wbn) {
      /* The icon shows what the click DOES, not the current state: an arrow set
         pointing outward means "widen", inward means "narrow back". */
      wbn.innerHTML = ui.width === 'full' ? ICON.goFixed : ICON.goFull;
      tip(wbn, ui.width === 'full' ? 'Narrow to fixed width' : 'Expand to full width');
    }
    localStorage.setItem('briefUI', JSON.stringify(ui));
  }
  var themeBtn = document.getElementById('themeBtn');
  if (themeBtn) themeBtn.addEventListener('click', function () {
    ui.theme = THEMES[(THEMES.indexOf(ui.theme) + 1) % THEMES.length]; applyUI();
  });
  var widthBtn = document.getElementById('widthBtn');
  if (widthBtn) widthBtn.addEventListener('click', function () {
    ui.width = ui.width === 'full' ? 'fixed' : 'full'; applyUI();
  });
  /* ── playback speed, only on briefs that actually carry audio/video ──
     One control for every player on the page: a review deck of 40 clips is
     unlistenable if each one needs its own speed set. */
  var MEDIA_RATES = [1, 1.5, 2];
  function applyRate() {
    var r = MEDIA_RATES.indexOf(ui.rate) < 0 ? 1 : ui.rate;
    ui.rate = r;
    document.querySelectorAll('audio, video').forEach(function (m) { m.playbackRate = r; });
    var b = document.getElementById('rateBtn');
    if (b) {
      b.textContent = r + '×';
      b.setAttribute('aria-label', 'Playback speed ' + r + '× — click to change');
    }
    localStorage.setItem('briefUI', JSON.stringify(ui));
  }
  if (document.querySelector('audio, video')) {
    var rb = document.createElement('button');
    rb.className = 'btn icon'; rb.id = 'rateBtn'; rb.type = 'button';
    var anchor = document.getElementById('widthBtn') || document.getElementById('themeBtn');
    if (anchor) anchor.parentNode.insertBefore(rb, anchor);
    rb.addEventListener('click', function () {
      ui.rate = MEDIA_RATES[(MEDIA_RATES.indexOf(ui.rate) + 1) % MEDIA_RATES.length];
      applyRate();
    });
    /* A player created or loaded later must not silently revert to 1x. */
    document.addEventListener('play', function (e) {
      if (e.target.playbackRate !== ui.rate) e.target.playbackRate = ui.rate;
    }, true);
    applyRate();
  }
  applyUI();
  if (!document.getElementById('toast')) {
    var t0 = document.createElement('div');
    t0.id = 'toast'; t0.setAttribute('role', 'status');
    document.body.appendChild(t0);
  }
  if (!document.getElementById('briefMain')) {
    var m = document.querySelector('main');
    if (m) m.id = 'briefMain';
  }
  var KEY = 'brief:' + BRIEF;
  var state = { ticks: {}, answers: {}, notes: {}, comments: [], drafts: [] };
  if (!state.notes) state.notes = {};
  try { state = Object.assign(state, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch {}
  if (!Array.isArray(state.drafts)) state.drafts = [];
  if (!Array.isArray(state.comments)) state.comments = [];
  function save() { localStorage.setItem(KEY, JSON.stringify(state)); }
  function toast(msg) {
    var t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove('show'); }, 1800);
  }


  /* ── comments the author has already addressed ──
     A regenerated brief can declare which comments it has acted on, so the
     reader is not asked to carry them back a second time. Put on <body>:

         data-addressed="first 40 chars of a comment||another one"

     Matching is on a normalised prefix of the comment text, because the comment
     itself is the only stable identifier: it lives in the reader's
     localStorage, not in the file, so the file cannot carry an id it never saw.
     A resolved comment stays visible and readable, greyed, and is dropped from
     the exported JSON. Nothing is deleted: the reader can untick it. */
  function addrKey(x) { return (x || '').replace(/\s+/g, ' ').trim().toLowerCase().slice(0, 40); }
  var ADDRESSED = (document.body.dataset.addressed || '')
    .split('||').map(addrKey).filter(Boolean);
  function isAddressed(c) {
    var n = addrKey(c.comment);
    return ADDRESSED.some(function (a) { return n.indexOf(a) === 0 || a.indexOf(n) === 0; });
  }
  state.comments.forEach(function (c) {
    if (c.resolved === undefined && isAddressed(c)) c.resolved = true;
  });
  save();

  /* Paint the strike-through once the marks exist. Runs after init rather than
     inside it, because a mark is created when its text is found in the DOM and
     that happens later in this file. */
  function paintResolved() {
    state.comments.forEach(function (c) {
      if (!c.resolved) return;
      Array.prototype.forEach.call(
        document.querySelectorAll('mark.cmt[data-cid="' + c.cid + '"]'),
        function (m) { m.classList.add('resolved'); m.title = 'Addressed — not sent again'; });
    });
  }
  setTimeout(paintResolved, 0);

  /* ── free-standing note fields ──
     Any <textarea data-note="key"> persists under state.notes[key] and is
     exported in the JSON. Unlike the per-question answer boxes these are not
     tied to a section.q, so a brief can put a note box under each audio sample,
     table row, or mockup without inventing a question for every one of them. */
  Array.prototype.forEach.call(document.querySelectorAll('textarea[data-note]'), function (ta) {
    var k = ta.dataset.note;
    if (state.notes[k]) ta.value = state.notes[k];
    ta.addEventListener('input', function () {
      if (ta.value.trim()) state.notes[k] = ta.value; else delete state.notes[k];
      save();
    });
  });

  /* ── ticks (questions + sections) ── */
  var sections = Array.prototype.slice.call(document.querySelectorAll('section.q, section.brief-section'));
  function idOf(sec) { return sec.dataset.q || 'sec:' + sec.dataset.sec; }
  sections.forEach(function (sec) {
    var box = sec.querySelector('.tick input');
    if (!box) return;
    if (state.ticks[idOf(sec)]) { box.checked = true; sec.classList.add('done'); }
    box.addEventListener('change', function () {
      sec.classList.toggle('done', box.checked);
      state.ticks[idOf(sec)] = box.checked; save(); renderProgress();
    });
  });
  /* A question counts as resolved once it has an answer typed into it, OR it has
     been ticked. Typing an answer IS resolving it — requiring a separate tick made
     the counter read 0/4 on a brief whose four answers had already been sent back,
     which is worse than useless. The tick stays meaningful on its own: it's how you
     resolve a question by accepting the stated assumption without typing anything. */
  function answered(qid) { return !!(state.answers[qid] || '').trim(); }
  function resolved(qid) { return !!state.ticks[qid] || answered(qid); }

  /* The progress counter doubles as a jump-link to the next unresolved question,
     so a long brief never has to be scrolled to find what's still outstanding. */
  function renderProgress() {
    var qs = sections.filter(function (s) { return s.dataset.q; });
    var done = qs.filter(function (s) { return resolved(s.dataset.q); }).length;
    var el = document.getElementById('progress');
    if (!el) return;
    var next = qs.find(function (s) { return !resolved(s.dataset.q); });
    el.textContent = done + '/' + qs.length + ' questions resolved';
    if (next) {
      el.setAttribute('href', '#' + (next.id || (next.id = 'q-' + next.dataset.q)));
      el.setAttribute('title', 'Jump to ' + next.dataset.q + ' — next unresolved');
      el.setAttribute('aria-label', done + ' of ' + qs.length +
        ' questions resolved. Jump to ' + next.dataset.q + ', the next unresolved question.');
      el.classList.remove('all-done');
    } else {
      el.removeAttribute('href');
      el.removeAttribute('title');
      el.setAttribute('aria-label', 'All ' + qs.length + ' questions resolved');
      el.classList.add('all-done');
    }
  }

  /* ── answers ── */
  /* Auto-inject a Response textarea into every question that lacks one, so an
     author can never ship a question with no way to answer it. */
  sections.forEach(function (sec) {
    if (!sec.dataset.q) return;
    if (sec.querySelector('textarea.answer')) return;
    var body = sec.querySelector('.q-body') || sec;
    var wrap = document.createElement('div');
    wrap.className = 'answerwrap';
    var qid = sec.dataset.q;
    var lbl = document.createElement('label');
    lbl.setAttribute('for', 'ans-' + qid);
    lbl.textContent = 'Your answer';
    var ta = document.createElement('textarea');
    ta.className = 'answer';
    ta.id = 'ans-' + qid;
    ta.setAttribute('placeholder', 'Type answer — saved locally as you type');
    wrap.appendChild(lbl); wrap.appendChild(ta);
    body.appendChild(wrap);
  });
  document.querySelectorAll('textarea.answer').forEach(function (ta) {
    var q = ta.closest('section.q'); if (!q) return;
    var qid = q.dataset.q;
    if (state.answers[qid]) ta.value = state.answers[qid];
    ta.addEventListener('input', function () {
      var was = answered(qid);
      state.answers[qid] = ta.value; clearTimeout(ta._h);
      ta._h = setTimeout(save, 250);
      /* Only re-render when the answered/empty state actually flips, so the
         counter tracks typing live without doing work on every keystroke. */
      if (answered(qid) !== was) renderProgress();
    });
  });

  /* ── responses JSON ── */
  function responsesJSON() {
    var out = { brief: BRIEF, title: document.title, exported: new Date().toISOString(), answers: [], comments: [] };
    sections.forEach(function (sec) {
      if (!sec.dataset.q) return;
      var h = sec.querySelector('.q-head h2');
      /* `resolved` matches the on-screen counter: answered OR ticked. `ticked` is
         reported separately so an explicit "assumption accepted, nothing to add"
         (ticked, no answer) stays distinguishable from a typed reply. */
      out.answers.push({
        id: sec.dataset.q,
        question: h ? h.textContent.replace(/\s+/g, ' ').trim() : sec.dataset.q,
        resolved: resolved(sec.dataset.q),
        ticked: !!state.ticks[sec.dataset.q],
        answer: state.answers[sec.dataset.q] || ''
      });
    });
    out.notes = [];
    Array.prototype.forEach.call(document.querySelectorAll('textarea[data-note]'), function (ta) {
      var k = ta.dataset.note;
      if (state.notes[k]) {
        out.notes.push({ id: k, label: ta.dataset.noteLabel || ta.getAttribute('aria-label') || k,
                         note: state.notes[k] });
      }
    });
    state.comments.forEach(function (c) {
      if (c.resolved) return;   // the author has already acted on it; do not round-trip it
      out.comments.push({
        selected_text: c.text, near_question: c.near || null, comment: c.comment,
        anchored: !!document.querySelector('mark.cmt[data-cid="' + c.cid + '"]')
      });
    });
    /* Drafts are comments the reader typed but never saved. They ship in the
       payload rather than being dropped: losing a typed thought to a stray
       click outside the box is the failure this whole subsystem exists to stop. */
    out.drafts = state.drafts.filter(function (d) { return (d.comment || '').trim(); })
      .map(function (d) {
        return { selected_text: d.text || '', near_question: d.near || null,
                 comment: d.comment, draft: true };
      });
    return JSON.stringify(out, null, 2);
  }
  function copyText(txt, msg) {
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = txt; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch {}
      ta.remove(); toast(msg);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(function () { toast(msg); }, fallback);
    } else fallback();
  }
  function copyJSON() { copyText(responsesJSON(), 'Responses JSON copied'); }
  var copyBtnEl = document.getElementById('copyBtn');
  copyBtnEl.innerHTML = ICON.copy;
  tip(copyBtnEl, 'Copy responses JSON', MOD + 'C');
  copyBtnEl.addEventListener('click', copyJSON);
  /* Download the same payload as a file — a brief read offline, or one whose
     answers must be kept, needs an artefact rather than a clipboard. */
  function downloadJSON() {
    var slug = (BRIEF || document.title || 'brief').toLowerCase()
      .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'brief';
    var date = new Date().toISOString().slice(0, 10);
    var url = URL.createObjectURL(new Blob([responsesJSON()], { type: 'application/json' }));
    var a = document.createElement('a');
    a.href = url; a.download = slug + '-responses-' + date + '.json';
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    toast('Responses JSON downloaded');
  }
  var dlBtn = document.getElementById('downloadBtn');
  if (dlBtn) {
    dlBtn.innerHTML = ICON.download;
    tip(dlBtn, 'Download responses JSON');
    dlBtn.addEventListener('click', downloadJSON);
  }
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'c') {
      var sel = window.getSelection();
      var active = document.activeElement;
      var inField = active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT');
      if ((!sel || sel.isCollapsed) && !inField) { e.preventDefault(); copyJSON(); }
    }
    if (e.key === 'Escape') closePop();
  });

  /* ── selection comments ───────────────────────────────────────────────
     Three defects fixed here, all of which presented as "my comment vanished":
       1. surroundContents() throws on any selection crossing an element
          boundary, so the comment saved but was never highlighted, and nothing
          in the UI could reach it again.
       2. re-anchoring searched one text node at a time, so a quote spanning a
          <strong> or two paragraphs could never re-match on reload.
       3. text typed into the popup was lost the moment the reader clicked away.
     The drawer is the backstop: every comment and every draft is reachable
     from it whether or not its highlight survived. */
  var CHROME = '.topbar, #cpop, #cdrawer, #toast, .codecopy';
  var pop = null, editing = null, pendingRange = null, popDraftKey = null;

  function main() { return document.getElementById('briefMain') || document.querySelector('main'); }
  function norm(t) { return String(t).replace(/\s+/g, ' ').trim(); }
  function nearestQ(node) {
    var el = node && node.nodeType === 1 ? node : (node && node.parentElement);
    var q = el && el.closest ? el.closest('section.q, section.brief-section') : null;
    return q ? (q.dataset.q || q.dataset.sec) : null;
  }

  function textNodesIn(root) {
    if (!root) return [];
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        var pe = n.parentElement;
        if (!pe || pe.closest(CHROME)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var out = [], n;
    while ((n = w.nextNode())) out.push(n);
    return out;
  }

  /* Flatten the document to one whitespace-normalised string with an index map
     back into its text nodes, so a quote spanning several elements still
     resolves to a single Range. */
  function flatten(root) {
    var nodes = textNodesIn(root), str = '', map = [];
    nodes.forEach(function (n) {
      var v = n.nodeValue;
      for (var i = 0; i < v.length; i++) {
        var ch = /\s/.test(v[i]) ? ' ' : v[i];
        if (ch === ' ' && str.slice(-1) === ' ') continue;
        str += ch; map.push({ node: n, offset: i });
      }
    });
    return { text: str, map: map };
  }

  function findRange(root, quote, nth) {
    if (!root || !quote) return null;
    var f = flatten(root), q = norm(quote);
    if (!q) return null;
    var from = 0, at = -1, seen = 0, hit;
    while ((hit = f.text.indexOf(q, from)) !== -1) {
      at = hit;
      if (seen === (nth || 0)) break;
      seen++; from = hit + 1; at = -1;
    }
    if (at === -1 || !f.map[at] || !f.map[at + q.length - 1]) return null;
    var a = f.map[at], b = f.map[at + q.length - 1];
    var r = document.createRange();
    r.setStart(a.node, a.offset); r.setEnd(b.node, b.offset + 1);
    return r;
  }

  /* Which occurrence of this text the reader actually selected — without it,
     a repeated phrase re-anchors onto the first match on reload. */
  function occurrenceOf(root, range) {
    var f = flatten(root), q = norm(range.toString());
    if (!q) return 0;
    var probe = document.createRange(), from = 0, at, i = 0;
    while ((at = f.text.indexOf(q, from)) !== -1) {
      var a = f.map[at], b = f.map[at + q.length - 1];
      if (a && b) {
        probe.setStart(a.node, a.offset); probe.setEnd(b.node, b.offset + 1);
        if (probe.compareBoundaryPoints(Range.START_TO_START, range) === 0) return i;
      }
      i++; from = at + 1;
    }
    return 0;
  }

  /* Wrap every text node the range touches in its own <mark>, instead of one
     surroundContents() that throws the moment the range crosses an element. */
  function wrapRange(range, cid) {
    var all = textNodesIn(main()).filter(function (n) {
      try { return range.intersectsNode(n); } catch { return false; }
    });
    if (!all.length) return false;
    var sc = range.startContainer, so = range.startOffset;
    var ec = range.endContainer, eo = range.endOffset;
    var made = false;
    all.forEach(function (node) {
      var a = (node === sc) ? so : 0;
      var b = (node === ec) ? eo : node.nodeValue.length;
      if (b <= a) return;
      var r = document.createRange();
      try { r.setStart(node, a); r.setEnd(node, b); } catch { return; }
      var mk = document.createElement('mark');
      mk.className = 'cmt'; mk.dataset.cid = cid;
      try { r.surroundContents(mk); made = true; } catch {}
    });
    return made;
  }

  function unpaint(cid) {
    Array.prototype.forEach.call(document.querySelectorAll('mark.cmt[data-cid="' + cid + '"]'), function (m) {
      var parent = m.parentNode;
      while (m.firstChild) parent.insertBefore(m.firstChild, m);
      m.remove(); parent.normalize();
    });
  }
  function isAnchored(cid) { return !!document.querySelector('mark.cmt[data-cid="' + cid + '"]'); }

  /* ── drafts ── */
  function draftKey(existing, quote) { return existing ? 'cid:' + existing.cid : 'sel:' + norm(quote); }
  function draftFor(key) {
    return state.drafts.filter(function (d) { return d.key === key; })[0] || null;
  }
  function putDraft(key, quote, body, near, cid) {
    var d = draftFor(key);
    if (!body.trim()) { return dropDraft(key); }
    if (!d) { d = { key: key, text: quote || '', near: near || null, cid: cid || null }; state.drafts.push(d); }
    d.comment = body; d.at = new Date().toISOString();
    save(); renderDrawer();
  }
  function dropDraft(key) {
    var before = state.drafts.length;
    state.drafts = state.drafts.filter(function (d) { return d.key !== key; });
    if (state.drafts.length !== before) { save(); renderDrawer(); }
  }

  /* ── the popup ── */
  function closePop() { if (pop) { pop.remove(); pop = null; editing = null; popDraftKey = null; } }

  function openPop(x, y, quote, existing, prefill) {
    closePop();
    var key = draftKey(existing, quote);
    popDraftKey = key;
    var draft = draftFor(key);
    pop = document.createElement('div');
    pop.id = 'cpop';
    pop.innerHTML =
      '<div class="quote">“' + String(quote).replace(/[<&]/g, function (c) { return c === '<' ? '&lt;' : '&amp;'; }).slice(0, 180) + '”</div>' +
      '<textarea placeholder="Comment — saved locally"></textarea>' +
      '<div class="row">' +
      (existing ? '<button class="btn small danger" data-act="del" type="button">Delete</button>' : '') +
      (existing ? '' : '<button class="btn small" data-act="copy" type="button">Copy text</button>') +
      '<button class="btn small" data-act="cancel" type="button">Discard</button>' +
      '<button class="btn small primary" data-act="save" type="button">Save</button></div>' +
      '<p class="pophint">' + MOD + 'Enter saves · Esc closes and keeps a draft' +
      (existing ? '' : ' · selection stays live, ' + MOD + 'C copies it') + '</p>';
    document.body.appendChild(pop);
    var vw = document.documentElement.clientWidth;
    var w = pop.offsetWidth;
    pop.style.left = Math.max(8, Math.min(x - w / 2, vw - w - 8)) + 'px';
    pop.style.top = (y + 8) + 'px';

    var ta = pop.querySelector('textarea');
    ta.value = (prefill != null ? prefill : (draft ? draft.comment : (existing ? existing.comment : '')));
    /* On a FRESH selection we deliberately do not focus: focusing collapses the
       document selection and would break a plain copy. */
    if (existing || prefill != null) setTimeout(function () { ta.focus(); }, 10);

    ta.addEventListener('input', function () {
      putDraft(key, quote, ta.value, existing ? existing.near : (pendingRange ? nearestQ(pendingRange.startContainer) : null),
               existing ? existing.cid : null);
    });
    pop.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePop(); return; }
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); e.stopPropagation(); commit(); }
    }, true);
    pop.addEventListener('mousedown', function (e) { e.stopPropagation(); });

    function commit() {
      var val = ta.value.trim();
      if (!val) { dropDraft(key); closePop(); return; }
      if (existing) {
        existing.comment = val; existing.at = new Date().toISOString();
        dropDraft(key); save(); renderDrawer(); closePop(); toast('Comment updated');
        return;
      }
      var cid = 'c' + Date.now() + Math.floor(Math.random() * 1000);
      var range = pendingRange || (draft ? findRange(main(), draft.text, draft.nth || 0) : null);
      var c = {
        cid: cid, text: quote, comment: val,
        near: range ? nearestQ(range.startContainer) : (draft ? draft.near : null),
        nth: range ? occurrenceOf(main(), range) : 0,
        at: new Date().toISOString()
      };
      state.comments.push(c);
      if (range) wrapRange(range, cid);
      dropDraft(key); save(); renderDrawer(); closePop();
      var sel = window.getSelection(); if (sel) sel.removeAllRanges();
      toast(isAnchored(cid) ? 'Comment saved' : 'Comment saved (no highlight — find it in Comments)');
    }

    pop.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('button');
      var act = btn && btn.dataset.act;
      if (!act) return;
      if (act === 'cancel') { dropDraft(key); closePop(); return; }
      if (act === 'copy') { copyText(quote, 'Selected text copied'); return; }
      if (act === 'del' && existing) {
        unpaint(existing.cid);
        state.comments = state.comments.filter(function (c) { return c.cid !== existing.cid; });
        dropDraft(key); save(); renderDrawer(); closePop(); toast('Comment deleted');
        return;
      }
      if (act === 'save') commit();
    });
  }

  function editComment(c) {
    editing = c;
    var mk = document.querySelector('mark.cmt[data-cid="' + c.cid + '"]');
    var r = mk ? mk.getBoundingClientRect() : { left: innerWidth / 2 - 170, width: 0, bottom: 120 };
    if (mk) mk.scrollIntoView({ block: 'center', behavior: 'smooth' });
    openPop(r.left + r.width / 2 + window.scrollX, r.bottom + window.scrollY, c.text, c, null);
  }

  document.addEventListener('mouseup', function (e) {
    if (pop && pop.contains(e.target)) return;
    if (e.target.closest && e.target.closest('#cdrawer, .topbar')) return;
    var mark = e.target.closest && e.target.closest('mark.cmt');
    setTimeout(function () {
      var sel = window.getSelection();
      if (sel && !sel.isCollapsed && sel.toString().trim() && main() && main().contains(sel.anchorNode)) {
        pendingRange = sel.getRangeAt(0).cloneRange();
        var r = pendingRange.getBoundingClientRect();
        openPop(r.left + r.width / 2 + window.scrollX, r.bottom + window.scrollY, sel.toString().trim(), null, null);
      } else if (mark) {
        var c = state.comments.filter(function (x) { return x.cid === mark.dataset.cid; })[0];
        if (c) editComment(c);
      } else if (pop) closePop();
    }, 0);
  });

  function reanchor() {
    state.comments.forEach(function (c) {
      if (isAnchored(c.cid)) return;
      /* A comment whose quoted text is no longer in the document cannot anchor,
         and findRange walks every text node to discover that. Retrying it on
         every drawer open made the first few clicks crawl on a brief carrying
         two dozen comments from earlier versions. Remember the miss instead. */
      if (c.noAnchor) return;
      var r = findRange(main(), c.text, c.nth || 0);
      if (r) wrapRange(r, c.cid); else c.noAnchor = true;
    });
    paintResolved();
    renderDrawer();
  }

  /* ── comments drawer ──
     Every comment and draft in one list, anchored or not. This is what makes a
     lost highlight a cosmetic problem instead of a lost thought. */
  var drawer = document.createElement('div');
  drawer.id = 'cdrawer'; drawer.hidden = true;
  drawer.setAttribute('role', 'dialog');
  drawer.setAttribute('aria-label', 'Comments and drafts');
  document.body.appendChild(drawer);

  function esc(t) {
    return String(t == null ? '' : t).replace(/[<>&]/g, function (c) {
      return c === '<' ? '&lt;' : c === '>' ? '&gt;' : '&amp;';
    });
  }

  function renderDrawer() {
    var cmtBtn = document.getElementById('cmtBtn');
    var drafts = state.drafts.filter(function (d) { return (d.comment || '').trim(); });
    var n = state.comments.length;
    if (cmtBtn) {
      cmtBtn.innerHTML = ICON.comment +
        (n || drafts.length ? '<span class="cbadge' + (drafts.length ? ' hasdraft' : '') + '">' + (n + drafts.length) + '</span>' : '');
      tip(cmtBtn, 'Comments' + (drafts.length ? ' — ' + drafts.length + ' unsaved draft' + (drafts.length > 1 ? 's' : '') : ''), 'C');
    }
    if (drawer.hidden) return;
    var html = '<div class="dhead"><strong>Comments</strong><button class="btn small" data-d="close" type="button">Close</button></div>';
    if (drafts.length) {
      html += '<p class="dlabel">Unsaved drafts</p>';
      drafts.forEach(function (d) {
        html += '<div class="drow draft" data-key="' + esc(d.key) + '">' +
          '<div class="dq">' + (d.text ? '“' + esc(d.text).slice(0, 160) + '”' : '<em>no selection</em>') + '</div>' +
          '<div class="db">' + esc(d.comment) + '</div>' +
          '<div class="dacts"><button class="btn small" data-d="resume" type="button">Resume</button>' +
          '<button class="btn small danger" data-d="discard" type="button">Discard</button></div></div>';
      });
    }
    if (!n) {
      html += '<p class="dempty">No saved comments yet. Select any text in the brief to comment on it.</p>';
    } else {
      html += '<p class="dlabel">Saved</p>';
      state.comments.forEach(function (c) {
        var anchored = isAnchored(c.cid);
        html += '<div class="drow' + (c.resolved ? ' resolved' : '') + '" data-cid="' + esc(c.cid) + '">' +
          '<div class="dq">“' + esc(c.text).slice(0, 160) + '”' +
          (c.resolved ? '<span class="dbadge done">addressed</span>' : '') +
          (anchored ? '' : '<span class="dbadge">not highlighted</span>') + '</div>' +
          '<div class="db">' + esc(c.comment) + '</div>' +
          '<div class="dacts">' +
          (anchored ? '<button class="btn small" data-d="goto" type="button">Show</button>' : '') +
          '<button class="btn small" data-d="edit" type="button">Edit</button>' +
          '<button class="btn small danger" data-d="del" type="button">Delete</button></div></div>';
      });
    }
    drawer.innerHTML = html;
  }

  drawer.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('button');
    if (!btn) return;
    var act = btn.dataset.d;
    var row = btn.closest('.drow');
    if (act === 'close') return toggleDrawer(false);
    if (act === 'discard') { dropDraft(row.dataset.key); return; }
    if (act === 'resume') {
      var d = draftFor(row.dataset.key);
      if (!d) return;
      toggleDrawer(false);
      if (d.cid) {
        var c0 = state.comments.filter(function (c) { return c.cid === d.cid; })[0];
        if (c0) { editing = c0; return openPop(innerWidth / 2, window.scrollY + 100, c0.text, c0, d.comment); }
      }
      pendingRange = d.text ? findRange(main(), d.text, d.nth || 0) : null;
      return openPop(innerWidth / 2, window.scrollY + 100, d.text || '(no selection)', null, d.comment);
    }
    var c = state.comments.filter(function (x) { return x.cid === row.dataset.cid; })[0];
    if (!c) return;
    if (act === 'goto') {
      toggleDrawer(false);
      var mk = document.querySelector('mark.cmt[data-cid="' + c.cid + '"]');
      if (mk) { mk.scrollIntoView({ block: 'center', behavior: 'smooth' }); mk.classList.add('flash');
                setTimeout(function () { mk.classList.remove('flash'); }, 1600); }
      return;
    }
    if (act === 'edit') { toggleDrawer(false); return editComment(c); }
    if (act === 'del') {
      unpaint(c.cid);
      state.comments = state.comments.filter(function (x) { return x.cid !== c.cid; });
      save(); renderDrawer(); toast('Comment deleted');
    }
  });

  function toggleDrawer(on) {
    drawer.hidden = (on === undefined) ? !drawer.hidden : !on;
    if (!drawer.hidden) renderDrawer();
  }
  var cmtBtnEl = document.getElementById('cmtBtn');
  if (cmtBtnEl) cmtBtnEl.addEventListener('click', function () { toggleDrawer(); });
  document.addEventListener('click', function (e) {
    if (drawer.hidden) return;
    if (e.target.closest && e.target.closest('#cdrawer, #cmtBtn, #cpop')) return;
    toggleDrawer(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'c' && e.key !== 'C') return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var a = document.activeElement;
    if (a && (a.tagName === 'TEXTAREA' || a.tagName === 'INPUT' || a.isContentEditable)) return;
    var sel = window.getSelection();
    if (sel && !sel.isCollapsed) return;
    e.preventDefault(); toggleDrawer();
  });

  /* ── footnotes → references ──
     A footnote target may sit inside a collapsed <details> or a ticked-off
     (collapsed) section, so jumping to it must reveal it first, else the click
     appears to do nothing. Also back-links each reference to its first citation. */
  function revealTarget(hash) {
    if (!hash || hash.length < 2) return;
    var el;
    try { el = document.querySelector(hash); } catch { return; }
    if (!el) return;
    var p = el;
    while (p && p !== document.body) {
      if (p.tagName === 'DETAILS') p.open = true;
      if (p.classList && p.classList.contains('done')) {
        var cb = p.querySelector('.tick input');
        if (cb && cb.checked) { cb.checked = false; cb.dispatchEvent(new Event('change', { bubbles: true })); }
      }
      p = p.parentElement;
    }
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
  window.addEventListener('hashchange', function () { revealTarget(location.hash); });
  if (location.hash) setTimeout(function () { revealTarget(location.hash); }, 0);

  var citedBy = {};
  Array.prototype.forEach.call(document.querySelectorAll('sup.fn > a[href^="#"]'), function (a, i) {
    var sup = a.parentElement;
    if (!sup.id) sup.id = 'cite-' + (i + 1);
    var key = a.getAttribute('href').slice(1);
    if (!citedBy[key]) citedBy[key] = sup.id;
    if (!a.title) a.title = 'Jump to reference';
  });
  Object.keys(citedBy).forEach(function (key) {
    var target = document.getElementById(key);
    if (!target || target.querySelector('a.backref')) return;
    var back = document.createElement('a');
    back.className = 'backref'; back.href = '#' + citedBy[key];
    back.textContent = '↩'; back.setAttribute('aria-label', 'Back to the text that cites this');
    (target.querySelector('.apa') || target).appendChild(back);
  });

  /* ── copy buttons on code blocks ── */
  /* Every <pre> gets a copy icon top-right that copies its text content. */
  Array.prototype.slice.call(document.querySelectorAll('#briefMain pre, main pre')).forEach(function (pre) {
    if (pre.querySelector(':scope > .codecopy')) return;
    pre.classList.add('has-copy');
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'codecopy';
    btn.setAttribute('aria-label', 'Copy code');
    btn.innerHTML = '<span class="ci" aria-hidden="true">⎘</span>';
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var code = pre.querySelector('code');
      var txt = (code || pre).textContent;
      function done() { btn.classList.add('copied'); toast('Copied'); clearTimeout(btn._h); btn._h = setTimeout(function () { btn.classList.remove('copied'); }, 1200); }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(txt).then(done, function () {
          var ta = document.createElement('textarea'); ta.value = txt; document.body.appendChild(ta); ta.select();
          try { document.execCommand('copy'); } catch {} ta.remove(); done();
        });
      } else {
        var ta2 = document.createElement('textarea'); ta2.value = txt; document.body.appendChild(ta2); ta2.select();
        try { document.execCommand('copy'); } catch {} ta2.remove(); done();
      }
    });
    pre.appendChild(btn);
  });

  reanchor();
  renderProgress();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
