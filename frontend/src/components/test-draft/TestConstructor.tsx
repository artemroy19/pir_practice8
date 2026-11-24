import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DndContext, DragEndEvent, PointerSensor, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, arrayMove, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { apiClient } from "../../api/client";
import { RequiredMark } from "../common/RequiredMark/RequiredMark";
import { Modal } from "../common/Modal/Modal";
import { SectionHeader } from "../layout/SectionHeader/SectionHeader";
import { QuestionForm, QuestionFormModal } from "../question-bank/QuestionFormModal/QuestionFormModal";
import { DiscardDraftModal } from "./DiscardDraftModal";
import { SortableQuestion } from "./SortableQuestion";
import { TestSettings, TestSettingsFields } from "./TestSettingsFields";
import { useDraftExit } from "./useDraftExit";
import { getQuestionTypeLabel } from "../../constants/questionTypes";
import { extractList } from "../../utils/extractList";
import { formatError } from "../../utils/formatError";
import styles from "../../pages/teacher/TeacherTestConstructorPage.module.css";

export type ConstructorQuestion = QuestionForm & {
  rowId: number;
  expected_updated_at?: string;
  overridden_points?: string | null;
  cognitive_target?: "theory" | "practice";
};
type Category = { id: number; title: string };
export type BankQuestionData = Omit<QuestionForm, "category" | "base_points"> & {
  id: number; updated_at: string; category: Category | null; base_points: string | number;
};
export function fromBank(question: BankQuestionData): ConstructorQuestion {
  return { id: question.id, rowId: question.id, title: question.title, prompt: question.prompt,
    question_type: question.question_type, payload: question.payload, category: question.category?.id ?? null,
    base_points: String(question.base_points), expected_updated_at: question.updated_at };
}

