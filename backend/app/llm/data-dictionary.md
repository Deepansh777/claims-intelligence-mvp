# Claims Intelligence — Data Dictionary

Reference for anyone (human or LLM agent) writing SQL against the Postgres database. Loaded by `backend/scripts/load_data.py` from `data/`. Row counts and value lists below are from the 2026-08 extract.

---

## 1. Rules for writing SQL

1. **Two schemas.** `raw` = source extracts (claims, eligibility, providers) at line/span level. `mart` = derived tables built from raw: some are per-event (admissions, ER encounters, referral episodes), some are pre-aggregated summaries. Prefer `mart` when it already answers the question; go to `raw` only for detail mart does not have.
2. **All identifiers are lowercase snake_case.** Never quote them. `member_sk`, not `"Member_SK"`.
3. **IDs and codes are `text`**, even when they look numeric (`member_sk`, NPI, TIN, zip, diagnosis/procedure/revenue codes, DRG). Compare with string literals: `member_sk = '536507'`.
4. **Booleans are real booleans** (`is_icu`, `dq_*`, …): `WHERE is_icu`, not `= 'True'`.
5. **Dates are `date`.** `month_year` / `*_month_year` columns are `text` `'YYYY-MM'` (sort correctly as text).
6. **Never average a rate.** To roll up PMPM or per-1000 across months, PCPs or groups, sum the numerator and `member_months`, then divide (see §4).
7. **Never sum `cumulative_*` columns.** They are already running totals.
8. **Reporting period is 2024-07-01 → 2026-06-30** (24 months). All mart tables cover exactly this window.
9. **Members can appear under both networks** (`level1_hierarchy` = `NEXUS` and `PCN`). Counting distinct members across both double-counts unless you `COUNT(DISTINCT member_sk)`.
10. Data is synthetic, but treat names, addresses and DOB as PHI: don't select them unless the question requires it.

---

## 2. Business concepts

| Concept | Meaning |
|---|---|
| `level1_hierarchy` | Network/program. `NEXUS` (the clinically integrated network this product focuses on; ~10.6K members) or `PCN` (~36K members). |
| `level2_hierarchy` | Plan administrator / TPA, e.g. `ALLIED BENEFIT SYSTEMS`, `LUMINARE HEALTH (TRUSTMARK)`. |
| `level3_hierarchy` | Employer group, e.g. `CITY OF DERBY`, `ATLAS AEROSPACE LLC`. |
| PCP | Primary care provider a member is attributed to. Identified by NPI (person) + TIN (group/billing entity). |
| Member months (MM) | One member enrolled for one month. Denominator for all rates. |
| Allowed amount | Contracted cost of a service. All cost metrics use allowed (in raw claims `paid_amt` always equals `allowed_amt`). |
| UB vs HCFA | UB = facility/institutional claim (UB-04), HCFA = professional claim (CMS-1500). |
| Tier 1 / Tier 2 | Specialist provider tiers in referrals; Tier 1 is the preferred tier. |

---

## 3. Join keys

| Entity | Key | Where it appears (same values) |
|---|---|---|
| Member | `member_sk` (text, e.g. `'536507'`) | `raw.claims`, `raw.eligibility`, and every mart member/event table. **`mart.access_hedis_measure.membernumber`** holds the same value. |
| Provider (row-level) | `provider_sk` (text, e.g. `'12567-10314-24525-481172106-145'`) | `raw.providers.provider_sk` = `raw.claims.servicing_provider_sk` = `raw.eligibility.member_pcp_sk` = mart `member_pcp_sk`, `provider_sk`, `servicing_provider_sk`, `index_/readmit_provider_sk`. The last dash segment is a specialty code (`-24` = PCP). |
| Provider (person) | NPI (10-digit text) | `prov_npi`, `member_pcp_npi`, `pcp_npi`, `anchor_pcp_npi`, `servicing_prov_npi`, `memberpcpnpi`, `readmit_pcp_npi`. One NPI can have many `provider_sk` rows. |
| Provider group | TIN (9-digit text) | `prov_tin`, `provider_tin`, `member_pcp_tin`, `pcp_group_tin`, `anchor_pcp_tin`, `servicing_prov_tin`. |
| Claim | `claim_number` (+ `claimline_num`) | `raw.claims`; mart `ub_claim_number`, `hcfa_claim_number` and `claim_numbers` (`CLM…`, same format; `;`-separated lists need `string_to_array(x, ';')`) join to `raw.claims.claim_number`. Verified: every admission and ER claim number exists in raw. |

