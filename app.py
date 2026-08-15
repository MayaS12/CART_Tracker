"""
NexCAR19 Patient Tracker — prototype
Structured replacement for the WhatsApp update workflow.
Entry form is now stage-based/dynamic: which panels show depends on which
stage (Phase) of the CAR-T journey the entry is for, per the treating team's
stage-specific checklists.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000

Demo logins (change these before any real use):
    nurse1 / nurse123      (role: nurse_mo)
    spec1  / spec123       (role: specialist)
    admin  / admin123      (role: admin)
"""
import json
import os
from datetime import date, datetime

from flask import Flask, render_template, redirect, url_for, request, flash, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")

db_url = os.environ.get("DATABASE_URL", "sqlite:///tracker.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ---------------- Stage / form constants ----------------

PHASES = [
    "Before Apheresis",
    "After Apheresis",
    "Conditioning",
    "Eligibility & Pre-Infusion (Day -1)",
    "CAR T-Cell Infusion",
    "Routine Visit",
]

SYMPTOM_OPTIONS = [
    "fever", "dry_cough", "sore_throat", "chills", "headache",
    "neck_pain", "myalgia", "fatigue", "nausea", "vomiting",
    "facial_swelling", "visual_problems", "lower_limb_pain",
]

LAB_GROUPS = {
    "CBC": ["hb", "tlc_wbc", "anc", "plt", "alc"],
    "Renal": ["urea", "creat"],
    "Electrolytes": ["na", "k", "ca", "po4", "mg"],
    "Liver": ["ast", "alt", "t_bil", "alp"],
    "Coagulation / inflammation": ["fibrinogen", "crp", "ldh", "ferritin", "b2_microglobulin"],
    "Immunoglobulins": ["igg", "iga", "igm"],
    "Infection workup": [
        "cmv_dna_pcr", "bdg", "galactomannan", "posa_level",
        "blood_culture", "picc_swab_culture", "sputum_culture",
    ],
    "Conditioning workup": ["triglycerides", "beta_hcg"],
}
LAB_FIELDS = [f for group in LAB_GROUPS.values() for f in group]

# Panels/lab-groups that only apply to specific stages — everything else
# (Vitals, Symptoms, the core lab groups, meds, notes) is shown on every stage.
PHASE_ONLY_LAB_GROUPS = {"Conditioning workup": "Conditioning"}

ICAHT_GRADES = ["none", "Grade I", "Grade II", "Grade III", "Grade IV"]
BM_MRD_OPTIONS = ["not_done", "negative", "positive"]
CSF_STATUS_OPTIONS = ["not_done", "negative", "flow_positive", "morpho_positive", "both_positive"]

DRUGS_STOPPED_OPTIONS = [
    "steroids", "immunosuppressants", "antiproliferative_therapies",
    "tyrosine_kinase_inhibitors", "hydroxyurea", "cytotoxic_drugs",
    "weekly_maintenance_therapies", "anti_cd20_antibodies",
    "cns_disease_prophylaxis", "radiation_therapy",
]
CONSUMABLES_OPTIONS = [
    "apheresis_kit", "acd", "saline", "heparin",
    "machine_functioning_confirmed", "investigations_noted",
    "cd3_count_informed_to_manufacturing",
]
CONDITIONING_INVESTIGATIONS_OPTIONS = [
    "cbc", "biochemistry", "serum_electrolytes", "s_crp", "s_ferritin",
    "s_beta2_microglobulin", "ldh", "s_triglycerides", "fibrinogen",
    "beta_hcg", "pet_ct", "bm_biopsy",
]


# ---------------- Models ----------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(128))
    role = db.Column(db.String(32), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128))
    code = db.Column(db.String(32), unique=True, nullable=False)
    age = db.Column(db.Integer)
    sex = db.Column(db.String(16))

    treating_center = db.Column(db.String(128))
    referring_center = db.Column(db.String(128))

    diagnosis = db.Column(db.String(256))
    diagnosis_subtype = db.Column(db.String(128))
    cytogenetics_baseline = db.Column(db.String(256))
    relapse_date = db.Column(db.Date, nullable=True)
    disease_history = db.Column(db.Text)

    car_t_product = db.Column(db.String(128))
    planned_dose = db.Column(db.String(64))
    central_line_type = db.Column(db.String(64))
    central_line_date = db.Column(db.Date, nullable=True)

    infusion_date = db.Column(db.Date, nullable=True)

    entries = db.relationship("Entry", backref="patient", lazy=True,
                               order_by="Entry.entry_date")