export function TestConstructor({ initialSettings, initialQuestions, testId, revision, generated = false, saveKey, onSaved }: {
  initialSettings: TestSettings; initialQuestions: ConstructorQuestion[]; testId?: number; revision?: string;
  generated?: boolean; saveKey: string; onSaved?: () => void;
}) {
  const navigate = useNavigate();
  const [settings, setSettings] = useState(initialSettings);
  const [questions, setQuestions] = useState(initialQuestions);
  const snapshot = (settings: TestSettings, questions: ConstructorQuestion[]) => JSON.stringify({
    settings, questions: questions.map((q) => ({ ...q, base_points: Number(q.base_points) })),
  });
  const dirty = generated || snapshot(settings, questions) !== snapshot(initialSettings, initialQuestions);
  const { blocker, release } = useDraftExit(dirty);
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const [bank, setBank] = useState<ConstructorQuestion[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [bankOpen, setBankOpen] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<ConstructorQuestion | null>(null);
  const [loadingBank, setLoadingBank] = useState(true);
  const [bankError, setBankError] = useState("");
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState("");

  async function loadBank(signal?: AbortSignal) {
    setLoadingBank(true); setBankError("");
    try {
      const [questionResponse, categoryResponse] = await Promise.all([
        apiClient.get("/questions/", { params: { is_bank_question: true }, signal }), apiClient.get("/categories/", { signal }),
      ]);
      setBank(extractList<BankQuestionData>(questionResponse.data).map(fromBank));
      setCategories(extractList<Category>(categoryResponse.data));
    } catch {
      if (!signal?.aborted) setBankError("Не удалось загрузить банк вопросов и категории.");
    } finally { if (!signal?.aborted) setLoadingBank(false); }
  }
  useEffect(() => { const request = new AbortController(); void loadBank(request.signal); return () => request.abort(); }, []);

  function reorder({ active, over }: DragEndEvent) {
    if (!over || active.id === over.id || saving) return;
    setQuestions((previous) => arrayMove(previous, previous.findIndex((q) => q.rowId === active.id), previous.findIndex((q) => q.rowId === over.id)));
  }
  async function save() {
    if (inFlight.current || !questions.length || !settings.title.trim()) return;
    inFlight.current = true; setSaving(true); setError("");
    try {
      await apiClient.post("/tests/save-draft/", {
        test_id: testId, expected_updated_at: revision,
        test: { ...settings, title: settings.title.trim(), deadline: settings.deadline || null },
        questions: questions.map(({ id, title, prompt, question_type, payload, base_points, category, expected_updated_at, overridden_points }) => ({
          id, title, prompt, question_type, payload, base_points, category_id: category, expected_updated_at, overridden_points,
        })),
      }, { headers: { "Idempotency-Key": saveKey } });
      release();
      navigate("/teacher/tests", { replace: true, state: { success: "Тест сохранён. Изменения вопросов применены в банке." } });
      onSaved?.();
    } catch (failure) { setError(formatError(failure, "Не удалось сохранить тест. Повторите сохранение.")); }
    finally { inFlight.current = false; setSaving(false); }
  }
  const included = new Set(questions.flatMap((q) => q.id == null ? [] : [q.id]));
  const matches = bank.filter((q) => `${q.title} ${q.prompt}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <div className={styles.page}>
    <SectionHeader title={generated ? "Проверить черновик теста" : testId ? "Редактирование теста" : "Создание теста"}
      description="Настройте тест и вопросы. Все изменения сохраняются одной кнопкой." />
    {bankError && <p role="alert" className={styles.error}>{bankError}</p>}
    <div className={styles.layout}>
      <TestSettingsFields value={settings} disabled={saving} onChange={(patch) => setSettings((previous) => ({ ...previous, ...patch }))} />
      <section className={styles.questionsCard} aria-label="Вопросы теста">
        <div className={styles.questionsHeader}><div><h3>Вопросы теста <RequiredMark /></h3><p aria-live="polite">Всего: {questions.length}</p></div></div>
        {questions.length === 0 ? <p>В тесте пока нет вопросов</p> :
          <DndContext sensors={sensors} onDragEnd={reorder} accessibility={{ screenReaderInstructions: { draggable: "Для изменения порядка перетащите вопрос мышью или касанием." } }}>
            <SortableContext items={questions.map((q) => q.rowId)} strategy={verticalListSortingStrategy}>
              <div className={styles.questionsList}>{questions.map((question) =>
                <SortableQuestion key={question.rowId} question={{ ...question, id: question.rowId }} disabled={saving}
                  onEdit={() => setEditing(question)} onRemove={() => setQuestions((previous) => previous.filter((q) => q.rowId !== question.rowId))}>
                  {question.cognitive_target && <span>{question.cognitive_target === "theory" ? "Теория" : "Практика"}</span>}
                  {question.overridden_points != null && <small>Баллы в этом тесте: {question.overridden_points}. Изменение баллов в редакторе заменит это значение.</small>}
                  {question.id && <small>Правки обновятся в банке и связанных тестах при сохранении теста.</small>}
                </SortableQuestion>)}</div>
            </SortableContext>
          </DndContext>}
        <button type="button" className="button button-secondary" disabled={saving} onClick={() => { setSelected([]); setSearch(""); setBankOpen(true); }}>Добавить из банка</button>
      </section>
    </div>
    {error && <div className="ui-error" role="alert">{error}</div>}
    <div className={styles.footerActions}>
      <button type="button" className="button button-secondary" disabled={saving} onClick={() => navigate("/teacher/tests")}>Отмена</button>
      <button type="button" className="button button-primary" disabled={saving || !settings.title.trim() || !questions.length} onClick={() => void save()}>{saving ? "Сохраняем…" : "Сохранить тест"}</button>
    </div>
    {editing && <QuestionFormModal categories={categories} question={editing} title="Редактировать вопрос" saveLabel="Применить изменения"
      onClose={() => setEditing(null)} onSave={async (value) => {
        setQuestions((previous) => previous.map((q) => q.rowId === editing.rowId ? { ...q, ...value, overridden_points: Number(q.base_points) !== Number(value.base_points) ? null : q.overridden_points } : q)); setEditing(null);
      }} />}
    {bankOpen && <Modal isOpen title="Банк вопросов" headerTone="lavender" size="medium" trapFocus lockScroll onClose={() => setBankOpen(false)} actions={<>
      <button type="button" className="button button-secondary" onClick={() => setBankOpen(false)}>Отмена</button>
      <button type="button" className="button button-primary" disabled={!selected.length} onClick={() => {
        setQuestions((previous) => [...previous, ...bank.filter((q) => selected.includes(q.id!) && !included.has(q.id!))]); setBankOpen(false);
      }}>Добавить выбранные ({selected.length})</button></>}>
      <label className={styles.bankToolbar}>Поиск вопросов<input autoFocus value={search} onChange={(e) => setSearch(e.target.value)} /></label>
      {loadingBank && <p role="status">Загрузка банка…</p>}
      {bankError && <div role="alert"><p>{bankError}</p><button className="button button-secondary" onClick={() => void loadBank()}>Повторить загрузку</button></div>}
      {!loadingBank && !bankError && matches.length === 0 && <p>Ничего не найдено</p>}
      <div className={styles.bankList}>{matches.map((q) => <label className={styles.bankQuestion} key={q.id}>
        <input type="checkbox" checked={included.has(q.id!) || selected.includes(q.id!)} disabled={included.has(q.id!)}
          onChange={(e) => setSelected((previous) => e.target.checked ? [...previous, q.id!] : previous.filter((id) => id !== q.id))} />
        <span><strong>{q.title}</strong><p>{getQuestionTypeLabel(q.question_type)}{included.has(q.id!) ? " · Уже в тесте" : ""}</p></span>
      </label>)}</div>
    </Modal>}
    {blocker.state === "blocked" && <DiscardDraftModal busy={saving} onContinue={blocker.reset} onDiscard={() => {
      if (inFlight.current) return; release(); blocker.proceed(); onSaved?.();
    }}>Настройки теста и применённые правки вопросов будут потеряны.</DiscardDraftModal>}
  </div>;
}
