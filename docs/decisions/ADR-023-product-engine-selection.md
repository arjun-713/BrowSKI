# ADR-023: Product selection of managed General/Fast engines

Date: 2026-10-18 · Status: accepted for implementation; IN MIGRATION

## Context

Phases 1/3/4 have verified managed Browser Use navigation and CPU Laya decisions.
The extension still submits to the attached Luna graph. Its chrome.debugger
relay is not a browser-level CDP WebSocket supported by Browser Use. Assuming
it is would introduce overlapping control and an unverified transport rewrite.
The user permits only Laya locally and small explicitly opted-in OpenAI debugging.

## Decision

Expose task-level General/Fast selection in the existing product configuration
and settings. Fast/Laya is the target default, text generation disabled and paid
inference denied until explicitly enabled. Retain an explicitly selected Legacy
engine for rollback, with the same paid-API gate. Never infer hosted permission
from the mere presence of credentials. Jev remains optional with offline tests.

First product tasks use an isolated task-owned managed Chrome profile; source
references do not transfer authentication or control of personal tabs. Preserve
Native Messaging authentication, sequence validation, task events/results,
stop/pause boundaries and existing approval behavior. General's initial tool
allowlist remains navigation/reading only, so consequential actions cannot bypass
approval by selecting that engine. New form/action capabilities need approval
and independent verification coverage before enabling them.

Use one small product dispatch function and cancellation/pause controls around
the proven engines. Do not wrap the new loop in LangGraph or introduce a second
browser ownership service. Engine/provider selection is pinned for a task;
settings changes apply to the next task. No mid-task engine handoff.

## Contract and compatibility

Extend the product settings and task submission/result envelopes, coordinated
with extension version 0.2.0 and the matching local host. Retain protocol-v1
framing and replay rules; Rust browser-side schemas/bindings remain unchanged.
The new result preserves completed/partial/blocked/failed/cancelled distinctions;
never map an unverified result to verified_success. Old task submissions remain
valid for the explicitly selected legacy path. Unknown fields and invalid
engine/provider/endpoint values fail validation before task execution.

## Gate

Test the actual packaged extension → Native Messaging → product dispatch →
official Browser Use engine → Chrome → independent outcome verifier → UI path.
Offline provider responses establish wiring; a bounded authorized live-model
acceptance establishes one real task. Also verify cancellation, paid opt-in
refusal, local defaults, configuration persistence and no concurrent controller.
The broader reliability, text/form actions and legacy cleanup gates remain open.
