/**
 * Shared HTML sanitization — single source of truth for escHtml / escapeHtml.
 *
 * Previously duplicated across 10+ files (main.ts, settings.ts, skill-*.ts, etc.).
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
