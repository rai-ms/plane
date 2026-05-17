# Per-Project Status Workflow — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the admin-only "Workflow" config UI (from→to transition grid) in Project Settings → States, and filter the work-item status dropdown to only allowed next statuses.

**Architecture:** New `IStateTransition` type → service methods on `ProjectStateService` (session-auth, hits the already-live `/state-transitions/` API) → MobX store map+actions on `StateStore` → a new admin-gated grid component mounted in `project-states/root.tsx` → opt-in filtering in the shared state dropdown driven by the store. Backend (live in prod) is unchanged; this is pure UI.

**Tech Stack:** Vite + React Router + MobX + TypeScript; pnpm + Turbo monorepo. `@plane/types`, `@plane/constants`.

**Verification model (IMPORTANT — deviates from TDD by necessity):** `apps/web` has **no vitest/jest** (verified). There is nothing to write unit tests against. The automated gate per task is **`check:types` + `check:lint` + `build`** run on CI (new `genzit-web-check.yml`, modeled on `pull-request-build-lint-web-apps.yml`). Behavior correctness (grid saves, dropdown filters) is validated by **manual visual QA in the deployed UI** at the end (Task 8) — there is no automated alternative in this codebase. Each code task: implement → CI typecheck/lint/build green → commit.

**Spec:** `docs/superpowers/specs/2026-05-16-project-status-workflow-design.md` §8. Backend API contract (live): `GET .../state-transitions/` → `[{from_state_id,to_state_id}]`; `PUT` body `{"transitions":[{from_state_id,to_state_id},…]}` (replace, admin-only); `DELETE` clears. Deleting a State CASCADE-removes its transition rows server-side (no 409 — no defensive UI needed).

---

## File Structure

| File | Responsibility |
|---|---|
| Modify `packages/types/src/state.ts` | add `IStateTransition` |
| Modify `packages/types/src/index.ts` | ensure state types exported (verify; likely already `export * from "./state"`) |
| Modify `apps/web/core/services/project/project-state.service.ts` | `getStateTransitions/setStateTransitions/clearStateTransitions` |
| Modify `apps/web/core/store/state.store.ts` | `stateTransitionMap` observable + `fetchStateTransitions/saveStateTransitions/getAllowedToStateIds` + interface |
| Create `apps/web/core/components/project-states/workflow-transitions/root.tsx` | admin grid UI |
| Create `apps/web/core/components/project-states/workflow-transitions/index.ts` | barrel export |
| Modify `apps/web/core/components/project-states/root.tsx` | mount workflow section (admin-gated, reuse `isEditable`) |
| Modify `apps/web/core/components/dropdowns/state/dropdown.tsx` | compute allowed next-state ids, pass down |
| Modify `apps/web/core/components/dropdowns/state/base.tsx` | honor an optional `allowedStateIds` filter |
| Create `.github/workflows/genzit-web-check.yml` | CI: pnpm + turbo check:types/lint/build (web) |

CI gate command (all tasks): pushed to branch → `genzit-web-check.yml` runs
`pnpm install` then `pnpm turbo run check:types check:lint build --filter=web`.

---

## Task 1: Web CI harness (infra first)

**Files:** Create `.github/workflows/genzit-web-check.yml`

- [ ] **Step 1: Create the workflow**

```yaml
name: Genzit Web Check (status-workflow-ui)

on:
  push:
    branches: [feat/project-status-workflow-frontend]
  workflow_dispatch:

concurrency:
  group: genzit-web-${{ github.ref }}
  cancel-in-progress: true

jobs:
  web-check:
    runs-on: ubuntu-22.04
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
      - name: Install deps
        run: pnpm install --frozen-lockfile
      - name: Typecheck + lint + build (web)
        run: pnpm turbo run check:types check:lint build --filter=web
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/genzit-web-check.yml
git commit -m "ci: web typecheck/lint/build harness for status-workflow UI"
```

- [ ] **Step 3: Push to create branch + verify the harness runs green on untouched code**

