//! Snapshot collection: CDP DOM + Accessibility + layout merged into one
//! semantic projection.
//!
//! Pipeline:
//!
//! ```text
//! CDP DOM + Accessibility + layout
//!         ↓
//! raw page graph (frame/shadow-aware walk)
//!         ↓
//! visibility/interactability filtering (style + box + hit test)
//!         ↓
//! semantic labeling (AX-enriched roles/names/values/states)
//!         ↓
//! ElementRegistry (stable refs, leveled reacquisition)
//!         ↓
//! SemanticSnapshot → incremental diff
//! ```
//!
//! Collection is concurrent per candidate (JoinSet) but deterministic in
//! output: elements sort by document order, aliases assign in document
//! order, fingerprints hash normalized signals. Same page → same snapshot.

use browser_agent_cdp::{CdpSessionId, CdpTransport, TabId, TargetId};
use browser_agent_element_registry::{ElementRegistry, ReacquireCandidate, ReacquireOutcome};
use browser_agent_observation::{
    assign_aliases, classify, diff_snapshots, fingerprint, page_fingerprint, score, AliasInput,
    BBox, BackendNodeId, ClassifyInput, DialogSummary, FingerprintSignals, FormSummary, FrameId,
    SemanticElement, SemanticKind, SemanticSnapshot, SnapshotDelta, TextBlock, TextKind, Viewport,
    SCORE_WEAK,
};
use serde_json::Value;
use std::collections::{HashMap, HashSet};

use crate::error::BrowserRuntimeError;
use crate::session::BrowserSession;

/// Upper bound on primary semantic candidates, including controls and headings.
const MAX_CANDIDATES: usize = 400;
/// Small supplementary paragraph budget; paragraph evidence cannot displace
/// primary semantic candidates.
const MAX_PARAGRAPH_CANDIDATES: usize = 50;
/// Text lengths are bounded everywhere (working-memory discipline).
const MAX_TEXT_LEN: usize = 200;

// ---------------------------------------------------------------------------
// CDP response shapes (defensive: only the fields we use)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default)]
struct AxInfo {
    role: Option<String>,
    name: Option<String>,
    value: Option<String>,
    ignored: bool,
    hidden: bool,
    disabled: bool,
    focused: bool,
    checked: Option<bool>,
    expanded: Option<bool>,
    pressed: Option<bool>,
    selected: Option<bool>,
    readonly: bool,
    required: bool,
    level: Option<u32>,
    modal: bool,
}

fn ax_value_text(v: &Value) -> Option<String> {
    match v.get("type").and_then(Value::as_str) {
        Some("string") => v.get("value").and_then(Value::as_str).map(str::to_string),
        Some("boolean") => v
            .get("value")
            .and_then(Value::as_bool)
            .map(|b| b.to_string()),
        Some("integer") | Some("number") => v.get("value").map(|n| n.to_string()),
        _ => None,
    }
}

fn parse_ax_node(node: &Value) -> (Option<i64>, AxInfo) {
    let backend = node.get("backendDOMNodeId").and_then(Value::as_i64);
    let props: Vec<(&str, &Value)> = node
        .get("properties")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .map(|p| {
                    (
                        p.get("name").and_then(Value::as_str).unwrap_or(""),
                        p.get("value").unwrap_or(&Value::Null),
                    )
                })
                .collect()
        })
        .unwrap_or_default();
    let flag = |name: &str| -> bool {
        props
            .iter()
            .find(|(n, _)| *n == name)
            .and_then(|(_, v)| v.get("value"))
            .and_then(Value::as_bool)
            .unwrap_or(false)
    };
    let tri = |name: &str| -> Option<bool> {
        props.iter().find(|(n, _)| *n == name).and_then(|(_, v)| {
            v.get("value")
                .and_then(Value::as_str)
                .map(|s| s == "true")
                .or_else(|| v.get("value").and_then(Value::as_bool))
        })
    };
    let level = props
        .iter()
        .find(|(n, _)| *n == "level")
        .and_then(|(_, v)| {
            v.get("value")
                .and_then(Value::as_f64)
                .map(|f| f as u32)
                .or_else(|| v.get("value").and_then(Value::as_u64).map(|u| u as u32))
        });
    let info = AxInfo {
        role: node.get("role").and_then(ax_value_text),
        name: node.get("name").and_then(ax_value_text),
        value: node.get("value").and_then(ax_value_text),
        ignored: node
            .get("ignored")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        hidden: flag("hidden"),
        disabled: flag("disabled"),
        focused: flag("focused"),
        checked: tri("checked"),
        expanded: tri("expanded"),
        pressed: tri("pressed"),
        readonly: flag("readonly"),
        required: flag("required"),
        level,
        modal: flag("modal"),
        selected: tri("selected"),
    };
    (backend, info)
}

// ---------------------------------------------------------------------------
// DOM walk
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default)]
struct RawNode {
    backend: Option<i64>,
    node_id: Option<i64>,
    tag: String,
    attrs: HashMap<String, String>,
    text: String,
    frame_path: Vec<String>,
    frame: Option<String>,
    doc_order: u64,
    ancestry: Vec<String>,
    children_backends: Vec<i64>,
    /// Nearest form/section context (name/id/aria-label), if any.
    context: Option<String>,
    /// Wrapping <label> text, if any.
    implicit_label: Option<String>,
    /// Inside an inert subtree.
    inert_ancestor: bool,
}

fn attr_map(node: &Value) -> HashMap<String, String> {
    let mut map = HashMap::new();
    if let Some(arr) = node.get("attributes").and_then(Value::as_array) {
        let mut iter = arr.iter();
        while let (Some(k), Some(v)) = (iter.next(), iter.next()) {
            if let (Some(k), Some(v)) = (k.as_str(), v.as_str()) {
                map.insert(k.to_lowercase(), v.to_string());
            }
        }
    }
    map
}

fn tag_signature(tag: &str, attrs: &HashMap<String, String>) -> String {
    // Root-level classes churn constantly (frameworks toggle body classes
    // for themes/modals); they are volatile, not identity. Deeper classes
    // stay in the signature.
    if matches!(tag, "html" | "head" | "body") {
        return tag.to_string();
    }
    let class = attrs
        .get("class")
        .map(|c| c.split_whitespace().take(2).collect::<Vec<_>>().join("."))
        .filter(|c| !c.is_empty());
    match class {
        Some(c) => format!("{tag}.{c}"),
        None => tag.to_string(),
    }
}

const INTERACTIVE_TAGS: &[&str] = &[
    "a", "button", "input", "select", "textarea", "option", "summary", "details", "video", "audio",
];

fn is_heading(tag: &str) -> bool {
    matches!(tag, "h1" | "h2" | "h3" | "h4" | "h5" | "h6")
}

