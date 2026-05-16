# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.db import models

from .project import ProjectBaseModel


class StateTransition(ProjectBaseModel):
    """One allowed (from_state -> to_state) move within a project's workflow.

    Semantics: the set of rows for a project IS that project's workflow.
    Zero rows for a project => every transition is allowed (back-compat).
    """

    from_state = models.ForeignKey(
        "db.State", on_delete=models.CASCADE, related_name="+"
    )
    to_state = models.ForeignKey(
        "db.State", on_delete=models.CASCADE, related_name="+"
    )

    def __str__(self):
        return f"{self.from_state_id} -> {self.to_state_id} <{self.project_id}>"

    class Meta:
        unique_together = ["project", "from_state", "to_state", "deleted_at"]
        verbose_name = "State Transition"
        verbose_name_plural = "State Transitions"
        db_table = "state_transitions"
        ordering = ("created_at",)
