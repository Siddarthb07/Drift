"""
HealthTracker v5 — Main Flask Application
"""
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3, os, numpy as np, datetime, bcrypt, json, io, csv
from risk_calculators import (
    pooled_cohort_cvd_10yr, findrisc_diabetes, cancer_lifestyle_risk,
    estimate_health_age, classify_lab, LAB_REFS
)
from requests_oauthlib import OAuth2Session

DB = "users.db"
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production-32chars+")

# ─── OAuth config ────────────────────────────────────────────
OAUTH_CFG = {
    "fitbit": {
        "client_id":     os.getenv("FITBIT_CLIENT_ID"),
        "client_secret": os.getenv("FITBIT_CLIENT_SECRET"),
        "auth_uri":  "https://www.fitbit.com/oauth2/authorize",
        "token_uri": "https://api.fitbit.com/oauth2/token",
        "scope": ["profile","activity","heartrate","sleep","weight"],
    },
    "googlefit": {
        "client_id":     os.getenv("GOOGLE_CLIENT_ID"),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
        "auth_uri":  "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scope": ["openid","profile","email",
                  "https://www.googleapis.com/auth/fitness.activity.read",
                  "https://www.googleapis.com/auth/fitness.heart_rate.read",
                  "https://www.googleapis.com/auth/fitness.sleep.read"],
    },
    "garmin": {
        "client_id":     os.getenv("GARMIN_CLIENT_ID"),
        "client_secret": os.getenv("GARMIN_CLIENT_SECRET"),
        "auth_uri":  "https://connect.garmin.com/oauthConfirm",
        "token_uri": "https://connectapi.garmin.com/oauth-service/oauth/token",
        "scope": [],
    },
}

