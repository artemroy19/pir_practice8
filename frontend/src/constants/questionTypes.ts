import { QuestionType } from "../types/domain";

export const QUESTION_TYPE_LABELS: Record<QuestionType, string> = {
  single: "Одиночный выбор",
  multiple: "Множественный выбор",
  text: "Краткий ответ",
  extended: "Развёрнутый вопрос",
};

export const getQuestionTypeLabel = (type: QuestionType): string => {
  return QUESTION_TYPE_LABELS[type] || type;
};

export const QUESTION_TYPE_OPTIONS = (Object.keys(QUESTION_TYPE_LABELS) as QuestionType[]).map((value) => ({
  value,
  label: QUESTION_TYPE_LABELS[value],
}));

export const ANSWER_FORMAT_OPTIONS: { value: QuestionType; label: string }[] = [
  { value: "single", label: "Один правильный ответ" },
  { value: "multiple", label: "Несколько правильных ответов" },
  { value: "text", label: "Краткий ответ" },
  { value: "extended", label: "Развёрнутый ответ" },
];
