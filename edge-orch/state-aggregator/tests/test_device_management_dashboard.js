const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  adapterCanApply,
  createManagementDevice,
  fetchManagementAdapters,
  fetchManagementOperation,
  operationStatusView,
  patchManagementDevice,
  pollManagementOperation,
  validateManagementDevice,
} = require("../app/static/device-management.js");


function response(payload, {ok = true, status = 200} = {}) {
  return {
    ok,
    status,
    json: async () => payload,
  };
}


test("only installed runtime adapters can be applied", () => {
  assert.equal(adapterCanApply({status: "installed", mutationEnabled: true}), true);
  assert.equal(adapterCanApply({status: "installed", mutationEnabled: false}), false);
  assert.equal(adapterCanApply({status: "unavailable", mutationEnabled: true}), false);
  assert.equal(adapterCanApply({status: "unsupported", mutationEnabled: true}), false);
  assert.equal(adapterCanApply(null), false);
});


test("loads adapter catalog without browser cache", async () => {
  let request = null;
  const fetchFn = async (url, options) => {
    request = {url, options};
    return response([{adapterId: "serial-jetson", status: "installed"}]);
  };

  const adapters = await fetchManagementAdapters(fetchFn);

  assert.deepEqual(request, {
    url: "/management/adapters",
    options: {cache: "no-store"},
  });
  assert.equal(adapters[0].adapterId, "serial-jetson");
});


test("dry-run posts no authentication or mutation headers", async () => {
  let request = null;
  const payload = {adapterId: "serial-jetson", device: {name: "device-01"}};
  const fetchFn = async (url, options) => {
    request = {url, options};
    return response({valid: true, issues: [], plan: {mutations: ["create_device"]}});
  };

  const result = await validateManagementDevice(payload, fetchFn);

  assert.equal(result.valid, true);
  assert.equal(request.url, "/management/devices/validate");
  assert.equal(request.options.method, "POST");
  assert.deepEqual(request.options.headers, {"Content-Type": "application/json"});
  assert.deepEqual(JSON.parse(request.options.body), payload);
  assert.equal("Authorization" in request.options.headers, false);
  assert.equal("Idempotency-Key" in request.options.headers, false);
});


test("create sends bearer and idempotency headers but never puts token in body", async () => {
  let request = null;
  const payload = {adapterId: "serial-jetson", device: {name: "device-01"}};
  const fetchFn = async (url, options) => {
    request = {url, options};
    return response({requestId: "request-01", status: "waiting_for_event"}, {status: 201});
  };

  const result = await createManagementDevice(payload, {
    token: "admin-secret",
    idempotencyKey: "retry-key",
    fetchFn,
  });

  assert.equal(result.requestId, "request-01");
  assert.equal(request.url, "/management/devices");
  assert.equal(request.options.headers.Authorization, "Bearer admin-secret");
  assert.equal(request.options.headers["Idempotency-Key"], "retry-key");
  assert.doesNotMatch(request.options.body, /admin-secret|retry-key/);
});


test("patch URL-encodes device identity and uses the same guarded headers", async () => {
  let request = null;
  const fetchFn = async (url, options) => {
    request = {url, options};
    return response({requestId: "patch-01", action: "patch", status: "verified"});
  };

  await patchManagementDevice(
    "device / 01",
    {description: "updated"},
    {token: "admin-secret", idempotencyKey: "patch-key", fetchFn},
  );

  assert.equal(request.url, "/management/devices/device%20%2F%2001");
  assert.equal(request.options.method, "PATCH");
  assert.equal(request.options.headers.Authorization, "Bearer admin-secret");
  assert.equal(request.options.headers["Idempotency-Key"], "patch-key");
});


test("management errors preserve safe server detail", async () => {
  const fetchFn = async () => response(
    {detail: {requestId: "request-01", status: "failed", message: "apply failed"}},
    {ok: false, status: 502},
  );

  await assert.rejects(
    createManagementDevice({}, {
      token: "admin-secret",
      idempotencyKey: "retry-key",
      fetchFn,
    }),
    /apply failed/,
  );
});


test("operation status distinguishes metadata wait, verified, and failure", () => {
  assert.deepEqual(operationStatusView({status: "waiting_for_event"}), {
    label: "WAITING FOR EVENT",
    tone: "waiting",
    detail: "EdgeX Metadata 적용 완료 · 첫 Core Data Event 대기",
    terminal: false,
  });
  assert.equal(operationStatusView({status: "verified"}).terminal, true);
  assert.match(operationStatusView({status: "verified"}).detail, /Event 검증 완료/);
  assert.equal(operationStatusView({status: "failed"}).terminal, true);
  assert.match(operationStatusView({status: "failed", error: "readback mismatch"}).detail, /readback mismatch/);
  assert.match(
    operationStatusView({status: "waiting_for_event", error: "Core Data unavailable"}).detail,
    /Core Data unavailable/,
  );
});


test("polling stops when first Event verification becomes terminal", async () => {
  const payloads = [
    {requestId: "request-01", status: "waiting_for_event"},
    {requestId: "request-01", status: "verified"},
  ];
  const urls = [];
  let sleeps = 0;
  const fetchFn = async (url) => {
    urls.push(url);
    return response(payloads.shift());
  };

  const result = await pollManagementOperation("request-01", {
    fetchFn,
    sleepFn: async () => { sleeps += 1; },
    maxAttempts: 3,
  });

  assert.equal(result.status, "verified");
  assert.equal(sleeps, 1);
  assert.deepEqual(urls, [
    "/management/operations/request-01",
    "/management/operations/request-01",
  ]);
});


test("fetches one operation without cache", async () => {
  let options = null;
  const fetchFn = async (_url, requestOptions) => {
    options = requestOptions;
    return response({requestId: "request-01", status: "verified"});
  };

  await fetchManagementOperation("request-01", fetchFn);

  assert.deepEqual(options, {cache: "no-store"});
});


test("dashboard ships an accessible session-only device management page", () => {
  const root = path.resolve(__dirname, "..");
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const css = fs.readFileSync(path.join(root, "app/static/device-management.css"), "utf8");
  const javascript = fs.readFileSync(path.join(root, "app/static/device-management.js"), "utf8");

  assert.match(html, /data-dashboard-page="management"/);
  assert.match(html, /data-page="management"/);
  for (const id of [
    "managementAdapterList",
    "deviceOnboardingForm",
    "managementAdapter",
    "managementProtocolFields",
    "managementValidation",
    "managementOperation",
    "managementMutationMode",
    "managementAdminToken",
    "managedDeviceList",
    "devicePatchForm",
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /id="managementAdminToken"[^>]+type="password"[^>]+autocomplete="off"/);
  assert.match(html, /id="managementPatchApply"[^>]+disabled/);
  assert.match(html, /device-management\.css\?v=onboarding-20260723/);
  assert.match(html, /device-management\.js\?v=onboarding-20260723/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /body\[data-dashboard-page="management"\] \.side-rail/);
  assert.doesNotMatch(javascript, /localStorage|sessionStorage/);
  assert.doesNotMatch(javascript, /\.innerHTML\s*=/);
  assert.match(javascript, /function renderManagementValidation\(/);
  assert.doesNotMatch(javascript, /function renderValidation\(/);
});
