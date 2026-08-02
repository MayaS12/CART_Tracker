"""
NexCAR19 Patient Tracker — prototype
Structured replacement for the WhatsApp update workflow.

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
# Render (and some other hosts) hand out "postgres://" but SQLAlchemy 1.4+
# requires "postgresql://" — this rewrites it automatically either way.
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

PHASES = [
    "Planned", "Apheresis", "Bridging therapy", "Conditioning chemotherapy",
    "CAR T-cell infusion", "Acute toxicity", "Long-term toxicity", "Maintenance",
]

SYMPTOM_OPTIONS = [
    "fever", "cough", "dry_cough", "sore_throat", "chills", "headache",
    "neck_pain", "myalgia", "fatigue", "nausea", "vomiting",
    "facial_swelling", "visual_problems", "lower_limb_pain",
]

LAB_GROUPS = {
    "CBC": ["hb", "tlc_wbc", "anc", "plt"],
    "Renal": ["urea", "creat"],
    "Electrolytes": ["na", "k", "ca", "po4", "mg"],
    "Liver": ["ast", "alt", "t_bil", "alp"],
    "Coagulation / inflammation": ["fibrinogen", "crp", "ldh", "ferritin", "b2_microglobulin"],
    "Immunoglobulins": ["igg", "iga", "igm"],
    "Infection workup": [
        "cmv_dna_pcr", "bdg", "galactomannan", "posa_level",
        "blood_culture", "picc_swab_culture", "sputum_culture",
    ],
}
LAB_FIELDS = [f for group in LAB_GROUPS.values() for f in group]

COMMON_MEDS = [
    "posaconazole", "acyclovir", "septran_ds", "hmw_clogen",
    "g_csf", "ruxolitinib", "tocilizumab", "antibiotics_broad_spectrum",
    "ivig", "folvite_b12",
]

ICAHT_GRADES = ["none", "Grade I", "Grade II", "Grade III", "Grade IV"]
DISEASE_STATUS_OPTIONS = ["not_done", "negative", "positive"]


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

    temp_f = db.Column(db.Float)
    pulse = db.Column(db.Integer)
    bp_sys = db.Column(db.Integer)
    bp_dia = db.Column(db.Integer)
    spo2 = db.Column(db.Integer)
    rr = db.Column(db.Integer)

    symptom_flags = db.Column(db.Text)
    symptoms_note = db.Column(db.Text)

    cns_status = db.Column(db.String(16))
    hmf_status = db.Column(db.String(16))
    cranial_nerves_status = db.Column(db.String(16))
    neck_rigidity = db.Column(db.String(8))
    fnd_present = db.Column(db.String(8))
    handwriting_normal = db.Column(db.String(8))
    cvs_status = db.Column(db.String(16))
    resp_status = db.Column(db.String(16))
    abd_status = db.Column(db.String(16))
    splenomegaly = db.Column(db.String(8))
    exam_note = db.Column(db.Text)

    labs = db.Column(db.Text)

    assessment_date = db.Column(db.Date, nullable=True)
    bm_blast_pct = db.Column(db.Float, nullable=True)
    bm_mrd_status = db.Column(db.String(16), nullable=True)
    csf_status = db.Column(db.String(16), nullable=True)
    ctg_status = db.Column(db.String(16), nullable=True)
    flow_mrd_status = db.Column(db.String(16), nullable=True)

    apheresis_time = db.Column(db.String(64), nullable=True)
    apheresis_outcome = db.Column(db.String(16), nullable=True)
    car_t_dose_given = db.Column(db.String(64), nullable=True)
    premedication_start = db.Column(db.String(32), nullable=True)
    premedication_stop = db.Column(db.String(32), nullable=True)
    thaw_start = db.Column(db.String(32), nullable=True)
    thaw_stop = db.Column(db.String(32), nullable=True)
    infusion_start = db.Column(db.String(32), nullable=True)
    infusion_stop = db.Column(db.String(32), nullable=True)
    infusion_outcome = db.Column(db.String(16), nullable=True)

    fever_present = db.Column(db.Boolean, default=False)
    hypotension_level = db.Column(db.String(32), default="none")
    hypoxia_level = db.Column(db.String(32), default="none")
    crs_grade = db.Column(db.Integer, default=0)

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

    car_hematotox_score = db.Column(db.Integer, nullable=True)
    icaht_grade = db.Column(db.String(16), nullable=True)
    hlh_suspected = db.Column(db.String(8), nullable=True)
    hlh_note = db.Column(db.Text, nullable=True)

    b_cells_count = db.Column(db.Float, nullable=True)
    cd3_count = db.Column(db.Float, nullable=True)
    cd4_count = db.Column(db.Float, nullable=True)

    common_meds = db.Column(db.Text)
    medications_plan = db.Column(db.Text)
    free_notes = db.Column(db.Text)

    creator = db.relationship("User", foreign_keys=[created_by_id])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by_id])

    def symptom_list(self):
        return json.loads(self.symptom_flags or "[]")

    def med_list(self):
        return json.loads(self.common_meds or "[]")

    def lab_dict(self):
        return json.loads(self.labs or "{}")

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
        else:  # specialist / admin can also search by center
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


def apply_entry_fields(e, f):
    """Populate an Entry's clinical fields from submitted form data.
    Shared between creating a new entry and editing one sent back for changes,
    so both paths stay in sync."""
    symptom_flags = f.getlist("symptom_flags")
    common_meds = f.getlist("common_meds")
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

    e.cns_status, e.hmf_status = f.get("cns_status"), f.get("hmf_status")
    e.cranial_nerves_status = f.get("cranial_nerves_status")
    e.neck_rigidity, e.fnd_present = f.get("neck_rigidity"), f.get("fnd_present")
    e.handwriting_normal = f.get("handwriting_normal")
    e.cvs_status, e.resp_status = f.get("cvs_status"), f.get("resp_status")
    e.abd_status, e.splenomegaly = f.get("abd_status"), f.get("splenomegaly")
    e.exam_note = f.get("exam_note")

    e.labs = json.dumps(labs)

    e.assessment_date = _parse_date(f.get("assessment_date"))
    e.bm_blast_pct = opt_float("bm_blast_pct")
    e.bm_mrd_status = f.get("bm_mrd_status") or None
    e.csf_status = f.get("csf_status") or None
    e.ctg_status = f.get("ctg_status") or None
    e.flow_mrd_status = f.get("flow_mrd_status") or None

    e.apheresis_time = f.get("apheresis_time")
    e.apheresis_outcome = f.get("apheresis_outcome") or None
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

    e.car_hematotox_score = opt_int("car_hematotox_score")
    e.icaht_grade = f.get("icaht_grade") or None
    e.hlh_suspected = f.get("hlh_suspected") or None
    e.hlh_note = f.get("hlh_note")

    e.b_cells_count = opt_float("b_cells_count")
    e.cd3_count = opt_float("cd3_count")
    e.cd4_count = opt_float("cd4_count")

    e.common_meds = json.dumps(common_meds)
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
        common_meds=COMMON_MEDS, icaht_grades=ICAHT_GRADES,
        disease_status_options=DISEASE_STATUS_OPTIONS,
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
        common_meds=COMMON_MEDS, icaht_grades=ICAHT_GRADES,
        disease_status_options=DISEASE_STATUS_OPTIONS,
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


def ensure_schema():
    """Small self-healing migration: db.create_all() only creates tables
    that don't exist yet, it won't add a new column to a table that's
    already live (e.g. on Render). This patches that gap for simple
    additive changes so a redeploy doesn't crash on an old database."""
    inspector = inspect(db.engine)
    if "user" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("user")}
        if "active" not in existing_cols:
            with db.engine.connect() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN active BOOLEAN DEFAULT TRUE'))
                conn.commit()


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
