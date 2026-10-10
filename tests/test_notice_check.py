import copy
import hashlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "mrcactus66/deprecation-notice-check"
URL = "https://raw.githubusercontent.com/" + REPOSITORY + "/" + "a" * 40 + "/notice.txt"
BODY = (ROOT / "examples/adequate-notice.txt").read_text(encoding="utf-8")
NOTICE = "Parcel API v1 was announced for deprecation on 2026-07-01. Parcel API v1 will\nbe removed on 2026-10-01."
MIGRATION = "Integrators should migrate to Parcel API v2 and use\nPOST /v2/parcels in place of POST /v1/parcels."
ROW = {"kind": "EXPLICIT", "announced_on": "2026-07-01", "removal_on": "2026-10-01",
       "notice_quote": NOTICE, "migration_available": True, "migration_quote": MIGRATION}


@pytest.fixture
def contract(direct_deploy):
    return direct_deploy(str(ROOT / "contracts/notice_check.py"), REPOSITORY, sdk_version="v0.2.12")


def manifest(body=BODY, url=URL):
    return json.dumps([{"url": url, "sha256": hashlib.sha256(body.encode()).hexdigest()}])


def register(contract, body=BODY, url=URL, case="parcel", days=90, removal="2026-10-01", migration=True):
    contract.register(case, "Parcel API v1", removal, days, migration, manifest(body, url))


def mock(direct_vm, body=BODY, row=None, url=URL, status=200):
    direct_vm.mock_web("^" + __import__("re").escape(url) + "$", {"status": status, "body": body})
    direct_vm.mock_llm("Extract one software deprecation notice", json.dumps(ROW if row is None else row))


def receipt(contract):
    return json.loads(contract.get_receipt("parcel"))


def test_declared_policy_and_receipt_are_bound_to_sources(contract, direct_vm):
    register(contract)
    mock(direct_vm)
    contract.audit("parcel")
    result = receipt(contract)
    assert result["status"] == "MEETS_DECLARED_POLICY"
    assert result["notice_days"] == 92
    assert result["sources"][0]["sha256"] == hashlib.sha256(BODY.encode()).hexdigest()
    assert result["policy_sha256"] == hashlib.sha256(contract.get_policy("parcel").encode()).hexdigest()
    assert contract.meets_declared_policy("parcel")
    assert direct_vm.run_validator() is True


@pytest.mark.parametrize("days,removal,status", [
    (93, "2026-10-01", "SHORT_NOTICE"),
    (92, "2026-10-01", "MEETS_DECLARED_POLICY"),
    (90, "2026-10-02", "REMOVAL_MISMATCH"),
])
def test_policy_boundaries(contract, direct_vm, days, removal, status):
    register(contract, days=days, removal=removal)
    mock(direct_vm)
    contract.audit("parcel")
    assert receipt(contract)["status"] == status


@pytest.mark.parametrize("required,expected", [(True, "MISSING_MIGRATION"), (False, "MEETS_DECLARED_POLICY")])
def test_migration_policy(contract, direct_vm, required, expected):
    row = {**ROW, "migration_available": False, "migration_quote": ""}
    register(contract, migration=required)
    mock(direct_vm, row=row)
    contract.audit("parcel")
    assert receipt(contract)["status"] == expected


def test_tentative_notice_stays_incomplete(contract, direct_vm):
    body = (ROOT / "examples/tentative-notice.txt").read_text(encoding="utf-8")
    row = {"kind": "UNCLEAR", "announced_on": "", "removal_on": "",
           "notice_quote": "The team is considering removing Parcel API v1 sometime next quarter.",
           "migration_available": False, "migration_quote": ""}
    register(contract, body=body)
    mock(direct_vm, body=body, row=row)
    contract.audit("parcel")
    assert receipt(contract)["status"] == "INCOMPLETE"
    assert contract.meets_declared_policy("parcel") is False


def test_conflicting_notices_cannot_pass(contract, direct_vm):
    other_body = BODY.replace("2026-10-01", "2026-10-02")
    other_url = URL.replace("notice.txt", "other.txt")
    sources = json.loads(manifest()) + json.loads(manifest(other_body, other_url))
    contract.register("parcel", "Parcel API v1", "2026-10-01", 90, True, json.dumps(sources))
    mock(direct_vm)
    direct_vm.mock_web("other.txt", {"status": 200, "body": other_body})
    original = direct_vm._match_llm_mock
    # Different pinned source text must produce a different independently extracted date.
    def by_document(prompt):
        row = {**ROW, "removal_on": "2026-10-02", "notice_quote": NOTICE.replace("2026-10-01", "2026-10-02")}
        return json.dumps(row) if "2026-10-02" in prompt else original(prompt)
    direct_vm._match_llm_mock = by_document
    contract.audit("parcel")
    assert receipt(contract)["status"] == "CONFLICTING_NOTICES"


def test_inverted_dates_are_rejected_as_policy_failure(contract, direct_vm):
    body = BODY.replace("2026-07-01", "2026-11-01")
    row = {**ROW, "announced_on": "2026-11-01", "notice_quote": NOTICE.replace("2026-07-01", "2026-11-01")}
    register(contract, body=body)
    mock(direct_vm, body=body, row=row)
    contract.audit("parcel")
    assert receipt(contract)["status"] == "INVALID_DATE_ORDER"


