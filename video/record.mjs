/**
 * Drive the real Cloud HoneyVault app and record it.
 *
 * Nothing here fakes UI. Every frame is the actual frontend at :5173 talking to
 * the actual backend at :8000. The script's only job is to behave like a person
 * would - at a person's pace - so the footage is watchable.
 *
 * Playwright saves one video per browser CONTEXT, written on context.close().
 * Several clips need to continue an earlier login, so instead of keeping a
 * context open we re-seed `sessionStorage` with the token that context captured.
 * That is exactly how the app authenticates (see frontend/src/api.js), so the
 * backend session carries on uninterrupted while each clip still gets its own
 * isolated context and its own file.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(HERE, '..', 'recordings');
const APP = 'http://localhost:5173';
const API = 'http://localhost:8000';

const VIEWPORT = { width: 1920, height: 1080 };

// Human pacing. Actions land 400-800ms apart, with longer beats where a viewer
// needs a moment to read something.
const rand = (lo, hi) => Math.round(lo + Math.random() * (hi - lo));
const beat = (p, lo = 400, hi = 800) => p.waitForTimeout(rand(lo, hi));
const read = (p, ms = 1800) => p.waitForTimeout(ms);

let browser;
const manifest = [];

async function openContext(name) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    recordVideo: { dir: OUT, size: VIEWPORT },
  });
  const page = await context.newPage();
  page.on('pageerror', (e) => console.log(`  [page error in ${name}] ${e.message}`));
  return { context, page, name };
}

/** Close the context and rename the video Playwright wrote to a stable name. */
async function finish(clip) {
  const video = clip.page.video();
  await clip.context.close();
  const tmp = await video.path();
  const dest = path.join(OUT, `${clip.name}.webm`);
  if (fs.existsSync(dest)) fs.unlinkSync(dest);
  fs.renameSync(tmp, dest);
  const kb = Math.round(fs.statSync(dest).size / 1024);
  manifest.push({ name: clip.name, file: path.basename(dest), kb });
  console.log(`  saved ${path.basename(dest)} (${kb} KB)`);
}

/** Log in through the real form, and hand back the credentials it stored. */
async function signIn(page, username, password) {
  await page.goto(`${APP}/login`);
  await page.waitForSelector('#username');
  await beat(page, 600, 900);
  await page.fill('#username', username);
  await beat(page);
  await page.fill('#password', password);
  await beat(page);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(drive|admin)/, { timeout: 15000 });
  await page.waitForTimeout(700);
  return page.evaluate(() => ({
    token: sessionStorage.getItem('hv_token'),
    user: sessionStorage.getItem('hv_user'),
  }));
}

/** Resume an existing backend session in a brand-new context. */
async function resume(clip, creds, route = '/drive') {
  await clip.context.addInitScript(
    ([t, u]) => {
      sessionStorage.setItem('hv_token', t);
      sessionStorage.setItem('hv_user', u);
    },
    [creds.token, creds.user],
  );
  await clip.page.goto(`${APP}${route}`);
  await clip.page.waitForSelector('header.bar', { timeout: 15000 });
  await clip.page.waitForTimeout(800);
}

// ---------------------------------------------------------------- drive acts

async function openFolder(page, name) {
  await page.click(`ul.plain button:has-text("${name} (")`);
  await beat(page, 500, 800);
}

function fileRow(page, filename) {
  return page.locator('tr', { has: page.locator(`td:text-is("${filename}")`) });
}

async function openFile(page, filename, dwell = 2200) {
  await fileRow(page, filename).getByRole('button', { name: 'Open' }).click();
  await page.waitForTimeout(dwell);
}

async function downloadFile(page, filename) {
  const wait = page.waitForEvent('download').catch(() => null);
  await fileRow(page, filename).getByRole('button', { name: 'Download' }).click();
  await wait;
  await beat(page, 700, 1000);
}

