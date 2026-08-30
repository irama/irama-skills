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
  var state = { ticks: {}, answers: {}, notes: {}, edits: {}, comments: [], drafts: [] };
  if (!state.notes) state.notes = {};
  if (!state.edits) state.edits = {};
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
    /* An edited document ships as the reader left it, with the original beside it,
       because a rewrite the author cannot diff is a rewrite they have to re-read whole. */
    out.edits = [];
    Array.prototype.forEach.call(document.querySelectorAll('[data-doc]'), function (doc) {
      var k = doc.dataset.doc, edited = state.edits[k];
      if (edited == null || edited === docSource(doc)) return;
      out.edits.push({ id: k, label: doc.dataset.docLabel || k,
                       original: docSource(doc), edited: edited });
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
  /* stopPropagation, because opening the drawer re-renders this button's icon:
     by the time the document listener below runs, the <svg> the click landed on
     has been replaced, its closest('#cmtBtn') walks a detached tree, the
     click-outside guard misses, and the drawer closes on the very click that
     opened it. Hitting the button's padding worked, the icon did not. */
  if (cmtBtnEl) cmtBtnEl.addEventListener('click', function (e) { e.stopPropagation(); toggleDrawer(); });
  document.addEventListener('click', function (e) {
    if (drawer.hidden) return;
    /* composedPath() is captured at dispatch, so it still names the button even
       if the node the click hit has since been re-rendered. */
    var path = e.composedPath ? e.composedPath() : [];
    for (var i = 0; i < path.length; i++) {
      var el = path[i];
      if (el && el.id && /^(cdrawer|cmtBtn|cpop)$/.test(el.id)) return;
    }
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

  /* ── editable documents ──────────────────────────────────────────────────
     A `[data-doc]` block is a document the reader may rewrite, not just comment
     on. Source is source, so Edit mode is mono, wrapped and syntax-tinted, the
     same call prima's workbench makes; the reading view stays serif. The
     original is held in the DOM (a <script type="text/markdown">) so a revert is
     always possible and the export can carry both sides.

     ponytail: a ~40-line markdown renderer, not a parser. It covers what an
     article uses (headings, emphasis, links, code, lists, quotes, rules, tables
     are NOT covered) and the source is always one keystroke away in Edit mode,
     which is the escape hatch that makes the small renderer safe. Swap in a real
     parser the day a brief needs one. */
  function docSource(doc) {
    var src = doc.querySelector('script[type="text/markdown"]');
    return src ? src.textContent.replace(/^\n/, '') : '';
  }
  function esc(t) {
    return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function inline(t) {
    return esc(t)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
      .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2">$1</a>');
  }
  /* GFM pipe tables. A brief's editable document is usually a draft of something
     that ships, and shipping prose has tables in it; without this a pasted table
     is silently flattened on the way back to markdown. */
  function tableRow(line) {
    return line.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map(function (c) { return c.trim(); });
  }
  function isTableDivider(line) {
    return /^\s*\|?[\s:-]*-[\s:|-]*\|?\s*$/.test(line) && line.indexOf('-') > -1;
  }
  function mdToHtml(md) {
    var out = [], para = [], list = null, fence = null;
    function flush() {
      if (para.length) { out.push('<p>' + inline(para.join(' ')) + '</p>'); para = []; }
      if (list) { out.push('</' + list + '>'); list = null; }
    }
    var lines = md.split('\n');
    /* Tables are handled by a pre-pass so the line loop below stays a line loop:
       a table needs two lines of lookahead, which the per-line reducer cannot do. */
    var html = [], i = 0;
    while (i < lines.length) {
      if (/\|/.test(lines[i]) && lines[i + 1] !== undefined && isTableDivider(lines[i + 1]) &&
          !/^```/.test(lines[i])) {
        var head = tableRow(lines[i]), rows = [];
        i += 2;
        while (i < lines.length && /\|/.test(lines[i]) && lines[i].trim()) { rows.push(tableRow(lines[i])); i += 1; }
        var t = '<div class="tblwrap nopin"><table><thead><tr>' +
          head.map(function (c) { return '<th>' + inline(c) + '</th>'; }).join('') + '</tr></thead><tbody>' +
          rows.map(function (r) {
            return '<tr>' + r.map(function (c) { return '<td>' + inline(c) + '</td>'; }).join('') + '</tr>';
          }).join('') + '</tbody></table></div>';
        html.push({ raw: t });
        continue;
      }
      html.push(lines[i]); i += 1;
    }
    html.forEach(function (line) {
      if (line && line.raw !== undefined) { flush(); out.push(line.raw); return; }
      if (/^```/.test(line)) {
        if (fence === null) { flush(); fence = []; }
        else { out.push('<pre><code>' + esc(fence.join('\n')) + '</code></pre>'); fence = null; }
        return;
      }
      if (fence !== null) { fence.push(line); return; }
      var h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) { flush(); out.push('<h' + h[1].length + '>' + inline(h[2]) + '</h' + h[1].length + '>'); return; }
      if (/^\s*(---|\*\*\*)\s*$/.test(line)) { flush(); out.push('<hr>'); return; }
      if (/^>\s?/.test(line)) { flush(); out.push('<blockquote>' + inline(line.replace(/^>\s?/, '')) + '</blockquote>'); return; }
      var li = line.match(/^\s*([-*]|\d+\.)\s+(.*)$/);
      if (li) {
        var want = /^\d/.test(li[1]) ? 'ol' : 'ul';
        if (list !== want) { flush(); out.push('<' + want + '>'); list = want; }
        out.push('<li>' + inline(li[2]) + '</li>');
        return;
      }
      if (!line.trim()) { flush(); return; }
      if (list) { out.push('</' + list + '>'); list = null; }
      para.push(line.trim());
    });
    flush();
    return out.join('\n');
  }
  /* The way back: the rich view is edited in place, so what the reader sees is
     what gets serialised. Markdown stays the stored form — it is what rides in
     the responses JSON and what Revert compares against — so every keystroke in
     rich mode walks the DOM back to markdown. Covers the same subset mdToHtml
     renders; anything else the browser produces (a stray <div>, a <b>) is
     normalised to its markdown equivalent rather than passed through. */
  function mdInline(node) {
    var out = '';
    Array.prototype.forEach.call(node.childNodes, function (n) {
      if (n.nodeType === 3) { out += n.nodeValue.replace(/\s+/g, ' '); return; }
      if (n.nodeType !== 1) return;
      var tag = n.nodeName.toLowerCase(), inner = mdInline(n);
      if (tag === 'br') out += '\n';
      else if (tag === 'strong' || tag === 'b') out += inner.trim() ? '**' + inner.trim() + '**' : '';
      else if (tag === 'em' || tag === 'i') out += inner.trim() ? '*' + inner.trim() + '*' : '';
      else if (tag === 'code') out += '`' + inner + '`';
      else if (tag === 'a') out += '[' + inner + '](' + (n.getAttribute('href') || '') + ')';
      else out += inner;
    });
    return out;
  }
  function htmlToMd(root) {
    var out = [];
    Array.prototype.forEach.call(root.childNodes, function (n) {
      if (n.nodeType === 3) { if (n.nodeValue.trim()) out.push(n.nodeValue.trim()); return; }
      if (n.nodeType !== 1) return;
      var tag = n.nodeName.toLowerCase();
      if (/^h[1-6]$/.test(tag)) out.push(new Array(+tag[1] + 1).join('#') + ' ' + mdInline(n).trim());
      else if (tag === 'hr') out.push('---');
      else if (tag === 'blockquote') out.push(htmlToMd(n).split('\n').map(function (l) {
        return l.trim() ? '> ' + l : '>';
      }).join('\n'));
      else if (tag === 'pre') out.push('```\n' + (n.textContent || '').replace(/\n$/, '') + '\n```');
      else if (tag === 'ul' || tag === 'ol') {
        var i = 0;
        Array.prototype.forEach.call(n.children, function (li) {
          i += 1;
          out.push((tag === 'ol' ? i + '. ' : '- ') + mdInline(li).trim());
        });
      } else if (tag === 'table' || (tag === 'div' && n.querySelector('table'))) {
        var tbl = tag === 'table' ? n : n.querySelector('table');
        var rows = tbl.querySelectorAll('tr'), lines = [], cols = 0;
        Array.prototype.forEach.call(rows, function (tr, ri) {
          var cells = Array.prototype.map.call(tr.children, function (td) {
            return mdInline(td).trim().replace(/\|/g, '\\|');
          });
          cols = Math.max(cols, cells.length);
          lines.push('| ' + cells.join(' | ') + ' |');
          if (ri === 0) lines.push('| ' + new Array(cells.length + 1).join('--- |').replace(/ \|$/, ' |').split('--- |').join('--- | ').trim());
        });
        if (lines[1]) lines[1] = '|' + new Array(cols + 1).join(' --- |');
        out.push(lines.join('\n'));
      } else if (tag === 'div' && n.children.length && !mdInline(n).trim()) out.push(htmlToMd(n));
      else { var t = mdInline(n).trim(); if (t) out.push(t); }
    });
    return out.join('\n\n');
  }

  /* ── the editor ──────────────────────────────────────────────────────────
     Ported from the project-lightbox Description field in a sibling app
     (its src/components/ui/{MarkdownEditor,RichTextEditor,MiniTocSidebar}.tsx).
     That app runs TipTap through a bundler; a brief is one file opened from disk, so
     the behaviour is rebuilt on contenteditable + execCommand. What is copied
     deliberately: click the rendered text to start editing with the caret where
     you clicked, a sticky toolbar whose buttons light up for the caret's
     context, a Raw MD / Rich editor toggle over the same markdown string, and a
     hover-to-expand heading rail of thin bars.

     ponytail: execCommand is deprecated and still the only zero-dependency way
     to format a contenteditable selection. Swap for Selection/Range surgery the
     day a browser drops it — apply() is the only caller. */

  /* MiniTocSidebar.tsx:39 — width per level, non-linear so H1 and H2 read
     as different things at a glance. */
  var TOC_BAR = [22, 15, 9, 6, 4, 3];
  /* MiniTocSidebar.tsx:79 — the active heading is the last one whose top
     edge is at or above the fold. */
  var TOC_FOLD = 112;

  var DOC_TOOLS = [
    { block: 'h1', label: 'H1', tip: 'Heading 1', is: 'h1' },
    { block: 'h2', label: 'H2', tip: 'Heading 2', is: 'h2' },
    { block: 'h3', label: 'H3', tip: 'Heading 3', is: 'h3' },
    { sep: true },
    { cmd: 'bold', label: 'B', tip: 'Bold (⌘B)', cls: 'b', state: 'bold' },
    { cmd: 'italic', label: 'I', tip: 'Italic (⌘I)', cls: 'i', state: 'italic' },
    { cmd: 'strikeThrough', label: 'S', tip: 'Strikethrough', cls: 's', state: 'strikeThrough' },
    { code: true, label: '‹›', tip: 'Inline code', is: 'code' },
    { block: 'pre', label: '{ }', tip: 'Code block', is: 'pre' },
    { sep: true },
    { cmd: 'insertUnorderedList', label: '•', tip: 'Bullet list', state: 'insertUnorderedList' },
    { cmd: 'insertOrderedList', label: '1.', tip: 'Ordered list', state: 'insertOrderedList' },
    { sep: true },
    { block: 'blockquote', label: '❝', tip: 'Blockquote (>)', is: 'blockquote' },
    { block: 'p', label: '¶', tip: 'Body text', is: 'p' },
    { hr: true, label: '—', tip: 'Horizontal rule (---)' },
    { sep: true },
    { link: true, label: '🔗', tip: 'Add link (⌘K)', is: 'a' },
    { unlink: true, label: '⛓', tip: 'Remove link' },
    { table: true, label: '▦', tip: 'Table controls' },
    { sep: true },
    { copy: true, label: '⧉', tip: 'Copy as markdown' }
  ];
  var TABLE_TOOLS = [
    { act: 'insert', label: 'Insert 3×3', tip: 'Insert 3×3 table' },
    { act: 'rowAfter', label: '+ row', tip: 'Add row below' },
    { act: 'rowDel', label: '− row', tip: 'Delete row' },
    { act: 'colAfter', label: '+ col', tip: 'Add column right' },
    { act: 'colDel', label: '− col', tip: 'Delete column' }
  ];

  /* MarkdownEditor.tsx:355 — resolve a click to a plain-text character
     offset in the rendered document. the source app needs this because its preview
     and its editor are two different DOMs; here they are the same DOM, so the offset
     round-trips exactly rather than approximately. */
  function offsetFromPoint(root, x, y) {
    var node = null, off = 0;
    if (document.caretPositionFromPoint) {
      var pos = document.caretPositionFromPoint(x, y);
      if (pos) { node = pos.offsetNode; off = pos.offset; }
    } else if (document.caretRangeFromPoint) {
      var rg = document.caretRangeFromPoint(x, y);
      if (rg) { node = rg.startContainer; off = rg.startOffset; }
    }
    if (!node || !root.contains(node)) return null;
    var count = 0, w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), n = w.nextNode();
    while (n) {
      if (n === node) return count + off;
      count += (n.nodeValue || '').length;
      n = w.nextNode();
    }
    return null;
  }
  function caretToOffset(root, offset) {
    var count = 0, w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT), n = w.nextNode();
    while (n) {
      var len = (n.nodeValue || '').length;
      if (count + len >= offset) {
        var r = document.createRange();
        r.setStart(n, Math.max(0, Math.min(len, offset - count)));
        r.collapse(true);
        var s = window.getSelection();
        s.removeAllRanges(); s.addRange(r);
        return true;
      }
      count += len; n = w.nextNode();
    }
    return false;
  }

  Array.prototype.forEach.call(document.querySelectorAll('[data-doc]'), function (doc) {
    var key = doc.dataset.doc;
    var label = doc.dataset.docLabel || 'document';
    var view = document.createElement('div'); view.className = 'doc-view';
    view.setAttribute('role', 'textbox');
    view.setAttribute('aria-label', label + ' — click the text to edit it');
    var ta = document.createElement('textarea'); ta.className = 'doc-src';
    ta.setAttribute('aria-label', 'Edit ' + label + ' markdown source');
    ta.spellcheck = false;
    var bar = document.createElement('div'); bar.className = 'doc-bar';
    var tools = document.createElement('div'); tools.className = 'doc-tools';
    var tblbar = document.createElement('div'); tblbar.className = 'doc-tablebar'; tblbar.hidden = true;
    var done = document.createElement('button'); done.type = 'button'; done.className = 'doc-btn doc-done';
    done.textContent = 'Done';
    var srcBtn = document.createElement('button'); srcBtn.type = 'button'; srcBtn.className = 'doc-btn doc-srcbtn';
    var revert = document.createElement('button'); revert.type = 'button'; revert.className = 'doc-btn doc-revert';
    revert.textContent = 'Revert';
    var flag = document.createElement('span'); flag.className = 'doc-flag';
    var hint = document.createElement('span'); hint.className = 'doc-hint'; hint.textContent = 'Click the text to edit';
    var rail = document.createElement('div'); rail.className = 'doc-rail';
    var bars = document.createElement('div'); bars.className = 'doc-bars';
    var fly = document.createElement('div'); fly.className = 'doc-fly'; fly.hidden = true;
    rail.appendChild(fly); rail.appendChild(bars);
    rail.setAttribute('aria-label', 'Headings in ' + label);

    function editing() { return doc.classList.contains('editing'); }
    function raw() { return doc.classList.contains('raw'); }
    function current() {
      var e = state.edits[key];
      return e == null ? docSource(doc) : e;
    }
    function store(md) {
      state.edits[key] = md; save();
      var changed = md !== docSource(doc);
      flag.textContent = changed ? 'edited' : '';
      doc.classList.toggle('is-edited', changed);
      revert.hidden = !changed;
    }
    function inTable() {
      var s = window.getSelection();
      if (!s || !s.rangeCount) return null;
      var n = s.getRangeAt(0).startContainer;
      n = n.nodeType === 1 ? n : n.parentNode;
      return n && n.closest ? n.closest('td, th') : null;
    }
    function activeTag(tag) {
      var s = window.getSelection();
      if (!s || !s.rangeCount || !view.contains(s.anchorNode)) return false;
      var n = s.anchorNode;
      n = n.nodeType === 1 ? n : n.parentNode;
      return !!(n && n.closest && n.closest(tag) && view.contains(n.closest(tag)));
    }
    /* the source app lights its buttons from editor.isActive(); execCommand gives the same
       answer for inline marks, and the caret's ancestors give it for blocks. */
    function syncTools() {
      Array.prototype.forEach.call(tools.children, function (b) {
        if (!b.dataset.i) return;
        var t = DOC_TOOLS[+b.dataset.i], on = false;
        try {
          if (t.state) on = document.queryCommandState(t.state);
          else if (t.is) on = activeTag(t.is);
        } catch (err) { on = false; }
        b.classList.toggle('on', !!on);
      });
      var cell = inTable();
      if (cell) tblbar.hidden = false;      /* RichTextEditor.tsx:502 — the table
                                               controls open themselves when the caret
                                               lands in a table, and close by hand. */
    }
    function apply(t) {
      if (!editing() || raw()) return;
      view.focus();
      if (t.block) {
        /* Toggle back to a paragraph when the caret is already in that block,
           the way the source app's toggleHeading does. */
        document.execCommand('formatBlock', false, t.is && activeTag(t.is) && t.block !== 'p' ? 'p' : t.block);
      } else if (t.code) {
        var s = window.getSelection();
        if (s && !s.isCollapsed) {
          if (activeTag('code')) document.execCommand('removeFormat', false, null);
          else {
            var c = document.createElement('code');
            try { s.getRangeAt(0).surroundContents(c); }
            catch (err) { document.execCommand('insertHTML', false, '<code>' + esc(s.toString()) + '</code>'); }
          }
        }
      } else if (t.hr) document.execCommand('insertHorizontalRule', false, null);
      else if (t.link) {
        var href = window.prompt('Link URL');
        if (href) document.execCommand('createLink', false, href);
      } else if (t.unlink) document.execCommand('unlink', false, null);
      else if (t.table) { tblbar.hidden = !tblbar.hidden; return; }
      else if (t.copy) {
        copyText(current(), 'Markdown copied');
        return;
      } else document.execCommand(t.cmd, false, null);
      onRichInput();
    }
    function tableAct(act) {
      view.focus();
      var cell = inTable();
      if (act === 'insert') {
        var rows = [], head = [];
        for (var c = 0; c < 3; c++) head.push('<th>Head ' + (c + 1) + '</th>');
        for (var r = 0; r < 2; r++) rows.push('<tr><td> </td><td> </td><td> </td></tr>');
        document.execCommand('insertHTML', false,
          '<div class="tblwrap nopin"><table><thead><tr>' + head.join('') + '</tr></thead><tbody>' +
          rows.join('') + '</tbody></table></div><p><br></p>');
      } else if (cell) {
        var tr = cell.parentNode, tbl = cell.closest('table');
        var idx = Array.prototype.indexOf.call(tr.children, cell);
        if (act === 'rowAfter') {
          var nr = tr.cloneNode(true);
          Array.prototype.forEach.call(nr.children, function (td) { td.textContent = ' '; });
          tr.parentNode.insertBefore(nr, tr.nextSibling);
        } else if (act === 'rowDel') { if (tbl.querySelectorAll('tr').length > 2) tr.remove(); }
        else if (act === 'colAfter') {
          Array.prototype.forEach.call(tbl.querySelectorAll('tr'), function (row) {
            var ref = row.children[idx];
            var cellEl = document.createElement(ref && ref.tagName === 'TH' ? 'th' : 'td');
            cellEl.textContent = ' ';
            row.insertBefore(cellEl, ref ? ref.nextSibling : null);
          });
        } else if (act === 'colDel') {
          Array.prototype.forEach.call(tbl.querySelectorAll('tr'), function (row) {
            if (row.children.length > 1 && row.children[idx]) row.children[idx].remove();
          });
        }
      }
      onRichInput();
    }
    function onRichInput() {
      store(htmlToMd(view));
      buildRail();
      syncTools();
    }

    /* ── heading rail (the source app's MiniTocSidebar) ──
       Thin bars, one per heading, width by level; hovering the rail opens a
       flyout of titles to its left; the bar for the heading you are reading is
       highlighted. */
    var entries = [];
    function buildRail() {
      entries = [];
      var hs = view.querySelectorAll('h1, h2, h3, h4, h5, h6');
      bars.innerHTML = ''; fly.innerHTML = '';
      Array.prototype.forEach.call(hs, function (h, i) {
        if (!h.id) h.id = key + '-h' + i;
        var lvl = +h.nodeName[1];
        var text = h.textContent.trim();
        var b = document.createElement('div'); b.className = 'doc-bar-i';
        var line = document.createElement('span'); line.className = 'doc-bar-l';
        line.style.width = TOC_BAR[Math.min(lvl, 6) - 1] + 'px';
        b.appendChild(line);
        b.setAttribute('aria-label', 'Scroll to ' + text);
        var a = document.createElement('button');
        a.type = 'button'; a.className = 'doc-fly-i lv' + lvl; a.textContent = text;
        function go(e) { e.preventDefault(); e.stopPropagation(); h.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
        b.addEventListener('click', go); a.addEventListener('click', go);
        b.addEventListener('mouseenter', function () { hover(i, true); });
        a.addEventListener('mouseenter', function () { hover(i, true); });
        bars.appendChild(b); fly.appendChild(a);
        entries.push({ h: h, bar: b, item: a });
      });
      rail.hidden = !entries.length;
      markActive();
    }
    function hover(i, on) {
      entries.forEach(function (e, j) {
        e.bar.classList.toggle('hov', on && j === i);
        e.item.classList.toggle('hov', on && j === i);
      });
    }
    function markActive() {
      if (!entries.length) return;
      var hit = 0;
      entries.forEach(function (e, i) {
        if (e.h.getBoundingClientRect().top <= TOC_FOLD) hit = i;
      });
      entries.forEach(function (e, i) {
        e.bar.classList.toggle('on', i === hit);
        e.item.classList.toggle('on', i === hit);
      });
    }
    var flyTimer = null;
    rail.addEventListener('mouseenter', function () { clearTimeout(flyTimer); fly.hidden = false; });
    rail.addEventListener('mouseleave', function () {
      /* 180ms, MiniTocSidebar.tsx:112 — long enough to cross the gap from
         the rail to the flyout without it vanishing. */
      flyTimer = setTimeout(function () { fly.hidden = true; hover(-1, false); }, 180);
    });
    window.addEventListener('scroll', markActive, { passive: true });

    function paint() {
      var changed = current() !== docSource(doc);
      view.innerHTML = mdToHtml(current());
      flag.textContent = changed ? 'edited' : '';
      doc.classList.toggle('is-edited', changed);
      revert.hidden = !changed;
      srcBtn.textContent = raw() ? 'Rich editor' : 'Raw MD';
      srcBtn.hidden = !editing();
      done.hidden = !editing();
      hint.hidden = editing();
      tools.hidden = !editing() || raw();
      tblbar.hidden = true;
      view.contentEditable = editing() && !raw() ? 'true' : 'false';
      if (editing() && raw()) { ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; }
      buildRail();
    }
    /* MarkdownEditor.tsx:463 — the reading view IS the edit affordance. No
       Edit button: click the sentence you want to change and the caret is there. */
    view.addEventListener('click', function (e) {
      if (editing()) return;
      if (e.target.closest && e.target.closest('a')) return;      /* let links be links */
      var off = offsetFromPoint(view, e.clientX, e.clientY);
      doc.classList.add('editing');
      paint();
      view.focus();
      if (off != null) caretToOffset(view, off);
      syncTools();
    });
    view.addEventListener('keydown', function (e) {
      if (!editing() && e.key === 'Enter') { doc.classList.add('editing'); paint(); view.focus(); return; }
      if (e.key === 'Escape' && editing()) { e.stopPropagation(); finish(); return; }
      if (!(e.metaKey || e.ctrlKey)) return;
      var k = e.key.toLowerCase();
      if (k === 'k') { e.preventDefault(); apply({ link: true }); }
      else if (k === 'enter' || k === 's') { e.preventDefault(); finish(); }
      else if (k === 'b' || k === 'i') setTimeout(onRichInput, 0);
    });
    function finish() {
      if (!raw()) store(htmlToMd(view));
      doc.classList.remove('editing', 'raw');
      paint();
    }
    done.addEventListener('click', finish);
    /* Both modes edit the same markdown string, so the switch is a conversion
       either way and never a merge. */
    srcBtn.addEventListener('click', function () {
      if (raw()) { doc.classList.remove('raw'); paint(); view.focus(); }
      else { store(htmlToMd(view)); ta.value = current(); doc.classList.add('raw'); paint(); ta.focus(); }
    });
    revert.addEventListener('click', function () {
      delete state.edits[key]; save(); ta.value = docSource(doc); paint();
      toast('Reverted to the original');
    });
    view.addEventListener('input', onRichInput);
    view.addEventListener('keyup', syncTools);
    view.addEventListener('mouseup', syncTools);
    ta.addEventListener('input', function () {
      store(ta.value);
      ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px';
    });

    DOC_TOOLS.forEach(function (t, i) {
      if (t.sep) { var s = document.createElement('span'); s.className = 'doc-sep'; tools.appendChild(s); return; }
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'doc-tool' + (t.cls ? ' t-' + t.cls : '');
      b.textContent = t.label; b.dataset.tip = t.tip; b.dataset.i = i;
      /* mousedown, not click: the caret must still be in the document when the
         command runs, and focusing a button collapses the selection. */
      b.addEventListener('mousedown', function (e) { e.preventDefault(); apply(t); });
      tools.appendChild(b);
    });
    TABLE_TOOLS.forEach(function (t) {
      var b = document.createElement('button');
      b.type = 'button'; b.className = 'doc-tool'; b.textContent = t.label; b.dataset.tip = t.tip;
      b.addEventListener('mousedown', function (e) { e.preventDefault(); tableAct(t.act); });
      tblbar.appendChild(b);
    });
    var tclose = document.createElement('button');
    tclose.type = 'button'; tclose.className = 'doc-tool'; tclose.textContent = '×'; tclose.dataset.tip = 'Hide table controls';
    tclose.addEventListener('mousedown', function (e) { e.preventDefault(); tblbar.hidden = true; });
    tblbar.appendChild(tclose);

    bar.appendChild(tools);
    bar.appendChild(hint); bar.appendChild(flag); bar.appendChild(revert);
    bar.appendChild(srcBtn); bar.appendChild(done);
    doc.appendChild(bar); doc.appendChild(tblbar); doc.appendChild(view); doc.appendChild(ta); doc.appendChild(rail);
    ta.value = current();
    paint();
  });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();

})();