class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patient.id"), nullable=False)

    phase = db.Column(db.String(64))
    entry_date = db.Column(db.Date, default=date.today)
    reason_for_admission = db.Column(db.String(256))
    performance_status = db.Column(db.Integer)

    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    status = db.Column(db.String(32), default="submitted")
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    review_comment = db.Column(db.Text, nullable=True)

    # vitals
    temp_f = db.Column(db.Float)
    pulse = db.Column(db.Integer)
    bp_sys = db.Column(db.Integer)
    bp_dia = db.Column(db.Integer)
    spo2 = db.Column(db.Integer)
    rr = db.Column(db.Integer)

    # symptoms
    symptom_flags = db.Column(db.Text)
    symptoms_note = db.Column(db.Text)

    # labs (flat JSON)
    labs = db.Column(db.Text)

    # disease reassessment
    assessment_date = db.Column(db.Date, nullable=True)
    bm_blast_pct = db.Column(db.Float, nullable=True)
    bm_mrd_status = db.Column(db.String(16), nullable=True)
    csf_status = db.Column(db.String(16), nullable=True)
    ctg_findings = db.Column(db.String(256), nullable=True)      # free text
    rt_qpcr = db.Column(db.String(256), nullable=True)            # free text
    molecular_report = db.Column(db.String(256), nullable=True)   # free text

    # --- Before Apheresis ---
    apheresis_fit = db.Column(db.String(8), nullable=True)
    apheresis_labs_wnl = db.Column(db.String(8), nullable=True)
    meal_before_apheresis = db.Column(db.String(8), nullable=True)
    heparin_issued = db.Column(db.String(8), nullable=True)
    apheresis_machine_ok = db.Column(db.String(8), nullable=True)
    apheresis_concerns = db.Column(db.Text, nullable=True)
    apheresis_final_fit = db.Column(db.String(8), nullable=True)
    non_refundable_blocked = db.Column(db.String(8), nullable=True)
    drugs_stopped = db.Column(db.Text, nullable=True)   # JSON list
    consumables_ready = db.Column(db.Text, nullable=True)  # JSON list
    pending_reports = db.Column(db.Text, nullable=True)
    apheresis_time = db.Column(db.String(64), nullable=True)
    apheresis_outcome = db.Column(db.String(16), nullable=True)

    # --- After Apheresis ---
    bridging_therapy_planned = db.Column(db.String(8), nullable=True)
    it_mtx_given = db.Column(db.String(8), nullable=True)
    it_mtx_dose = db.Column(db.String(64), nullable=True)
    response_assessment_done = db.Column(db.String(8), nullable=True)
    response_assessment_type = db.Column(db.String(64), nullable=True)
    response_assessment_date = db.Column(db.Date, nullable=True)
    central_line_removal_precautions = db.Column(db.String(8), nullable=True)

    # --- Conditioning ---
    conditioning_investigations_done = db.Column(db.Text, nullable=True)  # JSON list
    car_hematotox_score = db.Column(db.Integer, nullable=True)
    car_hematotox_risk = db.Column(db.String(32), nullable=True)
    prn_orders_confirmed = db.Column(db.String(8), nullable=True)
    bsa = db.Column(db.Float, nullable=True)
    fludarabine_given = db.Column(db.String(8), nullable=True)
    fludarabine_dose = db.Column(db.String(64), nullable=True)
    cyclophosphamide_given = db.Column(db.String(8), nullable=True)
    cyclophosphamide_dose = db.Column(db.String(64), nullable=True)
    dose_modification = db.Column(db.String(8), nullable=True)
    dose_modification_reason = db.Column(db.Text, nullable=True)

    # --- Eligibility & Pre-Infusion ---
    ps_unchanged = db.Column(db.String(8), nullable=True)
    chemo_toxicities_resolved = db.Column(db.String(8), nullable=True)
    postponement_pulmonary = db.Column(db.String(8), nullable=True)
    postponement_cardiac = db.Column(db.String(8), nullable=True)
    postponement_hypotension = db.Column(db.String(8), nullable=True)
    postponement_infection = db.Column(db.String(8), nullable=True)
    fit_for_infusion = db.Column(db.String(8), nullable=True)
    delay_reassessment_date = db.Column(db.Date, nullable=True)
    delay_duration = db.Column(db.String(64), nullable=True)
    delay_reason = db.Column(db.String(256), nullable=True)

    # --- CAR T-Cell Infusion ---
    car_t_dose_given = db.Column(db.String(64), nullable=True)
    premedication_start = db.Column(db.String(32), nullable=True)
    premedication_stop = db.Column(db.String(32), nullable=True)
    thaw_start = db.Column(db.String(32), nullable=True)
    thaw_stop = db.Column(db.String(32), nullable=True)
    infusion_start = db.Column(db.String(32), nullable=True)
    infusion_stop = db.Column(db.String(32), nullable=True)
    infusion_outcome = db.Column(db.String(16), nullable=True)

    # CRS
    fever_present = db.Column(db.Boolean, default=False)
    hypotension_level = db.Column(db.String(32), default="none")
    hypoxia_level = db.Column(db.String(32), default="none")
    crs_grade = db.Column(db.Integer, default=0)

    # ICANS / ICE
    ice_orientation = db.Column(db.Integer, default=4)
    ice_naming = db.Column(db.Integer, default=3)
    ice_command = db.Column(db.Integer, default=1)
    ice_writing = db.Column(db.Integer, default=1)
    ice_attention = db.Column(db.Integer, default=1)
    consciousness_level = db.Column(db.String(32), default="spontaneous")
    seizure_status = db.Column(db.String(32), default="none")
    motor_findings = db.Column(db.String(32), default="none")
    cerebral_edema = db.Column(db.String(32), default="none")
    ice_score = db.Column(db.Integer)
    icans_grade = db.Column(db.Integer, default=0)

    # other toxicity (bundled with CAR T-Cell Infusion stage)
    icaht_grade = db.Column(db.String(16), nullable=True)
    hlh_suspected = db.Column(db.String(8), nullable=True)
    hlh_note = db.Column(db.Text, nullable=True)

    # medications (always available regardless of stage)
    medication_rows = db.Column(db.Text)  # JSON list of {name, frequency, dose, stop_date}
    medications_plan = db.Column(db.Text)  # free text
    free_notes = db.Column(db.Text)

    creator = db.relationship("User", foreign_keys=[created_by_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by_id])

    def symptom_list(self):
        return json.loads(self.symptom_flags or "[]")

    def lab_dict(self):
        return json.loads(self.labs or "{}")

    def med_rows(self):
        return json.loads(self.medication_rows or "[]")

    def drugs_stopped_list(self):
        return json.loads(self.drugs_stopped or "[]")

    def consumables_list(self):
        return json.loads(self.consumables_ready or "[]")

    def conditioning_investigations_list(self):
        return json.loads(self.conditioning_investigations_done or "[]")

    def day_relative(self):
        if self.patient.infusion_date and self.entry_date:
            delta = (self.entry_date - self.patient.infusion_date).days
            return f"D{'+' if delta >= 0 else ''}{delta}"
        return "—"


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entry_id = db.Column(db.Integer, db.ForeignKey("entry.id"))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(64))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    detail = db.Column(db.Text)

    entry = db.relationship("Entry")
    user = db.relationship("User")


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------- Computed grading ----------------

