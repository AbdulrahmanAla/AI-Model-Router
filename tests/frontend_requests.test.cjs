const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const indexHtml = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');

function appHarness({ withMathQuill = false, staticMathFailure = false, liveRender = false } = {}) {
  const pending = [];
  const timers = new Map();
  const downloads = [];
  const domNodes = new Map();
  let nextTimer = 0;
  const createNode = () => ({ value: '', dataset: {}, style: {}, scrollHeight: 42, hidden: true, children: [], get childElementCount() { return this.children.length; }, attributes: {}, focus() { this.focused = true; }, getBoundingClientRect() { return { top: this.rectTop ?? 200 }; }, removeAttribute(name) { delete this.attributes[name]; }, setAttribute(name, value) { this.attributes[name] = value; }, addEventListener(event, callback) { this[event] = callback; }, classList: { add() {}, remove() {}, contains() { return false; } }, replaceChildren(...nodes) { this.children = nodes; }, append(...nodes) { this.children.push(...nodes); }, appendChild(node) { this.children.push(node); return node; }, querySelector() { return createNode(); }, querySelectorAll(selector) { return descendants(this).filter((node) => String(node.className || '').split(' ').includes(selector.slice(1))); } });
  const mathFields = new Map();
  const mathQuill = withMathQuill ? { getInterface: () => ({ MathField(node) {
    let value = '';
    const field = { latex(next) { if (next !== undefined) { value = next; return field; } return value; }, focus() { node.focused = true; } };
    mathFields.set(node.id, field);
    return field;
  }, StaticMath(node) {
    if (staticMathFailure) throw new Error('Renderer unavailable');
    return { latex(value) { node.renderedLatex = value; return this; }, reflow() {} };
  } }) } : undefined;
  const source = fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
  const context = vm.createContext({
    AbortController,
    document: {
      createTextNode: (text) => ({ textContent: text }),
      querySelector: (selector) => { if (!domNodes.has(selector)) { const node = createNode(); node.id = selector.startsWith('#') ? selector.slice(1) : ''; domNodes.set(selector, node); } return domNodes.get(selector); },
      querySelectorAll: () => [],
      addEventListener() {},
      body: { append(node) { downloads.push(node); } },
      createElement: () => Object.assign(createNode(), { click() { this.clicked = true; }, remove() { this.removed = true; } }),
    },
    window: {
      setTimeout: (callback) => { timers.set(++nextTimer, callback); return nextTimer; },
      clearTimeout: (id) => timers.delete(id),
      MathQuill: mathQuill,
    },
    Blob: class Blob { constructor(parts, options) { this.parts = parts; this.options = options; } },
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} },
    fetch: (url, options) => new Promise((resolve, reject) => pending.push({ resolve, reject, signal: options.signal, url, options })),
  });
  vm.runInContext(source.replace(/  wireEvents\(\);[\s\S]*$/, `
    const renderConversation = renderMessages;
    ${liveRender ? '' : 'renderMessages = () => {};'}
    copyText = (value) => { state.copiedEvidence = value; };
    setServiceStatus = (kind, label) => { state.serviceLabel = label; };
    this.app = { state, elements, solve, route, cancelSolve, retrySolve, retryRoute, requestAi, cancelAi, copySessionEvidence, downloadSessionEvidence, sessionEvidenceText, addCopyActions, exampleValues, fillComposer, freeformRequest, routeLabel, resultAriaLabel, shouldFocusComposer, shouldCloseSidebarOnEscape, shouldCloseChatSearch, shouldFocusChatSearch, latestMessage, renderAiResponse, renderChatList, closeChatSearch, openChatSearch, fetchWithTimeout, submit, clearFormError, renderAssistant, renderConversation, latexToExpression, expressionToLatex, buildRequest, buildRoutePayload, setFieldValue, validateRequest, validateRoutePayload };
  })();`), context);
  return { ...context.app, pending, timers, downloads, mathFields };
}

const request = { operation: 'derivative', expression: 'x^2' };
const result = { status: 'solved', operation: 'derivative', expression: 'x^2', request: { ...request, variable: 'x', lower: null, upper: null, target: null, direction: null }, result: '2*x', verification: { status: 'symbolic_check', detail: 'Checked.' }, steps: ['Read the function.', 'Apply the power rule.'] };
const response = (body) => ({ ok: true, json: async () => body });

test('free form math messages become validated structured requests', () => {
  const app = appHarness();
  assert.deepEqual(app.freeformRequest('Differentiate x^3 + sin(x)'), {
    request: { operation: 'derivative', expression: 'x^3 + sin(x)', variable: 'x', lower: null, upper: null, target: null, direction: null }, prompt: ''
  });
  assert.deepEqual(app.freeformRequest('Find the limit of sin(x)/x as x approaches 0 from the right').request, {
    operation: 'limit', expression: 'sin(x)/x', variable: 'x', lower: null, upper: null, target: '0', direction: '+'
  });
  assert.deepEqual(app.freeformRequest('Solve x^2 - 4 = 0').request.operation, 'equation');
});

test('free form prose stays a prompt and is never treated as a formula', () => {
  const app = appHarness();
  const parsed = app.freeformRequest('Can you explain why the power rule works?');
  assert.equal(parsed.request, null);
  assert.equal(parsed.prompt, 'Can you explain why the power rule works');
});

function descendants(node) {
  return (node.children || []).flatMap((child) => [child, ...descendants(child)]);
}

