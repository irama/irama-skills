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
await browser.close();
