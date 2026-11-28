// Open in QuantiSheet: the add-on tried in a real (headless) browser.
//
//     node tools/addon_test/run.js [name ...]
//     NOHOST=1 node tools/addon_test/run.js store direct viewer
//
// Needs Node.js with Playwright and its Chromium, and Python 3. It loads a
// temporary copy of browser_extension/ (given site access up front, since
// nobody is there to click the toolbar button), serves made-up PDFs and
// pages from 127.0.0.1, and plays QuantiSheet's side of the direct line
// with tools/addon_test/host.py (app/browserhost.py itself, saving into a
// temporary folder instead of starting the program). NOHOST=1 leaves the
// program's side out, as with the Store copy: the checks named direct,
// restart, always, button, denied, guard, guardhtml and store are about
// that download route and only mean something with NOHOST=1. Each line
// printed is one check; read them, there is no pass/fail total. Everything is made up
// and stays in a temporary folder.
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path'), os = require('os');
const { execFileSync } = require('child_process');
const ROOT = path.resolve(__dirname, '..', '..');
const WORK = fs.mkdtempSync(path.join(os.tmpdir(), 'qs-addon-test-'));
const GOT = WORK + '/got', FIX = WORK + '/fixtures';
fs.mkdirSync(GOT); fs.mkdirSync(FIX);
execFileSync('python3', [path.join(__dirname, 'make_fixtures.py'), FIX]);
// the add-on with its optional access granted
const EXT = WORK + '/ext';
fs.cpSync(path.join(ROOT, 'browser_extension'), EXT, { recursive: true });
{ const mp = EXT + '/manifest.json'; const m = JSON.parse(fs.readFileSync(mp, 'utf8'));
  m.permissions = m.permissions.concat(m.optional_permissions || []); delete m.optional_permissions;
  m.host_permissions = m.optional_host_permissions || []; delete m.optional_host_permissions;
  fs.writeFileSync(mp, JSON.stringify(m)); }