test('exact results display typeset fractions while keeping accessible and copied answers exact', () => {
  const app = appHarness({ withMathQuill: true });
  app.state.messages.push({ id: '1', request, display: 'Derivative sqrt(x)', response: { ...result, result: '1/(2*sqrt(x))', latex: '\\frac{1}{2 \\sqrt{x}}' } });
  app.renderConversation();
  const nodes = descendants(app.elements.messages);
  const visual = nodes.find((node) => node.className === 'formula-math');
  assert.ok(visual, 'A typeset formula should be rendered');
  assert.equal(visual.renderedLatex, '\\frac{1}{2 \\sqrt{x}}');
  assert.equal(visual.attributes['aria-hidden'], 'true');
  assert.equal(nodes.find((node) => node.className === 'formula').attributes['aria-label'], 'Exact result: 1/(2*sqrt(x))');
  const copy = nodes.find((node) => node.attributes?.['aria-label'] === 'Copy exact result');
  copy.click();
  assert.equal(app.state.copiedEvidence, '1/(2*sqrt(x))');
  visual.append({ textContent: 'Rendered glyphs must not enter the plain answer' });
  app.renderConversation();
  const updated = descendants(app.elements.messages);
  assert.notEqual(updated.find((node) => node.className === 'formula-math'), visual);
  const plain = updated.filter((node) => node.className === 'sr-only' && node.textContent === '1/(2*sqrt(x))');
  assert.equal(plain.length, 1, 'Repeated rendering keeps one authoritative accessible answer');
});

test('exact result cards offer LaTeX copying without changing the typed result copy', () => {
  const app = appHarness();
  const buttons = [];
  app.addCopyActions({ result: '1/(2*sqrt(x))', latex: '\\frac{1}{2\\sqrt{x}}', steps: [] }, { append: (button) => buttons.push(button) }, request);
  const latex = buttons.find((button) => button.textContent === 'Copy LaTeX');
  assert.ok(latex);
  assert.equal(latex.attributes['aria-label'], 'Copy exact result as LaTeX');
  latex.click();
  assert.equal(app.state.copiedEvidence, '\\frac{1}{2\\sqrt{x}}');
  const exact = buttons.find((button) => button.textContent === 'Copy exact result');
  exact.click();
  assert.equal(app.state.copiedEvidence, '1/(2*sqrt(x))');
});

test('result cards copy the complete structured request including context fields', () => {
  const app = appHarness();
  const buttons = [];
  const requestWithContext = { operation: 'limit', expression: 'sqrt(x)', variable: 'x', lower: null, upper: null, target: '0', direction: '+' };
  app.addCopyActions({ result: '0', steps: [] }, { append: (button) => buttons.push(button) }, requestWithContext);
  const copy = buttons.find((button) => button.textContent === 'Copy request JSON');
  assert.ok(copy);
  assert.equal(copy.attributes['aria-label'], 'Copy structured request JSON');
  copy.click();
  assert.equal(app.state.copiedEvidence, JSON.stringify(requestWithContext));
});

for (const [label, options, latex] of [
  ['missing library', {}, '\\frac{1}{x}'],
  ['renderer failure', { withMathQuill: true, staticMathFailure: true }, '\\frac{1}{x}'],
  ['unfamiliar notation', { withMathQuill: true }, '\\operatorname{erf}(x)'],
  ['indexed root', { withMathQuill: true }, '\\sqrt[3]{x}'],
  ['oversized notation', { withMathQuill: true }, 'x'.repeat(4001)],
  ['excessive nesting', { withMathQuill: true }, '{'.repeat(17) + 'x' + '}'.repeat(17)],
  ['unbalanced groups', { withMathQuill: true }, '\\frac{1}{x'],
  ['plain language result', { withMathQuill: true }, 'all real x'],
]) {
  test(`exact answer stays readable with ${label}`, () => {
    const app = appHarness(options);
    app.state.messages.push({ id: '1', request, display: 'Question', response: { ...result, latex } });
    app.renderConversation();
    const nodes = descendants(app.elements.messages);
    assert.equal(nodes.some((node) => node.className === 'formula-math'), false);
    const formula = nodes.find((node) => node.className === 'formula');
    assert.equal(formula.attributes['aria-label'], 'Exact result: 2*x');
    assert.ok(formula.textContent === '2*x' || formula.children.some((node) => node.textContent === '2*x'));
    assert.ok(nodes.some((node) => node.textContent === 'Solution steps'));
  });
}

test('visual math conversion preserves supported fractions, powers, products, and constants', () => {
  const app = appHarness();
  for (const [latex, expected] of [
    ['\\frac{x+1}{x-1}', '((x+1)/(x-1))'],
    ['\\frac{1}{\\frac{x}{2}}', '((1)/(((x)/(2))))'],
    ['\\frac{1}{x}^{2}', '((1)/(x))^(2)'],
    ['x^{x+1}', 'x^(x+1)'],
    ['x^{12}', 'x^(12)'],
    ['2x+3\\cdot\\pi', '2*x+3*pi'],
    ['\\sin\\left(x\\right)+\\sqrt{x}', 'sin(x)+sqrt(x)'],
    ['x+\\infty', 'x+oo'],
  ]) assert.equal(app.latexToExpression(latex), expected, latex);
});