/** Type into the search box at human speed, then submit. */
async function search(page, query, dwell = 1600) {
  const box = page.locator('input[placeholder="Search files by name..."]');
  await box.click();
  await box.fill('');
  await box.pressSequentially(query, { delay: 85 });
  await beat(page, 350, 550);
  await page.click('button:has-text("Search")');
  await page.waitForTimeout(dwell);
}

// ------------------------------------------------------------- admin acts

async function refreshAdmin(page) {
  await page.click('button:has-text("Refresh now")');
  await page.waitForTimeout(900);
}

/** Open a session's detail card by its numeric id. */
async function viewSession(page, sessionId, dwell = 2200) {
  // Scope to rows that actually have a View button, then match the first cell
  // only - a bare numeric match would also hit the score or action-count column.
  const row = page
    .locator('tr', { has: page.getByRole('button', { name: 'View' }) })
    .filter({ has: page.locator(`td:nth-child(1):text-is("${sessionId}")`) })
    .first();
  await row.scrollIntoViewIfNeeded();
  await row.getByRole('button', { name: 'View' }).click();
  await page.waitForSelector('#session-detail', { timeout: 10000 });
  await page.waitForTimeout(dwell);
}

async function scrollTo(page, selector, dwell = 1500) {
  await page.locator(selector).first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(dwell);
}

