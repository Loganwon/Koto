const TASK_CONTRACT_KEYS: Record<string, string> = {
  file_path: 'fp',
  request_kind: 'rk',
  task_family: 'tf',
  operation_kind: 'ok',
  execution_mode: 'em',
  output_mode: 'om',
  target_mode: 'tm',
  multi_target_instructions: 'mti',
  expected_tool_name: 'etn',
  max_tool_calls: 'mtc',
  max_iterations: 'mi',
  background: 'bg',
  use_tool_fleet: 'utf',
  draft_mode: 'dm',
  quick_action_mode: 'qam',
  allowed_tool_names: 'atn',
  post_processing_script: 'pps',
  initial_instructions: 'ii',
  reasoning_effort: 're',
};

export function compactTaskContract(
  contract: Record<string, any> | null | undefined,
): Record<string, any> | null {
  if (!contract || typeof contract !== 'object') return null;
  const result: Record<string, any> = {};
  Object.entries(TASK_CONTRACT_KEYS).forEach(([source, target]) => {
    const value = contract[source];
    if (value == null || value === '') return;
    if (source === 'allowed_tool_names' && !Array.isArray(value)) return;
    result[target] = value;
  });
  result.v = 1;
  return result;
}

export function encodeTaskContract(
  contract: Record<string, any> | null | undefined,
): string {
  const compacted = compactTaskContract(contract);
  if (!compacted) return '';
  try {
    const json = JSON.stringify(compacted);
    const compressed = (window as any).LZString?.compressToEncodedURIComponent(json);
    return compressed || encodeURIComponent(json);
  } catch {
    return '';
  }
}

export function decodeTaskContract(encoded: string): Record<string, any> | null {
  if (!encoded || typeof encoded !== 'string') return null;
  try {
    const decompressor = (window as any).LZString?.decompressFromEncodedURIComponent;
    const json = typeof decompressor === 'function'
      ? decompressor(encoded) || ''
      : decodeURIComponent(encoded);
    if (!json) return null;
    const parsed = JSON.parse(json);
    if (!parsed || typeof parsed !== 'object' || parsed.v !== 1) return parsed || null;
    const expandMap = Object.fromEntries(
      Object.entries(TASK_CONTRACT_KEYS).map(([source, target]) => [target, source]),
    );
    const expanded: Record<string, any> = {};
    Object.keys(parsed).forEach((key) => {
      if (key !== 'v') expanded[expandMap[key] || key] = parsed[key];
    });
    return expanded;
  } catch {
    return null;
  }
}
