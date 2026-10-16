import { PROTOCOL_VERSION } from "./protocol";

export type NativeEnvelope = {
  protocolVersion: typeof PROTOCOL_VERSION;
  type: string;
  eventId: string;
  sequence: number;
  payload: Record<string, unknown>;
};

let sequence = 0;

export function createNativeEnvelope(
  type: string,
  payload: Record<string, unknown>,
): NativeEnvelope {
  if (sequence >= Number.MAX_SAFE_INTEGER) {
    throw new Error("Native message sequence exhausted; reload the extension.");
  }
  return {
    protocolVersion: PROTOCOL_VERSION,
    type,
    eventId: crypto.randomUUID(),
    sequence: ++sequence,
    payload,
  };
}