def compute_crs_grade(fever, hypotension_level, hypoxia_level):
    if not fever:
        return 0
    grade = 1
    if hypotension_level == "multi_vasopressor" or hypoxia_level == "positive_pressure":
        grade = 4
    elif hypotension_level == "one_vasopressor" or hypoxia_level == "high_flow_or_mask":
        grade = 3
    elif hypotension_level == "fluids" or hypoxia_level == "low_flow":
        grade = 2
    return grade


def compute_icans(ice_score, consciousness, seizure, motor, edema):
    if consciousness == "unarousable":
        grade = 4
    else:
        if ice_score >= 7:
            grade = 1
        elif ice_score >= 3:
            grade = 2
        else:
            grade = 3

    if consciousness == "voice":
        grade = max(grade, 2)
    elif consciousness == "tactile":
        grade = max(grade, 3)

    if seizure == "resolves_lt5min":
        grade = max(grade, 3)
    elif seizure == "prolonged_or_recurrent":
        grade = max(grade, 4)

    if motor == "focal_weakness":
        grade = max(grade, 4)

    if edema == "focal":
        grade = max(grade, 3)
    elif edema == "diffuse":
        grade = max(grade, 4)

    return grade


def compute_hematotox(labs):
    """CAR-HEMATOTOX score from the pre-conditioning planner's table.
    Only scores the parameters that were actually entered — missing values
    just don't add points, so an incomplete panel understates the score
    rather than erroring. Flag this to whoever reviews it."""
    def num(key):
        v = labs.get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    score = 0
    plt, anc, hb, crp, ferritin = num("plt"), num("anc"), num("hb"), num("crp"), num("ferritin")

    if plt is not None:
        score += 2 if plt <= 75 else (1 if plt <= 175 else 0)
    if anc is not None:
        score += 1 if anc < 1.2 else 0
    if hb is not None:
        score += 1 if hb <= 9.0 else 0
    if crp is not None:
        score += 1 if crp >= 3.0 else 0
    if ferritin is not None:
        score += 2 if ferritin > 2000 else (1 if ferritin >= 650 else 0)

    risk = "High risk (HThigh)" if score >= 2 else "Low risk (HTlow)"
    return score, risk


