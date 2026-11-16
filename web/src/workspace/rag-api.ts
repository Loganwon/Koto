/**
 * Koto RAG API Client
 * ===================
 * TypeScript client for the RAG (Retrieval-Augmented Generation) API.
 */

export interface RAGSearchResult {
  content: string;
  source: string;
  score: number;
  chunk_index: number;
}

export interface RAGStats {
  initialized: boolean;
  doc_count: number;
  index_dir: string;
  index_size_mb: number;
  embedding_model: string;
  retrieval_backend: "hybrid" | "lexical" | "none";
}

export interface RAGIndexerStatus {
  running: boolean;
  watch_dir: string;
  indexed_files: number;
  rag_stats: RAGStats;
  supported_extensions: string[];
}

export interface IndexedFile {
  path: string;
  hash: string;
}

export interface RAGSearchRequest {
  query: string;
  k?: number;
  score_threshold?: number;
  bm25_weight?: number;
}

export interface RAGSearchResponse {
  success: boolean;
  results: RAGSearchResult[];
  count: number;
  index_stats: RAGStats;
}

export interface TemplatePlaceholderResponse {
  success: boolean;
  template_path: string;
  placeholders: string[];
  count: number;
}

export interface TemplatePreviewResponse {
  success: boolean;
  template_path: string;
  placeholders: string[];
  filled: Record<string, string>;
  rag_sources: string[];
  model_used: string;
}

export interface TemplateGenerateResponse {
  success: boolean;
  output_path?: string;
  placeholders_filled?: Record<string, string>;
  placeholder_count?: number;
  rag_sources?: string[];
  rag_chunks_used?: number;
  model_used?: string;
  error?: string;
  hint?: string;
}

// ── API functions ──────────────────────────────────────────────────────────

async function apiPost<T>(url: string, body: unknown): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error((err as { error?: string }).error || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

async function apiGet<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

// ── RAG Search ─────────────────────────────────────────────────────────────

export async function ragSearch(req: RAGSearchRequest): Promise<RAGSearchResponse> {
  return apiPost<RAGSearchResponse>("/api/rag/search", req);
}

// ── RAG Index Status ───────────────────────────────────────────────────────

export async function ragIndexStatus(): Promise<{
  success: boolean;
  rag: RAGStats;
  indexer: RAGIndexerStatus;
}> {
  return apiGet("/api/rag/index-status");
}

// ── Reindex ────────────────────────────────────────────────────────────────

export async function ragReindex(): Promise<{
  success: boolean;
  scanned: number;
  indexed: number;
  skipped: number;
  failed: number;
  total_chunks: number;
}> {
  return apiPost("/api/rag/reindex", {});
}

// ── Index File ─────────────────────────────────────────────────────────────

export async function ragIndexFile(filePath: string): Promise<{
  success: boolean;
  file_path: string;
  chunks: number;
}> {
  return apiPost("/api/rag/index-file", { file_path: filePath });
}

// ── Index Directory ────────────────────────────────────────────────────────

export async function ragIndexDirectory(
  dirPath: string,
  extensions?: string[]
): Promise<{
  success: boolean;
  results: Record<string, number>;
  total_files: number;
  total_chunks: number;
}> {
  return apiPost("/api/rag/index-directory", {
    dir_path: dirPath,
    extensions,
  });
}

// ── Indexed Files ──────────────────────────────────────────────────────────

export async function ragIndexedFiles(): Promise<{
  success: boolean;
  files: IndexedFile[];
}> {
  return apiGet("/api/rag/indexed-files");
}

// ── File Watcher ───────────────────────────────────────────────────────────

export async function ragStartWatcher(interval?: number): Promise<{
  success: boolean;
  message: string;
  status: RAGIndexerStatus;
}> {
  return apiPost("/api/rag/start-watcher", { interval });
}

export async function ragStopWatcher(): Promise<{
  success: boolean;
  message: string;
  status: RAGIndexerStatus;
}> {
  return apiPost("/api/rag/stop-watcher", {});
}

// ── Template Generation ────────────────────────────────────────────────────

export async function templateGenerate(
  templatePath: string,
  userQuery: string,
  options?: {
    outputPath?: string;
    ragK?: number;
    extraContext?: string;
  }
): Promise<TemplateGenerateResponse> {
  return apiPost<TemplateGenerateResponse>("/api/template/generate", {
    template_path: templatePath,
    user_query: userQuery,
    output_path: options?.outputPath,
    rag_k: options?.ragK,
    extra_context: options?.extraContext,
  });
}

export async function templatePreview(
  templatePath: string,
  userQuery: string,
  ragK?: number
): Promise<TemplatePreviewResponse> {
  return apiPost<TemplatePreviewResponse>("/api/template/preview", {
    template_path: templatePath,
    user_query: userQuery,
    rag_k: ragK,
  });
}

export async function templatePlaceholders(
  templatePath: string
): Promise<TemplatePlaceholderResponse> {
  return apiPost<TemplatePlaceholderResponse>("/api/template/placeholders", {
    template_path: templatePath,
  });
}
