# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from rest_framework.exceptions import ValidationError

from plane.db.models import State, StateTransition
from plane.tests.factories import ProjectFactory
from plane.utils.state_workflow import validate_state_transition


def _state(project, name):
    return State.objects.create(project=project, name=name, color="#fff")


@pytest.mark.django_db
class TestValidateStateTransition:
    def test_creation_has_no_from_state_is_allowed(self):
        p = ProjectFactory()
        to = _state(p, "Todo")
        validate_state_transition(p.id, None, to.id)  # no raise

    def test_noop_same_state_is_allowed(self):
        p = ProjectFactory()
        s = _state(p, "Todo")
        validate_state_transition(p.id, s.id, s.id)  # no raise

    def test_no_rules_configured_allows_any_move(self):
        p = ProjectFactory()
        a, b = _state(p, "Todo"), _state(p, "Done")
        validate_state_transition(p.id, a.id, b.id)  # no raise

    def test_allowed_pair_passes(self):
        p = ProjectFactory()
        a, b = _state(p, "Todo"), _state(p, "Done")
        StateTransition.objects.create(project=p, from_state=a, to_state=b)
        validate_state_transition(p.id, a.id, b.id)  # no raise

    def test_disallowed_pair_raises(self):
        p = ProjectFactory()
        a, b, c = _state(p, "Todo"), _state(p, "Done"), _state(p, "Backlog")
        StateTransition.objects.create(project=p, from_state=a, to_state=b)
        with pytest.raises(ValidationError) as exc:
            validate_state_transition(p.id, a.id, c.id)
        assert exc.value.get_codes() == ["STATE_TRANSITION_NOT_ALLOWED"]
