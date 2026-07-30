const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  renderSensorDeviceRows,
  sensorDeviceStatusLabel,
} = require("../app/static/dashboard.js");

const root = path.resolve(__dirname, "..");

test("renders a scalable four-column sensor inventory row", () => {
  const device = {
    name: "virtual-temperature-001",
    overall_status: "available",
    latest_event_timestamp: "2099-01-01T00:00:00Z",
  };

  const markup = renderSensorDeviceRows([device]);

  assert.match(markup, /<tr class="sensor-device-row/);
  assert.match(markup, />virtual-temperature-001</);
  assert.match(markup, /Available/);
  assert.match(markup, /data-label="최신 이벤트"/);
  assert.match(markup, />상세보기</);
  assert.doesNotMatch(markup, /프로토콜|수집 서비스|배치 노드/);
});

test("maps all sensor availability states to operator labels", () => {
  assert.equal(sensorDeviceStatusLabel({overall_status: "available"}), "Available");
  assert.equal(sensorDeviceStatusLabel({overall_status: "degraded"}), "Degraded");
  assert.equal(sensorDeviceStatusLabel({overall_status: "unavailable"}), "Unavailable");
  assert.equal(sensorDeviceStatusLabel({overall_status: "unexpected"}), "Degraded");
});

test("dashboard exposes sensor language and table-first inventory structure", () => {
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const css = fs.readFileSync(
    path.join(root, "app/static/operations-dashboard.css"),
    "utf8",
  );

  assert.match(html, />센서 디바이스</);
  assert.match(html, /class="sensor-device-table"/);
  assert.match(html, /<th scope="col">이름<\/th>/);
  assert.match(html, /<th scope="col">상태<\/th>/);
  assert.match(html, /<th scope="col">최신 이벤트<\/th>/);
  assert.doesNotMatch(html, /EdgeX 디바이스/);
  assert.match(css, /#deviceList\s*\{\s*display: table-row-group !important;/);
  assert.match(css, /@media \(max-width: 680px\)/);
});
