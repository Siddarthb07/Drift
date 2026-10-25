"""
Drift — Flask application (claim-honest risk disclosure + wearables).
"""
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3, os, numpy as np, datetime, bcrypt, json, io, csv
from risk_calculators import classify_lab, LAB_REFS
from risk_engine import compute_risk_scores
import oauth_watch
from token_vault import seal as seal_token, open_token

DB = "users.db"
app = Flask(__name__)
_DEFAULT_SECRET = "change-me-in-production-32chars+"
app.secret_key = os.getenv("SECRET_KEY", _DEFAULT_SECRET)
STUDY_INSECURE = app.secret_key == _DEFAULT_SECRET
OAUTH_CFG = oauth_watch.oauth_config()

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
        race TEXT,
        sex_for_equation TEXT,
        region TEXT DEFAULT 'global',
        prefer_pce INTEGER DEFAULT 0,
        statin INTEGER DEFAULT 0,
        consent_version TEXT,
        consent_at TEXT,
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
    _migrate_db()


def _migrate_db():
    """Add columns introduced for global / consent / equation sex."""
    cols = {
        "sex_for_equation": "TEXT",
        "region": "TEXT DEFAULT 'global'",
        "prefer_pce": "INTEGER DEFAULT 0",
        "statin": "INTEGER DEFAULT 0",
        "consent_version": "TEXT",
        "consent_at": "TEXT",
    }
    with sqlite3.connect(DB) as conn:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for name, decl in cols.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {name} {decl}")
        # Drop silent default: if race was 'white' from old DEFAULT and never set intentionally,
        # leave as-is; new users get NULL race until chosen.

init_db()


def ui_mode() -> str:
    m = (request.args.get("mode") or session.get("ui_mode") or "honest").lower()
    if m in ("honest", "baseline"):
        session["ui_mode"] = m
        return m
    return "honest"

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

# compute_risk_scores imported from risk_engine (claim-honest default).

# ─── Auth ────────────────────────────────────────────────────
@app.route("/")
def home():
    return render_template("home.html")


@app.route("/consent", methods=["GET", "POST"])
def consent():
    """Pre-onboarding epistemic + privacy consent (P11)."""
    if "username" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        if not request.form.get("accept_limits") or not request.form.get("accept_data"):
            flash("Please acknowledge both statements to continue.", "error")
            return redirect(url_for("consent"))
        with sqlite3.connect(DB) as conn:
            conn.execute(
                "UPDATE users SET consent_version=?, consent_at=? WHERE username=?",
                ("v1-facct", datetime.datetime.utcnow().isoformat(), session["username"]),
            )
        flash("Consent recorded. You can export or delete your data anytime from Profile.", "success")
        return redirect(url_for("onboarding", step=2))
    return render_template("consent.html")

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
            flash("Account created — log in, then review consent before health data entry.","success")
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
            if not user.get("consent_version"):
                return redirect(url_for("consent"))
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
    if not user.get("consent_version"):
        return redirect(url_for("consent"))
    if request.method == "POST":
        with sqlite3.connect(DB) as conn:
            if step == 2:
                sex = request.form.get("sex")
                sex_eq = request.form.get("sex_for_equation") or (
                    sex if sex in ("male", "female") else ""
                )
                conn.execute(
                    "UPDATE users SET age=?,sex=?,sex_for_equation=?,height=?,weight=?,waist_cm=?,race=?,region=? WHERE username=?",
                    (request.form.get("age"), sex, sex_eq or None,
                     request.form.get("height"), request.form.get("weight"),
                     request.form.get("waist_cm") or None,
                     request.form.get("race") or None,
                     request.form.get("region") or "global",
                     un))
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

    mode = ui_mode()
    risk = compute_risk_scores(user, daily, labs, mode=mode, username=un)

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
        today=datetime.date.today().isoformat(),
        ui_mode=mode,
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
        fields = ["age","sex","sex_for_equation","height","weight","waist_cm","systolic","diastolic",
                  "resting_hr","bp_medication","smoking_status","alcohol_per_week","race","region",
                  "prefer_pce","statin",
                  "existing_diabetes","existing_cvd","existing_cancer","existing_asthma",
                  "existing_hypertension","high_glucose_history",
                  "family_history_diabetes","family_history_cvd","family_history_cancer",
                  "goal_weight","goal_steps","goal_sleep"]
        vals = []
        bool_fields = {"bp_medication","prefer_pce","statin","existing_diabetes","existing_cvd","existing_cancer",
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

    return render_template(
        "smartwatch.html",
        user=user,
        configured=oauth_watch.provider_status(),
        redirect_hint=request.url_root.rstrip("/") + "/oauth/callback/<provider>",
    )

@app.route("/connect/<provider>")
def oauth_connect(provider):
    if "username" not in session: return redirect(url_for("login"))
    auth_url, err = oauth_watch.begin_auth(provider)
    if err:
        flash(err, "error")
        return redirect(url_for("smartwatch"))
    return redirect(auth_url)

@app.route("/oauth/callback/<provider>")
def oauth_callback(provider):
    if "username" not in session: return redirect(url_for("login"))
    token, err = oauth_watch.finish_auth(provider)
    if err:
        flash(err, "error")
        return redirect(url_for("smartwatch"))
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "UPDATE users SET watch_token=?,smartwatch=? WHERE username=?",
            (seal_token(json.dumps(token)), provider, session["username"]),
        )
    flash(f"{provider} connected successfully.", "success")
    return redirect(url_for("smartwatch"))

