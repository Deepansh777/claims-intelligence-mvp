# AI Query Policy — Maintainer Notes

Not loaded into the AI's context. Companion to `ai-query-policy.md`.

## Status

The policy is based on the data dictionary for the August 2026 extract. It has not been validated against a live database or the transformation code. On each refresh, update the reporting period and row counts in `data-dictionary.md`; the policy reads coverage from there.

## Application integration

The application must explicitly load `ai-query-policy.md` and `data-dictionary.md` into the SQL agent's context before query planning; storing them in the repo does not enforce them. Keep both versioned with the data transformations. Enforce database permissions, read-only access, parameterization, timeouts, result limits, and SQL restrictions in the application/database — the policy text alone cannot.

The `ref` tables used by §9 must be loaded (`python -m scripts.load_reference` from `backend/`) before the SQL agent runs; the ICD-10-CM file is the 2027 code set, not the 2024–2026 sets in the claims.

## Open questions for the data owner

Once resolved, update the policy and remove the corresponding "state the limitation" fallbacks.

- Transformation rules for admissions, ER visits, referrals, allowed spend, and claim status/reversal handling.
- Whether `exclude_from_rate_count` should also apply to referral spend.
- Member-month conventions: partial months, overlapping networks/spans, attribution timing.
- Approved network/hierarchy mapping for `mart.er_encounters` and `mart.er_revisits_30d`.
- Whether location-level PCP summary numerators and exposures are additive, and how they reconcile to roster and event totals.
- HEDIS measure identity, tie/null-date status resolution, and reporting-period semantics.
- Clinical cohort definitions, age reference dates, readmission denominator and follow-up rules, risk-score weighting.
- Refresh timestamps and complete-through dates per table; authoritative source for validating each metric.
