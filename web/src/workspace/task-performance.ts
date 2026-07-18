export interface ModelSummaryState {
  rounds: Set<number>;
  startedRounds: Set<number>;
  toolCalls: number;
  contentChars: number;
  latestRound: number;
  mode: string;
  failed: boolean;
}

export interface TaskPerformanceUpdate {
  performance: Record<string, any>;
  encoded: string;
  summary: string;
}

export interface ModelSummaryUpdate {
  chip: string;
  summary: string;
}

export interface TaskPerformanceCard {
  dataset: DOMStringMap;
}

export function createModelSummaryState(): ModelSummaryState {
  return {
    rounds: new Set(),
    startedRounds: new Set(),
    toolCalls: 0,
    contentChars: 0,
    latestRound: 0,
    mode: '',
    failed: false,
  };
}

export function taskPerformanceSource(data: Record<string, any>): Record<string, any> {
  const merged: Record<string, any> = {};
  const routingDecision = data.routing_decision && typeof data.routing_decision === 'object' ? data.routing_decision : null;
  const routePerformance = routingDecision && routingDecision.performance && typeof routingDecision.performance === 'object'
    ? routingDecision.performance
    : null;
  const payloadPerformance = data.performance && typeof data.performance === 'object' ? data.performance : null;
  const runtime = data.runtime && typeof data.runtime === 'object' ? data.runtime : null;
  const runtimePerformance = runtime && runtime.performance && typeof runtime.performance === 'object' ? runtime.performance : null;
  [routePerformance, payloadPerformance, runtimePerformance].forEach((source) => {
    if (!source) return;
    Object.keys(source).forEach((key) => { merged[key] = source[key]; });
  });
  return merged;
}

export function taskPerformanceFromDataset(encoded: string): Record<string, any> {
  const value = String(encoded || '').trim();
  if (!value) return {};
  try {
    const parsed = JSON.parse(decodeURIComponent(value));
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_) {
    return {};
  }
}

export function encodeTaskPerformance(performance: Record<string, any>): string {
  return encodeURIComponent(JSON.stringify(performance || {}));
}

export function taskPerformanceMs(value: any): number | null {
  const num = Number(value);
  return Number.isFinite(num) && num >= 0 ? num : null;
}

export function taskPerformanceDuration(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(ms >= 10000 ? 1 : 2)}s`;
  if (ms >= 10) return `${Math.round(ms)}ms`;
  return `${ms.toFixed(1)}ms`;
}

export function taskPerformanceSummary(data: Record<string, any>): string {
  const perf = taskPerformanceSource(data);
  const fields: Array<[string, string]> = [
    ['路由', 'route_decision_ms'],
    ['上下文', 'context_files_ms'],
    ['分类', 'classification_ms'],
    ['裁决', 'intent_adjudication_ms'],
    ['计划', 'plan_materialization_ms'],
    ['总计', 'total_ms'],
  ];
  const parts = fields.map(([label, key]) => {
    const ms = taskPerformanceMs(perf[key]);
    return ms === null ? '' : `${label} ${taskPerformanceDuration(ms)}`;
  }).filter(Boolean);
  return parts.join(' · ');
}

export function updateTaskPerformanceDataset(currentEncoded: string, data: Record<string, any>): TaskPerformanceUpdate {
  const performance = Object.assign({}, taskPerformanceFromDataset(currentEncoded), taskPerformanceSource(data));
  return {
    performance,
    encoded: encodeTaskPerformance(performance),
    summary: taskPerformanceSummary({ performance }),
  };
}

export function updateTaskPerformanceRow(
  card: TaskPerformanceCard,
  data: Record<string, any>,
): void {
  if (!card || !card.dataset) return;
  const current = String(card.dataset.taskPerformance || '').trim();
  const next = updateTaskPerformanceDataset(current, data);
  try { card.dataset.taskPerformance = next.encoded; }
  catch { delete card.dataset.taskPerformance; }
}

export function updateModelSummaryState(state: ModelSummaryState, data: Record<string, any>): ModelSummaryUpdate {
  state.latestRound = Number(data.round || state.latestRound || 0);
  state.toolCalls = Number(data.tool_calls || state.toolCalls || 0);
  state.contentChars = Number(data.content_chars || state.contentChars || 0);
  state.mode = String(data.mode || state.mode || '').trim();
  if (data.failed) state.failed = true;
  if (data.round !== undefined && !state.startedRounds.has(state.latestRound)) state.startedRounds.add(state.latestRound);
  if (data.round_finished !== undefined && state.latestRound) state.rounds.add(state.latestRound);
  const roundLabel = state.latestRound ? '第' + state.latestRound + '轮' : '';
  const callsLabel = state.toolCalls ? state.toolCalls + '次工具调用' : '';
  return {
    chip: state.mode || '思考',
    summary: [roundLabel, callsLabel].filter(Boolean).join('，') || '思考中',
  };
}