test('visual math conversion rejects unsupported commands and indexed roots', () => {
  const app = appHarness();
  assert.match(app.latexToExpression('\\theta+x'), /__unsupported_latex_command_theta__/);
  assert.match(app.latexToExpression('\\sqrt[3]{x}'), /__unsupported_indexed_root__/);
  assert.match(app.latexToExpression('\\frac{x+1'), /__unsupported_frac__/);
  assert.match(app.latexToExpression('x'.repeat(4001)), /__unsupported_math_input__/);
  assert.match(app.latexToExpression(`${'{'.repeat(17)}x${'}'.repeat(17)}`), /__unsupported_math_input__/);
});

test('MathQuill edit roundtrip keeps grouped and multidigit exponents intact', () => {
  const app = appHarness({ withMathQuill: true });
  for (const [expression, expected] of [
    ['x^12', 'x^(12)'],
    ['x^(x+1)', 'x^(x+1)'],
    ['x**(-2)', 'x^(-2)'],
    ['sin(x^2)', 'sin(x^(2))'],
    ['(x+1)/(x-1)', '(x+1)/(x-1)'],
  ]) {
    app.setFieldValue('expression', expression);
    assert.equal(app.buildRequest().expression, expected, expression);
  }
});

test('restoring a square-root example keeps the radicand inside the root', () => {
  const app = appHarness({ withMathQuill: true });
  assert.equal(app.expressionToLatex('sqrt(x)'), '\\sqrt x');
  app.setFieldValue('expression', 'sqrt(x)');
  assert.equal(app.buildRequest().expression, 'sqrt(x)');
  assert.equal(app.expressionToLatex('sqrt(x+1)'), '\\sqrt{\\left(x+1\\right)}');
  app.setFieldValue('expression', 'sqrt(x+1)');
  assert.equal(app.buildRequest().expression, 'sqrt((x+1))');
});

test('visual editor request construction includes operation context while typed fallback remains usable', () => {
  const visual = appHarness({ withMathQuill: true });
  visual.elements.operation.value = 'integral';
  visual.setFieldValue('expression', '\\frac{x+1}{2}');
  visual.setFieldValue('lower', '0');
  visual.setFieldValue('upper', '1');
  assert.deepEqual(JSON.parse(JSON.stringify(visual.buildRequest())), {
    operation: 'integral', expression: '((x+1)/(2))', variable: 'x', lower: '0', upper: '1', target: null, direction: null,
  });

  const typed = appHarness();
  typed.elements.operation.value = 'limit';
  typed.elements.expression.value = 'sin(x)/x';
  typed.elements.target.value = '0';
  typed.elements.direction.value = '+';
  assert.deepEqual(JSON.parse(JSON.stringify(typed.buildRequest())), {
    operation: 'limit', expression: 'sin(x)/x', variable: 'x', lower: null, upper: null, target: '0', direction: '+',
  });
});

test('exact mode keeps the existing solver request boundary', async () => {
  const app = appHarness();
  app.elements.operation.value = 'derivative';
  app.elements.expression.value = 'x^2';
  app.elements.routeMode.value = 'exact';
  app.submit({ preventDefault() {} });
  assert.equal(app.pending.length, 1);
  assert.equal(app.pending[0].url, '/api/solve');
  assert.equal(JSON.parse(app.pending[0].options.body).expression, 'x^2');
});

test('structured routed mode sends exactly one request to the route boundary', () => {
  const app = appHarness();
  app.elements.operation.value = 'derivative';
  app.elements.expression.value = 'x^2';
  app.elements.routeMode.value = 'jev';
  app.submit({ preventDefault() {} });
  assert.equal(app.pending.length, 1);
  assert.equal(app.pending[0].url, '/api/route');
  assert.deepEqual(JSON.parse(app.pending[0].options.body), {
    mode: 'jev',
    request: { operation: 'derivative', expression: 'x^2', variable: 'x', lower: null, upper: null, target: null, direction: null },
  });
});

test('language routed mode sends a bounded prompt without a solver request', () => {
  const app = appHarness();
  app.elements.routeMode.value = 'ai_only';
  app.elements.routePrompt.value = 'Explain why the derivative of x squared is 2x.';
  app.submit({ preventDefault() {} });
  assert.equal(app.pending.length, 1);
  assert.equal(app.pending[0].url, '/api/route');
  assert.deepEqual(JSON.parse(app.pending[0].options.body), {
    mode: 'ai_only',
    prompt: 'Explain why the derivative of x squared is 2x.',
  });
});

test('route response keeps AI text unverified and records route metrics', async () => {
  const app = appHarness({ liveRender: true });
  const message = { id: 'route-1', routeMode: 'ai_only', prompt: 'Explain x squared.', request: null, generation: 0, loading: true };
  app.state.messages.push(message);
  const running = app.route({ mode: 'ai_only', request: { expression: '' }, prompt: 'Explain x squared.' }, message);
  assert.equal(app.pending.length, 1);
  app.pending[0].resolve(response({ status: 'routed', answer: { status: 'answered', text: 'The derivative is 2x.' }, routing: { source: 'ollama', choice: 'ai', ai_calls: 1, total_tokens: 18 } }));
  await running;
  assert.equal(message.response.status, 'answered');
  assert.equal(message.response.verification.status, 'not_checked');
  assert.equal(message.response.metrics.route, 'ai');
  assert.equal(message.response.metrics.source, 'ollama');
});

