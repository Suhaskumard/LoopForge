"""The single source of the release version (Phase 18, ADR-0025).

Semantic versioning with a pre-release tag: ``1.0.0-rc1`` is the first release candidate. Used by
OpenAPI document, ``/health``, the CLI and the SDKs; ``test_phase18_platform`` fails if another file
disagrees. Not 1.0.0 yet: see ADR-0025 for what is missing.
"""

__version__ = "1.0.0-rc1"
