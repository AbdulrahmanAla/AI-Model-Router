const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function appHarness() {
  const pending = [];
  const timers = new Map();
  const downloads = [];
  const storage = new Map();
  let nextTimer = 0;
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  const context = vm.createContext({
    AbortController,
    document: {
      querySelector: () => ({ dataset: {}, hidden: true, children: [], classList: { add() {}, remove() {}, contains() { return false; } }, replaceChildren(...nodes) { this.children = nodes; }, append(...nodes) { this.children.push(...nodes); } }),
      body: { append(node) { downloads.push(node); } },
      createElement: () => ({ style: {}, children: [], attributes: {}, append(...nodes) { this.children.push(...nodes); }, setAttribute(name, value) { this.attributes[name] = value; }, addEventListener(event, callback) { this[event] = callback; }, click() { this.clicked = true; }, remove() { this.removed = true; } }),
    },
    window: {
      setTimeout: (callback) => { timers.set(++nextTimer, callback); return nextTimer; },
      clearTimeout: (id) => timers.delete(id),
      localStorage: {
        getItem: (key) => storage.has(key) ? storage.get(key) : null,
        setItem: (key, value) => storage.set(key, String(value)),
        removeItem: (key) => storage.delete(key),
      },
    },
    storage,
    Blob: class Blob { constructor(parts, options) { this.parts = parts; this.options = options; } },
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} },
    fetch: (url, options) => new Promise((resolve, reject) => pending.push({ resolve, reject, signal: options.signal })),
  });
  vm.runInContext(source.replace(/  wireEvents\(\);[\s\S]*$/, `
    renderMessages = () => {};
    copyText = (value) => { state.copiedEvidence = value; };
    setServiceStatus = (kind, label) => { state.serviceLabel = label; };
    this.app = { state, elements, solve, cancelSolve, retrySolve, requestAi, cancelAi, copySessionEvidence, downloadSessionEvidence, sessionEvidenceText, addCopyActions, exampleValues, routeLabel, shouldFocusComposer, shouldCloseSidebarOnEscape, shouldFocusChatSearch, latestMessage, renderAiResponse, renderChatList, persistSession, restoreSession, storage };
  })();`), context);
  return { ...context.app, pending, timers, downloads };
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

test('route label makes the exact local path explicit', () => {
  const app = appHarness();
  assert.equal(app.routeLabel({ aiCalls: 0, routes: ['solver'] }), 'Exact local · 0 model calls');
  assert.equal(app.routeLabel({ aiCalls: 1, routes: ['solver', 'explain'] }), '1 general-model call');
  assert.equal(app.routeLabel({ aiCalls: null, routes: ['solver'] }), 'AI calls not reported');
});

test('slash shortcut only focuses the composer outside text fields', () => {
  const app = appHarness();
  assert.equal(app.shouldFocusComposer({ key: '/', ctrlKey: false, metaKey: false, altKey: false }, 'BODY'), true);
  assert.equal(app.shouldFocusComposer({ key: '/', ctrlKey: false, metaKey: false, altKey: false }, 'TEXTAREA'), false);
  assert.equal(app.shouldFocusComposer({ key: '/', ctrlKey: true, metaKey: false, altKey: false }, 'BODY'), false);
});

test('escape gives an open sidebar priority', () => {
  const app = appHarness();
  assert.equal(app.shouldCloseSidebarOnEscape({ key: 'Escape' }, true), true);
  assert.equal(app.shouldCloseSidebarOnEscape({ key: 'Escape' }, false), false);
});

test('command K focuses chat search outside text fields', () => {
  const app = appHarness();
  assert.equal(app.shouldFocusChatSearch({ key: 'k', ctrlKey: true, metaKey: false, altKey: false }, 'BODY'), true);
  assert.equal(app.shouldFocusChatSearch({ key: 'K', ctrlKey: false, metaKey: true, altKey: false }, 'BODY'), true);
  assert.equal(app.shouldFocusChatSearch({ key: 'k', ctrlKey: true, metaKey: false, altKey: false }, 'INPUT'), false);
});

