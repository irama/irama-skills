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
console.log(JSON.stringify({ okTopbar, okProgress, collapsed, okProgress2, markCount, selectionSurvives,
  jsonAnswer: json.answers[0], jsonComment: json.comments[0], okDownload, dlName,
  persistTick, persistAns, reanchored, errors }, null, 1));
await browser.close();
