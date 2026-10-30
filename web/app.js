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
  const routeCopy = {
    exact: { label: 'Exact solver', hint: 'No model call for supported math' },
    deterministic: { label: 'Deterministic router', hint: 'Solver for structured math, local AI for language' },
    jev: { label: 'Jev router', hint: 'Jev chooses solver or local AI; fallback is deterministic' },
    ai_only: { label: 'AI only', hint: 'Send the task to the configured AI provider' }
  };

  const elements = {
    form: $('#solve-form'), chatInput: $('#chat-input'), operation: $('#operation'), routeMode: $('#route-mode'), routeModeHint: $('#route-mode-hint'), routePromptField: $('#route-prompt-field'), routePrompt: $('#route-prompt'), expression: $('#expression'), lower: $('#lower'), upper: $('#upper'),
    target: $('#target'), direction: $('#direction'), integralOptions: $('#integral-options'), limitOptions: $('#limit-options'),
    operationHint: $('#operation-hint'), inputHelp: $('#input-help'), send: $('#send-button'), messages: $('#messages'), welcome: $('#welcome'), sessionStats: $('#session-stats'),
    formError: $('#form-error'), sessionSummary: $('#session-summary'), sessionChecks: $('#session-checks'),
    chatList: $('#chat-list'), chatSearchWrap: $('#chat-search-wrap'), chatSearch: $('#chat-search'), chatSearchToggle: $('#search-toggle'), status: $('#service-status'), toast: $('#toast'),
    appShell: document.querySelector('.app-shell'), sidebar: $('#sidebar'), openSidebar: $('#open-sidebar'), help: $('#help-dialog'), examples: $('#examples-dialog'), routeHelp: $('#route-dialog'), conversation: $('#conversation')
  };

  const mathFields = {};
  const mathFunctions = new Set(['sin', 'cos', 'tan', 'log', 'exp', 'sqrt', 'Abs', 'asin', 'acos', 'atan', 'sinh', 'cosh', 'tanh']);
  const latexCommandNames = {
    sin: 'sin', cos: 'cos', tan: 'tan', log: 'log', ln: 'log', exp: 'exp', sqrt: 'sqrt', Abs: 'Abs',
    asin: 'asin', acos: 'acos', atan: 'atan', sinh: 'sinh', cosh: 'cosh', tanh: 'tanh'
  };

  function selectedRouteMode() {
    const value = elements.routeMode && elements.routeMode.value;
    return routeCopy[value] ? value : 'exact';
  }

  function readLatexGroup(source, start, open = '{', close = '}') {
    if (source[start] !== open) return null;
    let depth = 0;
    for (let index = start; index < source.length; index += 1) {
      if (source[index] === open) depth += 1;
      else if (source[index] === close) {
        depth -= 1;
        if (depth === 0) return { content: source.slice(start + 1, index), end: index + 1 };
      }
    }
    return null;
  }

  function skipLatexSpace(source, start) {
    let index = start;
    while (index < source.length && /\s/.test(source[index])) index += 1;
    return index;
  }

  const MAX_LATEX_LENGTH = 4000;
  const MAX_LATEX_DEPTH = 16;

  function convertLatexSegment(source, depth = 0) {
    if (source.length > MAX_LATEX_LENGTH || depth > MAX_LATEX_DEPTH) return '__unsupported_math_input__';
    let output = '';
    let index = 0;
    while (index < source.length) {
      if (/\s/.test(source[index])) {
        output += source[index];
        index += 1;
        continue;
      }
      if (source.startsWith('\\frac', index) && !/[A-Za-z]/.test(source[index + 5] || '')) {
        let cursor = skipLatexSpace(source, index + 5);
        const numerator = readLatexGroup(source, cursor);
        if (!numerator) { output += '__unsupported_frac__'; index += 5; continue; }
        cursor = skipLatexSpace(source, numerator.end);
        const denominator = readLatexGroup(source, cursor);
        if (!denominator) { output += '__unsupported_frac__'; index = numerator.end; continue; }
        output += `((${convertLatexSegment(numerator.content, depth + 1)})/(${convertLatexSegment(denominator.content, depth + 1)}))`;
        index = denominator.end;
        continue;
      }
      if (source.startsWith('\\sqrt', index) && !/[A-Za-z]/.test(source[index + 5] || '')) {
        let cursor = skipLatexSpace(source, index + 5);
        let indexedRoot = false;
        if (source[cursor] === '[') {
          const rootIndex = readLatexGroup(source, cursor, '[', ']');
          if (rootIndex) {
            indexedRoot = true;
            cursor = skipLatexSpace(source, rootIndex.end);
          }
        }
        if (source.startsWith('\\left', cursor)) cursor = skipLatexSpace(source, cursor + 5);
        let radicand = readLatexGroup(source, cursor);
        if (!radicand && source[cursor] === '(') {
          radicand = readLatexGroup(source, cursor, '(', ')');
        }
        if (!radicand) {
          const atom = source.slice(cursor).match(/^[A-Za-z_][A-Za-z_0-9]*|^\d+(?:\.\d+)?/);
          if (atom) radicand = { content: atom[0], end: cursor + atom[0].length };
        }
        if (!radicand) { output += '__unsupported_sqrt__'; index += 5; continue; }
        output += indexedRoot ? '__unsupported_indexed_root__' : `sqrt(${convertLatexSegment(radicand.content, depth + 1)})`;
        index = radicand.end;
        continue;
      }
      if (source.startsWith('\\left', index) || source.startsWith('\\right', index)) {
        index += source[index + 1] === 'l' ? 5 : 6;
        continue;
      }
      if (source[index] === '\\') {
        const command = source.slice(index + 1).match(/^[A-Za-z]+|^./);
        if (!command) { output += '\\\\'; index += 1; continue; }
        const name = command[0];
        index += name.length + 1;
        if (['(', ')', '[', ']', '{', '}'].includes(name)) { output += name; continue; }
        if (name === 'cdot' || name === 'times') { output += '*'; continue; }
        if (name === 'pi') { output += 'pi'; continue; }
        if (name === 'infty') { output += 'oo'; continue; }
        if (name === 'le' || name === 'leq') { output += '<='; continue; }
        if (name === 'ge' || name === 'geq') { output += '>='; continue; }
        if (name === 'pm') { output += '+/-'; continue; }
        if (latexCommandNames[name]) {
          const functionName = latexCommandNames[name];
          let cursor = skipLatexSpace(source, index);
          if (source.startsWith('\\left', cursor)) cursor = skipLatexSpace(source, cursor + 5);
          if (source[cursor] === '{' || source[cursor] === '(') {
            const argument = source[cursor] === '{'
              ? readLatexGroup(source, cursor)
              : readLatexGroup(source, cursor, '(', ')');
            if (argument) {
              output += `${functionName}(${convertLatexSegment(argument.content, depth + 1)})`;
              index = argument.end;
              continue;
            }
          }
          output += functionName;
          continue;
        }
        output += `__unsupported_latex_command_${name}__`;
        continue;
      }
      if (source[index] === '{') {
        const group = readLatexGroup(source, index);
        if (!group) { output += '__unsupported_group__'; index += 1; continue; }
        output += `(${convertLatexSegment(group.content, depth + 1)})`;
        index = group.end;
        continue;
      }
      output += source[index];
      index += 1;
    }
    return output;
  }

  function addImplicitMultiplication(expression) {
    const tokens = [];
    const tokenPattern = /(?:\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z_0-9]*|==|[()+\-*/^=,])/g;
    let cursor = 0;
    let match;
    while ((match = tokenPattern.exec(expression)) !== null) {
      if (/\S/.test(expression.slice(cursor, match.index))) tokens.push(expression.slice(cursor, match.index));
      tokens.push(match[0]);
      cursor = match.index + match[0].length;
    }
    if (/\S/.test(expression.slice(cursor))) tokens.push(expression.slice(cursor));
    const canEnd = (token) => token === ')' || /^\d/.test(token) || /^[A-Za-z_]/.test(token);
    const canStart = (token) => token === '(' || /^\d/.test(token) || /^[A-Za-z_]/.test(token);
    const result = [];
    tokens.forEach((token) => {
      const previous = result[result.length - 1];
      const functionCall = previous && mathFunctions.has(previous) && token === '(';
      if (previous && canEnd(previous) && canStart(token) && !functionCall) result.push('*');
      result.push(token);
    });
    return result.join('');
  }

  function latexToExpression(latex) {
    const converted = convertLatexSegment(String(latex || '').replace(/\\!|\\,/g, ''));
    return addImplicitMultiplication(converted).trim();
  }

  function expressionToLatex(expression) {
    const source = String(expression || '').replace(/\*\*/g, '^');
    const convert = (start, stopAtClose = false) => {
      let output = '';
      let index = start;
      while (index < source.length) {
        const char = source[index];
        if (char === ')' && stopAtClose) return { output, end: index + 1 };
        if (char === '(') {
          const nested = convert(index + 1, true);
          output += `(${nested.output})`;
          index = nested.end;
          continue;
        }
        if (char === '^') {
          let cursor = index + 1;
          while (/\s/.test(source[cursor] || '') && cursor < source.length) cursor += 1;
          if (source[cursor] === '(') {
            const exponent = convert(cursor + 1, true);
            output += `^{${exponent.output}}`;
            index = exponent.end;
          } else {
            const atom = source.slice(cursor).match(/^[+-]?(?:\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z_0-9]*)/);
            if (!atom) { output += '^'; index += 1; continue; }
            output += `^{${atom[0]}}`;
            index = cursor + atom[0].length;
          }
          continue;
        }
        if (/[A-Za-z_]/.test(char)) {
          const identifier = source.slice(index).match(/^[A-Za-z_][A-Za-z_0-9]*/)[0];
          const commands = { sin: '\\sin', cos: '\\cos', tan: '\\tan', log: '\\log', exp: '\\exp', sqrt: '\\sqrt', Abs: 'Abs', pi: '\\pi', oo: '\\infty' };
          const command = commands[identifier] || identifier;
          const afterIdentifier = index + identifier.length;
          // MathQuill's square-root command takes a braced radicand. Sending
          // `\\sqrt(` leaves the opening parenthesis as an empty radicand and
          // turns the following expression into a product (for example,
          // `sqrt(x)` became `sqrt(()*x)`). Preserve the function call as one
          // grouped atom when restoring a saved question or starter example.
          if (identifier === 'sqrt' && source[afterIdentifier] === '(') {
            const radicand = convert(afterIdentifier + 1, true);
            if (radicand.end > afterIdentifier + 1 && source[radicand.end - 1] === ')') {
              const simpleRadicand = /^(?:[A-Za-z_][A-Za-z_0-9]*|\d+(?:\.\d+)?)$/.test(radicand.output);
              output += simpleRadicand
                ? `\\sqrt ${radicand.output}`
                : `\\sqrt{\\left(${radicand.output}\\right)}`;
              index = radicand.end;
              continue;
            }
          }
          output += command;
          index = afterIdentifier;
          continue;
        }
        output += char === '*' ? '\\cdot ' : char;
        index += 1;
      }
      return { output, end: index };
    };
    return convert(0).output;
  }

  function useTypedFallback() {
    ['expression', 'lower', 'upper', 'target'].forEach((name) => {
      const fallback = document.querySelector(`#${name}-typed`);
      if (!fallback) return;
      fallback.hidden = false;
      fallback.value = '';
      elements[name].hidden = true;
      elements[name] = fallback;
      const label = document.querySelector(`label[for="${name}"]`);
      if (label) label.htmlFor = fallback.id;
    });
  }

  function setupMathFields() {
    if (!window.MathQuill || typeof window.MathQuill.getInterface !== 'function') {
      useTypedFallback();
      return;
    }
    const MQ = window.MathQuill.getInterface(2);
    if (!MQ || typeof MQ.MathField !== 'function') {
      useTypedFallback();
      return;
    }
    ['expression', 'lower', 'upper', 'target'].forEach((name) => {
      const node = elements[name];
      if (!node || typeof MQ.MathField !== 'function') return;
      mathFields[name] = MQ.MathField(node, {
        restrictMismatchedBrackets: true,
        handlers: { edit: () => { resizeExpression(); clearFormError(); } }
      });
    });
  }

  function fieldValue(name) {
    const mathField = mathFields[name];
    if (mathField) {
      const latex = mathField.latex();
      if (latex && latex.trim()) return latexToExpression(latex);
    }
    return String(elements[name] && elements[name].value ? elements[name].value : '').trim();
  }

  function setFieldValue(name, value) {
    const text = value || '';
    if (mathFields[name]) mathFields[name].latex(expressionToLatex(text));
    else if (elements[name]) elements[name].value = text;
  }

  function focusField(name) {
    const mathField = mathFields[name];
    if (mathField) mathField.focus();
    else if (elements[name] && typeof elements[name].focus === 'function') elements[name].focus();
  }

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
    const routeMode = selectedRouteMode();
    elements.integralOptions.hidden = operation !== 'integral';
    elements.limitOptions.hidden = operation !== 'limit';
    if (elements.routePromptField) elements.routePromptField.hidden = routeMode === 'exact';
    setText(elements.operationHint, operationCopy[operation].hint);
    if (elements.routeModeHint) setText(elements.routeModeHint, (routeCopy[routeMode] || routeCopy.exact).hint);
    const multiplicationHelp = mathFields.expression ? ' Visual entry accepts implicit multiplication such as 2x.' : ' Use explicit multiplication, such as 2*x.';
    if (elements.chatInput) {
      setText(elements.inputHelp, 'Ask a math question or type anything you want help with. Enter sends; Shift+Enter adds a line; Escape cancels a running request.');
    } else {
      setText(elements.inputHelp, `${operationCopy[operation].help}${multiplicationHelp} Enter solves; Shift+Enter makes a new line; / focuses the composer; Escape cancels a running request.`);
    }
    const placeholders = {
      derivative: 'For example: x^3*sin(x)',
      integral: 'For example: 2*x + cos(x)',
      limit: 'For example: sin(x)/x',
      equation: 'For example: x^2 - 4 = 0'
    };
    if ('placeholder' in elements.expression) elements.expression.placeholder = placeholders[operation];
    elements.expression.dataset.placeholder = placeholders[operation];
    resizeExpression();
  }

  function resizeExpression() {
    if (mathFields.expression) return;
    elements.expression.style.height = 'auto';
    elements.expression.style.height = `${Math.min(elements.expression.scrollHeight, 120)}px`;
  }

  function buildRequest() {
    const operation = elements.operation.value;
    const request = { operation, expression: fieldValue('expression'), variable: 'x' };
    const lower = fieldValue('lower');
    const upper = fieldValue('upper');
    const target = fieldValue('target');
    request.lower = operation === 'integral' && lower ? lower : null;
    request.upper = operation === 'integral' && upper ? upper : null;
    request.target = operation === 'limit' && target ? target : null;
    request.direction = operation === 'limit' ? elements.direction.value : null;
    return request;
  }

  // Convert the small set of natural language forms that can be proven safe
  // into the existing structured solver request. Everything else stays a
  // plain prompt and follows the configured language route.
  function freeformRequest(text) {
    const source = String(text || '').trim().replace(/[?؟]+$/u, '').trim();
    if (!source) return { request: null, prompt: '' };
    const clean = (value) => String(value || '')
      .trim()
      .replace(/^(?:of|for|with)\s+/i, '')
      .replace(/\s+(?:with\s+respect\s+to|respecting)\s+x\s*$/i, '')
      .replace(/[.,;:]$/u, '')
      .trim();
    const bounded = (value) => {
      const expression = clean(value);
      if (!expression || expression.length > 400) return null;
      // Keep the backend grammar as the authority. This check only prevents
      // prose fragments from being mistaken for exact math.
      if (!/[0-9xX]/.test(expression)) return null;
      if (/[\n\r]/.test(expression)) return null;
      return expression;
    };
    let match = source.match(/^(?:please\s+)?(?:(?:what\s+is|calculate|compute|find)\s+)?(?:the\s+)?(?:differentiate|derivative\s+of|find\s+the\s+derivative\s+of|d\s*\/\s*d\s*x)\s*(?:of\s+)?(.+)$/i);
    if (match) {
      const expression = bounded(match[1]);
      if (expression) return { request: { operation: 'derivative', expression, variable: 'x', lower: null, upper: null, target: null, direction: null }, prompt: '' };
    }
    match = source.match(/^(?:please\s+)?(?:(?:what\s+is|calculate|compute|find)\s+)?(?:integrate|integral\s+of|find\s+the\s+integral\s+of)\s*(?:of\s+)?(.+)$/i);
    if (match) {
      const expression = bounded(match[1]);
      if (expression) return { request: { operation: 'integral', expression, variable: 'x', lower: null, upper: null, target: null, direction: null }, prompt: '' };
    }
    match = source.match(/^(?:please\s+)?(?:find\s+the\s+)?limit\s+(?:of\s+)?(.+?)\s+(?:as\s+)?x\s*(?:approaches|->|→)\s*([^\s,]+)(?:\s+from\s+(?:the\s+)?(right|left))?$/i);
    if (match) {
      const expression = bounded(match[1]);
      const target = clean(match[2]);
      if (expression && target) return { request: { operation: 'limit', expression, variable: 'x', lower: null, upper: null, target, direction: match[3] ? (match[3].toLowerCase() === 'right' ? '+' : '-') : 'both' }, prompt: '' };
    }
    match = source.match(/^(?:please\s+)?(?:solve|find\s+the\s+roots?\s+of)\s+(.+)$/i);
    if (match && /=/.test(match[1])) {
      const expression = bounded(match[1]);
      if (expression) return { request: { operation: 'equation', expression, variable: 'x', lower: null, upper: null, target: null, direction: null }, prompt: '' };
    }
    if (/=/.test(source) && /^[0-9xX+*/^().\s=\-]+$/.test(source)) {
      return { request: { operation: 'equation', expression: source, variable: 'x', lower: null, upper: null, target: null, direction: null }, prompt: '' };
    }
    return { request: null, prompt: source };
  }

  function buildRoutePayload() {
    if (elements.chatInput && String(elements.chatInput.value || '').trim()) {
      const parsed = freeformRequest(elements.chatInput.value);
      return { mode: parsed.request ? 'deterministic' : 'deterministic', request: parsed.request, prompt: parsed.prompt };
    }
    const mode = selectedRouteMode();
    const request = buildRequest();
    const prompt = elements.routePrompt ? String(elements.routePrompt.value || '').trim() : '';
    return { mode, request, prompt };
  }

  function validateRequest(request) {
    if (!request.expression) return { message: 'Enter an expression before solving.', fields: ['expression'] };
    if (request.expression.length > 400 || ['lower', 'upper', 'target'].some((name) => request[name] && request[name].length > 100)) {
      return { message: 'This formula is too long. Shorten it and try again.', fields: ['expression'] };
    }
    if (request.expression.includes('__unsupported_') || ['lower', 'upper', 'target'].some((name) => request[name] && request[name].includes('__unsupported_'))) {
      return { message: 'That visual math symbol is not supported yet. Use the listed functions and symbols, or enter a typed formula.', fields: ['expression'] };
    }
    if (request.operation === 'integral' && Boolean(request.lower) !== Boolean(request.upper)) return {
      message: 'Enter both integral bounds, or leave both blank.', fields: [request.lower ? 'upper' : 'lower']
    };
    if (request.operation === 'limit' && !request.target) return { message: 'Enter the value that x approaches.', fields: ['target'] };
    return null;
  }

  function validateRoutePayload(payload) {
    const mode = payload.mode || 'exact';
    if (mode === 'exact') return validateRequest(payload.request);
    if (!['deterministic', 'jev', 'ai_only'].includes(mode)) return { message: 'Choose a supported route.', fields: [] };
    const prompt = String(payload.prompt || '').trim();
    if (prompt.length > 2000) return { message: 'That language question is too long. Shorten it and try again.', fields: ['routePrompt'] };
    const requestError = payload.request && payload.request.expression ? validateRequest(payload.request) : null;
    if (requestError) return requestError;
    if (!(payload.request && payload.request.expression) && !prompt) return { message: 'Enter an expression or a language question before sending.', fields: ['expression', 'routePrompt'] };
    return null;
  }

  function clearFormError() {
    elements.formError.hidden = true;
    setText(elements.formError, '');
    [elements.expression, elements.lower, elements.upper, elements.target].forEach((field) => {
      field.removeAttribute('aria-invalid');
      field.removeAttribute('aria-describedby');
    });
    elements.expression.setAttribute('aria-describedby', 'input-help');
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
      field.setAttribute('aria-describedby', field === elements.expression ? 'input-help form-error' : 'form-error');
    });
  }

  function prettyOperation(operation) {
    return operation.charAt(0).toUpperCase() + operation.slice(1);
  }

  function requestTitle(request) {
    if (!request || typeof request !== 'object') return 'Language question';
    const shortExpression = request.expression.length > 42 ? `${request.expression.slice(0, 39)}...` : request.expression;
    return `${prettyOperation(request.operation)}: ${shortExpression}`;
  }

  function displayRequest(request) {
    if (!request || typeof request !== 'object') return 'Language question';
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
    const routedAiAttempt = !attempts.length && solverMetrics.route && solverMetrics.route !== 'solver' && Number.isFinite(solverMetrics.ai_calls) && solverMetrics.ai_calls > 0 ? 1 : 0;
    const aiCalls = attempts.length
      ? sumKnown(attemptMetrics.map((metrics) => Number.isFinite(metrics.ai_calls) ? metrics.ai_calls : NaN))
      : (Number.isFinite(solverMetrics.ai_calls) ? solverMetrics.ai_calls : null);
    const totalTokens = attempts.length
      ? sumKnown(attemptMetrics.map((metrics) => Number.isFinite(metrics.total_tokens) ? metrics.total_tokens : NaN))
      : (Number.isFinite(solverMetrics.total_tokens) ? solverMetrics.total_tokens : null);
    const aiLatency = sumKnown(attemptMetrics.map((metrics) => Number.isFinite(metrics.latency_ms) ? metrics.latency_ms : (Number.isFinite(metrics.ai_latency_ms) ? metrics.ai_latency_ms : NaN)));
    const models = [...new Set(attemptMetrics.map((metrics) => metrics.model).filter(Boolean))];
    const routes = [...new Set([solverMetrics.route || (message.routeMode === 'exact' ? 'solver' : message.routeMode) || 'solver', ...attempts.map((attempt) => (attempt.metrics && attempt.metrics.route) || attempt.action).filter(Boolean)])];
    const statuses = [...new Set(attempts.map((attempt) => (attempt.metrics && attempt.metrics.status) || attempt.status).filter(Boolean))];
    return { aiCalls, aiLatency, attempts: attempts.length || routedAiAttempt, totalTokens, solverMetrics, models, routes, statuses };
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
    if (metrics.solverMetrics.source) grid.append(metricCard('Route source', metrics.solverMetrics.source));
    if (metrics.solverMetrics.choice) grid.append(metricCard('Route choice', metrics.solverMetrics.choice));
    if (metrics.solverMetrics.reason) grid.append(metricCard('Route note', metrics.solverMetrics.reason));
    grid.append(metricCard('General-model calls', metricValue(metrics.aiCalls)));
    grid.append(metricCard('AI attempts', String(metrics.attempts)));
    grid.append(metricCard('Solver time', metricValue(metrics.solverMetrics.solver_ms, 'ms')));
    grid.append(metricCard('AI time', metricValue(metrics.aiLatency, 'ms')));
    grid.append(metricCard('Solve time', metricValue(metrics.solverMetrics.elapsed_ms, 'ms')));
    const modelLabel = metrics.models.length ? metrics.models.join(', ')
      : (metrics.attempts && metrics.aiCalls !== 0 ? 'Not reported' : 'Not used');
    grid.append(metricCard('Model', modelLabel));
    grid.append(metricCard('Reported tokens', metricValue(metrics.totalTokens)));
    if (metrics.statuses.length) grid.append(metricCard('AI status', metrics.statuses.join(', ')));
    details.append(grid);
  }

  function routeLabel(metrics) {
    if (metrics.aiCalls === 0 && metrics.routes.includes('solver')) return 'Exact local · 0 model calls';
    if (metrics.aiCalls === null) return 'AI calls not reported';
    return `${metrics.aiCalls} general-model call${metrics.aiCalls === 1 ? '' : 's'}`;
  }

  function renderSteps(response, card, message) {
    if (!Array.isArray(response.steps) || !response.steps.length) return;
    const details = element('details', 'solution-steps');
    details.open = message.stepsExpanded !== false;
    details.addEventListener('toggle', () => { message.stepsExpanded = details.open; });
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
    if (request && typeof request === 'object') {
      const copyRequest = element('button', '', 'Copy request JSON');
      copyRequest.type = 'button';
      copyRequest.setAttribute('aria-label', 'Copy structured request JSON');
      copyRequest.addEventListener('click', () => copyText(JSON.stringify(request), 'Structured request copied.'));
      card.append(copyRequest);
    }
    if (response.result !== null && response.result !== undefined) {
      const copyResult = element('button', '', 'Copy exact result');
      copyResult.type = 'button';
      copyResult.setAttribute('aria-label', 'Copy exact result');
      copyResult.addEventListener('click', () => copyText(response.result, 'Exact result copied.'));
      card.append(copyResult);
      if (typeof response.latex === 'string' && response.latex.trim() && response.latex !== response.result) {
        const copyLatex = element('button', '', 'Copy LaTeX');
        copyLatex.type = 'button';
        copyLatex.setAttribute('aria-label', 'Copy exact result as LaTeX');
        copyLatex.addEventListener('click', () => copyText(response.latex, 'LaTeX result copied.'));
        card.append(copyLatex);
      }
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
        const latexLine = response.latex ? `LaTeX: ${response.latex}` : '';
        copyText([`Question: ${displayRequest(request)}`, resultLine, latexLine, verification, route, calls, timing, ...aiTexts, notes, `Steps:\n${steps}`].filter(Boolean).join('\n'), response.status === 'unresolved' ? 'Full attempt copied.' : 'Full solution copied.');
      });
      card.append(copyFull);
    }
  }

  function aiResponseBox(response, announce, attemptNumber = null) {
    const boxClass = response.status === 'answered' ? 'ai-response' : (response.status === 'loading' ? 'ai-response ai-loading' : 'ai-response error');
    const box = element('div', boxClass);
    if (response.status === 'loading') box.setAttribute('aria-busy', 'true');
    if (response.status === 'answered' && announce) box.setAttribute('aria-live', 'polite');
    const label = response.status === 'answered' ? 'AI text · unverified' : (response.status === 'loading' ? 'AI request in progress' : 'AI response unavailable');
    box.append(element('span', 'ai-label', attemptNumber === null ? label : `Attempt ${attemptNumber} · ${label}`));
    box.append(element('span', 'ai-copy', response.status === 'answered' ? (response.text || 'The provider returned no explanation text.') : (response.message || 'The AI response is unavailable.')));
    if (response.status === 'answered' && response.text) {
      const copy = element('button', 'ai-copy-button', 'Copy AI explanation');
      copy.type = 'button';
      copy.setAttribute('aria-label', attemptNumber === null ? 'Copy unverified AI explanation' : `Copy unverified AI explanation from attempt ${attemptNumber}`);
      copy.addEventListener('click', () => copyText(response.text, 'AI explanation copied.'));
      box.append(copy);
    }
    return box;
  }

  function renderAiResponse(message, body) {
    if (!message.ai) return;
    body.append(aiResponseBox(message.ai, true));
    const earlier = Array.isArray(message.aiAttempts) ? message.aiAttempts.slice(0, -1) : [];
    if (!earlier.length) return;
    const history = element('details', 'ai-history');
    history.open = message.aiHistoryExpanded === true;
    history.addEventListener('toggle', () => { message.aiHistoryExpanded = history.open; });
    history.append(element('summary', '', `Earlier AI attempts (${earlier.length})`));
    earlier.forEach((attempt, index) => history.append(aiResponseBox(attempt, false, index + 1)));
    body.append(history);
  }

  function renderAssistant(message) {
    const row = element('article', 'message assistant-message');
    row.setAttribute('aria-label', 'Assistant response');
    const assistantMark = element('div', 'assistant-mark', '🤖');
    assistantMark.setAttribute('aria-label', 'AI Math Assistant');
    assistantMark.setAttribute('title', 'AI Math Assistant');
    row.append(assistantMark);
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
      retry.addEventListener('click', () => (message.routeMode && message.routeMode !== 'exact' ? retryRoute(message) : retrySolve(message)));
      actions.append(retry);
      if (message.request) actions.append(editQuestionButton(message.request));
      body.append(actions);
      row.append(body);
      return row;
    }
    const response = message.response || {};
    if (response.status === 'answered' && typeof response.text === 'string') {
      const text = element('p', 'assistant-copy', response.text || 'The provider returned no explanation text.');
      text.setAttribute('aria-live', 'polite');
      body.append(text);
      const details = element('details', 'route-details');
      details.open = message.routeExpanded === true;
      details.addEventListener('toggle', () => { message.routeExpanded = details.open; });
      details.append(element('summary', '', 'Response details'));
      details.append(aiResponseBox(response, false));
      renderMetrics(message, details);
      body.append(details);
      if (message.request) body.append(editQuestionButton(message.request));
      row.append(body);
      return row;
    }
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
      if (typeof response.latex === 'string') formula.dataset.latex = response.latex;
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
    renderSteps(response, card, message);
    const copyActions = element('div', 'card-actions');
    addCopyActions(response, copyActions, message.request, message);
    if (copyActions.childElementCount) card.append(copyActions);
    const details = element('details', 'route-details');
    details.open = message.routeExpanded === true;
    details.addEventListener('toggle', () => { message.routeExpanded = details.open; });
    details.append(element('summary', '', 'Show route details'));
    renderMetrics(message, details);
    card.append(details);
    body.append(card);
    const actions = element('div', 'message-actions');
    if (message.request) actions.append(editQuestionButton(message.request));
    if (response.status === 'solved') {
      const explain = element('button', '', message.aiLoading ? 'Generating explanation...' : (message.ai && message.ai.action === 'explain' ? 'Explain again' : 'Explain this result'));
      explain.type = 'button';
      explain.disabled = Boolean(message.aiLoading);
      explain.addEventListener('click', () => requestAi(message, 'explain'));
      actions.append(explain);
    } else if (response.status === 'unresolved') {
      const fallback = element('button', '', message.aiLoading ? 'Asking AI...' : (message.ai && message.ai.action === 'fallback' ? 'Ask AI again' : 'Ask AI for help'));
      fallback.type = 'button';
      fallback.disabled = Boolean(message.aiLoading);
      fallback.addEventListener('click', () => requestAi(message, 'fallback'));
      actions.append(fallback);
    }
    if (message.aiLoading) {
      const cancelAiButton = element('button', '', 'Cancel AI request');
      cancelAiButton.type = 'button';
      cancelAiButton.addEventListener('click', () => cancelAi(message));
      actions.append(cancelAiButton);
    }
    if (message.ai && message.ai.status === 'answered') actions.append(element('span', 'message-time', `AI calls this message: ${combinedMetrics(message).aiCalls === null ? 'not reported' : combinedMetrics(message).aiCalls}`));
    body.append(actions);
    renderAiResponse(message, body);
    row.append(body);
    return row;
  }

  function supportedResultLatex(latex) {
    if (!latex || latex.length > MAX_LATEX_LENGTH || /\\sqrt\s*\[/.test(latex)) return false;
    const commands = new Set(['frac', 'sqrt', 'left', 'right', 'sin', 'cos', 'tan', 'log', 'exp', 'sinh', 'cosh', 'tanh', 'pi', 'infty', 'cdot', ',', '!', ';', ':', '{', '}']);
    let supported = true;
    const remainder = latex.replace(/\\([A-Za-z]+|.)/g, (_match, command) => {
      if (!commands.has(command)) supported = false;
      return '';
    });
    if (!supported || /[^0-9xe+\-*/^{}()[\]|.,\s]/.test(remainder)) return false;
    let depth = 0;
    for (const character of remainder) {
      if (character === '{' && ++depth > MAX_LATEX_DEPTH) return false;
      if (character === '}' && --depth < 0) return false;
    }
    return depth === 0;
  }

  function typesetResults() {
    let MQ;
    try { MQ = window.MathQuill && window.MathQuill.getInterface(2); } catch (_) { return; }
    if (!MQ || typeof MQ.StaticMath !== 'function') return;
    elements.messages.querySelectorAll('.formula').forEach((formula) => {
      const latex = formula.dataset.latex;
      if (!supportedResultLatex(latex)) return;
      const original = formula.textContent;
      try {
        const visual = element('span', 'formula-math');
        visual.setAttribute('aria-hidden', 'true');
        const math = MQ.StaticMath(visual);
        math.latex(latex);
        formula.replaceChildren(element('span', 'sr-only', original), visual);
        math.reflow();
      } catch (_) {
        formula.replaceChildren(document.createTextNode(original));
      }
    });
  }

  function renderMessages(scrollToLatest = false, revealMessageId = null) {
    const previousScrollTop = elements.conversation.scrollTop;
    const followLatest = scrollToLatest || elements.conversation.scrollHeight
      - elements.conversation.clientHeight - previousScrollTop <= 48;
    elements.messages.replaceChildren();
    elements.welcome.hidden = state.messages.length > 0;
    let revealTarget = null;
    state.messages.forEach((message) => {
      const wrapper = element('div', 'message');
      wrapper.dataset.messageId = message.id;
      if (message.id === revealMessageId) revealTarget = wrapper;
      const user = element('div', 'user-message');
      user.append(element('div', 'user-bubble', message.display));
      wrapper.append(user, renderAssistant(message));
      elements.messages.append(wrapper);
    });
    typesetResults();
    renderChatList();
    renderSessionStats();
    if (followLatest && revealTarget) {
      const top = revealTarget.getBoundingClientRect().top - elements.conversation.getBoundingClientRect().top
        + elements.conversation.scrollTop - 18;
      elements.conversation.scrollTop = Math.max(0, top);
    } else elements.conversation.scrollTop = followLatest ? elements.conversation.scrollHeight : previousScrollTop;
  }

  function renderChatList() {
    elements.chatList.replaceChildren();
    const visible = state.messages.filter((message) => (message.display || requestTitle(message.request)).toLowerCase().includes(state.chatFilter.toLowerCase()));
    if (!visible.length) {
      elements.chatList.append(element('p', 'empty-chats', state.messages.length ? 'No matching questions.' : 'Your solved questions will appear here.'));
      return;
    }
    visible.forEach((message) => {
      const button = element('button', message.id === state.selectedMessageId ? 'chat-row active' : 'chat-row', message.display || requestTitle(message.request));
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

  function sessionSummary() {
    const summary = { solved: 0, unresolved: 0, failed: 0, pending: 0,
      checks: { symbolic_check: 0, numerical_evidence: 0, not_checked: 0, failed: 0 } };
    state.messages.forEach((message) => {
      if (message.loading) summary.pending += 1;
      else if (message.response && message.response.status === 'solved') {
        summary.solved += 1;
        const status = message.response.verification && message.response.verification.status;
        summary.checks[Object.hasOwn(summary.checks, status) ? status : 'not_checked'] += 1;
      } else if (message.response && message.response.status === 'unresolved') summary.unresolved += 1;
      else if (message.response && message.response.status === 'answered') {
        const status = message.response.verification && message.response.verification.status;
        summary.checks[Object.hasOwn(summary.checks, status) ? status : 'not_checked'] += 1;
      } else summary.failed += 1;
    });
    const metrics = state.messages.map(combinedMetrics);
    const providerMetrics = metrics.filter((item) => item.attempts > 0);
    summary.calls = providerMetrics.length ? sumKnown(providerMetrics.map((item) => item.aiCalls)) : 0;
    summary.attempts = metrics.reduce((total, item) => total + item.attempts, 0);
    summary.tokens = sumKnown(providerMetrics.map((item) => item.totalTokens));
    return summary;
  }

  function sessionCheckSummary(summary) {
    return `Solved-result checks: ${summary.checks.symbolic_check} symbolic; ${summary.checks.numerical_evidence} numerical; ${summary.checks.not_checked} not independently checked; ${summary.checks.failed} failed`;
  }

  function renderSessionStats() {
    const summary = sessionSummary();
    const calls = summary.calls === null ? 'model calls not reported' : `${summary.calls} model call${summary.calls === 1 ? '' : 's'}`;
    const other = [summary.unresolved ? `${summary.unresolved} unresolved` : '', summary.failed ? `${summary.failed} failed` : '', summary.pending ? `${summary.pending} pending` : ''].filter(Boolean);
    setText(elements.sessionStats, [`${summary.solved} exact solve${summary.solved === 1 ? '' : 's'}`, ...other, calls].join(' · '));
    elements.sessionSummary.replaceChildren(
      metricCard('Solved by solver', String(summary.solved)), metricCard('Unresolved', String(summary.unresolved)),
      metricCard('Solver errors', String(summary.failed)), metricCard('AI attempts', String(summary.attempts)),
      metricCard('General-model calls', metricValue(summary.calls)), metricCard('Reported AI tokens', metricValue(summary.tokens))
    );
    setText(elements.sessionChecks, `Pending requests: ${summary.pending}. ${sessionCheckSummary(summary)}`);
  }

  function sessionEvidenceText() {
    if (!state.messages.length) return '';
    const summary = sessionSummary();
    const lines = ['AI Math Assistant session evidence', '',
      `Session outcomes: ${summary.solved} solved; ${summary.unresolved} unresolved; ${summary.failed} failed; ${summary.pending} pending`,
      sessionCheckSummary(summary),
      `Session AI attempts: ${summary.attempts}`,
      `Session general-model calls: ${summary.calls === null ? 'not reported' : summary.calls}`,
      `Session reported tokens: ${summary.tokens === null ? 'not reported' : summary.tokens}`,
      'Session activity only; not a benchmark or an AI comparison. Energy and FLOPs are not measured.', ''];
    state.messages.forEach((message, index) => {
      const response = message.response || {};
      const metrics = combinedMetrics(message);
      lines.push(`${index + 1}. ${message.display}`);
      lines.push(`Status: ${response.status || (message.loading ? 'loading' : 'error')}`);
      if (message.error) lines.push(`Solver error: ${message.error}`);
      if (response.result !== null && response.result !== undefined) lines.push(`Result: ${response.result}`);
      if (Array.isArray(response.notes) && response.notes.length) {
        lines.push('Notes:');
        response.notes.forEach((note) => lines.push(`- ${note}`));
      }
      if (response.verification) {
        const verification = response.verification.detail ? `${checkLabel(response.verification.status)}: ${response.verification.detail}` : checkLabel(response.verification.status);
        lines.push(`Verification: ${verification}`);
      }
      lines.push(`Routes: ${metrics.routes.join(' + ')}`);
      if (metrics.solverMetrics.source) lines.push(`Route source: ${metrics.solverMetrics.source}`);
      if (metrics.solverMetrics.choice) lines.push(`Route choice: ${metrics.solverMetrics.choice}`);
      if (metrics.solverMetrics.reason) lines.push(`Route note: ${metrics.solverMetrics.reason}`);
      lines.push(`Solver time: ${metricValue(metrics.solverMetrics.solver_ms, 'ms')}`);
      lines.push(`Total solve time: ${metricValue(metrics.solverMetrics.elapsed_ms, 'ms')}`);
      lines.push(`AI time: ${metricValue(metrics.aiLatency, 'ms')}`);
      lines.push(`General-model calls: ${Number.isFinite(metrics.aiCalls) ? metrics.aiCalls : 'not reported'}`);
      lines.push(`Reported tokens: ${Number.isFinite(metrics.totalTokens) ? metrics.totalTokens : 'not reported'}`);
      lines.push(`AI attempts: ${metrics.attempts}`);
      const attempts = Array.isArray(message.aiAttempts) ? message.aiAttempts : (message.ai ? [message.ai] : []);
      attempts.forEach((attempt, attemptIndex) => {
        lines.push(`AI attempt ${attemptIndex + 1}: ${attempt.action || 'AI'}; ${attempt.status || 'not reported'}`);
        if (attempt.message) lines.push(`AI attempt detail: ${attempt.message}`);
        if (attempt.metrics && attempt.metrics.model) lines.push(`AI model: ${attempt.metrics.model}`);
      });
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
        const echoed = body.request;
        const matchesRequest = !expectedRequest || (
          body.operation === expectedRequest.operation && body.expression === expectedRequest.expression
          && echoed && typeof echoed === 'object' && !Array.isArray(echoed)
          && ['operation', 'expression', 'lower', 'upper', 'target', 'direction'].every((field) =>
            (echoed[field] ?? null) === (expectedRequest[field] ?? null))
          && echoed.variable === (expectedRequest.variable || 'x')
        );
        const validResult = body.status === 'solved'
          ? typeof body.result === 'string' && body.result.trim().length > 0
          : body.status === 'unresolved' && body.result === null && check && check.status === 'not_checked';
        if (!matchesRequest || !validCheck || !validSteps || !validResult) throw new Error('The server returned an invalid response. Please retry.');
      }
      if (url === '/api/route') {
        const validStatus = ['routed', 'refused'].includes(body.status);
        const validRouting = body.routing && typeof body.routing === 'object' && !Array.isArray(body.routing);
        const validAnswer = body.answer === null || (body.answer && typeof body.answer === 'object' && !Array.isArray(body.answer));
        if (!validStatus || !validRouting || !validAnswer) throw new Error('The server returned an invalid route response. Please retry.');
      }
      const validAiVerification = body.verification
        && body.verification.status === 'not_checked'
        && typeof body.verification.method === 'string'
        && typeof body.verification.detail === 'string';
      if (url === '/api/ai' && (body.status !== 'answered' || typeof body.text !== 'string' || !body.text.trim() || body.text.length > MAX_AI_TEXT_LENGTH || !validAiVerification)) {
        throw new Error('The server returned an invalid response. Please retry.');
      }
      if (url === '/api/health' && (body.status !== 'ok' || typeof body.ai_configured !== 'boolean')) {
        throw new Error('The server returned an invalid health response.');
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
      const ownsRequest = current();
      if (state.activeSolve === controller) {
        state.activeSolve = null;
        state.solving = false;
        elements.send.disabled = false;
      }
      if (ownsRequest) renderMessages(false, message.id);
    }
  }

  async function route(payload, message) {
    message.cancelled = false;
    const controller = new AbortController();
    message.controller = controller;
    state.activeSolve = controller;
    const current = () => message.controller === controller && state.activeSolve === controller && message.generation === state.solveGeneration;
    try {
      const body = { mode: payload.mode };
      if (payload.request && payload.request.expression) body.request = payload.request;
      else body.prompt = payload.prompt;
      const response = await fetchWithTimeout('/api/route', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }, 45000, controller);
      if (!current()) return;
      message.loading = false;
      const answer = response.answer && typeof response.answer === 'object' ? response.answer : {};
      const routeMetrics = { ...(answer.metrics || {}), ...(response.routing || {}), route: (response.routing && (response.routing.choice || response.routing.source)) || (answer.metrics && answer.metrics.route) || payload.mode };
      message.response = response.status === 'refused'
        ? { status: 'unresolved', result: null, text: null, notes: [response.routing.reason || 'The selected route refused this request.'], steps: [], verification: { status: 'not_checked', method: 'route', detail: 'No answer was returned.' }, metrics: routeMetrics, routing: response.routing }
        : { ...answer, status: answer.status || (answer.text ? 'answered' : 'unresolved'), result: answer.result === undefined ? null : answer.result, steps: Array.isArray(answer.steps) ? answer.steps : [], notes: Array.isArray(answer.notes) ? answer.notes : [], verification: answer.verification || { status: 'not_checked', method: 'route', detail: 'The selected route did not provide an independent check.' }, metrics: routeMetrics, routing: response.routing };
      setServiceStatus('ready', routeMetrics.route ? `Route ready · ${routeMetrics.route}` : 'Route ready');
    } catch (error) {
      if (!current()) return;
      message.loading = false;
      message.error = message.cancelled ? 'Route cancelled. You can retry this question.' : (error.message || 'The selected route is unavailable.');
      setServiceStatus(error.status === 422 ? 'ready' : 'error', error.status === 422 ? 'Solver ready' : 'Route unavailable');
    } finally {
      const ownsRequest = current();
      if (state.activeSolve === controller) {
        state.activeSolve = null;
        state.solving = false;
        elements.send.disabled = false;
      }
      if (ownsRequest) renderMessages(false, message.id);
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

  function retryRoute(message) {
    if (state.solving) return;
    const payload = { mode: message.routeMode || 'deterministic', request: message.request || buildRequest(), prompt: message.prompt || '' };
    state.solving = true;
    elements.send.disabled = true;
    message.error = null;
    message.loading = true;
    renderMessages();
    route(payload, message);
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
    const payload = buildRoutePayload();
    const request = payload.request;
    const validationError = validateRoutePayload(payload);
    if (validationError) {
      const fields = validationError.fields.map((name) => elements[name]).filter(Boolean);
      clearFormError();
      showFormError(validationError.message, fields);
      showToast(validationError.message);
      elements.toast.dataset.formError = 'true';
      if (elements.chatInput && !payload.request && !payload.prompt) elements.chatInput.focus();
      else if (validationError.fields[0] === 'routePrompt') elements.routePrompt.focus();
      else focusField(validationError.fields[0] || 'expression');
      return;
    }
    clearFormError();
    state.solving = true;
    elements.send.disabled = true;
    const structuredRequest = request && request.expression ? request : null;
    const display = (elements.chatInput && String(elements.chatInput.value || '').trim())
      || (structuredRequest ? displayRequest(structuredRequest) : payload.prompt);
    const message = { id: String(state.nextMessageId++), generation: state.solveGeneration, request: structuredRequest, prompt: payload.prompt || null, routeMode: payload.mode, display, loading: true };
    state.selectedMessageId = message.id;
    state.messages.push(message);
    if (elements.chatInput) elements.chatInput.value = '';
    renderMessages(true, message.id);
    if (payload.mode === 'exact') solve(request, message);
    else route(payload, message);
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
    if (elements.routeMode) elements.routeMode.value = 'exact';
    if (elements.routePrompt) elements.routePrompt.value = '';
    elements.chatSearch.value = '';
    if (elements.chatInput) elements.chatInput.value = '';
    setFieldValue('expression', '');
    setFieldValue('lower', '');
    setFieldValue('upper', '');
    setFieldValue('target', '');
    clearFormError();
    updateOperationFields();
    renderMessages();
    // Keep the legacy field focus state for compatibility with saved examples,
    // then place the real cursor in the chat composer.
    focusField('expression');
    if (elements.chatInput) elements.chatInput.focus();
  }

  function closeMobileSidebar() {
    if (!elements.sidebar.classList.contains('open')) return;
    elements.sidebar.classList.remove('open');
    elements.appShell.classList.add('sidebar-collapsed');
    elements.openSidebar.setAttribute('aria-expanded', 'false');
  }

  function exampleValues(button) {
    return {
      operation: button.dataset.operation || 'derivative',
      expression: button.dataset.expression || '',
      lower: button.dataset.lower || '',
      upper: button.dataset.upper || '',
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

  function openChatSearch() {
    elements.chatSearchWrap.hidden = false;
    elements.chatSearchToggle.setAttribute('aria-expanded', 'true');
    elements.chatSearchToggle.setAttribute('aria-label', 'Close chat search');
    elements.chatSearch.focus();
  }

  function closeChatSearch() {
    if (elements.chatSearchWrap.hidden) return;
    elements.chatSearchWrap.hidden = true;
    elements.chatSearchToggle.setAttribute('aria-expanded', 'false');
    elements.chatSearchToggle.setAttribute('aria-label', 'Search chats (Ctrl+K or Cmd+K)');
    elements.chatSearch.value = '';
    state.chatFilter = '';
    renderChatList();
    elements.chatSearchToggle.focus();
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

  function fillComposer(values) {
    if (elements.routeMode) elements.routeMode.value = 'exact';
    if (elements.routePrompt) elements.routePrompt.value = '';
    elements.operation.value = values.operation;
    setFieldValue('expression', values.expression);
    setFieldValue('lower', values.lower || '');
    setFieldValue('upper', values.upper || '');
    setFieldValue('target', values.target || '');
    elements.direction.value = values.direction || 'both';
    if (elements.chatInput) {
      const operationText = values.operation === 'derivative' ? 'Differentiate' : values.operation === 'integral' ? 'Integrate' : values.operation === 'limit' ? `Find the limit of ${values.expression} as x approaches ${values.target || '0'}` : `Solve ${values.expression}`;
      elements.chatInput.value = values.operation === 'limit' ? operationText : `${operationText} ${values.expression}`;
    }
    clearFormError();
    updateOperationFields();
    focusField('expression');
    if (elements.chatInput) elements.chatInput.focus();
  }

  function editQuestionButton(request) {
    const button = element('button', '', 'Edit question');
    button.type = 'button';
    button.addEventListener('click', () => fillComposer(request));
    return button;
  }

  function applyExample(button) {
    elements.help.close();
    elements.examples.close();
    fillComposer(exampleValues(button));
  }

  function wireEvents() {
    elements.form.addEventListener('submit', submit);
    elements.operation.addEventListener('change', () => { updateOperationFields(); clearFormError(); });
    if (elements.routeMode) elements.routeMode.addEventListener('change', () => { updateOperationFields(); clearFormError(); });
    elements.expression.addEventListener('input', () => { resizeExpression(); clearFormError(); });
    if (elements.routePrompt) elements.routePrompt.addEventListener('input', clearFormError);
    [elements.lower, elements.upper, elements.target].forEach((field) => field.addEventListener('input', clearFormError));
    elements.expression.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); elements.form.requestSubmit(); }
    });
    if (elements.chatInput) {
      elements.chatInput.addEventListener('input', () => {
        elements.chatInput.style.height = 'auto';
        elements.chatInput.style.height = `${Math.min(elements.chatInput.scrollHeight, 140)}px`;
        clearFormError();
      });
      elements.chatInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); elements.form.requestSubmit(); }
      });
    }
    document.addEventListener('keydown', (event) => {
      const dialogOpen = elements.help.open || elements.examples.open || elements.routeHelp.open;
      if (!dialogOpen && shouldFocusChatSearch(event, document.activeElement && document.activeElement.tagName)) {
        event.preventDefault();
        closeMobileSidebar();
        openChatSearch();
        return;
      }
      if (!dialogOpen && shouldFocusComposer(event, document.activeElement && document.activeElement.tagName)) {
        event.preventDefault();
        if (elements.chatInput) elements.chatInput.focus();
        else focusField('expression');
        return;
      }
      if (event.key !== 'Escape') return;
      if (elements.help.open || elements.examples.open || elements.routeHelp.open) return;
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
    ['#worked-examples', '#explore-examples'].forEach((selector) => {
      $(selector).addEventListener('click', () => { closeMobileSidebar(); elements.examples.showModal(); });
    });
    $('#close-examples').addEventListener('click', () => elements.examples.close());
    $('#route-help').addEventListener('click', () => { closeMobileSidebar(); renderSessionStats(); elements.routeHelp.showModal(); });
    $('#session-copy').addEventListener('click', () => { closeMobileSidebar(); copySessionEvidence(); });
    $('#session-download').addEventListener('click', () => { closeMobileSidebar(); downloadSessionEvidence(); });
    $('#latest-question').addEventListener('click', scrollToLatest);
    $('#open-help-inline').addEventListener('click', () => elements.help.showModal());
    $('#close-help').addEventListener('click', () => elements.help.close());
    $('#close-route').addEventListener('click', () => elements.routeHelp.close());
    $('#close-sidebar').addEventListener('click', () => { elements.sidebar.classList.remove('open'); elements.appShell.classList.add('sidebar-collapsed'); elements.openSidebar.setAttribute('aria-expanded', 'false'); });
    $('#open-sidebar').addEventListener('click', () => { elements.appShell.classList.remove('sidebar-collapsed'); elements.sidebar.classList.add('open'); elements.openSidebar.setAttribute('aria-expanded', 'true'); });
    $('#search-toggle').addEventListener('click', () => {
      if (elements.chatSearchWrap.hidden) {
        openChatSearch();
      } else closeChatSearch();
    });
    elements.chatSearch.addEventListener('input', () => { state.chatFilter = elements.chatSearch.value; renderChatList(); });
    document.querySelectorAll('.starter-prompt').forEach((button) => {
      button.addEventListener('click', () => applyExample(button));
    });
    document.querySelectorAll('.syntax-example, .worked-example').forEach((button) => {
      button.addEventListener('click', () => applyExample(button));
    });
  }

  setupMathFields();
  wireEvents();
  updateOperationFields();
  checkHealth();
})();