def test_owner_only_policy_and_permissionless_audit(contract, direct_vm, direct_bob):
    with direct_vm.prank(direct_bob), direct_vm.expect_revert("Only the owner"):
        register(contract)
    register(contract)
    mock(direct_vm)
    with direct_vm.prank(direct_bob):
        contract.audit("parcel")
    assert contract.meets_declared_policy("parcel")


def test_duplicate_policy_and_audit_cannot_overwrite(contract, direct_vm):
    register(contract)
    before = contract.get_policy("parcel")
    with direct_vm.expect_revert("duplicate case"):
        register(contract, days=1)
    assert contract.get_policy("parcel") == before
    mock(direct_vm)
    contract.audit("parcel")
    before_receipt = contract.get_receipt("parcel")
    with direct_vm.expect_revert("already audited"):
        contract.audit("parcel")
    assert contract.get_receipt("parcel") == before_receipt


@pytest.mark.parametrize("url", [
    URL.replace("a" * 40, "main"),
    URL.replace(REPOSITORY, "someone/else"),
    URL.replace("raw.githubusercontent.com", "raw.githubusercontent.com.evil.test"),
    URL + "?query=1", URL.replace("notice.txt", "../notice.txt"),
    URL.replace("notice.txt", "%2e%2e/notice.txt"),
])
def test_source_restrictions(contract, direct_vm, url):
    with direct_vm.expect_revert():
        register(contract, url=url)
    assert not contract.meets_declared_policy("parcel")


@pytest.mark.parametrize("sources", ["not json", "{}", "[]", '[{"url":1,"sha256":2}]',
    json.dumps(json.loads(manifest()) * 2),
    json.dumps([{**json.loads(manifest())[0], "sha256": "bad"}]),
])
def test_invalid_manifest(contract, direct_vm, sources):
    with direct_vm.expect_revert():
        contract.register("parcel", "Parcel API v1", "2026-10-01", 90, True, sources)


@pytest.mark.parametrize("date", ["2026-02-30", "2026-13-01", "26-10-01", "2026-1-1"])
def test_invalid_calendar_dates(contract, direct_vm, date):
    with direct_vm.expect_revert():
        register(contract, removal=date)


@pytest.mark.parametrize("body,status,error", [
    ("wrong bytes", 200, "hash mismatch"), (BODY, 503, "HTTP failure"),
    ("x" * 8193, 200, "size outside bounds"), ("", 200, "size outside bounds"),
])
def test_fetch_failures_leave_case_retryable(contract, direct_vm, body, status, error):
    register(contract)
    mock(direct_vm, body=body, status=status)
    with direct_vm.expect_revert(error):
        contract.audit("parcel")
    assert contract.meets_declared_policy("parcel") is False
    with direct_vm.expect_revert("no audit receipt"):
        contract.get_receipt("parcel")
    direct_vm.clear_mocks()
    mock(direct_vm)
    contract.audit("parcel")
    assert contract.meets_declared_policy("parcel")


@pytest.mark.parametrize("mutation,error", [
    ({"notice_quote": "An invented quote"}, "exact source"),
    ({"notice_quote": "The separate Tracking API v1 will be removed on 2026-08-01."}, "anchor"),
    ({"migration_available": "yes"}, "migration flag"),
    ({"kind": "UNCLEAR"}, "decision facts"),
    ({"migration_quote": ""}, "needs a source"),
    ({"extra": "injected"}, "fields"),
])
def test_unanchored_or_malformed_llm_answers_fail_closed(contract, direct_vm, mutation, error):
    register(contract)
    mock(direct_vm, row={**ROW, **mutation})
    with direct_vm.expect_revert(error):
        contract.audit("parcel")
    assert not contract.meets_declared_policy("parcel")


def test_validator_disagrees_on_migration_even_with_valid_json(contract, direct_vm):
    register(contract)
    mock(direct_vm)
    contract.audit("parcel")
    direct_vm.clear_mocks()
    mock(direct_vm, row={**ROW, "migration_available": False, "migration_quote": ""})
    assert direct_vm.run_validator() is False


def test_validator_may_choose_another_exact_quote(contract, direct_vm):
    register(contract)
    mock(direct_vm)
    contract.audit("parcel")
    direct_vm.clear_mocks()
    mock(direct_vm, row={**ROW, "migration_quote": "migrate to Parcel API v2 and use\nPOST /v2/parcels in place of POST /v1/parcels."})
    assert direct_vm.run_validator() is True


def test_forged_leader_dates_and_schema_do_not_bypass_independent_work(contract, direct_vm):
    register(contract)
    mock(direct_vm)
    contract.audit("parcel")
    forged = copy.deepcopy(receipt(contract)["sources"])
    forged[0]["announced_on"] = "2026-06-01"
    assert direct_vm.run_validator(leader_result=forged) is False
    forged = copy.deepcopy(receipt(contract)["sources"])
    forged[0]["migration_quote"] = "A made-up migration route"
    assert direct_vm.run_validator(leader_result=forged) is False
    assert direct_vm.run_validator(leader_result={"status": "MEETS_DECLARED_POLICY"}) is False
    assert direct_vm.run_validator(leader_error=RuntimeError("leader failed")) is False


def test_unregistered_case_cannot_be_audited(contract, direct_vm):
    with direct_vm.expect_revert("Unknown case"):
        contract.audit("unknown")
