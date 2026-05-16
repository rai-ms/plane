# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import pytest
from rest_framework.exceptions import ValidationError

from plane.db.models import State, StateTransition, Issue
from plane.app.serializers.issue import IssueCreateSerializer
from plane.tests.factories import ProjectFactory, UserFactory


def _state(p, n):
    return State.objects.create(project=p, name=n, color="#fff")


@pytest.mark.django_db
class TestIssueSerializerWorkflowEnforcement:
    def _ctx(self, project, user):
        return {
            "project_id": project.id,
            "workspace_id": project.workspace_id,
            "default_assignee_id": None,
            "request": type("R", (), {"user": user})(),
        }

    def test_disallowed_update_transition_blocked(self):
        p = ProjectFactory()
        u = UserFactory(username="wf-user-disallowed")
        a, b = _state(p, "Todo"), _state(p, "Backlog")
        StateTransition.objects.create(project=p, from_state=a, to_state=_state(p, "Done"))
        issue = Issue.objects.create(project=p, name="x", state=a)
        ser = IssueCreateSerializer(
            instance=issue, data={"state_id": str(b.id)},
            partial=True, context=self._ctx(p, u),
        )
        with pytest.raises(ValidationError) as exc:
            ser.is_valid(raise_exception=True)
        assert exc.value.get_codes() == ["STATE_TRANSITION_NOT_ALLOWED"]

    def test_allowed_update_transition_ok(self):
        p = ProjectFactory()
        u = UserFactory(username="wf-user-allowed")
        a, b = _state(p, "Todo"), _state(p, "Done")
        StateTransition.objects.create(project=p, from_state=a, to_state=b)
        issue = Issue.objects.create(project=p, name="x", state=a)
        ser = IssueCreateSerializer(
            instance=issue, data={"state_id": str(b.id)},
            partial=True, context=self._ctx(p, u),
        )
        assert ser.is_valid(raise_exception=True) is True
