import { ReactNode } from "react";
import { Modal } from "../common/Modal/Modal";
import styles from "./TestCard.module.css";

export type TestSummary = {
  id: number; title: string; description: string; questions_count: number;
  timer_minutes: number | null; attempts_limit?: number | null; deadline: string | null; author_name?: string | null;
};
export function deadlineLabel(value: string | null) {
  return value ? new Date(value).toLocaleString("ru-RU") : "Без дедлайна";
}
export function TestCard({ test, onDescription, children, extra }: {
  test: TestSummary; onDescription: () => void; children: ReactNode; extra?: ReactNode;
}) {
  return <article className={styles.card}>
    <button type="button" className={styles.title} onClick={onDescription}>{test.title}</button>
    <p className={styles.preview}>{test.description || "Описание не указано."}</p>
    <div className={styles.summary}><span>{test.questions_count} вопросов</span><button type="button" onClick={onDescription}>Описание</button></div>
    <dl className={styles.meta}>
      <div><dt>Время</dt><dd>{test.timer_minutes ? `${test.timer_minutes} мин` : "Без таймера"}</dd></div>
      <div><dt>Попытки</dt><dd>{test.attempts_limit == null ? "Без лимита" : test.attempts_limit}</dd></div>
      <div><dt>Дедлайн</dt><dd>{deadlineLabel(test.deadline)}</dd></div>
      {extra}
    </dl>
    <div className={styles.actions}>{children}</div>
  </article>;
}
export function TestDescriptionModal({ test, onClose }: { test: TestSummary; onClose: () => void }) {
  return <Modal isOpen title={test.title} eyebrow="Описание теста" description={`${test.questions_count} вопросов`}
    onClose={onClose} size="detail" headerTone="lavender" trapFocus lockScroll>
    <p className={styles.fullDescription}>{test.description || "Описание не указано."}</p>
    <dl className={`${styles.meta} ${styles.details}`}>
      <div><dt>Время</dt><dd>{test.timer_minutes ? `${test.timer_minutes} мин` : "Без таймера"}</dd></div>
      <div><dt>Попытки</dt><dd>{test.attempts_limit == null ? "Без лимита" : test.attempts_limit}</dd></div>
      <div><dt>Дедлайн</dt><dd>{deadlineLabel(test.deadline)}</dd></div>
      <div><dt>Автор теста</dt><dd>{test.author_name || "Не указан"}</dd></div>
    </dl>
  </Modal>;
}
