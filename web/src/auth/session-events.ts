/**
 * Singleton EventTarget for session-lifecycle events.
 *
 * Lives in its own module so `api-fetch.ts` (which is policy-light)
 * can dispatch `session:expired` without depending on the rest of the
 * auth module. The shell layout subscribes here.
 */

export const sessionEvents: EventTarget = new EventTarget();

export type SessionExpiredDetail = { code: string; status: number };
