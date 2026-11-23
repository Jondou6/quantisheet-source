const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const [htmlPath, pdfPath, footerJson] = process.argv.slice(2);
  const footer = JSON.parse(footerJson);
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file://' + path.resolve(htmlPath), { waitUntil: 'load' });
  const opts = { path: pdfPath, format: 'Letter', printBackground: true,
                 preferCSSPageSize: true, outline: true, tagged: true };
  if (footer) {
    opts.displayHeaderFooter = true;
    opts.headerTemplate = '<span></span>';
    opts.footerTemplate = footer;
  }
  await p.pdf(opts);
  await b.close();
})();