# ---------------- Auth / dashboard routes ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(username=request.form["username"]).first()
        if user and not user.active:
            flash("This account has been deactivated")
        elif user and user.check_password(request.form["password"]):
            login_user(user)
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    q = request.args.get("q", "").strip()
    patients_query = Patient.query
    if q:
        like = f"%{q}%"
        if current_user.role == "nurse_mo":
            patients_query = patients_query.filter(
                db.or_(Patient.name.ilike(like), Patient.code.ilike(like))
            )
        else:
            patients_query = patients_query.filter(
                db.or_(
                    Patient.name.ilike(like), Patient.code.ilike(like),
                    Patient.treating_center.ilike(like), Patient.referring_center.ilike(like),
                )
            )
    patients = patients_query.order_by(Patient.code).all()
    pending_count = Entry.query.filter_by(status="submitted").count()
    revision_count = Entry.query.filter_by(status="changes_requested").count()
    return render_template("dashboard.html", patients=patients,
                            pending_count=pending_count, revision_count=revision_count, q=q)


def _parse_date(val):
    return datetime.strptime(val, "%Y-%m-%d").date() if val else None


@app.route("/patients/new", methods=["GET", "POST"])
@login_required
def new_patient():
    if request.method == "POST":
        f = request.form
        p = Patient(
            name=f.get("name"),
            code=f["code"],
            age=f.get("age") or None,
            sex=f.get("sex"),
            treating_center=f.get("treating_center"),
            referring_center=f.get("referring_center"),
            diagnosis=f.get("diagnosis"),
            diagnosis_subtype=f.get("diagnosis_subtype"),
            cytogenetics_baseline=f.get("cytogenetics_baseline"),
            relapse_date=_parse_date(f.get("relapse_date")),
            disease_history=f.get("disease_history"),
            car_t_product=f.get("car_t_product"),
            planned_dose=f.get("planned_dose"),
            central_line_type=f.get("central_line_type"),
            central_line_date=_parse_date(f.get("central_line_date")),
            infusion_date=_parse_date(f.get("infusion_date")),
        )
        db.session.add(p)
        db.session.commit()
        flash(f"Patient {p.code} created")
        return redirect(url_for("dashboard"))
    return render_template("new_patient.html")