@app.route("/api/sync_watch")
def sync_watch():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401
    un = session["username"]
    user = get_user(un)
    provider = user.get("smartwatch", "")
    token_raw = user.get("watch_token", "")
    if not provider or not token_raw:
        return jsonify({"error": "No watch connected", "tip": "Connect Fitbit or Google Fit first."}), 400
    try:
        token = json.loads(open_token(token_raw))
    except Exception:
        return jsonify({"error": "Invalid token stored. Please re-connect your watch."}), 400

    synced, updated_token, err = oauth_watch.sync_provider(provider, token)
    if updated_token:
        with sqlite3.connect(DB) as conn:
            conn.execute(
                "UPDATE users SET watch_token=? WHERE username=?",
                (seal_token(json.dumps(updated_token)), un),
            )
    if err:
        return jsonify({"error": err}), 400
    today = datetime.date.today().isoformat()
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
            """, (un, today, synced.get("steps"), synced.get("sleep"),
                  synced.get("active_minutes"), provider))
        return jsonify({"ok": True, "synced": synced, "date": today})
    return jsonify({"ok": False, "note": "No data returned from provider for today."})

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
    risk  = compute_risk_scores(user, daily, labs, mode=ui_mode(), username=un)
    return jsonify(risk)


@app.route("/api/export")
def api_export():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401
    un = session["username"]
    user = get_user(un)
    # Strip secrets
    user = {k: v for k, v in user.items() if k not in ("password", "watch_token")}
    payload = {
        "user": user,
        "daily_log": get_daily_data(un, 3650),
        "labs": get_all_labs(un),
        "exported_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    return jsonify(payload)


@app.route("/api/delete_account", methods=["POST"])
def api_delete_account():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401
    un = session["username"]
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM daily_log WHERE username=?", (un,))
        conn.execute("DELETE FROM lab_results WHERE username=?", (un,))
        conn.execute("DELETE FROM surveys WHERE username=?", (un,))
        conn.execute("DELETE FROM users WHERE username=?", (un,))
    session.clear()
    flash("Account and health data deleted.", "info")
    return redirect(url_for("home"))


@app.route("/model-cards")
def model_cards():
    from disclosure import load_claims
    return render_template("model_cards.html", claims=load_claims().get("claims", {}))


@app.route("/study/prolific")
def study_prolific():
    """Prolific vignette survey. Arm assigned server-side (session); ignore client ?arm=."""
    path = os.path.join(os.path.dirname(__file__), "study", "prolific_survey.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _study_db_init():
    with sqlite3.connect(DB) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS study_assignments (
                token TEXT PRIMARY KEY,
                arm TEXT NOT NULL,
                prolific_id TEXT,
                created_at TEXT NOT NULL
            )"""
        )


