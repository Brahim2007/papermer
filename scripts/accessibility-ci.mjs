import AxeBuilder from "@axe-core/playwright";
import { chromium } from "playwright";

const baseURL = process.env.AXE_BASE_URL || "http://127.0.0.1:8000";
const email = process.env.AXE_TEST_EMAIL || "axe-ci@papermetrix.invalid";
const password = process.env.AXE_TEST_PASSWORD;

if (!password) throw new Error("AXE_TEST_PASSWORD is required");

const browser = await chromium.launch({
  headless: true,
  ...(process.env.AXE_BROWSER_EXECUTABLE
    ? { executablePath: process.env.AXE_BROWSER_EXECUTABLE }
    : {}),
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const failures = [];

async function scan(path, label) {
  await page.goto(`${baseURL}${path}`, { waitUntil: "networkidle" });
  const results = await new AxeBuilder({ page }).analyze();
  if (results.violations.length) {
    failures.push({ label, path, violations: results.violations });
  }
  console.log(`${label}: ${results.violations.length} axe violation(s)`);
}

try {
  await scan("/", "Home");
  await scan(
    "/search/?query=hybrid+retrieval&year_from=2020&open_access=1",
    "Filtered search",
  );
  await scan("/about/", "About");
  await scan("/faq/", "Questions and answers");
  await scan(
    "/ar/search/?query=hybrid+retrieval&year_from=2020&open_access=1",
    "Arabic RTL filtered search",
  );
  await scan("/article/axe-ci-paper/", "Paper detail");

  await page.goto(`${baseURL}/auth/login/`, { waitUntil: "networkidle" });
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await Promise.all([
    page.waitForURL(`${baseURL}/`),
    page.getByRole("button", { name: "Log in securely" }).click(),
  ]);

  await scan("/library/", "Authenticated libraries");
  const libraryHref = await page.locator(".library-card__link").first().getAttribute("href");
  if (!libraryHref) throw new Error("Seeded library link was not found");
  await scan(libraryHref, "Authenticated library detail");
  await scan("/topics/", "Authenticated topics");
  await scan("/recommendations/", "Authenticated recommendations");
  await scan("/evaluation/", "Staff retrieval evaluation");
} finally {
  await browser.close();
}

if (failures.length) {
  for (const failure of failures) {
    console.error(`\n${failure.label} (${failure.path})`);
    for (const violation of failure.violations) {
      console.error(`- ${violation.id}: ${violation.help}`);
      for (const node of violation.nodes) console.error(`  ${node.target.join(" ")}`);
    }
  }
  process.exit(1);
}