#[allow(clippy::too_many_arguments)]
fn walk(
    node: &Value,
    out: &mut Vec<RawNode>,
    labels_for: &mut HashMap<String, String>,
    frame_path: &[String],
    frame: Option<String>,
    ancestry: &[String],
    doc_order: &mut u64,
    form_stack: &mut Vec<String>,
    section_stack: &mut Vec<String>,
    label_stack: &mut Vec<String>,
    id_text: &mut HashMap<String, String>,
    visible_ax_text: &HashSet<i64>,
    paragraph_count: &mut usize,
    inert_ancestor: bool,
) {
    let node_type = node.get("nodeType").and_then(Value::as_u64).unwrap_or(0);
    // Text node: fold into parent via return (handled by caller through nodeValue).
    if node_type == 3 {
        return;
    }
    if node_type == 10 {
        return; // doctype
    }
    let node_name = node
        .get("nodeName")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    let tag = node_name.to_lowercase();

    // Document node: descend into children (and adopt frame id if present).
    if node_type == 9 {
        let frame = node
            .get("frameId")
            .and_then(Value::as_str)
            .map(str::to_string)
            .or(frame);
        for child in node
            .get("children")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            walk(
                child,
                out,
                labels_for,
                frame_path,
                frame.clone(),
                ancestry,
                doc_order,
                form_stack,
                section_stack,
                label_stack,
                id_text,
                visible_ax_text,
                paragraph_count,
                inert_ancestor,
            );
        }
        if let Some(content) = node.get("contentDocument") {
            walk(
                content,
                out,
                labels_for,
                frame_path,
                frame,
                ancestry,
                doc_order,
                form_stack,
                section_stack,
                label_stack,
                id_text,
                visible_ax_text,
                paragraph_count,
                inert_ancestor,
            );
        }
        return;
    }
    if node_type != 1 {
        return; // elements only from here
    }

    let attrs = attr_map(node);
    let inert_here = inert_ancestor || attrs.contains_key("inert");
    if let Some(id) = attrs.get("id") {
        let text = direct_text(node);
        if !text.is_empty() {
            id_text.insert(id.clone(), text);
        }
    }
    // Collect label[for] associations for pass two.
    if tag == "label" {
        if let Some(for_id) = attrs.get("for") {
            let text = direct_text(node);
            if !text.is_empty() {
                labels_for.insert(for_id.clone(), text);
            }
        }
    }

    // iframe: descend into contentDocument with extended provenance.
    if tag == "iframe" || tag == "frame" {
        let name = attrs
            .get("name")
            .or_else(|| attrs.get("title"))
            .or_else(|| attrs.get("id"))
            .cloned()
            .unwrap_or_else(|| "frame".to_string());
        let mut child_path = frame_path.to_vec();
        child_path.push(format!("iframe[{name}]"));
        let mut child_ancestry = ancestry.to_vec();
        child_ancestry.push(tag_signature(&tag, &attrs));
        if let Some(content) = node.get("contentDocument") {
            walk(
                content,
                out,
                labels_for,
                &child_path,
                frame.clone(),
                &child_ancestry,
                doc_order,
                &mut vec![],
                &mut vec![],
                &mut vec![],
                &mut HashMap::new(),
                visible_ax_text,
                paragraph_count,
                inert_here,
            );
        } else {
            // Cross-origin (OOPIF): contents invisible to this walk. Record
            // the frame element itself as a region if named.
            push_candidate(
                node,
                &attrs,
                &tag,
                out,
                labels_for,
                visible_ax_text,
                frame_path,
                frame.clone(),
                ancestry,
                doc_order,
                form_stack,
                section_stack,
                label_stack,
                paragraph_count,
                inert_here,
                true,
            );
        }
        return;
    }

    // Wrapping-label tracking: label text applies to descendant controls.
    let mut pushed_label = false;
    if tag == "label" {
        label_stack.push(direct_text(node));
        pushed_label = true;
    }

    // Form/section context tracking.
    let mut pushed_form = false;
    let mut pushed_section = false;
    if tag == "form" {
        let ctx = attrs
            .get("name")
            .or_else(|| attrs.get("id"))
            .or_else(|| attrs.get("aria-label"))
            .cloned()
            .unwrap_or_default();
        form_stack.push(ctx);
        pushed_form = true;
    }
    if tag == "section" || tag == "fieldset" || tag == "main" || tag == "nav" {
        let ctx = attrs
            .get("aria-label")
            .or_else(|| attrs.get("id"))
            .cloned()
            .unwrap_or_default();
        section_stack.push(ctx);
        pushed_section = true;
    }

    push_candidate(
        node,
        &attrs,
        &tag,
        out,
        labels_for,
        visible_ax_text,
        frame_path,
        frame.clone(),
        ancestry,
        doc_order,
        form_stack,
        section_stack,
        label_stack,
        paragraph_count,
        inert_here,
        false,
    );

    let mut child_ancestry = ancestry.to_vec();
    child_ancestry.push(tag_signature(&tag, &attrs));
    if child_ancestry.len() > 4 {
        child_ancestry.drain(..child_ancestry.len() - 4);
    }
    for child in node
        .get("children")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        walk(
            child,
            out,
            labels_for,
            frame_path,
            frame.clone(),
            &child_ancestry,
            doc_order,
            form_stack,
            section_stack,
            label_stack,
            id_text,
            visible_ax_text,
            paragraph_count,
            inert_here,
        );
    }
    // Open shadow roots (pierce:true inlines them); closed roots are absent
    // and fall back to AX/vision later.
    if let Some(roots) = node.get("shadowRoots").and_then(Value::as_array) {
        for root in roots {
            let rtype = root
                .get("shadowRootType")
                .and_then(Value::as_str)
                .unwrap_or("");
            if rtype == "closed" || rtype == "user-agent" {
                continue;
            }
            for child in root
                .get("children")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
            {
                let mut shadow_ancestry = child_ancestry.clone();
                shadow_ancestry.push(">>shadow".to_string());
                walk(
                    child,
                    out,
                    labels_for,
                    frame_path,
                    frame.clone(),
                    &shadow_ancestry,
                    doc_order,
                    form_stack,
                    section_stack,
                    label_stack,
                    id_text,
                    visible_ax_text,
                    paragraph_count,
                    inert_here,
                );
            }
        }
    }

    if pushed_label {
        label_stack.pop();
    }
    if pushed_form {
        form_stack.pop();
    }
    if pushed_section {
        section_stack.pop();
    }
}

fn direct_text(node: &Value) -> String {
    let mut parts = Vec::new();
    for child in node
        .get("children")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let t = child.get("nodeType").and_then(Value::as_u64).unwrap_or(0);
        if t == 3 {
            if let Some(s) = child.get("nodeValue").and_then(Value::as_str) {
                let trimmed = s.split_whitespace().collect::<Vec<_>>().join(" ");
                if !trimmed.is_empty() {
                    parts.push(trimmed);
                }
            }
        }
    }
    let joined = parts.join(" ");
    joined.chars().take(MAX_TEXT_LEN).collect()
}

fn inline_style_hides_text(attrs: &HashMap<String, String>) -> bool {
    // The AX tree gates text by descendant visibility without per-node style
    // calls. This inline check remains a local guard against hidden attributes.
    attrs.get("style").is_some_and(|style| {
        style.split(';').any(|declaration| {
            let Some((property, value)) = declaration.split_once(':') else {
                return false;
            };
            let property = property.trim().to_ascii_lowercase();
            let value = value
                .split('!')
                .next()
                .unwrap_or_default()
                .trim()
                .to_ascii_lowercase();
            matches!(
                (property.as_str(), value.as_str()),
                ("display", "none")
                    | ("visibility", "hidden")
                    | ("visibility", "collapse")
                    | ("content-visibility", "hidden")
                    | ("opacity", "0")
            )
        })
    })
}

