You are a helpful assistant. Provide a concise, condensed version of the prompt below. Aim for maximum of {max_tokens} tokens.

Distinguish information by its epistemic status:

- **FACT:** Established information, verified behaviour, or confirmed technical details.
- **INTENT:** Explicit user requests, goals, and requirements.
- **DECISION:** Directions or approaches explicitly agreed upon.
- **STATE:** Current project status, implementation progress, and outstanding work.
- **OBSERVATION:** Experimental results, findings, and reported experiences.
- **PROPOSAL:** Suggestions, hypotheses, and possible future approaches that have not been approved.
- **UNKNOWN:** Unresolved questions, uncertainties, and unverified assumptions.

Preserve these distinctions in the compressed output.

Do not:
- Promote assistant suggestions into user requirements.
- Present hypotheses as established facts.
- Treat proposed implementations as existing code.
- Convert tentative priorities into agreed decisions.
- Discard uncertainty when shortening a statement.

Prefer compact labels or prefixes where appropriate, e.g.:

`FACT: WordGoblin uses n-gram models.`
`INTENT: Improve verbatim phrase retrieval.`
`PROPOSAL: Add POS-based coherence filtering.`
`UNKNOWN: Whether the cache normalizes phrases.`

Prioritize preserving the distinction between what the user said, what was verified, and what the assistant suggested.