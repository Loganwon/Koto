export interface WorkspaceOpenFileRouteDeps {
  state: Record<string, any>;
  openWorkspaceFile?: (_path: string) => Promise<any> | any;
  appendAssistantTurn: (_text: string, _metadata: Record<string, any>) => void;
  setStreamButton?: (_streaming: boolean) => void;
}

export interface WorkspaceOpenFileRouteContext {
  loadingEl?: HTMLElement;
}

function displayFileName(path: string): string {
  return path.replace(/\\/g, '/').split('/').filter(Boolean).pop() || path;
}

export async function runWorkspaceOpenFileRoute(
  deps: WorkspaceOpenFileRouteDeps,
  context: WorkspaceOpenFileRouteContext,
  routeDecision: Record<string, any>,
): Promise<Record<string, any>> {
  const targetPath = String(routeDecision && routeDecision.target_path || '').trim();
  const loadingEl = context && context.loadingEl;
  let status = 'error';
  let assistantText = targetPath ? `无法打开文件：${displayFileName(targetPath)}` : '没有找到要打开的文件。';
  deps.state.isLoading = true;

  try {
    if (!targetPath) throw new Error('缺少目标文件路径');
    if (typeof deps.openWorkspaceFile !== 'function') throw new Error('工作区文件加载器未就绪');
    const opened = await deps.openWorkspaceFile(targetPath);
    if (!opened) throw new Error('文件加载失败');
    status = 'done';
    assistantText = `已打开文件：${displayFileName(targetPath)}`;
  } catch (error: any) {
    const detail = String(error && error.message || '').trim();
    assistantText = detail ? `${assistantText}（${detail}）` : assistantText;
  } finally {
    if (loadingEl) {
      loadingEl.classList.remove('streaming');
      loadingEl.textContent = assistantText;
      loadingEl.dataset.rawText = assistantText;
      loadingEl.dataset.workspaceRoute = 'open_file';
      loadingEl.dataset.workspaceRouteSource = String(routeDecision && routeDecision.route_source || '');
    }
    deps.appendAssistantTurn(assistantText, {
      loadingEl,
      task_kind: 'open_file',
      status,
      route_intent: routeDecision,
      skip_model_context: false,
    });
    deps.state.isLoading = false;
    if (typeof deps.setStreamButton === 'function') deps.setStreamButton(false);
  }

  return { routeId: 'open_file', assistantText, routeDecision, status };
}
