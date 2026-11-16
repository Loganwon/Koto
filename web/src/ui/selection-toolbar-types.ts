// @ts-nocheck
/**
 * Selection Toolbar — AI context bar, selection tooltip, PPTX table extract,
 * HTML table extract, toolbar positioning engine.
 * Workspace selection toolbar.
 */

export interface ToolbarConfig {
  centerX: number;
  top: number;
  bottom: number;
  left?: number;
  right?: number;
}

export interface PositionResult {
  left: number;
  top: number;
  centerX: number;
}

export interface SelectionBounds {
  top: number;
  bottom: number;
  left: number;
  right: number;
  centerX: number;
}

export interface PinnedSelectionContext {
  text: string;
  previewText: string;
  sourcePath: string;
  sourceName: string;
  sourceType: string;
  kind?: string;
  rawText?: string;
  sheetName?: string;
  rangeA1?: string;
  rows?: number;
  cols?: number;
  anchor_text?: string;
  anchor_start_offset?: number;
  anchor_end_offset?: number;
  anchor_occurrence?: number;
  anchor_context_before?: string;
  anchor_context_after?: string;
  slideIndex?: number;
  shapeId?: number;
  shapeName?: string;
  pageStart?: number;
  pageEnd?: number;
}

export interface DocxSelectionPayload {
  kind: string;
  rawText: string;
  aiText: string;
  previewText: string;
  countLabel: string;
  tableElement: HTMLElement | null;
  anchor_text?: string;
  anchor_start_offset?: number;
  anchor_end_offset?: number;
  anchor_occurrence?: number;
  anchor_context_before?: string;
  anchor_context_after?: string;
}

export interface DocxAnchorMeta {
  anchor_text: string;
  anchor_start_offset: number;
  anchor_end_offset: number;
  anchor_occurrence: number;
  anchor_context_before: string;
  anchor_context_after: string;
}

export interface PptxTableSelection {
  anchorRow: number;
  anchorCol: number;
  headRow: number;
  headCol: number;
  startRow: number;
  endRow: number;
  startCol: number;
  endCol: number;
  rows: number;
  cols: number;
}
