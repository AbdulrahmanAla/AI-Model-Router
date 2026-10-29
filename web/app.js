(() => {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const state = { messages: [], solving: false, health: null, chatFilter: '' };
  const operationCopy = {
    derivative: { hint: 'Find d/dx of an expression', help: 'Use explicit multiplication, such as 2*x.' },
    integral: { hint: 'Find an antiderivative or a definite integral', help: 'Leave bounds blank for an antiderivative, or provide both.' },
    limit: { hint: 'Evaluate a limit as x approaches a value', help: 'Use a number, pi, or infinity as the target.' },
    equation: { hint: 'Find the real roots of a polynomial', help: 'Write an equation such as x^2 - 4 = 0.' }
  };

  const elements = {
    form: $('#solve-form'), operation: $('#operation'), expression: $('#expression'), lower: $('#lower'), upper: $('#upper'),
    target: $('#target'), direction: $('#direction'), integralOptions: $('#integral-options'), limitOptions: $('#limit-options'),
    operationHint: $('#operation-hint'), inputHelp: $('#input-help'), send: $('#send-button'), messages: $('#messages'), welcome: $('#welcome'),
    chatList: $('#chat-list'), chatSearchWrap: $('#chat-search-wrap'), chatSearch: $('#chat-search'), status: $('#service-status'), toast: $('#toast'),
    sidebar: $('#sidebar'), help: $('#help-dialog')
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
    setText(elements.inputHelp, operationCopy[operation].help);
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
    request.direction = operation === 'limit' ? elements.direction.value : 'both';
    return request;
  }

  function validateRequest(request) {
    if (!request.expression) return 'Enter an expression before solving.';
    if (request.operation === 'integral' && Boolean(request.lower) !== Boolean(request.upper)) return 'Enter both integral bounds, or leave both blank.';
    if (request.operation === 'limit' && !request.target) return 'Enter the value that x approaches.';
    return '';
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
    if (response.status === 'solved') return 'Verified result';
    if (response.status === 'unresolved') return 'Could not verify';
    return 'Solver error';
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

  function combinedMetrics(message) {
    const solverMetrics = message.response && message.response.metrics ? message.response.metrics : {};
    const aiMetrics = message.ai && message.ai.metrics ? message.ai.metrics : null;
    const modelCalls = (Number.isFinite(solverMetrics.ai_calls) ? solverMetrics.ai_calls : 0) + (aiMetrics && Number.isFinite(aiMetrics.model_calls) ? aiMetrics.model_calls : 0);
    const totalTokens = solverMetrics.total_tokens !== null && solverMetrics.total_tokens !== undefined
      ? solverMetrics.total_tokens
      : (aiMetrics ? aiMetrics.total_tokens : null);
    return { modelCalls, totalTokens, solverMetrics, aiMetrics };
  }

  function renderMetrics(message, details) {
    const metrics = combinedMetrics(message);
    const grid = element('div', 'route-grid');
    grid.append(metricCard('Route', metrics.solverMetrics.route || (metrics.aiMetrics && metrics.aiMetrics.route) || 'solver'));
    grid.append(metricCard('General-model calls', String(metrics.modelCalls)));
    grid.append(metricCard('Solver time', metricValue(metrics.solverMetrics.solver_ms, 'ms')));
    grid.append(metricCard('Total time', metricValue(metrics.solverMetrics.elapsed_ms, 'ms')));
    grid.append(metricCard('Reported tokens', metricValue(metrics.totalTokens)));
    if (metrics.aiMetrics) grid.append(metricCard('AI status', metrics.aiMetrics.status || 'reported'));
    details.append(grid);
  }

  function renderAiResponse(message, body) {
    if (!message.ai) return;
    const response = message.ai;
    const box = element('div', response.status === 'answered' ? 'ai-response' : 'ai-response error');
    if (response.status === 'answered') {
      setText(box, response.text || 'The provider returned no explanation text.');
    } else {
      setText(box, response.message || 'The AI response is unavailable.');
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
      row.append(body);
      return row;
    }
    if (message.error) {
      body.append(element('p', 'assistant-copy', message.error));
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
    card.append(heading);
    if (response.result !== null && response.result !== undefined) card.append(element('div', 'formula', response.result));
    if (response.verification && response.verification.detail) card.append(element('p', 'message-time', response.verification.detail));
    if (Array.isArray(response.notes) && response.notes.length) {
      const notes = element('ul', 'result-notes');
      response.notes.forEach((note) => notes.append(element('li', '', note)));
      card.append(notes);
    }
    const details = element('details', 'route-details');
    details.append(element('summary', '', 'Show route details'));
    renderMetrics(message, details);
    card.append(details);
    body.append(card);
    const actions = element('div', 'message-actions');
    if (response.status === 'solved') {
      const explain = element('button', '', message.ai && message.ai.action === 'explain' ? 'Explain again' : 'Explain this result');
      explain.type = 'button';
      explain.addEventListener('click', () => requestAi(message, 'explain'));
      actions.append(explain);
    } else if (response.status === 'unresolved') {
      const fallback = element('button', '', message.ai && message.ai.action === 'fallback' ? 'Ask AI again' : 'Ask AI for help');
      fallback.type = 'button';
      fallback.addEventListener('click', () => requestAi(message, 'fallback'));
      actions.append(fallback);
    }
    if (message.ai && message.ai.status === 'answered') actions.append(element('span', 'message-time', `AI calls this message: ${message.ai.metrics && message.ai.metrics.model_calls !== undefined ? message.ai.metrics.model_calls : 'not reported'}`));
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
      const user = element('div', 'user-message');
      user.append(element('div', 'user-bubble', message.display));
      wrapper.append(user, renderAssistant(message));
      elements.messages.append(wrapper);
    });
    renderChatList();
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
        const target = [...elements.messages.querySelectorAll('.message')].find((node) => node.textContent.includes(message.display));
        if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      elements.chatList.append(button);
    });
  }

  async function readResponse(response) {
    let body;
    try { body = await response.json(); } catch (error) { body = {}; }
    if (!response.ok) {
      const detail = typeof body.detail === 'string' ? body.detail : (body.message || `Request failed with status ${response.status}.`);
      const failure = new Error(detail);
      failure.status = response.status;
      failure.payload = body;
      throw failure;
    }
    return body;
  }

  async function solve(request, message) {
    try {
      const response = await readResponse(await fetch('/api/solve', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request) }));
      message.loading = false;
      message.response = response;
      setServiceStatus('ready', 'Solver ready');
    } catch (error) {
      message.loading = false;
      message.error = error.message || 'The solver is unavailable.';
      setServiceStatus('error', 'Solver unavailable');
    } finally {
      state.solving = false;
      elements.send.disabled = false;
      renderMessages();
    }
  }

  async function requestAi(message, action) {
    if (!message.response || !message.request || message.aiLoading) return;
    message.aiLoading = true;
    message.ai = { action, status: 'loading', message: 'Contacting the configured AI provider...' };
    renderMessages();
    try {
      const response = await readResponse(await fetch('/api/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, request: message.request }) }));
      message.ai = { ...response, action };
    } catch (error) {
      message.ai = { action, status: 'error', message: error.message || 'The AI response is unavailable.', metrics: error.payload && error.payload.metrics };
    } finally {
      message.aiLoading = false;
      renderMessages();
    }
  }

  function submit(event) {
    event.preventDefault();
    if (state.solving) return;
    const request = buildRequest();
    const validationError = validateRequest(request);
    if (validationError) { showToast(validationError); elements.expression.focus(); return; }
    state.solving = true;
    elements.send.disabled = true;
    const message = { request, display: displayRequest(request), loading: true };
    state.messages.push(message);
    renderMessages();
    solve(request, message);
  }

  async function checkHealth() {
    try {
      const response = await readResponse(await fetch('/api/health'));
      state.health = response;
      setServiceStatus('ready', response.ai_configured ? 'Solver ready · AI configured' : 'Solver ready');
    } catch (error) {
      state.health = null;
      setServiceStatus('error', 'Start the local server');
    }
  }

  function resetChat() {
    state.messages = [];
    state.chatFilter = '';
    elements.chatSearch.value = '';
    elements.expression.value = '';
    elements.lower.value = '';
    elements.upper.value = '';
    elements.target.value = '';
    updateOperationFields();
    renderMessages();
    elements.expression.focus();
  }

  function wireEvents() {
    elements.form.addEventListener('submit', submit);
    elements.operation.addEventListener('change', updateOperationFields);
    elements.expression.addEventListener('input', resizeExpression);
    elements.expression.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); elements.form.requestSubmit(); }
    });
    $('#new-chat').addEventListener('click', resetChat);
    $('#syntax-help').addEventListener('click', () => elements.help.showModal());
    $('#open-help-inline').addEventListener('click', () => elements.help.showModal());
    $('#close-help').addEventListener('click', () => elements.help.close());
    $('#close-sidebar').addEventListener('click', () => elements.sidebar.classList.remove('open'));
    $('#open-sidebar').addEventListener('click', () => elements.sidebar.classList.add('open'));
    $('#search-toggle').addEventListener('click', () => { elements.chatSearchWrap.hidden = !elements.chatSearchWrap.hidden; if (!elements.chatSearchWrap.hidden) elements.chatSearch.focus(); });
    elements.chatSearch.addEventListener('input', () => { state.chatFilter = elements.chatSearch.value; renderChatList(); });
  }

  wireEvents();
  updateOperationFields();
  checkHealth();
})();