Common joins:

```sql
-- claim lines → servicing provider
FROM raw.claims c JOIN raw.providers p ON p.provider_sk = c.servicing_provider_sk
-- NEXUS PCP roster → monthly per-PCP admissions
FROM mart.nexus_pcp_roster r JOIN mart.admission_summary_by_pcp a ON a.member_pcp_npi = r.pcp_npi
-- HEDIS gaps → member demographics
FROM mart.access_hedis_measure h JOIN mart.member_info m ON m.member_sk = h.membernumber
```

---

## 4. Metric definitions (verified against the data)

| Metric | Formula | Notes |
|---|---|---|
| PMPM | `total_allowed_amt / member_months` | Per member per month cost. |
| Util per 1,000 / `*_per_1000` | `event_count * 1000 / member_months` | **Per 1,000 member months — not annualized.** Multiply by 12 for "per 1,000 members per year". |
| Cumulative PMPM | `cumulative_total_allowed_amt / cumulative_member_months` | Running from 2024-07 within the same `level1_hierarchy`. |
| Risk-adjusted PMPM | `pmpm / avg_risk_score` | In `mart.nexus_pcp_roster`. |
| Cost per admit | `admission_allowed_amt / admission_count` | |
| ALOS | average `admission_los` (days, discharge − admit) | |
| 30-day readmission | Inpatient admission within 30 days of a prior discharge for the same member | Pairs in `mart.readmissions_30d`; flag `is_readmission_30d` in `mart.admission_members`. |
| 30-day ER revisit | ER visit within 30 days of a prior ER visit | Pairs in `mart.er_revisits_30d`; flag `is_revisit_30d`. |

Rolling up correctly:

```sql
-- NEXUS total-cost PMPM for calendar 2025
SELECT sum(total_allowed_amt) / sum(member_months) AS pmpm
FROM mart.total_cost_of_care_summary_l1
WHERE level1_hierarchy = 'NEXUS' AND month_year BETWEEN '2025-01' AND '2025-12';
```

`total_cost_of_care` allowed is larger than admissions + ER + referrals combined (it includes all other spend), so don't expect those to add up.

---

## 5. Known data quirks

- **raw.claims `rev_code` and `bill_code` are float-formatted** (`'450.0'` = revenue code `0450`, `'111.0'` = type of bill `111`). Normalize with `lpad(split_part(rev_code, '.', 1), 4, '0')` and `lpad(split_part(bill_code, '.', 1), 3, '0')`. `referring_provider_sk` is also float-formatted (`'1548233844.0'`).
- **Denied lines carry allowed amounts.** `claim_status = 'D'` (7,270 lines, ~$4.2M allowed). Filter `claim_status = 'P'` for paid spend.
- Negative `allowed_amt` / `allowed_units` exist (979 lines) — adjustments/reversals.
- `raw.claims.servicing_providernpi` disagrees with `raw.providers.prov_npi` on ~32K lines; prefer the NPI from `raw.providers` via `servicing_provider_sk`. TIN always agrees.
- Diagnosis columns contain some junk values (`'11'`, `'A1'`, `'000.00'`) and occasional ICD-10-PCS procedure codes in later positions.
- Outlier dates: `raw.claims.admit_date` as early as 1954, `discharge_date` as late as 2206.
- `9999999999` in `mart.access_hedis_measure.memberpcpnpi` is a placeholder for "no attributed PCP".
- `raw.eligibility.pcp_attribution`: rows with `'Y'` never have `member_pcp_sk`; rows with `'N'` always do. Use `member_pcp_sk IS NOT NULL` to find members with an assigned PCP.
- `*_by_pcp` tables can have 2 rows for the same PCP NPI + TIN + month (PCP practicing at two locations). Always `GROUP BY` and `SUM`.
- `mart.access_hedis_measure` has one row per member × measure × qualifying service event, so a member-measure can repeat. For current status per member-measure take the row with the latest `measurelastsvcdate`.
- Columns marked "always empty" below are 100% NULL in this extract; kept for schema stability.

---

## 6. Schema `raw`

### raw.claims — 1,387,054 rows

**Grain:** one row per claim line. **Key:** (`claim_number`, `claimline_num`). ~153K claims, ~17.6K members. Service dates 2024-01-10 → 2026-06-30.