@app.route("/study/assign", methods=["GET"])
def study_assign():
    """Server-side assignment stored in SQLite (opaque token only to client)."""
    import random
    if STUDY_INSECURE:
        return jsonify({
            "error": "set_SECRET_KEY",
            "hint": "Export a strong SECRET_KEY before fielding; default key refuses study assign.",
        }), 503
    _study_db_init()
    token = session.get("study_token")
    if token:
        with sqlite3.connect(DB) as conn:
            row = conn.execute(
                "SELECT arm FROM study_assignments WHERE token=?", (token,)
            ).fetchone()
        if row:
            return jsonify({"token": token, "fixtures_url": "/study/fixtures"})
    # Balance on assignments (not only completions)
    with sqlite3.connect(DB) as conn:
        n_h = conn.execute(
            "SELECT COUNT(*) FROM study_assignments WHERE arm='honest'"
        ).fetchone()[0]
        n_b = conn.execute(
            "SELECT COUNT(*) FROM study_assignments WHERE arm='baseline'"
        ).fetchone()[0]
    if n_h < n_b:
        arm = "honest"
    elif n_b < n_h:
        arm = "baseline"
    else:
        arm = random.choice(["honest", "baseline"])
    token = os.urandom(16).hex()
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO study_assignments(token, arm, created_at) VALUES (?,?,?)",
            (token, arm, datetime.datetime.utcnow().isoformat() + "Z"),
        )
    session["study_token"] = token
    # Do NOT put arm in the session cookie
    return jsonify({"token": token, "fixtures_url": "/study/fixtures"})


def _arm_for_token(token: str):
    if not token:
        return None
    _study_db_init()
    with sqlite3.connect(DB) as conn:
        row = conn.execute(
            "SELECT arm FROM study_assignments WHERE token=?", (token,)
        ).fetchone()
    return row[0] if row else None


@app.route("/study/fixtures")
def study_fixtures():
    """Return participant cards for the assigned arm only (no arm field in payload)."""
    token = request.args.get("token") or session.get("study_token")
    arm = _arm_for_token(token)
    if arm not in ("honest", "baseline"):
        return jsonify({"error": "assign_first"}), 400
    path = os.path.join(os.path.dirname(__file__), "study", "rendered_fixtures.json")
    if not os.path.exists(path):
        return jsonify({"error": "run scripts/render_study_fixtures.py first"}), 503
    data = json.loads(open(path, encoding="utf-8").read())
    cards = []
    for fx in data.get("fixtures", []):
        view = fx.get(arm) or {}
        cards.append({
            "id": fx["id"],
            "title": fx.get("title"),
            "profile": fx.get("profile"),
            "cvd": view.get("cvd"),
            "diab": view.get("diab"),
            "cancer": view.get("cancer"),
            "hero": view.get("hero"),
            "foot": view.get("foot"),
            "heroClass": view.get("heroClass") or "",
        })
    order_key = f"study_order_{token}"
    if order_key not in session:
        import random
        order = list(range(len(cards)))
        random.shuffle(order)
        session[order_key] = order
    order = session[order_key]
    ordered = [cards[i] for i in order if i < len(cards)]
    return jsonify({"cards": ordered, "token": token})


@app.route("/study/collect", methods=["POST"])
def study_collect():
    """Append-only collector for vignette study JSON (no PHI; Prolific ID only)."""
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        return jsonify({"ok": False, "error": "invalid_json"}), 400
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "expected_object"}), 400
    token = payload.get("token") or session.get("study_token")
    arm = _arm_for_token(token)
    if arm not in ("honest", "baseline"):
        return jsonify({"ok": False, "error": "no_assignment"}), 400
    allowed = {
        "completion_code", "pid", "prolific_id", "responses",
        "started", "finished", "consent_version", "attention_ok", "token",
    }
    clean = {k: payload[k] for k in payload if k in allowed}
    clean["arm"] = arm  # server truth from SQLite
    clean["received_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    clean["remote"] = (request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64]
    # Bind prolific_id on first completion; reject arm re-roll via new token for same pid later (soft)
    pid = clean.get("prolific_id") or clean.get("pid")
    if pid:
        _study_db_init()
        with sqlite3.connect(DB) as conn:
            conn.execute(
                "UPDATE study_assignments SET prolific_id=? WHERE token=? AND (prolific_id IS NULL OR prolific_id='')",
                (pid, token),
            )
    out_dir = os.path.join(os.path.dirname(__file__), "study", "results")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "responses.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(clean, ensure_ascii=False) + "\n")
    return jsonify({"ok": True, "stored": True})


@app.route("/study/status")
def study_status():
    path = os.path.join(os.path.dirname(__file__), "study", "results", "responses.jsonl")
    n = n_h = n_b = 0
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                n += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("arm") == "honest":
                    n_h += 1
                elif row.get("arm") == "baseline":
                    n_b += 1
    return jsonify({"n_submissions": n, "n_honest": n_h, "n_baseline": n_b, "collector": "/study/collect"})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