test('a completed solve reveals the start of its result when following the conversation', async () => {
  const app = appHarness({ liveRender: true });
  const message = { id: '1', request, display: 'Derivative x^2', generation: 0, loading: true };
  app.state.messages.push(message);
  Object.assign(app.elements.conversation, { scrollTop: 580, scrollHeight: 1000, clientHeight: 400, rectTop: 58 });
  const running = app.solve(request, message);
  app.pending[0].resolve(response(result));
  await running;
  assert.equal(app.elements.conversation.scrollTop, 704, 'Reveal the start of the answer within the conversation pane');
});

test('a solve completing while the student reads earlier work keeps their reading position', async () => {
  const app = appHarness({ liveRender: true });
  const message = { id: '2', request, display: 'Derivative x^2', generation: 0, loading: true };
  app.state.messages.push({ id: '1', request, display: 'Previous question', response: result }, message);
  Object.assign(app.elements.conversation, { scrollTop: 200, scrollHeight: 1000, clientHeight: 400 });
  const running = app.solve(request, message);
  app.pending[0].resolve(response(result));
  await running;
  assert.equal(app.elements.conversation.scrollTop, 200);
});

for (const [outcome, payload] of [
  ['unresolved', { ...result, status: 'unresolved', result: null, verification: { status: 'not_checked', detail: 'Unsupported exact calculation.' } }],
  ['invalid response', {}],
]) {
  test(`a completed ${outcome} reveals its stopping reason`, async () => {
    const app = appHarness({ liveRender: true });
    const message = { id: '1', request, display: 'Question', generation: 0, loading: true };
    app.state.messages.push(message);
    Object.assign(app.elements.conversation, { scrollTop: 580, scrollHeight: 1000, clientHeight: 400, rectTop: 58 });
    const running = app.solve(request, message);
    app.pending[0].resolve(response(payload));
    await running;
    assert.equal(app.elements.conversation.scrollTop, 704);
    assert.ok(message.response?.status === 'unresolved' || message.error);
  });
}

test('editing a visual limit and applying an example preserve fields and direction', () => {
  const app = appHarness({ withMathQuill: true });
  app.fillComposer({ operation: 'limit', expression: 'x^(x+1)', target: 'pi/2', direction: '+' });
  assert.deepEqual(JSON.parse(JSON.stringify(app.buildRequest())), {
    operation: 'limit', expression: 'x^(x+1)', variable: 'x', lower: null, upper: null, target: 'pi/2', direction: '+',
  });
  app.fillComposer(app.exampleValues({ dataset: { operation: 'limit', expression: 'sqrt(x)', target: '0', direction: '+' } }));
  assert.deepEqual(JSON.parse(JSON.stringify(app.buildRequest())), {
    operation: 'limit', expression: 'sqrt(x)', variable: 'x', lower: null, upper: null, target: '0', direction: '+',
  });
});

test('unsupported visual notation is stopped at the editor boundary', () => {
  const app = appHarness();
  const error = app.validateRequest({ operation: 'derivative', expression: app.latexToExpression('\\theta*x') });
  assert.match(error.message, /not supported yet/i);
});

for (const [position, force, expected] of [[200, false, 200], [580, false, 1400], [200, true, 1400]]) {
  test(`conversation render preserves reading position ${position}, force latest ${force}`, () => {
    const app = appHarness();
    Object.assign(app.elements.conversation, { scrollTop: position, scrollHeight: 1000, clientHeight: 400 });
    app.elements.messages.replaceChildren = function () {
      this.children = [];
      app.elements.conversation.scrollTop = 0;
      app.elements.conversation.scrollHeight = 1400;
    };
    app.state.messages.push({ id: '1', request, display: 'Derivative x^2', response: result });
    app.renderConversation(force);
    assert.equal(app.elements.conversation.scrollTop, expected);
    assert.equal(app.elements.messages.children.length, 1);
    assert.equal(app.elements.welcome.hidden, true);
  });
}

test('solution and route disclosures retain each message reading state across AI updates', async () => {
  const app = appHarness();
  const message = { request, response: result };
  const disclosures = (target) => {
    const found = {};
    const visit = (node) => {
      if (node.className === 'solution-steps' || node.className === 'route-details') found[node.className] = node;
      (node.children || []).forEach(visit);
    };
    visit(app.renderAssistant(target));
    return found;
  };
  const initial = disclosures(message);
  assert.equal(initial['solution-steps'].open, true);
  assert.equal(initial['route-details'].open, false);
  initial['solution-steps'].open = false;
  initial['solution-steps'].toggle();
  initial['route-details'].open = true;
  initial['route-details'].toggle();
  const running = app.requestAi(message, 'explain');
  const loading = disclosures(message);
  assert.equal(loading['solution-steps'].open, false);
  assert.equal(loading['route-details'].open, true);
  app.pending[0].resolve(response({ status: 'answered', text: 'Use the power rule.', verification: { status: 'not_checked', method: 'AI output', detail: 'Unverified.' } }));
  await running;
  const completed = disclosures(message);
  assert.equal(completed['solution-steps'].open, false);
  assert.equal(completed['route-details'].open, true);
  const other = disclosures({ request, response: result });
  assert.equal(other['solution-steps'].open, true);
  assert.equal(other['route-details'].open, false);
});

