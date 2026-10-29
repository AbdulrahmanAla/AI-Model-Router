const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function appHarness() {
  const pending = [];
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  const context = vm.createContext({
    AbortController,
    document: { querySelector: () => ({}) },
    window: { setTimeout: () => 1, clearTimeout() {} },
    fetch: () => new Promise((resolve, reject) => pending.push({ resolve, reject })),
  });
  vm.runInContext(source.replace(/  wireEvents\(\);[\s\S]*$/, `
    renderMessages = () => {};
    setServiceStatus = (kind, label) => { state.serviceLabel = label; };
    this.app = { state, elements, solve, cancelSolve, retrySolve, requestAi, cancelAi };
  })();`), context);
  return { ...context.app, pending };
}

const request = { operation: 'derivative', expression: 'x^2' };
const result = { status: 'solved', result: '2*x' };
const response = (body) => ({ ok: true, json: async () => body });

test('cancelled solve cannot unlock or overwrite an immediate retry', async () => {
  const app = appHarness();
  const message = { request, generation: 0, loading: true };
  const old = app.solve(request, message);
  app.cancelSolve(message);
  app.retrySolve(message);
  app.pending[0].resolve(response({ status: 'solved', result: 'stale' }));
  await old;
  assert.equal(app.elements.send.disabled, true);
  assert.equal(message.loading, true);
  assert.equal(message.response, undefined);
  app.pending[1].resolve(response(result));
  await new Promise(setImmediate);
  assert.equal(message.response.result, '2*x');
  assert.equal(app.elements.send.disabled, false);
});

test('a previous session cannot change the service status', async () => {
  const app = appHarness();
  const message = { request, generation: 0, loading: true };
  const old = app.solve(request, message);
  app.state.solveGeneration++;
  app.state.serviceLabel = 'New session';
  app.pending[0].reject(new Error('Old failure'));
  await old;
  assert.equal(app.state.serviceLabel, 'New session');
});

test('late cancellation failure cannot unlock a different question', async () => {
  const app = appHarness();
  const first = { request, generation: 0, loading: true };
  const old = app.solve(request, first);
  app.cancelSolve(first);
  const second = { request, generation: 0, loading: true };
  app.state.solving = true;
  app.elements.send.disabled = true;
  const next = app.solve(request, second);
  app.pending[0].reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
  await old;
  assert.equal(app.elements.send.disabled, true);
  assert.equal(app.state.solving, true);
  app.pending[1].resolve(response(result));
  await next;
  assert.equal(second.response.result, '2*x');
});

test('cancelled AI response cannot replace a new explanation', async () => {
  const app = appHarness();
  const message = { request, response: result };
  const old = app.requestAi(message, 'explain');
  app.cancelAi(message);
  const next = app.requestAi(message, 'explain');
  app.pending[0].resolve(response({ status: 'answered', text: 'stale' }));
  await old;
  assert.equal(message.aiLoading, true);
  assert.equal(message.ai.status, 'loading');
  app.pending[1].resolve(response({ status: 'answered', text: 'current' }));
  await next;
  assert.equal(message.ai.text, 'current');
  assert.equal(message.aiLoading, false);
});
