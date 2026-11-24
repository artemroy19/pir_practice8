import { RequiredMark } from "../common/RequiredMark/RequiredMark";
import required from "../common/RequiredMark/RequiredMark.module.css";
import styles from "../../pages/teacher/TeacherTestConstructorPage.module.css";

export type TestSettings = {
  title: string;
  description: string;
  timer_minutes: number | null;
  attempts_limit: number | null;
  deadline: string;
  result_visibility: "score_only" | "score_with_review";
};

export const DEFAULT_TEST_SETTINGS: TestSettings = {
  title: "",
  description: "",
  timer_minutes: null,
  attempts_limit: null,
  deadline: "",
  result_visibility: "score_with_review",
};

export function TestSettingsFields({ value, onChange, disabled }: {
  value: TestSettings;
  onChange: (patch: Partial<TestSettings>) => void;
  disabled?: boolean;
}) {
  return (
    <fieldset className={`${styles.settingsCard} ${required.fields}`} disabled={disabled}>
      <label>
        <span>Название теста <RequiredMark /></span>
        <input required maxLength={255} value={value.title} onChange={(event) => onChange({ title: event.target.value })} />
      </label>
      <label>
        Описание
        <textarea rows={4} value={value.description} onChange={(event) => onChange({ description: event.target.value })} />
      </label>
      <label>
        Таймер в минутах
        <input type="number" min={1} value={value.timer_minutes ?? ""} onChange={(event) => onChange({
          timer_minutes: event.target.value ? Number(event.target.value) : null,
        })} />
      </label>
      <label>
        Лимит попыток
        <input type="number" min={1} value={value.attempts_limit ?? ""} onChange={(event) => onChange({
          attempts_limit: event.target.value ? Number(event.target.value) : null,
        })} />
      </label>
      <label>
        Дедлайн
        <input type="datetime-local" value={value.deadline} onChange={(event) => onChange({ deadline: event.target.value })} />
      </label>
      <label>
        <span>Видимость результатов <RequiredMark /></span>
        <select required value={value.result_visibility} onChange={(event) => onChange({
          result_visibility: event.target.value as TestSettings["result_visibility"],
        })}>
          <option value="score_only">Только балл</option>
          <option value="score_with_review">Балл с разбором</option>
        </select>
      </label>
    </fieldset>
  );
}
