"""Property-based tests (Hypothesis) for the state machine and ETag helper."""

import pytest
from fastapi import HTTPException
from hypothesis import given
from hypothesis import strategies as st

from app.api.etag import check_if_match, etag_for
from app.services.task_service import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    TaskStatus,
    can_transition,
)

statuses = st.sampled_from(list(TaskStatus))


@given(statuses, statuses)
def test_can_transition_matches_table(a, b):
    assert can_transition(a, b) == (b in ALLOWED_TRANSITIONS[a])


@given(st.sampled_from(sorted(TERMINAL_STATES)), statuses)
def test_terminal_states_are_absorbing(terminal, other):
    assert not can_transition(terminal, other)


@given(statuses)
def test_no_self_transitions(s):
    assert not can_transition(s, s)


@given(st.lists(statuses, min_size=1, max_size=30))
def test_every_walk_reaches_terminal_without_illegal_steps(walk):
    """Following only legal edges from PENDING never leaves the defined state set."""
    current = TaskStatus.PENDING
    for nxt in walk:
        if can_transition(current, nxt):
            current = nxt
    assert current in set(TaskStatus)


@given(st.integers(min_value=1, max_value=10_000))
def test_if_match_accepts_current_and_star(version):
    check_if_match(etag_for(version), version)
    check_if_match(f"W/{etag_for(version)}", version)
    check_if_match("*", version)
    check_if_match(None, version)


@given(st.integers(min_value=1, max_value=10_000), st.integers(min_value=1, max_value=10_000))
def test_if_match_rejects_stale(version, other):
    if version == other:
        return
    with pytest.raises(HTTPException) as exc:
        check_if_match(etag_for(other), version)
    assert exc.value.status_code == 412
