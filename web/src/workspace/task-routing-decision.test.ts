import { describe, expect, it } from 'vitest';
import {
  deterministicWorkspaceRouteDecision,
  fileTaskRouteDecision,
  isDirectWorkspaceResponse,
  isWorkspaceOpenFileResponse,
  normalizeFileTaskRoutingDecision,
  normalizeWorkspaceRouteDecision,
  shouldForceFileTaskForWorkspaceContext,
  workspaceRouteErrorFallbackDecision,
} from './task-routing-decision';

describe('workspace task routing decisions', () => {
  it('short-circuits supported system actions without model routing', () => {
    expect(deterministicWorkspaceRouteDecision({
      text: '打开微信',
      hasFileContext: false,
    })).toMatchObject({
      route_kind: 'direct_response',
      route: 'system_action',
      task_type: 'SYSTEM',
      route_source: 'frontend_deterministic_system',
    });
  });

  it('routes file-context requests directly into the file task flow', () => {
    expect(deterministicWorkspaceRouteDecision({
      text: '总结当前文档',
      hasFileContext: true,
    })).toMatchObject({
      route_kind: 'complex_task',
      route: 'file_task',
      skip_ai_intent_adjudicator: true,
    });
  });

  it('recognizes an explicit file reference without an attached context', () => {
    expect(deterministicWorkspaceRouteDecision({
      text: '读取 workspace/report.docx 并总结',
      hasFileContext: false,
    })).toMatchObject({
      route: 'file_task',
      route_source: 'frontend_deterministic_explicit_file_reference',
    });
  });

  it('corrects contradictory route kinds at the normalization boundary', () => {
    expect(normalizeWorkspaceRouteDecision({
      route: 'file_task',
      route_kind: 'direct_response',
      task_type: 'CHAT',
    })).toMatchObject({
      route: 'file_task',
      route_kind: 'complex_task',
      task_type: 'FILE_TASK',
      source_task_type: 'CHAT',
    });
  });

  it('upgrades a direct model decision when attached file cues are present', () => {
    const direct = normalizeWorkspaceRouteDecision({
      route: 'light_chat',
      task_type: 'CHAT',
    });
    expect(shouldForceFileTaskForWorkspaceContext({
      text: '修改附件中的第三段',
      hasFileContext: true,
    }, direct)).toBe(true);
    expect(fileTaskRouteDecision('frontend_file_context_guard', direct)).toMatchObject({
      route: 'file_task',
      task_type: 'FILE_TASK',
      skip_ai_intent_adjudicator: true,
    });
  });

  it('preserves a backend open-file decision as a direct product action', () => {
    const decision = normalizeWorkspaceRouteDecision({
      route: 'open_file',
      route_kind: 'direct_response',
      task_type: 'FILE_TASK',
      target_path: 'reports/summary.docx',
    });

    expect(decision).toMatchObject({
      route: 'open_file',
      route_kind: 'direct_response',
      target_path: 'reports/summary.docx',
    });
    expect(isDirectWorkspaceResponse(decision)).toBe(true);
    expect(isWorkspaceOpenFileResponse(decision)).toBe(true);
    expect(shouldForceFileTaskForWorkspaceContext({
      text: '打开 summary.docx',
      hasFileContext: true,
    }, decision)).toBe(false);
  });

  it('falls back to chat on route transport errors unless file-task evidence is deterministic', () => {
    expect(workspaceRouteErrorFallbackDecision({
      text: '你好，介绍一下你自己',
      hasFileContext: false,
    })).toMatchObject({
      route: 'light_chat',
      route_kind: 'direct_response',
      route_source: 'frontend_route_error_fallback',
    });
    expect(workspaceRouteErrorFallbackDecision({
      text: '总结当前文档',
      hasFileContext: true,
    })).toMatchObject({
      route: 'file_task',
      route_source: 'frontend_deterministic_file_context',
    });
  });

  it('bounds workflow candidates and executable plan metadata', () => {
    const normalized = normalizeFileTaskRoutingDecision({
      route: 'file_task',
      workflow_candidates: Array.from({ length: 12 }, (_, index) => `workflow_${index}`),
      steps: Array.from({ length: 12 }, (_, index) => ({
        title: `step_${index}`,
        detail: 'x'.repeat(400),
      })),
    });

    expect(normalized?.candidate_workflows).toHaveLength(8);
    expect(normalized?.plan_steps).toHaveLength(8);
    expect(normalized?.plan_steps[0].description.length).toBe(323);
    expect(isDirectWorkspaceResponse(normalized)).toBe(false);
  });
});
