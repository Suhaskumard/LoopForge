# Support policy (Phase 18)

LoopForge has one maintainer and no paying customers yet; this policy states what is promised, not what would be nice.

| Release line | Status | Gets |
|---|---|---|
| `1.0.0-rcN` (current) | release candidate | fixes for defects found while validating the release; no security backports promised |
| `1.0.x` (after 1.0.0) | supported | bug and security fixes until `1.1.0` ships + **90 days** |
| `1.N.x` (latest minor) | supported | everything |
| older minors | unsupported | upgrade; security fixes only for the previous minor, for 90 days |
| `0.x` / pre-release phases | unsupported | - |

* **Security issues**: report privately to the repository owner (`SECURITY.md` in the repository root once published); acknowledged within 5 business days;
  critical/high fixed within 7 days of confirmation (`docs/dependency_policy.md`). No bug bounty.
* **LTS**: none until at least two minor releases of 1.x exist. Naming one is a decision for after real usage data.
* **Upgrades** are supported from the immediately preceding release (N-1 -> N), tested by `scripts/upgrade_test.py`. Skipping releases: upgrade one at a time.
* **Deprecations** follow `docs/api_policy.md` (two minors and 90 days).
* **What is out of scope**: the model provider's behaviour and availability, third-party IdPs, your infrastructure, forks.

Honest limit: nothing here has been exercised by an external user; the dates are commitments of intent, not an SLA.
