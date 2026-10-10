"""Keep full local RPC receipts and publish readable consensus evidence."""
import base64
import hashlib
import json
from pathlib import Path
from genlayer_py.abi import calldata

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
RAW = ROOT / ".local/raw-receipts"
RAW.mkdir(parents=True, exist_ok=True)


def execution(row):
    return {key: row.get(key) for key in ("mode", "vote", "execution_result",
        "genvm_result", "nondet_disagree", "contract_state_hash")}


transactions = []
for operation in sorted(EVIDENCE.glob("*-transaction.json")):
    meta = json.loads(operation.read_text())
    path = EVIDENCE / (meta["transaction_id"] + "-receipt.json")
    original = RAW / path.name
    if not original.exists():
        original.write_bytes(path.read_bytes())
    raw = json.loads(original.read_text())
    public = {key: raw.get(key) for key in ("hash", "from_address", "to_address",
        "value", "type", "status_name", "result_name", "leader_only",
        "rotation_count", "num_of_rounds", "last_round", "created_at")}
    public["explorer"] = "https://explorer-studio.genlayer.com/tx/" + raw["hash"]
    leaders = raw["consensus_data"]["leader_receipt"]
    public["executions"] = [execution(row) for row in leaders + raw["consensus_data"]["validators"]]
    if raw["type"] == 1:
        public["deployed_source_sha256"] = hashlib.sha256(
            base64.b64decode(raw["data"]["contract_code"])).hexdigest()
        assert public["deployed_source_sha256"] == hashlib.sha256(
            (ROOT / "contracts/notice_check.py").read_bytes()).hexdigest()
    encoded = raw["data"]["calldata"]
    public["calldata"] = (encoded.get("readable") if isinstance(encoded, dict)
                          else calldata.decode(base64.b64decode(encoded)))
    assert raw["result_name"] == "MAJORITY_AGREE"
    assert any(row.get("execution_result") == "SUCCESS" for row in leaders)
    path.write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    transactions.append({"operation": operation.stem.replace("-transaction", ""),
        "transaction_id": raw["hash"], "status": raw["status_name"],
        "consensus": raw["result_name"], "receipt": path.name})

expected = {"adequate": ("MEETS_DECLARED_POLICY", 92),
            "short": ("SHORT_NOTICE", 11), "tentative": ("INCOMPLETE", -1)}
for case, values in expected.items():
    row = json.loads((EVIDENCE / (case + "-onchain.json")).read_text())
    assert (row["status"], row["notice_days"]) == values
    source_file = ROOT / "examples" / (case + "-notice.txt")
    assert row["sources"][0]["sha256"] == hashlib.sha256(source_file.read_bytes()).hexdigest()

(EVIDENCE / "index.json").write_text(json.dumps({"network": "StudioNet", "chain_id": 61999,
    "fixtures": "synthetic", "transactions": transactions,
    "expected_results_verified": True}, indent=2) + "\n", encoding="utf-8")
print("Verified deployed source, seven consensus receipts, and three onchain results.")