test('latest question navigation selects the newest session message', () => {
  const app = appHarness();
  assert.equal(app.latestMessage([]), null);
  assert.equal(app.latestMessage([{ id: '1' }, { id: '2' }]).id, '2');
});

test('session persistence restores completed work without in-flight state', () => {
  const app = appHarness();
  app.state.messages = [{ id: '4', request, display: 'Derivative x^2', response: { ...result }, loading: false, controller: {}, aiLoading: true }];
  app.persistSession();
  app.state.messages = [];
  app.restoreSession();
  assert.equal(app.state.messages.length, 1);
  assert.equal(app.state.messages[0].response.result, '2*x');
  assert.equal(app.state.messages[0].loading, undefined);
  assert.equal(app.state.messages[0].controller, undefined);
  assert.equal(app.state.selectedMessageId, '4');
});

test('malformed session storage is discarded safely', () => {
  const app = appHarness();
  app.storage.set('ai-math-assistant.session.v1', '{not-json');
  app.restoreSession();
  assert.equal(app.state.messages.length, 0);
  assert.equal(app.storage.has('ai-math-assistant.session.v1'), false);
});

test('selected chat row exposes aria-current', () => {
  const app = appHarness();
  app.state.messages = [{ id: '1', request: { operation: 'derivative', expression: 'x' } }];
  app.state.selectedMessageId = '1';
  app.renderChatList();
  assert.equal(app.elements.chatList.children[0].attributes['aria-current'], 'true');
});

for (const [question, expected] of [
  [{ operation: 'integral', expression: 'x', lower: '0', upper: '1' }, 'Integral x from 0 to 1'],
  [{ operation: 'limit', expression: '1/x', target: '0', direction: '+' }, 'Limit of 1/x as x approaches 0 from the right'],
]) {
  test(`full-solution copy preserves context: ${expected}`, () => {
    const app = appHarness();
    const buttons = [];
    app.addCopyActions({ ...result, expression: question.expression, metrics: { route: 'solver', ai_calls: 0, solver_ms: 4.5, elapsed_ms: 9.25 }, steps: ['Compute the result.'],
      notes: ['Numerical samples are not a proof.'] }, { append: (button) => buttons.push(button) }, question);
    buttons.find((button) => button.textContent === 'Copy full solution').click();
    assert.ok(app.state.copiedEvidence.includes(`Question: ${expected}`));
    assert.match(app.state.copiedEvidence, /Verification \(Symbolic check\): Checked\./);
    assert.match(app.state.copiedEvidence, /Numerical samples are not a proof/);
    assert.match(app.state.copiedEvidence, /Routes: solver/);
    assert.match(app.state.copiedEvidence, /Timing: solver 4\.50 ms; total 9\.25 ms; AI Not reported/);
  });
}

test('unresolved results can be copied as a full attempt', () => {
  const app = appHarness();
  const buttons = [];
  const unresolved = { status: 'unresolved', result: null, verification: { status: 'not_checked', detail: 'The exact route stopped safely.' }, steps: ['Stop before returning an exact answer.'] };
  app.addCopyActions(unresolved, { append: (button) => buttons.push(button) }, request);
  buttons.find((button) => button.textContent === 'Copy full attempt').click();
  assert.match(app.state.copiedEvidence, /Question: Derivative x\^2/);
  assert.match(app.state.copiedEvidence, /Status: unresolved/);
  assert.match(app.state.copiedEvidence, /Stop before returning/);
});