| Column | Type | Description |
|---|---|---|
| claim_number | text | Claim ID (`CLM…`). |
| claimline_num | text | Line number within claim (`'1'`, `'2'`, …). |
| member_sk | text | Member → `raw.eligibility.member_sk`. |
| servicing_provider_sk | text | Servicing provider → `raw.providers.provider_sk` (always matches). |
| servicing_providernpi | text | Servicing NPI as submitted (see quirks). |
| ordering_provider_sk | text | Always empty. |
| referring_provider_sk | text | Referring provider NPI, float-formatted; 52% null. |
| provider_pcp_sk | text | Always empty. |
| provider_tin | text | Billing TIN. |
| claimline_servdatefrom / claimline_servdateto | date | Line service date range. |
| claim_servdatefrom / claim_servdateto | date | Claim-level service date range. Use `claim_servdatefrom` for "month of service". |
| claimline_status / claim_status | text | `P` paid, `D` denied. |
| proc_code | text | CPT/HCPCS (e.g. `99213`). Null on most IP lines. |
| proc_type | text | Always empty. |
| proc_mod1 / proc_mod2 | text | Procedure modifiers (`25`, `26`, `TC`, `GP`, `LT`, `RT`, …). |
| rev_code | text | Revenue code, float-formatted. Present on IP/OP only. |
| pos | text | Place of service (`11` office, `22` outpatient hospital, `23` ER, `21` inpatient, `81` lab, …). |
| tos | text | Always empty. |
| sub_drgversion | text | Always empty. |
| sub_drgcode | text | MS-DRG (IP only, 99% null). |
| diagnosis_cd01 … diagnosis_cd10 | text | ICD-10-CM codes with dot (`I10`, `E11.9`); `cd01` is principal. |
| surgproccode_1 … surgproccode_5 | text | ICD-10-PCS procedure codes (IP). |
| admit_date / discharge_date | date | Facility admit/discharge (IP/OP). |
| admit_time / discharge_time | text | `HH:MM` or `HH:MM:SS`. |
| admit_source | text | UB-04 point of origin code (`1`,`2`,`4`,`5`,`6`,`8`,`9`,`D`). |
| icd_ind | text | Always empty. |
| admit_dx_cd | text | Admitting diagnosis (ICD-10). |
| admit_type | numeric | UB-04 admission type: 1 emergency, 2 urgent, 3 elective, 4 newborn, 5 trauma, 9 unknown. |
| discharge_source | text | Always empty. |
| bed_days | numeric | Inpatient bed days. |
| auth_number | text | Prior authorization number (93% null). |
| bill_code | text | Type of bill, float-formatted (`111` inpatient, `131` outpatient, …). |
| claim_type | text | `IP` inpatient facility (34.7K lines), `OP` outpatient facility (380K), `PR` professional (972K). |
| allowed_units | numeric | Units allowed. Can be negative. |
| facility_type | text | Always empty. |
| billed_amt | numeric | Billed (charged) amount. |
| allowed_amt | numeric | Allowed amount. **Use for cost.** |
| paid_amt | numeric | Paid amount (equals `allowed_amt` on every row). |
| coinsurance_amount / copay_amount | numeric | Member cost share (94% null). |
| claim_reversal_id | text | Always empty. |
| additional_field_01 … 20 | text | Always empty. |
| custom_field_01 | text | Provider participation: `PAR` / `NON`. |
| custom_field_02 | text | Extract window, always `20240701-20260630`. |
| custom_field_03 | text | Employer group name (mixed case version of `level3_hierarchy`). |
| custom_field_04 | text | Plan administrator / TPA (mixed case version of `level2_hierarchy`). |
| custom_field_05 | text | Network/contract code (`PCN`, `NEXUS-PCP`, `NEXUS-SPEC`, `NEXUS-FAC`, …). |
| custom_field_06 | numeric | 10-digit NPI-like provider number (meaning unconfirmed; `9999999999` = unknown). |
| custom_field_07 … 10 | text | Always empty. |

### raw.eligibility — 53,513 rows

**Grain:** one row per member × network (`level1_hierarchy`) × coverage span. ~43.3K distinct members; a member has up to 5 rows and can have simultaneous `NEXUS` and `PCN` rows.