for (const question of [
  { operation: 'derivative', expression: 'x^3' },
  { operation: 'integral', expression: 'x^2', lower: '0', upper: '1' },
  { operation: 'integral', expression: 'sin(x)', lower: null, upper: null },
  { operation: 'limit', expression: 'sqrt(x)', target: '0', direction: '+' },
  { operation: 'equation', expression: 'x^2 - 4 = 0' },
]) {
  for (const outcome of ['solved', 'unresolved', 'error']) {
    test(`edit ${outcome} ${question.operation} restores the question without a request`, () => {
      const app = appHarness();
      const original = JSON.stringify(question);
      const message = outcome === 'error' ? { request: question, error: 'Please correct the formula.' }
        : { request: question, response: { ...result, status: outcome, result: outcome === 'solved' ? result.result : null, steps: [] } };
      for (const name of ['expression', 'lower', 'upper', 'target', 'direction']) app.elements[name].value = 'old draft';
      const nodes = [];
      const visit = (node) => { nodes.push(node); (node.children || []).forEach(visit); };
      visit(app.renderAssistant(message));
      const edit = nodes.find((node) => node.textContent === 'Edit question');
      assert.ok(edit);
      edit.click();
      assert.equal(app.elements.operation.value, question.operation);
      assert.equal(app.elements.expression.value, question.expression);
      assert.equal(app.elements.lower.value, question.lower || '');
      assert.equal(app.elements.upper.value, question.upper || '');
      assert.equal(app.elements.target.value, question.target || '');
      assert.equal(app.elements.direction.value, question.direction || 'both');
      assert.equal(app.elements.integralOptions.hidden, question.operation !== 'integral');
      assert.equal(app.elements.limitOptions.hidden, question.operation !== 'limit');
      assert.equal(app.elements.expression.focused, true);
      assert.equal(app.pending.length, 0);
      assert.equal(JSON.stringify(question), original);
      assert.equal(app.state.messages.length, 0);
    });
  }
}

for (const status of ['solved', 'unresolved']) {
  test(`visible cancel action stops the ${status === 'solved' ? 'explanation' : 'fallback'} request`, async () => {
    const app = appHarness();
    const solverResponse = { ...result, status, result: status === 'solved' ? '2*x' : null, steps: [] };
    const message = { request, response: solverResponse };
    const running = app.requestAi(message, status === 'solved' ? 'explain' : 'fallback');
    const nodes = [];
    const visit = (node) => { nodes.push(node); (node.children || []).forEach(visit); };
    visit(app.renderAssistant(message));
    const cancel = nodes.find((node) => node.textContent === 'Cancel AI request');
    assert.ok(cancel, 'each active AI route exposes a visible cancel button');
    cancel.click();
    assert.equal(app.pending[0].signal.aborted, true);
    assert.equal(message.aiLoading, false);
    assert.equal(message.ai.status, 'error');
    assert.match(message.ai.message, /cancelled.*usage is not yet known/i);
    assert.equal(message.response, solverResponse);
    app.pending[0].resolve(response({ status: 'answered', text: 'Late answer', verification: { status: 'not_checked', method: 'AI output', detail: 'Unverified.' } }));
    await running;
    assert.equal(message.ai.status, 'error');
    assert.equal(message.ai.text, undefined);
  });
}

for (const [operation, expression, lower, upper, target, invalidField] of [
  ['derivative', '', '', '', '', 'expression'],
  ['integral', '', '0', '', '', 'expression'],
  ['limit', '', '', '', '', 'expression'],
  ['integral', 'x', '0', '', '', 'upper'],
  ['integral', 'x', '', '1', '', 'lower'],
  ['limit', 'x', '', '', '', 'target'],
]) {
  test(`invalid ${operation} submission focuses ${invalidField} (${expression || 'empty expression'}, ${lower}, ${upper})`, () => {
    const app = appHarness();
    Object.entries({ operation, expression, lower, upper, target, direction: 'both' }).forEach(([name, value]) => { app.elements[name].value = value; });
    app.submit({ preventDefault() {} });
    assert.equal(app.elements[invalidField].focused, true);
    assert.equal(app.elements[invalidField].attributes['aria-invalid'], 'true');
    for (const name of ['expression', 'lower', 'upper', 'target']) {
      if (name !== invalidField) assert.equal(app.elements[name].attributes['aria-invalid'], undefined);
    }
    assert.equal(app.pending.length, 0);
    assert.equal(app.state.messages.length, 0);
    assert.equal(app.elements.formError.hidden, false);
    app.clearFormError();
    assert.equal(app.elements.formError.hidden, true);
    assert.equal(app.elements.expression.attributes['aria-describedby'], 'input-help');
    assert.equal(app.elements[invalidField].attributes['aria-invalid'], undefined);
  });
}

test('chat search opening and closing synchronizes name, state, filter and focus', () => {
  const app = appHarness();
  app.openChatSearch();
  assert.equal(app.elements.chatSearchWrap.hidden, false);
  assert.equal(app.elements.chatSearchToggle.attributes['aria-expanded'], 'true');
  assert.equal(app.elements.chatSearchToggle.attributes['aria-label'], 'Close chat search');
  assert.equal(app.elements.chatSearch.focused, true);
  app.state.chatFilter = 'missing';
  app.elements.chatSearch.value = 'missing';
  app.closeChatSearch();
  assert.equal(app.elements.chatSearchWrap.hidden, true);
  assert.equal(app.elements.chatSearchToggle.attributes['aria-expanded'], 'false');
  assert.equal(app.elements.chatSearchToggle.attributes['aria-label'], 'Search chats (Ctrl+K or Cmd+K)');
  assert.equal(app.elements.chatSearchToggle.focused, true);
  assert.equal(app.state.chatFilter, '');
  assert.equal(app.elements.chatSearch.value, '');
});

