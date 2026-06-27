export interface QuickActionDefinition {
  action: string;
  id?: string;
  keywords?: string[];
  label: string;
  route: string;
  readOnly?: boolean;
  fullDocument?: boolean | string;
  taskFlowMode?: string;
  prompt?: string;
  language?: string;
}

export interface QuickActionDeps {
  getMessagesElement?: () => HTMLElement | null;
  getModelMode?: () => string;
  getSelectedCloudModelId?: () => string;
  setProgress?: (text: string) => void;
  applyRouteEvent?: (evt: any) => void;
  handleProposals?: (proposals: any) => void;
}

export interface QuickActionContext {
  action?: string;
  text?: string;
  selectionText?: string;
  selectionSource?: string;
  pinnedSelSource?: string;
  model_mode?: string;
  model_id?: string;
  msgs?: HTMLElement;
  loadingEl?: HTMLElement;
  options?: Record<string, any>;
  prompt?: string;
  language?: string;
  csv_data?: string;
}

const BUILTIN_ACTIONS: QuickActionDefinition[] = [
  { action: '润色', keywords: ['润色'], label: '润色优化', route: 'editor', taskFlowMode: 'proposal' },
  { action: '翻译', keywords: ['翻译'], label: '翻译（中英互译）', route: 'editor', readOnly: true, taskFlowMode: 'simple' },
  { action: '总结', keywords: ['总结'], label: '总结要点', route: 'editor', readOnly: true, fullDocument: true, taskFlowMode: 'simple' },
  { action: '续写', keywords: ['续写'], label: '续写补全', route: 'editor', fullDocument: true, taskFlowMode: 'proposal' },
  { action: '改写', keywords: ['改写'], label: '改写', route: 'editor', taskFlowMode: 'proposal' },
  { action: '解释', keywords: ['解释'], label: '解释分析', route: 'editor', readOnly: true, taskFlowMode: 'simple' },
  { action: '检查', keywords: ['检查'], label: '检查建议', route: 'editor', readOnly: true, fullDocument: true, taskFlowMode: 'simple' },
  { action: '可视化', keywords: ['可视化'], label: '可视化图表', route: 'chart', fullDocument: 'xlsx-only', prompt: '请基于当前数据生成最合适、最清晰的图表，并在必要时自动清洗列名与空值。', language: 'python' },
];

function normalizeKeywords(keywords: string[], actionId: string): string[] {
  const values = Array.isArray(keywords) ? keywords : [keywords || actionId];
  return Array.from(new Set(values.map((k) => String(k || '').trim()).filter(Boolean)));
}