| Column | Type | Description |
|---|---|---|
| member_sk | text | Member key. |
| member_nbr | text | Member number (`M1000…`). |
| member_id | text | Always empty. |
| member_first_name / member_last_name | text | PHI. Middle name always empty. |
| member_address_1 / member_address_2 / member_city / member_zip / member_state | text | PHI. Mostly KS, also MO, CO, OK, NE, …. `member_zip_4`, `member_county` always empty. |
| member_age | text | Always empty — compute from `member_dob`. |
| member_dob | date | Date of birth (PHI). |
| member_gender | text | `F`, `M`, `U`. |
| member_race / member_ethnicity / member_relationship | text | Always empty. |
| benefit_plan / plan_name / product_entity | text | Always empty. |
| plan_id | text | Plan code (176 values). |
| product_lob_code / product_lob_name | text | Always `COMM` / `Commercial`. |
| member_startdate / member_termdate | date | Coverage span. Null `member_termdate` (79%) = still active. |
| member_pcp_sk | text | Assigned PCP → `raw.providers.provider_sk`. 82% null. |
| member_pcpstartdate / member_pcpenddate | date | PCP assignment span. |
| level1_hierarchy / level2_hierarchy / level3_hierarchy | text | Network / TPA / employer (see §2). |
| pcp_attribution | text | `Y`/`N` (see quirks — inverted relative to `member_pcp_sk`). |
| additional_field_01 … 16 | text | Always empty. |
| custom_field_01 | text | Extract window, always `20240701-20260630`. |
| custom_field_02 … 10 | text | Always empty. |

### raw.providers — 258,515 rows

**Grain:** one row per `provider_sk` (provider × group/location). ~22.6K distinct NPIs, ~3.1K TINs.

| Column | Type | Description |
|---|---|---|
| provider_sk | text | Provider key. |
| prov_id | text | Provider ID (`PROV…`), unique per row. |
| prov_npi | text | Individual NPI. |
| prov_fname / prov_lname / prov_mi | text | Provider name. |
| prov_tin | text | Group TIN. |
| prov_groupid | text | Group ID (`GRP…`), unique per row. |
| prov_officenum | text | Office number (`OFF…`). |
| prov_groupnpi | text | Group NPI. |
| prov_groupname | text | Group/practice name. |
| prov_groupaddress_1 / _2, prov_groupcity, prov_groupzip, prov_groupzip_4, prov_groupstate | text | Group address. `prov_groupcounty`, `prov_groupregion` always empty. |
| prov_statuscode | text | Always `P`. |
| prov_networkind | text | `1` or `3` (network indicator code). |
| prov_networkname | text | Despite the name, holds a **specialty** (`Dermatology`, `Physical Therapist`, `Other`, …). |
| prov_affcode / prov_affname / prov_deanum | text | Always empty. |
| additional_field_01 | text | Specialty (most complete specialty column; `Unknown` when missing). |
| additional_field_02 … 20 | text | Always empty. |
| custom_field_01 | text | Always `PAR`. |
| custom_field_02 | text | `PCP` when the provider is a PCP, else null. |
| custom_field_03 | text | Extract window, always `20240701-20260630`. |
| custom_field_04 | bigint | Specialty code (matches last segment of `provider_sk`). |
| custom_field_05 | text | Specialty (same as `additional_field_01`). |
| custom_field_06 | text | Network segment: `PCN`, `NEXUS-SPEC`, `NEXUS-PCP`, `NEXUS-FAC`, `NEX-FH-PCP`, `NEX-FH-HOS`, `NEXUS-COV`, `EXTERNAL PROVIDERS`. |
| custom_field_07 … 10 | text | Always empty. |

---

## 7. Schema `mart`

### Summaries by network and month (`*_summary_l1`) — 48 rows each

**Grain:** one row per `level1_hierarchy` (`NEXUS`, `PCN`) × month (2024-07 … 2026-06). Same pattern across four tables; `cumulative_*` are running totals from 2024-07 within the network.

| Table | Month column | Event columns |
|---|---|---|
| mart.total_cost_of_care_summary_l1 | `month_year` | — (all spend) |
| mart.admission_summary_l1 | `admission_month_year` | `admission_count`, `avg_admission_los` |
| mart.er_summary_l1 | `er_month_year` | `er_encounter_count` |
| mart.referrals_summary_l1 | `referral_month_year` | `referral_count`, `unique_member_count`, `total_billed_amt`, `pct_pcp_directed`, `pct_in_group`, `pct_procedure_performed` (percent 0–100) |

