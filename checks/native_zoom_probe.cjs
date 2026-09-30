#!/usr/bin/env node
"use strict";

// Verify real Chromium tab zoom using a temporary extension and persistent profile.
// Usage: node checks/native_zoom_probe.cjs <app-url> [outer-width] [outer-height]
// Optional env: PLAYWRIGHT_MODULE (module name/path), CHROMIUM_EXECUTABLE (browser path).
const fs = require("node:fs/promises");
const path = require("node:path");
const crypto = require("node:crypto");
const scenarioPath = process.env.NATIVE_ZOOM_SCENARIO;

const appUrl = process.argv[2];
const width = Number(process.argv[3] || 1280);
const height = Number(process.argv[4] || 720);

function output(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

async function main() {
  if (!appUrl || ![width, height].every(value => Number.isInteger(value) && value > 0)) {
    throw new Error("usage: node checks/native_zoom_probe.cjs <app-url> [outer-width] [outer-height]");
  }
  const target = new URL(appUrl);
  if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) {
    throw new Error("app-url must be an HTTP(S) URL without embedded credentials");
  }
  const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
  const tempRoot = path.join(__dirname, `.native-zoom-${process.pid}-${crypto.randomUUID()}`);
  const extensionDir = path.join(tempRoot, "extension");
  const profileDir = path.join(tempRoot, "profile");
  let context;
  const result = {
    method: "Playwright persistent Chromium context + temporary MV3 extension",
    requestedZoom: 2,
    target: `${target.origin}${target.pathname}`,
    outerViewport: [width, height],
  };

  try {
    await fs.mkdir(extensionDir, { recursive: true });
    await fs.mkdir(profileDir, { recursive: true });
    await fs.writeFile(path.join(extensionDir, "manifest.json"), JSON.stringify({
      manifest_version: 3,
      name: "QA Native Zoom Probe",
      version: "1.0",
      permissions: ["tabs"],
      host_permissions: [`${target.origin}/*`],
      background: { service_worker: "background.js" },
    }));
    await fs.writeFile(path.join(extensionDir, "background.js"), "chrome.runtime.onInstalled.addListener(() => {});\n");

    const launch = {
      headless: true,
      viewport: { width, height },
      args: [`--disable-extensions-except=${extensionDir}`, `--load-extension=${extensionDir}`],
      timeout: 15000,
    };
    if (process.env.CHROMIUM_EXECUTABLE) launch.executablePath = process.env.CHROMIUM_EXECUTABLE;
    context = await chromium.launchPersistentContext(profileDir, launch);
    result.browserVersion = context.browser()?.version() || "unavailable";
    const page = context.pages()[0] || await context.newPage();
    await page.goto(appUrl, { waitUntil: "domcontentloaded", timeout: 15000 });
    let worker = context.serviceWorkers().find(item => item.url().startsWith("chrome-extension://"));
    if (!worker) worker = await context.waitForEvent("serviceworker", { timeout: 10000 });

    const zoom = await worker.evaluate(async targetOrigin => {
      const queryTabs = () => new Promise((resolve, reject) => chrome.tabs.query(
        { active: true, lastFocusedWindow: true }, tabs => {
          const error = chrome.runtime.lastError;
          if (error) reject(new Error(error.message)); else resolve(tabs);
        }));
      const callTab = (method, tabId, value) => new Promise((resolve, reject) => {
        const done = result => {
          const error = chrome.runtime.lastError;
          if (error) reject(new Error(error.message)); else resolve(result);
        };
        if (method === "setZoom") chrome.tabs.setZoom(tabId, value, done);
        else chrome.tabs.getZoom(tabId, done);
      });
      const tabs = await queryTabs();
      const tab = tabs.find(item => item.url && item.url.startsWith(targetOrigin));
      if (!tab) throw new Error("active app tab not found");
      await callTab("setZoom", tab.id, 2);
      return await callTab("getZoom", tab.id);
    }, target.origin);
    result.getZoom = zoom;
    result.metrics = await page.evaluate(() => ({
      cssViewport: [window.innerWidth, window.innerHeight],
      windowOuter: [window.outerWidth, window.outerHeight],
      devicePixelRatio: window.devicePixelRatio,
      documentClient: [document.documentElement.clientWidth, document.documentElement.clientHeight],
      documentScroll: [document.documentElement.scrollWidth, document.documentElement.scrollHeight],
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    }));
    const getZoom = () => worker.evaluate(async targetOrigin => {
      const tabs = await new Promise((resolve, reject) => chrome.tabs.query(
        { active: true, lastFocusedWindow: true }, rows => {
          const error = chrome.runtime.lastError;
          if (error) reject(new Error(error.message)); else resolve(rows);
        }));
      const tab = tabs.find(item => item.url && item.url.startsWith(targetOrigin));
      if (!tab) throw new Error("active app tab not found");
      return await new Promise((resolve, reject) => chrome.tabs.getZoom(tab.id, value => {
        const error = chrome.runtime.lastError;
        if (error) reject(new Error(error.message)); else resolve(value);
      }));
    }, target.origin);
    const setZoom = value => worker.evaluate(async ({ targetOrigin, zoomValue }) => {
      const tabs = await new Promise((resolve, reject) => chrome.tabs.query(
        { active: true, lastFocusedWindow: true }, rows => {
          const error = chrome.runtime.lastError;
          if (error) reject(new Error(error.message)); else resolve(rows);
        }));
      const tab = tabs.find(item => item.url && item.url.startsWith(targetOrigin));
      if (!tab) throw new Error("active app tab not found");
      return await new Promise((resolve, reject) => chrome.tabs.setZoom(tab.id, zoomValue, () => {
        const error = chrome.runtime.lastError;
        if (error) reject(new Error(error.message));
        else chrome.tabs.getZoom(tab.id, actual => {
          const zoomError = chrome.runtime.lastError;
          if (zoomError) reject(new Error(zoomError.message)); else resolve(actual);
        });
      }));
    }, { targetOrigin: target.origin, zoomValue: value });
    if (scenarioPath) {
      const scenario = require(path.resolve(scenarioPath));
      if (typeof scenario !== "function") throw new Error("native-zoom scenario must export a function");
      result.scenario = await scenario(page, { getZoom, setZoom });
      result.postScenarioZoom = await getZoom();
    }
    result.ok = result.getZoom === 2 && !result.metrics.horizontalOverflow &&
      (!scenarioPath || result.postScenarioZoom === 2 && result.scenario?.ok !== false);
    output(result);
    if (!result.ok) process.exitCode = 1;
  } finally {
    if (context) await context.close().catch(() => {});
    await fs.rm(tempRoot, { recursive: true, force: true }).catch(() => {});
  }
}

main().catch(error => {
  output({ ok: false, error: { name: error.name, message: error.message } });
  process.exitCode = 1;
});
