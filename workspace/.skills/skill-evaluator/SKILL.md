---
name: skill-evaluator
description: Evaluate and refine an agent skill against a baseline, measuring lift
  rather than polish. Use when the user says "evaluate this skill", "is this skill
  any good", "refine my SKILL.md", or when a skill exists but has never been
  A/B tested against a no-skill baseline.
---

# Skill Evaluator

Judge a skill by one question: **does the agent do better with it than without
it?** Not "is the document good." A polished skill that doesn't beat baseline is
a regression with better formatting.

## When NOT to use

- The skill has never been run on a task → use it first, then evaluate.
  (You cannot evaluate a skill that has no behaviour; a skill has no behaviour
  in isolation.)
- The user wants copy-editing, not lift measurement → say so, do the edit, and
  state plainly that no eval was run.
- The task is so open-ended no two runs are comparable → propose a narrower
  task first. "Write good prose" cannot be evaluated; "given this brief, produce
  a paragraph with no sentence that explains a gesture's meaning" can.

## The loop

**0. Locate the criteria before you read the skill.**
Write down what "better" means for this task *now*, in checkable terms. If you
read the skill first, you will adopt its implicit criteria and grade it on its
own terms — the failure mode is self-justification, not bias.

**1. Baseline.** Run the target task with NO skill loaded. N≥3 runs. Save
outputs and the exact task prompt. This is the only number that matters and it
is the step people skip.

**2. With-skill.** Same task, same runs, skill loaded. Save separately.

**3. Score blind.** Score baseline and with-skill outputs without knowing which
is which. Use `scripts/score.py` for mechanical criteria; a fresh-context LLM
call for subjective ones. Record PASS/FAIL **with quoted evidence** per
criterion — never an opinion.

**4. Delete uninformative criteria.** Any criterion that passes in BOTH
conditions is measuring the task, not the skill. Remove it and recompute.
Criteria that pass with-skill and fail at baseline are the value signal; report
those explicitly.

**5. Diagnose, don't rewrite.** For each failing criterion, classify:
   - **not selected** — description didn't match; fix the description (L1), not the body
   - **selected, ignored** — instruction too long or too abstract; compress, make imperative
   - **selected, misapplied** — instruction ambiguous; add a gotcha with the concrete case
   - **absent** — the model had no way to know; this is the only case that justifies adding content

**6. Refine one thing.** Change one of {description, one instruction, one
gotcha, one script}. Rerun the full suite. If lift doesn't improve, revert —
a change that doesn't move the score is noise that costs tokens forever.

**7. Report.** Delta per criterion (baseline → with-skill), criteria deleted as
uninformative, and the single weakest judgment plus what would overturn it.

## Structural checks (run before any eval)

Mechanical, so script them — `scripts/lint_skill.py`:

- description is `[summary]. [Use when …]`, 5–8 word summary, names trigger phrases
- body ≤ ~500 lines; core workflow ≤ ~50
- every instruction passes: *would the agent get this wrong without it?*
- scripts contain no `if` that decides what content **means**
- prompts contain no structural validation, counting, or file-existence checks
- "When NOT to use" section exists
- verification checklist items name observable output, not "looks correct"

A skill failing lint should not consume eval budget.

## Gotchas

Each of these is a real failure from a real refinement session. They are the
highest-value content in this file; grow this list from actual corrections.

- **"The doc looks complete" is not evidence.** A schema with every field
  filled and no consumer for three of them reads as finished. Check that each
  field is *consumed* by a script or instruction, not just present.
- **A dropped requirement reads as an oversight, but it's usually a decision.**
  When a refinement silently removes the load-bearing part and keeps the
  plumbing, that's the model optimizing for what it can check. Diff the
  semantics, not the structure.
- **Frozen placeholder vocabularies become canon.** If an example shows
  `moves: [a, b]`, later drafts treat a and b as the full set. Show `[]` with a
  pointer to the induction procedure instead.
- **Self-generated content regresses.** Model-written skills measured 8–11
  points BELOW no-skill baseline. Model *assistance* is fine; model *authorship*
  without a held-out test is a regression with good prose.
- **Automation removes the signal.** If the human gate is what makes the data
  good (curation, approval, a like), automating it produces more data of lower
  value. "Reduce manual steps" is a rationalization, not a goal.
- **Looping without external input converges on priors.** Two refinement passes
  with no new source, corpus, or human judgment → stop and ask. Further passes
  polish the model's own distribution.
- **Dangling references.** A doc citing `REFERENCES.md` that doesn't exist, or
  a schema pointing at `MOVES.md` that was never written. `lint_skill.py` checks
  every referenced path resolves.
- **The evaluator grades on the skill's own criteria.** If step 0 didn't happen,
  stop and redo step 0.

## Anti-rationalization

| Rationalization | Why it's wrong |
|---|---|
| "The skill is clearly an improvement; eval is overkill." | Unmeasured improvement is the default assumption of every skill author, including the ones that measured negative. Run the baseline. |
| "Baseline runs are expensive." | Cheaper than shipping a regression that silently degrades every task the skill touches. N=3 baseline is ~3 task runs. |
| "This criterion passes in both, but it's still good practice." | Then it measures the task, not the skill. Delete it. Keeping it inflates the score and hides the real delta. |
| "I'll rewrite the whole thing; it's faster than diagnosing." | A rewrite discards the only evidence you have — which instruction was being ignored. Diagnose the category first; rewrite only if the category is "absent" across the board. |
| "The description is fine, the body is what matters." | The description is the only thing in context at selection time. A perfect body behind a vague description never fires. Fix L1 first. |
| "I'll add this instruction just in case." | Every added line competes for attention with the task. Test: would removal cause a worse outcome? If no, it's noise. |
| "The eval passed, so the skill is good." | It beat baseline on *these* tasks. State the scope: which tasks, how many runs, what the weakest criterion was. |

## Verification checklist

Before returning, confirm each with quoted output:

- [ ] Baseline run exists, N≥3, saved, task prompt recorded verbatim
- [ ] With-skill run exists, same task, same N
- [ ] Scoring was blind (state how)
- [ ] Every criterion has PASS/FAIL + quoted evidence
- [ ] Uninformative criteria listed and removed, with recomputed delta
- [ ] Report states per-criterion delta, not an overall score
- [ ] `lint_skill.py` passes, or its failures are listed and justified
- [ ] Report names the weakest judgment and what would overturn it

## Failure modes of this skill

State these in the report so the reader can discount appropriately:

- **N is small.** Three runs per condition is a smoke test, not a measurement.
  Say "N=3, indicative only."
- **Blind scoring by the same model that wrote the skill** is not blind. Use a
  fresh context or a different model; if neither is available, say so.
- **Subjective criteria are noisy.** Report them as "judged by X against
  criterion Y," never as a score.