# ADR-0002: LangGraph for orchestration
Status: accepted. Decision: explicit graph, typed shared state, checkpointing after every node so workflows resume after interruption. Alternatives: hand-rolled loop (no resume), CrewAI/AutoGen (implicit control flow). Large artifacts are passed by ID, not via LLM context.
