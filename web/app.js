(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const state = { messages: [], solving: false, health: null, chatFilter: '', nextMessageId: 1, solveGeneration: 0, activeSolve: null, selectedMessageId: null };
  const MAX_AI_TEXT_LENGTH = 12000;
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
    setText(elements.inputHelp, `${operationCopy[operation].help} Enter solves; Shift+Enter makes a new line; / focuses the composer; Escape cancels a running request.`);
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

  function resultAriaLabel(response) {
    if (response && response.result !== null && response.result !== undefined) return `Exact result: ${response.result}`;
    return 'Exact result unavailable';
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

  function answeredAiTexts(message) {
    const texts = Array.isArray(message && message.aiAttempts)
      ? message.aiAttempts.filter((attempt) => attempt.status === 'answered' && attempt.text).map((attempt) => attempt.text)
      : [];
    if (message && message.ai && message.ai.status === 'answered' && message.ai.text && !texts.includes(message.ai.text)) texts.push(message.ai.text);
    return texts;
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

  function routeLabel(metrics) {
    if (metrics.aiCalls === 0 && metrics.routes.includes('solver')) return 'Exact local · 0 model calls';
    if (metrics.aiCalls === null) return 'AI calls not reported';
    return `${metrics.aiCalls} general-model call${metrics.aiCalls === 1 ? '' : 's'}`;
  }

  function renderSteps(response, card) {
    if (!Array.isArray(response.steps) || !response.steps.length) return;
    const details = element('details', 'solution-steps');
    details.open = true;
    const summary = element('summary', '', 'Solution steps');
    summary.setAttribute('aria-label', 'Solution steps');
    summary.append(document.createTextNode(` (${response.steps.length})`));
    details.append(summary);
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

  function addCopyActions(response, card, request, message = null) {
    if (response.result !== null && response.result !== undefined) {
      const copyResult = element('button', '', 'Copy exact result');
      copyResult.type = 'button';
      copyResult.setAttribute('aria-label', 'Copy exact result');
      copyResult.addEventListener('click', () => copyText(response.result, 'Exact result copied.'));
      card.append(copyResult);
    }
    if (Array.isArray(response.steps) && response.steps.length) {
      const copySteps = element('button', '', 'Copy steps');
      copySteps.type = 'button';
      copySteps.setAttribute('aria-label', 'Copy all solution steps');
      copySteps.addEventListener('click', () => copyText(response.steps.map((step, index) => `${index + 1}. ${step}`).join('\n'), 'Solution steps copied.'));
      card.append(copySteps);
    }
    if (Array.isArray(response.steps) && response.steps.length && ((response.result !== null && response.result !== undefined) || response.status === 'unresolved')) {
      const copyFull = element('button', '', response.status === 'unresolved' ? 'Copy full attempt' : 'Copy full solution');
      copyFull.type = 'button';
      copyFull.setAttribute('aria-label', response.status === 'unresolved' ? 'Copy full unresolved attempt with verification and steps' : 'Copy full solution with verification and steps');
      copyFull.addEventListener('click', () => {
        const verification = response.verification && response.verification.detail ? `Verification (${checkLabel(response.verification.status)}): ${response.verification.detail}` : '';
        const combined = message ? combinedMetrics(message) : null;
        const metrics = combined ? combined.solverMetrics : (response.metrics || {});
        const route = `Routes: ${combined ? combined.routes.join(' + ') : (metrics.route || 'not reported')}`;
        const calls = `General-model calls: ${combined ? (Number.isFinite(combined.aiCalls) ? combined.aiCalls : 'not reported') : (Number.isFinite(metrics.ai_calls) ? metrics.ai_calls : 'not reported')}`;
        const timing = `Timing: solver ${metricValue(metrics.solver_ms, 'ms')}; total ${metricValue(metrics.elapsed_ms, 'ms')}; AI ${metricValue(combined && combined.aiLatency, 'ms')}`;
        const aiTexts = answeredAiTexts(message).map((text) => `AI explanation (unverified):\n${text}`);
        const steps = response.steps.map((step, index) => `${index + 1}. ${step}`).join('\n');
        const notes = Array.isArray(response.notes) && response.notes.length ? `Notes:\n${response.notes.join('\n')}` : '';
        const resultLine = response.result !== null && response.result !== undefined ? `Result: ${response.result}` : `Status: ${response.status || 'unresolved'}`;
        copyText([`Question: ${displayRequest(request)}`, resultLine, verification, route, calls, timing, ...aiTexts, notes, `Steps:\n${steps}`].filter(Boolean).join('\n'), response.status === 'unresolved' ? 'Full attempt copied.' : 'Full solution copied.');
      });
      card.append(copyFull);
    }
  }

  function renderAiResponse(message, body) {
    if (!message.ai) return;
    const response = message.ai;
    const boxClass = response.status === 'answered' ? 'ai-response' : (response.status === 'loading' ? 'ai-response ai-loading' : 'ai-response error');
    const box = element('div', boxClass);
    if (response.status === 'loading') box.setAttribute('aria-busy', 'true');
    if (response.status === 'answered') box.setAttribute('aria-live', 'polite');
    const label = response.status === 'answered' ? 'AI text · unverified' : (response.status === 'loading' ? 'AI request in progress' : 'AI response unavailable');
    box.append(element('span', 'ai-label', label));
    box.append(element('span', 'ai-copy', response.status === 'answered' ? (response.text || 'The provider returned no explanation text.') : (response.message || 'The AI response is unavailable.')));
    if (response.status === 'answered' && response.text) {
      const copy = element('button', 'ai-copy-button', 'Copy AI explanation');
      copy.type = 'button';
      copy.setAttribute('aria-label', 'Copy unverified AI explanation');
      copy.addEventListener('click', () => copyText(response.text, 'AI explanation copied.'));
      box.append(copy);
    }
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
    const verificationMark = element('span', `verification-icon ${response.verification ? response.verification.status : 'not_checked'}`, verificationIcon(response.verification && response.verification.status));
    verificationMark.setAttribute('aria-hidden', 'true');
    heading.append(verificationMark);
    heading.append(element('span', '', resultLabel(response)));
    heading.append(element('span', 'check-label', checkLabel(response.verification && response.verification.status)));
    const routeMetrics = combinedMetrics(message);
    heading.append(element('span', 'route-label', routeLabel(routeMetrics)));
    card.append(heading);
    if (response.result !== null && response.result !== undefined) {
      const formula = element('div', 'formula', response.result);
      formula.setAttribute('role', 'status');
      formula.setAttribute('aria-label', resultAriaLabel(response));
      card.append(formula);
    }
    if (response.verification && response.verification.detail) card.append(element('p', 'message-time', response.verification.detail));
    if (Array.isArray(response.notes) && response.notes.length) {
      const notes = element('ul', 'result-notes');
      response.notes.forEach((note) => notes.append(element('li', '', note)));
      card.append(notes);
    }
    renderSteps(response, card);
    const copyActions = element('div', 'card-actions');
    addCopyActions(response, copyActions, message.request, message);
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
      const button = element('button', message.id === state.selectedMessageId ? 'chat-row active' : 'chat-row', requestTitle(message.request));
      button.type = 'button';
      if (message.id === state.selectedMessageId) button.setAttribute('aria-current', 'true');
      button.addEventListener('click', () => {
        closeMobileSidebar();
        state.selectedMessageId = message.id;
        renderChatList();
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

  function sessionEvidenceText() {
    if (!state.messages.length) return '';
    const lines = ['AI Math Assistant session evidence', ''];
    state.messages.forEach((message, index) => {
      const response = message.response || {};
      const metrics = combinedMetrics(message);
      lines.push(`${index + 1}. ${message.display}`);
      lines.push(`Status: ${response.status || (message.loading ? 'loading' : 'error')}`);
      if (response.result !== null && response.result !== undefined) lines.push(`Result: ${response.result}`);
      if (response.verification) {
        const verification = response.verification.detail ? `${checkLabel(response.verification.status)}: ${response.verification.detail}` : checkLabel(response.verification.status);
        lines.push(`Verification: ${verification}`);
      }
      lines.push(`Routes: ${metrics.routes.join(' + ')}`);
      lines.push(`Solver time: ${metricValue(metrics.solverMetrics.solver_ms, 'ms')}`);
      lines.push(`Total solve time: ${metricValue(metrics.solverMetrics.elapsed_ms, 'ms')}`);
      lines.push(`AI time: ${metricValue(metrics.aiLatency, 'ms')}`);
      lines.push(`General-model calls: ${Number.isFinite(metrics.aiCalls) ? metrics.aiCalls : 'not reported'}`);
      lines.push(`Reported tokens: ${Number.isFinite(metrics.totalTokens) ? metrics.totalTokens : 'not reported'}`);
      lines.push(`AI attempts: ${metrics.attempts}`);
      const aiTexts = answeredAiTexts(message).map((text) => `AI explanation (unverified):\n${text}`);
      lines.push(...aiTexts);
      const steps = Array.isArray(response.steps) ? response.steps : [];
      lines.push(`Steps (${steps.length}):`);
      steps.forEach((step, stepIndex) => lines.push(`${stepIndex + 1}. ${step}`));
      lines.push('');
    });
    return lines.join('\n').trim();
  }

  function copySessionEvidence() {
    const evidence = sessionEvidenceText();
    if (!evidence) {
      showToast('Solve a question before copying session evidence.');
      return;
    }
    copyText(evidence, 'Session evidence copied.');
  }

  function downloadSessionEvidence() {
    const evidence = sessionEvidenceText();
    if (!evidence) {
      showToast('Solve a question before downloading session evidence.');
      return;
    }
    const blob = new Blob([evidence], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'ai-math-assistant-session-evidence.txt';
    link.style.display = 'none';
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    showToast('Session evidence downloaded.');
  }

  async function readResponse(response) {
    let body;
    try {
      body = await response.json();
    } catch (error) {
      if (error && error.name === 'AbortError') throw error;
      if (response.ok) throw new Error('The server returned an invalid response. Please retry.');
      body = {};
    }
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

  async function fetchWithTimeout(url, options, timeoutMs, externalController, expectedRequest = null) {
    const controller = externalController || new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const body = await readResponse(await fetch(url, { ...options, signal: controller.signal }));
      if (!body || typeof body !== 'object' || Array.isArray(body)) {
        throw new Error('The server returned an invalid response. Please retry.');
      }
      if (url === '/api/solve') {
        const check = body.verification;
        const validCheck = check && ['symbolic_check', 'numerical_evidence', 'not_checked', 'failed'].includes(check.status) && typeof check.detail === 'string';
        const validSteps = Array.isArray(body.steps) && body.steps.length >= 1 && body.steps.length <= 8
          && body.steps.every((step) => typeof step === 'string' && step.trim().length > 0 && step.length <= 500);
        const matchesRequest = !expectedRequest || (body.operation === expectedRequest.operation && body.expression === expectedRequest.expression);
        const validResult = body.status === 'solved'
          ? typeof body.result === 'string' && body.result.trim().length > 0
          : body.status === 'unresolved' && body.result === null && check && check.status === 'not_checked';
        if (!matchesRequest || !validCheck || !validSteps || !validResult) throw new Error('The server returned an invalid response. Please retry.');
      }
      if (url === '/api/ai' && (body.status !== 'answered' || typeof body.text !== 'string' || !body.text.trim() || body.text.length > MAX_AI_TEXT_LENGTH)) {
        throw new Error('The server returned an invalid response. Please retry.');
      }
      return body;
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
    const controller = new AbortController();
    message.controller = controller;
    state.activeSolve = controller;
    const current = () => message.controller === controller && state.activeSolve === controller && message.generation === state.solveGeneration;
    try {
      const response = await fetchWithTimeout('/api/solve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) }, 20000, controller, request);
      if (!current()) return;
      message.loading = false;
      message.response = response;
      setServiceStatus('ready', 'Solver ready');
    } catch (error) {
      if (!current()) return;
      message.loading = false;
      message.error = message.cancelled ? 'Solve cancelled. You can retry this question.' : (error.message || 'The solver is unavailable.');
      if (message.cancelled || error.status === 422) setServiceStatus('ready', 'Solver ready');
      else setServiceStatus('error', 'Solver unavailable');
    } finally {
      if (!current()) return;
      state.activeSolve = null;
      state.solving = false;
      elements.send.disabled = false;
      renderMessages();
    }
  }

  function cancelSolve(message) {
    if (!message.loading) return;
    message.cancelled = true;
    if (message.controller) message.controller.abort();
    message.controller = null;
    state.activeSolve = null;
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
    const controller = new AbortController();
    const generation = state.solveGeneration;
    message.aiController = controller;
    const current = () => message.aiController === controller && generation === state.solveGeneration;
    if (!Array.isArray(message.aiAttempts)) message.aiAttempts = [];
    const attempt = { action, status: 'loading', message: 'Contacting the configured AI provider...' };
    message.aiAttempts.push(attempt);
    message.ai = attempt;
    renderMessages();
    try {
      const response = await fetchWithTimeout('/api/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, request: message.request }) }, 45000, controller);
      if (!current()) return;
      Object.assign(attempt, response, { action });
      message.ai = attempt;
    } catch (error) {
      if (!current()) return;
      Object.assign(attempt, { action, status: 'error', message: message.aiCancelled ? 'AI request cancelled.' : (error.message || 'The AI response is unavailable.'), metrics: error.payload && error.payload.metrics });
      message.ai = attempt;
    } finally {
      if (!current()) return;
      message.aiLoading = false;
      renderMessages();
    }
  }

  function cancelAi(message) {
    if (!message.aiLoading) return;
    message.aiCancelled = true;
    if (message.aiController) message.aiController.abort();
    message.aiController = null;
    Object.assign(message.ai, { status: 'error', message: 'AI request cancelled. Provider usage is not yet known.' });
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
    state.selectedMessageId = message.id;
    state.messages.push(message);
    renderMessages();
    solve(request, message);
  }

  async function checkHealth() {
    window.clearTimeout(checkHealth.timer);
    try {
      const response = await fetchWithTimeout('/api/health', {}, 5000);
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
    state.selectedMessageId = null;
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

  function closeMobileSidebar() {
    if (!elements.sidebar.classList.contains('open')) return;
    elements.sidebar.classList.remove('open');
    elements.appShell.classList.add('sidebar-collapsed');
  }

  function exampleValues(button) {
    return {
      operation: button.dataset.operation || 'derivative',
      expression: button.dataset.expression || '',
      lower: '',
      upper: '',
      target: button.dataset.target || '',
      direction: button.dataset.direction || 'both'
    };
  }

  function shouldFocusComposer(event, activeTagName) {
    return event.key === '/' && !event.ctrlKey && !event.metaKey && !event.altKey && !['INPUT', 'TEXTAREA', 'SELECT'].includes(activeTagName || '');
  }

  function shouldCloseSidebarOnEscape(event, sidebarOpen) {
    return event.key === 'Escape' && sidebarOpen;
  }

  function shouldCloseChatSearchOnEscape(event, searchOpen) {
    return event.key === 'Escape' && searchOpen;
  }

  function shouldFocusChatSearch(event, activeTagName) {
    return event.key.toLowerCase() === 'k' && (event.ctrlKey || event.metaKey) && !event.altKey && !['INPUT', 'TEXTAREA', 'SELECT'].includes(activeTagName || '');
  }

  function latestMessage(messages) {
    return Array.isArray(messages) && messages.length ? messages[messages.length - 1] : null;
  }

  function closeChatSearch() {
    if (elements.chatSearchWrap.hidden) return;
    elements.chatSearchWrap.hidden = true;
    elements.chatSearch.value = '';
    state.chatFilter = '';
    renderChatList();
    $('#search-toggle').focus();
  }

  function scrollToLatest() {
    const latest = latestMessage(state.messages);
    closeMobileSidebar();
    if (!latest) {
      showToast('Solve a question before jumping to the latest result.');
      return;
    }
    state.selectedMessageId = latest.id;
    renderChatList();
    const target = elements.messages.querySelector(`[data-message-id="${latest.id}"]`);
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function applyExample(button) {
    const values = exampleValues(button);
    elements.operation.value = values.operation;
    elements.expression.value = values.expression;
    elements.lower.value = values.lower;
    elements.upper.value = values.upper;
    elements.target.value = values.target;
    elements.direction.value = values.direction;
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
      const dialogOpen = elements.help.open || elements.routeHelp.open;
      if (!dialogOpen && shouldFocusChatSearch(event, document.activeElement && document.activeElement.tagName)) {
        event.preventDefault();
        closeMobileSidebar();
        elements.chatSearchWrap.hidden = false;
        elements.chatSearch.focus();
        return;
      }
      if (!dialogOpen && shouldFocusComposer(event, document.activeElement && document.activeElement.tagName)) {
        event.preventDefault();
        elements.expression.focus();
        return;
      }
      if (event.key !== 'Escape') return;
      if (elements.help.open || elements.routeHelp.open) return;
      if (shouldCloseSidebarOnEscape(event, elements.sidebar.classList.contains('open'))) {
        closeMobileSidebar();
        return;
      }
      if (shouldCloseChatSearchOnEscape(event, !elements.chatSearchWrap.hidden)) {
        closeChatSearch();
        return;
      }
      const solving = state.messages.find((message) => message.loading);
      if (solving) cancelSolve(solving);
      const aiRequest = state.messages.find((message) => message.aiLoading);
      if (aiRequest) cancelAi(aiRequest);
    });
    $('#new-chat').addEventListener('click', () => { closeMobileSidebar(); resetChat(); });
    $('#syntax-help').addEventListener('click', () => { closeMobileSidebar(); elements.help.showModal(); });
    $('#route-help').addEventListener('click', () => { closeMobileSidebar(); elements.routeHelp.showModal(); });
    $('#session-copy').addEventListener('click', () => { closeMobileSidebar(); copySessionEvidence(); });
    $('#session-download').addEventListener('click', () => { closeMobileSidebar(); downloadSessionEvidence(); });
    $('#latest-question').addEventListener('click', scrollToLatest);
    $('#open-help-inline').addEventListener('click', () => elements.help.showModal());
    $('#close-help').addEventListener('click', () => elements.help.close());
    $('#close-route').addEventListener('click', () => elements.routeHelp.close());
    $('#close-sidebar').addEventListener('click', () => { elements.sidebar.classList.remove('open'); elements.appShell.classList.add('sidebar-collapsed'); });
    $('#open-sidebar').addEventListener('click', () => { elements.appShell.classList.remove('sidebar-collapsed'); elements.sidebar.classList.add('open'); });
    $('#search-toggle').addEventListener('click', () => {
      if (elements.chatSearchWrap.hidden) {
        elements.chatSearchWrap.hidden = false;
        elements.chatSearch.focus();
      } else closeChatSearch();
    });
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
