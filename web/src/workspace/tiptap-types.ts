/**
 * Type declarations for the TipTap DOCX editor bundle (IIFE).
 *
 * This module is loaded as an IIFE and attaches `KotoDocxEditorLib` to `window`.
 * It provides a rich text editor for DOCX documents based on ProseMirror/TipTap.
 */

declare global {
  interface Window {
    KotoDocxEditorLib?: KotoDocxEditorLib;
  }
}

/** Main entry point for creating and managing TipTap DOCX editors. */
export interface KotoDocxEditorLib {
  /**
   * Create a new KotoTipTapEditor instance.
   */
  KotoTipTapEditor: new (options: KotoTipTapEditorOptions) => KotoTipTapEditor;
}

/** Configuration options for creating a KotoTipTapEditor. */
export interface KotoTipTapEditorOptions {
  /** Target DOM element or selector to mount the editor. */
  element: string | HTMLElement;

  /** Initial editor content (HTML string). */
  content?: string;

  /** Whether the editor starts in editable mode. */
  editable?: boolean;

  /** Autofocus the editor on initialization. */
  autofocus?: boolean;

  /** Inject ProseMirror stylesheet. */
  injectCSS?: boolean;

  /**
   * Callback fired before the editor is created.
   */
  onBeforeCreate?: (ctx: { editor: KotoTipTapEditor }) => void;

  /**
   * Callback fired after the editor is created and ready.
   */
  onCreate?: (ctx: { editor: KotoTipTapEditor }) => void;

  /**
   * Callback fired when the editor content changes.
   */
  onUpdate?: (ctx: { editor: KotoTipTapEditor }) => void;

  /**
   * Callback fired when the selection changes.
   */
  onSelectionUpdate?: (ctx: { editor: KotoTipTapEditor }) => void;

  /**
   * Callback fired on every ProseMirror transaction.
   */
  onTransaction?: (ctx: { editor: KotoTipTapEditor }) => void;

  /**
   * Callback fired when the editor receives focus.
   */
  onFocus?: (ctx: { editor: KotoTipTapEditor }) => void;

  /**
   * Callback fired when the editor loses focus.
   */
  onBlur?: (ctx: { editor: KotoTipTapEditor }) => void;

  /**
   * Callback fired when the editor is destroyed.
   */
  onDestroy?: () => void;

  /**
   * TipTap extensions to register (typically none — the bundle includes standard ones).
   */
  extensions?: any[];

  /**
   * ProseMirror editor properties.
   */
  editorProps?: Record<string, any>;

  /**
   * Whether to enable input rules (e.g. `# ` for headings).
   */
  enableInputRules?: boolean;

  /**
   * Whether to enable paste rules (e.g. auto-link).
   */
  enablePasteRules?: boolean;

  /**
   * Whether to enable core extensions.
   */
  enableCoreExtensions?: boolean;

  /** Additional options for parsing HTML content. */
  parseOptions?: Record<string, any>;

  /** Additional options passed to core extensions. */
  coreExtensionOptions?: Record<string, any>;

  /** Allow any other option passed through to TipTap. */
  [key: string]: any;
}

/**
 * The KotoTipTapEditor instance — a TipTap editor extended with DOCX-friendly
 * commands and HTML export helpers.
 */
export interface KotoTipTapEditor {
  /**
   * The underlying TipTap/ProseMirror EditorView.
   */
  view: any;

  /**
   * The ProseMirror state (EditorState).
   */
  state: any;

  /**
   * Get the editor commands manager. Supports both direct command invocation
   * and the TipTap command chain pattern.
   */
  commands: Record<string, (...args: any[]) => boolean> & {
    setContent: (content: string, emitUpdate?: boolean) => boolean;
    focus: (position?: boolean | 'start' | 'end' | number) => boolean;
    blur: () => boolean;
    scrollIntoView: () => boolean;
    clearContent: (emitUpdate?: boolean) => boolean;
  };

  /**
   * Start a command chain.
   */
  chain: () => any;

  /**
   * Get or set the editor content as HTML.
   */
  getHTML: () => string;

  /**
   * Get the editor content as plain text.
   */
  getText: (options?: { blockSeparator?: string; textSerializers?: Record<string, any> }) => string;

  /**
   * Whether the editor has no content.
   */
  isEmpty: boolean;

  /**
   * Whether the editor is focused.
   */
  isFocused: boolean;

  /**
   * Whether the editor is initialized.
   */
  isInitialized: boolean;

  /**
   * Whether the editor has been destroyed.
   */
  isDestroyed: boolean;

  /**
   * The DOM element the editor is mounted on.
   */
  element: HTMLElement;

  /**
   * Extension storage.
   */
  storage: Record<string, any>;

  /**
   * Destroy the editor instance and clean up DOM / event listeners.
   */
  destroy: () => void;

  /**
   * Listen to an event.
   */
  on: (event: string, handler: (...args: any[]) => void) => void;

  /**
   * Remove an event listener.
   */
  off: (event: string, handler: (...args: any[]) => void) => void;

  /**
   * Emit an event.
   */
  emit: (event: string, ...args: any[]) => void;

  /**
   * Remove all event listeners.
   */
  removeAllListeners: () => void;

  /**
   * Set editor options.
   */
  setOptions: (options: Record<string, any>) => void;

  /**
   * Get a resolved position as a helper.
   */
  $pos: (pos: number) => any;

  /**
   * Query-select a single DOM node inside the editor.
   */
  $node: (selector: string, parent?: HTMLElement) => HTMLElement | null;

  /**
   * Query-select multiple DOM nodes inside the editor.
   */
  $nodes: (selector: string, parent?: HTMLElement) => NodeListOf<HTMLElement>;

  /**
   * Get the editor's root DOM element as a $pos helper.
   */
  $doc: any;

  /**
   * Check if a node type or mark is active at the current selection.
   */
  isActive: (type: any, attrs?: Record<string, any>) => boolean;
}