Run: `git push -u origin feat/project-status-workflow-frontend`
Expected (controller watches): `genzit-web-check` run → **success** (baseline, no code changed yet). If the harness itself is mis-wired (e.g. node version, pnpm), fix the workflow before any code task.

---

## Task 2: `IStateTransition` type

**Files:** Modify `packages/types/src/state.ts`, verify `packages/types/src/index.ts`

- [ ] **Step 1: Append the type** to `packages/types/src/state.ts` (after the `IState` interface):

```typescript
export interface IStateTransition {
  from_state_id: string;
  to_state_id: string;
}
```

- [ ] **Step 2: Verify export** — confirm `packages/types/src/index.ts` contains `export * from "./state";` (it does; if a named re-export list instead, add `IStateTransition`).

Run: `grep -n "state" packages/types/src/index.ts`
Expected: a line exporting `./state` (wildcard) — no change needed; if named, add `IStateTransition`.

- [ ] **Step 3: Commit**

```bash
git add packages/types/src/state.ts packages/types/src/index.ts
git commit -m "feat(types): add IStateTransition"
```

- [ ] **Step 4: Push; controller verifies `genzit-web-check` green.**

---

## Task 3: Service methods

**Files:** Modify `apps/web/core/services/project/project-state.service.ts`

- [ ] **Step 1: Add import + methods.** Add `IStateTransition` to the existing type import (`import type { IIntakeState, IState, IStateTransition } from "@plane/types";`). Add these methods inside the `ProjectStateService` class (mirror the existing `getStates`/`createState` style — `this.get/put/delete`, `.then(res=>res?.data).catch(err=>{throw err?.response?.data;})`):

```typescript
  async getStateTransitions(workspaceSlug: string, projectId: string): Promise<IStateTransition[]> {
    return this.get(`/api/workspaces/${workspaceSlug}/projects/${projectId}/state-transitions/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async setStateTransitions(
    workspaceSlug: string,
    projectId: string,
    transitions: IStateTransition[]
  ): Promise<void> {
    return this.put(`/api/workspaces/${workspaceSlug}/projects/${projectId}/state-transitions/`, {
      transitions,
    })
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }

  async clearStateTransitions(workspaceSlug: string, projectId: string): Promise<void> {
    return this.delete(`/api/workspaces/${workspaceSlug}/projects/${projectId}/state-transitions/`)
      .then((res) => res?.data)
      .catch((err) => {
        throw err?.response?.data;
      });
  }
```

(Confirm the exact `.then/.catch` shape against the file's existing `getStates`/`createState` before writing — match it precisely.)

- [ ] **Step 2: Commit + push; controller verifies CI green.**

```bash
git add apps/web/core/services/project/project-state.service.ts
git commit -m "feat(web): state-transitions service methods"
```

---

## Task 4: Store map + actions

**Files:** Modify `apps/web/core/store/state.store.ts`

- [ ] **Step 1: Extend `IStateStore` interface** — add:

```typescript
  stateTransitionMap: Record<string, IStateTransition[]>; // keyed by projectId
  fetchStateTransitions: (workspaceSlug: string, projectId: string) => Promise<IStateTransition[]>;
  saveStateTransitions: (
    workspaceSlug: string,
    projectId: string,
    transitions: IStateTransition[]
  ) => Promise<void>;
  getAllowedToStateIds: (projectId: string, fromStateId: string | null | undefined) => string[] | undefined;
