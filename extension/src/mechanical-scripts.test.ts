import { describe, expect, it } from "vitest";

import hitTestContains from "../../crates/browser-core/src/mechanics/hit-test-contains.js?raw";
import readValue from "../../crates/browser-core/src/mechanics/read-value.js?raw";
import selectMetadata from "../../crates/browser-core/src/mechanics/select-metadata.js?raw";
import setValue from "../../crates/browser-core/src/mechanics/set-value.js?raw";
import { isMechanicalEvaluation, isMechanicalFunctionCall } from "./mechanical-scripts";

describe("Rust-owned browser mechanics", () => {
  it("allows a fixed browser-truth read and rejects appended page code", () => {
    expect(
      isMechanicalEvaluation({ expression: "document.title", returnByValue: true }),
    ).toBe(true);
    expect(
      isMechanicalEvaluation({
        expression: "document.title; fetch('https://example.com/leak')",
        returnByValue: true,
      }),
    ).toBe(false);
    expect(
      isMechanicalEvaluation({ expression: "document.title", returnByValue: false }),
    ).toBe(false);
  });

  it("allows only the shared hit-test function with two numeric values", () => {
    const request = {
      objectId: "resolved-browser-object",
      functionDeclaration: hitTestContains,
      arguments: [{ value: 12 }, { value: 24 }],
      returnByValue: true,
    };

    expect(isMechanicalFunctionCall(request)).toBe(true);
    expect(
      isMechanicalFunctionCall({
        ...request,
        functionDeclaration: "function() { this.click(); }",
      }),
    ).toBe(false);
    expect(
      isMechanicalFunctionCall({ ...request, arguments: [{ value: "12" }, { value: 24 }] }),
    ).toBe(false);
    expect(
      isMechanicalFunctionCall({
        ...request,
        arguments: [{ objectId: "another-object" }, { value: 24 }],
      }),
    ).toBe(false);
    expect(isMechanicalFunctionCall({ ...request, userGesture: true })).toBe(false);
  });

  it("requires exact templates and typed arguments for executor mechanics", () => {
    const request = {
      objectId: "resolved-browser-object",
      functionDeclaration: readValue,
      arguments: [],
      returnByValue: true,
      awaitPromise: true,
    };
    expect(isMechanicalFunctionCall(request)).toBe(true);
    expect(
      isMechanicalFunctionCall({ ...request, arguments: [{ value: "ignored" }] }),
    ).toBe(false);
    const setter = {
      ...request,
      functionDeclaration: setValue,
      arguments: [{ value: 'text"; fetch("https://example.com")' }],
    };
    expect(isMechanicalFunctionCall(setter)).toBe(true);
    expect(
      isMechanicalFunctionCall({ ...setter, arguments: [{ value: "x".repeat(32_769) }] }),
    ).toBe(false);
    expect(
      isMechanicalFunctionCall({
        ...setter,
        functionDeclaration: setValue + "this.click()",
      }),
    ).toBe(false);
    const selection = {
      ...request,
      functionDeclaration: selectMetadata,
      arguments: [{ value: "Bengaluru" }, { value: "label" }],
    };
    expect(isMechanicalFunctionCall(selection)).toBe(true);
    expect(
      isMechanicalFunctionCall({
        ...selection,
        arguments: [{ value: "Bengaluru" }, { value: "option.text" }],
      }),
    ).toBe(false);
  });
});
