import { afterEach, describe, expect, it, vi } from "vitest";

import helloPacket from "../../tests/fixtures/extension/hello.v1.json";
import { createNativeEnvelope } from "./native-envelope";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("extension-runtime wire envelope", () => {
  it("serializes the shared v1 handshake packet accepted by Python", () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("11111111-1111-4111-8111-111111111111");

    const packet = createNativeEnvelope(helloPacket.type, helloPacket.payload);

    expect(packet).toEqual(helloPacket);
  });
});