fn paragraph_text(node: &Value, visible_ax_text: &HashSet<i64>) -> String {
    fn collect(
        node: &Value,
        output: &mut String,
        remaining: &mut usize,
        is_root: bool,
        visible_ax_text: &HashSet<i64>,
    ) {
        if *remaining == 0 {
            return;
        }
        let node_type = node.get("nodeType").and_then(Value::as_u64).unwrap_or(0);
        if node_type == 3 {
            let Some(backend) = node.get("backendNodeId").and_then(Value::as_i64) else {
                return;
            };
            if !visible_ax_text.contains(&backend) {
                return;
            }
            if let Some(text) = node.get("nodeValue").and_then(Value::as_str) {
                for word in text.split_whitespace() {
                    let needs_space = !output.is_empty();
                    if needs_space && *remaining > 0 {
                        output.push(' ');
                        *remaining -= 1;
                    }
                    for character in word.chars() {
                        if *remaining == 0 {
                            return;
                        }
                        output.push(character);
                        *remaining -= 1;
                    }
                }
            }
            return;
        }
        if node_type != 1 {
            return;
        }
        let tag = node
            .get("nodeName")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_ascii_lowercase();
        if matches!(tag.as_str(), "script" | "style" | "noscript" | "template") {
            return;
        }
        let attrs = attr_map(node);
        if !is_root
            && (attrs.contains_key("hidden")
                || attrs
                    .get("aria-hidden")
                    .is_some_and(|value| value == "true")
                || inline_style_hides_text(&attrs))
        {
            return;
        }
        for child in node
            .get("children")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
        {
            collect(child, output, remaining, false, visible_ax_text);
            if *remaining == 0 {
                return;
            }
        }
    }

    let mut output = String::new();
    let mut remaining = MAX_TEXT_LEN;
    collect(node, &mut output, &mut remaining, true, visible_ax_text);
    output
}

#[allow(clippy::too_many_arguments)]
fn push_candidate(
    node: &Value,
    attrs: &HashMap<String, String>,
    tag: &str,
    out: &mut Vec<RawNode>,
    _labels_for: &HashMap<String, String>,
    visible_ax_text: &HashSet<i64>,
    frame_path: &[String],
    frame: Option<String>,
    ancestry: &[String],
    doc_order: &mut u64,
    form_stack: &[String],
    section_stack: &[String],
    label_stack: &[String],
    paragraph_count: &mut usize,
    inert_ancestor: bool,
    _frame_only: bool,
) {
    let named = attrs.contains_key("aria-label")
        || attrs.contains_key("aria-labelledby")
        || attrs.contains_key("alt")
        || attrs.contains_key("title")
        || attrs.contains_key("placeholder")
        || attrs.contains_key("id")
        || attrs.contains_key("name");
    let interactive = INTERACTIVE_TAGS.contains(&tag)
        || attrs.contains_key("role")
        || attrs.contains_key("tabindex")
        || attrs.contains_key("onclick")
        || attrs.contains_key("contenteditable")
        || is_heading(tag);
    let paragraph = tag == "p";
    if paragraph && *paragraph_count >= MAX_PARAGRAPH_CANDIDATES {
        return;
    }
    if !(named || interactive || paragraph) && tag != "iframe" && tag != "frame" {
        return;
    }
    let backend = node.get("backendNodeId").and_then(Value::as_i64);
    let node_id = node.get("nodeId").and_then(Value::as_i64);
    let mut children_backends = Vec::new();
    for child in node
        .get("children")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        if let Some(b) = child.get("backendNodeId").and_then(Value::as_i64) {
            children_backends.push(b);
        }
    }
    // Nearest form/section context for identity + aliasing.
    let context = form_stack
        .last()
        .filter(|s| !s.is_empty())
        .cloned()
        .or_else(|| section_stack.last().filter(|s| !s.is_empty()).cloned());
    let implicit_label = label_stack.last().filter(|s| !s.is_empty()).cloned();
    let text = if paragraph {
        paragraph_text(node, visible_ax_text)
    } else {
        direct_text(node)
    };
    if paragraph {
        *paragraph_count += 1;
    }
    out.push(RawNode {
        backend,
        node_id,
        tag: tag.to_string(),
        attrs: attrs.clone(),
        text,
        frame_path: frame_path.to_vec(),
        frame,
        doc_order: *doc_order,
        ancestry: ancestry.to_vec(),
        children_backends,
        context,
        implicit_label,
        inert_ancestor,
    });
    *doc_order += 1;
}

// ---------------------------------------------------------------------------
// Semantic labeling
// ---------------------------------------------------------------------------

fn role_for(tag: &str, attrs: &HashMap<String, String>, ax: &AxInfo) -> String {
    if let Some(r) = &ax.role {
        if !r.is_empty() && r != "none" && r != "presentation" && r != "generic" {
            return r.clone();
        }
    }
    // contenteditable hosts are textboxes even when AX reports generic.
    if attrs.contains_key("contenteditable") {
        return "textbox".to_string();
    }
    if let Some(r) = attrs.get("role") {
        return r.clone();
    }
    match tag {
        "button" => "button",
        "a" => "link",
        "input" => match attrs.get("type").map(String::as_str) {
            Some("checkbox") => "checkbox",
            Some("radio") => "radio",
            Some("submit") | Some("button") | Some("reset") | Some("image") => "button",
            _ => "textbox",
        },
        "select" => "combobox",
        "textarea" => "textbox",
        "option" => "option",
        h if is_heading(h) => "heading",
        "form" => "form",
        "table" => "table",
        "nav" => "navigation",
        "main" | "section" => "region",
        "img" => "img",
        "ul" | "ol" => "list",
        "li" => "listitem",
        _ => "generic",
    }
    .to_string()
}

fn name_for(
    raw: &RawNode,
    ax: &AxInfo,
    labels_for: &HashMap<String, String>,
    id_text: &HashMap<String, String>,
) -> Option<String> {
    if let Some(n) = &ax.name {
        if !n.trim().is_empty() {
            return Some(truncate(n));
        }
    }
    for key in ["aria-label", "alt"] {
        if let Some(v) = raw.attrs.get(key) {
            if !v.trim().is_empty() {
                return Some(truncate(v));
            }
        }
    }
    // aria-labelledby="id1 id2" → referenced elements' text.
    if let Some(ids) = raw.attrs.get("aria-labelledby") {
        let parts: Vec<String> = ids
            .split_whitespace()
            .filter_map(|id| id_text.get(id))
            .filter(|t| !t.trim().is_empty())
            .cloned()
            .collect();
        if !parts.is_empty() {
            return Some(truncate(&parts.join(" ")));
        }
    }
    if let Some(id) = raw.attrs.get("id") {
        if let Some(label) = labels_for.get(id) {
            return Some(truncate(label));
        }
    }
    if let Some(label) = &raw.implicit_label {
        if !label.trim().is_empty() {
            return Some(truncate(label));
        }
    }
    for key in ["placeholder", "title"] {
        if let Some(v) = raw.attrs.get(key) {
            if !v.trim().is_empty() {
                return Some(truncate(v));
            }
        }
    }
    if matches!(
        raw.tag.as_str(),
        "button" | "a" | "option" | "h1" | "h2" | "h3" | "h4" | "h5" | "h6"
    ) && !raw.text.is_empty()
    {
        return Some(truncate(&raw.text.clone()));
    }
    if let Some(value) = raw.attrs.get("value") {
        if matches!(
            raw.attrs.get("type").map(String::as_str),
            Some("submit") | Some("button") | Some("reset")
        ) && !value.trim().is_empty()
        {
            return Some(truncate(value));
        }
    }
    None
}

