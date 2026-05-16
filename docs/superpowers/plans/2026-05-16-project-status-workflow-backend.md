# Per-Project Status Workflow — Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-configured, per-project allowed-transition workflow that rejects disallowed work-item status changes, with zero hardcoding and full backward-compatibility.

**Architecture:** New additive `StateTransition` model (0 rows for a project ⇒ all transitions allowed). A single pure validator queries it and raises a DRF `ValidationError` on a disallowed move; it is invoked from the issue create/update serializer. A new admin-only endpoint manages the rule set. State edit is tightened to ADMIN.

**Tech Stack:** Django 4 + DRF, pytest (`@pytest.mark.django_db`), `factory_boy` factories in `plane/tests/factories.py`.

**Scope:** Backend only. Frontend (transition grid UI + status-dropdown filtering) is a separate plan: `docs/superpowers/plans/<later>-project-status-workflow-frontend.md`. This plan alone produces working, API-testable software.

**Spec:** `docs/superpowers/specs/2026-05-16-project-status-workflow-design.md`

**Design deviation (recorded):** The pure validator lives in `apps/api/plane/utils/state_workflow.py` (NOT in `app/views/state/workflow.py` as the spec sketched) so serializers can import it without a serializer→view circular import. The admin config endpoint stays in `app/views/state/workflow.py`.

---

## File Structure

| File | Responsibility |
|---|---|
| Create `apps/api/plane/db/models/state_transition.py` | `StateTransition` model |
| Modify `apps/api/plane/db/models/__init__.py:64` | export `StateTransition` |
| Create `apps/api/plane/db/migrations/0122_statetransition.py` | additive migration (via makemigrations) |
| Create `apps/api/plane/utils/state_workflow.py` | pure `validate_state_transition()` |
| Modify `apps/api/plane/app/serializers/issue.py:~167` | call validator in `IssueCreateSerializer.validate()` |
| Create `apps/api/plane/app/views/state/workflow.py` | `StateTransitionEndpoint` (admin-only CRUD) |
| Modify `apps/api/plane/app/views/__init__.py:86` | export `StateTransitionEndpoint` |
| Modify `apps/api/plane/app/urls/state.py` | register route |
| Modify `apps/api/plane/app/views/state/base.py:61` | tighten `partial_update` to `[ROLE.ADMIN]` |
| Create `apps/api/plane/tests/unit/utils/__init__.py` + `test_state_workflow.py` | validator unit tests |
| Create `apps/api/plane/tests/unit/serializers/test_state_transition_enforce.py` | enforcement integration test |

Test command (all tasks): `cd apps/api && pytest <path> -v` (settings/db via existing `plane/tests/conftest.py`).

---

## Task 1: `StateTransition` model

**Files:**
- Create: `apps/api/plane/db/models/state_transition.py`
- Modify: `apps/api/plane/db/models/__init__.py:64`

- [ ] **Step 1: Create the model**

```python
# apps/api/plane/db/models/state_transition.py
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
```

- [ ] **Step 2: Export it** — in `apps/api/plane/db/models/__init__.py`, directly below line 64 (`from .state import State, StateGroup, DEFAULT_STATES`) add:

```python
from .state_transition import StateTransition
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/plane/db/models/state_transition.py apps/api/plane/db/models/__init__.py
git commit -m "feat(api): add StateTransition model (per-project workflow)"
```

---

## Task 2: Migration

**Files:** Create `apps/api/plane/db/migrations/0122_*.py` (generated)

- [ ] **Step 1: Generate the migration**

Run: `cd apps/api && python manage.py makemigrations db`
Expected: creates `plane/db/migrations/0122_statetransition.py` containing `migrations.CreateModel(name="StateTransition", ...)` and no other model changes.

- [ ] **Step 2: Verify it is additive only**

Run: `cd apps/api && grep -E "DeleteModel|RemoveField|AlterField|RunPython|RunSQL" plane/db/migrations/0122_*.py`
Expected: NO output (pure `CreateModel` + FKs only).

- [ ] **Step 3: Apply + reverse on the local/test DB to prove reversibility**

Run: `cd apps/api && python manage.py migrate db && python manage.py migrate db 0121 && python manage.py migrate db`
Expected: forward OK, reverse drops only `state_transitions`, forward OK again. No errors.