test('full-solution copy counts optional AI attempts', () => {
  const app = appHarness();
  const buttons = [];
  const message = { display: 'Derivative x^2', response: { ...result, metrics: { route: 'solver', ai_calls: 0, solver_ms: 4, elapsed_ms: 8 }, steps: ['Compute the result.'] }, ai: { status: 'error', message: 'Provider unavailable.' }, aiAttempts: [
    { status: 'answered', action: 'explain', text: 'Use the power rule here.', metrics: { route: 'ai', ai_calls: 1, latency_ms: 12, total_tokens: 20 } },
    { status: 'error', action: 'explain' }
  ] };
  app.addCopyActions(message.response, { append: (button) => buttons.push(button) }, request, message);
  buttons.find((button) => button.textContent === 'Copy full solution').click();
  assert.match(app.state.copiedEvidence, /Routes: solver \+ ai \+ explain/);
  assert.match(app.state.copiedEvidence, /General-model calls: not reported/);
  assert.match(app.state.copiedEvidence, /AI Not reported/);
  assert.match(app.state.copiedEvidence, /AI explanation \(unverified\):\nUse the power rule here\./);
});

test('answered AI text has an independent copy action', () => {
  const app = appHarness();
  const children = [];
  app.renderAiResponse({ ai: { status: 'answered', text: 'Use the power rule here.' } }, { append: (node) => children.push(node) });
  const box = children[0];
  const copy = box.children.find((child) => child.textContent === 'Copy AI explanation');
  assert.ok(copy);
  assert.equal(copy.attributes['aria-label'], 'Copy unverified AI explanation');
  copy.click();
  assert.equal(app.state.copiedEvidence, 'Use the power rule here.');
});

test('AI states expose live-region semantics', () => {
  const app = appHarness();
  const loading = [];
  app.renderAiResponse({ ai: { status: 'loading', message: 'Working...' } }, { append: (node) => loading.push(node) });
  assert.equal(loading[0].attributes['aria-busy'], 'true');
  const answered = [];
  app.renderAiResponse({ ai: { status: 'answered', text: 'Done.' } }, { append: (node) => answered.push(node) });
  assert.equal(answered[0].attributes['aria-live'], 'polite');
});

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

test('oversized AI success is a recoverable invalid response', async () => {
  const app = appHarness();
  const message = { request, response: result };
  const running = app.requestAi(message, 'explain');
  app.pending[0].resolve(response({ status: 'answered', text: 'x'.repeat(12001) }));
  await running;
  assert.equal(message.ai.status, 'error');
  assert.match(message.ai.message, /invalid response/i);
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
  app.state.messages.push({ display: 'Derivative x^2', response: { ...result, metrics: { route: 'solver', ai_calls: 0, solver_ms: 12.5, elapsed_ms: 25.75 } }, ai: { status: 'error', message: 'Provider unavailable.' }, aiAttempts: [
    { status: 'answered', action: 'explain', text: 'Explain the power rule.', metrics: { ai_calls: 1, total_tokens: 40 } },
    { status: 'error', action: 'explain' },
  ] });
  app.copySessionEvidence();
  assert.match(app.state.copiedEvidence, /General-model calls: not reported/);
  assert.match(app.state.copiedEvidence, /Reported tokens: not reported/);
  assert.match(app.state.copiedEvidence, /AI attempts: 2/);
  assert.match(app.state.copiedEvidence, /Routes: solver \+ explain/);
  assert.match(app.state.copiedEvidence, /Solver time: 12\.50 ms/);
  assert.match(app.state.copiedEvidence, /Total solve time: 25\.75 ms/);
  assert.match(app.sessionEvidenceText(), /AI Math Assistant session evidence/);
  assert.match(app.state.copiedEvidence, /AI explanation \(unverified\):\nExplain the power rule\./);
});

test('session evidence download creates a text attachment', () => {
  const app = appHarness();
  app.state.messages.push({ display: 'Derivative x^2', response: { ...result, metrics: { ai_calls: 0 } } });
  app.downloadSessionEvidence();
  assert.equal(app.downloads.length, 1);
  assert.equal(app.downloads[0].download, 'ai-math-assistant-session-evidence.txt');
  assert.equal(app.downloads[0].href, 'blob:test');
  assert.equal(app.downloads[0].clicked, true);
  assert.equal(app.downloads[0].removed, true);
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