fn truncate(s: &str) -> String {
    let flat = s.split_whitespace().collect::<Vec<_>>().join(" ");
    flat.chars().take(MAX_TEXT_LEN).collect()
}

fn value_for(raw: &RawNode, ax: &AxInfo) -> Option<String> {
    if let Some(v) = &ax.value {
        if !v.trim().is_empty() {
            return Some(truncate(v));
        }
    }
    if raw
        .attrs
        .get("contenteditable")
        .is_some_and(|value| value != "false")
    {
        return (!raw.text.is_empty()).then(|| truncate(&raw.text));
    }
    match raw.tag.as_str() {
        "input" => match raw.attrs.get("type").map(String::as_str) {
            Some("checkbox") | Some("radio") => None, // state flags carry this
            _ => raw
                .attrs
                .get("value")
                .filter(|v| !v.is_empty())
                .map(|v| truncate(v)),
        },
        "textarea" => {
            if raw.text.is_empty() {
                None
            } else {
                Some(truncate(&raw.text.clone()))
            }
        }
        "select" => raw
            .attrs
            .get("value")
            .filter(|v| !v.is_empty())
            .map(|v| truncate(v)),
        _ => None,
    }
}

fn states_for(raw: &RawNode, ax: &AxInfo, role: &str) -> Vec<String> {
    let mut states = Vec::new();
    let input_type = raw
        .attrs
        .get("type")
        .map(|value| value.to_ascii_lowercase());
    let native_submit = (raw.tag == "button"
        && !matches!(input_type.as_deref(), Some("button" | "reset")))
        || (raw.tag == "input" && matches!(input_type.as_deref(), Some("submit" | "image")));
    if native_submit {
        states.push("submit".to_string());
    }
    if ax.disabled || raw.attrs.contains_key("disabled") {
        states.push("disabled".to_string());
    }
    if ax.readonly || raw.attrs.contains_key("readonly") {
        states.push("readonly".to_string());
    }
    if ax.required || raw.attrs.contains_key("required") {
        states.push("required".to_string());
    }
    // checked/selected: the content attribute does NOT reflect live toggles
    // (unlike `disabled`), so live AX state wins whenever present and the
    // attribute is only a fallback for backends that omit the property.
    let checked_state = match ax.checked {
        Some(b) => b,
        None => raw.attrs.contains_key("checked"),
    };
    if checked_state {
        states.push("checked".to_string());
    }
    if ax.selected == Some(true) {
        states.push("selected".to_string());
    }
    if ax.expanded == Some(true) {
        states.push("expanded".to_string());
    } else if ax.expanded == Some(false) && matches!(role, "combobox" | "button") {
        states.push("collapsed".to_string());
    }
    if ax.pressed == Some(true) {
        states.push("pressed".to_string());
    }
    if ax.focused {
        states.push("focused".to_string());
    }
    if role == "heading" {
        if let Some(level) = ax.level {
            states.push(format!("level-{level}"));
        }
    }
    if ax.modal && matches!(role, "dialog" | "alertdialog") {
        states.push("modal".to_string());
    }
    if role == "combobox" && raw.tag == "input" && raw.attrs.contains_key("list") {
        states.push("has-datalist".to_string());
    }
    if raw.attrs.contains_key("contenteditable") {
        states.push("editable".to_string());
    }
    states
}

fn kind_for(role: &str, tag: &str, attrs: &HashMap<String, String>) -> SemanticKind {
    match role {
        "button" => SemanticKind::Button,
        "link" => SemanticKind::Link,
        "textbox" | "searchbox" | "combobox" | "listbox" => {
            if role == "combobox" || tag == "select" {
                SemanticKind::OptionList
            } else {
                SemanticKind::TextInput
            }
        }
        "checkbox" | "radio" | "switch" => SemanticKind::Checkable,
        "option" => SemanticKind::Option,
        "heading" => SemanticKind::Heading,
        "form" => SemanticKind::Form,
        "dialog" | "alertdialog" => SemanticKind::Dialog,
        "alert" | "status" => SemanticKind::Alert,
        "table" | "grid" => SemanticKind::Table,
        "navigation" => SemanticKind::Navigation,
        "img" | "image" => SemanticKind::Image,
        "region" | "main" | "section" => SemanticKind::Region,
        _ => match tag {
            "input" => match attrs.get("type").map(String::as_str) {
                Some("checkbox") | Some("radio") => SemanticKind::Checkable,
                Some("submit") | Some("button") => SemanticKind::Button,
                _ => SemanticKind::TextInput,
            },
            "select" | "datalist" => SemanticKind::OptionList,
            "textarea" => SemanticKind::TextInput,
            "p" => SemanticKind::Text,
            _ => SemanticKind::Generic,
        },
    }
}

fn is_actionable(role: &str, tag: &str, attrs: &HashMap<String, String>) -> bool {
    if attrs.contains_key("onclick") {
        return true;
    }
    matches!(
        role,
        "button"
            | "link"
            | "textbox"
            | "searchbox"
            | "combobox"
            | "listbox"
            | "checkbox"
            | "radio"
            | "switch"
            | "option"
            | "menuitem"
            | "tab"
            | "slider"
            | "spinbutton"
    ) || matches!(
        tag,
        "a" | "button" | "input" | "select" | "textarea" | "option" | "summary"
    ) || attrs.contains_key("contenteditable")
}

// ---------------------------------------------------------------------------
// Geometry collection (concurrent, deterministic output)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct Geometry {
    bbox: Option<BBox>,
    display: String,
    visibility_css: String,
    opacity: f64,
    pointer_events: String,
}

