# Deprecation notice check

A GenLayer contract for one specific question: does a documented API removal
meet the notice period and migration requirements registered by its maintainer?

An announcement can mention several APIs, tentative dates, and a generic
"updated" date. Reading those statements is the nondeterministic step. The
contract keeps date arithmetic and the final policy decision in Python.

## How it works

The deployer chooses one GitHub source repository. Only that deployer can
register a case: component name, planned removal date, minimum notice days,
migration requirement, and one to three source URLs with SHA-256 hashes.
Each URL must contain a full Git commit SHA. A registered case cannot change.

Anyone can call `audit(case_id)`. Leader and validators independently fetch
the pinned documents, check their bytes, and extract announcement date,
firm removal date, component relevance, and migration availability. They must
agree on those facts and the source commitments. Exact quote spans can differ,
but both leader and validator quotes must actually occur in the fetched text.
Matching JSON shape by itself never accepts a leader answer.

After consensus, deterministic code calculates the calendar-day difference
and stores an immutable receipt. Consumers can read the receipt or call
`meets_declared_policy(case_id)`; an unaudited case returns false.

| Result | Meaning |
| --- | --- |
| MEETS_DECLARED_POLICY | All required facts satisfy the registered policy |
| SHORT_NOTICE | The documented interval is shorter than the minimum |
| MISSING_MIGRATION | Required replacement or migration route is missing |
| REMOVAL_MISMATCH | The notice date differs from the registered removal date |
| INVALID_DATE_ORDER | Removal precedes announcement |
| CONFLICTING_NOTICES | Sources state different dates |
| INCOMPLETE | At least one source is tentative, unrelated, or lacks dates |

HTTP errors, hash mismatches, invalid UTF-8, documents over 8 KiB, malformed
extractions, and unsupported quotations abort the audit without a receipt.
The case can be retried. A completed receipt cannot be overwritten.

## Run the tests

Python 3.13 is used for local testing.

```sh
python -m venv .venv
python -m pip install -r requirements.txt
python -m pytest -q
genvm-lint lint contracts/notice_check.py
```

Activate the virtual environment before installing and running those commands.
The first direct test downloads official GenVM v0.2.12 artifacts. Tests execute
the actual contract with `gltest` storage and calldata handling, while web and
model responses are mocked. Explicit validator calls check agreement,
disagreement, malformed leader results, and fabricated quotes. These tests
do not simulate a distributed network or prove model accuracy.
`tests/conftest.py` defers cleanup of the runner's open message file on Windows;
it does not replace contract storage, extraction, or validator behavior.

## Scope

The receipt establishes agreement about the supplied documentation. It does
not prove when a notice was first publicly published, whether users received
it, whether the migration works, or whether a service has actually shut down.
The owner chooses the policy and source repository; a dishonest owner can
register misleading documents. Commit pinning protects bytes from changing,
not the truth of their contents.

Dates must be literal ISO calendar dates in a component-specific notice. This
deliberately excludes relative dates and ambiguous promises. Exact fact
agreement can reject borderline prose; rejection is preferable to silently
granting a passing receipt.

The Parcel API documents under `examples/` are fictional test fixtures. They
cover adequate notice, short notice, and an announcement with no firm dates.
No user data, real service audit, token transfer, or financial decision is
involved in this demonstration.
