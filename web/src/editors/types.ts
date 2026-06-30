export interface WorkspaceEditor {
  render(data: any, ...args: any[]): Promise<void> | void;
  getContent(): any;
  applyToolCall(cmd: any): any;
  serialize(): any;
  destroy(): void;
}

export interface PptxEditorOptions {
  slideWidthEmu?: number;
  slideHeightEmu?: number;
  defaultFontSizePt?: number;
  defaultTitleFontSizePt?: number;
  slides?: PptxSlide[];
}

export interface PptxSlide {
  index?: number;
  slide_index?: number;
  background?: string;
  backgroundImage?: string;
  backgroundGradient?: string;
  shapes?: SlideShape[];
}

export interface SlideShape {
  id: number;
  name?: string;
  type?: string;
  _type?: string;
  left: number;
  top: number;
  width: number;
  height: number;
  z_order: number;
  has_text?: boolean;
  fill?: string | null;
  fillGradient?: string;
  fillImage?: string;
  border?: { widthEmu?: number; color?: string; width?: number };
  rotation?: number;
  autoShapeType?: string;
  cornerRadiusEmu?: number;
  editable?: boolean;
  opacity?: number;
  fontScale?: number;
  textInsets?: { t: number; r: number; b: number; l: number };
  textAnchor?: string;
  wordWrap?: string;
  is_title?: boolean;
  paragraphs?: ParaRun[];
  image_b64?: string;
  imageBase64?: string;
  cells?: TableCell[];
  table_rows?: number;
  table_cols?: number;
  col_widths?: number[];
  row_heights?: number[];
}

export interface ParaRun {
  align?: string;
  runs?: TextRun[];
  lineSpacing?: number;
  lineSpacingPt?: number;
  spaceBefore?: number;
  spaceBeforePct?: number;
  spaceAfter?: number;
  spaceAfterPct?: number;
  bullet?: boolean | string;
  numbered?: boolean;
  indent?: number;
}

export interface TextRun {
  text: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strikethrough?: boolean;
  superscript?: boolean;
  subscript?: boolean;
  size?: number;
  color?: string;
  fontName?: string;
  eaFontName?: string;
  highlight?: string;
  charSpacing?: number;
}

export interface TableCell {
  row: number;
  col: number;
  text?: string;
  bold?: boolean;
  color?: string;
  fill?: string;
  fontSize?: number;
  align?: string;
}

export interface PdfViewerOptions {
  outline?: PdfOutlineItem[];
  metadata?: Record<string, any>;
}

export interface PdfOutlineItem {
  title?: string;
  page?: number;
  children?: PdfOutlineItem[];
}

export interface PdfAnnotation {
  id: string;
  type: 'highlight' | 'underline' | 'strikethrough' | 'note' | 'draw' | 'rect' | 'ellipse' | 'line' | 'arrow' | 'textbox';
  page: number;
  color?: string;
  lineWidth?: number;
  timestamp?: number;
  text?: string;
  rects?: Array<{ x: number; y: number; w: number; h: number }>;
  points?: Array<{ x: number; y: number }>;
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  cx?: number;
  cy?: number;
  rx?: number;
  ry?: number;
  x1?: number;
  y1?: number;
  x2?: number;
  y2?: number;
  fontSize?: number;
  _open?: boolean;
}

export interface PdfSearchMatch {
  page: number;
  charIdx: number;
  charLen: number;
}

export interface DocxHeadingEntry {
  level: number;
  text: string;
  id: string;
}

export interface TextEditorData {
  content?: string;
  language?: string;
}
