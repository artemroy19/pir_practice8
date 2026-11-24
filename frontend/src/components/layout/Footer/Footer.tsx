import { PRODUCT_NAME, PRODUCT_VERSION } from "../../common/Brand/Brand";
import footerStyles from "./Footer.module.css";

export function Footer() {
  return (
    <footer className={footerStyles.footer}>
      <span>{PRODUCT_NAME} · версия {PRODUCT_VERSION}</span>
      <span>Автор: Ройтман Артём</span>
    </footer>
  );
}
