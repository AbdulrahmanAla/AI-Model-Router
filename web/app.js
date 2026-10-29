(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const state = { messages: [], solving: false, health: null, chatFilter: '', nextMessageId: 1, solveGeneration: 0 };
  const operationCopy = {
    derivative: { hint: 'Find d/dx of an expression', help: 'Use explicit multiplication, such as 2*x.' },
    integral: { hint: 'Find an antiderivative or a definite integral', help: 'Leave bounds blank for an antiderivative, or provide both.' },
    limit: { hint: 'Evaluate a limit as x approaches a value', help: 'Use a number, pi, or oo as the target.' },
    equation: { hint: 'Find the real roots of a polynomial', help: 'Write an equation such as x^2 - 4 = 0.' }
  };

  const elements = {
    form: $('#solve-form'), operation: $('#operation'), expression: $('#expression'), lower: $('#lower'), upper: $('#upper'),
    target: $('#target'), direction: $('#direction'), integralOptions: $('#integral-options'), limitOptions: $('#limit-options'),
    operationHint: $('#operation-hint'), inputHelp: $('#input-help'), send: $('#send-button'), messages: $('#messages'), welcome: $('#welcome'), sessionStats: $('#session-stats'),
    formError: $('#form-error'),
    chatList: $('#chat-list'), chatSearchWrap: $('#chat-search-wrap'), chatSearch: $('#chat-search'), status: $('#service-status'), toast: $('#toast'),
    appShell: document.querySelector('.app-shell'), sidebar: $('#sidebar'), help: $('#help-dialog'), routeHelp: $('#route-dialog'), conversation: $('#conversation')
  };

  function setText(node, value) {
    node.textContent = value === null || value === undefined ? '' : String(value);
    return node;
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) setText(node, text);
    return node;
  }

  function showToast(message) {
    setText(elements.toast, message);
    elements.toast.hidden = false;
    delete elements.toast.dataset.formError;
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => { elements.toast.hidden = true; }, 3500);
  }

  function setServiceStatus(kind, label) {
    elements.status.classList.remove('ready', 'error');
    if (kind) elements.status.classList.add(kind);
    setText(elements.status.querySelector('span:last-child'), label);
  }

  function updateOperationFields() {
    const operation = elements.operation.value;
    elements.integralOptions.hidden = operation !== 'integral';
    elements.limitOptions.hidden = operation !== 'limit';
    setText(elements.operationHint, operationCopy[operation].hint);
    setText(elements.inputHelp, `${operationCopy[operation].help} Enter solves; Shift+Enter makes a new line; Escape cancels a running request.`);
    const placeholders = {
      derivative: 'For example: x^3*sin(x)',
      integral: 'For example: 2*x + cos(x)',
      limit: 'For example: sin(x)/x',
      equation: 'For example: x^2 - 4 = 0'
    };
    elements.expression.placeholder = placeholders[operation];
    resizeExpression();
  }

  function resizeExpression() {
    elements.expression.style.height = 'auto';
    elements.expression.style.height = `${Math.min(elements.expression.scrollHeight, 120)}px`;
  }

  function buildRequest() {
    const operation = elements.operation.value;
    const request = { operation, expression: elements.expression.value.trim(), variable: 'x' };
    request.lower = operation === 'integral' && elements.lower.value.trim() ? elements.lower.value.trim() : null;
    request.upper = operation === 'integral' && elements.upper.value.trim() ? elements.upper.value.trim() : null;
    request.target = operation === 'limit' && elements.target.value.trim() ? elements.target.value.trim() : null;
    request.direction = operation === 'limit' ? elements.direction.value : null;
    return request;
  }

  function validateRequest(request) {
    if (!request.expression) return 'Enter an expression before solving.';
    if (request.operation === 'integral' && Boolean(request.lower) !== Boolean(request.upper)) return 'Enter both integral bounds, or leave both blank.';
    if (request.operation === 'limit' && !request.target) return 'Enter the value that x approaches.';
    return '';
  }

  function clearFormError() {
    elements.formError.hidden = true;
    setText(elements.formError, '');
    [elements.expression, elements.lower, elements.upper, elements.target].forEach((field) => {
      field.removeAttribute('aria-invalid');
      field.removeAttribute('aria-describedby');
    });
    if (elements.toast.dataset.formError === 'true') {
      elements.toast.hidden = true;
      delete elements.toast.dataset.formError;
    }
  }

  function showFormError(message, fields = [elements.expression]) {
    setText(elements.formError, message);
    elements.formError.hidden = false;
    fields.forEach((field) => {
      field.setAttribute('aria-invalid', 'true');
      field.setAttribute('aria-describedby', 'form-error');
    });
  }

  function prettyOperation(operation) {
    return operation.charAt(0).toUpperCase() + operation.slice(1);
  }

  function requestTitle(request) {
    const shortExpression = request.expression.length > 42 ? `${request.expression.slice(0, 39)}...` : request.expression;
    return `${prettyOperation(request.operation)}: ${shortExpression}`;
  }

  function displayRequest(request) {
    if (request.operation === 'integral' && request.lower !== null) return `${prettyOperation(request.operation)} ${request.expression} from ${request.lower} to ${request.upper}`;
    if (request.operation === 'limit') return `Limit of ${request.expression} as x approaches ${request.target}${request.direction === 'both' ? '' : ` from the ${request.direction === '+' ? 'right' : 'left'}`}`;
    return `${prettyOperation(request.operation)} ${request.expression}`;
  }

  function resultLabel(response) {
    if (response.status === 'solved') return 'Exact result';
    if (response.status === 'unresolved') return 'Could not verify';
    return 'Solver error';
  }

  function checkLabel(status) {
    if (status === 'symbolic_check') return 'Symbolic check';
    if (status === 'numerical_evidence') return 'Numerical evidence';
    if (status === 'failed') return 'Check failed';
    return 'Not independently checked';
  }

  function verificationIcon(status) {
    if (status === 'symbolic_check' || status === 'numerical_evidence') return '✓';
    if (status === 'failed' || status === 'error') return '!';
    return '?';
  }

  function metricValue(value, suffix) {
    if (value === null || value === undefined || value === '') return 'Not reported';
    if (typeof value === 'number' && suffix) return `${value.toFixed(2)} ${suffix}`;
    return String(value);
  }

  function metricCard(label, value) {
    const card = element('div', 'metric');
    setText(card.appendChild(element('span')), label);
    setText(card.appendChild(element('strong')), value);
    return card;
  }

  function sumKnown(values) {
    if (!values.length || values.some((value) => !Number.isFinite(value))) return null;
    return values.reduce((total, value) => total + value, 0);
  }

  function combinedMetrics(message) {
    const solverMetrics = message.response && message.response.metrics ? message.response.metrics : {};
    const attempts = Array.isArray(message.aiAttempts) ? message.aiAttempts : (message.ai ? [message.ai] : []);
    const attemptMetrics = attempts.map((attempt) => attempt.metrics || {});
    const aiCalls = attempts.length
      ? sumKnown(attemptMetrics.map((metrics) => Number.isFinite(metrics.ai_calls) ? metrics.ai_calls : NaN))
      : (Number.isFinite(solverMetrics.ai_calls) ? solverMetrics.ai_calls : null);
    const totalTokens = attempts.length
      ? sumKnown(attemptMetrics.map((metrics) => Number.isFinite(metrics.total_tokens) ? metrics.total_tokens : NaN))
      : (Number.isFinite(solverMetrics.total_tokens) ? solverMetrics.total_tokens : null);
    const aiLatency = sumKnown(attemptMetrics.map((metrics) => Number.isFinite(metrics.latency_ms) ? metrics.latency_ms : (Number.isFinite(metrics.ai_latency_ms) ? metrics.ai_latency_ms : NaN)));
    const models = [...new Set(attemptMetrics.map((metrics) => metrics.model).filter(Boolean))];
    const routes = [...new Set([solverMetrics.route || 'solver', ...attempts.map((attempt) => (attempt.metrics && attempt.metrics.route) || attempt.action).filter(Boolean)])];
    const statuses = [...new Set(attempts.map((attempt) => (attempt.metrics && attempt.metrics.status) || attempt.status).filter(Boolean))];
    return { aiCalls, aiLatency, attempts: attempts.length, totalTokens, solverMetrics, models, routes, statuses };
  }

  function renderMetrics(message, details) {
    const metrics = combinedMetrics(message);
    const grid = element('div', 'route-grid');
    grid.append(metricCard('Routes', metrics.routes.join(' + ')));
    grid.append(metricCard('General-model calls', metricValue(metrics.aiCalls)));
    grid.append(metricCard('AI attempts', String(metrics.attempts)));
    grid.append(metricCard('Solver time', metricValue(metrics.solverMetrics.solver_ms, 'ms')));
    grid.append(metricCard('AI time', metricValue(metrics.aiLatency, 'ms')));
    grid.append(metricCard('Solve time', metricValue(metrics.solverMetrics.elapsed_ms, 'ms')));
    grid.append(metricCard('Model', metrics.models.length ? metrics.models.join(', ') : 'Not used'));
    grid.append(metricCard('Reported tokens', metricValue(metrics.totalTokens)));
    if (metrics.statuses.length) grid.append(metricCard('AI status', metrics.statuses.join(', ')));
    details.append(grid);
  }

  function renderSteps(response, card) {
    if (!Array.isArray(response.steps) || !response.steps.length) return;
    const details = element('details', 'solution-steps');
    details.open = true;
    details.append(element('summary', '', 'Solution steps'));
    const list = element('ol', 'step-list');
    response.steps.forEach((step) => list.append(element('li', '', step)));
    details.append(list);
    card.append(details);
  }

  async function copyText(value, successMessage) {
    if (!value) return;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
      } else {
        const helper = document.createElement('textarea');
        helper.value = value;
        helper.setAttribute('readonly', '');
        helper.style.position = 'fixed';
        helper.style.opacity = '0';
        document.body.append(helper);
        helper.select();
        const copied = document.execCommand('copy');
        helper.remove();
        if (!copied) throw new Error('Clipboard copy was rejected.');
      }
      showToast(successMessage);
    } catch (error) {
      showToast('Copy is unavailable in this browser.');
    }
  }

  function addCopyActions(response, card) {
    if (response.result !== null && response.result !== undefined) {
      const copyResult = element('button', '', 'Copy exact result');
      copyResult.type = 'button';
      copyResult.addEventListener('click', () => copyText(response.result, 'Exact result copied.'));
      card.append(copyResult);
    }
    if (Array.isArray(response.steps) && response.steps.length) {
      const copySteps = element('button', '', 'Copy steps');
      copySteps.type = 'button';
      copySteps.addEventListener('click', () => copyText(response.steps.map((step, index) => `${index + 1}. ${step}`).join('\n'), 'Solution steps copied.'));
      card.append(copySteps);
    }
    if (response.result !== null && response.result !== undefined && Array.isArray(response.steps) && response.steps.length) {
      const copyFull = element('button', '', 'Copy full solution');
      copyFull.type = 'button';
      copyFull.addEventListener('click', () => {
        const verification = response.verification && response.verification.detail ? `Verification: ${response.verification.detail}` : '';
        const steps = response.steps.map((step, index) => `${index + 1}. ${step}`).join('\n');
        copyText(`Question: ${response.expression}\nResult: ${response.result}\n${verification}\nSteps:\n${steps}`.trim(), 'Full solution copied.');
      });
      card.append(copyFull);
    }
  }

  function renderAiResponse(message, body) {
    if (!message.ai) return;
    const response = message.ai;
    const boxClass = response.status === 'answered' ? 'ai-response' : (response.status === 'loading' ? 'ai-response ai-loading' : 'ai-response error');
    const box = element('div', boxClass);
    const label = response.status === 'answered' ? 'AI text · unverified' : (response.status === 'loading' ? 'AI request in progress' : 'AI response unavailable');
    box.append(element('span', 'ai-label', label));
    box.append(element('span', 'ai-copy', response.status === 'answered' ? (response.text || 'The provider returned no explanation text.') : (response.message || 'The AI response is unavailable.')));
    body.append(box);
  }

  function renderAssistant(message) {
    const row = element('article', 'message assistant-message');
    row.setAttribute('aria-label', 'Assistant response');
    row.append(element('div', 'assistant-mark', '∑'));
    const body = element('div', 'assistant-body');
    if (message.loading) {
      const loading = element('p', 'assistant-copy', 'Computing the exact result...');
      loading.setAttribute('aria-busy', 'true');
      body.append(loading);
      const actions = element('div', 'message-actions');
      const cancel = element('button', '', 'Cancel solve');
      cancel.type = 'button';
      cancel.addEventListener('click', () => cancelSolve(message));
      actions.append(cancel);
      body.append(actions);
      row.append(body);
      return row;
    }
    if (message.error) {
      body.append(element('p', 'assistant-copy', message.error));
      const actions = element('div', 'message-actions');
      const retry = element('button', '', 'Retry solve');
      retry.type = 'button';
      retry.addEventListener('click', () => retrySolve(message));
      actions.append(retry);
      body.append(actions);
      row.append(body);
      return row;
    }
    const response = message.response || {};
    const intro = response.status === 'solved' ? 'I solved this with the exact path and recorded the check below.' : (response.notes && response.notes[0]) || 'The exact path could not safely answer this request.';
    body.append(element('p', 'assistant-copy', intro));
    const cardClass = response.status === 'solved' ? 'answer-card' : 'answer-card unresolved-card';
    const card = element('div', cardClass);
    const heading = element('div', 'answer-heading');
    heading.append(element('span', `verification-icon ${response.verification ? response.verification.status : 'not_checked'}`, verificationIcon(response.verification && response.verification.status)));
    heading.append(element('span', '', resultLabel(response)));
    heading.append(element('span', 'check-label', checkLabel(response.verification && response.verification.status)));
    const routeMetrics = combinedMetrics(message);
    const routeText = routeMetrics.aiCalls === null
      ? 'AI calls not reported'
      : `${routeMetrics.aiCalls} general-model call${routeMetrics.aiCalls === 1 ? '' : 's'}`;
    heading.append(element('span', 'route-label', routeText));
    card.append(heading);
    if (response.result !== null && response.result !== undefined) card.append(element('div', 'formula', response.result));
    if (response.verification && response.verification.detail) card.append(element('p', 'message-time', response.verification.detail));
    if (Array.isArray(response.notes) && response.notes.length) {
      const notes = element('ul', 'result-notes');
      response.notes.forEach((note) => notes.append(element('li', '', note)));
      card.append(notes);
    }
    renderSteps(response, card);
    const copyActions = element('div', 'card-actions');
    addCopyActions(response, copyActions);
    if (copyActions.childElementCount) card.append(copyActions);
    const details = element('details', 'route-details');
    details.append(element('summary', '', 'Show route details'));
    renderMetrics(message, details);
    card.append(details);
    body.append(card);
    const actions = element('div', 'message-actions');
    if (response.status === 'solved') {
      const explain = element('button', '', message.aiLoading ? 'Generating explanation...' : (message.ai && message.ai.action === 'explain' ? 'Explain again' : 'Explain this result'));
      explain.type = 'button';
      explain.disabled = Boolean(message.aiLoading);
      explain.addEventListener('click', () => requestAi(message, 'explain'));
      actions.append(explain);
      if (message.aiLoading) {
        const cancelAiButton = element('button', '', 'Cancel AI request');
        cancelAiButton.type = 'button';
        cancelAiButton.addEventListener('click', () => cancelAi(message));
        actions.append(cancelAiButton);
      }
    } else if (response.status === 'unresolved') {
      const fallback = element('button', '', message.aiLoading ? 'Asking AI...' : (message.ai && message.ai.action === 'fallback' ? 'Ask AI again' : 'Ask AI for help'));
      fallback.type = 'button';
      fallback.disabled = Boolean(message.aiLoading);
      fallback.addEventListener('click', () => requestAi(message, 'fallback'));
      actions.append(fallback);
    }
    if (message.ai && message.ai.status === 'answered') actions.append(element('span', 'message-time', `AI calls this message: ${combinedMetrics(message).aiCalls === null ? 'not reported' : combinedMetrics(message).aiCalls}`));
    body.append(actions);
    renderAiResponse(message, body);
    row.append(body);
    return row;
  }

  function renderMessages() {
    elements.messages.replaceChildren();
    elements.welcome.hidden = state.messages.length > 0;
    state.messages.forEach((message) => {
      const wrapper = element('div', 'message');
      wrapper.dataset.messageId = message.id;
      const user = element('div', 'user-message');
      user.append(element('div', 'user-bubble', message.display));
      wrapper.append(user, renderAssistant(message));
      elements.messages.append(wrapper);
    });
    renderChatList();
    renderSessionStats();
    window.requestAnimationFrame(() => { elements.conversation.scrollTop = elements.conversation.scrollHeight; });
  }

  function renderChatList() {
    elements.chatList.replaceChildren();
    const visible = state.messages.filter((message) => requestTitle(message.request).toLowerCase().includes(state.chatFilter.toLowerCase()));
    if (!visible.length) {
      elements.chatList.append(element('p', 'empty-chats', state.messages.length ? 'No matching questions.' : 'Your solved questions will appear here.'));
      return;
    }
    visible.forEach((message) => {
      const button = element('button', 'chat-row', requestTitle(message.request));
      button.type = 'button';
      button.addEventListener('click', () => {
        const target = elements.messages.querySelector(`[data-message-id="${message.id}"]`);
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      elements.chatList.append(button);
    });
  }

  function renderSessionStats() {
    const completed = state.messages.filter((message) => message.response && message.response.status === 'solved').length;
    const unresolved = state.messages.filter((message) => message.response && message.response.status === 'unresolved').length;
    const attempts = state.messages.flatMap((message) => Array.isArray(message.aiAttempts) ? message.aiAttempts : []);
    const unknownCalls = attempts.some((attempt) => !(attempt.metrics && Number.isFinite(attempt.metrics.ai_calls)));
    const knownCalls = attempts.reduce((total, attempt) => total + (attempt.metrics && Number.isFinite(attempt.metrics.ai_calls) ? attempt.metrics.ai_calls : 0), 0);
    const calls = unknownCalls ? 'model calls not reported' : `${knownCalls} model call${knownCalls === 1 ? '' : 's'}`;
    const unresolvedLabel = unresolved ? ` · ${unresolved} unresolved` : '';
    setText(elements.sessionStats, `${completed} exact solve${completed === 1 ? '' : 's'}${unresolvedLabel} · ${calls}`);
  }

  async function readResponse(response) {
    let body;
    try { body = await response.json(); } catch (error) { body = {}; }
    if (!response.ok) {
      let detail = typeof body.detail === 'string' ? body.detail : body.message;
      if (!detail && Array.isArray(body.detail)) {
        detail = body.detail.map((item) => {
          if (typeof item === 'string') return item;
          const location = Array.isArray(item.loc) ? item.loc.filter((part) => part !== 'body').join('.') : '';
          const message = item.msg || item.message || 'Invalid value.';
          return location ? `${location}: ${message}` : message;
        }).join(' ');
      }
      if (!detail && body.detail && typeof body.detail === 'object') detail = body.detail.msg || body.detail.message;
      detail = detail || `Request failed with status ${response.status}.`;
      const failure = new Error(detail);
      failure.status = response.status;
      failure.payload = body;
      throw failure;
    }
    return body;
  }

  async function fetchWithTimeout(url, options, timeoutMs, externalController) {
    const controller = externalController || new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } catch (error) {
      if (error && error.name === 'AbortError') {
        const timeout = new Error('The request took too long. You can retry without retyping it.');
        timeout.code = 'timeout';
        throw timeout;
      }
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function solve(request, message) {
    message.cancelled = false;
    message.controller = new AbortController();
    try {
      const response = await readResponse(await fetchWithTimeout('/api/solve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) }, 20000, message.controller));
      message.loading = false;
      message.response = response;
      setServiceStatus('ready', 'Solver ready');
    } catch (error) {
      message.loading = false;
      message.error = message.cancelled ? 'Solve cancelled. You can retry this question.' : (error.message || 'The solver is unavailable.');
      if (message.cancelled || error.status === 422) setServiceStatus('ready', 'Solver ready');
      else setServiceStatus('error', 'Solver unavailable');
    } finally {
      if (message.generation !== state.solveGeneration) return;
      state.solving = false;
      elements.send.disabled = false;
      renderMessages();
    }
  }

  function cancelSolve(message) {
    if (!message.loading) return;
    message.cancelled = true;
    if (message.controller) message.controller.abort();
    message.loading = false;
    message.error = 'Solve cancelled. You can retry this question.';
    state.solving = false;
    elements.send.disabled = false;
    renderMessages();
  }

  function retrySolve(message) {
    if (state.solving || !message.request) return;
    state.solving = true;
    elements.send.disabled = true;
    message.error = null;
    message.loading = true;
    renderMessages();
    solve(message.request, message);
  }

  async function requestAi(message, action) {
    if (!message.response || !message.request || message.aiLoading) return;
    message.aiLoading = true;
    message.aiCancelled = false;
    message.aiController = new AbortController();
    if (!Array.isArray(message.aiAttempts)) message.aiAttempts = [];
    const attempt = { action, status: 'loading', message: 'Contacting the configured AI provider...' };
    message.aiAttempts.push(attempt);
    message.ai = attempt;
    renderMessages();
    try {
      const response = await readResponse(await fetchWithTimeout('/api/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, request: message.request }) }, 45000, message.aiController));
      Object.assign(attempt, response, { action });
      message.ai = attempt;
    } catch (error) {
      Object.assign(attempt, { action, status: 'error', message: message.aiCancelled ? 'AI request cancelled.' : (error.message || 'The AI response is unavailable.'), metrics: error.payload && error.payload.metrics });
      message.ai = attempt;
    } finally {
      message.aiLoading = false;
      renderMessages();
    }
  }

  function cancelAi(message) {
    if (!message.aiLoading) return;
    message.aiCancelled = true;
    if (message.aiController) message.aiController.abort();
    message.aiLoading = false;
    renderMessages();
  }

  function submit(event) {
    event.preventDefault();
    if (state.solving) return;
    const request = buildRequest();
    const validationError = validateRequest(request);
    if (validationError) {
      const fields = request.operation === 'integral' ? [elements.lower, elements.upper] : request.operation === 'limit' ? [elements.target] : [elements.expression];
      showFormError(validationError, fields);
      showToast(validationError);
      elements.toast.dataset.formError = 'true';
      (fields[0] || elements.expression).focus();
      return;
    }
    clearFormError();
    state.solving = true;
    elements.send.disabled = true;
    const message = { id: String(state.nextMessageId++), generation: state.solveGeneration, request, display: displayRequest(request), loading: true };
    state.messages.push(message);
    renderMessages();
    solve(request, message);
  }

  async function checkHealth() {
    window.clearTimeout(checkHealth.timer);
    try {
      const response = await readResponse(await fetchWithTimeout('/api/health', {}, 5000));
      state.health = response;
      setServiceStatus('ready', response.ai_configured ? 'Solver ready · AI configured' : 'Solver ready');
    } catch (error) {
      state.health = null;
      setServiceStatus('error', 'Start the local server');
      checkHealth.timer = window.setTimeout(checkHealth, 5000);
    }
  }

  function resetChat() {
    state.messages.forEach((message) => {
      if (message.controller) message.controller.abort();
      if (message.aiController) message.aiController.abort();
    });
    state.solveGeneration += 1;
    state.solving = false;
    elements.send.disabled = false;
    state.messages = [];
    state.nextMessageId = 1;
    state.chatFilter = '';
    elements.chatSearch.value = '';
    elements.expression.value = '';
    elements.lower.value = '';
    elements.upper.value = '';
    elements.target.value = '';
    clearFormError();
    updateOperationFields();
    renderMessages();
    elements.expression.focus();
  }

  function applyExample(button) {
    elements.operation.value = button.dataset.operation;
    elements.expression.value = button.dataset.expression || '';
    elements.lower.value = '';
    elements.upper.value = '';
    elements.target.value = button.dataset.target || '';
    clearFormError();
    updateOperationFields();
    elements.help.close();
    elements.expression.focus();
  }

  function wireEvents() {
    elements.form.addEventListener('submit', submit);
    elements.operation.addEventListener('change', () => { updateOperationFields(); clearFormError(); });
    elements.expression.addEventListener('input', () => { resizeExpression(); clearFormError(); });
    [elements.lower, elements.upper, elements.target].forEach((field) => field.addEventListener('input', clearFormError));
    elements.expression.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); elements.form.requestSubmit(); }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      if (elements.help.open || elements.routeHelp.open) return;
      const solving = state.messages.find((message) => message.loading);
      if (solving) cancelSolve(solving);
      const aiRequest = state.messages.find((message) => message.aiLoading);
      if (aiRequest) cancelAi(aiRequest);
    });
    $('#new-chat').addEventListener('click', resetChat);
    $('#syntax-help').addEventListener('click', () => elements.help.showModal());
    $('#route-help').addEventListener('click', () => elements.routeHelp.showModal());
    $('#open-help-inline').addEventListener('click', () => elements.help.showModal());
    $('#close-help').addEventListener('click', () => elements.help.close());
    $('#close-route').addEventListener('click', () => elements.routeHelp.close());
    $('#close-sidebar').addEventListener('click', () => { elements.sidebar.classList.remove('open'); elements.appShell.classList.add('sidebar-collapsed'); });
    $('#open-sidebar').addEventListener('click', () => { elements.appShell.classList.remove('sidebar-collapsed'); elements.sidebar.classList.add('open'); });
    $('#search-toggle').addEventListener('click', () => { elements.chatSearchWrap.hidden = !elements.chatSearchWrap.hidden; if (!elements.chatSearchWrap.hidden) elements.chatSearch.focus(); });
    elements.chatSearch.addEventListener('input', () => { state.chatFilter = elements.chatSearch.value; renderChatList(); });
    document.querySelectorAll('.starter-prompt').forEach((button) => {
      button.addEventListener('click', () => applyExample(button));
    });
    document.querySelectorAll('.syntax-example').forEach((button) => {
      button.addEventListener('click', () => applyExample(button));
    });
  }

  wireEvents();
  updateOperationFields();
  checkHealth();
})();
