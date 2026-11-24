import { Fragment, useEffect, useId, useRef, useState } from "react";
import { Modal } from "../../common/Modal/Modal";
import { ANSWER_FORMAT_OPTIONS } from "../../../constants/questionTypes";
import { QuestionType } from "../../../types/domain";
import { formatError } from "../../../utils/formatError";
import styles from "./QuestionFormModal.module.css";

type Category = { id: number; title: string };
type Option = { id: string | number; text: string };

export type QuestionForm = {
  id?: number;
  title: string;
  prompt: string;
  question_type: QuestionType;
  base_points: string;
  payload: any;
  category: number | null;
};

export type QuestionFormInput = Omit<QuestionForm, "base_points" | "category">
  & Partial<Pick<QuestionForm, "base_points" | "category">>;

function initialValues(question?: QuestionFormInput | null) {
  const payload = question?.payload;
  const options: Option[] = Array.isArray(payload?.options) && payload.options.length
    ? payload.options
    : [{ id: "a", text: "Вариант A" }, { id: "b", text: "Вариант B" }];
  return {
    title: question?.title ?? "",
    prompt: question?.prompt ?? "",
    questionType: question?.question_type ?? "single",
    basePoints: String(question?.base_points ?? "1"),
    category: question?.category ?? null,
    options,
    correctOption: (payload?.correct_option ?? options[0].id) as Option["id"] | null,
    correctOptions: (Array.isArray(payload?.correct_options) && payload.correct_options.length ? payload.correct_options : [options[0].id]) as Option["id"][],
    correctAnswers: (Array.isArray(payload?.correct_answers) && payload.correct_answers.length ? payload.correct_answers : [""]) as string[],
  };
}

type Values = ReturnType<typeof initialValues>;

function comparable(value: Values) {
  const { title, prompt, questionType, basePoints, category, options, correctOption, correctOptions, correctAnswers } = value;
  return JSON.stringify({ title, prompt, questionType, category, basePoints: Number.isFinite(Number(basePoints)) ? Number(basePoints) : basePoints,
    ...(questionType === "single" ? { options, correctOption } : {}),
    ...(questionType === "multiple" ? { options, correctOptions: [...correctOptions].sort() } : {}),
    ...(questionType === "text" ? { correctAnswers } : {}),
  });
}

interface Props {
  categories: Category[];
  question?: QuestionFormInput | null;
  onClose: () => void;
  saveLabel?: string;
  title?: string;
  onSave: (question: QuestionForm) => Promise<void>;
}

