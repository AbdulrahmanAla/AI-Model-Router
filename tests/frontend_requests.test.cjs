const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function appHarness() {
  const pending = [];
  const timers = new Map();
  let nextTimer = 0;
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  const context = vm.createContext({
    AbortController,
    document: {
      querySelector: () => ({}),
      createElement: () => ({ addEventListener(event, callback) { this[event] = callback; } }),
    },
    window: {
      setTimeout: (callback) => { timers.set(++nextTimer, callback); return nextTimer; },
      clearTimeout: (id) => timers.delete(id),
    },
    fetch: (url, options) => new Promise((resolve, reject) => pending.push({ resolve, reject, signal: options.signal })),
  });
  vm.runInContext(source.replace(/  wireEvents\(\);[\s\S]*$/, `
    renderMessages = () => {};
    copyText = (value) => { state.copiedEvidence = value; };
    setServiceStatus = (kind, label) => { state.serviceLabel = label; };
    this.app = { state, elements, solve, cancelSolve, retrySolve, requestAi, cancelAi, copySessionEvidence, addCopyActions, exampleValues };
  })();`), context);
  return { ...context.app, pending, timers };
}

const request = { operation: 'derivative', expression: 'x^2' };
const result = { status: 'solved', result: '2*x', verification: { status: 'symbolic_check', detail: 'Checked.' } };
const response = (body) => ({ ok: true, json: async () => body });

test('examples carry their own limit direction', () => {
  const app = appHarness();
  assert.equal(JSON.stringify(app.exampleValues({ dataset: { operation: 'limit', expression: 'sqrt(x)', target: '0', direction: '+' } })), JSON.stringify({
    operation: 'limit', expression: 'sqrt(x)', lower: '', upper: '', target: '0', direction: '+'
  }));
  assert.equal(app.exampleValues({ dataset: { operation: 'limit', expression: 'sin(x)/x', target: '0' } }).direction, 'both');
});

for (const [question, expected] of [
  [{ operation: 'integral', expression: 'x', lower: '0', upper: '1' }, 'Integral x from 0 to 1'],
  [{ operation: 'limit', expression: '1/x', target: '0', direction: '+' }, 'Limit of 1/x as x approaches 0 from the right'],
]) {
  test(`full-solution copy preserves context: ${expected}`, () => {
    const app = appHarness();
    const buttons = [];
    app.addCopyActions({ ...result, expression: question.expression, steps: ['Compute the result.'],
      notes: ['Numerical samples are not a proof.'] }, { append: (button) => buttons.push(button) }, question);
    buttons.find((button) => button.textContent === 'Copy full solution').click();
    assert.ok(app.state.copiedEvidence.includes(`Question: ${expected}`));
    assert.match(app.state.copiedEvidence, /Verification \(Symbolic check\): Checked\./);
    assert.match(app.state.copiedEvidence, /Numerical samples are not a proof/);
  });
}

for (const body of [null, {}, [], { status: 'solved', result: { value: '2*x' } }, { status: 'solved', result: '2*x' }, { ...result, status: 'unresolved' }]) {
  test(`invalid solver response is retryable: ${JSON.stringify(body)}`, async () => {
    const app = appHarness();
    const message = { request, generation: 0, loading: true };
    const running = app.solve(request, message);
    app.pending[0].resolve(response(body));
    await running;
    assert.equal(message.response, undefined);
    assert.match(message.error, /invalid response/i);
    assert.equal(message.loading, false);
    assert.equal(app.elements.send.disabled, false);
  });
}

test('invalid AI success cannot masquerade as an explanation', async () => {
  const app = appHarness();
  const message = { request, response: result };
  const running = app.requestAi(message, 'explain');
  app.pending[0].resolve(response({}));
  await running;
  assert.equal(message.ai.status, 'error');
  assert.match(message.ai.message, /invalid response/i);
  assert.equal(message.response.result, '2*x');
});

test('valid unresolved response remains available for explicit fallback', async () => {
  const app = appHarness();
  const message = { request, generation: 0, loading: true };
  const running = app.solve(request, message);
  app.pending[0].resolve(response({ status: 'unresolved', result: null,
    verification: { status: 'not_checked', detail: 'The exact solver reached its time limit.' } }));
  await running;
  assert.equal(message.response.status, 'unresolved');
  assert.equal(message.error, undefined);
  assert.equal(message.loading, false);
});

test('retry recovers from an invalid response with the same question', async () => {
  const app = appHarness();
  const message = { request, generation: 0, loading: true };
  const running = app.solve(request, message);
  app.pending[0].resolve(response({}));
  await running;
  app.retrySolve(message);
  app.pending[1].resolve(response(result));
  await new Promise(setImmediate);
  assert.equal(message.response.result, '2*x');
  assert.equal(message.error, null);
  assert.equal(message.request, request);
});

