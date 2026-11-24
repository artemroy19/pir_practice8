import { RequiredMark } from "../common/RequiredMark/RequiredMark";
import required from "../common/RequiredMark/RequiredMark.module.css";
import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiClient } from "../../api/client";
import { ANSWER_FORMAT_OPTIONS } from "../../constants/questionTypes";
import { formatError } from "../../utils/formatError";
import { Modal } from "../common/Modal/Modal";
import { DiscardDraftModal } from "./DiscardDraftModal";
import { useTestDraft } from "./testDraftStore";
import { FormatCounts, GeneratedTest, MAX_TEST_QUESTIONS } from "./types";
import { useDraftExit } from "./useDraftExit";
import styles from "./TestGenerationModal.module.css";

const INITIAL_COUNTS: FormatCounts<string> = { single: "3", multiple: "1", text: "2", extended: "0" };

function validCount(value: string) {
  return /^\d+$/.test(value) && Number(value) <= MAX_TEST_QUESTIONS;
}

function nextTotal(counts: FormatCounts<string>) {
  return Object.values(counts).reduce((sum, count) => sum + (validCount(count) ? Number(count) : 0), 0);
}

export function TestGenerationModal({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const openDraft = useTestDraft((state) => state.open);
  const formId = useId();
  const pending = useRef<AbortController | null>(null);
  const [topic, setTopic] = useState("");
  const [counts, setCounts] = useState(INITIAL_COUNTS);
  const [theory, setTheory] = useState("2");
  const [practice, setPractice] = useState("4");
  const [audience, setAudience] = useState("");
  const [instructions, setInstructions] = useState("");
  const [sourceMaterial, setSourceMaterial] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmClose, setConfirmClose] = useState(false);
  const [draft, setDraft] = useState<GeneratedTest | null>(null);
  const total = nextTotal(counts);
  const dirty = Boolean(topic || audience || instructions || sourceMaterial || theory !== "2" || practice !== "4"
    || Object.values(counts).some((value, index) => value !== Object.values(INITIAL_COUNTS)[index]) || busy || draft);
  const { blocker, release } = useDraftExit(dirty);
  const navigatingAway = blocker.state === "blocked";
  const showConfirmation = confirmClose || navigatingAway;
  const topicError = checked && !topic.trim() ? "Введите тему теста." : "";
  const totalError = total < 1 || total > MAX_TEST_QUESTIONS
    ? `Укажите от 1 до ${MAX_TEST_QUESTIONS} вопросов.` : "";
  const goalError = !validCount(theory) || !validCount(practice) || Number(theory) + Number(practice) !== total
    ? `Введите целые неотрицательные числа с суммой ${total}.` : "";

  useEffect(() => () => pending.current?.abort(), []);

  useEffect(() => {
    if (!draft || showConfirmation) return;
    release();
    openDraft(draft);
    navigate("/teacher/tests/draft");
  }, [draft, showConfirmation, release, openDraft, navigate]);

  function changeCount(key: keyof FormatCounts, value: string) {
    const next = { ...counts, [key]: value };
    const nextSize = nextTotal(next);
    const nextTheory = Math.min(validCount(theory) ? Number(theory) : 0, nextSize);
    setCounts(next);
    setTheory(String(nextTheory));
    setPractice(String(nextSize - nextTheory));
  }

  function changeGoal(goal: "theory" | "practice", value: string) {
    const opposite = validCount(value) && Number(value) <= total ? String(total - Number(value)) : "";
    setTheory(goal === "theory" ? value : opposite);
    setPractice(goal === "practice" ? value : opposite);
  }

  function requestClose() {
    if (dirty) setConfirmClose(true);
    else onClose();
  }

  function leave() {
    pending.current?.abort();
    release();
    if (blocker.state === "blocked") blocker.proceed();
    onClose();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || draft) return;
    setChecked(true);
    if (!topic.trim() || !Object.values(counts).every(validCount) || totalError || goalError) return;
    const request = new AbortController();
    pending.current = request;
    setBusy(true);
    setError("");
    try {
      const { data } = await apiClient.post<GeneratedTest>("/tests/generate/", {
        topic: topic.trim(),
        counts: Object.fromEntries(Object.entries(counts).map(([key, value]) => [key, Number(value)])),
        theory: Number(theory),
        practice: Number(practice),
        audience, instructions, source_material: sourceMaterial,
      }, { signal: request.signal, timeout: 80000 });
      if (!request.signal.aborted) setDraft(data);
    } catch (failure) {
      if (!request.signal.aborted) setError(formatError(failure, "Не удалось сгенерировать тест. Попробуйте ещё раз."));
    } finally {
      pending.current = null;
      if (!request.signal.aborted) setBusy(false);
    }
  }

  if (showConfirmation) {
    return (
      <DiscardDraftModal onDiscard={leave} onContinue={() => {
        if (blocker.state === "blocked") blocker.reset();
        setConfirmClose(false);
      }}>
        Параметры генерации и её результат будут потеряны.
      </DiscardDraftModal>
    );
  }

  return (
    <Modal isOpen size="medium" lockScroll headerTone="lavender" trapFocus closeOnBackdrop={false}
      title="Сгенерировать тест" onClose={requestClose}
      actions={(
        <>
          <span className={styles.total} aria-live="polite">Всего вопросов: {total}</span>
          <button type="button" className="button button-secondary" onClick={requestClose}>Отмена</button>
          <button type="submit" form={formId} className="button button-primary" disabled={busy || Boolean(draft)}>
            {busy ? "Генерируем черновик…" : "Сгенерировать черновик"}
          </button>
        </>
      )}
    >
      <form id={formId} onSubmit={handleSubmit} noValidate>
        <fieldset className={`${styles.form} ${required.fields}`} disabled={busy}>
          <label>
            <span>Тема теста <RequiredMark /></span>
            <input required autoFocus placeholder="Введите тему теста" value={topic} maxLength={200}
              aria-invalid={Boolean(topicError)} aria-describedby={topicError ? `${formId}-topic` : undefined}
              onChange={(event) => setTopic(event.target.value)} />
            {topicError && <span className={styles.error} id={`${formId}-topic`} role="alert">{topicError}</span>}
          </label>
          <fieldset className={styles.section}>
            <legend>Количество вопросов по форматам ответа <RequiredMark /></legend>
            <div className={styles.columns}>
              {ANSWER_FORMAT_OPTIONS.map(({ value, label }) => {
                const invalid = checked && !validCount(counts[value]);
                return (
                  <label key={value}>
                    <span>{label} <RequiredMark /></span>
                    <input type="number" min={0} max={MAX_TEST_QUESTIONS} step={1} required value={counts[value]}
                      aria-invalid={invalid} aria-describedby={invalid ? `${formId}-${value}` : undefined}
                      onChange={(event) => changeCount(value, event.target.value)} />
                    {invalid && <span className={styles.error} id={`${formId}-${value}`} role="alert">
                      Введите целое число от 0 до {MAX_TEST_QUESTIONS}.
                    </span>}
                  </label>
                );
              })}
            </div>
            {checked && totalError && <p className={styles.error} role="alert">{totalError}</p>}
          </fieldset>
          <fieldset className={styles.section}>
            <legend>Что проверяем <RequiredMark /></legend>
            <div className={styles.columns}>
              <label>
                <span>Теория <RequiredMark /></span>
                <small>Знание понятий, определений, правил и свойств.</small>
                <input type="number" min={0} max={Math.min(total, MAX_TEST_QUESTIONS)} step={1} required
                  value={theory} aria-invalid={checked && Boolean(goalError)}
                  aria-describedby={checked && goalError ? `${formId}-goals` : undefined}
                  onChange={(event) => changeGoal("theory", event.target.value)} />
              </label>
              <label>
                <span>Практика <RequiredMark /></span>
                <small>Применение знаний при решении конкретной задачи.</small>
                <input type="number" min={0} max={Math.min(total, MAX_TEST_QUESTIONS)} step={1} required
                  value={practice} aria-invalid={checked && Boolean(goalError)}
                  aria-describedby={checked && goalError ? `${formId}-goals` : undefined}
                  onChange={(event) => changeGoal("practice", event.target.value)} />
              </label>
            </div>
            {checked && goalError && <p className={styles.error} id={`${formId}-goals`} role="alert">{goalError}</p>}
          </fieldset>
          <details open={advanced} onToggle={(event) => setAdvanced(event.currentTarget.open)}>
            <summary>Дополнительные параметры</summary>
            <div className={styles.form}>
              <label>
                Для кого
                <input placeholder="Например, 14–16 лет, 8 класс, 1 курс или начальный уровень" maxLength={120}
                  value={audience} onChange={(event) => setAudience(event.target.value)} />
              </label>
              <label>
                Акценты темы
                <textarea placeholder="Какие аспекты включить, что подчеркнуть и что оставить за рамками" maxLength={600}
                  value={instructions} onChange={(event) => setInstructions(event.target.value)} />
              </label>
              <label>
                Учебный материал
                <textarea placeholder="Вставьте отрывок, на который нужно опираться" maxLength={3000}
                  value={sourceMaterial} onChange={(event) => setSourceMaterial(event.target.value)} />
              </label>
            </div>
          </details>
        </fieldset>
      </form>
      {error && <p className="ui-error" role="alert">{error}</p>}
    </Modal>
  );
}
