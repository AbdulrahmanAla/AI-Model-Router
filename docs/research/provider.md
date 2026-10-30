# Configurable AI explanation and fallback provider

## Recommendation

Use a small server-side HTTP adapter for an OpenAI-compatible Chat Completions endpoint. Keep the exact SymPy path independent of the adapter, so the app runs and demonstrates the efficiency claim with no model key. Enable the provider only when `AI_BASE_URL`, `AI_API_KEY`, and `AI_MODEL` are configured. Do not send a browser request directly to a model provider.

The adapter sends a non-streaming `POST {base_url}/chat/completions` with `Content-Type: application/json`, an `Authorization: Bearer ...` header, a model name, and a short `messages` array. The OpenAI reference defines `messages` as the conversation input and shows this endpoint shape in its curl example: [Create chat completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create#request-body).

## Metrics contract

Record one provider attempt with:

- `provider`, `model`, and a request timestamp
- `latency_ms`
- `status`: `ok`, `missing_config`, `timeout`, `connection_error`, `auth_error`, `rate_limited`, `provider_error`, or `invalid_response`
- `model_calls`: 1 only after a request is sent
- `prompt_tokens`, `completion_tokens`, and `total_tokens` when the response supplies usage, otherwise null
- `explanation_tokens` as the same completion token count for this route

The Chat Completions response exposes optional `usage` with `prompt_tokens`, `completion_tokens`, and `total_tokens`. The official definition says total tokens are prompt plus completion tokens: [usage schema](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create#response-usage). A streaming response can omit the final usage chunk if interrupted, so use non-streaming calls for benchmark evidence and accounting.

## Error and timeout behavior

Set a short application deadline, such as 15 seconds, and make the adapter one attempt by default. A timeout or connection failure returns a visible `explanation_unavailable` state and preserves the exact solver result. The user can retry through the Explain action. Do not retry automatically in the demo because retries inflate model-call and token metrics.

OpenAI documents 400, 401, 403, 404, 409, 422, 429, and 500-plus errors, plus connection and timeout errors. Authentication failures and malformed requests require configuration or code changes. Temporary 429 and 503 responses may include `Retry-After`; quota, billing, and spend-limit errors require action and should not be retried: [Error codes](https://developers.openai.com/api/docs/guides/error-codes), [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits).

## Compatibility boundary

"OpenAI-compatible" is an adapter target, not a guarantee that every provider implements every OpenAI feature. Restrict the first contract to the common subset: non-streaming text messages, one model string, bearer authentication, an assistant text choice, and optional usage counters. Avoid tools, multimodal content, response-format extensions, provider-specific headers, streaming, and reasoning controls in the MVP. Validate the JSON shape before showing an explanation. Bound explanation text to 12,000 characters at both the provider adapter and browser boundary so unexpectedly verbose responses cannot overwhelm the UI or evidence exports. If the provider does not return usage, keep token fields null and label benchmark token evidence as unavailable rather than estimating it.

The provider base URL and model name are configuration, not user input. Keep keys in environment variables or deployment secrets, never in HTML, JavaScript sent to the browser, Git, or screenshots. `.env.example` may contain names and safe placeholder values only.

## No-key development

The local test suite should use a fake HTTP transport that returns a fixed assistant message and usage object, plus failure fixtures for timeout, 401, 429, malformed JSON, and missing usage. These tests prove routing and accounting without making paid network calls. The demo remains fully usable for exact derivatives, integrals, limits, and equations when no provider is configured.

## Limits of the evidence

Provider usage counters prove reported token counts for provider calls. They do not measure FLOPs, electricity, or total model compute. The hackathon claim should compare the same user cases and output requirements, report exact-path model calls as zero, and report optional explanation calls separately. No claim about cross-provider latency or quality is supported until each configured provider is measured with the same harness.
