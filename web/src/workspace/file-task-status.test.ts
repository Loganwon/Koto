import { describe, it, expect } from 'vitest';
import {
  normalizeFileTaskTerminalStatus,
  isFileTaskTerminalStatus,
  isFileTaskFailureStatus,
  isFileTaskWaitingStatus,
  isFileTaskConfirmationStatus,
} from '../workspace/file-task-status';

describe('file-task-status', () => {
  describe('normalizeFileTaskTerminalStatus', () => {
    it('normalizes success variants', () => {
      expect(normalizeFileTaskTerminalStatus('complete')).toBe('completed');
      expect(normalizeFileTaskTerminalStatus('success')).toBe('completed');
      expect(normalizeFileTaskTerminalStatus('succeeded')).toBe('completed');
      expect(normalizeFileTaskTerminalStatus('verified')).toBe('completed');
    });
    it('normalizes failure', () => {
      expect(normalizeFileTaskTerminalStatus('failure')).toBe('failed');
    });
    it('normalizes cancelled', () => {
      expect(normalizeFileTaskTerminalStatus('canceled')).toBe('cancelled');
    });
    it('normalizes in_progress', () => {
      expect(normalizeFileTaskTerminalStatus('in_progress')).toBe('running');
    });
    it('passes through unknown', () => {
      expect(normalizeFileTaskTerminalStatus('done')).toBe('done');
      expect(normalizeFileTaskTerminalStatus('error')).toBe('error');
    });
    it('handles empty/null', () => {
      expect(normalizeFileTaskTerminalStatus('')).toBe('');
      expect(normalizeFileTaskTerminalStatus(null as any)).toBe('');
    });
  });

  describe('isFileTaskFailureStatus', () => {
    it('detects failures', () => {
      expect(isFileTaskFailureStatus('failed')).toBe(true);
      expect(isFileTaskFailureStatus('error')).toBe(true);
      expect(isFileTaskFailureStatus('blocked')).toBe(true);
      expect(isFileTaskFailureStatus('completed')).toBe(false);
    });
  });

  describe('isFileTaskWaitingStatus', () => {
    it('detects waiting', () => {
      expect(isFileTaskWaitingStatus('waiting')).toBe(true);
      expect(isFileTaskWaitingStatus('pending')).toBe(true);
      expect(isFileTaskWaitingStatus('awaiting_confirmation')).toBe(true);
      expect(isFileTaskWaitingStatus('completed')).toBe(false);
    });
  });
});
