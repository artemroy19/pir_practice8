import type { QuestionForm } from "../question-bank/QuestionFormModal/QuestionFormModal";
import type { QuestionType } from "../../types/domain";

export const MAX_TEST_QUESTIONS = 12;
export const GOAL_LABELS = { theory: "Теория", practice: "Практика" } as const;

export type DraftQuestion = Pick<QuestionForm, "title" | "prompt" | "question_type" | "payload">
  & Partial<Pick<QuestionForm, "base_points" | "category">> & {
    position_id: number;
    cognitive_target: keyof typeof GOAL_LABELS;
  };

export type GeneratedTest = {
  title: string;
  description: string;
  questions: DraftQuestion[];
};

export type FormatCounts<T = number> = Record<QuestionType, T>;
