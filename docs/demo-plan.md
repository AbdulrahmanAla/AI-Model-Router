# Four-minute demo plan

The demo shows that Model Router chooses the cheapest adequate path for each request. The presenter types one message at a time in the chat composer and keeps the route details collapsed until the final proof point.

## Run order

| Time | Prompt | Expected path | Visible proof |
| --- | --- | --- | --- |
| 0:00 | `Hi` | Local Ollama | Conversational answer beside the robot avatar |
| 0:20 | `What is Python?` | Local Ollama | General answer, marked unverified |
| 0:50 | `What is the derivative of sin(x)?` | Exact solver | `cos(x)`, verification, and steps |
| 1:20 | `Differentiate x^3 sin(x^2)` | Exact solver | Product and chain rules in the numbered steps |
| 1:45 | `What is the derivative of exp(x^2) log(x)?` | Exact solver | Nested chain and product rules |
| 2:10 | `Integrate x exp(x)` | Exact solver | Integration by parts result |
| 2:35 | `Integrate x^2 exp(x)` | Exact solver | Harder repeated integration by parts |
| 2:55 | `What is the integral of x^2 from -1 to 1?` | Exact solver | Definite result and bound evaluation |
| 3:15 | `Integrate 1/(1+x^2)` | Exact solver | Inverse-trigonometric antiderivative |
| 3:35 | `Give a deeper explanation for this result` | Ollama with previous-result context | Explanation refers to the preceding exact result |
| 3:50 | Expand `Response details` | No new request | Route, model, verification, and token evidence |

The presenter should pause briefly after each answer so the audience can see that exact math is answered locally and general language is the only case that calls the model. The AI response is always labeled unverified.

## Acceptance rules

- Every prompt returns HTTP 200 through the local server.
- The first two prompts use the AI route.
- Every math prompt uses the exact solver and shows a result.
- The follow-up explanation includes the previous exact result in its model prompt.
- The composer is empty after every send.
- The route details remain collapsed by default and expand without another request.

Run the smoke script with the local server and Ollama available:

```powershell
python scripts/run_demo_smoke.py
```
