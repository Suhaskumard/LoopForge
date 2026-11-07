import itertools

import pytest

from app.services.task_service import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    TaskStatus,
    can_transition,
)


def test_happy_path_is_allowed():
    path = [
        TaskStatus.PENDING,
        TaskStatus.PLANNING,
        TaskStatus.GENERATING,
        TaskStatus.EXECUTING,
        TaskStatus.TESTING,
        TaskStatus.REVIEWING,
        TaskStatus.COMPLETED,
    ]
    for a, b in itertools.pairwise(path):
        assert can_transition(a, b)


def test_repair_loops_back_to_executing():
    assert can_transition(TaskStatus.REVIEWING, TaskStatus.REPAIRING)
    assert can_transition(TaskStatus.REPAIRING, TaskStatus.EXECUTING)
    assert not can_transition(TaskStatus.REPAIRING, TaskStatus.COMPLETED)


@pytest.mark.parametrize("terminal", sorted(TERMINAL_STATES))
def test_terminal_states_have_no_exits(terminal):
    assert ALLOWED_TRANSITIONS[terminal] == set()


def test_cannot_skip_stages():
    assert not can_transition(TaskStatus.PENDING, TaskStatus.COMPLETED)
    assert not can_transition(TaskStatus.GENERATING, TaskStatus.REVIEWING)


def test_every_status_has_a_rule():
    assert set(ALLOWED_TRANSITIONS) == set(TaskStatus)


def test_halted_tasks_can_be_retried_but_finished_ones_cannot():
    from app.services.task_service import RETRYABLE_STATES

    assert RETRYABLE_STATES == {TaskStatus.FAILED, TaskStatus.ESCALATED}
    for s in RETRYABLE_STATES:
        assert ALLOWED_TRANSITIONS[s] == {TaskStatus.PENDING}
    assert not (RETRYABLE_STATES & TERMINAL_STATES)
    assert TERMINAL_STATES == {TaskStatus.COMPLETED, TaskStatus.CANCELLED}
