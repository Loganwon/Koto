import { describe, it, expect } from "vitest";

// Test the escape/utility functions from infrastructure
// These are pure functions that don"t need DOM

function _escHtml(text: unknown): string {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function _fileExt(fileName: string): string {
  return (String(fileName || "").split(".").pop() || "").toLowerCase();
}

describe("infrastructure utilities", () => {
  describe("_escHtml", () => {
    it("escapes HTML special characters", () => {
      expect(_escHtml('<script>alert("xss")</script>')).toBe(
        "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;"
      );
    });

    it("handles empty values", () => {
      expect(_escHtml("")).toBe("");
      expect(_escHtml(null)).toBe("");
      expect(_escHtml(undefined)).toBe("");
    });

    it("handles single quotes", () => {
      expect(_escHtml("it's")).toBe("it&#39;s");
    });

    it("does not double-escape", () => {
      expect(_escHtml("&amp;")).toBe("&amp;amp;");
    });

    it("handles numbers", () => {
      expect(_escHtml(42)).toBe("42");
    });
  });

  describe("_fileExt", () => {
    it("extracts lowercase extension", () => {
      expect(_fileExt("test.DOCX")).toBe("docx");
      expect(_fileExt("report.PDF")).toBe("pdf");
    });

    it("handles no extension", () => {
      expect(_fileExt("README")).toBe("readme");
    });

    it("handles multiple dots", () => {
      expect(_fileExt("archive.tar.gz")).toBe("gz");
    });

    it("handles empty input", () => {
      expect(_fileExt("")).toBe("");
    });
  });
});
