import { useState } from "react";
import { Navigate } from "react-router-dom";
import { TestConstructor } from "../../components/test-draft/TestConstructor";
import { DEFAULT_TEST_SETTINGS } from "../../components/test-draft/TestSettingsFields";
import { useTestDraft } from "../../components/test-draft/testDraftStore";

export function TeacherTestDraftPage() {
  const [current] = useState(() => useTestDraft.getState().current);
  const clear = useTestDraft((state) => state.clear);
  if (!current) return <Navigate to="/teacher/tests" replace />;
  return <TestConstructor key={current.saveKey} generated saveKey={current.saveKey} onSaved={clear}
    initialSettings={{ ...DEFAULT_TEST_SETTINGS, title: current.draft.title, description: current.draft.description }}
    initialQuestions={current.draft.questions.map((q) => ({ ...q, rowId: -q.position_id, base_points: String(q.base_points ?? "1"), category: q.category ?? null }))} />;
}