- [ ] **Step 4: Commit**

```bash
git add apps/api/plane/db/migrations/0122_*.py
git commit -m "feat(api): migration for StateTransition"
```

---

## Task 3: Pure validator (TDD)

**Files:**
- Create: `apps/api/plane/utils/state_workflow.py`
- Test: `apps/api/plane/tests/unit/utils/__init__.py`, `apps/api/plane/tests/unit/utils/test_state_workflow.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/api/plane/tests/unit/utils/test_state_workflow.py
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
```

Also create empty file `apps/api/plane/tests/unit/utils/__init__.py`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && pytest plane/tests/unit/utils/test_state_workflow.py -v`
Expected: FAIL — `ModuleNotFoundError: plane.utils.state_workflow`.

- [ ] **Step 3: Implement the validator**

```python
# apps/api/plane/utils/state_workflow.py
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd apps/api && pytest plane/tests/unit/utils/test_state_workflow.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/plane/utils/state_workflow.py apps/api/plane/tests/unit/utils/
git commit -m "feat(api): add validate_state_transition + tests"
```

---

## Task 4: Enforce in app issue create/update serializer (TDD)

**Files:**
- Modify: `apps/api/plane/app/serializers/issue.py` (`IssueCreateSerializer.validate`, the `# Check state is from the project only` block ~line 167-175)
- Test: `apps/api/plane/tests/unit/serializers/test_state_transition_enforce.py`

- [ ] **Step 1: Write the failing test**

```python
# apps/api/plane/tests/unit/serializers/test_state_transition_enforce.py
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
        u = UserFactory()
        a, b = _state(p, "Todo"), _state(p, "Backlog")
        StateTransition.objects.create(project=p, from_state=a, to_state=_state(p, "Done"))
        issue = Issue.objects.create(project=p, name="x", state=a)
        ser = IssueCreateSerializer(
            instance=issue, data={"state_id": str(b.id)},
            partial=True, context=self._ctx(p, u),
        )
        with pytest.raises(ValidationError) as exc:
            ser.is_valid(raise_exception=True)
        assert "workflow" in str(exc.value)

    def test_allowed_update_transition_ok(self):
        p = ProjectFactory()
        u = UserFactory()
        a, b = _state(p, "Todo"), _state(p, "Done")
        StateTransition.objects.create(project=p, from_state=a, to_state=b)
        issue = Issue.objects.create(project=p, name="x", state=a)
        ser = IssueCreateSerializer(
            instance=issue, data={"state_id": str(b.id)},
            partial=True, context=self._ctx(p, u),
        )
        assert ser.is_valid(raise_exception=True) is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && pytest plane/tests/unit/serializers/test_state_transition_enforce.py -v`
Expected: FAIL — `test_disallowed_update_transition_blocked` does NOT raise (no enforcement yet).

- [ ] **Step 3: Add the enforcement call**

In `apps/api/plane/app/serializers/issue.py`, locate the existing block (≈ lines 167-175):

```python
        # Check state is from the project only else raise validation error
        if (
            attrs.get("state")
            and not state_manager.filter(
                project_id=self.context.get("project_id"),
                pk=attrs.get("state").id,
            ).exists()
        ):
            raise serializers.ValidationError("State is not valid please pass a valid state_id")
```

Immediately AFTER that block insert:

```python
        # Enforce per-project workflow on state changes (no rules => allowed)
        if attrs.get("state"):
            from plane.utils.state_workflow import validate_state_transition

            old_state_id = self.instance.state_id if self.instance else None
            validate_state_transition(
                self.context.get("project_id"),
                old_state_id,
                attrs.get("state").id,
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd apps/api && pytest plane/tests/unit/serializers/test_state_transition_enforce.py -v`
Expected: 2 passed.

- [ ] **Step 5: Regression — existing issue tests still green**

Run: `cd apps/api && pytest plane/tests/unit/serializers/ -v`
Expected: all pass (no rules configured anywhere ⇒ no behavior change for existing tests).

- [ ] **Step 6: Commit**

```bash
git add apps/api/plane/app/serializers/issue.py apps/api/plane/tests/unit/serializers/test_state_transition_enforce.py
git commit -m "feat(api): enforce per-project state workflow on issue state change"
```

