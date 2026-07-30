const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

test("workflow actions expose explicit loading, success, warning, and error feedback", () => {
  const root = path.resolve(__dirname, "..");
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const actions = fs.readFileSync(path.join(root, "app/static/workflow-actions.js"), "utf8");
  const events = fs.readFileSync(path.join(root, "app/static/workflow.js"), "utf8");
  const css = fs.readFileSync(path.join(root, "app/static/workflow.css"), "utf8");

  assert.match(html, /id="workflowStatus"[^>]+role="status"[^>]+aria-live="polite"/);
  assert.match(actions, /function setWorkflowStatus\(/);
  assert.match(actions, /function setWorkflowButtonBusy\(/);
  assert.match(actions, /브라우저 안에서만 유지됩니다/);
  assert.match(actions, /삭제할 단계를 먼저 선택하세요/);
  assert.match(actions, /바인딩할 워크플로우 단계를 먼저 선택하세요/);
  assert.match(actions, /EdgeX 디바이스 \$\{devices\.length\}개를 불러왔습니다/);
  assert.match(actions, /\/state\/device-source-bindings\/sample/);
  assert.match(actions, /method: "POST"/);
  assert.match(actions, /deviceName: target\.name/);
  assert.match(actions, /resourceName/);
  assert.match(actions, /readMode/);
  assert.match(html, /id="readLatestWorkflowDevice"[^>]*>샘플 조회</);
  assert.match(html, /로컬 최근값\/중앙 이력/);
  assert.match(events, /setWorkflowStatus\(/);
  assert.match(css, /#workflowStatus\[data-status="success"\]/);
  assert.match(css, /#workflowStatus\[data-status="error"\]/);
});
