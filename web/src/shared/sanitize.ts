/**
 * Shared HTML sanitization — single source of truth for escHtml / escapeHtml.
 *
 * Previously duplicated across many feature modules.
 * All callers should import from here to avoid drift.
 */

/** Escape HTML special characters to prevent XSS. */
export function escHtml(value: unknown): string {
  const s = String(value ?? "");
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Alias for backward compatibility. */
export const escapeHtml = escHtml;