async fn collect_geometry(
    transport: &dyn CdpTransport,
    session: &CdpSessionId,
    backend: Option<i64>,
    node_id: Option<i64>,
) -> Geometry {
    let mut out = Geometry {
        bbox: None,
        display: String::new(),
        visibility_css: "visible".to_string(),
        opacity: 1.0,
        pointer_events: "auto".to_string(),
    };
    if let Some(b) = backend {
        // Box model.
        if let Ok(res) = transport
            .command_in_session(
                session,
                "DOM.getBoxModel",
                serde_json::json!({"backendNodeId": b}),
            )
            .await
        {
            if let Some(content) = res
                .get("model")
                .and_then(|m| m.get("content"))
                .and_then(Value::as_array)
            {
                let nums: Vec<f64> = content.iter().filter_map(Value::as_f64).collect();
                if nums.len() == 8 {
                    let xs = [nums[0], nums[2], nums[4], nums[6]];
                    let ys = [nums[1], nums[3], nums[5], nums[7]];
                    let (x0, x1) = (
                        xs.iter().cloned().fold(f64::INFINITY, f64::min),
                        xs.iter().cloned().fold(f64::NEG_INFINITY, f64::max),
                    );
                    let (y0, y1) = (
                        ys.iter().cloned().fold(f64::INFINITY, f64::min),
                        ys.iter().cloned().fold(f64::NEG_INFINITY, f64::max),
                    );
                    out.bbox = Some(BBox {
                        x: x0,
                        y: y0,
                        width: (x1 - x0).max(0.0),
                        height: (y1 - y0).max(0.0),
                    });
                }
            }
        }
    }
    if let Some(n) = node_id {
        if let Ok(res) = transport
            .command_in_session(
                session,
                "CSS.getComputedStyleForNode",
                serde_json::json!({"nodeId": n}),
            )
            .await
        {
            if let Some(styles) = res.get("computedStyle").and_then(Value::as_array) {
                for s in styles {
                    let name = s.get("name").and_then(Value::as_str).unwrap_or("");
                    let value = s.get("value").and_then(Value::as_str).unwrap_or("");
                    match name {
                        "display" => out.display = value.to_lowercase(),
                        "visibility" => out.visibility_css = value.to_lowercase(),
                        "opacity" => out.opacity = value.parse().unwrap_or(1.0),
                        "pointer-events" => out.pointer_events = value.to_lowercase(),
                        _ => {}
                    }
                }
            }
        }
    }
    // Hit testing runs as a separate pass (it needs the box center).
    out
}

// ---------------------------------------------------------------------------
// Public collection entry point
// ---------------------------------------------------------------------------

