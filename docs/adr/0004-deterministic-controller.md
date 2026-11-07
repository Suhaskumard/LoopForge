# ADR-0004: Deterministic Decision Engine
Status: accepted. Decision: retry/accept/escalate/stop is plain Python, never an LLM (spec §4.7, §5.3). LLMs may advise routing; transitions stay policy-governed. Requires 100% branch coverage.
