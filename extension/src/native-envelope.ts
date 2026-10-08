import { PROTOCOL_VERSION } from "./protocol";

export type NativeEnvelope = {
  protocolVersion: typeof PROTOCOL_VERSION;
  type: string;
  eventId: string;
  payload: Record<string, unknown>;
};

export function createNativeEnvelope(
  type: string,
  payload: Record<string, unknown>,
): NativeEnvelope {
  return {
    protocolVersion: PROTOCOL_VERSION,
    type,
    eventId: crypto.randomUUID(),
    payload,
  };
}
