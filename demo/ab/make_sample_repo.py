"""A small sample repository the A/B tasks run against (synthetic, no real data)."""
import os, sys
FILES = {
    "README.md": "# acme-api\nSmall API client and deploy scripts.\nSee docs/ for setup and deployment.\n",
    "docs/setup.md": "# Setup\nInstall with pip. The client uses `requests`.\nSet API_KEY in your environment.\nTODO: document proxies.\n",
    "docs/deployment.md": "# Deployment\nRun `python -m src.deploy` to deploy to staging.\nThe deploy step reads API_KEY from config/prod.yml.\nRollback: see deploy_rollback.\n",
    "docs/architecture.md": "# Architecture\nfetch_users and fetch_orders live in src/client.py.\nparse_order is in src/models.py.\n",
    "docs/faq.md": "# FAQ\nQ: Why does fetch_users time out?\nA: Increase the timeout.\nTODO: add retry section.\n",
    "docs/changelog.md": "# Changelog\n- 0.2: deploy_staging added\n- 0.1: first release\n",
    "src/__init__.py": "",
    "src/app.py": "import requests\nfrom .client import fetch_users\n\n\ndef main():\n    # TODO: add CLI flags\n    print(fetch_users())\n",
    "src/client.py": "import os\nimport requests\n\nAPI_KEY = os.environ.get('API_KEY')\n\n\ndef fetch_users():\n    return requests.get('https://api.example.com/users', headers={'X-Key': API_KEY}).json()\n\n\ndef fetch_orders():\n    return requests.get('https://api.example.com/orders').json()\n\n\ndef _retry(fn, n=3):\n    for _ in range(n):\n        try:\n            return fn()\n        except Exception:\n            pass\n",
    "src/models.py": "from dataclasses import dataclass\n\n\n@dataclass\nclass Order:\n    id: int\n    total: float\n\n\ndef parse_order(d):\n    return Order(d['id'], d['total'])\n\n\ndef order_summary(orders):\n    # TODO: currency formatting\n    return sum(o.total for o in orders)\n",
    "src/deploy.py": "import os\n\n\ndef deploy_staging():\n    key = os.environ['API_KEY']\n    print('deploying to staging')\n\n\ndef deploy_rollback():\n    print('rolling back')\n",
    "src/utils.py": "def chunk(xs, n):\n    # TODO: handle n <= 0\n    return [xs[i:i + n] for i in range(0, len(xs), n)]\n",
    "tests/test_models.py": "from src.models import parse_order\n\n\ndef test_parse():\n    assert parse_order({'id': 1, 'total': 2.0}).total == 2.0\n",
    "config/prod.yml": "env: prod\napi_key: ${API_KEY}\nregion: eu-west-1\n",
    "config/dev.yml": "env: dev\nregion: local\n",
}
def make(root):
    for p, body in FILES.items():
        os.makedirs(os.path.dirname(os.path.join(root, p)) or root, exist_ok=True)
        open(os.path.join(root, p), "w").write(body)
if __name__ == "__main__":
    make(sys.argv[1])
