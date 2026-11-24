import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiClient } from "../../api/client";
import { TestCard, TestDescriptionModal } from "../../components/tests/TestCard";
import cards from "../../components/tests/TestCard.module.css";
import { ConfirmModal } from "../../components/common/ConfirmModal/ConfirmModal";
import { EmptyState } from "../../components/common/EmptyState/EmptyState";
import { SectionHeader } from "../../components/layout/SectionHeader/SectionHeader";
import { extractList } from "../../utils/extractList";
import styles from "./StudentTestsPage.module.css";

type StudentTest = {
  id: number;
  title: string;
  description: string;
  questions_count: number;
  deadline: string | null;
  timer_minutes: number | null;
  max_score: string;
  attempts_limit?: number | null;
  author_name?: string | null;
  availability: {
    code: "available" | "attempts_exhausted" | "deadline_passed";
    label: string;
    can_start: boolean;
    attempts_used: number;
    attempts_limit: number | null;
  } | null;
};

export function StudentTestsPage() {
  const navigate = useNavigate();
  const [descriptionTest, setDescriptionTest] = useState<StudentTest | null>(null);
  const [tests, setTests] = useState<StudentTest[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [testToStart, setTestToStart] = useState<StudentTest | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError("");
      try {
        const response = await apiClient.get("/tests/available/");
        setTests(extractList(response.data));
      } catch {
        setError("Не удалось загрузить список тестов.");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  const filteredTests = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return tests;
    }
    return tests.filter(
      (test) =>
        test.title.toLowerCase().includes(normalized) ||
        test.description.toLowerCase().includes(normalized),
    );
  }, [query, tests]);

  async function handleStart(testId: number) {
    try {
      const response = await apiClient.post("/attempts/start/", { test: testId });
      navigate(`/test/${testId}/attempt/${response.data.id}`);
    } catch {
      setError("Не удалось начать тест.");
    }
  }

  return (
    <div className="ui-page">
      <SectionHeader
        title="Мои тесты"
        description="Здесь собраны все тесты, назначенные вам преподавателями."
      />

      <div className="ui-toolbar">
        <input
          className={styles.search}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Поиск по названию или описанию"
        />
      </div>

      {error ? <div className="ui-error">{error}</div> : null}
      {loading ? <div className="ui-info">Загрузка тестов...</div> : null}

      {!loading && tests.length === 0 ? (
        <EmptyState title="Тестов пока нет" description="Когда преподаватель назначит вам тесты, они появятся на этой странице." />
      ) : null}

      {!loading && tests.length > 0 && filteredTests.length === 0 ? (
        <EmptyState
          title="Ничего не найдено"
          description="Попробуйте изменить параметры поиска."
        />
      ) : null}

      {!loading && filteredTests.length > 0 ? (
        <div className={cards.grid}>
          {filteredTests.map((test) => <TestCard key={test.id} test={{ ...test, attempts_limit: test.availability?.attempts_limit ?? test.attempts_limit }}
            onDescription={() => setDescriptionTest(test)} extra={<>
              <div><dt>Максимум баллов</dt><dd>{test.max_score}</dd></div>
              <div><dt>Использовано попыток</dt><dd>{test.availability?.attempts_used ?? 0}</dd></div>
            </>}>
            <p className={cards.status}>{test.availability?.can_start ? "Доступен для прохождения" : test.availability?.label ?? "Тест недоступен"}</p>
            <button type="button" className={`button button-primary ${cards.start}`} disabled={!test.availability?.can_start}
              onClick={() => setTestToStart(test)}>Пройти тест</button>
          </TestCard>)}
        </div>
      ) : null}
      {descriptionTest && <TestDescriptionModal test={{ ...descriptionTest, attempts_limit: descriptionTest.availability?.attempts_limit ?? descriptionTest.attempts_limit }} onClose={() => setDescriptionTest(null)} />}

      <ConfirmModal
        isOpen={Boolean(testToStart)}
        title="Начать тест?"
        description={testToStart ? `Вы действительно хотите приступить к тесту "${testToStart.title}"?` : ""}
        confirmLabel="Да, начать"
        cancelLabel="Нет"
        onCancel={() => setTestToStart(null)}
        onConfirm={() => {
          const testId = testToStart?.id;
          setTestToStart(null);
          if (testId) {
            void handleStart(testId);
          }
        }}
      />
    </div>
  );
}