// ---------------------------------------------------------------- the script

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  for (const f of fs.readdirSync(OUT)) fs.unlinkSync(path.join(OUT, f));

  const health = await fetch(`${API}/health`).then((r) => r.json());
  if (health.status !== 'ok') throw new Error('backend is not healthy');
  const front = await fetch(APP);
  if (!front.ok) throw new Error(`frontend returned ${front.status}`);
  console.log('prerequisites ok\n');

  browser = await chromium.launch();

  // Admin signs in once; every admin clip resumes that same session.
  let adminCreds;
  {
    const clip = await openContext('00-admin-bootstrap');
    adminCreds = await signIn(clip.page, 'admin', 'admin123');
    await clip.page.waitForTimeout(500);
    await clip.context.close();
    const v = clip.page.video();
    fs.unlinkSync(await v.path()); // bootstrap only, not part of the film
  }

  let emp01, emp02;

  // ---------------------------------------------------- 01 normal use
  console.log('clip 01 - normal use (employee01)');
  {
    const clip = await openContext('01-normal-use');
    emp01 = await signIn(clip.page, 'employee01', 'employee123');
    await openFolder(clip.page, 'Projects');
    await openFile(clip.page, 'project_report.pdf', 2600);
    await openFile(clip.page, 'presentation.pptx', 2400);
    await search(clip.page, 'report', 2000);
    await finish(clip);
  }

  console.log('clip 01b - the same session on the dashboard');
  {
    const clip = await openContext('01b-normal-use-admin');
    await resume(clip, adminCreds, '/admin');
    await refreshAdmin(clip.page);
    const id = await sessionIdFor(emp01);
    await viewSession(clip.page, id, 2800);
    await finish(clip);
  }

  // ---------------------------------------------------- 02 meet a decoy
  console.log('clip 02 - meet a decoy (employee01)');
  {
    const clip = await openContext('02-decoy');
    await resume(clip, emp01);
    await openFolder(clip.page, 'Projects');
    await openFile(clip.page, 'design_budget_2026.xlsx', 1200);
    await scrollTo(clip.page, 'pre.viewer', 3600);
    await finish(clip);
  }

  // ---------------------------------------------------- 03 insider hunting
  console.log('clip 03 - insider hunting (employee02)');
  {
    const clip = await openContext('03-insider-hunting');
    emp02 = await signIn(clip.page, 'employee02', 'employee123');
    await search(clip.page, 'salary', 1400);
    await search(clip.page, 'credentials', 1400);
    await search(clip.page, 'api', 1400);
    await openFolder(clip.page, 'HR');
    await openFile(clip.page, 'employee_salary_2026.xlsx', 2400);
    await openFolder(clip.page, 'Finance');
    await openFile(clip.page, 'bank_credentials.txt', 2400);
    await downloadFile(clip.page, 'bank_credentials.txt');
    await openFolder(clip.page, 'IT');
    await openFile(clip.page, 'production_api_keys.txt', 2800);
    await finish(clip);
  }

  // ---------------------------------------------------- 04 dashboard reacts
  console.log('clip 04 - dashboard reacts (admin)');
  const emp02Id = await sessionIdFor(emp02);
  {
    const clip = await openContext('04-dashboard-reacts');
    await resume(clip, adminCreds, '/admin');
    await refreshAdmin(clip.page);
    await read(clip.page, 1600);
    await viewSession(clip.page, emp02Id, 3000);
    await scrollTo(clip.page, '.viz-root', 4200);
    await scrollTo(clip.page, '#session-detail table', 3200);
    await finish(clip);
  }

  // ---------------------------------------------------- 05 active response
  console.log('clip 05 - active response (employee02 sees fiction)');
  {
    const clip = await openContext('05-active-response-intruder');
    await resume(clip, emp02);
    await openFolder(clip.page, 'Projects');
    await openFile(clip.page, 'project_report.pdf', 1200);
    await scrollTo(clip.page, 'pre.viewer', 4000);
    await finish(clip);
  }

  console.log('clip 05b - the same file for an honest user');
  {
    const clip = await openContext('05b-active-response-honest');
    await resume(clip, emp01);
    await openFolder(clip.page, 'Projects');
    await openFile(clip.page, 'project_report.pdf', 1200);
    await scrollTo(clip.page, 'pre.viewer', 4000);
    await finish(clip);
  }

  // ---------------------------------------------------- 06 honeytoken
  console.log('clip 06 - honeytoken used (employee02)');
  {
    const clip = await openContext('06-honeytoken-used');
    await resume(clip, emp02);
    await openFolder(clip.page, 'IT');
    await openFile(clip.page, 'production_api_keys.txt', 1400);
    await scrollTo(clip.page, 'pre.viewer', 2600);

    const body = await clip.page.locator('pre.viewer').innerText();
    const token = (body.match(/hv_live_[0-9a-f]{32}/) || [])[0];
    if (!token) {
      throw new Error(
        'no hv_live_ token found in production_api_keys.txt viewer pane - ' +
          'the decoy was served without planted tokens',
      );
    }
    console.log(`  lifted token ${token.slice(0, 16)}...`);
    await search(clip.page, token, 2600);
    await finish(clip);
  }

  console.log('clip 06b - the dashboard names the field');
  {
    const clip = await openContext('06b-honeytoken-admin');
    await resume(clip, adminCreds, '/admin');
    await refreshAdmin(clip.page);
    await read(clip.page, 2600);
    await viewSession(clip.page, emp02Id, 3000);
    await scrollTo(clip.page, '#session-detail table', 3400);
    await finish(clip);
  }

  // ---------------------------------------------------- 07 second opinion
  console.log('clip 07 - second opinion (anomaly model)');
  {
    const clip = await openContext('07-second-opinion');
    await resume(clip, adminCreds, '/admin');
    await refreshAdmin(clip.page);
    await scrollTo(clip.page, 'th:text-is("Anomaly")', 3400);
    await viewSession(clip.page, emp02Id, 1200);
    await scrollTo(clip.page, '.anomaly-box', 4000);
    await finish(clip);
  }

  // ---------------------------------------------------- 08 nothing hidden
  console.log('clip 08 - nothing hidden (live rules + force-end)');
  {
    const clip = await openContext('08-nothing-hidden');
    await resume(clip, adminCreds, '/admin');
    await showScoringRules(clip.page, adminCreds);
    await clip.page.goto(`${APP}/admin`);
    await clip.page.waitForSelector('header.bar');
    await clip.page.waitForTimeout(900);
    await refreshAdmin(clip.page);
    await viewSession(clip.page, emp02Id, 1400);
    await scrollTo(clip.page, 'button:has-text("End session")', 3000);
    await finish(clip);
  }

  // ---------------------------------------------------- 09 two more rules
  console.log('clip 09 - restricted attempt (employee02 in HR)');
  {
    const clip = await openContext('09-restricted-attempt');
    await resume(clip, emp02);
    await openFolder(clip.page, 'HR');
    await openFile(clip.page, 'leave_policy.pdf', 2600);
    await finish(clip);
  }

  console.log('clip 09b - failed logins carry over (hr01)');
  let hr01;
  {
    const clip = await openContext('09b-failed-logins');
    const page = clip.page;
    for (let attempt = 1; attempt <= 2; attempt += 1) {
      await page.goto(`${APP}/login`);
      await page.waitForSelector('#username');
      await beat(page, 500, 800);
      await page.fill('#username', 'hr01');
      await beat(page);
      await page.fill('#password', 'wrongpassword');
      await beat(page);
      await page.click('button[type="submit"]');
      await page.waitForSelector('p.error', { timeout: 8000 });
      await page.waitForTimeout(1600);
    }
    hr01 = await signIn(page, 'hr01', 'hr123');
    await page.waitForTimeout(1600);
    await finish(clip);
  }

  console.log('clip 09c - that session starts at 20, not 0');
  {
    const clip = await openContext('09c-carryover-admin');
    await resume(clip, adminCreds, '/admin');
    await refreshAdmin(clip.page);
    const id = await sessionIdFor(hr01);
    await viewSession(clip.page, id, 3400);
    await finish(clip);
  }

  await browser.close();

  fs.writeFileSync(
    path.join(OUT, 'manifest.json'),
    JSON.stringify(manifest, null, 2),
  );
  console.log(`\n${manifest.length} clips written to recordings/`);
}

