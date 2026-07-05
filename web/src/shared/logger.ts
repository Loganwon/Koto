/**
 * Structured Logger — replaces bare console.warn/error with categorized logging.
 *
 * Levels: debug < info < warn < error
 * In production (when app.debug is falsy), debug and info are suppressed.
 *
 * Usage:
 *   import { logger } from '../shared/logger';
 *   logger.warn('fs-tree', 'Failed to load', { path, error });
 *   logger.error('transport', 'SSE timeout', { url, elapsed });
 */

export type LogCategory =
  | 'fs-tree'
  | 'transport'
  | 'task-runner'
  | 'task-dispatcher'
  | 'ai-context'
  | 'ai-review'
  | 'chat-ui'
  | 'settings'
  | 'session'
  | 'editor'
  | 'pdf-viewer'
  | 'image-viewer'
  | 'pptx-editor'
  | 'xlsx-editor'
  | 'docx-review'
  | 'skills'
  | 'marketplace'
  | 'router'
  | 'state'
  | 'auth'
  | 'framework'
  | 'init'
  | 'general';

export type LogLevel = 'debug' | 'info' | 'warn' | 'error';

interface LogEntry {
  category: LogCategory;
  level: LogLevel;
  message: string;
  detail?: unknown;
  timestamp: number;
}

const LOG_LEVEL_RANK: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

const MIN_LEVEL: LogLevel = (typeof window !== 'undefined' && (window as any).app?.debug) ? 'debug' : 'info';

class Logger {
  private buffer: LogEntry[] = [];
  private maxBuffer = 200;

  private shouldLog(level: LogLevel): boolean {
    return LOG_LEVEL_RANK[level] >= LOG_LEVEL_RANK[MIN_LEVEL];
  }

  private log(level: LogLevel, category: LogCategory, message: string, detail?: unknown): void {
    if (!this.shouldLog(level)) return;

    const entry: LogEntry = {
      category,
      level,
      message,
      detail,
      timestamp: Date.now(),
    };

    // Ring buffer for diagnostics
    this.buffer.push(entry);
    if (this.buffer.length > this.maxBuffer) {
      this.buffer.shift();
    }

    const prefix = `[Koto][${category}]`;
    const consoleFn = level === 'error' ? console.error
      : level === 'warn' ? console.warn
      : level === 'info' ? console.info
      : console.debug;

    if (detail !== undefined) {
      consoleFn(prefix, message, detail);
    } else {
      consoleFn(prefix, message);
    }
  }

  debug(category: LogCategory, message: string, detail?: unknown): void {
    this.log('debug', category, message, detail);
  }

  info(category: LogCategory, message: string, detail?: unknown): void {
    this.log('info', category, message, detail);
  }

  warn(category: LogCategory, message: string, detail?: unknown): void {
    this.log('warn', category, message, detail);
  }

  error(category: LogCategory, message: string, detail?: unknown): void {
    this.log('error', category, message, detail);
  }

  /** Return recent log entries for diagnostics. */
  getRecent(count = 50): LogEntry[] {
    const start = Math.max(0, this.buffer.length - count);
    return this.buffer.slice(start);
  }

  /** Clear the log buffer. */
  clear(): void {
    this.buffer = [];
  }
}

export const logger = new Logger();
