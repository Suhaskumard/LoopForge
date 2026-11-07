from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user
from app.database.models import User
from app.schemas.run import AgentInfo

router = APIRouter(prefix="/agents", tags=["agents"])

# Spec §4 table. `implemented` flips as phases land; the Decision Engine is not an agent.
AGENTS = [
    AgentInfo(
        name="Planner",
        role="Requirement analysis and planning",
        implemented=True,
        phase=2,
        may_not="Write code",
    ),
    AgentInfo(
        name="Builder",
        role="Code generation",
        implemented=True,
        phase=2,
        may_not="Run shell commands freely",
    ),
    AgentInfo(
        name="Verifier",
        role="Testing",
        implemented=True,
        phase=3,
        may_not="Infer success without execution",
    ),
    AgentInfo(
        name="Repair",
        role="Debugging and correction",
        implemented=False,
        phase=4,
        may_not="Mark its own fix as successful",
    ),
    AgentInfo(
        name="Reviewer",
        role="Code review and quality",
        implemented=False,
        phase=4,
        may_not="Rely only on LLM scores",
    ),
    AgentInfo(
        name="Documentation",
        role="Final documentation",
        implemented=False,
        phase=6,
        may_not="Run before a terminal state",
    ),
]


@router.get("", response_model=list[AgentInfo])
def list_agents(_: User = Depends(get_current_user)) -> list[AgentInfo]:
    return AGENTS
