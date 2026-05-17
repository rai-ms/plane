# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers, status
from rest_framework.response import Response

from .. import BaseAPIView
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import Project, State, StateTransition


def set_project_transitions(project_id, pairs):
    """Replace a project's workflow with `pairs` of (from_id, to_id).

    State IDs are validated against the project's live states (State.objects
    excludes soft-deleted and triage), so rules cannot reference dead states.
    """
    valid_ids = set(
        str(i)
        for i in State.objects.filter(
            project_id=project_id
        ).values_list("id", flat=True)
    )
    for frm, to in pairs:
        if str(frm) not in valid_ids or str(to) not in valid_ids:
            raise serializers.ValidationError(
                "from_state/to_state must belong to this project"
            )
    workspace_id = (
        Project.objects.filter(id=project_id)
        .values_list("workspace_id", flat=True)
        .first()
    )
    StateTransition.objects.filter(project_id=project_id).delete(soft=False)
    StateTransition.objects.bulk_create(
        [
            StateTransition(
                project_id=project_id,
                workspace_id=workspace_id,
                from_state_id=f,
                to_state_id=t,
            )
            for f, t in pairs
        ]
    )


class StateTransitionEndpoint(BaseAPIView):
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def get(self, request, slug, project_id):
        data = list(
            StateTransition.objects.filter(project_id=project_id).values(
                "from_state_id", "to_state_id"
            )
        )
        return Response(data, status=status.HTTP_200_OK)

    @allow_permission([ROLE.ADMIN])
    def put(self, request, slug, project_id):
        try:
            pairs = [
                (t["from_state_id"], t["to_state_id"])
                for t in request.data.get("transitions", [])
            ]
        except (KeyError, TypeError):
            raise serializers.ValidationError(
                "transitions must be a list of {from_state_id, to_state_id} objects"
            )
        set_project_transitions(project_id, pairs)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id):
        StateTransition.objects.filter(project_id=project_id).delete(soft=False)
        return Response(status=status.HTTP_204_NO_CONTENT)