export function createQuickActionDispatcher(deps: QuickActionDeps = {}) {
  const options = deps || {};
  const actions = new Map<string, QuickActionDefinition>();
  let attachedDispatcher: any = null;

  function getMessagesElement(payload?: QuickActionContext): HTMLElement | null {
    if (payload && payload.msgs) return payload.msgs;
    return typeof options.getMessagesElement === 'function' ? options.getMessagesElement() : null;
  }

  function getModelMode(): string {
    return typeof options.getModelMode === 'function' ? options.getModelMode() : 'auto';
  }

  function getSelectedCloudModelId(): string {
    return typeof options.getSelectedCloudModelId === 'function' ? (options.getSelectedCloudModelId() || '') : '';
  }

  function getAction(actionId: string): QuickActionDefinition | null {
    return actions.get(String(actionId || '').trim()) || null;
  }

  function registerAction(definition: QuickActionDefinition): QuickActionDefinition {
    const actionId = String((definition && (definition.action || definition.id)) || '').trim();
    if (!actionId) throw new Error('Invalid quick action definition');

    const normalized: QuickActionDefinition = Object.assign({
      action: actionId, keywords: [actionId], label: actionId,
      route: 'editor', readOnly: false, fullDocument: false, prompt: '', language: 'python',
    }, definition || {}, { action: actionId });

    normalized.keywords = normalizeKeywords(normalized.keywords || [], actionId);
    actions.set(actionId, normalized);
    if (attachedDispatcher) attachActionToDispatcher(normalized);
    return normalized;
  }

  function listActions(): QuickActionDefinition[] {
    return Array.from(actions.values());
  }

  function matchAction(text: string): string {
    const source = String(text || '').trim();
    return actions.has(source) ? source : '';
  }

  function canUseFullDocument(actionId: string, fileType: string): boolean {
    const action = getAction(actionId);
    if (!action) return false;
    if (action.fullDocument === 'xlsx-only') return String(fileType || '').toLowerCase() === 'xlsx';
    return !!action.fullDocument;
  }

  function usesSimpleTaskFlow(action?: QuickActionDefinition): boolean {
    return !!(action && action.taskFlowMode === 'simple');
  }

  function usesProposalTaskFlow(action?: QuickActionDefinition): boolean {
    return !!(action && action.taskFlowMode === 'proposal');
  }

  function toolResultProgressText(parsed: any): string {
    const payload = parsed && typeof parsed === 'object' ? parsed : {};
    if (payload.summary) return String(payload.summary);
    if (payload.tool_name) return `已执行 ${payload.tool_name}`;
    if (payload.operation) return `已完成 ${payload.operation}`;
    return '工具步骤已完成';
  }

  function setProgress(text: string): void {
    if (typeof options.setProgress === 'function') options.setProgress(String(text || ''));
  }

  function handleToolResultProgress(parsed: any): void {
    setProgress(toolResultProgressText(parsed));
  }

  function handleParsedStreamEvent(parsed: any): boolean {
    if (!parsed || typeof parsed !== 'object') return false;
    if (parsed.type === 'classification' || parsed.type === 'route') {
      if (typeof options.applyRouteEvent === 'function') options.applyRouteEvent(parsed);
      return true;
    }
    if (parsed.type === 'tool_result') {
      handleToolResultProgress(parsed);
      return true;
    }
    return false;
  }

  function handleRuntimeEvent(evt: any): boolean {
    if (!evt || typeof evt !== 'object') return false;
    if (evt.type === 'classification' || evt.type === 'route') {
      if (typeof options.applyRouteEvent === 'function') options.applyRouteEvent(evt);
      return true;
    }
    return false;
  }

  function buildSimpleTaskFlowTask(payload: QuickActionContext, action?: QuickActionDefinition): string {
    const hasSelection = !!String(payload && payload.selectionText || '').trim();
    const scopeText = hasSelection ? '当前选区' : '已提供内容';
    const readonlySuffix = '这是只读 quick action，不要修改文件，也不要调用任何写入工具。';
    if (!action) return '';
    if (action.action === '翻译') return `请翻译${scopeText}，保持原意并使用自然表达；必要时只参考本次任务中显式提供的选区或分析文件。${readonlySuffix}`;
    if (action.action === '总结') return `请总结${scopeText}，提炼重点和待办事项；必要时只参考本次任务中显式提供的选区或分析文件。${readonlySuffix}`;
    if (action.action === '解释') return `请解释${scopeText}，说明关键含义、背景和风险点；必要时只参考本次任务中显式提供的选区或分析文件。${readonlySuffix}`;
    if (action.action === '检查') return `请检查${scopeText}中的语病、歧义、逻辑风险和表达问题，并按清单给出修改建议；必要时只参考本次任务中显式提供的选区或分析文件。${readonlySuffix}`;
    return '';
  }

  function buildProposalTaskFlowTask(payload: QuickActionContext, action?: QuickActionDefinition): string {
    const hasSelection = !!String(payload && payload.selectionText || '').trim();
    const scopeText = hasSelection ? '当前选区' : '已提供内容';
    const sharedSuffix = '必要时只参考本次任务中显式提供的选区或分析文件。不要调用任何写入工具，不要直接修改文件，只返回最终文本结果。';
    if (!action) return '';
    if (!hasSelection && !action.fullDocument && action.action !== '续写') return '';
    if (action.action === '润色') return `请润色${scopeText}内容，提升表达自然度、清晰度和流畅度，同时保持原意。直接输出可用于替换${scopeText}的最终文本，不要解释，不要加引号。${sharedSuffix}`;
    if (action.action === '改写') return `请改写${scopeText}内容，在保留核心含义的前提下优化结构和措辞。直接输出可用于替换${scopeText}的最终文本，不要解释，不要加引号。${sharedSuffix}`;
    if (action.action === '续写') {
      if (hasSelection) return `请基于当前选区继续写作，保持语气、主题和上下文连贯。直接输出可用于替换当前选区的完整文本，包含原有内容和新增续写部分，不要解释，不要加引号。${sharedSuffix}`;
      return `请基于已提供内容继续写作，保持语气、主题和上下文连贯。只输出新增续写内容，不要重复已有原文，不要解释，不要加引号。${sharedSuffix}`;
    }
    return '';
  }

  function normalizeProposalText(resultText: string): string {
    let text = String(resultText || '').trim();
    const fenced = text.match(/^```(?:[\w-]+)?\n([\s\S]*?)\n```$/);
    if (fenced) text = String(fenced[1] || '').trim();
    return text;
  }

  function attachActionToDispatcher(action: QuickActionDefinition): QuickActionDefinition {
    if (!attachedDispatcher || !action) return action;
    if (typeof attachedDispatcher.registerQuickActionHandler === 'function') {
      attachedDispatcher.registerQuickActionHandler(action.action, (context: any) => sendAction(action.action, context));
    }
    return action;
  }

  function attachDispatcher(dispatcher: any): any {
    attachedDispatcher = dispatcher || null;
    if (!attachedDispatcher) return null;
    listActions().forEach((action) => attachActionToDispatcher(action));
    return attachedDispatcher;
  }

  function sendAction(actionId: string, context: QuickActionContext): Promise<any> {
    const action = getAction(actionId);
    if (!action) return Promise.reject(new Error(`未注册任务动作：${actionId}`));
    if (action.route === 'chart') return sendChartAction(Object.assign({ action: actionId }, context), action);
    if (usesProposalTaskFlow(action)) return sendProposalTaskFlowAction(Object.assign({ action: actionId }, context), action);
    if (usesSimpleTaskFlow(action)) return sendSimpleTaskFlowAction(Object.assign({ action: actionId }, context), action);
    return Promise.reject(new Error(`快捷动作 ${actionId} 未配置可用的执行路径`));
  }

  function sendSimpleTaskFlowAction(payload: QuickActionContext, providedAction?: QuickActionDefinition): Promise<any> {
    const action = providedAction || getAction(payload.action || '');
    const msgs = getMessagesElement(payload);
    if (!msgs) throw new Error('AI message container unavailable');
    if (!attachedDispatcher || typeof attachedDispatcher.dispatchMessage !== 'function') {
      throw new Error('快捷动作任务流程运行时未加载，请刷新后重试。');
    }
    const taskText = buildSimpleTaskFlowTask(payload, action);
    if (!taskText) throw new Error(`快捷动作 ${payload.action || ''} 未生成可执行任务`);
    return attachedDispatcher.dispatchMessage({
      text: taskText,
      pinnedSelText: payload.selectionText || '',
      pinnedSelSource: payload.selectionSource || payload.pinnedSelSource || '',
      model_mode: payload.model_mode || getModelMode(),
      model_id: payload.model_id || getSelectedCloudModelId(),
      msgs,
      loadingEl: payload.loadingEl,
      options: { quick_action_mode: 'simple', quick_action_id: action!.action, quick_action_label: action!.label || action!.action },
    });
  }

  function sendProposalTaskFlowAction(payload: QuickActionContext, providedAction?: QuickActionDefinition): Promise<any> {
    const action = providedAction || getAction(payload.action || '');
    const msgs = getMessagesElement(payload);
    if (!msgs) throw new Error('AI message container unavailable');
    if (!attachedDispatcher || typeof attachedDispatcher.dispatchMessage !== 'function') {
      throw new Error('快捷动作任务流程运行时未加载，请刷新后重试。');
    }
    const taskText = buildProposalTaskFlowTask(payload, action);
    if (!taskText) throw new Error(`快捷动作 ${payload.action || ''} 未生成可执行任务`);
    const selectionText = String(payload.selectionText || '').trim();
    const hasSelection = !!selectionText;
    return attachedDispatcher.dispatchMessage({
      text: taskText,
      pinnedSelText: payload.selectionText || '',
      pinnedSelSource: payload.selectionSource || payload.pinnedSelSource || '',
      model_mode: payload.model_mode || getModelMode(),
      model_id: payload.model_id || getSelectedCloudModelId(),
      msgs,
      loadingEl: payload.loadingEl,
      options: { quick_action_mode: 'proposal', quick_action_id: action!.action, quick_action_label: action!.label || action!.action },
    }).then((result: any) => {
      if (!result || typeof result !== 'object' || result.error) return result;
      const assistantText = normalizeProposalText(result.assistantText || '');
      if (assistantText) result.assistantText = assistantText;
      if (!hasSelection || !assistantText || typeof options.handleProposals !== 'function') return result;
      options.handleProposals({
        proposals: [{ id: 'qa_' + Date.now(), original_text: selectionText, proposed_text: assistantText, rationale: action!.label || action!.action }],
        summary: action!.label || action!.action,
      });
      return result;
    });
  }

  async function sendChartAction(payload: QuickActionContext, providedAction?: QuickActionDefinition): Promise<any> {
    const action = providedAction || getAction(payload.action || '可视化');
    const msgs = getMessagesElement(payload);
    if (!msgs) throw new Error('AI message container unavailable');
    const language = String(payload.language || (action && action.language) || 'python').trim().toLowerCase();
    const modelMode = payload.model_mode || getModelMode();
    const modelId = payload.model_id || getSelectedCloudModelId();
    if (language !== 'python') throw new Error('只有 Python 图表动作可以进入任务流程。');
    if (!attachedDispatcher || typeof attachedDispatcher.dispatchMessage !== 'function') {
      throw new Error('任务流程调度器未加载，请刷新后重试。');
    }
    const instruction = String(payload.prompt || (action && action.prompt) || '').trim();
    const chartTaskText = instruction
      ? `请基于本次任务中显式提供的数据使用 Python 生成最合适、最清晰的图表。具体要求：${instruction}`
      : '请基于本次任务中显式提供的数据使用 Python 生成最合适、最清晰的图表。';
    return attachedDispatcher.dispatchMessage({
      text: chartTaskText,
      pinnedSelText: payload.csv_data || payload.selectionText || '',
      pinnedSelSource: payload.csv_data ? 'chart_csv' : (payload.selectionSource || payload.pinnedSelSource || 'chart_request'),
      model_mode: modelMode,
      model_id: modelId,
      msgs,
      loadingEl: payload.loadingEl,
      options: { quick_action_mode: 'simple', quick_action_id: action && action.action ? action.action : '可视化' },
    });
  }

  BUILTIN_ACTIONS.forEach((action) => registerAction(action));

  return {
    registerAction,
    getAction,
    listActions,
    matchAction,
    canUseFullDocument,
    attachDispatcher,
    handleParsedStreamEvent,
    handleRuntimeEvent,
    sendAction,
    sendChartAction(payload: QuickActionContext) {
      return sendChartAction(payload);
    },
  };
}

const WA = (window as any).WA || {};
WA.createQuickActionDispatcher = createQuickActionDispatcher;
WA.createWorkspaceQuickActionRuntime = createQuickActionDispatcher;
(window as any).WA = WA;
