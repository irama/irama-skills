(function () {
  'use strict';
  function init() {
  var BRIEF = document.body.dataset.briefId || location.pathname;
  /* bootstrap chrome if the page didn't include it */
  if (!document.querySelector('.topbar')) {
    var tb = document.createElement('div');
    tb.className = 'topbar';
    tb.innerHTML = '<h1></h1><a class="progress" id="progress"></a>' +
      '<button class="btn icon" id="widthBtn" type="button"></button>' +
      '<button class="btn icon" id="themeBtn" type="button"></button>' +
      '<button class="btn" id="copyBtn" type="button">Copy responses</button>' +
      '<button class="btn" id="downloadBtn" type="button">Download responses</button>';
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
      tbn.textContent = TICON[ui.theme];
      tbn.setAttribute('aria-label', TLABEL[ui.theme] + ' — click to switch');
    }
    if (wbn) {
      wbn.textContent = ui.width === 'full' ? '\u2194' : '\u21F2';
      wbn.setAttribute('aria-label', (ui.width === 'full' ? 'Full width' : 'Fixed width') + ' — click to toggle');
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
  var state = { ticks: {}, answers: {}, notes: {}, comments: [] };
  if (!state.notes) state.notes = {};
  try { state = Object.assign(state, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch {}
  function save() { localStorage.setItem(KEY, JSON.stringify(state)); }
  function toast(msg) {
    var t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    clearTimeout(t._h); t._h = setTimeout(function () { t.classList.remove('show'); }, 1800);
  }

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
      out.comments.push({ selected_text: c.text, near_question: c.near || null, comment: c.comment });
    });
    return JSON.stringify(out, null, 2);
  }
  var isMac = /Mac|iP(hone|ad|od)/.test(navigator.platform || navigator.userAgent);
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
  document.getElementById('copyBtn').addEventListener('click', copyJSON);
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
  if (dlBtn) dlBtn.addEventListener('click', downloadJSON);
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'c') {
      var sel = window.getSelection();
      var active = document.activeElement;
      var inField = active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT');
      if ((!sel || sel.isCollapsed) && !inField) { e.preventDefault(); copyJSON(); }
    }
    if (e.key === 'Escape') closePop();
  });

  /* ── selection comments ── */
  var pop = null, editing = null; // editing = comment object being edited
  function nearestQ(node) {
    var el = node.nodeType === 1 ? node : node.parentElement;
    var q = el && el.closest ? el.closest('section.q, section.brief-section') : null;
    return q ? (q.dataset.q || q.dataset.sec) : null;
  }
  function closePop() { if (pop) { pop.remove(); pop = null; editing = null; } }
  function openPop(x, y, quote, existing) {
    closePop();
    pop = document.createElement('div');
    pop.id = 'cpop';
    pop.innerHTML =
      '<div class="quote">“' + quote.replace(/</g, '&lt;').slice(0, 140) + '”</div>' +
      '<textarea placeholder="Comment — saved locally"></textarea>' +
      '<div class="row">' +
      (existing ? '<button class="btn small danger" data-act="del" type="button">Delete</button>' : '') +
      (existing ? '' : '<button class="btn small" data-act="copy" type="button">Copy text</button>') +
      '<button class="btn small" data-act="cancel" type="button">Cancel</button>' +
      '<button class="btn small" data-act="save" type="button">Save</button></div>' +
      (existing ? '' : '<p class="pophint">Selection is still live — ' + (isMac ? '⌘C' : 'Ctrl-C') + ' copies it. Click the box to comment.</p>');
    document.body.appendChild(pop);
    var vw = document.documentElement.clientWidth;
    var w = pop.offsetWidth;
    var left = Math.max(8, Math.min(x - w / 2, vw - w - 8));
    pop.style.left = left + 'px';
    pop.style.top = (y + 8) + 'px';
    var ta = pop.querySelector('textarea');
    if (existing) { ta.value = existing.comment; ta.focus(); }
    /* On a fresh selection we deliberately do NOT focus the textarea: focusing it
       collapses the document selection, which would break plain copy. The range is
       already cloned into pendingRange, so the user can copy first and comment after. */
    pop.addEventListener('mousedown', function (e) { e.stopPropagation(); });
    pop.addEventListener('click', function (e) {
      var act = e.target.dataset && e.target.dataset.act;
      if (!act) return;
      if (act === 'cancel') closePop();
      if (act === 'copy') { copyText(quote, 'Selected text copied'); closePop(); }
      if (act === 'del' && editing) {
        var m = document.querySelector('mark.cmt[data-cid="' + editing.cid + '"]');
        if (m) m.replaceWith(document.createTextNode(m.textContent));
        state.comments = state.comments.filter(function (c) { return c.cid !== editing.cid; });
        save(); closePop(); toast('Comment deleted');
      }
      if (act === 'save') {
        var val = ta.value.trim();
        if (!val) { closePop(); return; }
        if (editing) { editing.comment = val; save(); closePop(); toast('Comment updated'); }
        else if (pendingRange) {
          var cid = 'c' + Date.now();
          var c = { cid: cid, text: quote, comment: val, near: nearestQ(pendingRange.startContainer) };
          try {
            var mark = document.createElement('mark');
            mark.className = 'cmt'; mark.dataset.cid = cid;
            pendingRange.surroundContents(mark);
          } catch { /* cross-element selection — keep comment unanchored */ }
          state.comments.push(c); save(); closePop(); toast('Comment saved');
          window.getSelection().removeAllRanges();
        }
      }
    });
  }
  var pendingRange = null;
  document.addEventListener('mouseup', function (e) {
    if (pop && pop.contains(e.target)) return;
    var mark = e.target.closest && e.target.closest('mark.cmt');
    setTimeout(function () {
      var sel = window.getSelection();
      if (sel && !sel.isCollapsed && sel.toString().trim() && document.getElementById('briefMain').contains(sel.anchorNode)) {
        pendingRange = sel.getRangeAt(0).cloneRange();
        var r = pendingRange.getBoundingClientRect();
        openPop(r.left + r.width / 2 + window.scrollX, r.bottom + window.scrollY, sel.toString().trim(), null);
      } else if (mark) {
        var c = state.comments.filter(function (x) { return x.cid === mark.dataset.cid; })[0];
        if (c) {
          editing = c;
          var r2 = mark.getBoundingClientRect();
          openPop(r2.left + r2.width / 2 + window.scrollX, r2.bottom + window.scrollY, c.text, c);
        }
      } else if (pop) closePop();
    }, 0);
  });

  /* re-anchor saved comments: text search in text nodes. Whitespace-insensitive —
     Selection.toString() collapses the newlines that source markup leaves in the
     text node, so an exact indexOf misses every multi-line quote. */
  function looseMatcher(text) {
    var esc = text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
    return new RegExp(esc);
  }
  function reanchor() {
    state.comments.forEach(function (c) {
      if (document.querySelector('mark.cmt[data-cid="' + c.cid + '"]')) return;
      var walker = document.createTreeWalker(document.getElementById('briefMain'), NodeFilter.SHOW_TEXT);
      var re = looseMatcher(c.text), n;
      while ((n = walker.nextNode())) {
        var m = re.exec(n.nodeValue);
        if (!m) continue;
        var i = m.index;
        var range = document.createRange();
        range.setStart(n, i); range.setEnd(n, i + m[0].length);
        try {
          var mark = document.createElement('mark');
          mark.className = 'cmt'; mark.dataset.cid = c.cid;
          range.surroundContents(mark);
        } catch {}
        break;
      }
    });
  }

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
