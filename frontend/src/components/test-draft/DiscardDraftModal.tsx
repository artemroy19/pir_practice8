import { Modal } from "../common/Modal/Modal";

export function DiscardDraftModal({ onContinue, onDiscard, busy, children }: {
  onContinue: () => void;
  onDiscard: () => void;
  busy?: boolean;
  children: string;
}) {
  return (
    <Modal isOpen size="small" lockScroll trapFocus closeOnBackdrop={false}
      title="Закрыть без сохранения?" onClose={onContinue}
      actions={(
        <>
          <button type="button" className="button button-danger" onClick={onDiscard} disabled={busy}>
            Закрыть без сохранения
          </button>
          <button type="button" className="button button-primary" autoFocus onClick={onContinue}>
            Продолжить редактирование
          </button>
        </>
      )}
    >
      <p>{children}</p>
    </Modal>
  );
}