/// Observe a tab fully: collect, merge, classify, bind, snapshot.
pub(crate) async fn observe_full(
    session: &BrowserSession,
    tab: &TabId,
) -> Result<SemanticSnapshot, BrowserRuntimeError> {
    let (target, cdp_session) = session.tab_session_pub(tab).await?;
    let transport = session.transport_pub().await;
    let generation = session.generation();

    // 1. Independent collections concurrently.
    let (ax_res, dom_res, layout_res, href_res, title_res, scroll_res) = tokio::join!(
        transport.command_in_session(&cdp_session, "Accessibility.getFullAXTree", serde_json::json!({})),
        transport.command_in_session(
            &cdp_session,
            "DOM.getDocument",
            serde_json::json!({"depth": -1, "pierce": true})
        ),
        transport.command_in_session(&cdp_session, "Page.getLayoutMetrics", serde_json::json!({})),
        transport.command_in_session(
            &cdp_session,
            "Runtime.evaluate",
            serde_json::json!({"expression": "window.location.href", "returnByValue": true})
        ),
        transport.command_in_session(
            &cdp_session,
            "Runtime.evaluate",
            serde_json::json!({"expression": "document.title", "returnByValue": true})
        ),
        transport.command_in_session(
            &cdp_session,
            "Runtime.evaluate",
            serde_json::json!({"expression": "({x: window.scrollX, y: window.scrollY})", "returnByValue": true})
        ),
    );

    let url = eval_string(href_res, &target)?;
    let title = eval_string(title_res, &target).ok();
    let viewport = parse_viewport(layout_res);
    let (scroll_x, scroll_y) = parse_scroll(scroll_res);

    // 2. AX index by backend id.
    let mut ax_by_backend: HashMap<i64, AxInfo> = HashMap::new();
    let mut visible_ax_text = HashSet::new();
    if let Ok(ax) = ax_res {
        if let Some(nodes) = ax.get("nodes").and_then(Value::as_array) {
            for node in nodes {
                let (backend, info) = parse_ax_node(node);
                if let Some(b) = backend {
                    let ax_role = node
                        .get("chromeRole")
                        .and_then(|role| role.get("value"))
                        .and_then(Value::as_str)
                        .or_else(|| {
                            node.get("role")
                                .and_then(|role| role.get("value"))
                                .and_then(Value::as_str)
                        });
                    let is_visible_text = !info.ignored
                        && !info.hidden
                        && ax_role.is_some_and(|role| {
                            matches!(role.to_ascii_lowercase().as_str(), "statictext")
                        });
                    if is_visible_text {
                        visible_ax_text.insert(b);
                    }
                    ax_by_backend.insert(b, info);
                }
            }
        }
    }

    // 3. DOM walk.
    let dom = dom_res.map_err(|e| BrowserRuntimeError::from_cdp(e, Some(&target)))?;
    let mut raw: Vec<RawNode> = Vec::new();
    let mut labels_for: HashMap<String, String> = HashMap::new();
    let mut id_text: HashMap<String, String> = HashMap::new();
    let mut doc_order = 0u64;
    let mut paragraph_count = 0usize;
    if let Some(root) = dom.get("root") {
        walk(
            root,
            &mut raw,
            &mut labels_for,
            &["main".to_string()],
            None,
            &[],
            &mut doc_order,
            &mut vec![],
            &mut vec![],
            &mut vec![],
            &mut id_text,
            &visible_ax_text,
            &mut paragraph_count,
            false,
        );
    }

    // Form contexts need a second look: nearest form ancestor recorded during
    // walk was approximated; recompute cheaply is skipped (walk already did).
    // 4. Label association (pass two) is folded into name_for via labels_for.

    // Alive backends = everything seen this snapshot (level-1 signal).
    let alive: HashSet<BackendNodeId> = raw
        .iter()
        .filter_map(|n| n.backend)
        .map(BackendNodeId)
        .collect();

    // Descendant lookup for hit-test tolerance.
    let mut children: HashMap<i64, Vec<i64>> = HashMap::new();
    for n in &raw {
        if let Some(b) = n.backend {
            children.insert(b, n.children_backends.clone());
        }
    }

    // 5. Candidate labeling (truncate deterministically past the cap).
    let mut ordered_raw = raw;
    ordered_raw.sort_by_key(|node| node.doc_order);
    let mut candidates = Vec::new();
    let mut paragraph_candidates = Vec::new();
    for node in ordered_raw {
        if node.tag == "p" {
            paragraph_candidates.push(node);
        } else if candidates.len() < MAX_CANDIDATES {
            candidates.push(node);
        }
    }
    candidates.extend(paragraph_candidates);
    candidates.sort_by_key(|node| node.doc_order);

    // Sibling-text for `nearby`: index direct text by parent signature is
    // overkill; use the candidate's own text + label chain instead.
    struct Labeled {
        raw: RawNode,
        role: String,
        name: Option<String>,
        value: Option<String>,
        states: Vec<String>,
        kind: SemanticKind,
        ax: AxInfo,
        context: Option<String>,
    }
    let mut labeled: Vec<Labeled> = Vec::with_capacity(candidates.len());
    for node in candidates {
        let ax = node
            .backend
            .and_then(|b| ax_by_backend.get(&b))
            .cloned()
            .unwrap_or_default();
        if ax.ignored {
            continue;
        }
        let role = role_for(&node.tag, &node.attrs, &ax);
        let name = name_for(&node, &ax, &labels_for, &id_text);
        let value = value_for(&node, &ax);
        let states = states_for(&node, &ax, &role);
        let kind = kind_for(&role, &node.tag, &node.attrs);
        // Context: nearest form/section recorded at walk time is approximated
        // from ancestry tags here (walk stored raw ancestry only).
        labeled.push(Labeled {
            context: node.context.clone(),
            raw: node,
            role,
            name,
            value,
            states,
            kind,
            ax,
        });
    }

    // 6. Concurrent geometry per candidate.
    let mut geo_tasks = tokio::task::JoinSet::new();
    for (i, item) in labeled.iter().enumerate() {
        let t = transport.clone();
        let s = cdp_session.clone();
        let backend = item.raw.backend;
        let node_id = item.raw.node_id;
        geo_tasks.spawn(async move {
            // Center unknown until box arrives: two-phase (box first, then
            // hit test) doubles latency; instead hit-test after via second
            // pass only for interactable-looking candidates. Here: box+style.
            let g = collect_geometry(t.as_ref(), &s, backend, node_id).await;
            (i, g)
        });
    }
    let mut geos: Vec<Option<Geometry>> = vec![None; labeled.len()];
    while let Some(res) = geo_tasks.join_next().await {
        if let Ok((i, g)) = res {
            geos[i] = Some(g);
        }
    }

    // 7. Hit-test pass for visible, enabled, actionable candidates.
    // Fast path: DOM.getNodeForLocation. Fallback: resolve the node and ask
    // JS whether the point hits it or a descendant (covers text-node
    // topmost hits, which carry no usable backend id).
    let mut hit_tasks = tokio::task::JoinSet::new();
    for (i, item) in labeled.iter().enumerate() {
        let bbox = geos[i].as_ref().and_then(|g| g.bbox.clone());
        let actionable = is_actionable(&item.role, &item.raw.tag, &item.raw.attrs);
        let enabled = !item.ax.disabled && !item.raw.attrs.contains_key("disabled");
        if bbox.as_ref().is_some_and(|b| !b.is_empty()) && actionable && enabled {
            let t = transport.clone();
            let s = cdp_session.clone();
            let backend = item.raw.backend;
            // Descendant backend set for the cheap path (bounded).
            let subtree: HashSet<i64> = backend
                .map(|b| subtree_backends(&children, b, 200))
                .unwrap_or_default();
            let (cx, cy) = bbox.map(|b| b.center()).unwrap();
            hit_tasks.spawn(async move {
                // DOM.getBoxModel already returns viewport CSS coordinates.
                let x = cx.round() as i64;
                let y = cy.round() as i64;
                let topmost = t
                    .command_in_session(
                        &s,
                        "DOM.getNodeForLocation",
                        serde_json::json!({"x": x, "y": y}),
                    )
                    .await
                    .ok()
                    .and_then(|r| r.get("backendNodeId").and_then(Value::as_i64).to_owned());
                let mut pass =
                    topmost.is_some_and(|top| Some(top) == backend || subtree.contains(&top));
                if !pass {
                    // Fallback: JS contains-check against the resolved node
                    // (covers text-node topmost hits).
                    if let Some(b) = backend {
                        pass = hit_test_contains(t.as_ref(), &s, b, x, y).await;
                    }
                }
                (i, pass)
            });
        }
    }
    let mut hit_pass: Vec<Option<bool>> = vec![None; labeled.len()];
    while let Some(res) = hit_tasks.join_next().await {
        if let Ok((i, p)) = res {
            hit_pass[i] = Some(p);
        }
    }

    // 8. Classify + fingerprint + alias inputs.
    struct Built {
        element: SemanticElement,
        signals: FingerprintSignals,
        backend: Option<BackendNodeId>,
        alias_hint: AliasInput,
    }
    let mut built: Vec<Built> = Vec::with_capacity(labeled.len());
    for (i, item) in labeled.into_iter().enumerate() {
        let geo = geos[i].take().unwrap_or_else(|| Geometry {
            bbox: None,
            display: String::new(),
            visibility_css: "visible".into(),
            opacity: 1.0,
            pointer_events: "auto".into(),
        });
        let backend = item.raw.backend;
        // Tasks spawn for actionable candidates only; `None` means the
        // calls failed → conservatively no pass. (Non-actionable elements
        // ignore this flag in classification.)
        let hit_pass = hit_pass[i].unwrap_or(false);
        if std::env::var("BROWSER_AGENT_OBSERVE_DEBUG").is_ok() {
            eprintln!(
                "[obs] {} box={:?} display={} op={} ptr={} hit={:?} action={}",
                item.role,
                geo.bbox,
                geo.display,
                geo.opacity,
                geo.pointer_events,
                hit_pass,
                is_actionable(&item.role, &item.raw.tag, &item.raw.attrs)
            );
        }
        let actionable = is_actionable(&item.role, &item.raw.tag, &item.raw.attrs);
        let ax_hidden = item.ax.hidden;
        let input = ClassifyInput {
            has_box: geo.bbox.is_some(),
            bbox: geo.bbox.clone().unwrap_or_default(),
            viewport: viewport.clone(),
            display: if ax_hidden {
                "none".to_string()
            } else {
                geo.display.clone()
            },
            visibility_css: geo.visibility_css.clone(),
            opacity: geo.opacity,
            pointer_events: geo.pointer_events.clone(),
            disabled: item.ax.disabled || item.raw.attrs.contains_key("disabled"),
            inert: item.raw.attrs.contains_key("inert") || item.raw.inert_ancestor,
            hit_test_pass: if actionable { hit_pass } else { true },
            readonly: item.ax.readonly || item.raw.attrs.contains_key("readonly"),
            actionable,
        };
        let c = classify(&input);
        // Geometry bucket (coarse grid: volatile, scoring-only).
        let geometry = geo
            .bbox
            .as_ref()
            .map(|b| {
                format!(
                    "{}x{}@{},{}",
                    (b.width / 50.0).round() as i64,
                    (b.height / 50.0).round() as i64,
                    (b.x / 50.0).round() as i64,
                    (b.y / 50.0).round() as i64
                )
            })
            .unwrap_or_default();
        let ancestry = item.raw.ancestry.join(">");
        let mut stable_attrs = Vec::new();
        if let Some(t) = item.raw.attrs.get("data-testid") {
            stable_attrs.push(("data-testid".to_string(), t.clone()));
        }
        let signals = FingerprintSignals {
            role: item.role.clone(),
            name: item.name.clone(),
            text: if item.raw.text.is_empty() {
                None
            } else {
                Some(item.raw.text.clone())
            },
            label: item
                .raw
                .attrs
                .get("id")
                .and_then(|id| labels_for.get(id))
                .cloned()
                .or_else(|| item.raw.implicit_label.clone()),
            input_name: item.raw.attrs.get("name").cloned(),
            placeholder: item.raw.attrs.get("placeholder").cloned(),
            input_type: Some(item.raw.tag.clone()),
            nearby: None,
            ancestry,
            frame_path: item.raw.frame_path.clone(),
            geometry,
            backend,
            stable_attrs,
            context: item.context.clone(),
        };
        let fp = fingerprint(&signals);
        let mut hints = Vec::new();
        if let Some(n) = &item.name {
            hints.push(n.clone());
        }
        if let Some(v) = &item.value {
            if item.role == "button" || item.role == "option" {
                hints.push(v.clone());
            }
        }
        if !item.raw.text.is_empty()
            && matches!(
                item.kind,
                SemanticKind::Button | SemanticKind::Link | SemanticKind::Heading
            )
        {
            hints.push(item.raw.text.clone());
        }
        let alias_hint = AliasInput {
            doc_order: item.raw.doc_order,
            role: item.role.clone(),
            hints,
            context: item.context.clone(),
        };
        let frame = item.raw.frame.clone().map(FrameId::from);
        built.push(Built {
            element: SemanticElement {
                id: 0,
                reference: String::new(),
                generation,
                role: item.role,
                accessible_name: item.name,
                text: if item.raw.text.is_empty() {
                    None
                } else {
                    Some(item.raw.text)
                },
                value: item.value,
                state: item.states,
                bbox: geo.bbox,
                visible: c.visible,
                visibility: c.visibility,
                enabled: c.enabled,
                interactable: c.interactable,
                frame,
                frame_path: item.raw.frame_path,
                semantic_kind: item.kind,
                backend_node_id: backend.map(BackendNodeId),
                doc_order: item.raw.doc_order,
                ancestry: item.raw.ancestry.clone(),
                confidence: if item.ax.role.is_some() { 1.0 } else { 0.8 },
                fingerprint: fp,
            },
            signals,
            backend: backend.map(BackendNodeId),
            alias_hint,
        });
    }

    // 9. Registry bind/reacquire + alias assignment.
    let aliases = assign_aliases(
        &built
            .iter()
            .map(|b| b.alias_hint.clone())
            .collect::<Vec<_>>(),
    );
    let registries = session.registries_map();
    let mut registries = registries.write().await;
    let registry = registries
        .entry(target.clone())
        .or_insert_with(ElementRegistry::new);
    // Reconcile with previous entries: match old ids to new indices.
    let prev_ids: Vec<u64> = registry.entry_ids();
    let candidates: Vec<ReacquireCandidate> = built
        .iter()
        .map(|b| ReacquireCandidate {
            signals: b.signals.clone(),
        })
        .collect();
    let mut claimed_new: HashSet<usize> = HashSet::new();
    // Map new index -> (id, alias to keep).
    let mut bindings: HashMap<usize, (u64, String)> = HashMap::new();
    // Next fresh id base (registry allocates).
    for old_id in prev_ids {
        match registry.reacquire(old_id, &candidates, &alive) {
            ReacquireOutcome::Bound { id, .. } => {
                // Find the best candidate index again for binding (first
                // unclaimed candidate with score above floor).
                let mut best: Option<(usize, u32)> = None;
                for (idx, cand) in candidates.iter().enumerate() {
                    if claimed_new.contains(&idx) {
                        continue;
                    }
                    let stored = registry.signals_of(id).expect("entry present");
                    let s = score(stored, &cand.signals);
                    if s >= SCORE_WEAK && best.map_or(true, |(_, bs)| s > bs) {
                        best = Some((idx, s));
                    }
                }
                if let Some((idx, _)) = best {
                    claimed_new.insert(idx);
                    let alias = registry.alias_of(id).expect("alias present").to_string();
                    registry.refresh(id, generation);
                    registry.update_signals(
                        id,
                        &built[idx].signals,
                        &built[idx].element.fingerprint,
                        built[idx].backend,
                    );
                    bindings.insert(idx, (id, alias));
                }
            }
            ReacquireOutcome::Gone | ReacquireOutcome::Ambiguous { .. } => {
                registry.remove(old_id);
            }
        }
    }
    // Bind the rest with fresh aliases (collision-free vs kept aliases).
    let mut taken: HashSet<String> = bindings.values().map(|(_, a)| a.clone()).collect();
    for (idx, item) in built.iter().enumerate() {
        if bindings.contains_key(&idx) {
            continue;
        }
        let mut alias = aliases[idx].clone();
        let mut n = 2u32;
        while taken.contains(&alias) {
            alias = format!("{}_{n}", aliases[idx]);
            n += 1;
        }
        taken.insert(alias.clone());
        let reference = registry.bind(
            &alias,
            item.signals.clone(),
            item.element.fingerprint.clone(),
            item.backend,
        );
        // Sync generation (bind uses registry generation; align it).
        registry.refresh(reference.id, generation);
        bindings.insert(idx, (reference.id, alias));
    }
    for (idx, item) in built.iter_mut().enumerate() {
        let (id, alias) = bindings[&idx].clone();
        item.element.id = id;
        item.element.reference = alias;
        item.element.generation = generation;
    }

    // 10. Assemble snapshot.
    let mut elements: Vec<SemanticElement> = built.into_iter().map(|b| b.element).collect();
    elements.sort_by_key(|e| e.doc_order);

    let focused = ax_focused_ref(&ax_by_backend, &elements);
    let headings: Vec<String> = elements
        .iter()
        .filter(|e| e.semantic_kind == SemanticKind::Heading)
        .filter_map(|e| e.accessible_name.clone().or_else(|| e.text.clone()))
        .collect();
    let structure: Vec<(String, String)> = elements
        .iter()
        .filter(|e| e.interactable)
        .map(|e| {
            (
                e.role.clone(),
                e.accessible_name
                    .clone()
                    .or_else(|| e.text.clone())
                    .unwrap_or_default(),
            )
        })
        .collect();
    let forms = summarize_forms(&elements);
    let form_names: Vec<String> = forms
        .iter()
        .map(|f| f.name.clone().unwrap_or_default())
        .collect();
    let important_text = elements
        .iter()
        .filter_map(|e| e.accessible_name.clone().or_else(|| e.text.clone()))
        .take(50)
        .collect::<Vec<_>>()
        .join("|");
    let text_hash = browser_agent_observation::stable_hash_hex(&important_text);
    let fp = page_fingerprint(&url, &headings, &structure, &form_names, &text_hash);

    let text_blocks = build_text_blocks(&elements);
    let text_excerpt = {
        let joined = headings.join(" · ");
        if joined.is_empty() {
            None
        } else {
            Some(joined.chars().take(2000).collect())
        }
    };
    let dialog_summaries = build_dialogs(&elements);
    let dialog_names = dialog_summaries
        .iter()
        .filter_map(|d| d.name.clone())
        .collect();

    let snapshot = SemanticSnapshot {
        schema_version: 1,
        url: url.clone(),
        title,
        tabs: session.tab_ids_pub().await,
        active_tab: Some(tab.clone()),
        active_frame: None,
        viewport,
        scroll: browser_agent_observation::ScrollState {
            x: scroll_x,
            y: scroll_y,
        },
        interactive_elements: elements
            .iter()
            .filter(|e| e.interactable)
            .cloned()
            .collect(),
        elements,
        text_excerpt,
        text_blocks,
        form_count: forms.len(),
        forms,
        dialogs: dialog_names,
        dialog_summaries,
        focused,
        page_fingerprint: fp,
        state_generation: generation,
    };

    // 11. Delta vs last snapshot + store.
    let delta = {
        let snapshots = session.snapshots_map();
        let mut snaps = snapshots.write().await;
        let prev = snaps.get(&target);
        let d = match prev {
            Some(p) => diff_snapshots(p, &snapshot),
            None => SnapshotDelta::default(),
        };
        snaps.insert(target.clone(), snapshot.clone());
        d
    };
    session.deltas_map().write().await.insert(target, delta);
    Ok(snapshot)
}

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