Shared columns: `level1_hierarchy` text, `member_months` bigint, `total_allowed_amt` numeric, `pmpm` numeric, `util_per_1000` / `referrals_per_1000` numeric (not in TCOC), `cumulative_total_allowed_amt`, `cumulative_member_months`, `cumulative_<event>_count`, `cumulative_pmpm`, `cumulative_util_per_1000` / `cumulative_referrals_per_1000`.

### Summaries by PCP and month (`*_summary_by_pcp`) — 11,448 rows each

**Grain:** PCP (TIN + NPI) × `month_year`, NEXUS PCPs only; may have 2 rows per PCP-month (two locations) — always aggregate. `member_months` here sums to the roster total per PCP.

| Table | Columns beyond the shared ones |
|---|---|
| mart.admission_summary_by_pcp | `admission_count`, `avg_admission_los` (null when no admits), `admission_pmpm`, `admissions_per_1000` |
| mart.er_summary_by_pcp | `er_encounter_count`, `er_pmpm`, `er_per_1000` |
| mart.referrals_summary_by_pcp | `referral_count`, `referral_pmpm`, `referrals_per_1000` |

Shared: `member_pcp_tin`, `member_pcp_groupname`, `member_pcp_npi`, `member_pcp_fname`, `member_pcp_lname` (text), `month_year` text, `member_months` bigint, `total_allowed_amt` numeric. Rate columns are null when `member_months = 0`.

### mart.referrals_summary_by_pcp_specialty — 6,913 rows

**Grain:** NEXUS PCP (TIN + NPI) × `servicing_specialty`, whole period (may repeat — aggregate).

| Column | Type | Description |
|---|---|---|
| member_pcp_tin / member_pcp_groupname / member_pcp_npi / member_pcp_fullname | text | Referring PCP. |
| servicing_specialty | text | Specialist specialty (169 values). |
| tier1_referrals / tier2_referrals | bigint | Referral counts by specialist tier. |
| pct_tier1_referrals / pct_tier2_referrals | numeric | Percent 0–100. |
| referral_per_1000 / referral_pmpm | numeric | This PCP's rate for the specialty. |
| nexus_referral_per_1000 / nexus_referral_pmpm | numeric | NEXUS-wide benchmark for the same specialty. |

### mart.nexus_pcp_roster — 360 rows

**Grain:** one row per NEXUS PCP (`pcp_npi` unique). Whole-period (2024-07-01 → 2026-06-30) scorecard. Best starting point for "which PCP…" questions.

| Column | Type | Description |
|---|---|---|
| pcp_group_tin / pcp_group_name / pcp_standard_group_name | text | PCP group. |
| pcp_npi / pcp_fullname | text | PCP. |
| member_pcp_sk | text | → `raw.providers.provider_sk`. |
| member_months / attributed_member_count | bigint | Exposure and distinct attributed members. |
| admission_count, avg_admission_los, admission_allowed_amt | | Inpatient totals. |
| er_encounter_count, er_allowed_amt | | ER totals. |
| referral_count, referral_allowed_amt | | Referral totals. |
| readmission_30d_count, potentially_avoidable_admit_count | bigint | |
| admits_<category> | bigint | Admission count by category: `newborn_nicu`, `orthopedic_msk`, `maternity_delivery`, `cardiac`, `newborn_neonatal`, `gi_digestive`, `behavioral_health`, `behavioral_substance_use`, `general_surgical`, `general_medical`, `unclassified`, `respiratory`, `neuro_stroke`, `oncology`, `infectious_sepsis`, `maternity_c_section`. |
| er_treat_and_release / er_observation | bigint | ER count by disposition. `er_admitted` always 0. |
| avg_risk_score / risk_member_count | | Average risk score over members that have one. |
| reporting_start_date / reporting_end_date | date | Always 2024-07-01 / 2026-06-30. |
| admission_pmpm, admission_cost_per_admit, admissions_per_1000 | numeric | |
| er_pmpm, er_per_1000, referral_pmpm, referrals_per_1000 | numeric | |
| total_allowed_amt / allowed_pmpm | numeric | All spend for attributed members. |
| allowed_risk_adj_pmpm, admission_/er_/referral_risk_adj_pmpm | numeric | PMPM ÷ `avg_risk_score`. |
| quality_total_measures, quality_compliant_count, quality_overdue_count, quality_members_with_measures | bigint | HEDIS rollup. |
| sparkline_* | text | 24 comma-separated monthly cumulative values (for UI charts; not for SQL math). |