# ─── DB init ─────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password BLOB NOT NULL,
        age INTEGER, sex TEXT, height REAL, weight REAL,
        waist_cm REAL,
        systolic REAL, diastolic REAL, resting_hr REAL,
        bp_medication INTEGER DEFAULT 0,
        smoking_status TEXT DEFAULT 'never',
        alcohol_per_week REAL DEFAULT 0,
        race TEXT DEFAULT 'white',
        existing_diabetes INTEGER DEFAULT 0,
        existing_cvd INTEGER DEFAULT 0,
        existing_cancer INTEGER DEFAULT 0,
        existing_asthma INTEGER DEFAULT 0,
        existing_hypertension INTEGER DEFAULT 0,
        high_glucose_history INTEGER DEFAULT 0,
        family_history_diabetes INTEGER DEFAULT 0,
        family_history_cvd INTEGER DEFAULT 0,
        family_history_cancer INTEGER DEFAULT 0,
        smartwatch TEXT,
        watch_token TEXT,
        goal_weight REAL, goal_steps INTEGER DEFAULT 8000, goal_sleep REAL DEFAULT 8.0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS daily_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        date TEXT NOT NULL,
        sleep REAL, steps INTEGER,
        sugar_drinks_ml REAL,
        fruit_servings REAL, veg_servings REAL,
        red_meat_servings REAL,
        processed_meat INTEGER DEFAULT 0,
        stress_level REAL,
        active_minutes INTEGER,
        water_ml REAL,
        notes TEXT,
        source TEXT DEFAULT 'manual',
        UNIQUE(username, date)
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS lab_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        date TEXT NOT NULL,
        total_cholesterol REAL, ldl_cholesterol REAL, hdl_cholesterol REAL,
        triglycerides REAL,
        fasting_glucose REAL, hba1c REAL,
        hs_crp REAL,
        egfr REAL, creatinine REAL,
        alt REAL, ast REAL,
        tsh REAL, vitamin_d REAL, hemoglobin REAL,
        uric_acid REAL, ferritin REAL, albumin REAL,
        notes TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS surveys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT, date TEXT, answers TEXT
    )""")

    conn.commit(); conn.close()

init_db()

# ─── Helpers ─────────────────────────────────────────────────
def hash_pw(pw):  return bcrypt.hashpw(pw.encode(), bcrypt.gensalt())
def check_pw(pw, h):
    try: return bcrypt.checkpw(pw.encode(), h)
    except: return False

def get_user(un):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        return dict(conn.execute("SELECT * FROM users WHERE username=?", (un,)).fetchone() or {})

def profile_pct(u):
    fields = ["age","sex","height","weight","waist_cm","systolic","diastolic"]
    if not u: return 0
    filled = sum(1 for f in fields if u.get(f) not in (None,"",0))
    return int(filled/len(fields)*100)

def get_daily_data(username, days=30):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM daily_log WHERE username=? ORDER BY date DESC LIMIT ?",
            (username, days)
        ).fetchall()
        return [dict(r) for r in rows] if rows else []

def get_latest_labs(username):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM lab_results WHERE username=? ORDER BY date DESC LIMIT 1",
            (username,)
        ).fetchone()
    return dict(row) if row else {}

def get_all_labs(username):
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM lab_results WHERE username=? ORDER BY date ASC",
            (username,)
        ).fetchall()
        return [dict(r) for r in rows]

def compute_daily_stats(rows):
    def mean(vals): return round(float(np.mean([v for v in vals if v is not None])),1) if any(v is not None for v in vals) else None
    sleep  = [r.get("sleep") for r in rows]
    steps  = [r.get("steps") for r in rows]
    stress = [r.get("stress_level") for r in rows]
    return {
        "avg_sleep": mean(sleep),
        "avg_steps": int(mean(steps)) if mean(steps) else None,
        "avg_stress": mean(stress),
        "sleep_score": max(0,min(100, int(100 - abs((mean(sleep) or 8)-8)*12))) if mean(sleep) else 0,
        "steps_score": min(100, int((mean(steps) or 0)/10000*100)) if mean(steps) else 0,
        "stress_score": max(0,100-int(((mean(stress) or 5)/10)*100)) if mean(stress) else 0,
    }

def compute_risk_scores(user, daily_rows, labs):
    """
    Compute evidence-based risk scores.

    GATING RULES (all three must be met before any score is shown):
      1. Profile: age, sex, height, weight filled
      2. Daily log: at least 7 entries
      3. Labs: at least one lab entry exists

    CVD additionally requires: total_cholesterol + hdl_cholesterol in labs.
    """
    results = {}

    # ── Gate 1: basic profile ────────────────────────────────
    if not all(user.get(f) for f in ["age", "sex", "height", "weight"]):
        for name in ["CVD", "Diabetes", "Cancer"]:
            results[name] = {
                "risk_pct": None, "relative_risk": None,
                "risk_category": "Profile incomplete",
                "color": "gray",
                "gate": "profile",
                "note": "Complete your profile (age, sex, height, weight) to unlock this score.",
                "source": "", "modifiable_factors": []
            }
        return results

    # ── Gate 2: minimum 7 days of daily log ──────────────────
    daily_count = len(daily_rows)
    if daily_count < 7:
        days_needed = 7 - daily_count
        for name in ["CVD", "Diabetes", "Cancer"]:
            results[name] = {
                "risk_pct": None, "relative_risk": None,
                "risk_category": f"Need {days_needed} more day{'s' if days_needed != 1 else ''} of logging",
                "color": "gray",
                "gate": "daily_log",
                "note": f"Log your daily health data for at least 7 days to enable predictions. ({daily_count}/7 days logged)",
                "source": "", "modifiable_factors": []
            }
        return results

    # ── Gate 3: at least one lab entry ───────────────────────
    has_any_lab = any(
        labs.get(k) not in (None, "", 0)
        for k in ["total_cholesterol", "ldl_cholesterol", "hdl_cholesterol",
                  "fasting_glucose", "hba1c", "hs_crp", "egfr"]
    )
    if not has_any_lab:
        for name in ["CVD", "Diabetes", "Cancer"]:
            results[name] = {
                "risk_pct": None, "relative_risk": None,
                "risk_category": "Lab results required",
                "color": "gray",
                "gate": "labs",
                "note": "Enter at least one set of lab results (cholesterol, glucose, etc.) to enable predictions.",
                "source": "", "modifiable_factors": []
            }
        return results

    # ── All gates passed — compute scores ────────────────────
    age    = float(user.get("age", 45))
    sex    = str(user.get("sex", "male")).lower()
    hm     = float(user.get("height") or 170) / 100
    weight = float(user.get("weight") or 70)
    bmi    = weight / (hm ** 2) if hm > 0 else 24
    waist  = float(user.get("waist_cm") or (94 if sex == "male" else 80))
    sbp    = float(user.get("systolic") or 120)
    smoker    = str(user.get("smoking_status", "never")) == "current"
    ex_smoker = str(user.get("smoking_status", "never")) == "ex"
    bp_meds   = bool(user.get("bp_medication"))
    diabetes  = bool(user.get("existing_diabetes"))
    has_glucose_hx = bool(user.get("high_glucose_history"))
    family_diab   = int(user.get("family_history_diabetes") or 0)
    family_cancer = bool(user.get("family_history_cancer"))
    alc   = float(user.get("alcohol_per_week") or 0)
    race  = str(user.get("race", "white")).lower()

    stats      = compute_daily_stats(daily_rows)
    avg_steps  = float(stats.get("avg_steps") or 3000)
    avg_sleep  = float(stats.get("avg_sleep") or 7)
    avg_stress = float(stats.get("avg_stress") or 5)

    def mean_col(col, default=0):
        vals = [r.get(col) for r in daily_rows if r.get(col) is not None]
        return float(np.mean(vals)) if vals else default

    active     = avg_steps >= 7500 or mean_col("active_minutes", 0) >= (150 / 7)
    red_meat   = mean_col("red_meat_servings", 2)
    processed  = mean_col("processed_meat", 0) > 0
    veg_daily  = mean_col("veg_servings", 0) >= 2 and mean_col("fruit_servings", 0) >= 1

    def safe_float(v):
        try:
            f = float(v)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None

    total_chol = safe_float(labs.get("total_cholesterol"))
    hdl_chol   = safe_float(labs.get("hdl_cholesterol"))
    fasting_gl = safe_float(labs.get("fasting_glucose"))
    hba1c      = safe_float(labs.get("hba1c"))

    # ── CVD: requires cholesterol labs ───────────────────────
    if total_chol and hdl_chol and age >= 40:
        cvd = pooled_cohort_cvd_10yr(
            age, sex, total_chol, hdl_chol, sbp,
            bp_meds, smoker, diabetes, race
        )
        if cvd:
            results["CVD"] = cvd
        else:
            results["CVD"] = {
                "risk_pct": None, "risk_category": "Age out of range (valid 40–79)",
                "color": "gray", "note": "PCE valid for ages 40–79 only.",
                "source": "ACC/AHA Pooled Cohort Equations", "modifiable_factors": []
            }
    elif not total_chol or not hdl_chol:
        results["CVD"] = {
            "risk_pct": None,
            "risk_category": "Cholesterol labs needed",
            "color": "gray",
            "gate": "labs_cholesterol",
            "note": "Enter Total Cholesterol and HDL Cholesterol in Lab Results to calculate your 10-year CVD risk.",
            "source": "ACC/AHA Pooled Cohort Equations (Goff et al., Circulation 2014)",
            "modifiable_factors": []
        }
    elif age < 40:
        results["CVD"] = {
            "risk_pct": None,
            "risk_category": "Under 40 — low absolute risk",
            "color": "green",
            "note": "ACC/AHA PCE is validated for ages 40–79. Focus on lifestyle factors.",
            "source": "ACC/AHA Pooled Cohort Equations", "modifiable_factors": []
        }

    # ── Diabetes: FINDRISC (no labs required beyond profile) ─
    diab = findrisc_diabetes(
        age, bmi, waist, sex, active, veg_daily,
        bp_meds, has_glucose_hx, family_diab
    )
    # Enhance with glucose labs if available
    if fasting_gl and fasting_gl >= 100:
        diab["note"] = (
            diab.get("note", "") +
            f" ⚠ Fasting glucose {fasting_gl} mg/dL is in the pre-diabetes range — consult your doctor."
        )
        if diab["color"] in ("green", "yellow"):
            diab["color"] = "orange"
    elif hba1c and hba1c >= 5.7:
        diab["note"] = (
            diab.get("note", "") +
            f" ⚠ HbA1c {hba1c}% is in the pre-diabetes range — consult your doctor."
        )
        if diab["color"] in ("green", "yellow"):
            diab["color"] = "orange"
    results["Diabetes"] = diab

    # ── Cancer: lifestyle relative risk ──────────────────────
    canc = cancer_lifestyle_risk(
        age, bmi, sex, smoker, ex_smoker, alc,
        active, red_meat, processed, veg_daily, family_cancer
    )
    results["Cancer"] = canc

    # ── Health Age ────────────────────────────────────────────
    ha = estimate_health_age(
        age, bmi, sbp, smoker, avg_sleep, avg_steps, avg_stress,
        total_chol, fasting_gl, hba1c
    )
    results["_health_age"] = ha
    results["_daily_count"] = daily_count

    return results

# ─── Auth ────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        un = request.form.get("username","").strip()
        pw = request.form.get("password","")
        if not un or not pw:
            flash("Username and password required.","error"); return redirect(url_for("register"))
        try:
            with sqlite3.connect(DB) as conn:
                conn.execute("INSERT INTO users (username,password) VALUES (?,?)", (un, hash_pw(pw)))
            flash("Account created — please log in.","success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.","error")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        un = request.form.get("username","").strip()
        pw = request.form.get("password","")
        with sqlite3.connect(DB) as conn:
            row = conn.execute("SELECT password FROM users WHERE username=?", (un,)).fetchone()
        if row and check_pw(pw, row[0]):
            session["username"] = un
            user = get_user(un)
            if profile_pct(user) < 60:
                return redirect(url_for("onboarding", step=2))
            return redirect(url_for("dashboard"))
        flash("Invalid credentials.","error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); flash("Logged out.","info"); return redirect(url_for("home"))

# ─── Onboarding ──────────────────────────────────────────────
@app.route("/onboarding/<int:step>", methods=["GET","POST"])
def onboarding(step):
    if "username" not in session: return redirect(url_for("login"))
    un = session["username"]
    user = get_user(un)
    if request.method == "POST":
        with sqlite3.connect(DB) as conn:
            if step == 2:
                conn.execute(
                    "UPDATE users SET age=?,sex=?,height=?,weight=?,waist_cm=? WHERE username=?",
                    (request.form.get("age"), request.form.get("sex"),
                     request.form.get("height"), request.form.get("weight"),
                     request.form.get("waist_cm"), un))
            elif step == 3:
                conn.execute(
                    "UPDATE users SET systolic=?,diastolic=?,resting_hr=?,bp_medication=?,smoking_status=?,alcohol_per_week=? WHERE username=?",
                    (request.form.get("systolic"), request.form.get("diastolic"),
                     request.form.get("resting_hr"),
                     1 if request.form.get("bp_medication") else 0,
                     request.form.get("smoking_status","never"),
                     request.form.get("alcohol_per_week") or 0, un))
            elif step == 4:
                fields = ["existing_diabetes","existing_cvd","existing_cancer",
                          "existing_asthma","existing_hypertension","high_glucose_history",
                          "family_history_diabetes","family_history_cvd","family_history_cancer"]
                vals = [1 if request.form.get(f) in ("on","1","true") else 0 for f in fields]
                conn.execute(
                    f"UPDATE users SET {','.join(f+'=?' for f in fields)} WHERE username=?",
                    (*vals, un))
        if step < 4:
            return redirect(url_for("onboarding", step=step+1))
        flash("Profile complete — you can now see your risk scores!","success")
        return redirect(url_for("dashboard"))
    return render_template(f"onboarding_step{step}.html", user=user, step=step)

# ─── Dashboard ───────────────────────────────────────────────
@app.route("/dashboard", methods=["GET","POST"])
def dashboard():
    if "username" not in session: return redirect(url_for("login"))
    un = session["username"]
    if request.method == "POST":
        today = datetime.date.today().isoformat()
        vals = {
            "sleep":             request.form.get("sleep") or None,
            "steps":             request.form.get("steps") or None,
            "sugar_drinks_ml":   request.form.get("sugar_drinks_ml") or None,
            "fruit_servings":    request.form.get("fruit_servings") or None,
            "veg_servings":      request.form.get("veg_servings") or None,
            "red_meat_servings": request.form.get("red_meat_servings") or None,
            "processed_meat":    1 if request.form.get("processed_meat") else 0,
            "stress_level":      request.form.get("stress_level") or None,
            "active_minutes":    request.form.get("active_minutes") or None,
            "water_ml":          request.form.get("water_ml") or None,
            "notes":             request.form.get("notes") or None,
        }
        try:
            with sqlite3.connect(DB) as conn:
                conn.execute("""
                    INSERT INTO daily_log (username,date,sleep,steps,sugar_drinks_ml,
                        fruit_servings,veg_servings,red_meat_servings,processed_meat,
                        stress_level,active_minutes,water_ml,notes)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(username,date) DO UPDATE SET
                        sleep=excluded.sleep, steps=excluded.steps,
                        sugar_drinks_ml=excluded.sugar_drinks_ml,
                        fruit_servings=excluded.fruit_servings,
                        veg_servings=excluded.veg_servings,
                        red_meat_servings=excluded.red_meat_servings,
                        processed_meat=excluded.processed_meat,
                        stress_level=excluded.stress_level,
                        active_minutes=excluded.active_minutes,
                        water_ml=excluded.water_ml, notes=excluded.notes
                """, (un, today, *vals.values()))
            flash("Entry saved!","success")
        except Exception as e:
            flash(f"Error saving entry: {e}","error")
        return redirect(url_for("dashboard"))

    user = get_user(un)
    daily = get_daily_data(un, 30)
    labs  = get_latest_labs(un)

    # Chart data (chronological order for chart)
    daily_rev = list(reversed(daily))
    chart = {
        "dates":  [d["date"]               for d in daily_rev],
        "sleep":  [d.get("sleep")          for d in daily_rev],
        "steps":  [d.get("steps")          for d in daily_rev],
        "stress": [d.get("stress_level")   for d in daily_rev],
        "active": [d.get("active_minutes") for d in daily_rev],
    }

    stats = compute_daily_stats(daily)

    goals = {
        "steps": int(user.get("goal_steps") or 8000),
        "sleep": float(user.get("goal_sleep") or 8.0),
    }

    # Always compute — gating is handled inside compute_risk_scores
    risk = compute_risk_scores(user, daily, labs)

    # Only classify labs that have a real positive numeric value
    lab_status = {}
    for k in LAB_REFS:
        raw = labs.get(k)
        if raw in (None, "", 0):
            continue
        try:
            fval = float(raw)
            if fval <= 0:
                continue
            lab_status[k] = classify_lab(k, fval, str(user.get("sex", "male")))
        except (TypeError, ValueError):
            continue

    daily_count = len(daily)

    return render_template("dashboard.html",
        user=user, chart=chart, stats=stats,
        risk=risk, labs=labs, lab_status=lab_status,
        goals=goals, profile_pct=profile_pct(user),
        daily_count=daily_count,
        today=datetime.date.today().isoformat()
    )

# ─── Lab Results ─────────────────────────────────────────────
@app.route("/labs", methods=["GET","POST"])
def labs():
    if "username" not in session: return redirect(url_for("login"))
    un = session["username"]
    if request.method == "POST":
        date = request.form.get("date") or datetime.date.today().isoformat()
        lab_fields = ["total_cholesterol","ldl_cholesterol","hdl_cholesterol",
                      "triglycerides","fasting_glucose","hba1c","hs_crp",
                      "egfr","creatinine","alt","ast","tsh","vitamin_d",
                      "hemoglobin","uric_acid","ferritin","albumin"]
        vals = [request.form.get(f) or None for f in lab_fields]
        notes = request.form.get("notes") or None
        with sqlite3.connect(DB) as conn:
            conn.execute(
                f"INSERT INTO lab_results (username,date,{','.join(lab_fields)},notes) VALUES (?,?,{','.join(['?']*len(lab_fields))},?)",
                (un, date, *vals, notes)
            )
        flash("Lab results saved!","success")
        return redirect(url_for("labs"))

    user = get_user(un)
    all_labs = get_all_labs(un)
    latest   = all_labs[-1] if all_labs else {}
    sex = str(user.get("sex", "male")).lower()

    lab_status = {}
    for k in LAB_REFS:
        raw = latest.get(k)
        if raw in (None, "", 0):
            continue
        try:
            fval = float(raw)
            if fval <= 0:
                continue
            lab_status[k] = {
                **classify_lab(k, fval, sex),
                "value": raw,
                "unit": LAB_REFS.get(k, {}).get("unit", "")
            }
        except (TypeError, ValueError):
            continue
    # Build timeline data for charts
    lab_timeline = {
        "dates": [r["date"] for r in all_labs],
        "total_cholesterol": [r.get("total_cholesterol") for r in all_labs],
        "ldl_cholesterol":   [r.get("ldl_cholesterol")   for r in all_labs],
        "hdl_cholesterol":   [r.get("hdl_cholesterol")   for r in all_labs],
        "fasting_glucose":   [r.get("fasting_glucose")   for r in all_labs],
        "hba1c":             [r.get("hba1c")             for r in all_labs],
        "hs_crp":            [r.get("hs_crp")            for r in all_labs],
    }
    return render_template("labs.html",
        user=user, lab_status=lab_status, lab_refs=LAB_REFS,
        all_labs=all_labs, latest=latest,
        lab_timeline=lab_timeline, today=datetime.date.today().isoformat()
    )

# ─── Profile ─────────────────────────────────────────────────
@app.route("/profile", methods=["GET","POST"])
def profile():
    if "username" not in session: return redirect(url_for("login"))
    un = session["username"]
    if request.method == "POST":
        fields = ["age","sex","height","weight","waist_cm","systolic","diastolic",
                  "resting_hr","bp_medication","smoking_status","alcohol_per_week","race",
                  "existing_diabetes","existing_cvd","existing_cancer","existing_asthma",
                  "existing_hypertension","high_glucose_history",
                  "family_history_diabetes","family_history_cvd","family_history_cancer",
                  "goal_weight","goal_steps","goal_sleep"]
        vals = []
        bool_fields = {"bp_medication","existing_diabetes","existing_cvd","existing_cancer",
                       "existing_asthma","existing_hypertension","high_glucose_history",
                       "family_history_diabetes","family_history_cvd","family_history_cancer"}
        for f in fields:
            v = request.form.get(f)
            if f in bool_fields:
                vals.append(1 if v in ("on","1","true") else 0)
            else:
                vals.append(v if v not in ("","None") else None)
        with sqlite3.connect(DB) as conn:
            conn.execute(f"UPDATE users SET {','.join(f+'=?' for f in fields)} WHERE username=?", (*vals, un))
        flash("Profile updated!","success")
        return redirect(url_for("profile"))
    user = get_user(un)
    return render_template("profile.html", user=user, pct=profile_pct(user))

# ─── Smartwatch ──────────────────────────────────────────────
@app.route("/smartwatch", methods=["GET","POST"])
def smartwatch():
    if "username" not in session: return redirect(url_for("login"))
    un = session["username"]
    user = get_user(un)
    if request.method == "POST":
        provider = request.form.get("provider","")
        token    = request.form.get("watch_token","")
        with sqlite3.connect(DB) as conn:
            conn.execute("UPDATE users SET smartwatch=?,watch_token=? WHERE username=?", (provider, token, un))
        flash("Watch settings saved.","success")
        return redirect(url_for("smartwatch"))

    # Check which env vars are configured
    configured = {p: bool(cfg.get("client_id")) for p,cfg in OAUTH_CFG.items()}
    return render_template("smartwatch.html", user=user, configured=configured)

@app.route("/connect/<provider>")
def oauth_connect(provider):
    if "username" not in session: return redirect(url_for("login"))
    cfg = OAUTH_CFG.get(provider,{})
    if not cfg.get("client_id"):
        flash(f"'{provider}' OAuth is not configured on this server. See README for setup steps.","error")
        return redirect(url_for("smartwatch"))
    cb = request.url_root.rstrip("/") + url_for("oauth_callback", provider=provider)
    oauth = OAuth2Session(cfg["client_id"], redirect_uri=cb, scope=cfg.get("scope",[]))
    auth_url, state = oauth.authorization_url(cfg["auth_uri"])
    session[f"oauth_state_{provider}"] = state
    return redirect(auth_url)

@app.route("/oauth/callback/<provider>")
def oauth_callback(provider):
    if "username" not in session: return redirect(url_for("login"))
    cfg = OAUTH_CFG.get(provider,{})
    if not cfg:
        flash("Unknown provider.","error"); return redirect(url_for("smartwatch"))
    cb = request.url_root.rstrip("/") + url_for("oauth_callback", provider=provider)
    oauth = OAuth2Session(cfg["client_id"], state=session.get(f"oauth_state_{provider}"), redirect_uri=cb)
    try:
        token = oauth.fetch_token(cfg["token_uri"], client_secret=cfg["client_secret"], authorization_response=request.url)
        with sqlite3.connect(DB) as conn:
            conn.execute("UPDATE users SET watch_token=?,smartwatch=? WHERE username=?",
                         (json.dumps(token), provider, session["username"]))
        flash(f"{provider.capitalize()} connected successfully!","success")
    except Exception as e:
        flash(f"OAuth failed: {e}. Ensure redirect URI is registered in the provider's developer console.","error")
    return redirect(url_for("smartwatch"))

@app.route("/api/sync_watch")
def sync_watch():
    """
    Real watch sync endpoint.
    Currently supports Fitbit (when credentials are set).
    Returns JSON with synced data and saves to daily_log.
    """
    if "username" not in session:
        return jsonify({"error":"Not logged in"}), 401
    un = session["username"]
    user = get_user(un)
    provider = user.get("smartwatch","")
    token_raw = user.get("watch_token","")

    if not provider or not token_raw:
        return jsonify({"error":"No watch connected","tip":"Connect a watch in the Smartwatch page first."}), 400

    try:
        token = json.loads(token_raw)
    except:
        return jsonify({"error":"Invalid token stored. Please re-connect your watch."}), 400

    cfg = OAUTH_CFG.get(provider,{})
    if not cfg.get("client_id"):
        return jsonify({"error":f"{provider} credentials not configured on server."}), 400

    try:
        oauth = OAuth2Session(cfg["client_id"], token=token)
        today = datetime.date.today().isoformat()
        synced = {}

        if provider == "fitbit":
            # Fitbit REST API v1
            r_act = oauth.get(f"https://api.fitbit.com/1/user/-/activities/date/{today}.json")
            r_slp = oauth.get(f"https://api.fitbit.com/1.2/user/-/sleep/date/{today}.json")
            if r_act.status_code == 200:
                act = r_act.json()
                synced["steps"] = act.get("summary",{}).get("steps")
                synced["active_minutes"] = act.get("summary",{}).get("veryActiveMinutes",0) + act.get("summary",{}).get("fairlyActiveMinutes",0)
            if r_slp.status_code == 200:
                slp = r_slp.json()
                mins = slp.get("summary",{}).get("totalMinutesAsleep",0)
                synced["sleep"] = round(mins/60, 1) if mins else None

        elif provider == "googlefit":
            # Google Fit REST API — summary for today
            now_ms = int(datetime.datetime.now().timestamp() * 1000)
            start_ms = int(datetime.datetime.combine(datetime.date.today(), datetime.time.min).timestamp() * 1000)
            body = {
                "aggregateBy": [{"dataTypeName":"com.google.step_count.delta"},
                                 {"dataTypeName":"com.google.active_minutes"}],
                "bucketByTime": {"durationMillis": 86400000},
                "startTimeMillis": start_ms,
                "endTimeMillis": now_ms
            }
            r = oauth.post("https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate", json=body)
            if r.status_code == 200:
                for bucket in r.json().get("bucket",[]):
                    for ds in bucket.get("dataset",[]):
                        for pt in ds.get("point",[]):
                            for val in pt.get("value",[]):
                                if "step_count" in ds.get("dataSourceId",""):
                                    synced["steps"] = synced.get("steps",0) + val.get("intVal",0)
                                elif "active_minutes" in ds.get("dataSourceId",""):
                                    synced["active_minutes"] = synced.get("active_minutes",0) + val.get("intVal",0)

        if synced:
            with sqlite3.connect(DB) as conn:
                conn.execute("""
                    INSERT INTO daily_log (username,date,steps,sleep,active_minutes,source)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(username,date) DO UPDATE SET
                        steps=COALESCE(excluded.steps, steps),
                        sleep=COALESCE(excluded.sleep, sleep),
                        active_minutes=COALESCE(excluded.active_minutes, active_minutes),
                        source='watch'
                """, (un, today, synced.get("steps"), synced.get("sleep"), synced.get("active_minutes"), provider))
            return jsonify({"ok": True, "synced": synced, "date": today})
        return jsonify({"ok": False, "note":"No data returned from provider for today."})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/import_csv", methods=["POST"])
def import_csv():
    """
    Import Apple Health or generic CSV export.
    Expected columns: date, sleep, steps, active_minutes (optional others)
    Apple Health: use the Summary CSV from Health app > Export Health Data
    """
    if "username" not in session: return redirect(url_for("login"))
    f = request.files.get("csv_file")
    if not f: flash("No file uploaded.","error"); return redirect(url_for("smartwatch"))
    try:
        content = f.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))
        rows_inserted = 0
        with sqlite3.connect(DB) as conn:
            for row in reader:
                date = row.get("date","").strip()
                if not date: continue
                conn.execute("""
                    INSERT OR REPLACE INTO daily_log
                    (username,date,sleep,steps,active_minutes,source)
                    VALUES (?,?,?,?,?,?)
                """, (session["username"], date,
                      row.get("sleep") or None,
                      row.get("steps") or None,
                      row.get("active_minutes") or None,
                      "csv_import"))
                rows_inserted += 1
        flash(f"Imported {rows_inserted} days from CSV.","success")
    except Exception as e:
        flash(f"Import failed: {e}","error")
    return redirect(url_for("smartwatch"))

# ─── Survey ──────────────────────────────────────────────────
@app.route("/survey", methods=["GET","POST"])
def survey():
    if "username" not in session: return redirect(url_for("login"))
    if request.method == "POST":
        with sqlite3.connect(DB) as conn:
            conn.execute("INSERT INTO surveys (username,date,answers) VALUES (?,?,?)",
                (session["username"], datetime.date.today().isoformat(), json.dumps(request.form.to_dict())))
        flash("Survey submitted!","success")
        return redirect(url_for("dashboard"))
    return render_template("survey.html")

# ─── API endpoints ───────────────────────────────────────────
@app.route("/api/daily_history")
def api_daily_history():
    if "username" not in session: return jsonify({}),401
    return jsonify(get_daily_data(session["username"], 90))

@app.route("/api/risk_summary")
def api_risk_summary():
    if "username" not in session: return jsonify({}),401
    un = session["username"]
    user = get_user(un)
    daily = get_daily_data(un)
    labs  = get_latest_labs(un)
    risk  = compute_risk_scores(user, daily, labs)
    return jsonify(risk)

if __name__ == "__main__":
    app.run(debug=True, port=5001)
