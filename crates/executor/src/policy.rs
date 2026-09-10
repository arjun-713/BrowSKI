//! Action policy: bounded mechanical retries, explicit options.
//!
//! M3 retries ONLY deterministic low-level repairs on the SAME intended
//! action: re-resolve, scroll into view, wait out a transient overlay,
//! retry the hit test, reacquire after mutation. Then it stops with
//! evidence. New plans and strategies belong to future agent recovery:
//!
//! ```text
//! M3: "same intended action, repair mechanics"
//! M4+: "choose another action or strategy"
//! ```

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Hard ceiling on perform attempts per `act()` call (initial + repairs).
pub const MAX_ACTION_ATTEMPTS: u32 = 3;

/// Pre-state settle budget after performing, before post-state capture.
pub const DEFAULT_SETTLE_TIMEOUT: Duration = Duration::from_secs(5);
/// Verification-window budget for declared effects.
pub const DEFAULT_VERIFY_TIMEOUT: Duration = Duration::from_secs(5);
/// Per-command budget inside actions.
pub const DEFAULT_ACTION_COMMAND_TIMEOUT: Duration = Duration::from_secs(15);

/// Knobs for one `act()` call.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActOptions {
    #[serde(default = "default_settle")]
    pub settle_timeout: Duration,
    #[serde(default = "default_verify")]
    pub verify_timeout: Duration,
    /// Allow the DOM-method fallback (e.g. `el.click()`) when trusted input
    /// cannot proceed. Default false: tests prove the trusted path first.
    #[serde(default)]
    pub allow_dom_fallback: bool,
    #[serde(default = "default_attempts")]
    pub max_attempts: u32,
}

fn default_settle() -> Duration {
    DEFAULT_SETTLE_TIMEOUT
}

fn default_verify() -> Duration {
    DEFAULT_VERIFY_TIMEOUT
}

fn default_attempts() -> u32 {
    MAX_ACTION_ATTEMPTS
}

impl Default for ActOptions {
    fn default() -> Self {
        Self {
            settle_timeout: DEFAULT_SETTLE_TIMEOUT,
            verify_timeout: DEFAULT_VERIFY_TIMEOUT,
            allow_dom_fallback: false,
            max_attempts: MAX_ACTION_ATTEMPTS,
        }
    }
}

impl ActOptions {
    /// Attempts are always bounded, no matter what the caller asks for.
    pub fn bounded_attempts(&self) -> u32 {
        self.max_attempts.clamp(1, MAX_ACTION_ATTEMPTS)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn attempts_are_clamped() {
        let opts = ActOptions { max_attempts: 99, ..Default::default() };
        assert_eq!(opts.bounded_attempts(), MAX_ACTION_ATTEMPTS);
        let opts = ActOptions { max_attempts: 0, ..Default::default() };
        assert_eq!(opts.bounded_attempts(), 1);
    }
}
