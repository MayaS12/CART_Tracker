# NexCAR19 Patient Tracker — prototype

Structured replacement for the WhatsApp update workflow. See `SCHEMA.md` for
the data model and design reasoning.

## Run it

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

Demo logins (change before any real use):
- `nurse1` / `nurse123` — role: nurse/MO, can submit entries
- `spec1` / `spec123` — role: specialist, can approve/request changes
- `admin` / `admin123` — role: admin

## What it does right now
- Create a patient (code, diagnosis, one-time history, infusion date)
- Nurse/MO fills a structured entry tied to a CAR-T phase (vitals, symptoms,
  exam, labs, CRS/ICANS inputs, plan)
- CRS grade and ICANS grade are **computed automatically** from the discrete
  inputs, per the ASTCT tables in the toxicity planner
- Entry goes into a specialist review queue
- Specialist approves (locks into timeline) or requests changes
- Patient timeline shows every approved entry in order, with auto D+n day count
- Full audit trail (who created, who reviewed, when)
- Role-based access (nurses can't reach the review queue)

## What's deliberately not built yet
- **Hosting/deployment** — this runs on SQLite locally for now. Before this
  touches real patient data, decide where it lives (Tata Memorial's own
  infrastructure vs. cloud) — that decision affects the DB choice, auth
  hardening, and encryption approach, and likely needs sign-off given India's
  DPDP Act applies to health data.
- Password reset / self-service account creation (currently seeded manually)
- Encryption at rest for sensitive fields
- Editing an approved entry (by design — corrections should be new addenda,
  not silent overwrites, but there's no UI for that yet)
- Charting labs/vitals over time (the data's there, just not graphed)
- Any LLM component — deliberately left out; see the discussion in chat on why
  a rule-based approach is more reliable here for v1

## A clinical caveat worth repeating
The CRS/ICANS grading logic in `app.py` (`compute_crs_grade`, `compute_icans`)
is a simplified, deterministic translation of the ASTCT tables in the
toxicity planner, meant to speed up entry and flag things early — it hasn't
been validated by a specialist. Before anyone relies on the auto-computed
grade as anything more than a prompt to double-check, have Dr. Jain or another
specialist review the logic against real cases.