/** Read the backend session id out of a captured credential blob. */
async function sessionIdFor(creds) {
  return JSON.parse(creds.user).session_id;
}

/**
 * Show the live scoring config through FastAPI's own Swagger UI at /docs.
 *
 * The route needs a bearer token, so a plain browser tab cannot render it.
 * /docs is part of the running backend - not a page built for this video - and
 * it is the app's own way of showing an authenticated response.
 */
async function showScoringRules(page, adminCreds) {
  await page.goto(`${API}/docs`);
  await page.waitForSelector('.swagger-ui', { timeout: 20000 });
  await page.waitForTimeout(1200);

  await page.click('button.btn.authorize');
  await page.waitForSelector('.auth-container input[type="text"]', { timeout: 10000 });
  await page.fill('.auth-container input[type="text"]', adminCreds.token);
  await page.waitForTimeout(600);
  await page.click('.auth-btn-wrapper button.authorize');
  await page.waitForTimeout(800);
  await page.click('.auth-btn-wrapper button.btn-done');
  await page.waitForTimeout(900);

  const op = page.locator('#operations-dashboard-scoring_rules_admin_scoring_rules_get');
  await op.scrollIntoViewIfNeeded();
  await op.locator('.opblock-summary').click();
  await page.waitForTimeout(900);
  await op.locator('button:has-text("Try it out")').click();
  await page.waitForTimeout(700);
  await op.locator('button.execute').click();
  await page.waitForSelector('.responses-table .microlight', { timeout: 15000 });
  // Centre the JSON response, which pushes Swagger's generated curl - and the
  // admin bearer token inside it - above the top of the frame. A working
  // credential has no business being legible in a shareable video.
  await page.evaluate(() => {
    const el = document.querySelector(
      '.responses-table .response-col_description .microlight',
    );
    if (el) el.scrollIntoView({ block: 'center' });
  });
  await page.waitForTimeout(4200);
}

main().catch(async (err) => {
  console.error('\nRECORDING FAILED\n');
  console.error(err);
  if (browser) await browser.close().catch(() => {});
  process.exit(1);
});
