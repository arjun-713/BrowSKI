//! Bounded JavaScript transforms over a safe projection of semantic snapshots.
//!
//! This crate does not expose browser APIs, host callbacks, module loading, or
//! process I/O to JavaScript. It never changes browser state.

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::{Duration, Instant};

use browser_agent_observation::{SemanticElement, SemanticSnapshot};
use rquickjs::{context::intrinsic, Context, Function, Runtime, Value};
use serde::Serialize;
use thiserror::Error;

pub const MAX_SCRIPT_BYTES: usize = 8_192;
pub const MAX_INPUT_BYTES: usize = 131_072;
pub const MAX_RESULT_BYTES: usize = 16_384;
pub const MAX_TIMEOUT_MS: u64 = 1_500;
const MAX_HEAP_BYTES: usize = 4 * 1024 * 1024;
const MAX_STACK_BYTES: usize = 256 * 1024;
const MAX_PROJECTION_ELEMENTS: usize = 160;
const MAX_PROJECTED_TEXT_CHARS: usize = 160;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum BrowserCodeError {
    #[error("script exceeds the configured byte limit")]
    ScriptTooLarge,
    #[error("execution timeout must be between 1 and 1500 milliseconds")]
    InvalidTimeout,
    #[error("result limit must be between 1 and 16384 bytes")]
    InvalidResultLimit,
    #[error("semantic projection exceeds the configured byte limit")]
    InputTooLarge,
    #[error("JavaScript execution exceeded its deadline")]
    Timeout,
    #[error("JavaScript evaluation failed")]
    Evaluation,
    #[error("result is not JSON serializable")]
    NotJson,
    #[error("result exceeds the configured byte limit")]
    ResultTooLarge,
    #[error("could not serialize the semantic projection")]
    Projection,
}

#[derive(Debug, PartialEq, Eq, Serialize)]
pub struct BrowserCodeResult {
    pub state_generation: u64,
    /// JSON text returned by the isolated engine.
    pub result_json: String,
}

#[derive(Serialize)]
struct SnapshotProjection<'a> {
    schema_version: u32,
    state_generation: u64,
    title: Option<String>,
    elements: Vec<ProjectedElement<'a>>,
    truncated: bool,
}

#[derive(Serialize)]
struct ProjectedElement<'a> {
    reference: String,
    role: &'a str,
    accessible_name: Option<String>,
    text: Option<String>,
    state: &'a [String],
    visible: bool,
    interactable: bool,
    doc_order: u64,
}

/// Apply a script function to a bounded data-only projection of `snapshot`.
///
/// `script` must evaluate to a function accepting one snapshot object. A new
/// runtime and context are created for every call, so globals cannot survive
/// between requests. The projection deliberately omits URLs, input values,
/// form summaries, screenshots, and page excerpts.
pub fn transform_snapshot(
    snapshot: &SemanticSnapshot,
    script: &str,
    timeout_ms: u64,
    max_result_bytes: usize,
) -> Result<BrowserCodeResult, BrowserCodeError> {
    if script.len() > MAX_SCRIPT_BYTES {
        return Err(BrowserCodeError::ScriptTooLarge);
    }
    if !(1..=MAX_TIMEOUT_MS).contains(&timeout_ms) {
        return Err(BrowserCodeError::InvalidTimeout);
    }
    if !(1..=MAX_RESULT_BYTES).contains(&max_result_bytes) {
        return Err(BrowserCodeError::InvalidResultLimit);
    }

    let projection_json = projection_json(snapshot)?;
    let runtime = Runtime::new().map_err(|_| BrowserCodeError::Evaluation)?;
    runtime.set_memory_limit(MAX_HEAP_BYTES);
    runtime.set_max_stack_size(MAX_STACK_BYTES);

    let context = Context::builder()
        .with::<intrinsic::Eval>()
        .build(&runtime)
        .map_err(|_| BrowserCodeError::Evaluation)?;

    let deadline = Instant::now() + Duration::from_millis(timeout_ms);
    let timed_out = Arc::new(AtomicBool::new(false));
    let interrupt_flag = Arc::clone(&timed_out);
    runtime.set_interrupt_handler(Some(Box::new(move || {
        let expired = Instant::now() >= deadline;
        if expired {
            interrupt_flag.store(true, Ordering::Relaxed);
        }
        expired
    })));

    let result = context.with(|ctx| -> Result<String, BrowserCodeError> {
        let input: Value = ctx
            .json_parse(projection_json.as_str())
            .map_err(|_| BrowserCodeError::Evaluation)?;
        let transform: Function = ctx.eval(script).map_err(|_| BrowserCodeError::Evaluation)?;
        let output: Value = transform
            .call((input,))
            .map_err(|_| BrowserCodeError::Evaluation)?;
        let serialized = ctx
            .json_stringify(output)
            .map_err(|_| BrowserCodeError::NotJson)?
            .ok_or(BrowserCodeError::NotJson)?;
        serialized
            .to_string()
            .map_err(|_| BrowserCodeError::NotJson)
    });

    if timed_out.load(Ordering::Relaxed) {
        return Err(BrowserCodeError::Timeout);
    }

    let result_json = result?;
    if result_json.len() > max_result_bytes {
        return Err(BrowserCodeError::ResultTooLarge);
    }

    Ok(BrowserCodeResult {
        state_generation: snapshot.state_generation,
        result_json,
    })
}

