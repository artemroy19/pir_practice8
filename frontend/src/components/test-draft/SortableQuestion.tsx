import { ReactNode } from "react";
import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import { getQuestionTypeLabel } from "../../constants/questionTypes";
import { QuestionType } from "../../types/domain";
import styles from "../../pages/teacher/TeacherTestConstructorPage.module.css";

export function SortableQuestion({ question, onRemove, onEdit, children, disabled }: {
  question: { id: number; title: string; question_type: QuestionType };
  onRemove: () => void;
  onEdit?: () => void;
  children?: ReactNode;
  disabled?: boolean;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition } = useSortable({ id: question.id, disabled });
  return (
    <div ref={setNodeRef} style={{ transform: CSS.Transform.toString(transform), transition }} className={styles.questionCard}>
      <button ref={setActivatorNodeRef} type="button" className={styles.dragHandle} {...attributes} {...listeners} disabled={disabled} tabIndex={-1}
        aria-label={`Перетащить вопрос «${question.title}»`}>::</button>
      <div className={styles.questionInfo}>
        {onEdit ? (
          <button type="button" className={styles.editQuestion} onClick={onEdit} disabled={disabled}>
            {question.title}
          </button>
        ) : <strong>{question.title}</strong>}
        <span>{getQuestionTypeLabel(question.question_type)}</span>
        {children}
      </div>
      <button type="button" className={styles.removeButton} onClick={onRemove} disabled={disabled}>
        Убрать
      </button>
    </div>
  );
}
