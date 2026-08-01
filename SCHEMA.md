# NexCAR19 Patient Tracker — Schema & Architecture

## Why this shape
Every WhatsApp entry for CK1326 repeats the same skeleton (history → phase → vitals →
exam → labs → toxicity signs → plan), just re-typed each time. The fix is: store the
stuff that doesn't change once (Patient), and make every update a structured Entry
tied to a phase, so nothing has to be retyped and toxicity grades get computed
instead of eyeballed.

## Tables

### users
| field | type | notes |
|---|---|---|
| id | int PK | |
| username | str unique | |
| password_hash | str | never store plaintext |
| role | enum | `nurse_mo`, `specialist`, `admin` |
| full_name | str | |

### patients
| field | type | notes |
|---|---|---|
| id | int PK | |
| code | str unique | e.g. CK1326 |
| age | int | |
| sex | str | |
| diagnosis | str | e.g. "B-ALL, relapsed" |
| disease_history | text | one-time narrative — dx date, prior lines, relapse date etc |
| infusion_date | date, nullable | set once known — powers auto "D+n" on every entry |

### entries  (one per clinical update — the core table)
| field | type | notes |
|---|---|---|
| id | int PK | |
| patient_id | FK → patients | |
| phase | enum | Planned / Apheresis / Bridging / Conditioning / Infusion / Acute toxicity / Long-term toxicity / Maintenance |
| entry_date | date | |
| created_by_id | FK → users | |
| status | enum | draft, submitted, approved, changes_requested |
| submitted_at | datetime | |
| reviewed_by_id | FK → users, nullable | |
| reviewed_at | datetime, nullable | |
| review_comment | text, nullable | |
| temp_f, pulse, bp_sys, bp_dia, spo2, rr | numeric | vitals |
| symptom_flags | JSON | checkbox list: fever, cough, chills, headache, sore_throat, myalgia, fatigue... |
| symptoms_note | text | free text |
| cns_status, cvs_status, resp_status, abd_status | str | normal / abnormal |
| exam_note | text | |
| labs | JSON | hb, tlc/wbc, anc, plt, creat, na, k, ca, po4, mg, ast, alt, tbil, crp, ferritin, fibrinogen, ldh, cmv_dna, bdg, igg, iga, igm |
| fever_present | bool | drives CRS grade |
| hypotension_level | enum | none / fluids / one_vasopressor / multi_vasopressor |
| hypoxia_level | enum | none / low_flow / high_flow_or_mask / positive_pressure |
| crs_grade | int, computed | 0–4 |
| ice_orientation, ice_naming, ice_command, ice_writing, ice_attention | int | ICE subscores |
| consciousness_level | enum | spontaneous / voice / tactile / unarousable |
| seizure_status | enum | none / resolves_lt5min / prolonged_or_recurrent |
| motor_findings | enum | none / focal_weakness |
| cerebral_edema | enum | none / focal / diffuse |
| ice_score, icans_grade | int, computed | |
| medications_plan | text | |
| free_notes | text | |

### audit_log
| field | type | notes |
|---|---|---|
| id | int PK | |
| entry_id | FK → entries | |
| user_id | FK → users | |
| action | str | created / submitted / approved / changes_requested |
| timestamp | datetime | |
| detail | text | |

## Workflow
1. Nurse/MO creates an entry against a patient + phase → `submitted`
2. Specialist sees a pending queue → approves (locks it into the timeline) or
   requests changes (goes back to the creator, original stays visible with the note)
3. Every entry is a new row, never edited in place after approval — corrections
   are addenda, so the timeline is a true audit trail
4. Patient timeline view = all approved entries in date order, plus computed
   D+n day count from `infusion_date`

## Computed toxicity grading
`crs_grade` from fever + hypotension level + hypoxia level, mapped against the
ASTCT CRS table in the planner.
`ice_score` = sum of the 5 ICE subscores (max 10); `icans_grade` takes the worst
of the ICE-score band, consciousness level, seizure status, motor findings, and
edema — per the planner's ICANS table.

**Important:** this is a simplified, deterministic re-implementation of the
ASTCT tables for speed of entry — it should be checked against Dr. Jain / a
specialist before anyone treats the auto-computed grade as authoritative rather
than advisory.

## Not built yet (flagged, not solved)
- Hosting/deployment target (depends on Tata Memorial IT vs cloud — decide before
  going live, since this is patient health data and India's DPDP Act likely
  applies to where it's hosted)
- Password reset / account provisioning flow
- Field-level encryption at rest
- LLM-assisted free-text parsing (optional, later — see chat discussion on why
  it's not needed for v1)
