import { chromium } from 'playwright';
const url = 'file://' + process.argv[2] + '/test.html';
const browser = await chromium.launch();
const page = await browser.newPage();
const errors = [];
page.on('pageerror', e => errors.push(e.message));
await page.goto(url);
// topbar injected
const okTopbar = await page.locator('.topbar h1').textContent() === 'Brief runtime test';
const okProgress = (await page.locator('#progress').textContent()) === '0/1 questions resolved';
// answer persist
await page.fill('#ans-Q1', 'my test answer');
// tick
await page.check('section[data-q="Q1"] .tick input');
const collapsed = await page.locator('section[data-q="Q1"] .q-body').isHidden();
const okProgress2 = (await page.locator('#progress').textContent()) === '1/1 questions resolved';
// selection comment
await page.locator('section.brief-section .sec-body p').first().selectText();
await page.mouse.up();
await page.waitForSelector('#cpop', { timeout: 3000 });
// the popover must NOT steal the selection — plain copy has to keep working
const selectionSurvives = await page.evaluate(() => {
  const s = window.getSelection();
  return !!s && !s.isCollapsed && s.toString().trim().length > 0;
});
await page.fill('#cpop textarea', 'a test comment');
await page.click('#cpop [data-act="save"]');
const markCount = await page.locator('mark.cmt').count();
// copy JSON via button
await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
await page.click('#copyBtn');
const json = JSON.parse(await page.evaluate(() => navigator.clipboard.readText()));
// download JSON via button — same payload, named file
const [download] = await Promise.all([page.waitForEvent('download'), page.click('#downloadBtn')]);
const dlName = download.suggestedFilename();
const okDownload = /^[a-z0-9-]+-responses-\d{4}-\d{2}-\d{2}\.json$/.test(dlName);
// reload persistence
await page.reload();
const persistTick = await page.locator('section[data-q="Q1"]').evaluate(el => el.classList.contains('done'));
await page.uncheck('section[data-q="Q1"] .tick input');
const persistAns = await page.inputValue('#ans-Q1');
const reanchored = await page.locator('mark.cmt').count();
// cross-element selection: the .assume paragraph wraps <strong> children, so the
// old surroundContents() path threw and the comment was saved but never marked.
await page.locator('section[data-q="Q1"] p.assume').selectText();
await page.mouse.up();
await page.waitForSelector('#cpop', { timeout: 3000 });
await page.fill('#cpop textarea', 'crosses an element boundary');
await page.click('#cpop [data-act="save"]');
const crossMarks = await page.locator('mark.cmt').count() - reanchored;
// draft recovery: type, then dismiss without saving
await page.locator('section.brief-section .sec-body p').last().selectText();
await page.mouse.up();
await page.waitForSelector('#cpop', { timeout: 3000 });
await page.fill('#cpop textarea', 'an abandoned draft');
await page.keyboard.press('Escape');
const popGone = await page.locator('#cpop').count() === 0;
await page.reload();
const crossReanchored = await page.locator('mark.cmt[data-cid]').count() >= 2;
// drawer lists saved comments and the recovered draft
await page.click('#cmtBtn');
await page.waitForSelector('#cdrawer .drow', { timeout: 3000 });
const drawerRows = await page.locator('#cdrawer .drow').count();
const draftRows = await page.locator('#cdrawer .drow.draft').count();
const draftText = await page.locator('#cdrawer .drow.draft .db').first().textContent();
// tooltips carry the shortcut, and no title attributes are used
const tipText = await page.locator('#copyBtn').getAttribute('data-tip');
const noTitleAttrs = await page.locator('.topbar [title]').count() === 0;
await page.click('#cdrawer [data-d="close"]');
await page.click('#copyBtn');
const json2 = JSON.parse(await page.evaluate(() => navigator.clipboard.readText()));
const draftInJSON = (json2.drafts || []).some(d => d.comment === 'an abandoned draft');
console.log(JSON.stringify({ crossMarks, popGone, crossReanchored, drawerRows, draftRows,
  draftText, tipText, noTitleAttrs, draftInJSON }, null, 1));
console.log(JSON.stringify({ okTopbar, okProgress, collapsed, okProgress2, markCount, selectionSurvives,
  jsonAnswer: json.answers[0], jsonComment: json.comments[0], okDownload, dlName,
  persistTick, persistAns, reanchored, errors }, null, 1));

