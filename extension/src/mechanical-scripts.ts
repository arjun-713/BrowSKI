import hitTestContains from "../../crates/browser-core/src/mechanics/hit-test-contains.js?raw";
import popupLink from "../../crates/browser-core/src/mechanics/popup-link.js?raw";
import clickElement from "../../crates/browser-core/src/mechanics/click.js?raw";
import elementTag from "../../crates/browser-core/src/mechanics/element-tag.js?raw";
import readChecked from "../../crates/browser-core/src/mechanics/read-checked.js?raw";
import readHover from "../../crates/browser-core/src/mechanics/read-hover.js?raw";
import readScroll from "../../crates/browser-core/src/mechanics/read-scroll.js?raw";
import readSelected from "../../crates/browser-core/src/mechanics/read-selected.js?raw";
import readText from "../../crates/browser-core/src/mechanics/read-text.js?raw";
import readValue from "../../crates/browser-core/src/mechanics/read-value.js?raw";
import selectMetadata from "../../crates/browser-core/src/mechanics/select-metadata.js?raw";
import setValue from "../../crates/browser-core/src/mechanics/set-value.js?raw";
import readExpressions from "../../crates/browser-core/src/mechanics/read-expressions.json";

const noArgumentFunctions = new Set([
  clickElement,
  popupLink,
  elementTag,
  readChecked,
  readHover,
  readScroll,
  readSelected,
  readText,
  readValue,
]);

function valueArgument(argument: unknown): unknown {
  if (
    typeof argument !== "object" ||
    argument === null ||
    Object.keys(argument).length !== 1 ||
    !("value" in argument)
  ) {
    return undefined;
  }
  return argument.value;
}

function boundedText(value: unknown): value is string {
  return typeof value === "string" && value.length <= 32_768;
}

function onlyKeys(params: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(params).every((key) => keys.includes(key));
}

function byValueOptions(params: Record<string, unknown>): boolean {
  return (
    params.returnByValue === true &&
    (params.awaitPromise === undefined || params.awaitPromise === true)
  );
}

export function isMechanicalEvaluation(params: Record<string, unknown>): boolean {
  return (
    onlyKeys(params, ["expression", "returnByValue", "awaitPromise"]) &&
    typeof params.expression === "string" &&
    readExpressions.includes(params.expression) &&
    byValueOptions(params)
  );
}

export function isMechanicalFunctionCall(params: Record<string, unknown>): boolean {
  if (
    !onlyKeys(params, [
      "objectId",
      "functionDeclaration",
      "arguments",
      "returnByValue",
      "awaitPromise",
    ]) ||
    typeof params.objectId !== "string" ||
    params.objectId.length === 0 ||
    params.objectId.length > 512 ||
    typeof params.functionDeclaration !== "string" ||
    !byValueOptions(params)
  ) {
    return false;
  }

  const args: unknown = params.arguments ?? [];
  if (!Array.isArray(args)) return false;
  const values: unknown[] = args.map(valueArgument);
  const declaration = params.functionDeclaration;
  if (noArgumentFunctions.has(declaration)) return args.length === 0;
  if (declaration === setValue) {
    return values.length === 1 && boundedText(values[0]);
  }
  if (declaration === selectMetadata) {
    return (
      values.length === 2 &&
      boundedText(values[0]) &&
      (values[1] === "value" || values[1] === "label")
    );
  }
  if (declaration === hitTestContains) {
    return (
      values.length === 2 &&
      values.every((value) => typeof value === "number" && Number.isFinite(value))
    );
  }
  return false;
}