test('examples carry their own limit direction', () => {
  const app = appHarness();
  assert.equal(JSON.stringify(app.exampleValues({ dataset: { operation: 'limit', expression: 'sqrt(x)', target: '0', direction: '+' } })), JSON.stringify({
    operation: 'limit', expression: 'sqrt(x)', lower: '', upper: '', target: '0', direction: '+'
  }));
  assert.equal(app.exampleValues({ dataset: { operation: 'limit', expression: 'sin(x)/x', target: '0' } }).direction, 'both');
});

test('a definite-integral example restores both bounds and clears prior limit context without making a request', () => {
  const app = appHarness({ withMathQuill: true });
  app.fillComposer({ operation: 'limit', expression: 'sqrt(x)', target: '0', direction: '+' });
  app.fillComposer(app.exampleValues({ dataset: { operation: 'integral', expression: 'x^2', lower: '0', upper: '1' } }));
  assert.deepEqual(JSON.parse(JSON.stringify(app.buildRequest())), {
    operation: 'integral', expression: 'x^(2)', variable: 'x', lower: '0', upper: '1', target: null, direction: null,
  });
  assert.equal(app.pending.length, 0);
});

test('session evidence starts with observed outcomes and labels its measurement limits', () => {
  const app = appHarness();
  app.state.messages.push(
    { display: 'Derivative x^2', request, response: { ...result, metrics: { route: 'solver', ai_calls: 0 } } },
    { display: 'Limit 1/x', request: { operation: 'limit', expression: '1/x', target: '0', direction: 'both' }, response: { status: 'unresolved', result: null, verification: { status: 'not_checked', detail: 'The sides disagree.' }, metrics: { route: 'solver', ai_calls: 0 } } },
  );
  const evidence = app.sessionEvidenceText();
  assert.match(evidence, /Session outcomes: 1 solved; 1 unresolved; 0 failed; 0 pending/);
  assert.match(evidence, /Solved-result checks: 1 symbolic; 0 numerical; 0 not independently checked; 0 failed/);
  assert.match(evidence, /Session general-model calls: 0/);
  assert.match(evidence, /Session reported tokens: not reported/);
  assert.match(evidence, /Session activity only; not a benchmark or an AI comparison/);
});

test('session summary never turns partially reported AI attempts into known usage totals', () => {
  const app = appHarness();
  app.state.messages.push({ id: '1', request, display: 'Derivative x^2', response: { ...result, metrics: { route: 'solver', ai_calls: 0 } }, aiAttempts: [
    { status: 'answered', action: 'explain', metrics: { ai_calls: 1, total_tokens: 20 } },
    { status: 'error', action: 'explain' },
  ] });
  app.renderConversation();
  const cards = Object.fromEntries(app.elements.sessionSummary.children.map((card) => [card.children[0].textContent, card.children[1].textContent]));
  assert.equal(cards['AI attempts'], '2');
  assert.equal(cards['General-model calls'], 'Not reported');
  assert.equal(cards['Reported AI tokens'], 'Not reported');
  assert.match(app.elements.sessionStats.textContent, /model calls not reported/);
  assert.match(app.sessionEvidenceText(), /Session general-model calls: not reported/);
  assert.match(app.sessionEvidenceText(), /Session reported tokens: not reported/);
});

test('session token totals include measured AI usage without treating solver-only questions as missing provider usage', () => {
  const app = appHarness();
  app.state.messages.push(
    { display: 'First question', request, error: 'Server unavailable; no AI action requested.' },
    { display: 'Second question', request, response: { ...result, metrics: { route: 'solver', ai_calls: 0 } }, aiAttempts: [
      { status: 'answered', action: 'explain', metrics: { ai_calls: 1, total_tokens: 20 } },
    ] },
  );
  assert.match(app.sessionEvidenceText(), /Session general-model calls: 1/);
  assert.match(app.sessionEvidenceText(), /Session reported tokens: 20/);
});

test('session evidence separates failed checks from failed requests and pending work', () => {
  const app = appHarness();
  for (const status of ['numerical_evidence', 'not_checked', 'failed']) {
    app.state.messages.push({ request, display: 'Question', response: { ...result, verification: { status, detail: 'Recorded check status.' }, metrics: { ai_calls: 0 } } });
  }
  app.state.messages.push({ request, display: 'Failed request', error: 'Server unavailable.' }, { request, display: 'Pending request', loading: true });
  const evidence = app.sessionEvidenceText();
  assert.match(evidence, /Session outcomes: 3 solved; 0 unresolved; 1 failed; 1 pending/);
  assert.match(evidence, /Solved-result checks: 0 symbolic; 1 numerical; 1 not independently checked; 1 failed/);
  assert.match(evidence, /Session general-model calls: 0/);
  app.renderConversation();
  assert.match(app.elements.sessionChecks.textContent, /^Pending requests: 1/);
});

test('route label makes the exact local path explicit', () => {
  const app = appHarness();
  assert.equal(app.routeLabel({ aiCalls: 0, routes: ['solver'] }), 'Exact local · 0 model calls');
  assert.equal(app.routeLabel({ aiCalls: 1, routes: ['solver', 'explain'] }), '1 general-model call');
  assert.equal(app.routeLabel({ aiCalls: null, routes: ['solver'] }), 'AI calls not reported');
});

