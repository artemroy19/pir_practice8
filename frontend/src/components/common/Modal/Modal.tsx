import { KeyboardEvent, ReactNode, useId } from "react";
import styles from "./Modal.module.css";

type Props = {
  isOpen: boolean;
  title: string;
  description?: string;
  eyebrow?: string;
  children: ReactNode;
  actions?: ReactNode;
  onClose: () => void;
  size?: "default" | "small" | "medium" | "wide" | "detail";
  closeOnBackdrop?: boolean;
  closeDisabled?: boolean;
  trapFocus?: boolean;
  headerTone?: "lavender";
  lockScroll?: boolean;
};

export function Modal({
  isOpen, title, description, eyebrow, children, actions, onClose, size = "default",
  closeOnBackdrop = true, closeDisabled = false, trapFocus = false, headerTone, lockScroll = false,
}: Props) {
  const titleId = useId();
  if (!isOpen) return null;

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.stopPropagation();
    }
    if (event.key !== "Tab") return;

    const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
      'button, input, select, textarea, summary, a[href], [tabindex]',
    )).filter((element) => element.tabIndex >= 0 && !element.matches(":disabled") && element.getClientRects().length);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey ? event.target === first : event.target === last) {
      event.preventDefault();
      (event.shiftKey ? last : first)?.focus();
    }
  }

  const sizeClass = {
    default: "",
    small: styles.modalContentSmall,
    medium: styles.modalContentMedium,
    wide: styles.modalContentWide,
    detail: styles.modalContentDetail,
  }[size];
  return (
    <div
      className={`${styles.modalOverlay} ${lockScroll ? styles.lockScroll : ""}`}
      onClick={closeOnBackdrop && !closeDisabled ? onClose : undefined}
    >
      <div
        className={`${styles.modalContent} ${sizeClass}`}
        role="dialog"
        aria-labelledby={titleId}
        aria-modal={trapFocus || undefined}
        onKeyDown={trapFocus ? handleKeyDown : undefined}
        onClick={(event) => event.stopPropagation()}
      >
        <div className={`${styles.modalHeader} ${headerTone === "lavender" ? styles.lavenderHeader : ""}`}>
          <div>
            {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
            <h2 id={titleId} className={styles.modalTitle}>{title}</h2>
            {description ? <p className={styles.modalDescription}>{description}</p> : null}
          </div>
          <button type="button" className={styles.closeButton} onClick={onClose} disabled={closeDisabled} autoFocus={Boolean(eyebrow)} aria-label="Закрыть">
            ×
          </button>
        </div>
        <div className={styles.modalBody}>{children}</div>
        {actions ? <div className={styles.modalFooter}>{actions}</div> : null}
      </div>
    </div>
  );
}
