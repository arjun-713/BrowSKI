//! Structured browser actions. Only these cross the agent boundary:
//! no CSS selectors ever come from the model — targets are [`ElementRef`]s
//! bound by the observation layer.

use browser_agent_element_registry::ElementRef;
use browser_agent_observation::TabId;
use browser_agent_verification::ExpectedEffect;
use serde::{Deserialize, Serialize};

/// Mouse button for clicks.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum MouseButton {
    #[default]
    Left,
    Middle,
    Right,
}

/// Click tuning.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ClickOptions {
    #[serde(default)]
    pub button: MouseButton,
    /// 1 = click, 2 = double-click.
    #[serde(default = "default_click_count")]
    pub click_count: u32,
}

fn default_click_count() -> u32 {
    1
}

impl Default for ClickOptions {
    fn default() -> Self {
        Self {
            button: MouseButton::Left,
            click_count: 1,
        }
    }
}

/// Which option a select should settle on.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum SelectBy {
    #[default]
    Value,
    Label,
}

/// Validated browser action with an optional declared postcondition.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum BrowserAction {
    Click {
        target: ElementRef,
        #[serde(default)]
        options: ClickOptions,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Type {
        target: ElementRef,
        text: String,
        /// Clear existing content first (default true).
        #[serde(default = "default_true")]
        clear: bool,
        /// Press Enter after typing (form submit gesture).
        #[serde(default)]
        submit: bool,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Select {
        target: ElementRef,
        value: String,
        #[serde(default)]
        by: SelectBy,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Check {
        target: ElementRef,
        checked: bool,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Press {
        #[serde(default)]
        target: Option<ElementRef>,
        key: String,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Scroll {
        #[serde(default)]
        target: Option<ElementRef>,
        #[serde(default)]
        dx: i64,
        #[serde(default)]
        dy: i64,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Hover {
        target: ElementRef,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Navigate {
        url: String,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Back {
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Forward {
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    Reload {
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    ActivateTab {
        tab: TabId,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    CloseTab {
        tab: TabId,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    NewTab {
        #[serde(default)]
        url: Option<String>,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    HandleDialog {
        accept: bool,
        #[serde(default)]
        expected_effect: ExpectedEffect,
    },
    /// Test/utility wait (not a browser interaction).
    Wait { ms: u64 },
}

fn default_true() -> bool {
    true
}

impl BrowserAction {
    /// Machine action-type name (verification defaults, telemetry).
    pub fn action_type(&self) -> &'static str {
        match self {
            BrowserAction::Click { .. } => "click",
            BrowserAction::Type { .. } => "type",
            BrowserAction::Select { .. } => "select",
            BrowserAction::Check { .. } => "check",
            BrowserAction::Press { .. } => "press",
            BrowserAction::Scroll { .. } => "scroll",
            BrowserAction::Hover { .. } => "hover",
            BrowserAction::Navigate { .. } => "navigate",
            BrowserAction::Back { .. } => "back",
            BrowserAction::Forward { .. } => "forward",
            BrowserAction::Reload { .. } => "reload",
            BrowserAction::ActivateTab { .. } => "activate_tab",
            BrowserAction::CloseTab { .. } => "close_tab",
            BrowserAction::NewTab { .. } => "new_tab",
            BrowserAction::HandleDialog { .. } => "handle_dialog",
            BrowserAction::Wait { .. } => "wait",
        }
    }

    /// The targeted ref, if any.
    pub fn target(&self) -> Option<&ElementRef> {
        match self {
            BrowserAction::Click { target, .. }
            | BrowserAction::Type { target, .. }
            | BrowserAction::Select { target, .. }
            | BrowserAction::Check { target, .. }
            | BrowserAction::Hover { target, .. } => Some(target),
            BrowserAction::Press { target, .. } => target.as_ref(),
            BrowserAction::Scroll { target, .. } => target.as_ref(),
            _ => None,
        }
    }

    pub fn expected_effect(&self) -> ExpectedEffect {
        match self {
            BrowserAction::Click {
                expected_effect, ..
            }
            | BrowserAction::Type {
                expected_effect, ..
            }
            | BrowserAction::Select {
                expected_effect, ..
            }
            | BrowserAction::Check {
                expected_effect, ..
            }
            | BrowserAction::Press {
                expected_effect, ..
            }
            | BrowserAction::Scroll {
                expected_effect, ..
            }
            | BrowserAction::Hover {
                expected_effect, ..
            }
            | BrowserAction::Navigate {
                expected_effect, ..
            }
            | BrowserAction::Back {
                expected_effect, ..
            }
            | BrowserAction::Forward {
                expected_effect, ..
            }
            | BrowserAction::Reload {
                expected_effect, ..
            }
            | BrowserAction::ActivateTab {
                expected_effect, ..
            }
            | BrowserAction::CloseTab {
                expected_effect, ..
            }
            | BrowserAction::NewTab {
                expected_effect, ..
            }
            | BrowserAction::HandleDialog {
                expected_effect, ..
            } => expected_effect.clone(),
            BrowserAction::Wait { .. } => ExpectedEffect::None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn click() -> BrowserAction {
        BrowserAction::Click {
            target: ElementRef::new(7, "@x", 1),
            options: ClickOptions::default(),
            expected_effect: ExpectedEffect::Unspecified,
        }
    }

    #[test]
    fn action_type_names() {
        assert_eq!(click().action_type(), "click");
        assert_eq!(BrowserAction::Wait { ms: 1 }.action_type(), "wait");
        assert_eq!(click().target().unwrap().to_string(), "@x");
    }

    #[test]
    fn action_serde_tagged() {
        let v = serde_json::to_value(click()).unwrap();
        assert_eq!(v["type"], "click");
        assert_eq!(v["target"]["ref"], "@x");
    }

    #[test]
    fn old_payloads_without_effects_still_parse() {
        // M0/M1 shape: no per-variant effect fields.
        let v = serde_json::json!({"type": "press", "key": "Enter"});
        let a: BrowserAction = serde_json::from_value(v).unwrap();
        assert_eq!(a.action_type(), "press");
        assert!(matches!(a.expected_effect(), ExpectedEffect::Unspecified));
    }
}
