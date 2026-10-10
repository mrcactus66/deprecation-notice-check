"""Gasless StudioNet demonstration with a disposable local account.

Usage: python scripts/studio_demo.py deploy
       python scripts/studio_demo.py inspect <transaction_id>
       python scripts/studio_demo.py register <case>
       python scripts/studio_demo.py audit <case>
       python scripts/studio_demo.py read <case>
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from eth_account import Account
from genlayer_py.client import GenLayerClient
from genlayer_py.chains import studionet
from genlayer_py.provider import GenLayerProvider
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
EVIDENCE = ROOT / "evidence"
REPOSITORY = "mrcactus66/deprecation-notice-check"
FILES = {"adequate": "adequate-notice.txt", "short": "short-notice.txt",
         "tentative": "tentative-notice.txt"}
LOCAL.mkdir(exist_ok=True)
EVIDENCE.mkdir(exist_ok=True)
key_file = LOCAL / "studio.key"
if not key_file.exists():
    key_file.write_text(Account.create().key.hex(), encoding="ascii")
account = Account.from_key(key_file.read_text(encoding="ascii"))
class StudioProvider(GenLayerProvider):
    def __init__(self, url):
        super().__init__(url)
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(max_retries=Retry(
            total=2, connect=2, read=0, backoff_factor=1)))

    def make_request(self, method, params):
        response = self.session.post(self.url, json={"jsonrpc": "2.0", "id": 1,
            "method": method, "params": params}, timeout=30)
        response.raise_for_status()
        value = response.json()
        self._raise_on_error(value, method)
        return value


client = GenLayerClient(studionet, account)
client.provider = StudioProvider(studionet.rpc_urls["default"]["http"][0])
client.w3.provider = client.provider
client.initialize_consensus_smart_contract()


def save(name, value):
    (EVIDENCE / name).write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def operation_log(operation, tx):
    save(operation + "-transaction.json", {"network": "StudioNet", "chain_id": 61999,
         "transaction_id": tx, "demo_account": account.address})
    print(tx, flush=True)


command = sys.argv[1]
if command == "deploy":
    code = (ROOT / "contracts/notice_check.py").read_bytes()
    tx = client.deploy_contract(code, args=[REPOSITORY], leader_only=False)
    operation_log("deploy", tx)
    save("source.json", {"repository": REPOSITORY,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "contract_sha256": hashlib.sha256(code).hexdigest(), "fixtures": "synthetic"})
elif command in ("inspect", "wait"):
    tx = sys.argv[2]
    receipt = (client.wait_for_transaction_receipt(tx, interval=3000, retries=12, full_transaction=True)
               if command == "wait" else client.get_transaction(tx))
    save(tx + "-receipt.json", receipt)
    print(json.dumps({k: v for k, v in receipt.items() if k in (
        "hash", "to_address", "status", "status_name", "consensus_result",
        "consensus_result_name", "result_name", "tx_execution_result", "tx_execution_result_name", "last_round")},
        indent=2, default=str))
elif command in ("register", "audit", "read"):
    case = sys.argv[2]
    contract = (LOCAL / "contract.address").read_text().strip()
    if command == "register":
        commit = json.loads((EVIDENCE / "source.json").read_text())["commit"]
        filename = FILES[case]
        content = (ROOT / "examples" / filename).read_bytes()
        manifest = [{"url": "https://raw.githubusercontent.com/" + REPOSITORY + "/" + commit + "/examples/" + filename,
                     "sha256": hashlib.sha256(content).hexdigest()}]
        args = [case, "Parcel API v1", "2026-10-01", 90, True, json.dumps(manifest)]
        save(case + "-input.json", {"contract": contract, "method": "register", "args": args})
        operation_log(case + "-register", client.write_contract(contract, "register", args=args, value=0, leader_only=False))
    elif command == "audit":
        operation_log(case + "-audit", client.write_contract(contract, "audit", args=[case], value=0, leader_only=False))
    else:
        result = json.loads(client.read_contract(contract, "get_receipt", args=[case]))
        save(case + "-onchain.json", result)
        print(json.dumps(result, indent=2))
else:
    raise SystemExit("Unknown operation")