fs.writeFileSync(WORK + '/run.sh', '#!/bin/bash\nQS_ROOT="' + ROOT + '" QS_WORK="' + WORK + '" exec python3 "' + path.join(__dirname, 'host.py') + '"\n', { mode: 0o755 });
const PDF = Buffer.from('%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n');
const seen = [];
const srv = http.createServer((q, r) => {
  const u = q.url.split('?')[0];
  if (u === '/plan.pdf') { r.writeHead(200, {'content-type':'application/pdf'}); r.end(PDF); }
  else if (u === '/dl') { r.writeHead(200, {'content-type':'application/pdf','content-disposition':'attachment; filename="Site Plan A-101.pdf"'}); r.end(PDF); }
  else if (u === '/nopdfname') { r.writeHead(200, {'content-type':'application/pdf'}); r.end(PDF); }
  else if (u === '/viewer.pdf') { r.writeHead(200, {'content-type':'text/html'}); r.end('<title>Viewer</title><a id=d href="/dl">Download</a>'); }
  else if (u === '/guard.pdf') { const ok = q.headers['sec-fetch-dest'] === 'document' || q.headers['sec-fetch-site'] === 'same-origin'; seen.push([q.headers['sec-fetch-dest'], q.headers['sec-fetch-site'], ok]); if (ok) { r.writeHead(200, {'content-type':'application/pdf','cache-control':'max-age=600'}); r.end(PDF); } else { r.writeHead(403, {'content-type':'text/html'}); r.end('<h1>Forbidden</h1>'); } }
  else if (u === '/guardhtml.pdf') { const ok = q.headers['sec-fetch-dest'] === 'document' || q.headers['sec-fetch-site'] === 'same-origin'; if (ok) { r.writeHead(200, {'content-type':'application/pdf'}); r.end(PDF); } else { r.writeHead(200, {'content-type':'text/html'}); r.end('<h1>Checking your browser</h1>'); } }
  else if (u === '/big.pdf') { r.writeHead(200, {'content-type':'application/pdf'}); r.end(Buffer.concat([PDF, Buffer.alloc(30*1024*1024, 32)])); }
  else if (u === '/long') { r.writeHead(200, {'content-type':'text/html; charset=utf-8'}); r.end('<title>Made-up Bid Notice: Clinic / Phase 2?</title><h1 style="background:#0e6a60;color:#fff">Made-up Bid Notice</h1>' + Array.from({length: 400}, (_, i) => '<p>Line ' + i + ' of a made-up bid notice with enough words to fill a row.</p>').join('')); }
  else if (u === '/text.pdf') { r.writeHead(200, {'content-type':'application/pdf'}); r.end(fs.readFileSync(FIX + '/text.pdf')); }
  else if (u === '/rot.pdf') { r.writeHead(200, {'content-type':'application/pdf'}); r.end(fs.readFileSync(FIX + '/rot.pdf')); }
  else if (u === '/lines.pdf') { r.writeHead(200, {'content-type':'application/pdf'}); r.end(fs.readFileSync(FIX + '/lines.pdf')); }
  else if (u === '/slow.pdf') { r.writeHead(200, {'content-type':'application/pdf'}); r.write(PDF.slice(0,20)); setTimeout(()=>r.end(PDF.slice(20)), 40000); }
  else { r.writeHead(200, {'content-type':'text/html'}); r.end('<title>Made-up Bid Page</title><a id=l href="/plan.pdf">plan</a> <a id=d href="/dl">dl</a>'); }
}).listen(8765);
(async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qsx-'));
  if (!process.env.NOHOST) { fs.mkdirSync(dir + '/NativeMessagingHosts', {recursive:true}); fs.writeFileSync(dir + '/NativeMessagingHosts/com.quantisheet.open.json', JSON.stringify({name:'com.quantisheet.open', description:'t', path: WORK + '/run.sh', type:'stdio', allowed_origins:['chrome-extension://klfflmcmedeghfecpbdmfajjhdbhigap/']})); }
  for (const f of fs.readdirSync(GOT)) fs.unlinkSync(GOT + '/' + f);
  const ctx = await chromium.launchPersistentContext(dir, { channel: 'chromium', headless: true, viewport: { width: 1280, height: 800 }, acceptDownloads: true,
    args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`] });
  let [sw] = ctx.serviceWorkers(); if (!sw) sw = await ctx.waitForEvent('serviceworker', {timeout: 15000});
  const id = sw.url().split('/')[2]; console.log('extension loaded', id);
  sw.on('console', m => console.log('  sw:', m.text()));
  const errs = []; ctx.on('weberror', e => errs.push(String(e.error())));
  const B = 'http://127.0.0.1:8765';
  const openTabs = async () => ctx.pages().map(p => p.url());
  const handoffs = async () => (await openTabs()).filter(u => u.includes('open.html'));
  const closeHandoffs = async () => { for (const p of ctx.pages()) if (p.url().includes('open.html') || p.url().startsWith('quantisheet')) await p.close(); };
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const mods = process.argv.slice(2);
  const run = async (name, fn) => { if (mods.length && !mods.includes(name)) return; try { await fn(); } catch (e) { console.log('FAIL', name, String(e).slice(0, 300)); } await closeHandoffs(); };

  // message helper: an extension page sends what the popup sends
  const ext = await ctx.newPage(); await ext.goto(`chrome-extension://${id}/popup.html`);
  ext.on('console', m => console.log('  popup:', m.text()));
  ext.on('pageerror', e => console.log('  popup error:', String(e)));
  { const c = await ctx.newCDPSession(ext); fs.mkdirSync(dir + '/dl'); await c.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: dir + '/dl' }); }
  const msg = m => ext.evaluate(m => new Promise(r => chrome.runtime.sendMessage(m, x => r(x || String(chrome.runtime.lastError && chrome.runtime.lastError.message)))), m);

  await run('direct', async () => {
    const r = await msg({ type: 'qs-open', url: B + '/plan.pdf', title: '', tabId: 1 });
    await wait(2500); const h = await handoffs();
    console.log('  downloads:', JSON.stringify(await sw.evaluate(() => chrome.downloads.search({}).then(a => a.map(i => [i.filename, i.mime, i.state, i.exists, i.error])))));
    console.log('1 direct PDF:', JSON.stringify(r), '-> hand-off', h.length === 1 ? decodeURIComponent(h[0].split('path=')[1]) : h);
  });
  await run('page', async () => {
    const p = [...ctx.pages()].find(p => p.url().includes('open.html'));
  });
  await run('handoffpage', async () => {
    const p = await ctx.newPage(); const nav = [];
    p.on('console', m => console.log('  open:', m.text())); p.on('pageerror', e => console.log('  open error:', String(e)));
    p.on('request', q => nav.push(q.url()));
    await p.goto(`chrome-extension://${id}/open.html?path=` + encodeURIComponent('D:\\Made up\\Downloads\\QuantiSheet\\A-101 Plan #2 & more.pdf'));
    await wait(800);
    console.log('2 hand-off page: file', JSON.stringify(await p.textContent('#file')), 'link', await p.getAttribute('#go', 'href'));
  });
  await run('viewer', async () => {
    const r = await msg({ type: 'qs-open', url: B + '/viewer.pdf', title: 'Viewer', tabId: 1 });
    await wait(2500);
    const w = await sw.evaluate(() => chrome.storage.session.get('watch'));
    const left = fs.existsSync(path.join(dir, 'x')); 
    console.log('3 page that is not a PDF:', JSON.stringify(r), 'hand-offs', (await handoffs()).length, 'watching', !!w.watch);
    const p = await ctx.newPage(); await p.goto(B + '/'); 
    await p.click('#d'); await wait(2500);
    const h = await handoffs();
    console.log('  then the site\'s own download:', h.length === 1 ? decodeURIComponent(h[0].split('path=')[1]) : h, 'still watching', !!(await sw.evaluate(() => chrome.storage.session.get('watch'))).watch);
    await p.close();
  });
  await run('unwatched', async () => {
    const p = await ctx.newPage(); await p.goto(B + '/');
    await p.click('#d'); await wait(2000);
    console.log('4 a download nobody asked us about: hand-offs', (await handoffs()).length, '(want 0)');
    await p.close();
  });
  await run('menu', async () => {
    console.log('5 menus:', await sw.evaluate(() => new Promise(r => chrome.contextMenus.update('qs-open-link', {}, () => r(chrome.runtime.lastError ? 'MISSING' : 'present')))));
  });
  await run('popup', async () => {
    const t = await ctx.newPage(); await t.goto(B + '/plan.pdf').catch(e => console.log('  nav', String(e).slice(0,80)));
    await wait(500);
    console.log('6 pdf tab:', t.url(), JSON.stringify(await t.title()));
    await t.close();
  });
  await run('restart', async () => {
    const r = await msg({ type: 'qs-open', url: B + '/slow.pdf', title: '', tabId: 1 });
    await wait(1500);
    console.log('7 worker forgets mid-download; stored:', JSON.stringify(await sw.evaluate(() => { waiting.clear(); return chrome.storage.session.get('mine'); })));
    await wait(42000);
    console.log('  hand-offs after the slow download:', (await handoffs()).length, '(want 1); stored now', JSON.stringify(await sw.evaluate(() => chrome.storage.session.get('mine'))));
  });
  await run('always', async () => {
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: true, button: false } }));
    const t = await ctx.newPage(); await t.goto(B + '/plan.pdf').catch(() => {}); await wait(3000);
    console.log('8 always open: hand-offs', (await handoffs()).length, '(want 1)');
    await closeHandoffs();
    await t.goto(B + '/').catch(() => {}); await wait(1500);
    console.log('  an ordinary page: hand-offs', (await handoffs()).length, '(want 0)');
    await t.goto(B + '/dl').catch(() => {}); await wait(2000);
    console.log('  a plain download (attachment): hand-offs', (await handoffs()).length, '(want 0)');
    await t.close();
  });
  await run('button', async () => {
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: true } }));
    const t = await ctx.newPage(); await t.goto(B + '/plan.pdf').catch(() => {}); await wait(2500);
    const has = await t.evaluate(() => !!document.getElementById('qs-open-btn')).catch(e => 'cannot look: ' + String(e).slice(0, 80));
    console.log('9 button on the PDF:', has, '; hand-offs before a click', (await handoffs()).length);
    await t.screenshot({ path: WORK + '/button.png' }).catch(() => {});
    await t.mouse.click(1280 - 24 - 110, 64 + 18).catch(() => {}); await wait(3000);
    console.log('  after clicking it: hand-offs', (await handoffs()).length, '(want 1)');
    await t.close();
  });
  await run('denied', async () => {
    await msg({ type: 'qs-open', url: B + '/slow.pdf', title: '', tabId: 1 });
    await wait(1500);
    const r = await sw.evaluate(async () => {
      const mine = (await chrome.storage.session.get('mine')).mine; const id = Number(Object.keys(mine)[0]);
      const before = JSON.stringify(mine[id]);
      const can = typeof chrome.downloads.onChanged.dispatch;
      await chrome.downloads.cancel(id);
      if (can === 'function') chrome.downloads.onChanged.dispatch({ id, state: { current: 'interrupted' }, error: { current: 'FILE_ACCESS_DENIED' } });
      await new Promise(r => setTimeout(r, 1500));
      return { before, can, after: JSON.stringify((await chrome.storage.session.get('mine')).mine), watch: !!(await chrome.storage.session.get('watch')).watch };
    });
    console.log('10 cannot write there:', JSON.stringify(r));
  });
  for (const [n, pth] of [['guard', '/guard.pdf'], ['guardhtml', '/guardhtml.pdf']]) await run(n, async () => {
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: false } }));
    const t = await ctx.newPage(); await t.goto(B + pth).catch(() => {}); await wait(1500);
    const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + pth);
    const r = await msg({ type: 'qs-open', url: B + pth, title: await t.title(), tabId });
    await wait(4000); const h = await handoffs();
    console.log('11 site refuses a second download (' + n + '): tab', tabId, JSON.stringify(r), '-> hand-off', h.length === 1 ? decodeURIComponent(h[0].split('path=')[1]) : h, 'requests', JSON.stringify(seen));
    console.log('   downloads left listed:', JSON.stringify(await sw.evaluate(() => chrome.downloads.search({}).then(a => a.map(i => [i.filename.split('/').pop(), i.state, i.error])))));
    await t.close();
  });
  const got = () => fs.readdirSync(GOT).map(f => f + ':' + fs.statSync(GOT + '/' + f).size);
  await run('app', async () => {
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: false } }));
    let r = await msg({ type: 'qs-open', url: B + '/plan.pdf', title: '', tabId: 1 });
    console.log('A link/no tab ->', JSON.stringify(r), got(), 'downloads', await sw.evaluate(() => chrome.downloads.search({}).then(a => a.length)), 'hand-off tabs', (await handoffs()).length);
    for (const pth of ['/guard.pdf', '/guardhtml.pdf', '/big.pdf']) {
      const t = await ctx.newPage(); await t.goto(B + pth).catch(() => {}); await wait(1500);
      const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + pth);
      const t0 = Date.now(); r = await msg({ type: 'qs-open', url: B + pth, title: 'Made-up: Sheet/Set?', tabId });
      console.log('B tab ' + pth + ' ->', JSON.stringify(r), (Date.now() - t0) + 'ms', got().filter(x => !x.startsWith('opened')).join(' | '));
      await t.close();
    }
    r = await msg({ type: 'qs-open', url: B + '/viewer.pdf', title: 'Viewer', tabId: 1 });
    await wait(1500);
    console.log('C not a PDF ->', JSON.stringify(r), 'watching', !!(await sw.evaluate(() => chrome.storage.session.get('watch'))).watch, 'parts left', got().filter(x => x.includes('.part')));
    console.log('opened:', fs.existsSync(GOT + '/opened.txt') ? fs.readFileSync(GOT + '/opened.txt', 'utf8').trim().split('\n').map(p => p.split('/').pop()) : 'nothing');
  });
  await run('webpage', async () => {
    for (const f of fs.readdirSync(GOT)) fs.unlinkSync(GOT + '/' + f);
    const t = await ctx.newPage(); await t.goto(B + '/long'); await wait(800);
    const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/long');
    const t0 = Date.now(); const r = await msg({ type: 'qs-page', url: B + '/long', title: await t.title(), tabId });
    console.log('W web page ->', JSON.stringify(r), (Date.now() - t0) + 'ms', got().join(' | '));
    const r2 = await msg({ type: 'qs-page', url: 'chrome://version', title: 'x', tabId });
    console.log('W not a web page ->', JSON.stringify(r2));
    console.log('W debugger still attached:', JSON.stringify(await sw.evaluate(() => chrome.debugger.getTargets().then(a => a.filter(x => x.attached && x.type === 'page').length))));
    await t.close();
  });
  await run('viewer2', async () => {
    for (const f of fs.readdirSync(GOT)) fs.unlinkSync(GOT + '/' + f);
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: false, viewer: false } }));
    const t = await ctx.newPage(); const errs2 = [];
    t.on('console', m => { if (m.type() === 'error') errs2.push(m.text().slice(0, 200)); }); t.on('pageerror', e => errs2.push('PAGEERR ' + String(e).slice(0, 200)));
    await t.goto(B + '/guard.pdf').catch(() => {}); await wait(1500);
    const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/guard.pdf');
    const r = await msg({ type: 'qs-view', url: B + '/guard.pdf', title: await t.title(), tabId });
    await wait(4000);
    const st = await t.evaluate(() => ({ url: location.pathname + location.search.slice(0, 5), pages: window.PDFViewerApplication && window.PDFViewerApplication.pagesCount, title: document.title, btn: !!document.getElementById('qsOpen'), editors: ['editorHighlightButton', 'editorFreeTextButton', 'editorInkButton', 'editorStampButton'].map(i => { const b = document.getElementById(i); return b ? !b.disabled : null; }) })).catch(e => String(e).slice(0, 200));
    console.log('V view here ->', JSON.stringify(r), JSON.stringify(st), 'errors', JSON.stringify(errs2));
    await t.screenshot({ path: WORK + '/viewer.png' });
    await t.click('#editorFreeTextButton').catch(e => console.log('  no text tool', String(e).slice(0, 80)));
    await t.mouse.click(640, 400); await t.keyboard.type('Made-up note: check drain at C-4'); await t.keyboard.press('Escape'); await wait(500);
    await t.click('#qsOpen'); await wait(2500);
    console.log('V open in QuantiSheet ->', JSON.stringify(await t.evaluate(() => document.getElementById('qsNote').textContent)), got().filter(x => !x.startsWith('opened')).join(' | '));
    await t.screenshot({ path: WORK + '/viewer2.png' });
    await t.close();
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: false, viewer: true } }));
    const t2 = await ctx.newPage(); const e3 = []; t2.on('pageerror', e => e3.push(String(e).slice(0, 200)));
    await t2.goto(B + '/plan.pdf').catch(() => {}); await wait(4000);
    console.log('V every PDF ->', JSON.stringify(await t2.evaluate(() => ({ url: location.pathname + location.search.slice(0, 5), pages: window.PDFViewerApplication && window.PDFViewerApplication.pagesCount })).catch(e => String(e).slice(0, 120))), 'errors', JSON.stringify(e3));
    await t2.goto(B + '/').catch(() => {}); await wait(1200);
    console.log('V an ordinary page stays:', t2.url());
    await t2.close();
  });
  await run('store', async () => {
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: false, viewer: false } }));
    const t = await ctx.newPage(); await t.goto(B + '/long'); await wait(800);
    let tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/long');
    let r = await msg({ type: 'qs-page', url: B + '/long', title: await t.title(), tabId });
    await wait(3000); let h = await handoffs();
    console.log('S page to PDF, no direct line ->', JSON.stringify(r), 'hand-off', h.length === 1 ? decodeURIComponent(h[0].split('path=')[1]).split('/').pop() : h, fs.readdirSync(dir + '/dl').map(f => f + ':' + fs.statSync(dir + '/dl/' + f).size).join(' | '));
    await closeHandoffs(); await t.close();
    const v = await ctx.newPage(); await v.goto(B + '/guard.pdf').catch(() => {}); await wait(1200);
    tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/guard.pdf');
    await msg({ type: 'qs-view', url: B + '/guard.pdf', title: '', tabId }); await wait(3500);
    await v.click('#editorFreeTextButton'); await v.mouse.click(640, 400); await v.keyboard.type('Made-up note for the Store copy'); await v.keyboard.press('Escape'); await wait(400);
    await v.click('#qsOpen'); await wait(3500); h = await handoffs();
    console.log('S viewer button, no direct line ->', JSON.stringify(await v.evaluate(() => document.getElementById('qsNote').textContent)), 'hand-off', h.length === 1 ? decodeURIComponent(h[0].split('path=')[1]).split('/').pop() : h, fs.readdirSync(dir + '/dl').map(f => f + ':' + fs.statSync(dir + '/dl/' + f).size).join(' | '));
    await v.close();
  });
  await run('marks', async () => {
    for (const f of fs.readdirSync(GOT)) fs.unlinkSync(GOT + '/' + f);
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: false, viewer: false } }));
    const v = await ctx.newPage(); const er = []; v.on('pageerror', e => er.push(String(e).slice(0, 160)));
    await v.goto(B + '/text.pdf').catch(() => {}); await wait(1200);
    const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/text.pdf');
    await msg({ type: 'qs-view', url: B + '/text.pdf', title: '', tabId }); await wait(3500);
    const box = await v.evaluate(() => { const s = [...document.querySelectorAll('.textLayer span')].find(x => x.textContent.includes('Roof drain')); const r = s.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; });
    // highlight: select the words with the highlight tool on
    await v.click('#editorHighlightButton'); await wait(300);
    await v.mouse.move(box[0] + 3, box[1] + box[3] / 2); await v.mouse.down(); await v.mouse.move(box[0] + box[2] - 3, box[1] + box[3] / 2, { steps: 8 }); await v.mouse.up(); await wait(500);
    // draw
    await v.click('#editorInkButton'); await wait(300);
    const y0 = box[1] + 120; await v.mouse.move(box[0], y0); await v.mouse.down(); await v.mouse.move(box[0] + 150, y0 + 60, { steps: 10 }); await v.mouse.move(box[0] + 250, y0 + 10, { steps: 10 }); await v.mouse.up(); await wait(400);
    await v.keyboard.press('Escape'); await wait(200);
    // text note
    await v.click('#editorFreeTextButton'); await wait(300); await v.mouse.click(box[0] + 40, y0 + 160); await v.keyboard.type('Made-up note: confirm drain'); await v.keyboard.press('Escape'); await wait(300);
    // image
    await v.click('#editorStampButton'); await wait(300);
    const fc = v.waitForEvent('filechooser', { timeout: 5000 }).catch(() => null);
    await v.click('#editorStampAddImage').catch(e => console.log('  no add-image button', String(e).slice(0, 60)));
    const ch = await fc; if (ch) { await ch.setFiles(FIX + '/stamp.png'); await wait(1500); } else console.log('  no file chooser');
    await v.keyboard.press('Escape'); await wait(300);
    await v.screenshot({ path: WORK + '/marks.png' });
    await v.click('#qsOpen'); await wait(3000);
    console.log('M all four tools ->', JSON.stringify(await v.evaluate(() => document.getElementById('qsNote').textContent)), got().filter(x => !x.startsWith('opened')).join(' | '), 'errors', JSON.stringify(er));
    await v.close();
  });
  await run('takeoff', async () => {
    for (const f of fs.readdirSync(GOT)) fs.unlinkSync(GOT + '/' + f);
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: false, viewer: false } }));
    const v = await ctx.newPage(); const er = []; v.on('pageerror', e => er.push(String(e).slice(0, 200))); v.on('console', m => { if (m.type() === 'error') er.push(m.text().slice(0, 200)); });
    await v.goto(B + '/text.pdf').catch(() => {}); await wait(1200);
    const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/text.pdf');
    await msg({ type: 'qs-view', url: B + '/text.pdf', title: '', tabId }); await wait(3500);
    await v.click('#qsTakeoffBtn'); await wait(300);
    const idx = await v.evaluate(() => [...document.querySelectorAll('#qsPreset option')].findIndex(o => o.textContent.startsWith('1/4')));
    await v.selectOption('#qsPreset', { index: idx }); await wait(300);
    const pg = await v.evaluate(() => { const r = document.querySelector('.page').getBoundingClientRect(); const vp = PDFViewerApplication.pdfViewer.getPageView(0).viewport; return [r.left + (document.querySelector('.page').clientLeft || 0), r.top + (document.querySelector('.page').clientTop || 0), vp.scale]; });
    const at = (x, y) => [pg[0] + x * pg[2], pg[1] + (792 - y) * pg[2]];   // PDF point -> screen
    await v.fill('#qsGroup', 'Walls'); await v.click('button[data-tool=length]');
    let p = at(72, 700); await v.mouse.click(p[0], p[1]); p = at(252, 700); await v.mouse.click(p[0], p[1]); await v.keyboard.press('Enter'); await wait(300);
    await v.fill('#qsGroup', 'Slab'); await v.click('button[data-tool=area]');
    for (const q of [[72, 400], [252, 400], [252, 580], [72, 580]]) { p = at(q[0], q[1]); await v.mouse.click(p[0], p[1]); await wait(60); }
    await v.keyboard.press('Enter'); await wait(300);
    await v.fill('#qsGroup', 'Doors'); await v.click('button[data-tool=count]');
    for (const q of [[300, 500], [330, 500], [360, 500]]) { p = at(q[0], q[1]); await v.mouse.click(p[0], p[1]); await wait(60); }
    await v.click('button[data-tool=count]'); await wait(300);
    await v.click('button[data-tool=erase]'); p = at(330, 500); await v.mouse.click(p[0], p[1]); await wait(200); await v.click('button[data-tool=erase]'); await wait(200);
    console.log('T totals:', JSON.stringify(await v.evaluate(() => document.getElementById('qsTotals').innerText.split('\n'))), 'scale:', await v.evaluate(() => document.getElementById('qsScaleNow').textContent));
    await v.screenshot({ path: WORK + '/takeoff.png' });
    await v.reload(); await wait(3500);
    console.log('T after reload, kept:', await v.evaluate(() => window.QSTakeoff.count()), 'drawn:', await v.evaluate(() => document.querySelectorAll('svg.qsTakeoff *').length));
    await v.click('#qsOpen'); await wait(3000);
    const mk = fs.existsSync(GOT + '/marks.json') ? JSON.parse(fs.readFileSync(GOT + '/marks.json', 'utf8')) : null;
    console.log('T sent ->', JSON.stringify(await v.evaluate(() => document.getElementById('qsNote').textContent)));
    console.log('T marks at the program:', mk && JSON.stringify({ scales: mk.scales, marks: mk.marks.map(m => [m.type, m.group, m.pts.map(q => q.map(n => Math.round(n)))]) }), 'errors', JSON.stringify(er));
    await v.close();
  });
  await run('rot', async () => {
    for (const f of fs.readdirSync(GOT)) fs.unlinkSync(GOT + '/' + f);
    const v = await ctx.newPage(); const er = []; v.on('pageerror', e => er.push(String(e).slice(0, 200)));
    await v.goto(B + '/rot.pdf').catch(() => {}); await wait(1200);
    const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/rot.pdf');
    await msg({ type: 'qs-view', url: B + '/rot.pdf', title: '', tabId }); await wait(3500);
    await v.click('#qsTakeoffBtn'); await wait(300);
    // the scale by two points: across the words, 'said to be' 10 ft
    const box = await v.evaluate(() => { const s = [...document.querySelectorAll('.textLayer span')].find(x => x.textContent.includes('sideways')); const r = s.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; });
    await v.click('button[data-tool=calibrate]');
    await v.mouse.click(box[0], box[1] + box[3] / 2); await wait(100); await v.mouse.click(box[0] + box[2], box[1] + box[3] / 2); await wait(300);
    await v.fill('#qsCalLen', '10'); await v.click('#qsCalOk'); await wait(300);
    await v.fill('#qsGroup', 'Run'); await v.click('button[data-tool=length]');
    await v.mouse.click(box[0], box[1] + box[3] + 40); await wait(100); await v.mouse.click(box[0] + box[2], box[1] + box[3] + 40); await v.keyboard.press('Enter'); await wait(300);
    console.log('R on a sideways page:', JSON.stringify(await v.evaluate(() => [document.getElementById('qsScaleNow').textContent, document.getElementById('qsTotals').innerText, window.QSTakeoff.data().marks[0].pts.map(p => p.map(Math.round)), getComputedStyle(document.querySelector('.page')).width])), 'errors', JSON.stringify(er));
    await v.screenshot({ path: WORK + '/rot.png' });
    await v.click('#qsOpen'); await wait(2500);
    fs.copyFileSync(GOT + '/marks.json', WORK + '/rot-marks.json');
    await v.close();
  });
  await run('snap', async () => {
    const v = await ctx.newPage(); const er = []; v.on('pageerror', e => er.push(String(e).slice(0, 200)));
    await v.goto(B + '/lines.pdf').catch(() => {}); await wait(1200);
    const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/lines.pdf');
    await msg({ type: 'qs-view', url: B + '/lines.pdf', title: '', tabId }); await wait(3500);
    await v.click('#qsTakeoffBtn'); await wait(500);
    const pg = await v.evaluate(() => { const d = document.querySelector('.page'); const r = d.getBoundingClientRect(); return [r.left + d.clientLeft, r.top + d.clientTop, PDFViewerApplication.pdfViewer.getPageView(0).viewport.scale]; });
    const at = (x, y) => [pg[0] + x * pg[2], pg[1] + (792 - y) * pg[2]];
    await v.click('button[data-tool=length]'); await wait(800);
    let p = at(102, 498); await v.mouse.move(p[0], p[1]); await v.mouse.click(p[0], p[1]); p = at(198, 503); await v.mouse.move(p[0], p[1]); await v.mouse.click(p[0], p[1]); await v.keyboard.press('Enter'); await wait(300);
    p = at(121, 522); await v.mouse.click(p[0], p[1]); p = at(250, 600); await v.mouse.click(p[0], p[1]); await v.keyboard.press('Enter'); await wait(300);
    await v.uncheck('#qsSnap'); p = at(74, 698); await v.mouse.click(p[0], p[1]); p = at(298, 702); await v.mouse.click(p[0], p[1]); await v.keyboard.press('Enter'); await wait(300);
    console.log('N snapped:', JSON.stringify(await v.evaluate(() => window.QSTakeoff.data().marks.map(m => m.pts.map(q => q.map(n => Math.round(n * 100) / 100))))), 'errors', JSON.stringify(er));
    await v.screenshot({ path: WORK + '/snap.png' });
    await v.close();
  });
  await run('cut', async () => {
    for (const f of fs.readdirSync(GOT)) fs.unlinkSync(GOT + '/' + f);
    const v = await ctx.newPage(); const er = []; v.on('pageerror', e => er.push(String(e).slice(0, 200)));
    await v.goto(B + '/text.pdf').catch(() => {}); await wait(1200);
    const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/text.pdf');
    await msg({ type: 'qs-view', url: B + '/text.pdf', title: '', tabId }); await wait(3500);
    await v.click('#qsTakeoffBtn'); await wait(500);
    const idx = await v.evaluate(() => [...document.querySelectorAll('#qsPreset option')].findIndex(o => o.textContent.startsWith('1/4')));
    await v.selectOption('#qsPreset', { index: idx }); await wait(300); await v.uncheck('#qsSnap');
    const pg = await v.evaluate(() => { const d = document.querySelector('.page'); const r = d.getBoundingClientRect(); return [r.left + d.clientLeft, r.top + d.clientTop, PDFViewerApplication.pdfViewer.getPageView(0).viewport.scale]; });
    const at = (x, y) => [pg[0] + x * pg[2], pg[1] + (792 - y) * pg[2]];
    const poly = async (tool, pts) => { await v.click('button[data-tool=' + tool + ']'); for (const q of pts) { const p = at(q[0], q[1]); await v.mouse.click(p[0], p[1]); await wait(60); } await v.keyboard.press('Enter'); await wait(250); };
    await v.fill('#qsGroup', 'Slab'); await poly('area', [[72, 400], [252, 400], [252, 580], [72, 580]]);
    await poly('cutout', [[100, 430], [136, 430], [136, 466], [100, 466]]);
    await v.click('button[data-tool=move]'); { let p = at(252, 580); await v.mouse.move(p[0], p[1]); await v.mouse.down(); p = at(288, 580); await v.mouse.move(p[0], p[1], { steps: 5 }); await v.mouse.up(); await wait(200); } await v.click('button[data-tool=move]');
    console.log('C after dragging a corner out 2 ft:', JSON.stringify(await v.evaluate(() => [document.getElementById('qsTotals').innerText, window.QSTakeoff.data().marks[0].pts.map(q => q.map(Math.round))])));
    { await v.click('button[data-tool=move]'); let p = at(288, 580); await v.mouse.move(p[0], p[1]); await v.mouse.down(); p = at(252, 580); await v.mouse.move(p[0], p[1], { steps: 5 }); await v.mouse.up(); await wait(200); await v.click('button[data-tool=move]'); }
    console.log('C totals:', JSON.stringify(await v.evaluate(() => document.getElementById('qsTotals').innerText.split('\n'))), 'errors', JSON.stringify(er));
    await v.screenshot({ path: WORK + '/cut.png' });
    await v.click('#qsOpen'); await wait(2500);
    fs.copyFileSync(GOT + '/marks.json', WORK + '/cut-marks.json');
    console.log('C sent:', JSON.stringify(JSON.parse(fs.readFileSync(WORK + '/cut-marks.json', 'utf8')).marks.map(m => [m.type, m.pts.map(q => q.map(Math.round))])));
    await v.close();
  });
  await run('itoff', async () => {
    fs.writeFileSync(WORK + '/OFF', '1');
    try {
      const r = await msg({ type: 'qs-open', url: B + '/plan.pdf', title: '', tabId: 1 }); await wait(1500);
      const t = await ctx.newPage(); await t.goto(B + '/long'); await wait(600);
      const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/long');
      const r2 = await msg({ type: 'qs-page', url: B + '/long', title: 'x', tabId });
      console.log('I turned off by IT ->', JSON.stringify(r), JSON.stringify(r2), 'downloads', await sw.evaluate(() => chrome.downloads.search({}).then(a => a.length)), 'hand-offs', (await handoffs()).length);
      await t.close();
    } finally { fs.unlinkSync(WORK + '/OFF'); }
  });
  await run('keys', async () => {
    const v = await ctx.newPage();
    await v.goto(B + '/text.pdf').catch(() => {}); await wait(1200);
    const tabId = await sw.evaluate((u) => chrome.tabs.query({}).then(a => (a.find(x => x.url === u) || {}).id), B + '/text.pdf');
    await msg({ type: 'qs-view', url: B + '/text.pdf', title: '', tabId }); await wait(3500);
    const tool = () => v.evaluate(() => { const b = [...document.querySelectorAll('#qsTakeoffPanel button[data-tool]')].find(x => x.style.color === 'rgb(255, 255, 255)'); return b ? b.dataset.tool : null; });
    await v.keyboard.press('Shift+L'); const closed = await tool();
    await v.click('#qsTakeoffBtn'); await wait(300); await v.mouse.click(400, 500);
    await v.keyboard.press('Shift+L'); const a = await tool(); await v.keyboard.press('Shift+A'); const b2 = await tool(); await v.keyboard.press('Shift+C'); const c = await tool();
    await v.click('#qsGroup'); await v.keyboard.type('Lobby Area Count'); const typed = [await tool(), await v.inputValue('#qsGroup')];
    console.log('K keys:', JSON.stringify({ closed, a, b: b2, c, typed }));
    await v.close();
  });
  await run('usual', async () => {
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: false, viewer: true } }));
    const t = await ctx.newPage();
    await t.goto(B + '/guard.pdf').catch(() => {}); await wait(4000);
    const inViewer = t.url().includes('viewer.html');
    const said = await t.evaluate(() => (document.getElementById('qsNote') || {}).textContent).catch(() => null);
    await t.click('#qsUsual').catch(e => console.log('  no way back', String(e).slice(0, 80))); await wait(3000);
    console.log('U a site that will not send the PDF again:', JSON.stringify({ inViewer, said, after: t.url() }));
    await sw.evaluate(() => chrome.storage.local.set({ options: { always: false, button: false, viewer: false } }));
    await t.close();
  });
  console.log('page errors:', errs.length ? errs : 'none');
  await ctx.close(); srv.close();
})().catch(e => { console.log('HARNESS', e); process.exit(1); });
