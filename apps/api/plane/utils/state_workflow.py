# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers

from plane.db.models import State, StateTransition


def validate_state_transition(project_id, from_state_id, to_state_id):
    """Raise ValidationError if moving from_state -> to_state is not allowed
    by the project's workflow. No rules for the project => all allowed."""
    if from_state_id is None or to_state_id is None:
        return
    if str(from_state_id) == str(to_state_id):
        return
    if not StateTransition.objects.filter(project_id=project_id).exists():
        return
    if StateTransition.objects.filter(
        project_id=project_id,
        from_state_id=from_state_id,
        to_state_id=to_state_id,
    ).exists():
        return

    names = dict(
        State.all_state_objects.filter(
            id__in=[from_state_id, to_state_id]
        ).values_list("id", "name")
    )
    frm = names.get(from_state_id, "current")
    to = names.get(to_state_id, "target")
    raise serializers.ValidationError(
        f"'{frm}' → '{to}' is not allowed in this project's workflow",
        code="STATE_TRANSITION_NOT_ALLOWED",
    )