fn eval_string(
    res: Result<Value, browser_agent_cdp::CdpError>,
    target: &TargetId,
) -> Result<String, BrowserRuntimeError> {
    let v = res.map_err(|e| BrowserRuntimeError::from_cdp(e, Some(target)))?;
    v.get("result")
        .and_then(|r| r.get("value"))
        .and_then(Value::as_str)
        .map(str::to_string)
        .ok_or_else(|| BrowserRuntimeError::TargetClosed(target.clone()))
}

fn parse_viewport(res: Result<Value, browser_agent_cdp::CdpError>) -> Viewport {
    let v = match res {
        Ok(v) => v,
        Err(_) => {
            return Viewport {
                width: 1280.0,
                height: 800.0,
                device_scale_factor: 1.0,
            }
        }
    };
    let w = v
        .get("cssLayoutViewport")
        .and_then(|l| l.get("clientWidth"))
        .and_then(Value::as_f64)
        .unwrap_or(1280.0);
    let h = v
        .get("cssLayoutViewport")
        .and_then(|l| l.get("clientHeight"))
        .and_then(Value::as_f64)
        .unwrap_or(800.0);
    Viewport {
        width: w,
        height: h,
        device_scale_factor: 1.0,
    }
}

fn parse_scroll(res: Result<Value, browser_agent_cdp::CdpError>) -> (i64, i64) {
    let v = match res {
        Ok(v) => v,
        Err(_) => return (0, 0),
    };
    let val = v.get("result").and_then(|r| r.get("value"));
    let x = val
        .and_then(|o| o.get("x"))
        .and_then(Value::as_i64)
        .unwrap_or(0);
    let y = val
        .and_then(|o| o.get("y"))
        .and_then(Value::as_i64)
        .unwrap_or(0);
    (x, y)
}