```

- [ ] **Step 2: Implement in `StateStore` class.** Add `import type { IStateTransition } from "@plane/types";` to the existing types import. Add observable + actions (mirror the existing `stateMap` observable registration in the constructor `makeObservable`/`observable` block and the `fetchProjectStates` action style):

```typescript
  stateTransitionMap: Record<string, IStateTransition[]> = {};

  // in constructor makeObservable: add `stateTransitionMap: observable` and
  // `fetchStateTransitions: action`, `saveStateTransitions: action`.

  fetchStateTransitions = async (workspaceSlug: string, projectId: string) => {
    const response = await this.stateService.getStateTransitions(workspaceSlug, projectId);
    runInAction(() => {
      this.stateTransitionMap[projectId] = response ?? [];
    });
    return response;
  };

  saveStateTransitions = async (
    workspaceSlug: string,
    projectId: string,
    transitions: IStateTransition[]
  ) => {
    await this.stateService.setStateTransitions(workspaceSlug, projectId, transitions);
    runInAction(() => {
      this.stateTransitionMap[projectId] = transitions;
    });
  };

  getAllowedToStateIds = (projectId: string, fromStateId: string | null | undefined) => {
    const rules = this.stateTransitionMap[projectId];
    if (!rules || rules.length === 0) return undefined; // no workflow => caller shows all
    if (!fromStateId) return undefined; // creation/unknown => show all
    const allowed = rules.filter((r) => r.from_state_id === fromStateId).map((r) => r.to_state_id);
    return Array.from(new Set([fromStateId, ...allowed])); // keep current selectable
  };