test('a failed explanation retry preserves the previous unverified explanation in the page', async () => {
  const app = appHarness();
  const first = { action: 'explain', status: 'answered', text: 'Earlier explanation to keep.', metrics: { ai_calls: 1, total_tokens: 20 } };
  const message = { request, response: result, ai: first, aiAttempts: [first] };
  const running = app.requestAi(message, 'explain');
  app.pending[0].resolve({ ok: false, status: 502, json: async () => ({ detail: 'Provider unavailable.', metrics: { ai_calls: 1, total_tokens: null } }) });
  await running;
  const nodes = descendants(app.renderAssistant(message));
  assert.ok(nodes.some((node) => node.textContent === 'Earlier explanation to keep.'));
  assert.ok(nodes.some((node) => node.textContent === 'Provider unavailable.'));
  const history = nodes.find((node) => node.className === 'ai-history');
  assert.ok(history);
  assert.equal(history.open, false);
  history.open = true;
  history.toggle();
  const updated = descendants(app.renderAssistant(message));
  assert.equal(updated.find((node) => node.className === 'ai-history').open, true);
  const copy = updated.find((node) => node.attributes?.['aria-label'] === 'Copy unverified AI explanation from attempt 1');
  copy.click();
  assert.equal(app.state.copiedEvidence, 'Earlier explanation to keep.');
  const model = updated.find((node) => node.className === 'metric' && node.children[0].textContent === 'Model');
  assert.equal(model.children[1].textContent, 'Not reported');
  const earlierBox = descendants(history).find((node) => node.className === 'ai-response');
  assert.equal(earlierBox.attributes['aria-live'], undefined);
  assert.equal(app.pending.length, 1, 'Reading previous text needs no new provider request');
});

test('exact results expose a spoken result label', () => {
  const app = appHarness();
  assert.equal(app.resultAriaLabel(result), 'Exact result: 2*x');
  assert.equal(app.resultAriaLabel({ result: null }), 'Exact result unavailable');
});

test('navigation and operation controls keep their accessible relationships', () => {
  assert.match(indexHtml, /id="search-toggle"[^>]*aria-controls="chat-search-wrap"[^>]*aria-expanded="false"/);
  assert.match(indexHtml, /id="open-sidebar"[^>]*aria-controls="sidebar"[^>]*aria-expanded="false"/);
  assert.match(indexHtml, /id="operation"[^>]*aria-describedby="operation-hint"/);
  assert.match(indexHtml, /id="route-mode"[^>]*aria-describedby="route-mode-hint"/);
  assert.match(indexHtml, /id="route-prompt"[^>]*maxlength="2000"/);
});

for (const body of [null, {}, { status: 'ok' }, { status: 'ok', ai_configured: 'false' }]) {
  test(`malformed health response is rejected: ${JSON.stringify(body)}`, async () => {
    const app = appHarness();
    const running = app.fetchWithTimeout('/api/health', {}, 5000);
    app.pending[0].resolve(response(body));
    await assert.rejects(running, /invalid (health )?response/i);
  });
}

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

