import { describe, it, expect, beforeEach, vi } from 'vitest';
import { logger, LogCategory } from './logger';

describe('logger', () => {
  beforeEach(() => {
    logger.clear();
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'info').mockImplementation(() => {});
    vi.spyOn(console, 'debug').mockImplementation(() => {});
  });

  it('logs warning with category and message', () => {
    logger.warn('state', 'test message');
    expect(console.warn).toHaveBeenCalledWith('[Koto][state]', 'test message');
  });

  it('logs error with detail', () => {
    const err = new Error('boom');
    logger.error('transport', 'SSE failed', err);
    expect(console.error).toHaveBeenCalledWith('[Koto][transport]', 'SSE failed', err);
  });

  it('buffers recent entries', () => {
    logger.warn('state', 'msg1');
    logger.warn('state', 'msg2');
    const recent = logger.getRecent(1);
    expect(recent).toHaveLength(1);
    expect(recent[0].message).toBe('msg2');
  });

  it('getRecent respects count', () => {
    for (let i = 0; i < 5; i++) logger.info('general', `msg${i}`);
    expect(logger.getRecent(3)).toHaveLength(3);
  });

  it('clear empties buffer', () => {
    logger.warn('state', 'test');
    logger.clear();
    expect(logger.getRecent()).toHaveLength(0);
  });
});