export function QuestionFormModal({ categories, question, onClose, onSave, saveLabel = "Сохранить", title: dialogTitle }: Props) {
  const fieldId = useId();
  const [initial] = useState(() => initialValues(question));
  const [values, setValues] = useState(initial);
  const [saveError, setSaveError] = useState("");
  const [isSaving, setIsSaving] = useState(false);
  const [showValidation, setShowValidation] = useState(false);
  const [confirmingClose, setConfirmingClose] = useState(false);
  const errorMessage = useRef<HTMLParagraphElement>(null);

  const { title, prompt, questionType, basePoints, category, options, correctOption, correctOptions, correctAnswers } = values;
  const isChoice = questionType === "single" || questionType === "multiple";
  const isSingle = questionType === "single";
  const points = Number(basePoints);
  const validPoints = Number.isFinite(points) && points > 0 && points <= 9999.99
    && Math.abs(points * 100 - Math.round(points * 100)) < 1e-8;
  const titleError = !title.trim() ? "Введите название в банке."
    : Array.from(title.trim()).length > 255 ? "Название должно содержать не больше 255 символов." : "";
  const promptError = !prompt.trim() ? "Введите текст для ученика."
    : Array.from(prompt.trim()).length > 30000 ? "Текст должен содержать не больше 30 000 символов." : "";
  const pointsError = validPoints ? "" : "Введите число больше 0 и не больше 9999,99, до двух знаков после запятой.";
  const hasCorrectOption = isSingle
    ? options.some((option) => option.id === correctOption)
    : options.some((option) => correctOptions.includes(option.id));
  const choiceError = options.length < 2 || options.some((option) => !option.text.trim())
    ? "Заполните как минимум два варианта и удалите пустые."
    : !hasCorrectOption ? "Отметьте правильный ответ." : "";
  const textError = correctAnswers.some((answer) => answer.trim()) ? "" : "Укажите хотя бы один допустимый ответ.";
  const answerError = isChoice ? choiceError : questionType === "text" ? textError : "";

  function errorProps(field: string, message: string) {
    const invalid = showValidation && Boolean(message);
    return {
      "aria-invalid": invalid || undefined,
      "aria-describedby": invalid ? `${fieldId}-${field}-error` : undefined,
    };
  }

  function fieldError(field: string, message: string) {
    return showValidation && message
      ? <small id={`${fieldId}-${field}-error`} className={styles.fieldError} role="alert">{message}</small>
      : null;
  }

  const asterisk = <span className={styles.asterisk} aria-hidden="true">*</span>;

  useEffect(() => {
    if (saveError && !confirmingClose) errorMessage.current?.scrollIntoView({ block: "nearest" });
  }, [saveError, confirmingClose]);

  function update(next: Partial<Values>) {
    setValues((previous) => ({ ...previous, ...next }));
  }

  function addOption() {
    let index = options.length;
    const optionId = (position: number) => position < 26 ? String.fromCharCode(97 + position) : `option-${position + 1}`;
    while (options.some((option) => option.id === optionId(index))) index += 1;
    update({ options: [...options, { id: optionId(index), text: "" }] });
  }

  function removeOption(id: Option["id"]) {
    update({
      options: options.filter((option) => option.id !== id),
      correctOption: correctOption === id ? null : correctOption,
      correctOptions: correctOptions.filter((selected) => selected !== id),
    });
  }

  function nextPoints(direction: 1 | -1) {
    return (Math.round(points * 100) + direction * 50) / 100;
  }

  function canStepPoints(direction: 1 | -1) {
    const next = nextPoints(direction);
    return (basePoints === "" || validPoints || points === 0) && next >= 0 && next <= 9999.99;
  }

  function stepPoints(direction: 1 | -1) {
    if (canStepPoints(direction)) update({ basePoints: String(nextPoints(direction)) });
  }

  async function handleSave() {
    if (isSaving) return;
    setShowValidation(true);
    if (titleError || promptError || pointsError || answerError) return;

    let payload = {};
    if (isChoice) {
      payload = isSingle ? { options, correct_option: correctOption } : { options, correct_options: correctOptions };
    } else if (questionType === "text") {
      payload = { correct_answers: correctAnswers.filter((answer) => answer.trim()) };
    }

    setIsSaving(true);
    setSaveError("");
    try {
      await onSave({
        id: question?.id,
        title: title.trim(),
        prompt: prompt.trim(),
        question_type: questionType,
        base_points: basePoints,
        category,
        payload,
      });
    } catch (error) {
      setSaveError(formatError(error, "Не удалось сохранить вопрос."));
    } finally {
      setIsSaving(false);
    }
  }

  function handleClose() {
    if (isSaving) return;
    if (comparable(values) !== comparable(initial)) {
      setConfirmingClose(true);
    } else {
      onClose();
    }
  }

  function resumeEditing() {
    setConfirmingClose(false);
  }

  const editorTitle = question?.id != null ? "Редактировать вопрос" : "Создать вопрос";
  return (
    <Modal
      isOpen
      lockScroll
      size={confirmingClose ? "small" : "medium"}
      headerTone={confirmingClose ? undefined : "lavender"}
      title={confirmingClose ? "Закрыть без сохранения?" : (dialogTitle ?? editorTitle)}
      closeOnBackdrop={false}
      closeDisabled={isSaving}
      trapFocus
      onClose={confirmingClose ? resumeEditing : handleClose}
      actions={confirmingClose ? (
        <Fragment key="confirm">
          <button type="button" className="button button-danger" onClick={onClose}>
            Закрыть без сохранения
          </button>
          <button type="button" autoFocus className="button button-primary" onClick={resumeEditing}>
            Продолжить редактирование
          </button>
        </Fragment>
      ) : (
        <Fragment key="editor">
          <button type="button" className="button button-secondary" onClick={handleClose} disabled={isSaving}>
            Отмена
          </button>
          <button type="button" className="button button-primary" onClick={handleSave} disabled={isSaving}>
            {isSaving ? "Сохраняем…" : saveLabel}
          </button>
        </Fragment>
      )}
    >
      {confirmingClose ? (
        <p className={styles.closeMessage}>Введённые данные будут потеряны.</p>
      ) : (
        <>
          <div className={styles.grid}>
            <label className={styles.field}>
              <span>Название в банке {asterisk}</span>
              <input
                autoFocus
                required
                {...errorProps("title", titleError)}
                value={title}
                onChange={(event) => update({ title: event.target.value })}
                placeholder="Введите название вопроса"
              />
              {fieldError("title", titleError)}
            </label>

            <label className={styles.field}>
              <span>Формат ответа {asterisk}</span>
              <select required value={questionType} onChange={(event) => update({ questionType: event.target.value as QuestionType })}>
                {ANSWER_FORMAT_OPTIONS.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>

            <label className={styles.field}>
              <span>Текст для ученика {asterisk}</span>
              <textarea required {...errorProps("prompt", promptError)} value={prompt} rows={4}
                onChange={(event) => update({ prompt: event.target.value })} />
              {fieldError("prompt", promptError)}
            </label>

            <div className={styles.metadata}>
              <label className={styles.field}>
                <span>Категория</span>
                <select value={category ?? ""} onChange={(event) => update({
                  category: event.target.value ? Number(event.target.value) : null,
                })}>
                  <option value="">Без категории</option>
                  {categories.map(({ id, title }) => <option key={id} value={id}>{title}</option>)}
                </select>
              </label>
              <div className={styles.field}>
                <label className={styles.fieldLabel} htmlFor={`${fieldId}-points`}>Баллы {asterisk}</label>
                <div className={styles.pointsControl}>
                  <input
                    id={`${fieldId}-points`}
                    type="number"
                    inputMode="decimal"
                    required
                    min="0"
                    max="9999.99"
                    step="any"
                    {...errorProps("points", pointsError)}
                    value={basePoints}
                    onChange={(event) => update({ basePoints: event.target.value })}
                    onKeyDown={(event) => {
                      if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                        event.preventDefault();
                        stepPoints(event.key === "ArrowUp" ? 1 : -1);
                      }
                    }}
                  />
                  <div className={styles.pointsArrows}>
                    <button type="button" aria-label="Увеличить баллы на 0,5" disabled={!canStepPoints(1)}
                      onClick={() => stepPoints(1)}>▴</button>
                    <button type="button" aria-label="Уменьшить баллы на 0,5" disabled={!canStepPoints(-1)}
                      onClick={() => stepPoints(-1)}>▾</button>
                  </div>
                </div>
                {fieldError("points", pointsError)}
              </div>
            </div>
          </div>

          {isChoice && (
            <fieldset className={styles.section} {...errorProps("answers", choiceError)}>
              <legend>Варианты ответа {asterisk}</legend>
              {options.map((option, index) => (
                <div key={option.id} className={styles.inlineRow}>
                  <label>
                    <input
                      type={isSingle ? "radio" : "checkbox"}
                      name={isSingle ? `${fieldId}-correct` : undefined}
                      aria-label={`Отметить вариант ${index + 1} как правильный`}
                      checked={isSingle ? correctOption === option.id : correctOptions.includes(option.id)}
                      onChange={(event) => isSingle
                        ? update({ correctOption: option.id })
                        : update({ correctOptions: event.target.checked
                          ? [...correctOptions, option.id]
                          : correctOptions.filter((id) => id !== option.id) })}
                    />
                    <span>{index + 1}</span>
                  </label>
                  <input
                    type="text"
                    required
                    {...errorProps("answers", !option.text.trim() ? choiceError : "")}
                    aria-label={`Вариант ответа ${index + 1}`}
                    value={option.text}
                    onChange={(event) => update({
                      options: options.map((item) => item.id === option.id ? { ...item, text: event.target.value } : item),
                    })}
                  />
                  {options.length > 2 && (
                    <button type="button" className="button button-secondary" onClick={() => removeOption(option.id)}>
                      Удалить
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className="button button-secondary button-full" onClick={addOption}>
                Добавить вариант
              </button>
              {fieldError("answers", choiceError)}
            </fieldset>
          )}

          {questionType === "text" && (
            <fieldset className={styles.section} {...errorProps("answers", textError)}>
              <legend>Допустимые ответы {asterisk}</legend>
              <p className={styles.hint}>Укажите хотя бы один допустимый ответ.</p>
              {correctAnswers.map((answer, index) => (
                <div key={index} className={`${styles.inlineRow} ${styles.answerRow}`}>
                  <input
                    type="text"
                    aria-label={`Допустимый ответ ${index + 1}`}
                    value={answer}
                    onChange={(event) => update({
                      correctAnswers: correctAnswers.map((item, position) => index === position ? event.target.value : item),
                    })}
                  />
                  {correctAnswers.length > 1 && (
                    <button type="button" className="button button-secondary" onClick={() => update({
                      correctAnswers: correctAnswers.filter((_, position) => position !== index),
                    })}>
                      Удалить
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className="button button-secondary button-full" onClick={() => update({
                correctAnswers: [...correctAnswers, ""],
              })}>
                Добавить ответ
              </button>
              {fieldError("answers", textError)}
            </fieldset>
          )}

          {questionType === "extended" && <p className={styles.hint}>Развёрнутый ответ проверяет преподаватель.</p>}
          {saveError && <p ref={errorMessage} className={`ui-error ${styles.apiError}`} role="alert">{saveError}</p>}
        </>
      )}
    </Modal>
  );
}
