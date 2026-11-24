import styles from "./Brand.module.css";

export const PRODUCT_NAME = "РепИТ";
export const PRODUCT_VERSION = "0.0";

export function Brand({ large = false }: { large?: boolean }) {
  return <span className={`${styles.brand} ${large ? styles.large : ""}`}>{PRODUCT_NAME}</span>;
}
