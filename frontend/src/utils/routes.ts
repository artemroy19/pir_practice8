import type { UserRole } from "../types/domain";

export function getDefaultRoute(role?: UserRole | null) {
  return role === "teacher" || role === "admin" ? "/teacher/tests" : "/tests";
}