test('session export includes all explanation calls and reported tokens', () => {
  const app = appHarness();
  app.state.messages.push({ display: 'Derivative x^2', response: { ...result, metrics: { ai_calls: 0 } }, aiAttempts: [
    { status: 'answered', action: 'explain', metrics: { ai_calls: 1, total_tokens: 40 } },
    { status: 'answered', action: 'explain', metrics: { ai_calls: 1, total_tokens: 60 } },
  ] });
  app.copySessionEvidence();
  assert.match(app.state.copiedEvidence, /General-model calls: 2/);
  assert.match(app.state.copiedEvidence, /Reported tokens: 100/);
  assert.match(app.state.copiedEvidence, /AI attempts: 2/);
});

test('session export never treats interrupted AI usage as zero', () => {
  const app = appHarness();
  app.state.messages.push({ display: 'Derivative x^2', response: { ...result, metrics: { ai_calls: 0 } }, aiAttempts: [
    { status: 'error', action: 'explain' },
  ] });
  app.copySessionEvidence();
  assert.match(app.state.copiedEvidence, /General-model calls: not reported/);
  assert.match(app.state.copiedEvidence, /Reported tokens: not reported/);
});

test('session export reports zero model calls for a solver-only answer', () => {
  const app = appHarness();
  app.state.messages.push({ display: 'Derivative x^2', response: { ...result, metrics: { ai_calls: 0 } } });
  app.copySessionEvidence();
  assert.match(app.state.copiedEvidence, /General-model calls: 0/);
  assert.match(app.state.copiedEvidence, /AI attempts: 0/);
});

test('unknown usage in one AI attempt prevents a misleading partial total', () => {
  const app = appHarness();
  app.state.messages.push({ display: 'Derivative x^2', response: { ...result, metrics: { ai_calls: 0 } }, aiAttempts: [
    { status: 'answered', metrics: { ai_calls: 1, total_tokens: 40 } },
    { status: 'error' },
  ] });
  app.copySessionEvidence();
  assert.match(app.state.copiedEvidence, /General-model calls: not reported/);
  assert.match(app.state.copiedEvidence, /Reported tokens: not reported/);
  assert.match(app.state.copiedEvidence, /AI attempts: 2/);
});

test('solver deadline covers a stalled response body after headers arrive', async () => {
  const app = appHarness();
  const message = { request, generation: 0, loading: true };
  const running = app.solve(request, message);
  app.pending[0].resolve({ ok: true, json: () => new Promise((resolve, reject) => {
    app.pending[0].signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
  }) });
  await new Promise(setImmediate);
  assert.equal(app.timers.size, 1, 'deadline must remain active until JSON is read');
  [...app.timers.values()][0]();
  await running;
  assert.equal(message.response, undefined);
  assert.match(message.error, /took too long/);
  assert.equal(message.loading, false);
  assert.equal(app.elements.send.disabled, false);
});

test('malformed successful JSON is a recoverable error rather than an empty result', async () => {
  const app = appHarness();
  const message = { request, generation: 0, loading: true };
  const running = app.solve(request, message);
  app.pending[0].resolve({ ok: true, json: async () => { throw new SyntaxError('invalid JSON'); } });
  await running;
  assert.equal(message.response, undefined);
  assert.match(message.error, /invalid response/i);
  assert.equal(app.elements.send.disabled, false);
});

test('AI body timeout preserves the exact result and leaves usage unknown', async () => {
  const app = appHarness();
  const message = { request, response: result };
  const running = app.requestAi(message, 'explain');
  app.pending[0].resolve({ ok: true, json: () => new Promise((resolve, reject) => {
    app.pending[0].signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
  }) });
  await new Promise(setImmediate);
  assert.equal(app.timers.size, 1);
  [...app.timers.values()][0]();
  await running;
  assert.equal(message.response.result, '2*x');
  assert.equal(message.aiLoading, false);
  assert.equal(message.ai.metrics, undefined);
  assert.match(message.ai.message, /took too long/);
});

test('provider failure retains reported call accounting', async () => {
  const app = appHarness();
  const message = { request, response: result };
  const running = app.requestAi(message, 'explain');
  app.pending[0].resolve({ ok: false, status: 502, json: async () => ({
    detail: 'Provider unavailable.', metrics: { ai_calls: 1, total_tokens: null },
  }) });
  await running;
  assert.equal(message.ai.metrics.ai_calls, 1);
  assert.equal(message.ai.metrics.total_tokens, null);
  assert.equal(message.response.result, '2*x');
});

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
