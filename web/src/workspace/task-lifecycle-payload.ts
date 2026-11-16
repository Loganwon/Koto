export function normalizedTaskLifecyclePayload(payload: any): Record<string, any> {
  const data = payload && typeof payload === 'object' ? payload : {};
  const decisionContext = data.decision_context && typeof data.decision_context === 'object'
    ? data.decision_context
    : null;
  const classification = decisionContext?.classification && typeof decisionContext.classification === 'object'
    ? decisionContext.classification
    : (data.classification && typeof data.classification === 'object' ? data.classification : null);
  if (!classification) return data;

  // Terminal fields must win over classification metadata. Otherwise events
  // carrying decision context can lose summary/failure/completion details.
  const normalized = Object.assign({}, classification, data);
  if (decisionContext) normalized.decision_context = decisionContext;

  const nestedFields = [
    'intent_plan',
    'requirements',
    'plan_check',
    'routing_decision',
  ];
  nestedFields.forEach((key) => {
    const value = decisionContext?.[key] && typeof decisionContext[key] === 'object'
      ? decisionContext[key]
      : (data[key] && typeof data[key] === 'object' ? data[key] : null);
    if (value) normalized[key] = value;
  });

  [
    'runtime',
    'performance',
    'next_action_artifact',
    'artifact_result',
    'followup_record',
    'constraint_audit',
    'workflow_state',
    'supervisor_audit',
    'task_context',
    'task_request_payload',
  ].forEach((key) => {
    if (data[key] && typeof data[key] === 'object') normalized[key] = data[key];
  });
  [
    'intent_adjudication',
    'effective_planner',
  ].forEach((key) => {
    if (decisionContext?.[key] && typeof decisionContext[key] === 'object') {
      normalized[key] = decisionContext[key];
    }
  });
  [
    'quick_action_mode',
    'task_id',
    'run_id',
    'task',
    'task_title',
    'title',
    'summary',
    'memory_summary',
    'model_context_text',
  ].forEach((key) => {
    if (data[key]) normalized[key] = data[key];
  });
  if (data.text || data.error) normalized.text = data.text || data.error;
  [
    'final_answer',
    'finalAnswer',
    'answer',
    'result',
    'output',
    'output_text',
    'content',
    'message',
    'data',
    'payload',
    'completed_task',
  ].forEach((key) => {
    if (Object.prototype.hasOwnProperty.call(data, key)) normalized[key] = data[key];
  });
  return normalized;
}
