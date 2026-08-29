/* ═══════════════════════════════════════════════════════════════════════════
   DECK COMMENTS — the /html-brief selection-comment contract, for a deck.

   Select text on any slide, or click "Comment slide", write a note, then hit
   Copy to put one JSON payload on the clipboard. The payload carries the deck's
   identity and build stamp, so the JSON alone tells Claude which build was
   reviewed and where each note belongs.

   Self-contained on purpose: one file to copy into any deck-stage deck. It
   injects its own styles and never rewrites slide markup — highlights are
   painted with the CSS Custom Highlight API, so the slide DOM is untouched and
   the overflow audit cannot be disturbed.

   Hidden under ?export, ?audit and print, so it can never reach a leave-behind.
   Comments live in localStorage, keyed by the deck's path.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  if (/[?&](export|audit)\b/.test(location.search)) return;

  function el(t, c) { var e = document.createElement(t); if (c) e.className = c; return e; }
  function meta(n) { var m = document.querySelector('meta[name="' + n + '"]'); return m ? m.content : ''; }
  function norm(s) { return String(s).replace(/\s+/g, ' ').trim(); }

  var DECK = {
    title: (document.title || '').split('·')[0].trim(),
    file: meta('deck-file') || location.pathname,
    source: meta('deck-source') || '',
    build: meta('deck-build') || '',
    buildHash: meta('deck-build-hash') || '',
    resolutions: meta('deck-resolutions') || ''
  };

  var KEY = 'deckComments:' + (DECK.file || location.pathname);
  var state = { comments: [], showMarks: true, showBrand: true, noteEdits: {}, trayOpen: false, hidden: {},
               starred: {}, order: null, dirty: false,
               ovStarredOnly: false, ovShowHidden: true };
  try { state = Object.assign(state, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch (e) {}
  function save() {
    state.labels = labelSnapshot();
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {}
  }

  /* ── re-anchoring: slide identity is the LABEL, never the number ─────────
     Everything the reader stores used to be keyed by slide number, and a deck
     is generated: insert one slide near the front and every number after it
     shifts. The stored records then sit on whichever slide inherited their
     number, which is how a comment written about the pivot ended up painted on
     a bias board, and how a hide set on one slide hid a different one.

     So each save also records `labels` — the number-to-label map of the build
     it was saved against. On load we compare that snapshot with the deck in
     front of us and move every record to wherever its label now lives. A record
     whose label is gone is NOT guessed at: it is parked as an orphan, shown in
     the list under its own heading, and never painted on an innocent slide. */
  function labelSnapshot() {
    var out = {};
    slides().forEach(function (sec, i) { out[i + 1] = idOf(sec); });
    return out;
  }
  function reanchor() {
    var now = {}, dupes = {};
    slides().forEach(function (sec, i) {
      [idOf(sec), labelOf(sec)].forEach(function (k) {
        if (!k) return;
        if (now[k] !== undefined && now[k] !== i + 1) dupes[k] = true;
        else now[k] = i + 1;
      });
    });
    var was = state.labels || null;
    var moved = 0, orphaned = 0;

    // Comments carry their own label already, so they re-anchor on their own.
    (state.comments || []).forEach(function (c) {
      if (!c.slideId && !c.slideLabel) return;         // nothing to anchor to
      var to = (c.slideId && now[c.slideId]) || now[c.slideLabel];
      if (to) { if (c.slide !== to) { c.slide = to; moved++; } delete c.orphan; }
      else if (!c.orphan) { c.orphan = true; orphaned++; }
    });

    // hidden, starred and note edits are keyed by number, so they can only be
    // moved when we know which label that number meant when it was written.
    ['hidden', 'starred', 'noteEdits'].forEach(function (bag) {
      var src = state[bag] || {}, out = {};
      Object.keys(src).forEach(function (n) {
        var label = was ? was[n] : null;
        var to = label && !dupes[label] ? now[label] : null;
        if (to) { out[to] = src[n]; if (+n !== to) moved++; return; }
        if (!was) {
          // Written before this build kept a label snapshot, so its number
          // cannot be resolved to a slide. Typed prose is kept where it is,
          // because losing it costs the reader real work; a stale hide or star
          // is dropped, because an unexplained hidden slide is worse than
          // re-doing one click.
          if (bag === 'noteEdits') out[n] = src[n]; else orphaned++;
          return;
        }
        orphaned++;                                     // its slide is gone: drop it
      });
      state[bag] = out;
    });

    // An order instruction describes a deck that no longer exists.
    if (state.order && was && state.order.length !== slides().length) state.order = null;

    if (moved || orphaned) { state.labels = labelSnapshot(); save(); }
    return { moved: moved, orphaned: orphaned };
  }
  // Any unsent change makes the deck dirty: a comment, a rewritten note, a
  // star, a slide shown or hidden, a new order. Copying the payload clears it,
  // so the count badge answers "does this need resubmitting?" at a glance.
  function touch() { state.dirty = true; state.lastEdit = Date.now(); save(); render(); }

  var HL_OK = typeof CSS !== 'undefined' && CSS.highlights && typeof Highlight === 'function';

  /* ── resolutions ──────────────────────────────────────────────────────────
     Claude ticks a comment off by writing it into the deck's resolutions file,
     which the build embeds as a JSON block. Each entry is keyed by the comment's
     `at` timestamp — so EDITING A COMMENT CHANGES `at` AND THE TICK FALLS OFF,
     which is exactly what should happen when the user changes what they meant. */
  var RES = {};
  (function () {
    var tag = document.getElementById('deck-resolutions');
    if (!tag) return;
    try {
      (JSON.parse(tag.textContent) || {}).resolutions.forEach(function (r) {
        if (r && r.at) RES[r.at] = r;
      });
    } catch (e) {}
  })();
  function resolutionFor(c) { return RES[c.at] || null; }

  /* ── speaker notes ────────────────────────────────────────────────────────
     The deck ships its notes as a JSON block. The tray shows the note for the
     slide on screen, lets it be edited, and carries only the EDITED ones back
     in the payload, so the generator can be updated from the same round trip. */
  var NOTES = [];
  (function () {
    var tag = document.getElementById('speaker-notes');
    if (!tag) return;
    try { NOTES = JSON.parse(tag.textContent) || []; } catch (e) {}
  })();
  function originalNote(n) {
    for (var i = 0; i < NOTES.length; i++) if (NOTES[i].index === n) return NOTES[i].note || '';
    return '';
  }
  function noteFor(n) {
    var e = (state.noteEdits || {})[n];
    return e === undefined ? originalNote(n) : e;
  }
  function statusOf(c) { var r = resolutionFor(c); return r ? (r.status || 'addressed') : 'new'; }
  function isOpen(c) { var st = statusOf(c); return st === 'new' || st === 'question'; }

  /* ── styles ─────────────────────────────────────────────────────────── */
  var css = el('style');
  css.textContent = [
    '.dcx,.dcx *{box-sizing:border-box}',
    '.dcx{position:fixed;z-index:2147483000;font-family:"Inter",system-ui,sans-serif}',
    '.dcx-bar{top:16px;right:16px;display:flex;align-items:center;gap:4px;',
    '  background:rgba(14,10,8,.92);border:1px solid rgba(245,240,232,.16);border-radius:999px;',
    '  padding:6px 8px;box-shadow:0 6px 24px rgba(0,0,0,.4)}',
    '.dcx-bar button{appearance:none;border:0;background:transparent;color:#F5F0E8;cursor:pointer;',
    '  font:500 13px/1 "Inter",system-ui,sans-serif;padding:8px 12px;border-radius:999px;',
    '  display:flex;align-items:center;gap:7px}',
    // display:flex above beats the UA rule for [hidden], so a control that hides
    // itself off a build needs this or it never goes away.
    '.dcx-bar button[hidden]{display:none}',
    '.dcx-bar button:hover{background:rgba(245,240,232,.12)}',
    '.dcx-bar button.off{color:#8B8079}',
    '.dcx-bar .dcx-count{font-family:"JetBrains Mono",monospace;font-size:12px;color:#0E0A08;',
    '  background:#D0B561;border-radius:999px;padding:3px 8px;min-width:22px;text-align:center}',
    '.dcx-bar .dcx-count.zero{background:rgba(245,240,232,.18);color:#F5F0E8}',
    '.dcx-bar .sep{width:1px;height:20px;background:rgba(245,240,232,.16);margin:0 4px}',
    '.dcx-pop{background:#0E0A08;border:1px solid rgba(245,240,232,.2);border-radius:10px;',
    '  padding:12px;width:392px;box-shadow:0 10px 40px rgba(0,0,0,.55)}',
    '.dcx-pop .q{font:400 12px/1.5 "JetBrains Mono",monospace;color:#D0B561;max-height:66px;',
    '  overflow:hidden;margin-bottom:9px;border-left:2px solid #A93D1A;padding-left:9px}',
    '.dcx-pop textarea{width:100%;height:94px;resize:vertical;background:#1A1614;color:#F5F0E8;',
    '  border:1px solid rgba(245,240,232,.2);border-radius:6px;padding:9px;',
    '  font:400 14px/1.45 "Inter",system-ui,sans-serif}',
    '.dcx-pop textarea:focus{outline:2px solid #A93D1A;outline-offset:0}',
    '.dcx-pop .hint{font:400 11px/1.4 "Inter",sans-serif;color:#8B8079;margin:8px 2px 0}',
    '.dcx-row{display:flex;gap:8px;justify-content:flex-end;align-items:center;margin-top:9px}',
    '.dcx-row button{appearance:none;border:1px solid rgba(245,240,232,.2);background:transparent;',
    '  color:#F5F0E8;border-radius:6px;padding:7px 13px;cursor:pointer;',
    '  font:500 13px/1 "Inter",sans-serif}',
    '.dcx-row button:hover{background:rgba(245,240,232,.1)}',
    '.dcx-row button.pri{background:#A93D1A;border-color:#A93D1A}',
    '.dcx-row button.ghost{margin-right:auto;border-color:rgba(245,240,232,.14);color:#B5A899}',
    '.dcx-row button.danger{background:#A93D1A;border-color:#A93D1A;color:#fff}',
    '.dcx-panel{top:60px;right:16px;width:430px;max-height:72vh;overflow:auto;',
    '  background:rgba(14,10,8,.97);border:1px solid rgba(245,240,232,.16);border-radius:10px;',
    '  padding:10px;box-shadow:0 10px 40px rgba(0,0,0,.5)}',
    '.dcx-panel .item{border-top:1px solid rgba(245,240,232,.12);padding:11px 4px;cursor:pointer;',
    '  border-radius:6px}',
    '.dcx-panel .item:hover{background:rgba(245,240,232,.06)}',
    '.dcx-panel .item:first-child{border-top:0}',
    '.dcx-panel .slide{font:500 11px/1 "JetBrains Mono",monospace;letter-spacing:.14em;',
    '  text-transform:uppercase;color:#D0B561}',
    '.dcx-panel .quote{font:400 12px/1.5 "JetBrains Mono",monospace;color:#8B8079;margin-top:6px;',
    '  border-left:2px solid #A93D1A;padding-left:8px}',
    '.dcx-panel .body{font:400 14px/1.45 "Inter",sans-serif;color:#F5F0E8;margin-top:7px;',
    '  white-space:pre-wrap}',
    '.dcx-panel .acts{float:right;display:flex;gap:6px;align-items:center}',
    '.dcx-panel .acts span{color:#8B8079;font:500 11px/1 "Inter",sans-serif;cursor:pointer;',
    '  border:1px solid rgba(245,240,232,.16);border-radius:5px;padding:5px 8px}',
    '.dcx-panel .acts span:hover{color:#F5F0E8}',
    '.dcx-panel .acts span.danger{color:#fff;background:#A93D1A;border-color:#A93D1A}',
    '.dcx-panel .item.done{opacity:.5}',
    '.dcx-panel .tick{font:600 11px/1 "JetBrains Mono",monospace;letter-spacing:.1em;',
    '  border-radius:5px;padding:5px 8px;margin-left:8px}',
    '.dcx-panel .tick.addressed{background:rgba(208,181,97,.2);color:#D0B561}',
    '.dcx-panel .tick.wontfix{background:rgba(245,240,232,.12);color:#B5A899}',
    '.dcx-panel .tick.question{background:rgba(169,61,26,.25);color:#E0876A}',
    '.dcx-panel .resnote{font:400 12px/1.5 "Inter",sans-serif;color:#8B8079;margin-top:6px}',
    '.dcx-panel .empty{color:#8B8079;font-size:13px;padding:16px 6px;text-align:center;line-height:1.5}',
    '.dcx-tray{left:0;right:0;bottom:0;background:rgba(14,10,8,.97);',
    '  border-top:1px solid rgba(245,240,232,.18);padding:14px 20px 16px;',
    '  box-shadow:0 -8px 30px rgba(0,0,0,.45);max-height:42vh;overflow:auto}',
    '.dcx-tray .hdr{display:flex;align-items:center;gap:12px;margin-bottom:9px}',
    '.dcx-tray .hdr b{font:500 11px/1 "JetBrains Mono",monospace;letter-spacing:.18em;',
    '  text-transform:uppercase;color:#D0B561}',
    '.dcx-tray .hdr .edited{font:500 10px/1 "JetBrains Mono",monospace;letter-spacing:.14em;',
    '  color:#0E0A08;background:#D0B561;border-radius:4px;padding:4px 7px}',
    '.dcx-tray .hdr .sp{margin-left:auto;display:flex;gap:8px}',
    '.dcx-tray .hdr .sp span{font:500 11px/1 "Inter",sans-serif;color:#8B8079;cursor:pointer;',
    '  border:1px solid rgba(245,240,232,.16);border-radius:5px;padding:6px 9px}',
    '.dcx-tray .hdr .sp span:hover{color:#F5F0E8}',
    '.dcx-tray textarea{width:100%;min-height:104px;resize:vertical;background:#1A1614;',
    '  color:#F5F0E8;border:1px solid rgba(245,240,232,.2);border-radius:6px;padding:10px;',
    '  font:400 14px/1.55 "Inter",system-ui,sans-serif}',
    '.dcx-tray textarea:focus{outline:2px solid #A93D1A}',
    '.dcx-toast{bottom:24px;left:50%;transform:translateX(-50%);background:#D0B561;color:#0E0A08;',
    '  font:600 13px/1 "Inter",sans-serif;padding:11px 18px;border-radius:999px;opacity:0;',
    '  transition:opacity .18s;pointer-events:none}',
    '.dcx-toast.show{opacity:1}',
    '.dcx-bar button.on{background:#A93D1A}',
    '.dcx-pan .item.orphan{opacity:.75;border-left:3px solid #D0B561;padding-left:9px}',
    '.dcx-panel .item.orphanrow{cursor:default;background:rgba(208,181,97,.10);',
    '  border-left:3px solid #D0B561;padding-left:9px}',
    '.dcx-pan .item.orphan .slide{color:#D0B561}',
    '.dcx-hidden-badge{top:16px;left:16px;font:600 11px/1 "JetBrains Mono",monospace;',
    '  letter-spacing:.18em;color:#0E0A08;background:#D0B561;border-radius:4px;padding:7px 11px}',
    'deck-stage > section[data-hidden]{filter:brightness(.3) grayscale(.6)}', /* dim = darken, never a light wash */
    'body.dcx-performing .dcx{display:none!important}',
    'body.dcx-performing deck-stage > section[data-hidden]{opacity:1;filter:none}',
    /* ── overview ─────────────────────────────────────────────────────── */
    '.dcx-ov{inset:0;background:rgba(10,8,6,.99);overflow:auto;padding:0 24px 48px}',
    '.dcx-ovhdr{position:sticky;top:0;z-index:2;display:flex;align-items:baseline;gap:10px 14px;',
    '  flex-wrap:wrap;background:rgba(10,8,6,.99);padding:18px 2px 14px;margin-bottom:6px}',
    '.dcx-ovhdr b{font:500 11px/1 "JetBrains Mono",monospace;letter-spacing:.18em;',
    '  text-transform:uppercase;color:#D0B561}',
    '.dcx-ovhdr .hint{font:400 12px/1.4 "Inter",sans-serif;color:#8B8079;max-width:640px;',
    '  flex:1 1 240px;min-width:0}',
    '.dcx-ovhdr .sp{margin-left:auto;display:flex;flex-wrap:wrap;gap:8px;align-self:center}',
    '.dcx-ovhdr .sp span{font:500 11px/1 "Inter",sans-serif;color:#B5A899;cursor:pointer;',
    '  border:1px solid rgba(245,240,232,.18);border-radius:5px;padding:7px 10px}',
    '.dcx-ovhdr .sp span:hover{color:#F5F0E8;background:rgba(245,240,232,.08)}',
    '.dcx-ovhdr .sp span:focus-visible{outline:3px solid #D0B561;outline-offset:2px}',
    '.dcx-ovhdr .sp span[aria-pressed="true"]{color:#0E0A08;background:#D0B561;',
    '  border-color:#D0B561}',
    '.dcx-ovhdr .build{font:400 10px/1.5 "JetBrains Mono",monospace;letter-spacing:.06em;',
    '  color:#7A6E60;margin-left:14px;white-space:nowrap}',
    '.dcx-ovhdr .count{font:500 11px/1 "JetBrains Mono",monospace;letter-spacing:.12em;',
    '  color:#B5A899;white-space:nowrap}',
    '.dcx-ovgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));',
    '  gap:18px;max-width:1520px;margin:0 auto}',
    '.dcx-ovtile{position:relative;border:2px solid rgba(245,240,232,.14);border-radius:9px;',
    '  background:#0E0A08;padding:8px;cursor:pointer}',
    '.dcx-ovtile:hover{border-color:rgba(245,240,232,.34)}',
    '.dcx-ovtile:focus-visible{outline:3px solid #D0B561;outline-offset:3px}',
    '.dcx-ovtile.starred{border-color:#D0B561;box-shadow:0 0 0 1px rgba(208,181,97,.4)}',
    '.dcx-ovtile.dragging{opacity:.35}',
    '.dcx-ovtile.over{border-color:#A93D1A}',
    '.dcx-ovtop{display:flex;align-items:center;gap:6px;margin-bottom:7px}',
    '.dcx-ovtop .pos{font:600 12px/1 "JetBrains Mono",monospace;color:#F5F0E8}',
    '.dcx-ovtop .pos em{font-style:normal;color:#D0B561;font-size:10px;letter-spacing:.1em}',
    '.dcx-ovtop .btns{margin-left:auto;display:flex;gap:4px}',
    '.dcx-ovtop button{appearance:none;border:1px solid rgba(245,240,232,.18);background:transparent;',
    '  color:#F5F0E8;border-radius:5px;padding:4px 7px;cursor:pointer;font:400 13px/1 "Inter",sans-serif;',
    '  position:relative}',
    '.dcx-ovtop button:hover{background:rgba(245,240,232,.12)}',
    '.dcx-ovtop button:focus-visible{outline:2px solid #D0B561;outline-offset:2px}',
    '.dcx-ovtop button[aria-pressed="true"]{background:#D0B561;border-color:#D0B561;color:#0E0A08}',
    '.dcx-ovtop button i{font-style:normal;font:600 9px/1 "JetBrains Mono",monospace;',
    '  margin-left:3px;color:#D0B561}',
    '.dcx-ovthumb{position:relative;overflow:hidden;border-radius:5px;background:#1A1614}',
    '.dcx-ovstage{position:absolute;top:0;left:0;transform-origin:0 0;pointer-events:none}',
    '.dcx-ovtile.ishidden .dcx-ovthumb{filter:brightness(.3) grayscale(.6)}',
    '.dcx-ovlabel{font:400 11px/1.35 "Inter",sans-serif;color:#B5A899;margin-top:7px}',
    '.dcx-ovflags{display:flex;flex-wrap:wrap;align-items:center;gap:4px;margin-top:5px;',
    '  min-height:1px}',
    '.dcx-ovflags span{display:inline-block;width:auto;height:auto;',
    '  font:600 8px/1 "JetBrains Mono",monospace;letter-spacing:.09em;',
    '  border-radius:2px;padding:1px 4px 2px}',
    '.dcx-ovflags .dcx-f-st{background:#D0B561;color:#0E0A08}',
    '.dcx-ovflags .dcx-f-hd{background:rgba(245,240,232,.16);color:#F5F0E8}',
    '.dcx-ovflags .dcx-f-mv{background:rgba(169,61,26,.35);color:#E0876A}',
    '.dcx-ovflags .dcx-f-pr{background:rgba(208,181,97,.9);color:#0E0A08}',
    '.dcx-ovflags .dcx-f-cm{background:rgba(208,181,97,.22);color:#D0B561}',
    '.dcx-ovflags .dcx-f-fo{background:rgba(245,240,232,.16);color:#F5F0E8}',
    /* Kept on screen against the filter, because the reader is acting on it. */
    '.dcx-ovtile.filtered{border-style:dashed;opacity:.72}',
    '.dcx-noteedit{position:fixed;z-index:2147483647;right:26px;bottom:26px;width:520px;',
    '  background:#141210;border:1px solid rgba(245,240,232,.22);border-radius:10px;',
    '  padding:13px;box-shadow:0 18px 60px rgba(0,0,0,.6)}',
    '.dcx-noteedit .hd{display:flex;justify-content:space-between;align-items:center;',
    '  font:400 12px/1.4 "JetBrains Mono",monospace;color:#B5A899;margin-bottom:9px}',
    '.dcx-noteedit .edited{font-size:9px;letter-spacing:.13em;color:#0E0A08;',
    '  background:#D0B561;border-radius:3px;padding:2px 5px 3px}',
    '.dcx-noteedit textarea{width:100%;height:190px;resize:vertical;background:#1A1614;',
    '  color:#F5F0E8;border:1px solid rgba(245,240,232,.2);border-radius:6px;padding:9px;',
    '  font:400 14px/1.5 "Inter",system-ui,sans-serif}',
    '.dcx-noteedit .ft{display:flex;justify-content:space-between;margin-top:9px;',
    '  font:400 12px/1 "JetBrains Mono",monospace}',
    '.dcx-noteedit .ft span{cursor:pointer;color:#B5A899;padding:5px 9px;border-radius:5px}',
    '.dcx-noteedit .ft span:hover{background:rgba(245,240,232,.1);color:#F5F0E8}',
    '.dcx-ovempty{grid-column:1/-1;color:#B5A899;font:400 14px/1.6 "Inter",sans-serif;',
    '  text-align:center;padding:48px 12px}',
    /* Dirty: gold PLUS a filled dot and a worded title, because colour alone
       is not a signal a colour-blind reader can read. */
    '.dcx-bar .dcx-count.dirty{background:#D0B561;color:#0E0A08;font-weight:700}',
    '.dcx-panel .item.dirtyrow{cursor:default;background:rgba(208,181,97,.12);',
    '  border:1px solid rgba(208,181,97,.4);border-radius:7px;margin-bottom:8px}',
    '.dcx-panel .item.dirtyrow .t{font:600 11px/1 "JetBrains Mono",monospace;letter-spacing:.14em;',
    '  color:#D0B561}',
    '.dcx-panel .item.dirtyrow .w{font:400 13px/1.45 "Inter",sans-serif;color:#F5F0E8;margin-top:6px}',
    '@media print{.dcx{display:none!important}}'
  ].join('\n');
  document.head.appendChild(css);

  // Painted, not wrapped: no element is inserted, so nothing reflows.
  if (HL_OK) {
    var hlCss = el('style');
    hlCss.textContent =
      '::highlight(deck-comment){background:rgba(208,181,97,.30);' +
      'text-decoration:underline;text-decoration-color:#D0B561;text-underline-offset:4px}';
    document.head.appendChild(hlCss);
  }

  /* ── chrome ─────────────────────────────────────────────────────────── */
  var bar = el('div', 'dcx dcx-bar');
  bar.innerHTML =
    /* Grouped by what the control acts on: this slide's content, then this
       slide's state, then the deck, then the round trip. */
    '<button data-a="slide" title="Write the slide comment for this slide">&#128172; Slide comment</button>' +
    (HL_OK ? '<button data-a="marks" title="Show or hide comment highlights">&#128065;</button>' : '') +
    '<button data-a="brand" title="Show or hide the branding on every slide">&#9670;</button>' +
    '<button data-a="notes" title="Speaker notes for this slide">&#128221; Notes</button>' +
    '<span class="sep"></span>' +
    '<button data-a="star" aria-pressed="false" title="Star this slide (S)">&#9734;</button>' +
    '<button data-a="hide" title="Hide this slide from performance mode">&#128683;</button>' +
    '<button data-a="primary" title="Make this state the page that prints">&#9671;</button>' +
    '<span class="sep"></span>' +
    '<button data-a="overview" title="Overview: every slide, with star, hide and reorder">&#9638; Overview</button>' +
    '<button data-a="perform" title="Performance mode: full screen, no editing, Esc to exit">&#9654; Present</button>' +
    '<span class="sep"></span>' +
    '<button data-a="list" title="Show all comments"><span class="dcx-count zero">0</span></button>' +
    '<button data-a="copy" title="Copy the comments JSON for Claude">&#128203; Copy</button>';
  document.body.appendChild(bar);

  var panel = el('div', 'dcx dcx-panel');
  panel.style.display = 'none';
  document.body.appendChild(panel);

  var tray = el('div', 'dcx dcx-tray');
  tray.style.display = 'none';
  tray.innerHTML = '<div class="hdr"><b></b><span class="edited" hidden>EDITED</span>' +
    '<span class="sp"><span data-a="revert">Revert</span><span data-a="close">Close</span></span></div>' +
    '<textarea placeholder="Speaker notes for this slide"></textarea>';
  document.body.appendChild(tray);
  tray.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    e.preventDefault(); e.stopPropagation();
    state.trayOpen = false; save(); tray.style.display = 'none';
  }, true);
  ['keydown', 'keyup', 'keypress'].forEach(function (t) {
    tray.addEventListener(t, function (e) { e.stopPropagation(); }, true);
  });
  tray.addEventListener('mousedown', function (e) { e.stopPropagation(); });
  tray.addEventListener('input', function (e) {
    if (e.target.tagName !== 'TEXTAREA') return;
    var cur = currentSlide();
    var v = e.target.value;
    if (v === originalNote(cur.index)) delete state.noteEdits[cur.index];
    else state.noteEdits[cur.index] = v;
    touch(); paintTray(true);
  });
  tray.addEventListener('click', function (e) {
    var a = e.target.dataset && e.target.dataset.a;
    if (a === 'close') { state.trayOpen = false; save(); tray.style.display = 'none'; }
    if (a === 'revert') {
      delete state.noteEdits[currentSlide().index]; touch(); paintTray();
      say('Note reverted');
    }
  });

  /* ── hidden slides and performance mode ──────────────────────────────────
     A hidden slide is dimmed here and skipped when presenting. The state lives
     in localStorage and rides back in the payload, so the generator can be told
     to mark it hidden permanently rather than it living only in one browser. */
  // The generator's marking is the default, not the verdict. state.hidden[n] is
  // a tri-state override: true hides, false shows, absent means "whatever the
  // deck says". Without that a source-hidden slide could never be shown again,
  // which is what shipped and was wrong.
  function srcHidden(sec) { return !!sec && sec.hasAttribute('data-hidden-src'); }
  function effHidden(n, sec) {
    var o = state.hidden[n];
    return o === undefined ? srcHidden(sec) : !!o;
  }

  function applyHidden() {
    slides().forEach(function (sec, i) {
      if (effHidden(i + 1, sec)) sec.setAttribute('data-hidden', '');
      else sec.removeAttribute('data-hidden');
    });
    var cur = currentSlide();
    var hb = bar.querySelector('[data-a="hide"]');
    if (hb) hb.classList.toggle('on', !!cur.node && cur.node.hasAttribute('data-hidden'));
    badge.style.display = (cur.node && cur.node.hasAttribute('data-hidden') && !performing)
      ? 'block' : 'none';
  }

  var performing = false, lastDir = 1;

  function goToStage(i) {
    var stage = document.querySelector('deck-stage');
    if (stage && typeof stage.goTo === 'function') stage.goTo(i);
  }

  // Skip a hidden slide while presenting, in whichever direction we were going.
  function skipHidden() {
    if (!performing) return;
    var all = slides(), cur = currentSlide();
    var i = cur.index - 1;
    var guard = 0;
    while (all[i] && all[i].hasAttribute('data-hidden') && guard++ < all.length) {
      i += lastDir;
      if (i < 0 || i >= all.length) { i -= lastDir; break; }
    }
    if (i !== cur.index - 1) goToStage(i);
  }

  function setPerforming(on) {
    performing = on;
    document.body.classList.toggle('dcx-performing', on);
    if (on) {
      closePop();
      closeOv();
      panel.style.display = 'none';
      if (document.documentElement.requestFullscreen) {
        document.documentElement.requestFullscreen().catch(function () {});
      }
      skipHidden();
    } else if (document.fullscreenElement && document.exitFullscreen) {
      document.exitFullscreen().catch(function () {});
    }
    applyHidden();
  }

  document.addEventListener('keydown', function (e) {
    // An editor owns its own keys. Escape inside a comment must close the
    // comment, not drop the presenter out of full screen.
    if (e.target && e.target.closest &&
        e.target.closest('.dcx-pop,.dcx-tray,.dcx-ov')) return;
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') lastDir = 1;
    if (e.key === 'ArrowLeft' || e.key === 'PageUp') lastDir = -1;
    if (e.key === 'Escape' && performing) { e.stopPropagation(); setPerforming(false); }
    if (performing || ovOpen()) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    var t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || ''))) return;
    // Star the slide you are on, from that slide. The bar button says the same
    // thing with the mouse, and carries this key on its label.
    if (e.key === 's' || e.key === 'S') {
      e.preventDefault(); e.stopPropagation();
      return toggleStar(currentSlide().index);
    }
    // The overview sits before slide 1, so going left off the front opens it.
    if ((e.key === 'ArrowLeft' || e.key === 'PageUp') && currentSlide().index === 1) {
      e.preventDefault(); e.stopPropagation();
      return openOv();
    }
  }, true);
  document.addEventListener('fullscreenchange', function () {
    if (!document.fullscreenElement && performing) setPerforming(false);
  });

  function paintTray(keepValue) {
    if (!state.trayOpen) { tray.style.display = 'none'; return; }
    tray.style.display = 'block';
    var cur = currentSlide();
    tray.querySelector('.hdr b').textContent =
      'Slide ' + cur.index + ' \u00b7 ' + (labelOf(cur.node) || '—');
    tray.querySelector('.edited').hidden = state.noteEdits[cur.index] === undefined;
    if (!keepValue) tray.querySelector('textarea').value = noteFor(cur.index);
  }

  var badge = el('div', 'dcx dcx-hidden-badge');
  badge.textContent = 'HIDDEN';
  badge.style.display = 'none';
  document.body.appendChild(badge);

  var toast = el('div', 'dcx dcx-toast');
  document.body.appendChild(toast);

  function say(m) {
    toast.textContent = m; toast.classList.add('show');
    clearTimeout(say._h); say._h = setTimeout(function () { toast.classList.remove('show'); }, 1700);
  }

  /* ── which slide are we on ──────────────────────────────────────────── */
  function slides() {
    return Array.prototype.slice.call(document.querySelectorAll('deck-stage > section'));
  }
  function currentSlide() {
    // deck-stage stacks every slide in one box and switches opacity, so
    // geometry cannot say which is showing. It marks the live one instead.
    var all = slides();
    var live = document.querySelector('deck-stage > section[data-deck-active]');
    if (live) return { index: all.indexOf(live) + 1, node: live };
    var stage = document.querySelector('deck-stage');
    var i = stage && typeof stage.index === 'number' ? stage.index : 0;
    return { index: i + 1, node: all[i] || all[0] };
  }
  function labelOf(node) {
    return ((node && node.dataset.screenLabel) || '').replace(/^\d+\s+/, '');
  }
  /* A slide's IDENTITY, in order of trust: the id its generator minted, then its
     label. An id is an address and never changes; a label is a heading and gets
     rewritten, which is how a comment about "The stamp" orphaned when that slide
     was renamed "Confabulation stamp". A deck that emits data-slide-id keeps its
     comments across renames; one that does not still re-anchors by label. */
  function idOf(node) {
    return (node && node.dataset.slideId) || labelOf(node) || '';
  }
  /* The MINTED id only, with no label fallback. idOf() falls back to the label
     so an unminted deck can still re-anchor, but the payload must not: it tells
     the agent that slideId is an address it can search the generator for, and a
     heading dressed as an address sends it to the wrong slide. A deck that mints
     nothing carries no slideId at all, and the instruction says to fall back to
     the number and the label. */
  function mintedId(node) { return (node && node.dataset.slideId) || undefined; }
  function deckMintsIds() {
    return slides().some(function (s) { return !!s.dataset.slideId; });
  }
  function slideNode(n) { return slides()[n - 1] || null; }

  /* ── anchoring: find a quote inside a slide, without touching the DOM ── */
  function textNodes(root) {
    var w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: function (n) {
        if (!n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        var p = n.parentElement;
        if (!p || p.closest('.dcx')) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var out = [], n;
    while ((n = w.nextNode())) out.push(n);
    return out;
  }

  // Flatten the slide to one whitespace-normalised string with an index map
  // back into the text nodes, so a quote spanning several elements still
  // resolves to a single Range.
  function flatten(root) {
    var nodes = textNodes(root), s = '', map = [];
    nodes.forEach(function (n) {
      var v = n.nodeValue;
      for (var i = 0; i < v.length; i++) {
        var ch = /\s/.test(v[i]) ? ' ' : v[i];
        if (ch === ' ' && s.slice(-1) === ' ') continue;
        s += ch; map.push({ node: n, offset: i });
      }
    });
    return { text: s, map: map };
  }

  function findRange(root, quote, nth) {
    if (!root || !quote) return null;
    var f = flatten(root), q = norm(quote);
    var from = 0, at = -1, seen = 0;
    while ((at = f.text.indexOf(q, from)) !== -1) {
      if (seen === (nth || 0)) break;
      seen++; from = at + 1;
    }
    if (at === -1 || !f.map[at] || !f.map[at + q.length - 1]) return null;
    var a = f.map[at], b = f.map[at + q.length - 1];
    var r = document.createRange();
    r.setStart(a.node, a.offset);
    r.setEnd(b.node, b.offset + 1);
    return r;
  }

  function occurrenceOf(root, range) {
    var f = flatten(root), q = norm(range.toString());
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

  /* ── painting the highlights ────────────────────────────────────────── */
  var liveRanges = [];   // [{cid, range}] for the slide on screen
  function paint() {
    if (!HL_OK) return;
    liveRanges = [];
    CSS.highlights.delete('deck-comment');
    if (!state.showMarks) return;
    var cur = currentSlide();
    var hl = new Highlight();
    var any = false;
    state.comments.forEach(function (c) {
      if (c.slide !== cur.index || c.target !== 'selection') return;
      if (c.orphan) return;     // its slide is gone; painting it would be a lie
      if (!isOpen(c)) return;   // ticked off, so stop drawing attention to it
      var r = findRange(cur.node, c.quote, c.nth || 0);
      if (!r) return;
      hl.add(r); liveRanges.push({ cid: c.cid, range: r }); any = true;
    });
    if (any) CSS.highlights.set('deck-comment', hl);
  }

  /* ── popover ────────────────────────────────────────────────────────── */
  var pop = null, popReturn = null;
  function closePop() {
    if (!pop) return;
    pop.remove(); pop = null;
    // Focus goes back where it came from, so commenting from an overview tile
    // leaves the keyboard exactly where it was.
    var back = popReturn; popReturn = null;
    if (back) back();
  }

  function openPop(x, y, ctx, existing, onClosed) {
    closePop();
    pop = el('div', 'dcx dcx-pop');
    pop.style.left = Math.max(12, Math.min(x, innerWidth - 404)) + 'px';
    pop.style.top = Math.max(12, Math.min(y, innerHeight - 250)) + 'px';
    pop.innerHTML =
      (ctx.quote ? '<div class="q"></div>' : '') +
      '<textarea placeholder="What should change here, or what do you want to discuss?"></textarea>' +
      '<div class="dcx-row">' +
      (existing ? '<button class="ghost" data-a="del">Delete</button>'
                : (ctx.quote ? '<button class="ghost" data-a="copytext">Copy text</button>' : '')) +
      '<button data-a="cancel">Cancel</button>' +
      '<button class="pri" data-a="save">Save</button></div>' +
      (existing || !ctx.quote ? ''
        : '<p class="hint">Your selection stays live. Copy it, or click the box to comment.</p>');
    popReturn = onClosed || null;
    if (ctx.quote) pop.querySelector('.q').textContent = ctx.quote;
    var ta = pop.querySelector('textarea');
    if (existing) ta.value = existing.comment;
    document.body.appendChild(pop);

    // Never autofocus on a fresh SELECTION: focusing collapses it and kills
    // Cmd-C. An existing comment, or a whole-slide comment, has no selection to
    // protect, and must take the keyboard or Escape lands on whatever opened it.
    if (existing || !ctx.quote) setTimeout(function () { ta.focus(); }, 10);

    // Escape abandons the edit, Cmd+Enter (Ctrl+Enter off a Mac) saves and
    // closes. Registered before the swallowing listener below, on the same
    // node and phase, so it still runs.
    pop.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        e.preventDefault(); e.stopPropagation();
        return closePop();
      }
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault(); e.stopPropagation();
        return commit();
      }
    }, true);

    // deck-stage listens for arrows and space on document — a keystroke meant
    // for the textarea must never move the deck.
    ['keydown', 'keyup', 'keypress'].forEach(function (t) {
      pop.addEventListener(t, function (e) { e.stopPropagation(); }, true);
    });
    pop.addEventListener('mousedown', function (e) { e.stopPropagation(); });

    function commit() {
      var body = ta.value.trim();
      if (!body) return closePop();
      if (existing) { existing.comment = body; existing.at = new Date().toISOString(); }
      else {
        state.comments.push({
          cid: 'c' + Date.now() + Math.floor(Math.random() * 1000),
          slide: ctx.slide, slideLabel: ctx.slideLabel, slideId: ctx.slideId,
          target: ctx.quote ? 'selection' : 'slide',
          quote: ctx.quote || '', nth: ctx.nth || 0,
          comment: body, at: new Date().toISOString()
        });
      }
      touch(); paint(); renderOv(); closePop(); say('Comment saved');
    }

    var armed = false;   // delete needs two clicks
    pop.addEventListener('click', function (e) {
      var btn = e.target.closest('button');
      if (!btn) return;
      var a = btn.dataset.a;
      if (a === 'cancel') return closePop();
      if (a === 'copytext') return copyText(ctx.quote, 'Selected text copied');
      if (a === 'del') {
        if (!armed) {
          armed = true;
          btn.textContent = 'Confirm delete';
          btn.classList.remove('ghost'); btn.classList.add('danger');
          return;
        }
        remove(existing.cid); closePop(); return;
      }
      commit();
    });
  }

  function remove(cid) {
    state.comments = state.comments.filter(function (c) { return c.cid !== cid; });
    touch(); paint(); renderOv(); say('Comment deleted');
  }

  function editComment(c, onClosed) {
    var r = null;
    if (c.target === 'selection') {
      var node = slideNode(c.slide);
      if (node) r = findRange(node, c.quote, c.nth || 0);
    }
    var x = innerWidth - 460, y = 90;
    if (r) { var b = r.getBoundingClientRect(); x = b.left; y = b.bottom + 10; }
    if (ovOpen()) { x = Math.max(12, innerWidth / 2 - 196); y = 120; }
    openPop(x, y, { quote: c.quote, slide: c.slide, slideLabel: c.slideLabel,
                    slideId: c.slideId, nth: c.nth },
      c, onClosed);
  }

  /* ── selection → comment ────────────────────────────────────────────── */
  document.addEventListener('mouseup', function (e) {
    if (pop && pop.contains(e.target)) return;
    if (bar.contains(e.target) || panel.contains(e.target)) return;
    setTimeout(function () {
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount) return;
      var text = norm(String(sel));
      // One character is a legitimate selection on this deck — the letters on
      // the board are single glyphs. isCollapsed already filters stray clicks.
      if (!text) return;
      var cur = currentSlide();
      if (!cur.node.contains(sel.anchorNode)) return;
      var nth = 0;
      try { nth = occurrenceOf(cur.node, sel.getRangeAt(0)); } catch (err) {}
      openPop(e.clientX + 14, e.clientY + 14,
        { quote: text, slide: cur.index, slideLabel: labelOf(cur.node),
        slideId: idOf(cur.node), nth: nth }, null);
    }, 0);
  });

  // Click a painted highlight to edit it. No element exists to click, so hit
  // test the caret position against the ranges we painted.
  document.addEventListener('click', function (e) {
    if (!liveRanges.length) return;
    if (bar.contains(e.target) || panel.contains(e.target) || (pop && pop.contains(e.target))) return;
    var sel = window.getSelection();
    if (sel && !sel.isCollapsed) return;         // a drag-select, not a click
    var caret = document.caretRangeFromPoint
      ? document.caretRangeFromPoint(e.clientX, e.clientY) : null;
    if (!caret) return;
    for (var i = 0; i < liveRanges.length; i++) {
      var r = liveRanges[i].range;
      if (r.comparePoint(caret.startContainer, caret.startOffset) === 0) {
        var c = state.comments.filter(function (x) { return x.cid === liveRanges[i].cid; })[0];
        if (c) { e.preventDefault(); e.stopPropagation(); editComment(c); }
        return;
      }
    }
  }, true);

  // Click anywhere outside closes the popover and the list.
  document.addEventListener('mousedown', function (e) {
    if (pop && !pop.contains(e.target) && !bar.contains(e.target)) closePop();
    if (panel.style.display !== 'none' && !panel.contains(e.target) && !bar.contains(e.target)
        && !(pop && pop.contains(e.target))) {
      panel.style.display = 'none';
    }
  });

  /* ── stars, order and the overview ───────────────────────────────────────
     The overview shows the REAL slides, deep-cloned and scaled, so it cannot
     drift from the deck. Clones stay in the light DOM, where the deck's own
     CSS still reaches them; the only rules they lose are the ones scoped to
     `deck-stage`, and those are copied onto `.dcx-ovstage` on first open.

     Reordering is an INSTRUCTION, never a mutation. state.order is a
     permutation of the slide numbers in this build, and it rides back in the
     payload for the agent to apply to the generator. Nothing in the file moves. */
  function starredList() {
    return Object.keys(state.starred || {}).map(Number)
      .filter(function (n) { return !!slideNode(n); })
      .sort(function (a, b) { return a - b; });
  }
  /* ── order ────────────────────────────────────────────────────────────
     A reorder used to live only in the overview: the grid showed the new order
     and the deck still flowed in the old one, which is a lie the reader has no
     reason to expect. So a reorder now MOVES THE SECTIONS in the light DOM.
     deck-stage indexes its children, so the flow, the thumbnails, presentation
     mode and the page numbers all follow from one move.

     It is still an instruction, not a mutation of the file: the deck is
     generated, so the order rides back in the payload for the generator to
     apply. BUILD_IDS is the order the file was built in, captured once at load
     before anything moves, and it is what `wasSlide` is measured against.
     state.orderIds is the order the reader wants, by slide id, so it survives a
     rebuild and self-clears the moment the generator catches up. */
  var BUILD_IDS = slides().map(idOf);

  function identity() {
    var a = [], n = slides().length;
    for (var i = 1; i <= n; i++) a.push(i);
    return a;
  }
  function domIds() { return slides().map(idOf); }
  function orderChanged() {
    var now = domIds();
    return now.length === BUILD_IDS.length &&
           now.some(function (id, i) { return id !== BUILD_IDS[i]; });
  }
  // Presentation order, as build positions: [3,1,2] means the third slide of
  // the file is shown first. This is what the payload reports.
  function orderOrIdentity() {
    return domIds().map(function (id) { return BUILD_IDS.indexOf(id) + 1; });
  }
  function order() { return orderChanged() ? orderOrIdentity() : null; }

  function applyDom(ids) {
    var stage = document.querySelector('deck-stage');
    if (!stage) return;
    var byId = {};
    slides().forEach(function (sec) { byId[idOf(sec)] = sec; });
    ids.forEach(function (id) { if (byId[id]) stage.appendChild(byId[id]); });
    state.orderIds = domIds();
    save();
  }
  // Called once at load: put the deck into the order the reader last set. When
  // the generator has since been updated to match, the two agree and this is a
  // no-op that also clears the stored instruction.
  function applyStoredOrder() {
    var want = state.orderIds;
    if (!Array.isArray(want) || want.length !== BUILD_IDS.length) return;
    var have = {}; BUILD_IDS.forEach(function (id) { have[id] = 1; });
    if (!want.every(function (id) { return have[id]; })) { delete state.orderIds; save(); return; }
    var same = want.every(function (id, i) { return id === BUILD_IDS[i]; });
    if (same) { delete state.orderIds; delete state.order; save(); return; }
    applyDom(want);
  }
  function setOrder(o) {
    // o is a list of CURRENT positions in their new sequence.
    var secs = slides();
    applyDom(o.map(function (n) { return idOf(secs[n - 1]); }));
    if (!orderChanged()) { delete state.orderIds; delete state.order; }
    touch(); renderOv();
  }
  function move(from, to) {
    var o = identity();
    if (from === to || to < 0 || to >= o.length) return false;
    o.splice(to, 0, o.splice(from, 1)[0]);
    setOrder(o);
    return true;
  }
  function toggleStar(n) {
    if (state.starred[n]) delete state.starred[n]; else state.starred[n] = true;
    touch(); renderOv();
    say(state.starred[n] ? 'Slide ' + n + ' starred' : 'Star removed from slide ' + n);
  }
  /* ── states ───────────────────────────────────────────────────────────
     A state is a section carrying data-state-group. States are reviewed as
     separate slides, because a comment about the third frame of a build is
     about that frame. What they share is one job: exactly one of them is the
     PRIMARY, the frame that reaches print and PDF.

     Like visibility, primary is an INSTRUCTION. The generator's marking is the
     default, the reader's choice is an override stored by slide id, and it
     rides back in the payload for the generator to apply. */
  /** Branding on or off, for the whole deck.
   *
   *  One class on <html>, because WHAT counts as branding belongs to the deck's
   *  own stylesheet, not to the review layer. A deck opts in by styling
   *  `.deck-nobrand .brand { display: none }` for whatever it treats as a mark.
   *  Off by nothing: a deck that never wrote that rule simply ignores the
   *  toggle. */
  function applyBrand() {
    document.documentElement.classList.toggle('deck-nobrand', state.showBrand === false);
  }
  function toggleBrand() {
    state.showBrand = state.showBrand === false;
    applyBrand(); save(); paint();
  }

  function groupOf(sec) { return sec && sec.getAttribute('data-state-group'); }
  function groupMembers(g) {
    return slides().map(function (sec, i) { return { sec: sec, n: i + 1 }; })
      .filter(function (x) { return groupOf(x.sec) === g; });
  }
  function srcPrimary(sec) { return !!sec && sec.hasAttribute('data-state-primary'); }
  function effPrimary(sec) {
    var g = groupOf(sec);
    if (!g) return false;
    var chosen = (state.primary || {})[g];
    if (chosen) return idOf(sec) === chosen;
    return srcPrimary(sec);
  }
  function setPrimary(n) {
    var sec = slideNode(n), g = groupOf(sec);
    if (!g) return say('That slide is not part of a build');
    state.primary = state.primary || {};
    // An override that agrees with the deck is discarded, so the state stays readable.
    if (srcPrimary(sec)) delete state.primary[g]; else state.primary[g] = idOf(sec);
    applyPrimary();
    touch(); renderOv();
    say('Slide ' + n + ' is the page that prints');
  }
  /* The runtime decides which state prints from the attribute, so the override
     is written onto the DOM and deck-stage recomputes. A hidden primary falls
     back there, not here, because that rule belongs with the printing. */
  function applyPrimary() {
    slides().forEach(function (sec, i) {
      if (!groupOf(sec)) return;
      if (effPrimary(sec)) sec.setAttribute('data-state-primary', '');
      else sec.removeAttribute('data-state-primary');
    });
    if (window.deckStatePages) window.deckStatePages();
  }

  function toggleHide(n) {
    var sec = slideNode(n);
    var want = !effHidden(n, sec);
    // Only keep an override that actually differs from the deck's own marking.
    if (want === srcHidden(sec)) delete state.hidden[n]; else state.hidden[n] = want;
    touch(); applyHidden(); renderOv();
    say(want ? 'Slide ' + n + ' hidden' : 'Slide ' + n + ' visible');
  }
  // One slide-level comment per slide, so the affordance is lit or plain and
  // never a count. Selection comments do not light it: they already have the
  // highlights and the count badge.
  function hasSlideComment(n) {
    return state.comments.some(function (c) {
      return c.slide === n && c.target === 'slide' && isOpen(c);
    });
  }
  // One slide-level comment per slide: a second call edits the first rather
  // than quietly stacking a duplicate underneath it.
  function slideComment(n, anchor, onClosed) {
    var sec = slideNode(n);
    var already = state.comments.filter(function (c) {
      return c.slide === n && c.target === 'slide';
    })[0];
    if (already) return editComment(already, onClosed);
    var x = innerWidth - 452, y = bar.getBoundingClientRect().bottom + 10;
    if (anchor) {
      var b = anchor.getBoundingClientRect();
      x = Math.min(b.left, innerWidth - 404);
      y = b.bottom + 8;
    }
    openPop(x, y, { quote: '', slide: n, slideLabel: labelOf(sec), slideId: idOf(sec) },
            null, onClosed);
  }

  var ov = el('div', 'dcx dcx-ov');
  ov.setAttribute('role', 'dialog');
  ov.setAttribute('aria-modal', 'true');
  ov.setAttribute('aria-label', 'Slide overview');
  ov.style.display = 'none';
  ov.innerHTML =
    '<div class="dcx-ovhdr"><b>Overview</b><span class="count"></span>' +
    '<span class="build"></span>' +
    '<span class="hint">Click a slide to jump to it. Drag a slide, or hold Alt and press the ' +
    'left or right arrow, to reorder. With a slide focused: S stars, H hides or shows, ' +
    'C writes the slide comment here, without leaving this page. Tab stays inside this ' +
    'page. Esc goes back to the slide you came from.</span>' +
    '<span class="sp">' +
    '<span data-a="filterstar" role="button" tabindex="0" aria-pressed="false"></span>' +
    '<span data-a="filterhidden" role="button" tabindex="0" aria-pressed="false"></span>' +
    '<span data-a="brand" role="button" tabindex="0" aria-pressed="true"></span>' +
    '<span data-a="resetorder" role="button" tabindex="0">Reset order</span>' +
    '<span data-a="close" role="button" tabindex="0">Close</span></span></div>' +
    '<div class="dcx-ovgrid" role="list"></div>';
  document.body.appendChild(ov);
  var ovGrid = ov.querySelector('.dcx-ovgrid');
  // deck-stage listens for arrows, space and number keys on document. Nothing
  // typed inside the overview may reach it.
  ['keydown', 'keyup', 'keypress'].forEach(function (t) {
    ov.addEventListener(t, function (e) { e.stopPropagation(); }, false);
  });

  function ovOpen() { return ov.style.display !== 'none'; }

  var shimmed = false;
  function shimStageCss() {
    if (shimmed) return;
    shimmed = true;
    var out = [];
    Array.prototype.forEach.call(document.styleSheets, function (sh) {
      var rules;
      try { rules = sh.cssRules; } catch (e) { return; }   // cross-origin sheet
      Array.prototype.forEach.call(rules || [], function (r) {
        if (r.selectorText && r.selectorText.indexOf('deck-stage') !== -1) {
          out.push(r.cssText.replace(/deck-stage/g, '.dcx-ovstage'));
        }
      });
    });
    var s = el('style');
    s.textContent = out.join('\n');
    /* FIRST in head, not last. These rules only stand in for what deck-stage
       scoping used to provide, so they must lose every tie against the deck's
       own sheet. Appended last, `deck-stage > section {background:cream}`
       out-ordered `section.meta {background:charcoal}` at equal specificity and
       every dark slide rendered light in the grid. */
    document.head.insertBefore(s, document.head.firstChild);
  }

  var io = null;
  function materialise(frame) {
    if (frame.dataset.built) return;
    frame.dataset.built = '1';
    var src = slideNode(+frame.dataset.slide);
    if (!src) return;
    var clone = src.cloneNode(true);
    clone.removeAttribute('id');
    clone.removeAttribute('data-deck-active');
    Array.prototype.forEach.call(clone.querySelectorAll('[id]'), function (n) {
      n.removeAttribute('id');   // a duplicate id would break getElementById
    });
    Array.prototype.forEach.call(clone.querySelectorAll('iframe,audio,object,embed'),
      function (n) { n.removeAttribute('src'); n.removeAttribute('srcdoc'); n.innerHTML = ''; });
    Array.prototype.forEach.call(clone.querySelectorAll('img'), function (n) {
      n.loading = 'lazy'; n.decoding = 'async';
    });
    // A custom element inside a slide would run its mount logic once per
    // thumbnail. Keep the children, drop the element.
    Array.prototype.forEach.call(clone.querySelectorAll('*'), function (n) {
      if (n.tagName.indexOf('-') === -1) return;
      var box = el('div');
      box.className = n.className;
      box.setAttribute('style', n.getAttribute('style') || '');
      while (n.firstChild) box.appendChild(n.firstChild);
      n.replaceWith(box);
    });
    var stage = el('div', 'dcx-ovstage');
    stage.appendChild(clone);
    frame.appendChild(stage);
    var w = src.offsetWidth || 1920;
    var s = (frame.clientWidth || 268) / w;
    stage.style.transform = 'scale(' + s + ')';
  }

  function focusTile(n, a) {
    var t = ovGrid.querySelector('.dcx-ovtile[data-slide="' + n + '"]');
    if (!t) return;
    var b = a ? t.querySelector('[data-a="' + a + '"]') : null;
    (b || t).focus();
  }

  // Two filters, both remembered like the rest of the review state. They change
  // what is on screen, not what is sent, so they never make the deck dirty.
  function ovFiltering() { return !!state.ovStarredOnly || !state.ovShowHidden; }
  function ovVisible(n, sec) {
    if (state.ovStarredOnly && !state.starred[n]) return false;
    if (!state.ovShowHidden && effHidden(n, sec)) return false;
    return true;
  }

  function renderOv() {
    if (!ovOpen()) return;
    shimStageCss();
    // A rebuild must not throw the keyboard back to the top of the grid.
    var af = document.activeElement;
    var keepTile = af && af.closest ? af.closest('.dcx-ovtile') : null;
    var keepSlide = keepTile ? +keepTile.dataset.slide : 0;
    var keepBtn = (af && af.closest && af.closest('.dcx-ovtop button'))
      ? af.dataset.a : '';
    var ob = ov.querySelector('[data-a="brand"]');
    if (ob) {
      var brandOn = state.showBrand !== false;
      ob.textContent = brandOn ? '\u25C6 Branding: on' : '\u25C7 Branding: off';
      ob.setAttribute('aria-pressed', brandOn ? 'true' : 'false');
      ob.setAttribute('aria-label', ob.textContent);
      ob.title = brandOn ? 'Branding shows on every slide. Click to hide it.'
                         : 'Branding is hidden. Click to show it.';
    }
    var fs = ov.querySelector('[data-a="filterstar"]');
    fs.textContent = state.ovStarredOnly ? '\u2605 Starred only: on' : '\u2606 Starred only: off';
    fs.setAttribute('aria-pressed', state.ovStarredOnly ? 'true' : 'false');
    fs.setAttribute('aria-label', fs.textContent);
    fs.title = state.ovStarredOnly ? 'Showing starred slides only. Click to show them all.'
                                   : 'Show only the slides you starred';
    var fh = ov.querySelector('[data-a="filterhidden"]');
    fh.textContent = state.ovShowHidden ? '\u25C9 Hidden slides: shown'
                                        : '\u2298 Hidden slides: left out';
    fh.setAttribute('aria-pressed', state.ovShowHidden ? 'false' : 'true');
    fh.setAttribute('aria-label', fh.textContent);
    fh.title = state.ovShowHidden ? 'Leave the hidden slides out of this page'
                                  : 'Hidden slides are left out. Click to show them.';
    var first = slideNode(1);
    var ar = first ? (first.offsetWidth || 1920) / (first.offsetHeight || 1080) : 16 / 9;
    if (io) io.disconnect();
    io = ('IntersectionObserver' in window) ? new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        if (e.isIntersecting) { materialise(e.target); io.unobserve(e.target); }
      });
    }, { root: ov, rootMargin: '700px 0px' }) : null;
    ovGrid.innerHTML = '';
    var full = identity(), shown = 0;
    full.forEach(function (n, pos) {
      var sec = slideNode(n);
      // A filter must never take away the slide the reader is acting on, so the
      // focused one stays, flagged, rather than vanishing under his hands.
      var pass = ovVisible(n, sec);
      if (!pass && n !== keepSlide && n !== ovOrigin) return;
      shown++;
      var st = !!state.starred[n];
      var hd = effHidden(n, sec);
      var moved = idOf(sec) !== BUILD_IDS[n - 1];
      var cm = state.comments.filter(function (c) { return c.slide === n && isOpen(c); }).length;
      var sc = hasSlideComment(n);
      // The slide comment IS the only comment: one flag, not two saying the same.
      var only = sc && cm === 1;
      var t = el('div', 'dcx-ovtile' + (st ? ' starred' : '') + (hd ? ' ishidden' : '') +
        (pass ? '' : ' filtered'));
      t.tabIndex = 0;
      // Reorder works on the whole deck's positions, so it is off while a
      // filter is hiding part of it rather than moving a slide somewhere unseen.
      t.draggable = !ovFiltering();
      t.dataset.slide = n;
      t.dataset.pos = pos;
      t.setAttribute('role', 'listitem');
      t.setAttribute('aria-label',
        'Position ' + (pos + 1) + ' of ' + slides().length + ', slide ' + n + ', ' +
        (labelOf(sec) || 'untitled') + (st ? ', starred' : '') + (hd ? ', hidden' : '') +
        (moved ? ', moved from position ' + n : '') +
        (pass ? '' : ', kept on screen against the filter') +
        (sc ? ', has a slide comment' : '') +
        (cm ? ', ' + cm + ' open comment' + (cm === 1 ? '' : 's') : ''));
      t.innerHTML =
        '<div class="dcx-ovtop"><span class="pos">' + (pos + 1) +
          (moved ? ' <em>was ' + (BUILD_IDS.indexOf(idOf(sec)) + 1) + '</em>' : '') + '</span><span class="btns">' +
        '<button type="button" data-a="star" aria-pressed="' + st + '" ' +
          'aria-label="Star slide ' + n + '" title="Star this slide (S)">' +
          (st ? '★' : '☆') + '</button>' +
        '<button type="button" data-a="hide" aria-pressed="' + hd + '" ' +
          'aria-label="Hide or show slide ' + n + '" title="Hide or show this slide (H)">' +
          (hd ? '\u2298' : '\u25C9') + '</button>' +
        '<button type="button" data-a="cmt" aria-label="' +
          (sc ? 'Slide ' + n + ' has a slide comment. Read or edit it'
              : 'Write the slide comment for slide ' + n) + '" ' +
          'title="' + (sc ? 'Slide ' + n + ' has a slide comment (C)'
                          : 'Slide comment (C)') + '">💬' +
          (sc || cm ? '<i>' + (sc ? '\u25CF' : '') + (only ? '' : cm) + '</i>' : '') + '</button>' +
        (groupOf(sec) ? '<button type="button" data-a="primary" aria-pressed="' +
          (effPrimary(sec) ? 'true' : 'false') + '" aria-label="Make slide ' + n +
          ' the page that prints" title="Make primary: the one state of this build that ' +
          'reaches print (P)">' + (effPrimary(sec) ? '\u25C6' : '\u25C7') + '</button>' : '') +
        '<button type="button" data-a="note" aria-label="Edit the speaker note for slide ' + n +
          '" title="Edit this slide\'s speaker note (N)">📝' +
          (state.noteEdits[n] !== undefined ? '<i>\u2713</i>' : '') + '</button>' +
        '</span></div>' +
        '<div class="dcx-ovthumb" data-slide="' + n + '"></div>' +
        '<div class="dcx-ovlabel"></div>' +
        '<div class="dcx-ovflags">' +
          (st ? '<span class="dcx-f-st">★ STARRED</span>' : '') +
          (hd ? '<span class="dcx-f-hd">HIDDEN</span>' : '') +
          (moved ? '<span class="dcx-f-mv">MOVED</span>' : '') +
          (groupOf(sec) && effPrimary(sec) ? '<span class="dcx-f-pr">PRINTS</span>' : '') +
          (sc ? '<span class="dcx-f-cm">\u25CF SLIDE COMMENT</span>' : '') +
          (cm && !only ? '<span class="dcx-f-cm">' + cm + ' COMMENT' +
            (cm === 1 ? '' : 'S') + '</span>' : '') +
          (pass ? '' : '<span class="dcx-f-fo">FILTERED OUT</span>') +
        '</div>';
      t.querySelector('.dcx-ovlabel').textContent = 'Slide ' + n + ' · ' + (labelOf(sec) || '—');
      var frame = t.querySelector('.dcx-ovthumb');
      frame.style.aspectRatio = String(ar);
      ovGrid.appendChild(t);
      if (io) io.observe(frame); else materialise(frame);
    });
    // Which build is on screen, and when the reader last changed anything on top
    // of it. Two dates answer "am I looking at the current deck, and are my
    // edits in it?" without opening the file.
    var bEl = ov.querySelector('.dcx-ovhdr .build');
    if (bEl) {
      var built = (DECK.build || '').replace('T', ' ').replace('Z', ' UTC');
      var edited = state.lastEdit
        ? new Date(state.lastEdit).toLocaleString(undefined,
            { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
        : null;
      bEl.textContent = 'build ' + (DECK.buildHash || '?') +
        (built ? ' \u00b7 generated ' + built : '') +
        (edited ? ' \u00b7 your edits ' + edited : ' \u00b7 no local edits');
      bEl.title = 'The build this grid is showing, and when you last changed something in it.';
    }
    ov.querySelector('.dcx-ovhdr .count').textContent =
      shown === full.length ? 'All ' + full.length + ' slides'
                            : 'Showing ' + shown + ' of ' + full.length;
    if (!shown) {
      ovGrid.innerHTML = '<p class="dcx-ovempty">No slide matches the filters above. ' +
        'Turn one off to see the rest of the deck.</p>';
    }
    if (keepSlide) focusTile(keepSlide, keepBtn);
  }

  // Everything else on the page goes inert while the overview is up, so a
  // screen reader and the Tab key both stay inside it. Closing gives it back.
  var inerted = [];
  function outsideInert(on) {
    if (on) {
      Array.prototype.forEach.call(document.body.children, function (n) {
        if (n === ov || n.inert) return;
        n.inert = true; inerted.push(n);
      });
    } else {
      inerted.forEach(function (n) { n.inert = false; });
      inerted = [];
    }
  }

  // Where he was before he opened the overview. Escape goes back there.
  var ovOrigin = 0;
  function openOv() {
    if (performing) return;
    closePop();
    panel.style.display = 'none';
    ovOrigin = currentSlide().index;
    ov.style.display = 'block';
    outsideInert(true);
    renderOv();
    focusTile(ovOrigin);
    if (!ovGrid.querySelector('.dcx-ovtile:focus')) {
      var f = ovGrid.querySelector('.dcx-ovtile') ||
              ov.querySelector('.dcx-ovhdr [data-a="close"]');
      if (f) f.focus();
    }
  }
  // toOrigin: leaving the overview by Escape or Close puts him back on the
  // slide he came from. Clicking a tile passes false, because it is going
  // somewhere else on purpose.
  function closeOv(toOrigin) {
    if (!ovOpen()) return;
    ov.style.display = 'none';
    outsideInert(false);
    if (io) { io.disconnect(); io = null; }
    if (toOrigin && ovOrigin) goTo(ovOrigin);
    if (toOrigin && !performing) {
      var b = bar.querySelector('[data-a="overview"]');
      if (b) b.focus();
    }
    render();
  }

  function tileAction(a, n) {
    if (a === 'star') return toggleStar(n);
    if (a === 'hide') return toggleHide(n);
    // Commenting from the overview stays on the overview. Jumping to the
    // slide was the wrong answer: he was working the grid, not the deck.
    if (a === 'cmt') {
      if (!ovOpen()) { goTo(n); return setTimeout(function () { slideComment(n); }, 280); }
      var tile = ovGrid.querySelector('.dcx-ovtile[data-slide="' + n + '"]');
      var anchor = tile ? tile.querySelector('[data-a="cmt"]') : null;
      return slideComment(n, anchor, function () { focusTile(n, 'cmt'); });
    }
    // Editing a speaker note from the overview also stays on the overview: the
    // reader is working the grid, and the tray follows the deck, not the grid.
    if (a === 'note') return noteEditor(n);
    if (a === 'primary') return setPrimary(n);
  }

  /* ── the per-slide note editor, opened from an overview tile ────────────
     Writes to the same state.noteEdits the tray uses, so an edit made here is
     the same edit, carried back in noteEdits[] with its previousNote. */
  var noteBox = null;
  function closeNoteEditor(focusBack) {
    if (!noteBox) return;
    var n = noteBox.dataset.slide;
    noteBox.remove(); noteBox = null;
    if (focusBack && n) focusTile(+n, 'note');
  }
  function noteEditor(n) {
    closeNoteEditor(false);
    var sec = slideNode(n);
    if (!sec) return;
    noteBox = el('div', 'dcx-noteedit');
    noteBox.dataset.slide = n;
    noteBox.innerHTML =
      '<div class="hd"><b></b><span class="edited"' +
        (state.noteEdits[n] === undefined ? ' hidden' : '') + '>EDITED</span></div>' +
      '<textarea spellcheck="true"></textarea>' +
      '<div class="ft"><span data-a="revert">Revert</span>' +
        '<span data-a="done">Done</span></div>';
    noteBox.querySelector('b').textContent = 'Slide ' + n + ' \u00b7 ' + (labelOf(sec) || '\u2014');
    var ta = noteBox.querySelector('textarea');
    ta.value = noteFor(n);
    ta.placeholder = 'What the presenter says, does, or must not forget on this slide.';
    ta.addEventListener('input', function () {
      if (ta.value === originalNote(n)) delete state.noteEdits[n];
      else state.noteEdits[n] = ta.value;
      noteBox.querySelector('.edited').hidden = state.noteEdits[n] === undefined;
      touch(); paintTray(); renderOv();
    });
    ta.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); closeNoteEditor(true); }
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); closeNoteEditor(true); }
    });
    noteBox.addEventListener('click', function (e) {
      var a = e.target.dataset && e.target.dataset.a;
      if (a === 'done') return closeNoteEditor(true);
      if (a === 'revert') {
        delete state.noteEdits[n];
        ta.value = originalNote(n);
        noteBox.querySelector('.edited').hidden = true;
        touch(); paintTray(); renderOv();
      }
    });
    document.body.appendChild(noteBox);
    ta.focus();
  }

  ov.addEventListener('click', function (e) {
    var h = e.target.closest('.dcx-ovhdr [data-a]');
    if (h) {
      if (h.dataset.a === 'close') { closeNoteEditor(false); return closeOv(true); }
      if (h.dataset.a === 'filterstar') {
        state.ovStarredOnly = !state.ovStarredOnly; save(); renderOv();
        return say(state.ovStarredOnly ? 'Showing starred slides only' : 'Showing all slides');
      }
      if (h.dataset.a === 'filterhidden') {
        state.ovShowHidden = !state.ovShowHidden; save(); renderOv();
        return say(state.ovShowHidden ? 'Hidden slides shown' : 'Hidden slides left out');
      }
      if (h.dataset.a === 'brand') {
        toggleBrand(); renderOv();
        return say(state.showBrand === false ? 'Branding hidden' : 'Branding showing');
      }
      if (h.dataset.a === 'resetorder') {
        if (!orderChanged()) return say('Order is unchanged');
        delete state.order; touch(); renderOv();
        return say('Order reset');
      }
    }
    var t = e.target.closest('.dcx-ovtile');
    if (!t) return;
    var n = +t.dataset.slide;
    var b = e.target.closest('button');
    if (b) { e.stopPropagation(); return tileAction(b.dataset.a, n); }
    closeOv(false);
    goTo(n);
  });

  ov.addEventListener('keydown', function (e) {
    var h = e.target.closest('.dcx-ovhdr [data-a]');
    if (e.key === 'Escape') { e.preventDefault(); return closeOv(true); }
    // Tab cycles inside the overview. Nothing behind it can be reached, so the
    // keyboard cannot fall through to a deck the reader cannot see.
    if (e.key === 'Tab') {
      var foc = Array.prototype.slice.call(
        ov.querySelectorAll('.dcx-ovhdr [data-a], .dcx-ovtile, .dcx-ovtop button'));
      if (!foc.length) return;
      var i = foc.indexOf(e.target), j = i + (e.shiftKey ? -1 : 1);
      if (i === -1) j = e.shiftKey ? foc.length - 1 : 0;
      if (j < 0) j = foc.length - 1;
      if (j >= foc.length) j = 0;
      e.preventDefault();
      return foc[j].focus();
    }
    if (h && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); return h.click(); }
    var t = e.target.closest('.dcx-ovtile');
    if (!t || e.target.closest('button')) return;
    var n = +t.dataset.slide, pos = +t.dataset.pos, k = e.key;
    if (e.altKey && (k === 'ArrowLeft' || k === 'ArrowRight')) {
      e.preventDefault();
      if (ovFiltering()) return say('Turn the filters off to reorder the deck');
      var to = pos + (k === 'ArrowRight' ? 1 : -1);
      // Focus follows the SLIDE, not the number it used to have: after the move
      // the slide sits at to+1, and focusing n would grab whatever took its place.
      if (move(pos, to)) { focusTile(to + 1); say('Moved to position ' + (to + 1)); }
      return;
    }
    if (k === 'Enter' || k === ' ') { e.preventDefault(); closeOv(false); return goTo(n); }
    if (k === 's' || k === 'S') { e.preventDefault(); toggleStar(n); return focusTile(n); }
    if (k === 'h' || k === 'H') { e.preventDefault(); toggleHide(n); return focusTile(n); }
    if (k === 'c' || k === 'C') { e.preventDefault(); return tileAction('cmt', n); }
    if (k === 'n' || k === 'N') { e.preventDefault(); return tileAction('note', n); }
    if (k === 'p' || k === 'P') { e.preventDefault(); return tileAction('primary', n); }
    /* Left and right walk the sequence. Up and down move a whole ROW, which is
       what a grid promises the eye, so the column count is measured from the
       laid-out tiles rather than assumed: it changes with the window. */
    function rowLength() {
      var tiles = [].slice.call(ovGrid.querySelectorAll('.dcx-ovtile'));
      if (!tiles.length) return 1;
      var top0 = tiles[0].getBoundingClientRect().top, cols = 0;
      for (var i = 0; i < tiles.length; i++) {
        if (Math.abs(tiles[i].getBoundingClientRect().top - top0) > 2) break;
        cols++;
      }
      return cols || 1;
    }
    function step(by) {
      var tiles = [].slice.call(ovGrid.querySelectorAll('.dcx-ovtile'));
      var at = tiles.indexOf(t);
      if (at < 0) return;
      var to = at + by;
      if (to < 0 || to >= tiles.length) return;      // no wrap: the edge is the edge
      tiles[to].focus();
    }
    if (k === 'ArrowRight') { e.preventDefault(); return step(1); }
    if (k === 'ArrowLeft') { e.preventDefault(); return step(-1); }
    if (k === 'ArrowDown') { e.preventDefault(); return step(rowLength()); }
    if (k === 'ArrowUp') { e.preventDefault(); return step(-rowLength()); }
    if (k === 'Home') { e.preventDefault(); return focusTile(identity()[0]); }
    if (k === 'End') {
      e.preventDefault();
      var o = identity();
      return focusTile(o[o.length - 1]);
    }
  });

  var dragFrom = null, dragOver = null;
  ovGrid.addEventListener('dragstart', function (e) {
    var t = e.target.closest('.dcx-ovtile');
    if (!t) return;
    if (ovFiltering()) { e.preventDefault(); return say('Turn the filters off to reorder the deck'); }
    dragFrom = +t.dataset.pos;
    t.classList.add('dragging');
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = 'move';
      try { e.dataTransfer.setData('text/plain', String(dragFrom)); } catch (err) {}
    }
  });
  ovGrid.addEventListener('dragover', function (e) {
    if (dragFrom === null) return;
    var t = e.target.closest('.dcx-ovtile');
    if (!t) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
    if (dragOver && dragOver !== t) dragOver.classList.remove('over');
    dragOver = t;
    t.classList.add('over');
  });
  ovGrid.addEventListener('drop', function (e) {
    if (dragFrom === null) return;
    var t = e.target.closest('.dcx-ovtile');
    if (!t) return;
    e.preventDefault();
    var from = dragFrom, to = +t.dataset.pos;
    dragFrom = null;
    if (dragOver) { dragOver.classList.remove('over'); dragOver = null; }
    if (move(from, to)) say('Slide moved to position ' + (to + 1));
  });
  ovGrid.addEventListener('dragend', function () {
    dragFrom = null;
    if (dragOver) { dragOver.classList.remove('over'); dragOver = null; }
    Array.prototype.forEach.call(ovGrid.querySelectorAll('.dragging'), function (t) {
      t.classList.remove('dragging');
    });
  });

  /* ── the payload ────────────────────────────────────────────────────── */
  function payload() {
    // Only what is still open. A comment already ticked off has been read,
    // acted on and reported; copying it back is noise in both directions.
    var ordered = state.comments.filter(isOpen).sort(function (a, b) {
      return a.slide - b.slide || a.at.localeCompare(b.at);
    });
    var changes = visChanges();
    // A comment stores whatever idOf() resolved when it was written, which on an
    // unminted deck is the LABEL. Gate on whether this deck mints ids at all, so
    // a label never leaves here calling itself an id.
    // ponytail: deck-wide gate, not per-id. A comment written on this deck BEFORE
    // its generator started minting would emit its label as slideId. Tighten to a
    // per-id check against the minted set if that ever bites.
    var mints = deckMintsIds();
    var hiddenNow = slides().map(function (sec, i) { return { sec: sec, n: i + 1 }; })
      .filter(function (x) { return effHidden(x.n, x.sec); })
      .map(function (x) {
        return { slide: x.n, slideId: mintedId(x.sec), slideLabel: labelOf(x.sec),
                 inSource: srcHidden(x.sec) };
      });
    var primaryNow = slides().map(function (sec, i) { return { sec: sec, n: i + 1 }; })
      .filter(function (x) { return groupOf(x.sec) && effPrimary(x.sec); })
      .map(function (x) {
        return { slide: x.n, slideId: mintedId(x.sec), slideLabel: labelOf(x.sec),
                 group: groupOf(x.sec), inSource: srcPrimary(x.sec) };
      });
    var stars = starredList().map(function (n) {
      var node = slideNode(n);
      return { slide: n, slideId: mintedId(node), slideLabel: labelOf(node) };
    });
    var moved = orderChanged();
    // A note edit that matches the note already in the deck is not an edit. These
    // appear when slides are added: the bag is keyed by slide NUMBER, so an edit
    // stored against 7 is compared with a different slide's note after a build
    // shifts the numbering. Filtering here means the payload never asks for a
    // change that is already made.
    var edits = Object.keys(state.noteEdits || {}).map(Number).sort(function (a, b) { return a - b; })
      .map(function (n) {
        var node = slideNode(n);
        return { slide: n, slideId: mintedId(node), slideLabel: node ? labelOf(node) : '',
                 note: state.noteEdits[n], previousNote: originalNote(n) };
      }).filter(function (e) { return e.note !== e.previousNote; });
    return JSON.stringify({
      kind: 'deck-comments',
      version: 4,
      // Short on purpose. The long form lives in the deck-review SKILL.md; a
      // paragraph repeated in every round trip is a paragraph that stops being
      // read, and it is paid for on both sides.
      instruction: 'The user reviewed this deck in the browser. Work the comments with status '
        + '"new" or "question"; anything "addressed" or "wontfix" is done, so do not redo it or '
        + 'report on it. Find each slide by slideId, which never moves, and search for that id in '
        + 'the generator at deck.source. The deck HTML is GENERATED: edit the generator, never '
        + 'index.html, then rebuild with the command in BUILD.md and re-run ?audit. When the round '
        + 'is done, write {at, status, note} for each handled comment into the file at '
        + 'deck.resolutions, keyed by the comment\'s "at", and rebuild. If deck.buildHash is not '
        + 'the current build, say so before acting. Every array here is a CHANGE the reader made; '
        + 'anything they left alone is summarised in unchanged and needs no action.',
      deck: DECK,
      slideCount: slides().length,
      capturedAt: new Date().toISOString(),
      commentCount: state.comments.length,
      openCount: ordered.length,
      addressedCount: state.comments.length - ordered.length,
      note: 'comments[] carries the OPEN ones only.',
      noteEdits: edits,
      // Only slides the READER hid. One already hidden in the generator needs no
      // action, and listing it every round is the same instruction repeated
      // until it stops being read.
      hiddenSlides: hiddenNow.filter(function (x) { return !x.inSource; }),
      visibilityChanges: changes,
      primaryStates: primaryNow.filter(function (x) { return !x.inSource; }),
      primaryInstruction: primaryNow.some(function (x) { return !x.inSource; })
        ? 'primaryStates[] names a state the reader chose as the one that reaches print. Set '
          + 'primary on that slide in the generator and clear it from its sibling.'
        : undefined,
      // What the reader left ALONE, as counts rather than as rows, so a short
      // round trip stays short and nothing looks lost.
      unchanged: { hiddenInSource: hiddenNow.length - hiddenNow.filter(function (x) { return !x.inSource; }).length,
                   primaryInSource: primaryNow.length - primaryNow.filter(function (x) { return !x.inSource; }).length },
      starredSlides: stars,
      orderChanged: moved,
      slideOrder: moved ? slides().map(function (node, i) {
        return { position: i + 1, wasSlide: BUILD_IDS.indexOf(idOf(node)) + 1,
                 slideId: mintedId(node), slideLabel: labelOf(node) };
      }) : undefined,
      orderInstruction: moved
        ? 'slideOrder[] is the order the user wants the deck to end up in. Each entry gives '
          + 'the new position and wasSlide, the slide number in the build they reviewed. Move '
          + 'the slide-building calls in the generator at deck.source so the emitted order '
          + 'matches, and change nothing else about those slides. Every other slide number in '
          + 'this payload (comments[], hiddenSlides[], visibilityChanges[], noteEdits[], '
          + 'starredSlides[]) is the OLD numbering of the reviewed build, so resolve those '
          + 'against the current file BEFORE you reorder. Their slideId does not move, so use '
          + 'it instead of the number wherever it is present. Rebuild afterwards, and say in your '
          + 'reply what the new numbering is.'
        : undefined,
      starInstruction: stars.length
        ? 'starredSlides[] are the slides the user flagged for attention this round. A star is '
          + 'a marker, not an edit: do not change a starred slide unless a comment asks for it. '
          + 'Look at those slides first and lead your reply with what you found.'
        : undefined,
      visibilityInstruction: changes.length
        ? 'visibilityChanges[] are slides the user showed or hid in the browser, and they differ '
          + 'from what the generator says. Change each one in the generator so it survives a '
          + 'rebuild: hidden=True to hide, remove it to show. hiddenSlides[] is the full list of '
          + 'what should end up hidden.'
        : undefined,
      noteEditInstruction: edits.length
        ? 'noteEdits[] are speaker notes the user rewrote in the browser. Write each one into the generator as that slide\'s note, replacing previousNote, then rebuild.'
        : undefined,
      orphanedComments: (state.comments || []).filter(function (c) { return c.orphan; })
        .map(function (c) {
          return { slideId: mints ? c.slideId : undefined, slideLabel: c.slideLabel,
                   target: c.target, quote: c.quote, comment: c.comment, at: c.at };
        }),
      orphanInstruction: (state.comments || []).some(function (c) { return c.orphan; })
        ? 'orphanedComments[] were written about slides that no longer exist under that label. '
          + 'Do not guess which slide they now mean: say what they were about and ask.'
        : undefined,
      comments: ordered.map(function (c, i) {
        var r = resolutionFor(c);
        return {
          n: i + 1, slide: c.slide, slideId: mints ? c.slideId : undefined,
          slideLabel: c.slideLabel, target: c.target,
          quote: c.quote, comment: c.comment, at: c.at,
          status: statusOf(c),
          addressedInBuild: r ? (r.build || null) : null,
          resolutionNote: r ? (r.note || null) : null
        };
      })
    }, null, 2);
  }

  function copyText(txt, msg, done) {
    function ok() { say(msg); if (done) done(); }
    function fallback() {
      var ta = el('textarea');
      ta.value = txt; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); ok(); } catch (e) { say('Copy failed'); }
      ta.remove();
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(ok, fallback);
    } else fallback();
  }

  // What is waiting to be sent, in words. Used by the count badge's title and
  // by the row at the top of the comment list.
  function visChanges() {
    return slides().map(function (sec, i) { return { sec: sec, n: i + 1 }; })
      .filter(function (x) { return effHidden(x.n, x.sec) !== srcHidden(x.sec); })
      .map(function (x) {
        var to = effHidden(x.n, x.sec);
        return { slide: x.n, slideId: mintedId(x.sec), slideLabel: labelOf(x.sec),
                 from: to ? 'visible' : 'hidden', to: to ? 'hidden' : 'visible' };
      });
  }
  function changeList() {
    var out = [];
    var open = state.comments.filter(isOpen).length;
    if (open) out.push(open + (open === 1 ? ' comment' : ' comments'));
    var ne = Object.keys(state.noteEdits || {}).length;
    if (ne) out.push(ne + (ne === 1 ? ' edited speaker note' : ' edited speaker notes'));
    var vc = visChanges().length;
    if (vc) out.push(vc + (vc === 1 ? ' slide shown or hidden' : ' slides shown or hidden'));
    var st = starredList().length;
    if (st) out.push(st + (st === 1 ? ' starred slide' : ' starred slides'));
    if (orderChanged()) out.push('a new slide order');
    return out;
  }

  /* ── panel ──────────────────────────────────────────────────────────── */
  function render() {
    var n = state.comments.length;
    var open = state.comments.filter(isOpen).length;
    var badge = bar.querySelector('.dcx-count');
    var words = changeList();
    var dirty = !!state.dirty && words.length > 0;
    // Gold is the glance signal, but colour alone is not a signal everyone can
    // read: the filled dot and the spoken label carry it too.
    badge.textContent = (dirty ? '\u25CF ' : '') + (open === n ? String(n) : open + '/' + n);
    badge.classList.toggle('zero', open === 0 && !dirty);
    badge.classList.toggle('dirty', dirty);
    badge.title = dirty
      ? 'Unsent changes: ' + words.join(', ') + '. Press Copy to send them to Claude.'
      : open + ' open, ' + (n - open) + ' addressed';
    var lb = bar.querySelector('[data-a="list"]');
    if (lb) lb.setAttribute('aria-label', badge.title);
    var mb = bar.querySelector('[data-a="marks"]');
    if (mb) mb.classList.toggle('off', !state.showMarks);
    var bb2 = bar.querySelector('[data-a="brand"]');
    if (bb2) {
      var on = state.showBrand !== false;
      bb2.classList.toggle('off', !on);
      bb2.textContent = on ? '\u25C6' : '\u25C7';
      bb2.setAttribute('aria-pressed', on ? 'true' : 'false');
      bb2.title = on ? 'Branding is showing. Hide it on every slide'
                     : 'Branding is hidden. Show it on every slide';
    }
    // Primary is meaningless off a build, so the control disappears rather than
    // sitting there doing nothing.
    var pb = bar.querySelector('[data-a="primary"]');
    if (pb) {
      var pcur = currentSlide(), pg = groupOf(pcur.node);
      pb.hidden = !pg;
      if (pg) {
        var on = effPrimary(pcur.node);
        pb.textContent = on ? '\u25C6' : '\u25C7';
        pb.classList.toggle('on', on);
        pb.setAttribute('aria-pressed', on ? 'true' : 'false');
        pb.title = on ? 'This state is the page that prints'
                      : 'Make this state the page that prints';
      }
    }
    // The star affordance for the slide on screen. Icon only in the bar, so the
    // state is carried by the glyph's SHAPE (filled against hollow) and spelled
    // out in aria-label and the tooltip. Never by colour alone.
    var sb = bar.querySelector('[data-a="star"]');
    if (sb) {
      var cn = currentSlide().index, on = !!state.starred[cn];
      sb.textContent = (on ? '\u2605' : '\u2606');
      sb.setAttribute('aria-label', on ? 'Starred. Remove the star from this slide'
                                       : 'Star this slide');
      sb.classList.toggle('on', on);
      sb.setAttribute('aria-pressed', on ? 'true' : 'false');
      sb.title = on ? 'Slide ' + cn + ' is starred. Click, or press S, to remove the star.'
                    : 'Star this slide (S)';
      sb.setAttribute('aria-label', sb.title);
    }
    // Lit when this slide already carries a slide comment. Colour is not the
    // signal on its own: the filled dot leads the label and the tooltip and
    // aria-label say it in words, the same way the count badge does.
    var cb = bar.querySelector('[data-a="slide"]');
    if (cb) {
      var ci = currentSlide().index, hasC = hasSlideComment(ci);
      cb.textContent = (hasC ? '\u25CF ' : '') + '\uD83D\uDCAC Slide comment';
      cb.classList.toggle('on', hasC);
      cb.title = hasC
        ? 'Slide ' + ci + ' has a slide comment. Click to read or edit it.'
        : 'No slide comment on slide ' + ci + '. Click to write one.';
      cb.setAttribute('aria-label', cb.title);
    }
    var nb = bar.querySelector('[data-a="notes"]');
    if (nb) nb.classList.toggle('off', !noteFor(currentSlide().index).trim());
    if (panel.style.display === 'none') return;
    var dirtyRow = dirty
      ? '<div class="item dirtyrow"><div class="t">\u25CF UNSENT CHANGES</div>' +
        '<div class="w">Not yet sent: ' + words.join(', ') + '. ' +
        'Press Copy, then paste the payload into the chat.</div></div>'
      : '';
    if (!n) {
      panel.innerHTML = dirtyRow + '<div class="empty">No comments yet.<br>Select text on a ' +
        'slide, or use &ldquo;Slide comment&rdquo;.</div>';
      return;
    }
    var orphans = state.comments.filter(function (c) { return c.orphan; }).length;
    if (!panel.dataset.wired) {
      panel.dataset.wired = '1';
      panel.addEventListener('click', function (e) {
        if (!e.target.dataset || e.target.dataset.a !== 'clearorphans') return;
        state.comments = state.comments.filter(function (c) { return !c.orphan; });
        touch();
        say('Orphaned comments cleared');
      });
    }
    panel.innerHTML = dirtyRow + (orphans
      ? '<div class="item orphanrow"><div class="t">\u26A0 ' + orphans + ' ORPHANED</div>' +
        '<div class="w">Written about slides that no longer exist under that label. They are ' +
        'reported separately and never painted on a slide.</div>' +
        '<span class="acts"><span data-a="clearorphans">Clear all orphans</span></span></div>'
      : '');
    state.comments.slice().sort(function (a, b) { return a.slide - b.slide; }).forEach(function (c) {
      var r = resolutionFor(c), st = statusOf(c);
      var d = el('div', 'item' + (isOpen(c) ? '' : ' done'));
      d.innerHTML = '<span class="acts"><span data-a="edit">Edit</span>' +
        '<span data-a="del">Delete</span></span>' +
        '<span class="slide"></span>' +
        (st === 'new' ? '' : '<span class="tick ' + st + '">' +
          (st === 'addressed' ? '\u2713 ADDRESSED' : st === 'wontfix' ? '\u2013 NOT DOING' : '? DISCUSS') +
          '</span>') +
        (c.quote ? '<div class="quote"></div>' : '') +
        '<div class="body"></div>' +
        (r && r.note ? '<div class="resnote"></div>' : '');
      d.querySelector('.slide').textContent = c.orphan
        ? '\u26A0 ORPHANED \u00b7 was on \u201c' + (c.slideLabel || '\u2014') + '\u201d'
        : 'Slide ' + c.slide + ' \u00b7 ' + (c.slideLabel || '\u2014');
      if (r && r.note) d.querySelector('.resnote').textContent = r.note;
      if (c.quote) d.querySelector('.quote').textContent = c.quote;
      d.querySelector('.body').textContent = c.comment;

      var delBtn = d.querySelector('[data-a="del"]'), armed = false;
      d.addEventListener('click', function (e) {
        var a = e.target.dataset && e.target.dataset.a;
        if (a === 'del') {
          if (!armed) { armed = true; delBtn.textContent = 'Confirm'; delBtn.classList.add('danger'); return; }
          return remove(c.cid);
        }
        goTo(c.slide);
        if (a === 'edit') setTimeout(function () { editComment(c); }, 260);
      });
      panel.appendChild(d);
    });
  }

  function goTo(n) {
    var stage = document.querySelector('deck-stage');
    if (stage && typeof stage.goTo === 'function') stage.goTo(n - 1);
    setTimeout(paint, 220);
  }

  bar.addEventListener('click', function (e) {
    var b = e.target.closest('button');
    if (!b) return;
    var a = b.dataset.a;
    if (a === 'copy') {
      // Comments are not the only thing worth sending back. A note rewritten or a
      // slide shown or hidden is a change to the deck, and refusing to copy it
      // because nobody left a comment is how those changes get lost.
      var anything = state.comments.length
        || Object.keys(state.noteEdits || {}).length
        || Object.keys(state.hidden || {}).length
        || starredList().length
        || orderChanged();
      if (!anything) return say('Nothing to copy yet');
      // Dirty clears only once the payload is really on the clipboard.
      return copyText(payload(), 'Payload copied', function () {
        state.dirty = false; save(); render();
      });
    }
    if (a === 'marks') {
      state.showMarks = !state.showMarks; save(); paint(); render();
      return say(state.showMarks ? 'Highlights on' : 'Highlights off');
    }
    if (a === 'star') { return toggleStar(currentSlide().index); }
    if (a === 'hide') { return toggleHide(currentSlide().index); }
    if (a === 'brand') { return toggleBrand(); }
    if (a === 'primary') { return setPrimary(currentSlide().index); }
    if (a === 'overview') { return ovOpen() ? closeOv(true) : openOv(); }
    if (a === 'perform') { return setPerforming(true); }
    if (a === 'notes') {
      state.trayOpen = !state.trayOpen; save(); paintTray();
      return;
    }
    if (a === 'clearorphans') {
      state.comments = state.comments.filter(function (c) { return !c.orphan; });
      touch();
      return say('Orphaned comments cleared');
    }
    if (a === 'list') {
      panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
      return render();
    }
    if (a === 'slide') { return slideComment(currentSlide().index); }
  });

  // Repaint when the slide changes. deck-stage fires no event, so watch the
  // attribute it toggles.
  var stageEl = document.querySelector('deck-stage');
  if (stageEl) {
    new MutationObserver(function () {
      paint(); paintTray(); applyHidden(); skipHidden(); render();
    }).observe(stageEl, {
      subtree: true, attributes: true, attributeFilter: ['data-deck-active']
    });
  }

  // Put the deck into the order the reader last set, before anything paints.
  // When the generator has caught up, this is a no-op that clears the record.
  applyStoredOrder();

  // Move every stored record to wherever its slide went, BEFORE the first
  // paint, so nothing is ever drawn on a slide it does not belong to.
  applyBrand();
  applyPrimary();
  var moves = reanchor();
  if (moves.moved || moves.orphaned) {
    setTimeout(function () {
      say(moves.moved + ' re-anchored'
          + (moves.orphaned ? ', ' + moves.orphaned + ' orphaned' : ''));
    }, 900);
  }

  render();
  paintTray();
  applyHidden();
  setTimeout(paint, 400);
})();
