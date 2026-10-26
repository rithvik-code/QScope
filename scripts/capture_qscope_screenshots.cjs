const { chromium } = require("C:/Users/Rithvik/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright");

async function main() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1050 }, deviceScaleFactor: 1.25 });
  const output = "C:/Users/Rithvik/OneDrive/Documents/QScope/docs/research_figures";
  await page.addInitScript(() => {
    localStorage.setItem("qscope-first-run-hidden", "true");
    localStorage.setItem("qscope.guide.dismissed.v1", "Build,Execute");
  });
  await page.goto("http://127.0.0.1:8000/", { waitUntil: "networkidle", timeout: 30000 });
  console.log("loaded home");
  await page.screenshot({ path: `${output}/qscope-screenshot-01-home.png` });

  await page.getByRole("button", { name: "Build", exact: true }).click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${output}/qscope-screenshot-02-build.png` });
  console.log("captured build");

  await page.getByRole("button", { name: "Execute", exact: true }).click();
  await page.waitForTimeout(600);
  const discard = page.getByRole("button", { name: "discard", exact: true });
  if (await discard.count()) await discard.click();
  await page.getByRole("button", { name: "execute", exact: true }).click();
  await page.getByText("SIMULATED", { exact: false }).first().waitFor({ state: "visible", timeout: 30000 });
  await page.screenshot({ path: `${output}/qscope-screenshot-03-execute.png` });
  console.log("captured execute");

  await page.getByRole("button", { name: "History", exact: true }).click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${output}/qscope-screenshot-04-history.png` });

  await page.getByRole("button", { name: /more tools/i }).click();
  await page.getByRole("button", { name: "Benchmark", exact: true }).click();
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: "run benchmark", exact: true }).click();
  await page.getByText("Nothing measured yet", { exact: true }).waitFor({ state: "hidden", timeout: 60000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${output}/qscope-screenshot-05-benchmark.png` });
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
