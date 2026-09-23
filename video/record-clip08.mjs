/**
 * Re-record clip 08 only.
 *
 * Everything it does is read-only (Swagger GET, opening a session card), so it
 * cannot disturb the state the other clips already captured. Split out so a
 * framing fix does not cost a full re-record of the whole film.
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

const login = async (username, password) => {
  const r = await fetch(`${API}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  if (!r.ok) throw new Error(`login failed for ${username}: ${r.status}`);
  return r.json();
};

const browser = await chromium.launch();
const admin = await login('admin', 'admin123');

// Find the CRITICAL session to open on the detail card.
const sessions = await fetch(`${API}/admin/sessions`, {
  headers: { Authorization: `Bearer ${admin.token}` },
}).then((r) => r.json());
const target = sessions.find((s) => s.risk_level === 'CRITICAL' && s.is_active);
if (!target) throw new Error('no active CRITICAL session to show');
console.log(`showing session ${target.id} (${target.username})`);

const context = await browser.newContext({
  viewport: VIEWPORT,
  recordVideo: { dir: OUT, size: VIEWPORT },
});
await context.addInitScript(
  ([t, u]) => {
    sessionStorage.setItem('hv_token', t);
    sessionStorage.setItem('hv_user', u);
  },
  [
    admin.token,
    JSON.stringify({
      username: admin.username,
      role: admin.role,
      session_id: admin.session_id,
    }),
  ],
);
const page = await context.newPage();

// --- live scoring rules, through FastAPI's own Swagger UI -------------------
await page.goto(`${API}/docs`);
await page.waitForSelector('.swagger-ui', { timeout: 20000 });
await page.waitForTimeout(1200);

await page.click('button.btn.authorize');
await page.waitForSelector('.auth-container input[type="text"]', { timeout: 10000 });
await page.fill('.auth-container input[type="text"]', admin.token);
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

// Park the JSON response against the top of the frame. Swagger echoes the
// request as a curl command that includes the admin bearer token, and that
// block sits directly above the response - scrolling the response to the top
// is what pushes a working credential out of shot.
await page.evaluate(() => {
  const el = document.querySelector(
    '.responses-table .response-col_description .microlight',
  );
  if (!el) return;
  const y = el.getBoundingClientRect().top + window.scrollY - 40;
  window.scrollTo({ top: y });
});
await page.waitForTimeout(900);

const tokenVisible = await page.evaluate((token) => {
  const head = token.slice(0, 24);
  return [...document.querySelectorAll('.microlight')].some((el) => {
    if (!el.textContent.includes(head)) return false;
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.top < window.innerHeight;
  });
}, admin.token);
if (tokenVisible) {
  await context.close();
  await browser.close();
  throw new Error('admin token is still inside the frame - refusing to record');
}
console.log('token is out of frame');
await page.waitForTimeout(4200);

// --- back to the dashboard: force-end control ------------------------------
await page.goto(`${APP}/admin`);
await page.waitForSelector('header.bar', { timeout: 15000 });
await page.waitForTimeout(1000);
await page.click('button:has-text("Refresh now")');
await page.waitForTimeout(900);

const row = page
  .locator('tr', { has: page.getByRole('button', { name: 'View' }) })
  .filter({ has: page.locator(`td:nth-child(1):text-is("${target.id}")`) })
  .first();
await row.scrollIntoViewIfNeeded();
await row.getByRole('button', { name: 'View' }).click();
await page.waitForSelector('#session-detail', { timeout: 10000 });
await page.waitForTimeout(1400);
await page.locator('button:has-text("End session")').first().scrollIntoViewIfNeeded();
await page.waitForTimeout(3000);

const video = page.video();
await context.close();
const tmp = await video.path();
const dest = path.join(OUT, '08-nothing-hidden.webm');
if (fs.existsSync(dest)) fs.unlinkSync(dest);
fs.renameSync(tmp, dest);
console.log(`saved 08-nothing-hidden.webm (${Math.round(fs.statSync(dest).size / 1024)} KB)`);

await browser.close();
