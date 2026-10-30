"""Preview success followed by failure at the external AI transport boundary.

This local fixture does not contact a model. Its text and usage are synthetic.
"""

import argparse
import os
from pathlib import Path
import sys

import httpx
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8029)
    args = parser.parse_args()
    os.environ['AI_BASE_URL'] = 'https://synthetic-provider.example/v1'
    os.environ['AI_API_KEY'] = 'local-contract-fixture'
    os.environ['AI_MODEL'] = 'synthetic-contract-fixture'
    calls = 0

    def provider(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        print(f'Synthetic provider attempt {calls}', flush=True)
        if calls > 1:
            return httpx.Response(503, json={'error': 'Synthetic retry failure'})
        return httpx.Response(200, json={
            'choices': [{'message': {'content': 'Synthetic contract-test explanation. This text and its token counters are fixtures, not a live model response. The exact solver answer above remains authoritative.'}}],
            'usage': {'prompt_tokens': 8, 'completion_tokens': 12, 'total_tokens': 20},
        })

    app.state.ai_transport = httpx.MockTransport(provider)
    print('Local synthetic AI preview: first attempt answers, later attempts fail. No live model is used.', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