@app.route("/patients/<int:patient_id>")
@login_required
def patient_timeline(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    entries = Entry.query.filter_by(patient_id=patient_id).order_by(Entry.entry_date).all()
    return render_template("timeline.html", patient=patient, entries=entries)


# ---------------- Entry create / edit (shared logic) ----------------

def parse_med_rows(f):
    names = f.getlist("med_name")
    freqs = f.getlist("med_freq")
    doses = f.getlist("med_dose")
    stops = f.getlist("med_stop")
    rows = []
    for i, name in enumerate(names):
        if name.strip():
            rows.append({
                "name": name.strip(),
                "frequency": freqs[i].strip() if i < len(freqs) else "",
                "dose": doses[i].strip() if i < len(doses) else "",
                "stop_date": stops[i].strip() if i < len(stops) else "",
            })
    return rows


def apply_entry_fields(e, f):
    """Populate an Entry's fields from submitted form data. Shared between
    creating a new entry and editing one sent back for changes."""
    symptom_flags = f.getlist("symptom_flags")
    labs = {k: f.get(f"lab_{k}") for k in LAB_FIELDS if f.get(f"lab_{k}")}

    fever = "fever" in symptom_flags
    crs_grade = compute_crs_grade(fever, f.get("hypotension_level", "none"),
                                   f.get("hypoxia_level", "none"))
    ice_parts = [int(f.get(k, 0) or 0) for k in
                 ["ice_orientation", "ice_naming", "ice_command",
                  "ice_writing", "ice_attention"]]
    ice_score = sum(ice_parts)
    icans_grade = compute_icans(ice_score, f.get("consciousness_level", "spontaneous"),
                                 f.get("seizure_status", "none"),
                                 f.get("motor_findings", "none"),
                                 f.get("cerebral_edema", "none"))
    hematotox_score, hematotox_risk = compute_hematotox(labs)

    def opt_int(key):
        v = f.get(key)
        return int(v) if v else None

    def opt_float(key):
        v = f.get(key)
        return float(v) if v else None

    e.phase = f["phase"]
    e.entry_date = _parse_date(f["entry_date"])
    e.reason_for_admission = f.get("reason_for_admission")
    e.performance_status = opt_int("performance_status")

    e.temp_f, e.pulse = opt_float("temp_f"), opt_int("pulse")
    e.bp_sys, e.bp_dia = opt_int("bp_sys"), opt_int("bp_dia")
    e.spo2, e.rr = opt_int("spo2"), opt_int("rr")

    e.symptom_flags = json.dumps(symptom_flags)
    e.symptoms_note = f.get("symptoms_note")

    e.labs = json.dumps(labs)

    e.assessment_date = _parse_date(f.get("assessment_date"))
    e.bm_blast_pct = opt_float("bm_blast_pct")
    e.bm_mrd_status = f.get("bm_mrd_status") or None
    e.csf_status = f.get("csf_status") or None
    e.ctg_findings = f.get("ctg_findings")
    e.rt_qpcr = f.get("rt_qpcr")
    e.molecular_report = f.get("molecular_report")

    # Before Apheresis
    e.apheresis_fit = f.get("apheresis_fit") or None
    e.apheresis_labs_wnl = f.get("apheresis_labs_wnl") or None
    e.meal_before_apheresis = f.get("meal_before_apheresis") or None
    e.heparin_issued = f.get("heparin_issued") or None
    e.apheresis_machine_ok = f.get("apheresis_machine_ok") or None
    e.apheresis_concerns = f.get("apheresis_concerns")
    e.apheresis_final_fit = f.get("apheresis_final_fit") or None
    e.non_refundable_blocked = f.get("non_refundable_blocked") or None
    e.drugs_stopped = json.dumps(f.getlist("drugs_stopped"))
    e.consumables_ready = json.dumps(f.getlist("consumables_ready"))
    e.pending_reports = f.get("pending_reports")
    e.apheresis_time = f.get("apheresis_time")
    e.apheresis_outcome = f.get("apheresis_outcome") or None

    # After Apheresis
    e.bridging_therapy_planned = f.get("bridging_therapy_planned") or None
    e.it_mtx_given = f.get("it_mtx_given") or None
    e.it_mtx_dose = f.get("it_mtx_dose")
    e.response_assessment_done = f.get("response_assessment_done") or None
    e.response_assessment_type = f.get("response_assessment_type")
    e.response_assessment_date = _parse_date(f.get("response_assessment_date"))
    e.central_line_removal_precautions = f.get("central_line_removal_precautions") or None

    # Conditioning
    e.conditioning_investigations_done = json.dumps(f.getlist("conditioning_investigations_done"))
    e.car_hematotox_score = hematotox_score
    e.car_hematotox_risk = hematotox_risk
    e.prn_orders_confirmed = f.get("prn_orders_confirmed") or None
    e.bsa = opt_float("bsa")
    e.fludarabine_given = f.get("fludarabine_given") or None
    e.fludarabine_dose = f.get("fludarabine_dose")
    e.cyclophosphamide_given = f.get("cyclophosphamide_given") or None
    e.cyclophosphamide_dose = f.get("cyclophosphamide_dose")
    e.dose_modification = f.get("dose_modification") or None
    e.dose_modification_reason = f.get("dose_modification_reason")

    # Eligibility & Pre-Infusion
    e.ps_unchanged = f.get("ps_unchanged") or None
    e.chemo_toxicities_resolved = f.get("chemo_toxicities_resolved") or None
    e.postponement_pulmonary = f.get("postponement_pulmonary") or None
    e.postponement_cardiac = f.get("postponement_cardiac") or None
    e.postponement_hypotension = f.get("postponement_hypotension") or None
    e.postponement_infection = f.get("postponement_infection") or None
    e.fit_for_infusion = f.get("fit_for_infusion") or None
    e.delay_reassessment_date = _parse_date(f.get("delay_reassessment_date"))
    e.delay_duration = f.get("delay_duration")
    e.delay_reason = f.get("delay_reason")

    # CAR T-Cell Infusion
    e.car_t_dose_given = f.get("car_t_dose_given")
    e.premedication_start = f.get("premedication_start")
    e.premedication_stop = f.get("premedication_stop")
    e.thaw_start, e.thaw_stop = f.get("thaw_start"), f.get("thaw_stop")
    e.infusion_start, e.infusion_stop = f.get("infusion_start"), f.get("infusion_stop")
    e.infusion_outcome = f.get("infusion_outcome") or None

    e.fever_present = fever
    e.hypotension_level = f.get("hypotension_level", "none")
    e.hypoxia_level = f.get("hypoxia_level", "none")
    e.crs_grade = crs_grade

    e.ice_orientation, e.ice_naming = ice_parts[0], ice_parts[1]
    e.ice_command, e.ice_writing, e.ice_attention = ice_parts[2], ice_parts[3], ice_parts[4]
    e.consciousness_level = f.get("consciousness_level", "spontaneous")
    e.seizure_status = f.get("seizure_status", "none")
    e.motor_findings = f.get("motor_findings", "none")
    e.cerebral_edema = f.get("cerebral_edema", "none")
    e.ice_score, e.icans_grade = ice_score, icans_grade

    e.icaht_grade = f.get("icaht_grade") or None
    e.hlh_suspected = f.get("hlh_suspected") or None
    e.hlh_note = f.get("hlh_note")

    e.medication_rows = json.dumps(parse_med_rows(f))
    e.medications_plan = f.get("medications_plan")
    e.free_notes = f.get("free_notes")


@app.route("/patients/<int:patient_id>/entries/new", methods=["GET", "POST"])
@login_required
def new_entry(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    if request.method == "POST":
        e = Entry(patient_id=patient.id, created_by_id=current_user.id, status="submitted")
        apply_entry_fields(e, request.form)
        db.session.add(e)
        db.session.commit()

        db.session.add(AuditLog(entry_id=e.id, user_id=current_user.id,
                                 action="submitted", detail=f"Phase: {e.phase}"))
        db.session.commit()
        flash("Entry submitted for specialist review")
        return redirect(url_for("patient_timeline", patient_id=patient.id))

    return render_template(
        "entry_form.html", patient=patient, entry=None, phases=PHASES,
        symptom_options=SYMPTOM_OPTIONS, lab_groups=LAB_GROUPS,
        phase_only_lab_groups=PHASE_ONLY_LAB_GROUPS,
        icaht_grades=ICAHT_GRADES, bm_mrd_options=BM_MRD_OPTIONS,
        csf_status_options=CSF_STATUS_OPTIONS,
        drugs_stopped_options=DRUGS_STOPPED_OPTIONS,
        consumables_options=CONSUMABLES_OPTIONS,
        conditioning_investigations_options=CONDITIONING_INVESTIGATIONS_OPTIONS,
        today=date.today().isoformat(),
    )


@app.route("/entries/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
def edit_entry(entry_id):
    e = Entry.query.get_or_404(entry_id)
    if e.status != "changes_requested":
        flash("Only entries marked 'changes requested' can be edited")
        return redirect(url_for("patient_timeline", patient_id=e.patient_id))

    if request.method == "POST":
        apply_entry_fields(e, request.form)
        e.status = "submitted"
        e.submitted_at = datetime.utcnow()
        db.session.commit()

        db.session.add(AuditLog(entry_id=e.id, user_id=current_user.id,
                                 action="resubmitted",
                                 detail=f"Revised after review comment: {e.review_comment or ''}"))
        db.session.commit()
        flash("Entry resubmitted for specialist review")
        return redirect(url_for("patient_timeline", patient_id=e.patient_id))

    return render_template(
        "entry_form.html", patient=e.patient, entry=e, phases=PHASES,
        symptom_options=SYMPTOM_OPTIONS, lab_groups=LAB_GROUPS,
        phase_only_lab_groups=PHASE_ONLY_LAB_GROUPS,
        icaht_grades=ICAHT_GRADES, bm_mrd_options=BM_MRD_OPTIONS,
        csf_status_options=CSF_STATUS_OPTIONS,
        drugs_stopped_options=DRUGS_STOPPED_OPTIONS,
        consumables_options=CONSUMABLES_OPTIONS,
        conditioning_investigations_options=CONDITIONING_INVESTIGATIONS_OPTIONS,
        today=date.today().isoformat(),
    )


@app.route("/revisions")
@login_required
def revisions():
    needing_changes = Entry.query.filter_by(status="changes_requested") \
        .order_by(Entry.reviewed_at.desc()).all()
    return render_template("revisions.html", entries=needing_changes)


@app.route("/queue")
@login_required
def queue():
    if current_user.role not in ("specialist", "admin"):
        abort(403)
    pending = Entry.query.filter_by(status="submitted").order_by(Entry.submitted_at).all()
    return render_template("queue.html", entries=pending)


@app.route("/entries/<int:entry_id>/review", methods=["POST"])
@login_required
def review_entry(entry_id):
    if current_user.role not in ("specialist", "admin"):
        abort(403)
    e = Entry.query.get_or_404(entry_id)
    decision = request.form["decision"]
    e.status = "approved" if decision == "approve" else "changes_requested"
    e.reviewed_by_id = current_user.id
    e.reviewed_at = datetime.utcnow()
    e.review_comment = request.form.get("comment")
    db.session.add(AuditLog(entry_id=e.id, user_id=current_user.id,
                             action=e.status, detail=e.review_comment or ""))
    db.session.commit()
    flash(f"Entry {'approved' if decision == 'approve' else 'sent back for changes'}")
    return redirect(url_for("queue"))


@app.route("/audit")
@login_required
def audit_log():
    if current_user.role not in ("specialist", "admin"):
        abort(403)
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(300).all()
    return render_template("audit.html", logs=logs)


@app.route("/users")
@login_required
def users():
    if current_user.role != "admin":
        abort(403)
    all_users = User.query.order_by(User.username).all()
    return render_template("users.html", users=all_users)


@app.route("/users/new", methods=["GET", "POST"])
@login_required
def new_user():
    if current_user.role != "admin":
        abort(403)
    if request.method == "POST":
        f = request.form
        if User.query.filter_by(username=f["username"]).first():
            flash("That username is already taken")
            return redirect(url_for("new_user"))
        u = User(
            username=f["username"],
            full_name=f.get("full_name"),
            role=f["role"],
            password_hash=generate_password_hash(f["password"]),
        )
        db.session.add(u)
        db.session.commit()
        flash(f"Account created for {u.full_name} ({u.username})")
        return redirect(url_for("users"))
    return render_template("new_user.html")


@app.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
def toggle_user(user_id):
    if current_user.role != "admin":
        abort(403)
    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        flash("You can't deactivate your own account while logged in as it")
        return redirect(url_for("users"))
    u.active = not u.active
    db.session.commit()
    flash(f"{u.full_name} ({u.username}) {'reactivated' if u.active else 'deactivated'}")
    return redirect(url_for("users"))


# ---------------- bootstrap / self-healing schema ----------------

def ensure_schema():
    """db.create_all() only creates tables that don't exist yet — it won't
    add new columns to a table that's already live (e.g. on Render). This
    adds any columns the current model expects but the live table is
    missing, so a redeploy after a schema change doesn't crash."""
    inspector = inspect(db.engine)
    is_sqlite = db.engine.url.get_backend_name() == "sqlite"
    type_map = {
        db.Integer: "INTEGER", db.Float: "FLOAT", db.Boolean: "BOOLEAN",
        db.Date: "DATE", db.DateTime: "TIMESTAMP", db.Text: "TEXT",
    }

    for table_name, model in (("user", User), ("patient", Patient), ("entry", Entry)):
        if table_name not in inspector.get_table_names():
            continue
        existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        for col in model.__table__.columns:
            if col.name in existing_cols:
                continue
            col_type = "TEXT"
            for py_type, sql_type in type_map.items():
                if isinstance(col.type, py_type):
                    col_type = sql_type
                    break
            if isinstance(col.type, db.String):
                col_type = "TEXT" if not is_sqlite else "VARCHAR"
            ident = f'"{table_name}"' if table_name == "user" else table_name
            try:
                with db.engine.connect() as conn:
                    conn.execute(text(f'ALTER TABLE {ident} ADD COLUMN {col.name} {col_type}'))
                    conn.commit()
            except Exception:
                pass  # best-effort; a failed add here shouldn't crash startup


def seed():
    db.create_all()
    ensure_schema()
    if not User.query.filter_by(username="nurse1").first():
        db.session.add(User(username="nurse1", full_name="Nurse Demo",
                             role="nurse_mo",
                             password_hash=generate_password_hash("nurse123")))
    if not User.query.filter_by(username="spec1").first():
        db.session.add(User(username="spec1", full_name="Specialist Demo",
                             role="specialist",
                             password_hash=generate_password_hash("spec123")))
    if not User.query.filter_by(username="admin").first():
        db.session.add(User(username="admin", full_name="Admin Demo",
                             role="admin",
                             password_hash=generate_password_hash("admin123")))
    db.session.commit()


with app.app_context():
    seed()

if __name__ == "__main__":
    app.run(debug=True)
