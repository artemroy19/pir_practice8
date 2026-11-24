import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { apiClient } from "../../api/client";
import { ConstructorQuestion, fromBank, TestConstructor } from "../../components/test-draft/TestConstructor";
import { DEFAULT_TEST_SETTINGS, TestSettings } from "../../components/test-draft/TestSettingsFields";
import { newSaveKey } from "../../components/test-draft/testDraftStore";
import { formatError } from "../../utils/formatError";

type Initial = { settings: TestSettings; questions: ConstructorQuestion[]; revision?: string };
export function TeacherTestConstructorPage() {
  const { testId } = useParams();
  const [initial, setInitial] = useState<Initial | null>(null);
  const [error, setError] = useState("");
  const [saveKey] = useState(newSaveKey);
  useEffect(() => {
    const request = new AbortController(); setInitial(null); setError("");
    if (!testId) setInitial({ settings: DEFAULT_TEST_SETTINGS, questions: [] });
    else apiClient.get(`/tests/${testId}/`, { signal: request.signal }).then(({ data }) => {
      setInitial({ settings: { title: data.title, description: data.description ?? "", timer_minutes: data.timer_minutes,
        attempts_limit: data.attempts_limit, deadline: data.deadline ? localDeadline(data.deadline) : "",
        result_visibility: data.result_visibility }, revision: data.updated_at,
        questions: data.test_questions.map((item: any) => ({ ...fromBank(item.question_data), overridden_points: item.overridden_points })) });
    }).catch((failure) => { if (!request.signal.aborted) setError(formatError(failure, "Не удалось загрузить тест.")); });
    return () => request.abort();
  }, [testId]);
  if (error) return <div className="ui-error" role="alert">{error}</div>;
  if (!initial) return <p role="status">Загрузка конструктора…</p>;
  return <TestConstructor key={testId ?? "new"} initialSettings={initial.settings} initialQuestions={initial.questions}
    testId={testId ? Number(testId) : undefined} revision={initial.revision} saveKey={saveKey} />;
}
function localDeadline(value: string) {
  return new Date(value).toLocaleString("sv-SE", { timeZone: "Europe/Moscow" }).slice(0, 16).replace(" ", "T");
}
