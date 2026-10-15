# Laya Routing Audit — 2026-10-12

> Historical audit and experiment proposal. It did not authorize Laya
> execution. The subsequent [task evaluation](long-task-diagnostics-2026-10-15.md)
> keeps Luna active, Laya shadow-only and Jev disabled.

## Scope and decision

This is a read-only audit of the frozen Laya decision benchmarks, the current
Laya provider and candidate contracts, and the local service health endpoint.
It proposes an instrumented, narrowly eligible Laya-first experiment to reduce
Luna decision calls. It does not enable runtime routing or select a numerical
confidence or margin threshold. Paired runtime tasks and additional decision
probes were separate work; this document preserves the original proposal
rather than treating it as the current routing policy.

The local Laya service at `http://127.0.0.1:8001/health` returned HTTP 200 on
2026-10-12, reporting the English checkpoint revision
`7b928d828b7b0e022f929d9bd2e44165aa270148` loaded on CPU, with no CPU fallback.
This was a single GET health check only. No model decision request, benchmark,
OpenAI request, Jev request, or weight change was made for this audit. Service
health establishes availability, not decision quality or speed.

## Existing implementation contracts

- `LayaProvider.health_check()` makes a GET to `/health`; `evaluate()` sends
  typed Choice/Score/Noul questions to `/v1/systemone`, maps the typed response,
  and applies provider-specific calibration. See
  [`laya.py`](../../python/src/browser_agent/decisions/laya.py#L106) and
  [`calibration.py`](../../python/src/browser_agent/decisions/calibration.py#L13).
- `TaskState` already carries the user task and constraints, plan/milestones,
  current subgoal, completion evidence, bounded counters, recovery history,
  progress signals, and status. `WorkingMemory` carries bounded constraints,
  completed milestones, current subgoal, acquired facts, pending questions,
  failed strategies, irreversible actions, and recent events. See
  [`_types.py`](../../python/src/browser_agent/_types.py#L350).
- `build_action_candidates()` constructs at most 16 typed browser actions from
  runtime capabilities, current interactable semantic elements, and
  task-approved values. It can include an explicit planner-escalation
  candidate. `select_action_candidate()` passes task, subgoal, observation,
  and bounded candidate descriptions to a `DecisionProvider`. See
  [`candidates.py`](../../python/src/browser_agent/decisions/candidates.py#L98)
  and [`candidates.py`](../../python/src/browser_agent/decisions/candidates.py#L220).
- `LunaDecisionAgent` currently obtains a Luna action, validates that it matches
  a current bounded candidate and semantic reference, then may dispatch an
  optional Laya shadow comparison. The comparison cannot replace Luna's chosen
  action. Luna's action batch path validates the proposed batch against the
  authorized candidate actions; actions still return through the normal
  runtime. See [`luna.py`](../../python/src/browser_agent/agent/luna.py#L417)
  and [`luna.py`](../../python/src/browser_agent/agent/luna.py#L518).
- `CalibrationPolicy.threshold_for()` returns `None` when no provider-specific
  minimum confidence is configured. Provider calibration is kept separate by
  provider and decision kind. Missing thresholds mean unassessed, not
  calibrated or zero-risk. See
  [`calibration.py`](../../python/src/browser_agent/decisions/calibration.py#L13)
  and [`decision-routing.md`](../architecture/decision-routing.md).
- Product defaults currently remain Luna-active, Laya shadow-only, and Jev
  disabled. This audit recommends measuring an explicit policy experiment; it
  does not change that live default.

## Benchmark evidence

The committed V1 manifest freezes 80 hand-labeled cases (49 Choice, 11 Score,
20 Noul; three canonical repeats per case) at SHA-256
`d585b64c02132d127bf7915f7e0f650a7e9a282ea201fa41c62e7de959343fbb`. V2 is a
separate pre-inference holdout of 50 new cases (32 Choice, 7 Score, 11 Noul)
at SHA-256 `6b817a207f057651a47dc363911706a9d477d8f362e87b89c0dd9d21074610cd`.
The corpus covers next action, prerequisite/order, distractor/no-op,
ambiguity/escalation, recovery, progress, semantic verification, completion,
and multi-constraint decisions. Expected labels and rationales were not sent
to Laya. Three repeats per scenario were deterministic, but they do not
increase the count of independent scenarios. These are authored decision
probes, not browser end-to-end task runs.

| Result | Frozen V1 baseline | Tuned V1 | Frozen V2 holdout |
|---|---:|---:|---:|
| Canonical accuracy | 153/240 (63.75%) | 147/240 (61.25%) | 81/150 (54.00%) |
| Choice accuracy | 120/147 (81.63%) | 108/147 (73.47%) | 63/96 (65.63%) |
| Score accuracy | 12/33 (36.36%) | 12/33 (36.36%) | 0/21 (0%) |
| Noul accuracy | 21/60 (35.00%) | 27/60 (45.00%) | 18/33 (54.55%) |
| Choice answer-confidence ECE | 0.280 | 0.223 | 0.268 |
| Choice Brier | 0.359 | 0.452 | 0.560 |
| Choice mean top-1/top-2 margin | 0.282 | 0.227 | 0.174 |
| Choice p50 / p95 latency | 7.09 / 12.29 s | 4.24 / 5.41 s | 3.82 / 6.24 s |
| Position consistency | 35% | 40% | 25% |

V1 and V2 observed latencies are not a clean same-load paired comparison. The
baseline run had saturated system CPU and lower available RAM; tuned/holdout
runs used less loaded conditions. Treat the p50/p95 values as measurements of
those runs and not a causal speedup claim. The evaluation report states the
tuned context reduced reported state tokens by 6.6% versus baseline, while
overall correctness declined. It changed multiple prompt fields together and
does not isolate why.

Category errors identify direct eligibility exclusions:

| Decision family | Tuned V1 | V2 holdout | Routing implication |
|---|---:|---:|---|
| Next action | 80.0% (36/45) | 50.0% (9/18) | Candidate choice may be probed, but no general fast path is validated. |
| Prerequisite/order | 50.0% (15/30) | 100% (18/18) | Small and conflicting samples; keep sequence enforcement in code. |
| Distractor/no-op | 75.0% (18/24) | 80.0% (12/15) | Good probe family, still too small to stand alone as execution evidence. |
| Ambiguity/escalation | 50.0% (12/24) | 16.7% (3/18) | Exclude. Missing or conflicting evidence must escalate deterministically. |
| Recovery classification | 50.0% (12/24) | 0% (0/18) | Exclude; Rust mechanics and Luna recovery policy remain in control. |
| Progress judgment | 12.5% (3/24) | 40.0% (6/15) | Exclude; use observed deltas and deterministic progress state. |
| Semantic verification | 37.5% (9/24) | 66.7% (12/18) | Exclude; Laya must not attest task/action success. |
| Task completion | 85.7% (18/21) | 60.0% (9/15) | Exclude; use required milestones and evidence gate. |
| Multi-constraint | 100% (24/24) | 80.0% (12/15) | Keep constraints checked in code; not sufficient as a stand-alone policy. |

On tuned V1, answer-confidence `>= 0.50` plus margin `>= 0.10` accepted
69/147 Choice calls at 78.26% accuracy, with 15 wrong actions. On V2 the same
descriptive rule accepted 36/96 at 58.33%, again with 15 wrong actions. A
`>= 0.70` confidence slice had 6/6 correct in each V1 variant but only 3/3
wrong on V2. The apparent V1 high-confidence result therefore does not
transfer. Position permutations were correct in 20/60 V1 baseline probes and
15/36 V2 probes; semantic-answer consistency was 35% and 25% respectively.
Confidence, top margin, and position stability are useful recorded covariates,
not trustworthy acceptance criteria on these data.

Independent gold-free review adds qualitative risk evidence: tuned V1 included
2 `UNSAFE` and 4 `SHOULD_HAVE_ESCALATED` judgments; V2 included 5 `UNSAFE` and
2 `SHOULD_HAVE_ESCALATED`. Reviewers flagged violating explicit constraints,
risky edits, ambiguous bookings/scheduling, unauthorized transfers, retrying
unknown or denied operations, and possible duplicate submissions. The
benchmark's calibration verdict is `NEEDS_MORE_CALIBRATION`; no action family
or numerical threshold was accepted.

## Smallest measurable eligibility gate

Treat the following as an experiment predicate, not an already calibrated
production policy. It avoids a fabricated confidence number while making the
candidate action and routing outcomes measurable.

1. **Purpose:** only a bounded immediate `Choice` among current
   `ActionCandidate`s. Laya is not eligible to plan, score a proposal, decide
   ambiguity, classify recovery, judge progress, verify semantics, or mark a
   task/subgoal complete.
2. **Known task state:** the goal, constraints, current subgoal, permitted
   values, and required evidence are already explicit in `TaskState` / bounded
   `WorkingMemory`. If a task needs decomposition, missing information,
   cross-tab synthesis, or a new plan, use Luna. A trivially complete
   one-action microtask may skip Luna planning only if code can construct its
   safe candidate set and existing deterministic completion checks still
   establish completion.
3. **Safe candidate set:** every offered executable choice is code-constructed,
   semantically bound to the current observation generation, and classified
   as low risk. High-risk or irreversible actions (submit, send, purchase,
   delete, publish, security/account change, financial action) are ineligible;
   existing confirmation policy remains authoritative. If any candidate or
   state is ambiguous, stale, contradictory, or lacks a required prerequisite,
   route to Luna or the user before action.
4. **No sensitive outbound context:** the current provider privacy boundary
   decides whether task/state/candidate text may be sent to local Laya. PII,
   credentials, secrets, or user-private values not explicitly cleared by that
   boundary make the decision ineligible. Privacy-first/offline policy must
   continue to block or constrain provider routing as configured.
5. **Fail closed:** require a typed, well-formed Choice result that names one
   supplied candidate. An explicit escalation choice, provider error, malformed
   response, stale generation, policy rejection, or unconfigured acceptance
   threshold falls back to Luna/user handling; it never authorizes an action.
6. **Confidence attestation:** record the raw chosen-answer probability,
   probability vector, top margin, candidate order, provider/checkpoint ID,
   category, task state features, and eventual action/verification outcome.
   Use confidence and margin in the paired analysis. Do not compare Laya scores
   with Luna or another provider. Do not populate `minimum_confidence` until
   independent task-level evidence supports a family-specific gate; the current
   benchmark offers no transferable cutoff.
7. **Canonical action path:** after eligibility and candidate binding, the
   selected typed action still passes existing Python policy, Rust target and
   risk checks, execution, and deterministic Rust verification. Verification
   uncertainty or failure triggers the existing bounded recovery/plan path;
   Laya cannot claim success or bypass confirmation.

This gate is intentionally small: runtime facts already supply candidate
validity, generation, task/subgoal/constraints, and policy risk; only a code
eligibility decision and logging need to distinguish the experiment route.
It avoids opening all decision families at once.

## Where Luna-call reduction can work

- **One-shot microtasks:** if the task has a single already-understood action
  (for example, select the requested visible filter) and code can form a
  low-risk bounded candidate set, a Laya `Choice` can replace the Luna action
  selection. A one-action task can bypass planning only when planning adds no
  unresolved goal interpretation; completion must still come from deterministic
  visible evidence. The Laya benchmark did not test end-to-end savings or
  success here, so this is a hypothesis for paired tasks.
- **Known bounded stages:** after Luna has already established a plan/subgoal,
  a local Choice can replace a Luna call for each eligible immediate action.
  Keep prompt state compact: `Task`, `Subgoal`, `Constraints`, concise current
  semantic evidence, latest verified action/outcome/delta, and the small set of
  typed `Candidates`. This resembles the benchmark's tuned structure, while
  preserving complete candidate semantics. Its V1 raw accuracy regressed, so
  compactness is an input/token experiment, not assumed quality improvement.
- **Batching or caching:** current `DecisionProvider` choice contract returns
  one selection; it has no validated multi-action plan contract. Prefer
  re-evaluating each fresh observation. Any future bounded stage batch/cache
  should be limited to same-subgoal, explicitly authorized actions and invalidated
  on any generation/delta change that affects a target, failed/uncertain action,
  changed constraint, recovery, risk change, or plan/subgoal change. Every
  action remains individually target-checked and Rust-verified. Existing Luna
  action batches are candidate-validated; they are not evidence that Laya
  batches are safe. Do not let model-maintained completion booleans replace
  `TaskState`'s completed milestones, evidence, and deterministic completion
  gate.

A successful route should reduce measured Luna action-selection calls while
preserving end-to-end task completion. It should not optimize “calls saved” by
silently dropping planning, verification, recovery, or completion evidence.

## Measurement for the paired experiment

For each paired task, use the same initial page, goal, constraints, action
limits, browser build, and verification policy. Randomize/counterbalance route
order where replay is safe. Compare Luna-only against the proposed eligible
Laya-first route, and retain an ineligible shadow sample to expose gate coverage
and exclusion reasons. Freeze task cases before running and reserve new cases
for holdout after any interface or gate changes.

Report at task level and by eligibility/family: task success, partial
completion, policy violations/unsafe actions, steps, Luna calls (planning,
action, replan/deep), Laya calls, provider-reported tokens, provider latency,
wall-clock p50/p95, action failure, verification failure/uncertainty, recovery
success, stagnation, abstentions/escalations, and eligible coverage. Also
report Choice calibration (answer-confidence and candidate probability
quality, Brier/ECE, margin), candidate-order permutation stability, and
performance on each frozen category. Keep independent task counts separate
from repeated calls. State a success/non-inferiority criterion before testing;
its numerical tolerance must come from the product owner's risk decision and
available task sample size, not from this audit. Require a fresh held-out set
before promotion.

## Relevant code and evidence

- Benchmark protocol and cases:
  [`benchmarks/laya/README.md`](../../benchmarks/laya/README.md), V1
  [`benchmark_v1.jsonl`](../../benchmarks/laya/benchmark_v1.jsonl) and manifest,
  V2 [`benchmark_v2_holdout.jsonl`](../../benchmarks/laya/benchmark_v2_holdout.jsonl)
  and manifest.
- Calibration and measured risks:
  [`laya-calibration-report.md`](../../benchmarks/laya/reports/laya-calibration-report.md),
  [`baseline-analysis.md`](../../benchmarks/laya/reports/baseline-analysis.md),
  plus immutable raw/scored/analysis files in
  `benchmarks/laya/results/{baseline,tuned,holdout}/`.
- Typed provider:
  [`decisions/laya.py`](../../python/src/browser_agent/decisions/laya.py#L106),
  [`decisions/calibration.py`](../../python/src/browser_agent/decisions/calibration.py#L13),
  and [`decisions/base.py`](../../python/src/browser_agent/decisions/base.py).
- Candidate/runtime paths:
  [`decisions/candidates.py`](../../python/src/browser_agent/decisions/candidates.py#L98),
  [`agent/luna.py`](../../python/src/browser_agent/agent/luna.py#L417), and
  [`agent/luna.py`](../../python/src/browser_agent/agent/luna.py#L518).
- Policy and active behavior:
  [`docs/architecture/decision-routing.md`](../architecture/decision-routing.md),
  ADR-004 (provider contract history), and the current runtime authority in
  [`ARCHITECTURE_PLAN.md`](../../ARCHITECTURE_PLAN.md).

No runtime code, fixture, threshold, or benchmark result was changed or run as
part of this audit.