```

(Match the file's actual observable-registration mechanism — `makeObservable`, `observable.ref`, or a decorator. Inspect `stateMap`'s registration and replicate exactly for `stateTransitionMap`.)

- [ ] **Step 3: Commit + push; controller verifies CI green.**

```bash
git add apps/web/core/store/state.store.ts
git commit -m "feat(web): state-transitions store map + actions"
```

---

## Task 5: Workflow config grid component

**Files:** Create `apps/web/core/components/project-states/workflow-transitions/root.tsx`, `…/index.ts`

- [ ] **Step 1: Create the component.** Build an admin grid: rows = project states (from), cols = project states (to), a checkbox per off-diagonal cell; load via `fetchStateTransitions`, save the full set via `saveStateTransitions` (replace-semantics). Use `observer`, `useProjectState`, `useParams`. Empty grid ⇒ show hint "No workflow — all transitions allowed".

```tsx
import { useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
import { useParams } from "react-router";
import type { IStateTransition } from "@plane/types";
import { useProjectState } from "@/hooks/store/use-project-state";

type Props = { workspaceSlug: string; projectId: string };

export const WorkflowTransitions = observer(function WorkflowTransitions({ workspaceSlug, projectId }: Props) {
  const { getProjectStates, fetchStateTransitions, saveStateTransitions, stateTransitionMap } = useProjectState();
  const states = getProjectStates(projectId) ?? [];
  const [saving, setSaving] = useState(false);
  const [pairs, setPairs] = useState<Set<string>>(new Set());

  const key = (f: string, t: string) => `${f}->${t}`;

  useEffect(() => {
    fetchStateTransitions(workspaceSlug, projectId).catch(() => {});
  }, [workspaceSlug, projectId, fetchStateTransitions]);

  useEffect(() => {
    const rules = stateTransitionMap[projectId] ?? [];
    setPairs(new Set(rules.map((r) => key(r.from_state_id, r.to_state_id))));
  }, [stateTransitionMap, projectId]);

  const toggle = (f: string, t: string) => {
    if (f === t) return;
    setPairs((prev) => {
      const next = new Set(prev);
      const k = key(f, t);
      next.has(k) ? next.delete(k) : next.add(k);
      return next;
    });
  };

  const onSave = async () => {
    setSaving(true);
    try {
      const transitions: IStateTransition[] = Array.from(pairs).map((k) => {
        const [from_state_id, to_state_id] = k.split("->");
        return { from_state_id, to_state_id };
      });
      await saveStateTransitions(workspaceSlug, projectId, transitions);
    } finally {
      setSaving(false);
    }
  };

  const hasRules = useMemo(() => pairs.size > 0, [pairs]);

  return (
    <div className="mt-6 rounded border border-custom-border-200 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Workflow (admin only)</h3>
        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          className="rounded bg-custom-primary-100 px-3 py-1 text-xs text-white disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save workflow"}
        </button>
      </div>
      {!hasRules && (
        <p className="mt-2 text-xs text-custom-text-300">
          No transitions selected — workflow is off (all status moves allowed).
        </p>
      )}
      <div className="mt-3 overflow-x-auto">
        <table className="text-xs">
          <thead>
            <tr>
              <th className="p-2 text-left text-custom-text-300">from \ to</th>
              {states.map((s) => (
                <th key={s.id} className="p-2 text-custom-text-300">{s.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {states.map((f) => (
              <tr key={f.id}>
                <td className="p-2 font-medium">{f.name}</td>
                {states.map((t) => (
                  <td key={t.id} className="p-2 text-center">
                    {f.id === t.id ? (
                      <span className="text-custom-text-400">—</span>
                    ) : (
                      <input
                        type="checkbox"
                        checked={pairs.has(key(f.id, t.id))}
                        onChange={() => toggle(f.id, t.id)}
                      />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
});
```

`…/index.ts`:
```typescript
export * from "./root";
```

(Adjust class names / button + table styling to match the project-states components' existing Tailwind/`custom-*` tokens — inspect `state-item.tsx`/`group-item.tsx` for the exact design system classes before finalizing.)

- [ ] **Step 2: Commit + push; controller verifies CI green (typecheck/build).**

```bash
git add apps/web/core/components/project-states/workflow-transitions/
git commit -m "feat(web): workflow transition grid component"
```

---

## Task 6: Mount the grid (admin-gated)

**Files:** Modify `apps/web/core/components/project-states/root.tsx`

- [ ] **Step 1: Render the grid** below the existing `GroupList`, only when `isEditable` (the existing admin gate at root.tsx lines ~36-42). Import `WorkflowTransitions` from `./workflow-transitions`. Pass the `workspaceSlug` and `projectId` already used by the admin check. Example (place after the `GroupList` JSX, inside the same container):

```tsx
{isEditable && workspaceSlug && projectId && (
  <WorkflowTransitions workspaceSlug={String(workspaceSlug)} projectId={String(projectId)} />
)}
```

(Read root.tsx first; reuse its exact `workspaceSlug`/`projectId` variables and JSX container. Do not change the admin-gate logic.)

- [ ] **Step 2: Commit + push; controller verifies CI green.**

```bash
git add apps/web/core/components/project-states/root.tsx
git commit -m "feat(web): mount admin workflow grid in project states settings"
```

---

## Task 7: Filter the work-item status dropdown

**Files:** Modify `apps/web/core/components/dropdowns/state/dropdown.tsx`, `apps/web/core/components/dropdowns/state/base.tsx`

- [ ] **Step 1: base.tsx — honor an optional `allowedStateIds`.** In `TWorkItemStateDropdownBaseProps` add `allowedStateIds?: string[];`. Where the option list is built from `stateIds` (recon: ~line 113 `const statesList = stateIds.map(...)`), intersect first:

```tsx
const effectiveStateIds =
  allowedStateIds && allowedStateIds.length > 0
    ? stateIds.filter((id) => allowedStateIds.includes(id))
    : stateIds;
const statesList = effectiveStateIds.map((stateId) => getStateById(stateId)).filter((s) => !!s);
```

(Destructure `allowedStateIds` from props. If `allowedStateIds` is undefined/empty → behaves exactly as today. Pure additive, safe for every existing call site.)

- [ ] **Step 2: dropdown.tsx — compute allowed ids from the store.** Use the store getter with the dropdown's current `value` (current state) and `projectId`. Pass result as `allowedStateIds` to `WorkItemStateDropdownBase`. Also fetch transitions on open (next to the existing `fetchProjectStates` in `onDropdownOpen`):

```tsx
const { fetchProjectStates, getProjectStateIds, getStateById,
        fetchStateTransitions, getAllowedToStateIds } = useProjectState();
// ...
const allowedStateIds = projectId ? getAllowedToStateIds(projectId, props.value) : undefined;
const onDropdownOpen = async () => {
  if ((stateIds === undefined || stateIds.length === 0) && workspaceSlug && projectId) {
    await fetchProjectStates(workspaceSlug.toString(), projectId);
  }
  if (workspaceSlug && projectId) {
    await fetchStateTransitions(workspaceSlug.toString(), projectId).catch(() => {});
  }
};
return <WorkItemStateDropdownBase {...props} stateIds={stateIds ?? []} allowedStateIds={allowedStateIds} />;
```

(Read dropdown.tsx first; preserve its existing `onDropdownOpen` body and prop spreading. `getAllowedToStateIds` returns `undefined` when no rules / no current value → base shows all → zero behavior change for projects without a workflow. This is the safe-fallback contract.)

- [ ] **Step 3: Commit + push; controller verifies CI green (typecheck/lint/build).**

```bash
git add apps/web/core/components/dropdowns/state/base.tsx apps/web/core/components/dropdowns/state/dropdown.tsx
git commit -m "feat(web): filter work-item status dropdown by project workflow"
```

---

## Task 8: Final verification + manual QA + doc

- [ ] **Step 1: Full CI green** — push; controller confirms `genzit-web-check` run is **success** (check:types + check:lint + build all pass for `web`).

- [ ] **Step 2: Manual QA (deployed, after merge+deploy — there is no automated UI test in this codebase).** Checklist to run in the deployed app on a throwaway test project:
  - Project Settings → States: admin sees "Workflow" grid; non-admin (member) does NOT.
  - Tick TODO→Pending, Pending→Done; Save; reload → selections persist (GET round-trip).
  - Open a work item in TODO → status dropdown shows only Pending (+ TODO itself); not Done.
  - Clear all checkboxes, Save → dropdown shows ALL statuses again (workflow off).
  - A project with no workflow configured → dropdown unchanged (regression check).

- [ ] **Step 3: Update handoff doc customization log** — append to `docs/GENZIT-PLANE-CUSTOMIZATION.md` §11.1: frontend files added/modified, the `genzit-web-check.yml` CI, and that web verification = typecheck/lint/build + manual QA (no web unit-test fw).

- [ ] **Step 4: Commit**

```bash
git add docs/GENZIT-PLANE-CUSTOMIZATION.md 2>/dev/null || true
git commit -m "docs: record status-workflow frontend customization" || true
```

(Deploy via the existing gated GHCR→VPS pipeline — merge to genzit-custom → CI rebuild → fresh backup → compose pull && up -d → verify. NOT part of this plan; user-gated. No new migration in the frontend.)

---

## Self-Review

- **Spec coverage (§8):** admin Workflow grid → Tasks 5-6; dropdown filtering → Task 7; reuse existing store/service/permission patterns → Tasks 3-4 (mirror `stateMap`/`getStates`/`isEditable`); dynamic (no hardcoding) → grid built from live `getProjectStates`, rules from API. Backward-compat: `getAllowedToStateIds` returns `undefined` (⇒ show all) when no rules/no current value → Task 4/7. Admin-only → Task 6 reuses existing `isEditable`. Covered.
- **Placeholder scan:** every code step has concrete code. Two explicit "read the file first and match exact existing pattern" notes (service `.then/.catch` shape, store observable registration, dropdown `onDropdownOpen`) are *integration-accuracy guards*, not placeholders — the code to write is fully shown; only the surrounding match must be confirmed. No TBD/TODO.
- **Type consistency:** `IStateTransition {from_state_id,to_state_id}` identical across types/service/store/grid (Tasks 2-5). Store methods `fetchStateTransitions/saveStateTransitions/getAllowedToStateIds` named consistently in interface (Task 4 Step 1), impl (Task 4 Step 2), and consumers (Tasks 5,7). `allowedStateIds` prop name consistent across base.tsx (Task 7.1) and dropdown.tsx (Task 7.2).
- **No test framework:** plan correctly substitutes typecheck/lint/build CI + manual QA, with the reason documented (not a TDD violation — the codebase has no web test runner; verified in recon).