fn projection_json(snapshot: &SemanticSnapshot) -> Result<String, BrowserCodeError> {
    let source_elements = if snapshot.elements.is_empty() {
        &snapshot.interactive_elements
    } else {
        &snapshot.elements
    };
    let elements = source_elements
        .iter()
        .take(MAX_PROJECTION_ELEMENTS)
        .map(project_element)
        .collect::<Vec<_>>();

    let projection = SnapshotProjection {
        schema_version: snapshot.schema_version,
        state_generation: snapshot.state_generation,
        title: snapshot.title.as_deref().map(bounded_text),
        elements,
        truncated: source_elements.len() > MAX_PROJECTION_ELEMENTS,
    };
    let serialized =
        serde_json::to_string(&projection).map_err(|_| BrowserCodeError::Projection)?;
    if serialized.len() > MAX_INPUT_BYTES {
        return Err(BrowserCodeError::InputTooLarge);
    }
    Ok(serialized)
}

fn project_element(element: &SemanticElement) -> ProjectedElement<'_> {
    let credential_label = has_credential_label(&element.role)
        || element
            .accessible_name
            .as_deref()
            .is_some_and(has_credential_label)
        || element.text.as_deref().is_some_and(has_credential_label);
    let is_input = element.semantic_kind == browser_agent_observation::SemanticKind::TextInput
        || matches!(
            element.role.as_str(),
            "textbox" | "searchbox" | "combobox" | "slider" | "spinbutton"
        );

    ProjectedElement {
        reference: if credential_label {
            "[redacted]".to_owned()
        } else {
            element.reference.clone()
        },
        role: &element.role,
        accessible_name: element.accessible_name.as_deref().map(|value| {
            if credential_label {
                "[redacted]".to_owned()
            } else {
                bounded_text(value)
            }
        }),
        text: if is_input || credential_label {
            None
        } else {
            element.text.as_deref().map(bounded_text)
        },
        state: &element.state,
        visible: element.visible,
        interactable: element.interactable,
        doc_order: element.doc_order,
    }
}

fn has_credential_label(value: &str) -> bool {
    const SENSITIVE_LABEL_PARTS: &[&str] = &[
        "password",
        "passphrase",
        "passcode",
        "credential",
        "secret",
        "privatekey",
        "authorization",
        "bearer",
        "cookie",
        "csrf",
        "apikey",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "onetimecode",
        "mfacode",
        "otp",
        "securitycode",
        "verificationcode",
        "recoverycode",
        "creditcard",
        "cvv",
        "cvc",
        "ssn",
    ];
    let normalized = value
        .chars()
        .filter(char::is_ascii_alphanumeric)
        .flat_map(char::to_lowercase)
        .collect::<String>();
    SENSITIVE_LABEL_PARTS
        .iter()
        .any(|part| normalized.contains(part))
}

fn bounded_text(value: &str) -> String {
    value.chars().take(MAX_PROJECTED_TEXT_CHARS).collect()
}

#[cfg(test)]
mod tests {
    use browser_agent_observation::SemanticSnapshot;

    use super::{transform_snapshot, BrowserCodeError};

    fn snapshot() -> SemanticSnapshot {
        let mut snapshot =
            SemanticSnapshot::minimal("https://private.example/reset?token=x".to_owned(), None, 42);
        snapshot.title = Some("Jobs".to_owned());
        snapshot.text_excerpt = Some("must not be exposed".to_owned());
        snapshot
    }

