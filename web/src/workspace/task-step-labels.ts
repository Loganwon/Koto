import { taskReportStageTitle } from './task-report-layout';

const TOOL_LABELS: Record<string, string> = {
  selection_context: '读取选区',
  provided_file_context: '读取文件上下文',
  parse_file_to_text: '解析文件文本',
  read_sheet_data: '读取表格数据',
  read_docx_content: '读取 Word 内容',
  insert_excel_as_docx_table: '插入 Excel 表格',
  insert_image_into_docx: '插入 Word 图片',
  write_docx_content: '写入 Word 内容',
  write_sheet_data: '写入 Excel 单元格',
  design_pptx_theme_layout: '设计 PPT 主题版式',
  write_pptx_slides: '更新 PPT 页面',
  convert_pptx_picture_slides_to_textboxes: '图片页转可编辑文本',
  add_pptx_slides: '新增 PPT 页面',
  run_python_code: '运行 Python',
  read_file_range: '读取文本片段',
  replace_file_selection: '替换文本选区',
  create_file: '创建文件',
  copy_file: '复制文件',
  compare_files: '对比文件',
  extract_to_file: '提取到文件',
  annotate_file: '添加批注',
  list_conversions: '查询可转换格式',
  convert_file: '格式转换',
  list_workspace_files: '列出文件',
  open_file_in_editor: '打开文件',
  verify_task_completion: '核验结果',
  model_message: '模型说明',
  write_guard: '继续写入',
  supervisor_guard: '监管纠偏',
  plan_gate: '计划监管',
  image_insert_guard: '图表写入核验',
};

const INTERNAL_TOOL_NAMES = new Set([
  'selection_context', 'provided_file_context', 'parse_file_to_text',
  'model_message', 'answer_guard', 'readonly_answer_guard', 'repair_guard',
  'duplicate_guard', 'supervisor_guard', 'write_guard', 'plan_gate',
]);

const ALWAYS_SUPPRESS_TOOL_FINISHED_NAMES = new Set([
  'answer_guard', 'readonly_answer_guard', 'repair_guard', 'duplicate_guard',
  'supervisor_guard', 'write_guard', 'plan_gate',
]);

const READ_TOOL_NAMES = new Set([
  'read_sheet_data', 'read_docx_content', 'inspect_workbook_structure', 'audit_financial_workbook',
]);

const EXTRA_STEP_TITLES: Record<string, string> = {
  context: '读取文件',
  run: '任务状态',
};

const PLAN_VIOLATION_LABELS: Record<string, string> = {
  'write_required_but_plan_not_write': '任务需要写回，但计划没有标记为写入',
  'write_required_but_output_not_write': '任务需要写回，但输出模式不是 write',
  'clear_review_misclassified_as_annotation': '清除批注被误判为新增批注',
  'clear_review_allows_annotate_file': '清除批注任务误选择了 annotate_file 能力',
  'annotation_request_not_classified_as_annotation': '批注任务未被识别为批注流程',
  'read_request_escalated_to_write': '只读任务被错误升级为写入',
};

export function taskToolLabel(name: string): string {
  return TOOL_LABELS[name] || name || '工具';
}

export function isInternalTaskTool(name: string): boolean {
  return INTERNAL_TOOL_NAMES.has(name || '');
}

export function shouldAlwaysSuppressTaskToolFinished(name: string): boolean {
  return ALWAYS_SUPPRESS_TOOL_FINISHED_NAMES.has(name || '');
}

export function isReadTaskTool(name: string): boolean {
  return READ_TOOL_NAMES.has(name || '');
}

export function taskStepTitle(stepId: string, fallback?: string): string {
  return EXTRA_STEP_TITLES[stepId] || taskReportStageTitle(stepId, fallback || '步骤');
}

export function taskToolStepTitle(name: string): string {
  return '工具:' + taskToolLabel(name);
}

export function taskPlanViolationLabel(code: string): string {
  const value = String(code || '').trim();
  if (!value) return '';
  if (PLAN_VIOLATION_LABELS[value]) return PLAN_VIOLATION_LABELS[value];
  return value.replace(/_/g, ' ');
}