/// Bounded descendant-backend set for hit-test tolerance.
pub(crate) fn subtree_backends(
    children: &HashMap<i64, Vec<i64>>,
    root: i64,
    cap: usize,
) -> HashSet<i64> {
    let mut out = HashSet::new();
    let mut stack = vec![root];
    while let Some(current) = stack.pop() {
        if out.len() >= cap {
            break;
        }
        if !out.insert(current) {
            continue;
        }
        if let Some(kids) = children.get(&current) {
            stack.extend(kids.iter().copied());
        }
    }
    out
}

/// JS contains-check fallback: does the viewport point hit the node or a
/// descendant? Resolves the backend to an object id first.
pub(crate) async fn hit_test_contains(
    transport: &dyn CdpTransport,
    session: &CdpSessionId,
    backend: i64,
    x: i64,
    y: i64,
) -> bool {
    let object_id = transport
        .command_in_session(
            session,
            "DOM.resolveNode",
            serde_json::json!({"backendNodeId": backend}),
        )
        .await
        .ok()
        .and_then(|r| {
            r.get("object")
                .and_then(|o| o.get("objectId"))
                .and_then(Value::as_str)
                .map(str::to_string)
        });
    let Some(object_id) = object_id else {
        return false;
    };
    let result = transport
        .command_in_session(
            session,
            "Runtime.callFunctionOn",
            serde_json::json!({
                "objectId": object_id,
                "functionDeclaration": include_str!("mechanics/hit-test-contains.js"),
                "arguments": [{"value": x}, {"value": y}],
                "returnByValue": true,
            }),
        )
        .await;
    result
        .ok()
        .and_then(|r| {
            r.get("result")
                .and_then(|v| v.get("value"))
                .and_then(Value::as_bool)
        })
        .unwrap_or(false)
}

fn ax_focused_ref(_ax: &HashMap<i64, AxInfo>, _elements: &[SemanticElement]) -> Option<String> {
    // Focused backend → element ref resolution happens after binding; the
    // observer records focus from AX `focused` state flags instead.
    _elements
        .iter()
        .find(|e| e.state.iter().any(|s| s == "focused"))
        .map(|e| e.reference.clone())
}

fn summarize_forms(elements: &[SemanticElement]) -> Vec<FormSummary> {
    // Group controls by shared context is M3 work (needs form ancestry in
    // signals); M2 groups by identical frame path + explicit form markers.
    // For now: one synthetic group per run is wrong — instead group by the
    // `context` each control was labeled with. Context currently flows only
    // through fingerprints; approximate via submit-button proximity is out
    // of scope. Emit per-kind groups only when controls exist.
    let controls: Vec<String> = elements
        .iter()
        .filter(|e| {
            matches!(
                e.semantic_kind,
                SemanticKind::TextInput
                    | SemanticKind::Checkable
                    | SemanticKind::Option
                    | SemanticKind::OptionList
            )
        })
        .map(|e| e.reference.clone())
        .collect();
    if controls.is_empty() {
        return Vec::new();
    }
    let submit = elements
        .iter()
        .find(|e| e.semantic_kind == SemanticKind::Button && e.state.iter().any(|s| s == "submit"))
        .map(|e| e.reference.clone());
    vec![FormSummary {
        name: None,
        controls,
        submit,
        frame_path: vec!["main".to_string()],
    }]
}

fn build_text_blocks(elements: &[SemanticElement]) -> Vec<browser_agent_observation::TextBlock> {
    elements
        .iter()
        .filter(|e| {
            matches!(
                e.semantic_kind,
                SemanticKind::Heading | SemanticKind::Alert | SemanticKind::Text
            ) && (e.accessible_name.is_some() || e.text.is_some())
                && (e.semantic_kind != SemanticKind::Text
                    || e.visibility == browser_agent_observation::VisibilityClass::Visible)
        })
        .take(50)
        .map(|e| {
            let text = e
                .accessible_name
                .clone()
                .or_else(|| e.text.clone())
                .unwrap_or_default();
            let (kind, level) = if e.semantic_kind == SemanticKind::Heading {
                (
                    TextKind::Heading,
                    e.state
                        .iter()
                        .find_map(|s| s.strip_prefix("level-").and_then(|n| n.parse().ok())),
                )
            } else if e.semantic_kind == SemanticKind::Text {
                (TextKind::Paragraph, None)
            } else {
                (TextKind::Alert, None)
            };
            TextBlock {
                kind,
                level,
                text,
                frame_path: e.frame_path.clone(),
            }
        })
        .collect()
}

fn build_dialogs(elements: &[SemanticElement]) -> Vec<DialogSummary> {
    elements
        .iter()
        .filter(|e| e.semantic_kind == SemanticKind::Dialog)
        .map(|e| DialogSummary {
            kind: e.role.clone(),
            name: e.accessible_name.clone().or_else(|| e.text.clone()),
            modal: e.state.iter().any(|s| s == "modal"),
            frame_path: e.frame_path.clone(),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn submit_state_requires_native_submit_semantics() {
        for (tag, input_type, expected) in [
            ("button", None, true),
            ("button", Some("submit"), true),
            ("button", Some("button"), false),
            ("button", Some("reset"), false),
            ("input", Some("SUBMIT"), true),
            ("input", Some("image"), true),
            ("input", Some("button"), false),
            ("div", Some("submit"), false),
        ] {
            let mut raw = RawNode {
                tag: tag.to_string(),
                ..RawNode::default()
            };
            if let Some(input_type) = input_type {
                raw.attrs.insert("type".into(), input_type.into());
            }
            let states = states_for(&raw, &AxInfo::default(), "button");
            assert_eq!(states.iter().any(|state| state == "submit"), expected);
        }
    }
}