test('escape closes chat search before request cancellation', () => {
  const app = appHarness();
  assert.equal(app.shouldCloseChatSearchOnEscape({ key: 'Escape' }, true), true);
  assert.equal(app.shouldCloseChatSearchOnEscape({ key: 'Escape' }, false), false);
  assert.equal(app.shouldCloseChatSearchOnEscape({ key: 'Enter' }, true), false);
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
    app.addCopyActions({ ...result, expression: question.expression, latex: '\\frac{1}{2}x', metrics: { route: 'solver', ai_calls: 0, solver_ms: 4.5, elapsed_ms: 9.25 }, steps: ['Compute the result.'],
      notes: ['Numerical samples are not a proof.'] }, { append: (button) => buttons.push(button) }, question);
    assert.equal(buttons.find((button) => button.textContent === 'Copy exact result').attributes['aria-label'], 'Copy exact result');
    assert.equal(buttons.find((button) => button.textContent === 'Copy steps').attributes['aria-label'], 'Copy all solution steps');
    assert.equal(buttons.find((button) => button.textContent === 'Copy full solution').attributes['aria-label'], 'Copy full solution with verification and steps');
    buttons.find((button) => button.textContent === 'Copy full solution').click();
    assert.ok(app.state.copiedEvidence.includes(`Question: ${expected}`));
    assert.match(app.state.copiedEvidence, /Verification \(Symbolic check\): Checked\./);
    assert.match(app.state.copiedEvidence, /LaTeX: \\frac\{1\}\{2\}x/);
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
  assert.equal(buttons.find((button) => button.textContent === 'Copy full attempt').attributes['aria-label'], 'Copy full unresolved attempt with verification and steps');
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

test('AI success without explicit unverified metadata is rejected', async () => {
  const app = appHarness();
  const message = { request, response: result };
  const running = app.requestAi(message, 'explain');
  app.pending[0].resolve(response({ status: 'answered', text: 'Use the power rule.' }));
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

for (const body of [
  { ...result, steps: [] },
  { ...result, steps: ['x'.repeat(501)] },
  { ...result, steps: Array.from({ length: 9 }, () => 'Compute safely.') },
]) {
  test(`malformed solver steps are retryable: ${body.steps.length} entries`, async () => {
    const app = appHarness();
    const message = { request, generation: 0, loading: true };
    const running = app.solve(request, message);
    app.pending[0].resolve(response(body));
    await running;
    assert.equal(message.response, undefined);
    assert.match(message.error, /invalid response/i);
  });
}

for (const field of ['operation', 'expression']) {
  test(`mismatched solver ${field} is retryable`, async () => {
    const app = appHarness();
    const message = { request, generation: 0, loading: true };
    const running = app.solve(request, message);
    app.pending[0].resolve(response({ ...result, [field]: field === 'operation' ? 'integral' : 'sin(x)' }));
    await running;
    assert.equal(message.response, undefined);
    assert.match(message.error, /invalid response/i);
  });
}

for (const [question, field, wrong] of [
  [{ operation: 'integral', expression: 'x', lower: '0', upper: '1' }, 'lower', '-1'],
  [{ operation: 'integral', expression: 'x', lower: '0', upper: '1' }, 'upper', '2'],
  [{ operation: 'limit', expression: '1/x', target: '0', direction: '+' }, 'target', '1'],
  [{ operation: 'limit', expression: '1/x', target: '0', direction: '+' }, 'direction', '-'],
  [request, 'variable', 'y'],
]) {
  test(`solver rejects a mismatched echoed ${field} while accepting matching context`, async () => {
    const app = appHarness();
    const echoed = { variable: 'x', lower: null, upper: null, target: null, direction: null, ...question };
    const payload = { ...result, operation: question.operation, expression: question.expression, request: { ...echoed, [field]: wrong } };
    const message = { request: question, generation: 0, loading: true };
    const running = app.solve(question, message);
    app.pending[0].resolve(response(payload));
    await running;
    assert.equal(message.response, undefined);
    assert.match(message.error, /invalid response/i);
    app.retrySolve(message);
    app.pending[1].resolve(response({ ...payload, request: echoed }));
    await new Promise(setImmediate);
    assert.equal(message.response.request[field], echoed[field]);
    assert.equal(message.error, null);
  });
}

test('solver rejects a response without the echoed request', async () => {
  const app = appHarness();
  const message = { request, generation: 0, loading: true };
  const running = app.solve(request, message);
  app.pending[0].resolve(response({ ...result, request: null }));
  await running;
  assert.equal(message.response, undefined);
  assert.match(message.error, /invalid response/i);
});

test('valid unresolved response remains available for explicit fallback', async () => {
  const app = appHarness();
  const message = { request, generation: 0, loading: true };
  const running = app.solve(request, message);
  app.pending[0].resolve(response({ status: 'unresolved', result: null,
    operation: request.operation, expression: request.expression, request: result.request,
    verification: { status: 'not_checked', detail: 'The exact solver reached its time limit.' }, steps: ['Stop before returning an exact answer.'] }));
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
  app.state.messages.push({ display: 'Derivative x^2', response: { ...result, metrics: { route: 'solver', ai_calls: 0, solver_ms: 12.5, elapsed_ms: 25.75 }, steps: ['Read the function.', 'Apply the power rule.'] }, ai: { status: 'error', message: 'Provider unavailable.' }, aiAttempts: [
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
  assert.match(app.state.copiedEvidence, /Steps \(2\):\n1\. Read the function\.\n2\. Apply the power rule\./);
});

test('session evidence preserves solver failures without inventing an answer', () => {
  const app = appHarness();
  app.state.messages.push({ display: 'Derivative x^2', error: 'The request took too long. You can retry without retyping it.' });
  app.copySessionEvidence();
  assert.match(app.state.copiedEvidence, /Status: error\nSolver error: The request took too long/);
  assert.doesNotMatch(app.state.copiedEvidence, /^Result:/m);
});

test('session evidence preserves domain notes and each AI attempt outcome', () => {
  const app = appHarness();
  app.state.messages.push({ display: 'Integral 1/x', response: { ...result, result: 'log(Abs(x))', notes: ['Exclude x = 0.'], metrics: { ai_calls: 0 } }, aiAttempts: [
    { action: 'explain', status: 'answered', text: 'Respect the domain.', metrics: { model: 'test-model', ai_calls: 1, total_tokens: 20 } },
    { action: 'explain', status: 'error', message: 'AI request cancelled. Provider usage is not yet known.' },
  ] });
  app.copySessionEvidence();
  assert.match(app.state.copiedEvidence, /Notes:\n- Exclude x = 0\./);
  assert.match(app.state.copiedEvidence, /AI attempt 1: explain; answered\nAI model: test-model/);
  assert.match(app.state.copiedEvidence, /AI attempt 2: explain; error\nAI attempt detail: AI request cancelled/);
  assert.match(app.state.copiedEvidence, /General-model calls: not reported/);
  assert.match(app.state.copiedEvidence, /AI explanation \(unverified\):\nRespect the domain\./);
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
  app.pending[0].resolve(response({ status: 'answered', text: 'stale', verification: { status: 'not_checked', method: 'AI output', detail: 'Unverified.' } }));
  await old;
  assert.equal(message.aiLoading, true);
  assert.equal(message.ai.status, 'loading');
  app.pending[1].resolve(response({ status: 'answered', text: 'current', verification: { status: 'not_checked', method: 'AI output', detail: 'Unverified.' } }));
  await next;
  assert.equal(message.ai.text, 'current');
  assert.equal(message.aiLoading, false);
});
