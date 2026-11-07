# ADR-0001: Modular monolith
Status: accepted. Context: MVP needs debuggability; spec §2.2. Decision: one deployable with strict package boundaries (agents / orchestrator / execution / evaluation separate). Consequences: simple testing and deploys; a worker service can be split out in Phase 7 without rewriting.