### mart.member_panel — 4,374 rows

**Grain:** one row per NEXUS member with an attributed PCP (`member_sk` unique). Whole-period.

| Column | Type | Description |
|---|---|---|
| member_pcp_tin / member_pcp_groupname / member_pcp_npi / member_pcp_full_name | text | Attributed PCP. |
| member_sk / member_full_name | text | Member. |
| member_age | bigint | |
| member_gender | text | `F`, `M`, `U`. |
| risk_score / projected_risk / admission_risk | numeric | Risk model outputs (36% null). |
| resource_utilization | text | `Healthy Users`, `Low`, `Moderate`, `High`, `Very High`. |
| admission_count, readmission_count, er_count, referral_count | bigint | Whole-period counts. |
| alos | numeric | Avg length of stay. |
| pcp_start_date / last_pcp_visit_date | date | |
| probabilityhospitalization_next12months / _next6months, probability_icu, probabilityhospitalization_extended | numeric | Predicted probabilities, **in percent** (e.g. `0.39` = 0.39%). |
| chronic_conditions | text | `'; '`-separated codes: AFIB, AMI, ANE (anemia), ASTMA, BP (bipolar), BPH, CA* (cancers: BRST, CR, E, LNG, PRST, URL, TRCT=cataract), CKD/CKD1–5, COPD, DB (diabetes), DEM, DP (depression), GLA, HF, HLD, HPFRAC, HTH (hypothyroid), HTN, IHD, NP, OSTP, PNE, PVD, RA, SCHZ, STRK. Filter with `chronic_conditions LIKE '%HTN%'` or `'HTN' = ANY(string_to_array(chronic_conditions, '; '))`. |
| care_gaps | text | `'; '`-separated open HEDIS gap codes (BCS, CCS, CRCS, CHBP, CIS, DKE, EYE, CAP11/19/24/72, AAC20/44/64, IAC2, IAHPV, IAM, IATDAP, AICPC, AICT). |
| admission_/er_/referral_total_allowed_amt, total_allowed_amt | numeric | Whole-period spend. |

### mart.member_info — 10,561 rows

**Grain:** one row per NEXUS member (`member_sk` unique). Columns: `member_sk`, `member_full_name`, `member_full_address` (PHI), `member_gender`, `member_age` bigint, `member_relationship` (always empty), `level1_hierarchy` (always `NEXUS`), `level2_hierarchy`, `level3_hierarchy`.

### mart.member_months_by_provider_group — 1,545 rows

**Grain:** PCP (TIN + NPI) × employer group (may repeat — aggregate). Columns: `prov_tin`, `prov_groupname`, `prov_npi`, `prov_fullname`, `employer_group` (= `level3_hierarchy`), `employer_avg_risk_score` numeric (employer-level), `member_months` bigint.

### mart.admission_members — 3,050 rows

**Grain:** one row per inpatient/observation admission (`admission_number` unique), both networks.

| Column | Type | Description |
|---|---|---|
| admission_number | text | `'Admission 1625'`. |
| member_sk | text | |
| provider_sk / servicing_provider_groupname | text | Facility. |
| ub_claim_number / hcfa_claim_number | text | Claim numbers joinable to `raw.claims.claim_number`; HCFA is `;`-separated. |
| admission_category | text | `Maternity/Delivery`, `Newborn/Neonatal`, `General Medical`, `Behavioral Health`, `GI/Digestive`, `General Surgical`, `Cardiac`, `Oncology`, `Infectious/Sepsis`, `Respiratory`, `Neuro/Stroke`, `Orthopedic/MSK`, `Unclassified`, `Behavioral - Substance Use`, `Newborn - NICU`, `Maternity - C-Section`. |
| admission_source | text | `Emergency (ED-origin) [derived]`, `Elective/Scheduled [derived]`, `Unknown [derived]`. |
| care_setting | text | `Acute Inpatient`, `Observation (outpatient)`, `Inpatient Rehab`, `Skilled Nursing`, `Swing Bed` (each suffixed ` [derived]`). |
| admit_date / discharge_date | date | |
| admission_los | bigint | Days. |
| principal_diagnosis | text | ICD-10. |
| drg_code / drg_description | text | MS-DRG (54% null). |
| is_surgical, is_icu, is_ed_origin, is_observation, is_potentially_avoidable, is_readmission_30d | boolean | |
| ub_claim_count / hcfa_claim_line_count | bigint / numeric | |
| facility_billed_amt, facility_allowed_amt, professional_billed_amt, professional_allowed_amt, total_billed_amt, total_allowed_amt | numeric | Total = facility + professional. |
| dq_rnb_without_inpatient_tob, dq_inpatient_tob_without_rnb, dq_negative_los, dq_open_interim_chain, dq_drg_unmatched, dq_ambiguous_pcp_at_admit | boolean | Data-quality flags. |
| member_gender / member_age_at_admit | text / bigint | |
| level1_hierarchy / level2_hierarchy / level3_hierarchy | text | |
| member_pcp_sk, member_pcp_tin, member_pcp_groupname, member_pcp_npi, member_pcp_fname, member_pcp_lname | text | PCP at admit (88% null — most members have no attributed PCP). |

