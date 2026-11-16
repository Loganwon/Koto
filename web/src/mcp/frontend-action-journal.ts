/** Local handoff evidence, not an execution queue or an exactly-once promise.
 * A persisted started marker means unknown after a crash; it never means done.
 * Receipts are written before network acknowledgement and retried on reload.
 */
import type { FrontendAction } from './frontend-observer';

export type ActionOutcome = {
  ok: boolean;
  result: Record<string, unknown>;
  error: string;
  unknown?: boolean;
};
export type BrowserActionRecord = {
  id: string;
  fingerprint: string;
  browser_id: string;
  delivery_token: string;
  request_id?: string;
  session_id?: string;
  mutation: boolean;
  state: 'started' | 'completed' | 'failed' | 'unknown';
  outcome?: ActionOutcome;
  acknowledged: boolean;
  updated_at: number;
};
const STORAGE_PREFIX = 'koto_frontend_action_receipt_v1:';
const RETENTION_MS = 7 * 86400000;
const MAX_RECORDS = 1000;
const READ_ONLY_ACTIONS = new Set([
  'snapshot', 'read_dom', 'task_result_evidence', 'surface_inventory', 'wait_for',
  'list_workspace_files', 'current_file_state', 'read_editor_content',
  'current_selection', 'document_context', 'ui_read_context',
]);

export function browserActionMutation(action: FrontendAction): boolean {
  return action.mutation ?? !READ_ONLY_ACTIONS.has(action.action);
}

export function browserActionFingerprint(action: FrontendAction): string {
  // Transport actions carry the hash of their full trusted request. Direct
  // local callers retain the same bounded descriptor fallback.
  return action.request_fingerprint || JSON.stringify([action.action, action.path, action.selector, action.value, action.text, action.options]);
}

export function unknownActionOutcome(): ActionOutcome {
  return { ok: false, result: { execution_unknown: true }, error: 'Browser restarted without a confirmed execution receipt; inspect the current document before another write', unknown: true };
}

export function getBrowserActionJournal(): BrowserActionJournal {
  return new BrowserActionJournal(localStorage);
}

export class BrowserActionJournal {
  constructor(private readonly storage: Storage) {}
  private key(id: string): string { return STORAGE_PREFIX + encodeURIComponent(id); }

  private records(): BrowserActionRecord[] {
    const records: BrowserActionRecord[] = [];
    // Each action has its own atomic storage key. Different tabs cannot lose
    // one another's marker/receipt through a shared JSON read-modify-write.
    for (let index = 0; index < this.storage.length; index += 1) {
      const key = this.storage.key(index);
      if (!key?.startsWith(STORAGE_PREFIX)) continue;
      const raw = this.storage.getItem(key);
      if (!raw) continue;
      const record = JSON.parse(raw) as BrowserActionRecord;
      if (!record?.id || !record?.fingerprint) throw new Error('Browser action journal is unreadable; inspect pending actions before editing');
      records.push(record);
    }
    return records;
  }

  private write(record: BrowserActionRecord): void {
    this.storage.setItem(this.key(record.id), JSON.stringify(record));
  }

  get(id: string): BrowserActionRecord | undefined {
    const raw = this.storage.getItem(this.key(id));
    if (!raw) return undefined;
    const record = JSON.parse(raw) as BrowserActionRecord;
    if (record?.id !== id || !record?.fingerprint) throw new Error('Browser action journal has invalid identity');
    return record;
  }

  reserve(record: Omit<BrowserActionRecord, 'state' | 'outcome' | 'acknowledged' | 'updated_at'>): void {
    if (this.get(record.id)) throw new Error('Browser action already has execution evidence');
    const retained = this.records().filter((entry) => {
      if (entry.acknowledged && entry.state !== 'unknown' && entry.state !== 'started' && Date.now() - entry.updated_at > RETENTION_MS) {
        this.storage.removeItem(this.key(entry.id));
        return false;
      }
      return true;
    });
    if (retained.length >= MAX_RECORDS) throw new Error('Browser action receipt storage is full; pending operations require review');
    this.write({ ...record, state: 'started', acknowledged: false, updated_at: Date.now() });
  }

  finish(id: string, outcome: ActionOutcome): void {
    const record = this.get(id);
    if (!record) throw new Error('Browser action has no durable started marker');
    this.write({ ...record, state: outcome.unknown ? 'unknown' : (outcome.ok ? 'completed' : 'failed'), outcome, acknowledged: false, updated_at: Date.now() });
  }

  pending(): BrowserActionRecord[] {
    return this.records().filter((record) => !record.acknowledged && Boolean(record.delivery_token));
  }

  acknowledge(id: string): void {
    const record = this.get(id);
    if (record) this.write({ ...record, acknowledged: true, updated_at: Date.now() });
  }

  reject(id: string): void {
    const record = this.get(id);
    if (record) this.write({ ...record, state: 'unknown', acknowledged: true, updated_at: Date.now() });
  }

  async flush(pending: Map<string, BrowserActionRecord>, post: (record: BrowserActionRecord) => Promise<boolean>): Promise<void> {
    for (const record of this.pending()) {
      if (!pending.has(record.id)) pending.set(record.id, record);
    }
    for (const [id, record] of pending) {
      const accepted = await post(record);
      if (accepted) this.acknowledge(id);
      else this.reject(id); // retain unknown evidence; reads can still inspect it
      pending.delete(id);
    }
  }
}