    #[test]
    fn transforms_bounded_semantic_data_and_keeps_generation() {
        let result = transform_snapshot(
            &snapshot(),
            "(snapshot) => ({title: snapshot.title, count: snapshot.elements.length})",
            1_000,
            128,
        )
        .expect("transform should succeed");

        assert_eq!(result.state_generation, 42);
        assert_eq!(result.result_json, r#"{"title":"Jobs","count":0}"#);
    }

    #[test]
    fn times_out_infinite_loop() {
        let result = transform_snapshot(&snapshot(), "() => { while (true) {} }", 1, 128);

        assert_eq!(result, Err(BrowserCodeError::Timeout));
    }

    #[test]
    fn rejects_heap_exhaustion() {
        let result = transform_snapshot(
            &snapshot(),
            "() => new Array(1000000000).fill('x')",
            1_000,
            128,
        );

        assert!(matches!(
            result,
            Err(BrowserCodeError::NotJson | BrowserCodeError::Evaluation)
        ));
    }

    #[test]
    fn recursion_is_bounded_by_stack_and_heap() {
        let result = transform_snapshot(
            &snapshot(),
            "() => { const f = () => f(); f(); }",
            1_000,
            128,
        );

        assert!(matches!(
            result,
            Err(BrowserCodeError::NotJson | BrowserCodeError::Evaluation)
        ));
    }

    #[test]
    fn rejects_undefined_and_non_json_results() {
        let result = transform_snapshot(&snapshot(), "() => undefined", 1_000, 128);

        assert_eq!(result, Err(BrowserCodeError::NotJson));
    }

    #[test]
    fn enforces_result_limit() {
        let result = transform_snapshot(&snapshot(), "() => 'x'.repeat(200)", 1_000, 32);

        assert_eq!(result, Err(BrowserCodeError::ResultTooLarge));
    }

    #[test]
    fn javascript_has_no_browser_or_host_io_globals() {
        let script = "() => ({document: typeof document, fetch: typeof fetch, \
            process: typeof process, require: typeof require, \
            std: typeof std, os: typeof os, JSON: typeof JSON})";
        let result = transform_snapshot(&snapshot(), script, 1_000, 256)
            .expect("inspection transform should succeed");

        assert_eq!(
            result.result_json,
            r#"{"document":"undefined","fetch":"undefined","process":"undefined","require":"undefined","std":"undefined","os":"undefined","JSON":"undefined"}"#
        );
    }

    #[test]
    fn module_imports_are_not_available() {
        let result = transform_snapshot(
            &snapshot(),
            "import value from 'std'; (snapshot) => value",
            1_000,
            128,
        );

        assert_eq!(result, Err(BrowserCodeError::Evaluation));
    }

    #[test]
    fn does_not_expose_url_excerpt_or_input_values() {
        let mut snapshot = snapshot();
        snapshot.interactive_elements.push(
            serde_json::from_value::<browser_agent_observation::SemanticElement>(
                serde_json::json!({
                    "ref": "@email",
                    "role": "textbox",
                    "accessible_name": "Password",
                    "text": "secret-form-value",
                    "value": "password-like-value",
                    "fingerprint": ""
                }),
            )
            .expect("semantic element should deserialize"),
        );
        snapshot.elements = snapshot.interactive_elements.clone();

        let result = transform_snapshot(&snapshot, "(snapshot) => snapshot", 1_000, 10_000)
            .expect("projection inspection should succeed");

        assert!(!result.result_json.contains("private.example"));
        assert!(!result.result_json.contains("must not be exposed"));
        assert!(!result.result_json.contains("password-like-value"));
        assert!(!result.result_json.contains("secret-form-value"));
        assert!(!result.result_json.contains("Password"));
        assert!(!result.result_json.contains("@email"));
    }

    #[test]
    fn excludes_values_and_sensitive_text_from_non_input_elements() {
        let mut snapshot = snapshot();
        snapshot.elements = vec![
            serde_json::from_value::<browser_agent_observation::SemanticElement>(
                serde_json::json!({
                    "ref": "@continue",
                    "role": "button",
                    "accessible_name": "Continue",
                    "text": "Continue",
                    "value": "field-value-not-projected",
                    "fingerprint": ""
                }),
            )
            .expect("button should deserialize"),
            serde_json::from_value::<browser_agent_observation::SemanticElement>(
                serde_json::json!({
                    "ref": "@access_token",
                    "role": "generic",
                    "accessible_name": "Access token",
                    "text": "sensitive token page text",
                    "value": "another-value-not-projected",
                    "fingerprint": ""
                }),
            )
            .expect("semantic element should deserialize"),
        ];

        let result = transform_snapshot(&snapshot, "(snapshot) => snapshot", 1_000, 10_000)
            .expect("projection inspection should succeed");

        assert!(!result.result_json.contains("field-value-not-projected"));
        assert!(!result.result_json.contains("another-value-not-projected"));
        assert!(!result.result_json.contains("Access token"));
        assert!(!result.result_json.contains("sensitive token page text"));
        assert!(!result.result_json.contains("@access_token"));
    }

    #[test]
    fn omits_values_and_text_from_non_credential_inputs_too() {
        let mut snapshot = snapshot();
        snapshot.interactive_elements.push(
            serde_json::from_value::<browser_agent_observation::SemanticElement>(
                serde_json::json!({
                    "ref": "@email",
                    "role": "textbox",
                    "accessible_name": "Email address",
                    "text": "person@example.org",
                    "value": "person@example.org",
                    "fingerprint": ""
                }),
            )
            .expect("semantic element should deserialize"),
        );
        snapshot.elements = snapshot.interactive_elements.clone();

        let result = transform_snapshot(&snapshot, "(snapshot) => snapshot", 1_000, 10_000)
            .expect("projection inspection should succeed");

        assert!(!result.result_json.contains("person@example.org"));
    }

    #[test]
    fn fresh_runtime_does_not_keep_globals_between_requests() {
        let first = transform_snapshot(
            &snapshot(),
            "() => { globalThis.secret = 'x'; return 1; }",
            1_000,
            32,
        )
        .expect("first transform should succeed");
        let second = transform_snapshot(&snapshot(), "() => typeof secret", 1_000, 32)
            .expect("second transform should succeed");

        assert_eq!(first.result_json, "1");
        assert_eq!(second.result_json, r#""undefined""#);
    }
}
