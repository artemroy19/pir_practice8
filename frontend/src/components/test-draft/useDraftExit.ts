import { useCallback, useEffect, useRef } from "react";
import { useBlocker } from "react-router-dom";

export function useDraftExit(dirty: boolean) {
  const released = useRef(false);
  const blocker = useBlocker(useCallback(() => dirty && !released.current, [dirty]));
  useEffect(() => {
    if (!dirty) return;
    function warn(event: BeforeUnloadEvent) {
      if (released.current) return;
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const release = useCallback(() => { released.current = true; }, []);
  return { blocker, release };
}
