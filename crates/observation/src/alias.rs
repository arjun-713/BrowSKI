//! Deterministic model-facing alias generation.
//!
//! Aliases (`@email`, `@submit`, `@billing_continue`) are convenience for
//! the model. The numeric registry id remains the actual identity. Rules:
//!
//! - No LLM calls: pure function of role, names, labels, and form/section
//!   context, assigned in document order.
//! - Duplicates get numeric suffixes (`@continue`, `@continue_2`), or
//!   context prefixes when contexts differ (`@billing_continue`).
//! - Deterministic: identical inputs in identical order yield identical
//!   aliases, every run.

use std::collections::{HashMap, HashSet};

/// One alias request, in document order.
#[derive(Debug, Clone)]
pub struct AliasInput {
    pub doc_order: u64,
    pub role: String,
    /// Name candidates in priority order (accessible name, label, text,
    /// placeholder, value).
    pub hints: Vec<String>,
    /// Form/section context, e.g. `billing`.
    pub context: Option<String>,
}

fn slugify(text: &str) -> String {
    let words: Vec<String> = text
        .to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .take(4)
        .map(str::to_string)
        .collect();
    let slug = words.join("_");
    slug.chars().take(40).collect()
}

fn slugify_context(text: &str) -> String {
    let words: Vec<String> = text
        .to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| !w.is_empty())
        .take(2)
        .map(str::to_string)
        .collect();
    words.join("_")
}

fn base_slug(input: &AliasInput) -> String {
    for hint in &input.hints {
        let slug = slugify(hint);
        if !slug.is_empty() && slug != "_" {
            return slug;
        }
    }
    let role_slug = slugify(&input.role);
    if !role_slug.is_empty() {
        return role_slug;
    }
    "control".to_string()
}

/// Assign `@`-prefixed unique aliases, returned in input order.
///
/// - Unique bases stay bare (`@email`), even with a form context.
/// - Colliding bases disambiguate by context first (`@billing_continue`,
///   `@shipping_continue`), then by number (`@continue`, `@continue_2`).
/// - Residual collisions (a preferred name taken by an earlier element)
///   suffix deterministically.
/// - Pure function of inputs in document order: identical pages yield
///   identical aliases. No LLM calls.
pub fn assign_aliases(inputs: &[AliasInput]) -> Vec<String> {
    // Deterministic regardless of caller order.
    let mut order: Vec<usize> = (0..inputs.len()).collect();
    order.sort_by_key(|&i| (inputs[i].doc_order, i));

    let bases: Vec<String> = order.iter().map(|&i| base_slug(&inputs[i])).collect();
    let mut counts: HashMap<String, usize> = HashMap::new();
    for b in &bases {
        *counts.entry(b.clone()).or_insert(0) += 1;
    }

    let mut taken: HashSet<String> = HashSet::new();
    let mut out: Vec<String> = vec![String::new(); inputs.len()];
    let mut claim = |preferred: &str| -> String {
        let mut candidate = preferred.to_string();
        let mut n = 2u32;
        while taken.contains(&candidate) {
            candidate = format!("{preferred}_{n}");
            n += 1;
        }
        taken.insert(candidate.clone());
        format!("@{candidate}")
    };

    for (pos, &idx) in order.iter().enumerate() {
        let base = &bases[pos];
        let preferred = if counts[base] > 1 {
            match &inputs[idx].context {
                Some(ctx) => {
                    let c = slugify_context(ctx);
                    if c.is_empty() {
                        base.clone()
                    } else {
                        format!("{c}_{base}")
                    }
                }
                None => base.clone(),
            }
        } else {
            base.clone()
        };
        out[idx] = claim(&preferred);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input(order: u64, role: &str, hint: &str, context: Option<&str>) -> AliasInput {
        AliasInput {
            doc_order: order,
            role: role.into(),
            hints: if hint.is_empty() {
                vec![]
            } else {
                vec![hint.into()]
            },
            context: context.map(str::to_string),
        }
    }

    #[test]
    fn basic_slugs() {
        let out = assign_aliases(&[
            input(0, "textbox", "Search jobs", None),
            input(1, "button", "Apply", None),
        ]);
        assert_eq!(out, vec!["@search_jobs", "@apply"]);
    }

    #[test]
    fn duplicate_names_numbered_in_doc_order() {
        let out = assign_aliases(&[
            input(0, "button", "Continue", None),
            input(1, "button", "Continue", None),
        ]);
        assert_eq!(out, vec!["@continue", "@continue_2"]);
    }

    #[test]
    fn distinct_contexts_prefixed() {
        let out = assign_aliases(&[
            input(0, "button", "Continue", Some("billing")),
            input(1, "button", "Continue", Some("shipping")),
        ]);
        assert_eq!(out, vec!["@billing_continue", "@shipping_continue"]);
    }

    #[test]
    fn deterministic_regardless_of_input_order() {
        let a = assign_aliases(&[
            input(1, "button", "Continue", None),
            input(0, "textbox", "Email", None),
        ]);
        let b = assign_aliases(&[
            input(0, "textbox", "Email", None),
            input(1, "button", "Continue", None),
        ]);
        assert_eq!(a[1], b[0]);
        assert_eq!(a[0], b[1]);
    }

    #[test]
    fn role_fallback_and_empty_hints() {
        let out = assign_aliases(&[input(0, "button", "", None)]);
        assert_eq!(out, vec!["@button"]);
    }
}
