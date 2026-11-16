import { describe, it, expect } from 'vitest';
import {
  normalizeFileTaskTerminalStatus,
  isFileTaskTerminalStatus,
  isFileTaskFailureStatus,
  isFileTaskWaitingStatus,
  isFileTaskConfirmationStatus,
  fileTaskOutcomeCopy,
  fileTaskTerminalUiStatus,
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
      expect(normalizeFileTaskTerminalStatus('quality_gate_failed')).toBe('quality_gate_failed');
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
      expect(isFileTaskFailureStatus('write_not_performed')).toBe(true);
      expect(isFileTaskFailureStatus('model_timeout')).toBe(true);
      expect(isFileTaskFailureStatus('verify_error')).toBe(true);
      expect(isFileTaskFailureStatus('completed')).toBe(false);
    });
  });

  describe('isFileTaskWaitingStatus', () => {
    it('detects waiting', () => {
      expect(isFileTaskWaitingStatus('waiting')).toBe(true);
      expect(isFileTaskWaitingStatus('pending')).toBe(true);
      expect(isFileTaskWaitingStatus('awaiting_confirmation')).toBe(true);
      expect(isFileTaskWaitingStatus('context_summary_fallback')).toBe(true);
      expect(isFileTaskWaitingStatus('needs_review')).toBe(true);
      expect(isFileTaskWaitingStatus('completed')).toBe(false);
    });
  });

  describe('terminal outcome copy', () => {
    it('keeps successful results concise and points to artifacts', () => {
      expect(fileTaskTerminalUiStatus('completed', true)).toBe('done');
      expect(fileTaskOutcomeCopy('done')).toMatchObject({
        title: '任务完成',
        detail: '结果与产物已整理，可直接查看或继续处理。',
        toastType: 'success',
      });
    });

    it('keeps cancelled and failed outcomes distinct', () => {
      expect(fileTaskTerminalUiStatus('cancelled', false)).toBe('cancelled');
      expect(fileTaskOutcomeCopy('cancelled').title).toBe('任务已取消');
      expect(fileTaskTerminalUiStatus('failed', false)).toBe('error');
      expect(fileTaskOutcomeCopy('failed').title).toBe('任务未完成');
      expect(fileTaskOutcomeCopy('model_timeout').title).toBe('模型执行超时');
      expect(fileTaskOutcomeCopy('write_not_performed').title).toBe('未执行文件写入');
    });

    it('keeps confirmation as a pending action rather than a completion', () => {
      expect(fileTaskTerminalUiStatus('awaiting_confirmation', false)).toBe('pending');
      expect(fileTaskOutcomeCopy('pending', true).title).toBe('等待确认');
    });

    it('keeps fallback summaries reviewable instead of marking them done or failed', () => {
      expect(isFileTaskFailureStatus('context_summary_fallback')).toBe(false);
      expect(isFileTaskTerminalStatus('context_summary_fallback')).toBe(true);
      expect(fileTaskTerminalUiStatus('context_summary_fallback', false)).toBe('pending');
      expect(fileTaskOutcomeCopy('context_summary_fallback')).toMatchObject({
        title: '需复核',
        toastType: 'info',
      });
    });
  });
});
