import { compactJsonValue } from './task-dispatcher-payload';
import { previewText } from './task-final-report';

const WORKSPACE_ROUTE_NAMES = new Set(['light_chat', 'web_search', 'file_task', 'open_file', 'system_action']);
const WORKSPACE_DIRECT_ROUTES = new Set(['light_chat', 'web_search', 'open_file', 'system_action']);
const WORKSPACE_FILE_TASK_ROUTE = 'file_task';
const WORKSPACE_FILE_TASK_KIND = 'complex_task';
const WORKSPACE_DIRECT_KIND = 'direct_response';
const FILE_TASK_CONTEXT_CUE_RE = /(?:当前(?:打开的?)?(?:文件|文档|表格|演示稿)?|这个(?:文件|文档|表格|演示稿)|已打开|附件|选区|读取|阅读|查看|总结|概括|归纳|分析|检查|提取|改写|润色|翻译|批注|修订|写入|写回|修改|更新|处理|基于|文件|文档|表格|演示稿|pdf|docx?|xlsx?|pptx?|txt|md|csv)/i;
const EXPLICIT_FILE_REFERENCE_RE = /[\w\u4e00-\u9fff ._()[\]{}~@#$%^&+=,;!-]{1,180}\.(?:pdf|docx?|xlsx?|xlsm|pptx?|txt|md|csv)\b/i;
const SYSTEM_ACTION_CUE_RE = /^(?:现在)?(?:几点|时间|日期|几号|星期几|系统状态|电脑状态|系统信息|电脑信息|配置|内存|cpu|硬盘|time|date)$/i;
const WHITELISTED_APP_LAUNCH_RE = /^(?:请|帮我|麻烦)?\s*(?:打开|启动|开启|open|launch)\s*(?:微信|wechat|weixin)\s*(?:应用|app)?$/i;

export interface WorkspaceRouteContext {
  text?: string;
  hasFileContext?: boolean;
}

export function fileTaskRouteDecision(
  routeSource: string,
  base?: Record<string, any> | null,
): Record<string, any> {
  const decision = Object.assign({}, base || {}, {
    route_kind: WORKSPACE_FILE_TASK_KIND,
    base_task_type: 'COMPLEX_TASK',
    route: WORKSPACE_FILE_TASK_ROUTE,
    task_type: 'FILE_TASK',
    route_source: routeSource,
    keyword_policy: 'hint_only',
  });
  if (
    routeSource === 'frontend_deterministic_file_context'
    || routeSource === 'frontend_deterministic_explicit_file_reference'
    || routeSource === 'frontend_file_context_guard'
  ) {
    decision.skip_ai_intent_adjudicator = true;
  }
  return decision;
}

export function deterministicWorkspaceRouteDecision(
  context: WorkspaceRouteContext,
): Record<string, any> | null {
  const text = String(context && context.text || '').trim();
  if (!text) return null;
  if (
    text.length <= 30
    && (SYSTEM_ACTION_CUE_RE.test(text) || WHITELISTED_APP_LAUNCH_RE.test(text))
  ) {
    return normalizeWorkspaceRouteDecision({
      route_kind: WORKSPACE_DIRECT_KIND,
      route: 'system_action',
      task_type: 'SYSTEM',
      confidence: 0.99,
      reason: '前端确定性系统动作短路。',
      route_source: 'frontend_deterministic_system',
    });
  }
  if (context.hasFileContext && FILE_TASK_CONTEXT_CUE_RE.test(text)) {
    return fileTaskRouteDecision('frontend_deterministic_file_context');
  }
  if (mentionsExplicitTaskFile(text) && FILE_TASK_CONTEXT_CUE_RE.test(text)) {
    return fileTaskRouteDecision('frontend_deterministic_explicit_file_reference');
  }
  return null;
}

export function shouldForceFileTaskForWorkspaceContext(
  context: WorkspaceRouteContext,
  routeDecision: Record<string, any> | null,
): boolean {
  const route = String(routeDecision && routeDecision.route || '').trim().toLowerCase();
  if (route === 'open_file') return false;
  if (route && !WORKSPACE_DIRECT_ROUTES.has(route)) return false;
  const text = String(context && context.text || '').trim();
  return !!text && !!context.hasFileContext && FILE_TASK_CONTEXT_CUE_RE.test(text);
}

export function isDirectWorkspaceResponse(
  routeDecision: Record<string, any> | null,
): boolean {
  if (!routeDecision) return false;
  const routeKind = String(routeDecision.route_kind || '').trim().toLowerCase();
  const route = String(routeDecision.route || '').trim().toLowerCase();
  return routeKind === WORKSPACE_DIRECT_KIND && WORKSPACE_DIRECT_ROUTES.has(route);
}

export function isWorkspaceOpenFileResponse(
  routeDecision: Record<string, any> | null,
): boolean {
  if (!routeDecision) return false;
  return String(routeDecision.route_kind || '').trim().toLowerCase() === WORKSPACE_DIRECT_KIND
    && String(routeDecision.route || '').trim().toLowerCase() === 'open_file'
    && !!String(routeDecision.target_path || '').trim();
}

export function workspaceRouteErrorFallbackDecision(
  context: WorkspaceRouteContext,
): Record<string, any> {
  const deterministic = deterministicWorkspaceRouteDecision(context);
  if (deterministic) return deterministic;
  return normalizeWorkspaceRouteDecision({
    route_kind: WORKSPACE_DIRECT_KIND,
    route: 'light_chat',
    task_type: 'CHAT',
    confidence: 0,
    reason: '意图判断服务暂不可用，已降级为普通对话。',
    route_source: 'frontend_route_error_fallback',
  });
}

export function normalizeWorkspaceRouteDecision(data: any): Record<string, any> {
  const payload = data && typeof data === 'object' ? data : {};
  const route = String(payload.route || '').trim().toLowerCase();
  const rawTaskType = String(payload.task_type || '').trim().toUpperCase();
  const routeFromTaskType = rawTaskType === 'SYSTEM'
    ? 'system_action'
    : (rawTaskType === 'CHAT'
      ? 'light_chat'
      : (rawTaskType === 'WEB_SEARCH' ? 'web_search' : WORKSPACE_FILE_TASK_ROUTE));
  const normalizedRoute = WORKSPACE_ROUTE_NAMES.has(route) ? route : routeFromTaskType;
  const routeKind = canonicalWorkspaceRouteKind(normalizedRoute, payload.route_kind);
  const canonicalTaskType = canonicalWorkspaceTaskType(normalizedRoute, rawTaskType);
  const explicitSourceTaskType = String(payload.source_task_type || '').trim().toUpperCase();
  const sourceTaskType = explicitSourceTaskType
    || (rawTaskType && rawTaskType !== canonicalTaskType ? rawTaskType : '');
  return {
    ok: payload.ok !== false,
    route_kind: routeKind,
    base_task_type: routeKind === WORKSPACE_DIRECT_KIND ? 'DIRECT_RESPONSE' : 'COMPLEX_TASK',
    route: normalizedRoute,
    task_type: canonicalTaskType,
    source_task_type: sourceTaskType,
    confidence: Math.max(0, Math.min(1, Number(payload.confidence || 0) || 0)),
    reason: previewText(payload.reason || '', 280),
    target_path: previewText(payload.target_path || '', 260),
    hint: previewText(payload.hint || '', 180),
    route_source: previewText(payload.route_source || '', 160),
    keyword_policy: String(payload.keyword_policy || '').trim() || 'hint_only',
    performance: payload.performance && typeof payload.performance === 'object'
      ? compactJsonValue(payload.performance, 0, 800)
      : undefined,
  };
}

export function normalizeFileTaskRoutingDecision(
  value: any,
): Record<string, any> | null {
  const source = value && typeof value === 'object' ? value : null;
  if (!source) return null;
  const route = String(source.route || '').trim().toLowerCase();
  if (!route) return null;
  const routeKind = canonicalWorkspaceRouteKind(route, source.route_kind);
  const taskType = canonicalWorkspaceTaskType(route, source.task_type);
  const normalized: Record<string, any> = {
    route_kind: routeKind,
    route,
    task_type: taskType,
    source_task_type: String(source.source_task_type || '').trim().toUpperCase(),
    confidence: Math.max(0, Math.min(1, Number(source.confidence || 0) || 0)),
    reason: previewText(source.reason || '', 500),
    route_source: previewText(source.route_source || '', 160),
    router_policy: previewText(source.router_policy || source.route_policy || '', 120),
    keyword_policy: previewText(source.keyword_policy || '', 120),
    target_path: previewText(source.target_path || '', 260),
  };
  if (source.performance && typeof source.performance === 'object') {
    normalized.performance = compactJsonValue(source.performance, 0, 800);
  }
  if (source.skip_ai_intent_adjudicator === true) {
    normalized.skip_ai_intent_adjudicator = true;
  }
  const candidateWorkflows = Array.isArray(source.candidate_workflows || source.workflow_candidates)
    ? (source.candidate_workflows || source.workflow_candidates)
        .slice(0, 8)
        .map((item: any) => previewText(item || '', 160))
        .filter(Boolean)
    : [];
  if (candidateWorkflows.length) normalized.candidate_workflows = candidateWorkflows;
  if (Object.prototype.hasOwnProperty.call(source, 'requires_adjudication')) {
    normalized.requires_adjudication = !!source.requires_adjudication;
  }
  const finalToolPath = previewText(source.final_tool_path || source.tool_path || '', 240);
  if (finalToolPath) normalized.final_tool_path = finalToolPath;
  const frontendLabel = previewText(source.frontend_label || source.display_label || '', 160);
  if (frontendLabel) normalized.frontend_label = frontendLabel;
  const planSteps = Array.isArray(source.plan_steps || source.steps)
    ? (source.plan_steps || source.steps).slice(0, 8).map((item: any, index: number) => {
        const step = item && typeof item === 'object' ? item : { label: item };
        const normalizedStep: Record<string, any> = {
          id: previewText(step.id || `route_step_${index + 1}`, 64),
          label: previewText(step.label || step.title || step.step || '', 160),
          description: previewText(step.description || step.detail || '', 320),
          tool: previewText(step.tool || step.tool_name || '', 120),
        };
        Object.keys(normalizedStep).forEach((key) => {
          if (!normalizedStep[key]) delete normalizedStep[key];
        });
        return normalizedStep;
      }).filter((item: Record<string, any>) => item.label || item.description || item.tool)
    : [];
  if (planSteps.length) normalized.plan_steps = planSteps;
  return normalized;
}

export function canonicalWorkspaceRouteKind(route: string, routeKind?: string): string {
  const normalizedRoute = String(route || '').trim().toLowerCase();
  const normalizedKind = String(routeKind || '').trim().toLowerCase();
  if (normalizedKind === WORKSPACE_DIRECT_KIND || normalizedKind === WORKSPACE_FILE_TASK_KIND) {
    if (
      normalizedKind === WORKSPACE_DIRECT_KIND
      && normalizedRoute === WORKSPACE_FILE_TASK_ROUTE
    ) return WORKSPACE_FILE_TASK_KIND;
    if (
      normalizedKind === WORKSPACE_FILE_TASK_KIND
      && WORKSPACE_DIRECT_ROUTES.has(normalizedRoute)
    ) return WORKSPACE_DIRECT_KIND;
    return normalizedKind;
  }
  return WORKSPACE_DIRECT_ROUTES.has(normalizedRoute)
    ? WORKSPACE_DIRECT_KIND
    : WORKSPACE_FILE_TASK_KIND;
}

export function canonicalWorkspaceTaskType(route: string, taskType?: string): string {
  const normalizedRoute = String(route || '').trim().toLowerCase();
  const normalizedTask = String(taskType || '').trim().toUpperCase();
  if (normalizedRoute === 'web_search') return 'WEB_SEARCH';
  if (normalizedRoute === 'system_action') return 'SYSTEM';
  if (normalizedRoute === 'light_chat') return 'CHAT';
  if (normalizedRoute === WORKSPACE_FILE_TASK_ROUTE) return 'FILE_TASK';
  if (normalizedTask === 'CHAT' || normalizedTask === 'WEB_SEARCH') return normalizedTask;
  return 'FILE_TASK';
}

export function shouldBypassWorkspaceRoute(context: any): boolean {
  const options = context && context.options && typeof context.options === 'object'
    ? context.options
    : {};
  return !!(context && context.taskPayload)
    || !!options.followup_context
    || !!options.workflow_checkpoint;
}

function mentionsExplicitTaskFile(text: string): boolean {
  const source = String(text || '').trim();
  return !!source && EXPLICIT_FILE_REFERENCE_RE.test(source);
}
