/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

import { useEffect, useMemo, useState } from "react";
import { observer } from "mobx-react";
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
      if (next.has(k)) next.delete(k);
      else next.add(k);
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
    <div className="mt-6 rounded-sm border border-subtle bg-surface-1 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-primary">Workflow (admin only)</h3>
        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          className="rounded-sm bg-accent-primary px-3 py-1 text-xs text-white disabled:opacity-60"
        >
          {saving ? "Saving..." : "Save workflow"}
        </button>
      </div>
      {!hasRules && (
        <p className="mt-2 text-xs text-tertiary">
          No transitions selected — workflow is off (all status moves allowed).
        </p>
      )}
      <div className="mt-3 overflow-x-auto">
        <table className="text-xs">
          <thead>
            <tr>
              <th className="p-2 text-left text-tertiary">from \ to</th>
              {states.map((s) => (
                <th key={s.id} className="p-2 text-tertiary">
                  {s.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {states.map((f) => (
              <tr key={f.id}>
                <td className="p-2 font-medium text-primary">{f.name}</td>
                {states.map((t) => (
                  <td key={t.id} className="p-2 text-center">
                    {f.id === t.id ? (
                      <span className="text-placeholder">—</span>
                    ) : (
                      <input type="checkbox" checked={pairs.has(key(f.id, t.id))} onChange={() => toggle(f.id, t.id)} />
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
