//! Validated browser actions and their outcomes.
//!
//! Boundary: defines the [`BrowserAction`] vocabulary, execution failures,
//! [`ActionOutcome`], and action policy. Execution against a live browser
//! lives in `browser-core` (which owns the transport); verification verdicts
//! come from `verification`. Contains no agent reasoning and no LLM calls.
//!
//! Core rule: CDP command success != task success. [`ActionOutcome`] always
//! carries both the execution evidence and the verification verdict.

pub mod action;
pub mod failure;
pub mod outcome;
pub mod policy;

pub use action::{BrowserAction, ClickOptions, MouseButton, SelectBy};
pub use failure::{ExecutionFailure, ExecutionFailureKind};
pub use outcome::{ActionOutcome, ExecutionEvidence, ExecutionResult, MechanicalRepair};
pub use policy::{
    ActOptions, DEFAULT_ACTION_COMMAND_TIMEOUT, DEFAULT_SETTLE_TIMEOUT, DEFAULT_VERIFY_TIMEOUT,
    MAX_ACTION_ATTEMPTS,
};