### mart.readmissions_30d — 222 rows

**Grain:** one row per readmission pair (readmit within 30 days of index discharge). Columns: `readmission_admission_number`, `index_admission_number` (→ `admission_members.admission_number`), `member_sk`, `index_admit_date`, `index_discharge_date`, `readmit_date`, `readmit_discharge_date`, `days_between` (1–30), `index_los`, `readmit_los`, `index_category`, `readmit_category`, `index_principal_diagnosis`, `readmit_principal_diagnosis`, `same_service_line` bool, `readmit_potentially_avoidable` bool, `index_provider_sk`, `readmit_provider_sk`, `same_facility` bool, `index_allowed_amt`, `readmit_allowed_amt`, `readmit_billed_amt`, `member_age_at_readmit`, `member_gender`, `level1_hierarchy`, `level3_hierarchy`, `readmit_pcp_tin`, `readmit_pcp_groupname`, `readmit_pcp_npi`, `readmit_pcp_full_name`.

### mart.er_encounters — 10,052 rows

**Grain:** one row per ER visit (`er_encounter_id` unique), both networks.

| Column | Type | Description |
|---|---|---|
| er_encounter_id / er_encounter_number | text | `ER000001` / `'ER Encounter 1'`. |
| member_sk | text | |
| member_pcp_sk, member_pcp_tin, member_pcp_groupname, member_pcp_npi, member_pcp_fname, member_pcp_lname | text | PCP at visit (86% null). |
| dq_ambiguous_pcp_at_er | boolean | |
| servicing_provider_groupname | text | Facility. |
| ub_claim_number / hcfa_claim_number / claim_numbers | text | Join to `raw.claims.claim_number`; `;`-separated. |
| er_date | date | |
| is_er | boolean | Always true. |
| er_component | text | Which claims identified the visit: `BOTH`, `UB` (facility only), `PR` (professional only). |
| er_confidence | text | `High`, `Medium`, `Low`. |
| er_disposition | text | `treat_and_release`, `observation`. |
| is_observation / is_revisit_30d | boolean | |
| er_claim_count | bigint | |
| billed_amt / allowed_amt | numeric | |
| principal_diagnosis / principal_diagnosis_normalized / principal_diagnosis_description | text | ICD-10 with and without dot, plus description. |
| principal_diagnosis_ref_matched | boolean | Whether the code matched the ICD reference. |
| all_diagnosis_codes / all_diagnosis_descriptions | text | `;`-separated. |
| diagnosis_code_count | bigint | |
| dq_unmatched_diagnosis_codes | text | `;`-separated codes that didn't match the reference. |

### mart.er_revisits_30d — 1,475 rows

**Grain:** one row per ER revisit pair. Columns: `revisit_encounter_number`, `index_encounter_number` (→ `er_encounters.er_encounter_number`), `member_sk`, `index_er_date`, `revisit_er_date`, `days_between` (1–30), `index_/revisit_component`, `index_/revisit_confidence`, `index_/revisit_disposition`, `index_/revisit_principal_diagnosis`, `index_/revisit_principal_diagnosis_description`, `same_principal_diagnosis` bool, `index_allowed_amt`, `revisit_allowed_amt`, `revisit_billed_amt`.

### mart.referrals_episodes — 261,678 rows