---

## Task 5: Additional enforcement points (public API + bulk)

**Files:** Modify the public-API issue serializer and the bulk issue-update view.

- [ ] **Step 1: Locate the two sites**

Run:
```bash
cd apps/api && grep -rn "State is not valid please pass a valid state_id" plane/api/serializers/issue.py
grep -rn "def bulk" plane/app/views/issue/*.py | grep -i update
```
Expected: one match in `plane/api/serializers/issue.py` (public API `validate`), and the bulk update view method.

- [ ] **Step 2: Add the identical guard at the public-API serializer**

In `plane/api/serializers/issue.py`, immediately after the existing "State is not valid" validation block, insert (same code as Task 4 Step 3, adapted to that serializer's variable for the incoming state id — if it uses `data.get("state_id")`/`attrs.get("state")`, mirror it):

```python
        # Enforce per-project workflow on state changes (no rules => allowed)
        state_obj = attrs.get("state")
        if state_obj is not None:
            from plane.utils.state_workflow import validate_state_transition

            old_state_id = self.instance.state_id if self.instance else None
            validate_state_transition(
                self.context.get("project_id"), old_state_id, state_obj.id
            )
```

- [ ] **Step 3: Add the guard in the bulk update view**

In the bulk update method found in Step 1, for each issue being updated where a new `state_id` is provided, call before persisting:

```python
        from plane.utils.state_workflow import validate_state_transition

        validate_state_transition(project_id, issue.state_id, new_state_id)
```
(Place inside the per-issue loop; `project_id` is already available in these views as `kwargs["project_id"]` or `self.kwargs`.)

- [ ] **Step 4: Run full serializer + view issue tests**

Run: `cd apps/api && pytest plane/tests/unit/ -k issue -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plane/api/serializers/issue.py plane/app/views/issue/
git commit -m "feat(api): enforce state workflow on public API + bulk issue update"
```

---

## Task 6: Admin-only workflow config endpoint (TDD)

**Files:**
- Create: `apps/api/plane/app/views/state/workflow.py`
- Modify: `apps/api/plane/app/views/__init__.py` (after line 86 `from .state.base import StateViewSet, IntakeStateEndpoint`)
- Modify: `apps/api/plane/app/urls/state.py`
- Test: append to `apps/api/plane/tests/unit/serializers/test_state_transition_enforce.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.django_db
class TestStateTransitionEndpointLogic:
    def test_set_replaces_ruleset_and_rejects_cross_project(self):
        from plane.app.views.state.workflow import set_project_transitions
        p = ProjectFactory()
        a, b = _state(p, "Todo"), _state(p, "Done")
        other = _state(ProjectFactory(), "X")
        set_project_transitions(p.id, [(a.id, b.id)])
        assert StateTransition.objects.filter(project_id=p.id).count() == 1
        # replace semantics
        set_project_transitions(p.id, [])
        assert StateTransition.objects.filter(project_id=p.id).count() == 0
        # cross-project state rejected
        with pytest.raises(ValidationError):
            set_project_transitions(p.id, [(a.id, other.id)])
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd apps/api && pytest plane/tests/unit/serializers/test_state_transition_enforce.py::TestStateTransitionEndpointLogic -v`
Expected: FAIL — import error.

- [ ] **Step 3: Implement endpoint + helper**

```python
# apps/api/plane/app/views/state/workflow.py
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from rest_framework import serializers, status
from rest_framework.response import Response

from .. import BaseAPIView
from plane.app.permissions import ROLE, allow_permission
from plane.db.models import State, StateTransition


def set_project_transitions(project_id, pairs):
    """Replace a project's workflow with `pairs` of (from_id, to_id)."""
    valid_ids = set(
        str(i)
        for i in State.all_state_objects.filter(
            project_id=project_id
        ).values_list("id", flat=True)
    )
    for frm, to in pairs:
        if str(frm) not in valid_ids or str(to) not in valid_ids:
            raise serializers.ValidationError(
                "from_state/to_state must belong to this project"
            )
    StateTransition.objects.filter(project_id=project_id).delete()
    StateTransition.objects.bulk_create(
        [
            StateTransition(
                project_id=project_id, from_state_id=f, to_state_id=t
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
        pairs = [
            (t["from_state_id"], t["to_state_id"])
            for t in request.data.get("transitions", [])
        ]
        set_project_transitions(project_id, pairs)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @allow_permission([ROLE.ADMIN])
    def delete(self, request, slug, project_id):
        StateTransition.objects.filter(project_id=project_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
```

In `apps/api/plane/app/views/__init__.py`, after line 86 add:

```python
from .state.workflow import StateTransitionEndpoint
```

In `apps/api/plane/app/urls/state.py`: add `StateTransitionEndpoint` to the import on line 8, and add this `path(...)` to `urlpatterns`:

```python
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/state-transitions/",
        StateTransitionEndpoint.as_view(),
        name="project-state-transitions",
    ),
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd apps/api && pytest plane/tests/unit/serializers/test_state_transition_enforce.py::TestStateTransitionEndpointLogic -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/api/plane/app/views/state/workflow.py apps/api/plane/app/views/__init__.py apps/api/plane/app/urls/state.py apps/api/plane/tests/unit/serializers/test_state_transition_enforce.py
git commit -m "feat(api): admin-only state-transition config endpoint"
```

---

## Task 7: Tighten state edit to ADMIN-only

**Files:** Modify `apps/api/plane/app/views/state/base.py:61`

- [ ] **Step 1: Change the decorator**

In `apps/api/plane/app/views/state/base.py`, line 61, change:

```python
    @allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])
    def partial_update(self, request, slug, project_id, pk):
```
to:
```python
    @allow_permission([ROLE.ADMIN])
    def partial_update(self, request, slug, project_id, pk):
```

- [ ] **Step 2: Sanity-check no other call site relies on member edit**

Run: `cd apps/api && grep -rn "partial_update" plane/app/views/state/`
Expected: only the one definition. (Create/destroy/mark_default already `[ROLE.ADMIN]`.)

- [ ] **Step 3: Commit**

```bash
git add apps/api/plane/app/views/state/base.py
git commit -m "feat(api): restrict state edit to project admins"
```

---

## Task 8: Final verification

- [ ] **Step 1: Full targeted suite**

Run: `cd apps/api && pytest plane/tests/unit/utils/test_state_workflow.py plane/tests/unit/serializers/test_state_transition_enforce.py -v`
Expected: all pass.

- [ ] **Step 2: Broader regression**

Run: `cd apps/api && pytest plane/tests/unit/ -q`
Expected: no new failures vs. baseline (pre-change) run.

- [ ] **Step 3: Update the handoff doc customization log**

Append to `docs/GENZIT-PLANE-CUSTOMIZATION.md` (gitignored) §7/customization log: the 3 surgical edits (issue.py app serializer, public api serializer, state/base.py:61) + new files + new migration `0122`, and the rollback note (redeploy prior GHCR tag; `migrate db 0121` drops only `state_transitions`).

- [ ] **Step 4: Commit**

```bash
git add docs/GENZIT-PLANE-CUSTOMIZATION.md 2>/dev/null || true
git commit -m "docs: record status-workflow customization" || true
```

(Deploy via the existing gated GHCR pipeline — push `genzit-custom` → CI rebuilds → fresh backup → `compose pull && up -d` → verify counts unchanged. NOT part of this plan; user-gated.)

---

## Self-Review

- **Spec coverage:** §4 model→T1/T2; §5 validator+hooks→T3/T4/T5; §6 config endpoint→T6; §7 perm tighten→T7; §9 backward-compat (no rows⇒allow, additive migration, reverse)→T2/T3; §10 merge strategy (new files + 3 edits)→T8 doc; §11 testing→T3/T4/T5/T6/T8. Frontend (§8) intentionally deferred to a separate plan (noted in Scope).
- **Placeholder scan:** validator/model/endpoint/migration code fully shown; Task 5 repeats the guard snippet rather than "similar to". Bulk site is located by an explicit grep with the exact snippet to insert (DRY reuse of shown code, not a vague TODO).
- **Type consistency:** `validate_state_transition(project_id, from_state_id, to_state_id)` signature identical across T3/T4/T5; `set_project_transitions(project_id, pairs)` consistent T6; `StateTransition` fields `from_state`/`to_state`/`project` consistent across all tasks.
