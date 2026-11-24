import { FormEvent, Fragment, useEffect, useId, useRef, useState } from "react";

import { apiClient } from "../../../api/client";
import { ANSWER_FORMAT_OPTIONS } from "../../../constants/questionTypes";
import { QuestionType } from "../../../types/domain";
import { formatError } from "../../../utils/formatError";
import { Modal } from "../../common/Modal/Modal";
import type { QuestionForm } from "../QuestionFormModal/QuestionFormModal";
import styles from "../QuestionFormModal/QuestionFormModal.module.css";

type Draft = Pick<QuestionForm, "title" | "prompt" | "question_type" | "payload">;
const cognitiveTargets = [
  { value: "theory", label: "Теория", description: "Проверяет знание понятий, определений, правил и свойств" },
  { value: "practice", label: "Практика", description: "Проверяет умение применять знания при решении конкретной задачи" },
] as const;
type CognitiveTarget = typeof cognitiveTargets[number]["value"];

type Props = {
  onClose: () => void;
  onGenerated: (draft: Draft) => void;
};

export function QuestionGenerationModal({ onClose, onGenerated }: Props) {
  const formId = useId();
  const pending = useRef<AbortController | null>(null);
  const topicInput = useRef<HTMLInputElement>(null);
  const [topic, setTopic] = useState("");
  const [questionType, setQuestionType] = useState<QuestionType>("single");
  const [audience, setAudience] = useState("");
  const [cognitiveTarget, setCognitiveTarget] = useState<CognitiveTarget>("theory");
  const [instructions, setInstructions] = useState("");
  const [sourceMaterial, setSourceMaterial] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [confirmingClose, setConfirmingClose] = useState(false);
  const [readyDraft, setReadyDraft] = useState<Draft | null>(null);
  const [error, setError] = useState("");
  const [topicChecked, setTopicChecked] = useState(false);
  const topicError = topicChecked && !topic.trim() ? "Введите тему вопроса." : "";

  useEffect(() => () => pending.current?.abort(), []);

  useEffect(() => {
    if (!confirmingClose && readyDraft) onGenerated(readyDraft);
  }, [confirmingClose, readyDraft, onGenerated]);

  useEffect(() => {
    if (!confirmingClose && !readyDraft) topicInput.current?.focus({ preventScroll: true });
  }, [confirmingClose, readyDraft]);

  function resumeGeneration() {
    setConfirmingClose(false);
  }

  function discardGeneration() {
    pending.current?.abort();
    onClose();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current || confirmingClose || readyDraft) return;
    setTopicChecked(true);
    if (!topic.trim()) return;

    const request = new AbortController();
    pending.current = request;
    setError("");
    setIsGenerating(true);

    try {
      const { data } = await apiClient.post<Draft>("/questions/generate/", {
        topic: topic.trim(),
        question_type: questionType,
        audience,
        cognitive_target: cognitiveTarget,
        instructions,
        source_material: sourceMaterial,
      }, { signal: request.signal, timeout: 40000 });

      if (!request.signal.aborted) setReadyDraft(data);
    } catch (failure) {
      if (!request.signal.aborted) setError(formatError(failure, "Не удалось сгенерировать вопрос. Попробуйте ещё раз."));
    } finally {
      pending.current = null;
      if (!request.signal.aborted) setIsGenerating(false);
    }
  }

  return (
    <Modal
      isOpen
      title={confirmingClose ? "Закрыть без сохранения?" : "Сгенерировать вопрос"}
      size={confirmingClose ? "small" : "wide"}
      lockScroll
      headerTone={confirmingClose ? undefined : "lavender"}
      trapFocus
      closeOnBackdrop={false}
      onClose={confirmingClose ? resumeGeneration : () => setConfirmingClose(true)}
      actions={confirmingClose ? (
        <Fragment key="confirm">
          <button type="button" className="button button-danger" onClick={discardGeneration}>
            Закрыть без сохранения
          </button>
          <button type="button" autoFocus className="button button-primary" onClick={resumeGeneration}>
            Продолжить
          </button>
        </Fragment>
      ) : (
        <Fragment key="generation">
          <button type="button" className="button button-secondary" onClick={() => setConfirmingClose(true)}>
            Отмена
          </button>
          <button
            type="submit"
            form={formId}
            className="button button-primary"
            disabled={isGenerating || Boolean(readyDraft)}
          >
            {isGenerating ? "Генерируем вопрос…" : "Создать черновик"}
          </button>
        </Fragment>
      )}
    >
      {confirmingClose && <p className={styles.closeMessage}>Введённые параметры и черновик будут потеряны.</p>}
      <div hidden={confirmingClose}>
        <form id={formId} className={styles.grid} onSubmit={handleSubmit} noValidate>
          <div className={styles.generationRow}>
            <div>
              <label className={styles.field}>
                <span>Тема <span className={styles.asterisk} aria-hidden="true">*</span></span>
                <input
                  required
                  ref={topicInput}
                autoFocus
                  maxLength={200}
                  placeholder="Введите тему вопроса"
                  value={topic}
                  aria-invalid={Boolean(topicError)}
                  aria-describedby={topicError ? `${formId}-topic-error` : undefined}
                  onChange={(event) => setTopic(event.target.value)}
                />
              </label>
              {topicError && <p id={`${formId}-topic-error`} className={styles.fieldError} role="alert">{topicError}</p>}
            </div>
            <label className={styles.field}>
              <span>Формат ответа <span className={styles.asterisk} aria-hidden="true">*</span></span>
              <select required value={questionType} onChange={(event) => setQuestionType(event.target.value as QuestionType)}>
                {ANSWER_FORMAT_OPTIONS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
          </div>
          <fieldset className={styles.targets}>
            <legend>Что проверяем <span className={styles.asterisk} aria-hidden="true">*</span></legend>
            <div className={styles.targetOptions}>
              {cognitiveTargets.map(({ value, label, description }) => (
                <label key={value} className={styles.target}>
                  <input
                    type="radio"
                    required
                    name={`${formId}-target`}
                    value={value}
                    checked={cognitiveTarget === value}
                    onChange={() => setCognitiveTarget(value)}
                    aria-describedby={`${formId}-${value}`}
                  />
                  <span>
                    {label}
                    <small id={`${formId}-${value}`}>{description}</small>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className={styles.field}>
            <span>Уточнение темы <small>(необязательно)</small></span>
            <textarea
              maxLength={600}
              rows={3}
              placeholder="Укажите, какой аспект темы раскрыть, какие условия учесть и в каком виде ученик должен ответить"
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
            />
          </label>
          <details className={styles.details}>
            <summary>Дополнительные параметры</summary>
            <div className={styles.grid}>
              <label className={styles.field}>
                <span>Для кого <small>(необязательно)</small></span>
                <small id={`${formId}-audience-help`}>Можно указать возраст, класс, курс или уровень подготовки</small>
                <input
                  maxLength={120}
                  placeholder="Например, 14–16 лет, 8 класс, 1 курс или начальный уровень"
                  aria-describedby={`${formId}-audience-help`}
                  value={audience}
                  onChange={(event) => setAudience(event.target.value)}
                />
              </label>
              <label className={styles.field}>
                <span>Учебный материал <small>(необязательно)</small></span>
                <textarea maxLength={3000} rows={4} placeholder="Вставьте отрывок, по которому нужно составить вопрос" value={sourceMaterial} onChange={(event) => setSourceMaterial(event.target.value)} />
              </label>
            </div>
          </details>
          <div role="status" className={styles.announcement}>{isGenerating ? "Генерируем вопрос…" : ""}</div>
          {error && <p className={`ui-error ${styles.apiError}`} role="alert">{error}</p>}
        </form>
      </div>
    </Modal>
  );
}