**Grain:** one row per specialist episode (`referral_episode_id` unique), both networks. An episode groups a member's visits to one specialist provider.

| Column | Type | Description |
|---|---|---|
| referral_number / referral_episode_id | text | |
| member_sk, member_gender, member_age_at_referral | | `member_age_at_referral` has a few `-1`. |
| plan_id, level1_hierarchy, level2_hierarchy, level3_hierarchy | text | |
| member_pcp_sk, anchor_pcp_npi, anchor_pcp_tin, anchor_pcp_groupname, anchor_pcp_fullname, anchor_pcp_specialty | text | PCP the referral is anchored to (87% null). |
| anchor_pcp_visit_date / days_from_pcp_to_specialist | date / numeric | ~100% null. |
| pcp_visits_in_lookback | bigint | |
| servicing_provider_sk, servicing_prov_npi, servicing_prov_tin, servicing_prov_groupname, servicing_prov_fullname | text | Specialist. |
| servicing_specialty | text | 178 values. |
| specialty_group | text | `Other Specialty`, `OB/GYN`, `Orthopedic/MSK`, `Physical Therapy`, `ENT`, `Oncology`, `Podiatry`, `Pulmonology`, `Allergy/Immunology`, `Speech Therapy`. |
| servicing_provider_tier | text | `Tier 1`, `Tier 2`. |
| referral_type | text | `PCP-Directed`, `Self-Referral`, `Specialist-to-Specialist`, `No-PCP-Attribution` (each suffixed ` [derived]`). |
| network_status | text | `In-Group`, `Out-of-Group, Same Geography [derived]`, `Out-of-Network [derived]`. |
| acuity | text | `Consultation Only`, `Diagnostic Workup`, `Procedure Performed`, `Other`. |
| clinical_context | text | `Orthopedic/MSK`, `Cardiac`, `Behavioral`, `Symptoms/Non-Specific`, … (14 values). |
| episode_start_date / episode_end_date | date | |
| visit_count, claim_count, line_count | bigint | |
| governing_diagnosis_cd01 / governing_diagnosis_description | text | Primary diagnosis of the episode. |
| governing_proc_code / governing_proc_code_description | text | Primary procedure (CPT/HCPCS). |
| episode_billed_amt / episode_allowed_amt | numeric | |
| exclude_from_rate_count | boolean | **Exclude `true` rows when counting referrals for rates.** |
| dq_provider_specialty_missing, dq_pcp_window_outside_service, dq_pcp_window_open_ended, dq_ambiguous_pcp_specialty, dq_negative_days_from_pcp, dq_specialty_diagnosis_mismatch | boolean | Data-quality flags. |

### mart.access_hedis_measure — 12,639 rows

**Grain:** NEXUS member × HEDIS measure × qualifying service event (see quirks). ~5,071 members.

| Column | Type | Description |
|---|---|---|
| level1 / level2 / level3 | text | Same as `level1/2/3_hierarchy` (level1 always `NEXUS`). |
| membernumber | text | **= `member_sk`.** |
| membername | text | PHI. |
| measurename | text | AAP, BCS, CBP, CCS, CIS, `CAP - 12 to 24 Months`, `CAP - 25 to 72 Months`, `CAP - 7 to 11 Years`, `CAP - 12 to 19 Years`, `CDC - HbA1c Testing`, `CDC - HbA1c Poor Control >9.0)`, `Cervical Cancer Screening`, `Diabetes - Kidney Health Evaluation`, `Eye Exam for Patients With Diabetes, 2025`, `IMA - Combo2`, `Medication Management for People With Asthma`. |
| measuredesc | text | Full measure name (asthma measure has 50% and 75% variants). |
| measurestatus | text | `Completed` or `Overdue` (= open care gap). |
| measurelastsvcdate | date | Last qualifying service date (29% null). |
| measurerecfreq | text | Recommended frequency (`12 Months`, `24 Months`, `27 Months`, `Age 2 Years`). |
| memberpcpnpi / memberpcpname | text | PCP; `9999999999` = none. |
| memberactiveflag | text | Always `Y`. |
| measurevalue | numeric | Result value for value-based measures (blood pressure, HbA1c); 95% null. |
| member_pcp_sk, member_pcp_tin, member_pcp_groupname, member_pcp_npi, member_pcp_fname, member_pcp_lname | text | Attributed PCP detail (20% null). |