// ── editable document: click-to-edit, toolbar, rail, tables ──────────────
// Only runs when the page carries a [data-doc]; a brief without one skips it.
if (await page.locator('[data-doc]').count()) {
  const doc = page.locator('[data-doc]').first();
  const railBars = await doc.locator('.doc-bar-i').count();          // rail built while reading
  const toolsHiddenAtRest = await doc.locator('.doc-tools').isHidden();

  // click the rendered text: it enters edit mode AND lands the caret there
  const para = doc.locator('.doc-view p').first();
  await para.scrollIntoViewIfNeeded();
  const box = await para.boundingBox();
  await page.mouse.click(box.x + box.width - 60, box.y + box.height / 2);
  const editable = await doc.locator('.doc-view').getAttribute('contenteditable');
  const toolsVisible = await doc.locator('.doc-tools').isVisible();
  const caretInPara = await page.evaluate(() => {
    const s = getSelection(); if (!s.rangeCount) return false;
    let n = s.getRangeAt(0).startContainer;
    while (n && n.nodeName !== 'P') n = n.parentNode;
    return !!n;
  });
  // the caret is where the click was, not at the start of the block
  const caretOffset = await page.evaluate(() => getSelection().getRangeAt(0).startOffset);
  await page.keyboard.type('EDITED-IN-PLACE');
  await page.waitForTimeout(120);
  const flag = await doc.locator('.doc-flag').textContent();

  // toolbar reflects the caret's context: put it in the H1, H1 lights up
  await page.evaluate(() => {
    const h = document.querySelector('[data-doc] .doc-view h1');
    const r = document.createRange(); r.setStart(h.firstChild, 1); r.collapse(true);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
    document.querySelector('[data-doc] .doc-view').dispatchEvent(new Event('keyup', { bubbles: true }));
  });
  await page.waitForTimeout(80);
  const h1Active = await doc.locator('.doc-tool', { hasText: 'H1' }).first().evaluate(el => el.classList.contains('on'));

  // bold via the toolbar, on a selection, survives the round-trip to markdown
  await page.evaluate(() => {
    const el = document.querySelector('[data-doc] .doc-view p');
    const r = document.createRange(); r.setStart(el.firstChild, 0); r.setEnd(el.firstChild, 5);
    const s = getSelection(); s.removeAllRanges(); s.addRange(r);
  });
  await doc.locator('.doc-tool.t-b').click();
  await page.waitForTimeout(120);

  // Raw MD carries the same document, as markdown — including the table
  await doc.locator('.doc-srcbtn').click();
  const md = await doc.locator('.doc-src').inputValue();
  const mdHasEdit = md.includes('EDITED-IN-PLACE');
  const mdHasHeading = /^# Heading one/m.test(md);
  const mdHasList = /^- one$/m.test(md);
  const mdHasQuote = /^> a quote/m.test(md);
  const mdHasBold = /\*\*/.test(md);
  const mdHasTable = /^\| Col A \| Col B \|/m.test(md) && /^\|\s*---/m.test(md);
  const srcBtnLabel = await doc.locator('.doc-srcbtn').textContent();

  // back to rich, Done, reload: the edit persists, stored as markdown
  await doc.locator('.doc-srcbtn').click();
  const tableRendered = await doc.locator('.doc-view table td').count();
  await doc.locator('.doc-done').click();
  await page.reload();
  const persisted = (await doc.locator('.doc-view').textContent()).includes('EDITED-IN-PLACE');
  const stored = await page.evaluate(() => JSON.parse(localStorage.getItem(Object.keys(localStorage).find(k => k.includes('test-brief')))));
  const editStored = Object.values(stored.edits || {}).some(v => typeof v === 'string' && v.includes('EDITED-IN-PLACE'));

  // heading rail: hovering opens the flyout of titles, active bar is marked
  await doc.locator('.doc-bar-i').first().hover();
  await page.waitForTimeout(100);
  const flyoutOpen = await doc.locator('.doc-fly').isVisible();
  const flyoutItems = await doc.locator('.doc-fly-i').count();
  const hasActiveBar = await doc.locator('.doc-bar-i.on').count();

  await doc.locator('.doc-revert').click();
  const afterRevert = await doc.locator('.doc-view').textContent();
  console.log(JSON.stringify({ railBars, toolsHiddenAtRest, editable, toolsVisible, caretInPara,
    caretMidBlock: caretOffset > 0, flag, h1Active, mdHasEdit, mdHasHeading, mdHasList, mdHasQuote,
    mdHasBold, mdHasTable, tableRendered, srcBtnLabel, persisted, editStored, flyoutOpen,
    flyoutItems, hasActiveBar, revertClean: !afterRevert.includes('EDITED-IN-PLACE') }, null, 1));
}

// comments drawer: one click opens it, one closes it. Re-rendering the button's
// icon used to detach the click target and close the drawer on the same click.
const cbtn = page.locator('#cmtBtn');
await cbtn.click(); await page.waitForTimeout(80);
const drawerOpensInOneClick = await page.locator('#cdrawer').isVisible();
await cbtn.click(); await page.waitForTimeout(80);
const drawerClosesInOneClick = await page.locator('#cdrawer').isHidden();
console.log(JSON.stringify({ drawerOpensInOneClick, drawerClosesInOneClick, jsErrors: errors }, null, 1));

await browser.close();
