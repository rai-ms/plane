# Design Spec — Per-Project Status Workflow (Jira-like)

- **Date:** 2026-05-16
- **Repo / branch:** `rai-ms/plane` (fork) / `genzit-custom`
- **Status:** Approved design, pending spec review → implementation plan
- **Feature B (rebrand/white-label) is OUT of scope here** — separate spec→plan cycle.

## 1. Problem & Goal

Plane already has per-project custom statuses (the `State` model), and
creating/deleting them is already ADMIN-only. What is missing is a
**Jira-like workflow**: per project, an ADMIN configures *which status can
transition to which*, and disallowed moves on a work item are rejected.

Goal: add an admin-configured, per-project allowed-transition workflow,
enforced on work-item status changes, with status management fully
ADMIN-only.

## 2. Core Invariants (non-negotiable)

1. **100% dynamic, zero hardcoding.** No hardcoded state names, transition
   tables, default workflows, or literal role numbers in business logic.
   Behavior derives only from: the project's *live* `State` rows, the
   DB-stored transition rules, and the existing `ROLE` enum.
2. **Backward-compatible & data-safe.** A project with **no transition rows
   = unrestricted** (exactly today's behavior). Existing projects/issues
   (live: 4 projects, 22 issues) are untouched. Migration is purely
   additive (new table only; no backfill, no destructive ops).
3. **Admin-only.** Status create/edit/delete *and* workflow config require
   project ADMIN, with the existing workspace-admin override
   (`allow_permission` pattern).

## 3. Codebase Anchors (from recon)

- State model: `apps/api/plane/db/models/state.py:79-127`
  (fields: `name`, `group`, `sequence`, `default`, `color`,
  `description`, `project` FK, `workspace` via `ProjectBaseModel`).
- State CRUD view: `apps/api/plane/app/views/state/base.py:24-147`
  - `create()` `:47` `@allow_permission([ROLE.ADMIN])`
  - `partial_update()` `:62` `@allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])` ← **to tighten**
  - `destroy()` `:114` `@allow_permission([ROLE.ADMIN])`
  - `mark_as_default()` `:106` `@allow_permission([ROLE.ADMIN])`
- Permissions: `apps/api/plane/app/permissions/base.py:13-88`
  (`ROLE`: ADMIN=20, MEMBER=15, GUEST=5; `allow_permission` decorator
  with project-role check + workspace-admin fallback).
- Roles: `apps/api/plane/db/models/project.py:21` (`ROLE_CHOICES`),
  `ProjectMember` `:210-242`.
- Frontend states UI: `apps/web/core/components/project-states/`
  (`root.tsx` orchestrator; admin gate `root.tsx:38-43`
  `allowPermissions([EUserProjectRoles.ADMIN], EUserPermissionsLevel.PROJECT,…)`;
  `create-update/`, `state-item.tsx`, `group-list.tsx`).
- States store/hook: `apps/web/core/hooks/store/use-project-state.ts:13-17`
  (methods incl. `createState/updateState/deleteState`).
- No native workflow/transition concept exists anywhere (verified across
  all 33 model files; only aspirational mention in
  `apps/api/plane/settings/openapi.py`). Build from scratch.

## 4. Data Model (new, additive)

New file `apps/api/plane/db/models/state_transition.py`, model
`StateTransition` (extending `ProjectBaseModel` like `State`):

| Field | Type | Notes |
|---|---|---|
| `project` | FK → Project, `on_delete=CASCADE` | via ProjectBaseModel |
| `workspace` | FK → Workspace | via ProjectBaseModel |
| `from_state` | FK → State, `on_delete=CASCADE`, `related_name="+"` | |
| `to_state` | FK → State, `on_delete=CASCADE`, `related_name="+"` | |
| audit fields | created_by/updated_by/created_at/updated_at | match Plane base |

- `unique_together = ("project", "from_state", "to_state")`.
- Register in `apps/api/plane/db/models/__init__.py`.
- **Semantics:** the set of rows for a project *is* its workflow.
  **0 rows ⇒ all transitions allowed.** Deleting a `State` cascades and
  removes its transition rows automatically.
- One additive Django migration. No data migration/backfill.

## 5. API — Enforcement (single shared validator)

New module `apps/api/plane/app/views/state/workflow.py` exposing:

```
def validate_state_transition(project_id, from_state_id, to_state_id) -> None
    # raises rest_framework ValidationError(code="STATE_TRANSITION_NOT_ALLOWED")
```

Rules (evaluated in order, all dynamic):
1. `from_state_id is None` (issue **creation**, no prior state) → allow.
2. `from_state_id == to_state_id` (no-op) → allow.
3. `StateTransition.objects.filter(project=project_id).exists()` is
   `False` (no workflow configured) → allow.
4. Else allow **iff**
   `StateTransition.objects.filter(project, from_state, to_state).exists()`.
5. Otherwise raise `400` with body
   `{"error": "<dynamic msg>", "code": "STATE_TRANSITION_NOT_ALLOWED"}`,
   message built from the **actual** state names, e.g.
   `"'In Progress' → 'Backlog' is not allowed in this project's workflow"`.

**Hook points** (all call the one validator — no duplicated logic):
- App API single issue update: `apps/api/plane/app/serializers/issue.py`
  (issue update path, in `validate()` / `update()` where `state` changes).
- App API bulk issue update view:
  `apps/api/plane/app/views/issue/` (bulk state-change endpoint).
- Public API v1: `apps/api/plane/api/serializers/issue.py` /
  `apps/api/plane/api/views/issue.py`.
- **Exempt:** Intake/system auto-move (triage → default). Intake’s
  programmatic state set must NOT pass through the validator (pass an
  explicit `system=True`/skip flag at that call site) so Intake keeps
  working. Exact call sites pinned during planning by locating every
  place `Issue.state` is mutated.

## 6. API — Workflow Config CRUD (admin-only)

New view in `apps/api/plane/app/views/state/workflow.py` + URL under the
project: `…/workspaces/<slug>/projects/<pid>/state-transitions/`:

- `GET` → list current allowed `(from_state, to_state)` pairs.
- `POST`/`PUT` (bulk set) → replace the project's rule set with the
  submitted pairs (validate every state belongs to **this** project —
  dynamic check against live `State` rows; reject cross-project ids).
- `DELETE` → clear all rules for the project (workflow off).
- Decorated `@allow_permission([ROLE.ADMIN])` (workspace-admin override
  inherited from the decorator).
- Register route in `apps/api/plane/app/urls/` alongside state routes.

## 7. Permission Tightening (explicit requirement)

`apps/api/plane/app/views/state/base.py:62` `partial_update()`:
`@allow_permission([ROLE.ADMIN, ROLE.MEMBER, ROLE.GUEST])`
→ `@allow_permission([ROLE.ADMIN])`.
Result: create/edit/delete/mark-default/workflow-config all ADMIN-only.

## 8. Frontend (dynamic UI)

Extend Project Settings → States (`apps/web/core/components/project-states/`):

- New admin-only **"Workflow"** sub-section (reuse the existing
  `allowPermissions([EUserProjectRoles.ADMIN], …PROJECT…)` gate already in
  `root.tsx:38-43`; hide entirely for non-admins).
- Transition **grid built dynamically** from the project's live states
  (rows = from, cols = to), checkbox per cell; diagonal = N/A; empty grid
  shows a "workflow off — all moves allowed" hint. Saves via the new
  config endpoint; data via the existing `useProjectState` store
  (add `getStateTransitions/setStateTransitions` service+store methods).
- Work-item **status dropdown** filters to allowed next statuses, computed
  dynamically from `currentState + project rules`. Fallback: if no rules
  or fetch fails → show all (never block the UI).

```
Workflow (admin only)              to →
              Backlog  Todo  In-Prog  Done  Cancelled
from Backlog    —       [x]    [x]     [ ]     [x]
     Todo      [x]      —      [x]     [ ]     [x]
     In-Prog   [ ]      [x]    —       [x]     [x]
     Done      [ ]      [ ]    [ ]     —       [ ]
(no boxes ticked anywhere ⇒ workflow off ⇒ all moves allowed)
```

## 9. Backward-Compat, Data Safety, Rollback

- No rules ⇒ unrestricted ⇒ existing data and Intake flows unchanged.
- Migration additive only (new table) — safe on the live DB; standard
  pre-deploy backup per the handoff doc still applies.
- Rollback: redeploy the previous GHCR image tag. The new `db`-app table
  is inert without the new code (nothing queries it); to also drop it,
  reverse just this one migration: `python manage.py migrate db <prev>`
  (the migration immediately preceding the new `state_transition` one).
  `State`/`Issue` data is never modified by this feature.

## 10. Upstream-Merge Strategy

- Model, validator, config view, migration, frontend workflow component =
  **new files** (no merge conflicts).
- Only **3 surgical edits** to upstream-shared files: `partial_update`
  decorator (1 line), app-API issue serializer hook (validator call),
  public-API issue hook (validator call) — plus URL/`__init__`
  registration. All recorded in the handoff doc customization log.

## 11. Testing

- **Unit:** `validate_state_transition` — creation (None from),
  no-op, empty-config, allowed pair, blocked pair.
- **API:** blocked transition → 400 + correct code; allowed → 200;
  empty config → 200; non-admin config write → 403; cross-project
  state id in config → 400; Intake auto-move still works.
- **Migration:** forward + `migrate … zero` on a DB copy; existing
  row counts unchanged (ws/proj/issue/user) — mirrors the deploy
  data-integrity check.
- **UI:** admin sees Workflow section; non-admin does not; dropdown
  filtering reflects rules; empty grid = all allowed.

## 12. Out of Scope (future v2)

Per-transition role rules; transition conditions/required fields;
automation/post-functions; initial-state restriction on creation. The
`StateTransition` model can extend (add `allowed_roles`, `conditions`)
later without rework.
