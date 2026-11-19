import math
import os
import sqlite3
from datetime import datetime
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "bloodlink.db")

app = Flask(__name__)
app.secret_key = os.environ.get("BLOODLINK_SECRET", "change-this-secret-before-deployment")
BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','hospital','donor','staff')),
        phone TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS hospitals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        hospital_name TEXT NOT NULL,
        address TEXT NOT NULL,
        city TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        verified INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS donors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        blood_group TEXT NOT NULL,
        city TEXT NOT NULL,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        available INTEGER NOT NULL DEFAULT 1,
        last_donation TEXT DEFAULT '',
        consent INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS stock (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hospital_id INTEGER NOT NULL REFERENCES hospitals(id) ON DELETE CASCADE,
        blood_group TEXT NOT NULL,
        units INTEGER NOT NULL DEFAULT 0,
        threshold INTEGER NOT NULL DEFAULT 5,
        updated_at TEXT NOT NULL,
        UNIQUE(hospital_id, blood_group)
    );
    CREATE TABLE IF NOT EXISTS stock_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hospital_id INTEGER NOT NULL,
        blood_group TEXT NOT NULL,
        old_units INTEGER NOT NULL,
        new_units INTEGER NOT NULL,
        reason TEXT NOT NULL,
        updated_by INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS emergencies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
        blood_group TEXT NOT NULL,
        units INTEGER NOT NULL,
        priority TEXT NOT NULL,
        radius_km REAL NOT NULL,
        needed_at TEXT NOT NULL,
        notes TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'Open',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS donor_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emergency_id INTEGER NOT NULL REFERENCES emergencies(id) ON DELETE CASCADE,
        donor_id INTEGER NOT NULL REFERENCES donors(id),
        status TEXT NOT NULL DEFAULT 'Pending',
        responded_at TEXT DEFAULT '',
        UNIQUE(emergency_id, donor_id)
    );
    CREATE TABLE IF NOT EXISTS transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
        to_hospital_id INTEGER NOT NULL REFERENCES hospitals(id),
        blood_group TEXT NOT NULL,
        units INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        link TEXT DEFAULT '',
        read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    """)
    # Demo users are inserted only on a fresh database.
    if not con.execute("SELECT id FROM users LIMIT 1").fetchone():
        cur = con.execute("INSERT INTO users(name,email,password,role,phone,created_at) VALUES(?,?,?,?,?,?)",
            ("BloodLink Admin", "admin@bloodlink.local", generate_password_hash("Admin@123"), "admin", "", now()))
        admin_id = cur.lastrowid
        cur = con.execute("INSERT INTO users(name,email,password,role,phone,created_at) VALUES(?,?,?,?,?,?)",
            ("Demo Hospital Manager", "hospital@bloodlink.local", generate_password_hash("Hospital@123"), "hospital", "9000000001", now()))
        huser = cur.lastrowid
        cur = con.execute("""INSERT INTO hospitals(user_id,hospital_name,address,city,latitude,longitude,verified)
                             VALUES(?,?,?,?,?,?,1)""",
            (huser, "Central Care Hospital", "Demo Road", "Chennai", 13.0827, 80.2707))
        hid = cur.lastrowid
        for bg, units in zip(BLOOD_GROUPS, [14, 4, 9, 2, 7, 1, 12, 0]):
            con.execute("INSERT INTO stock(hospital_id,blood_group,units,threshold,updated_at) VALUES(?,?,?,?,?)",
                        (hid, bg, units, 5, now()))
        cur = con.execute("INSERT INTO users(name,email,password,role,phone,created_at) VALUES(?,?,?,?,?,?)",
            ("Demo Donor", "donor@bloodlink.local", generate_password_hash("Donor@123"), "donor", "9000000002", now()))
        duser = cur.lastrowid
        con.execute("""INSERT INTO donors(user_id,blood_group,city,latitude,longitude,available,last_donation,consent)
                       VALUES(?,?,?,?,?,?,?,1)""",
                    (duser, "O+", "Chennai", 13.0674, 80.2376, 1, ""))
        # A second hospital gives the nearby-stock finder something to show.
        cur = con.execute("INSERT INTO users(name,email,password,role,phone,created_at) VALUES(?,?,?,?,?,?)",
            ("Demo Hospital Two", "apollo.demo@bloodlink.local", generate_password_hash("Hospital@123"), "hospital", "9000000003", now()))
        huser2 = cur.lastrowid
        cur = con.execute("""INSERT INTO hospitals(user_id,hospital_name,address,city,latitude,longitude,verified)
                             VALUES(?,?,?,?,?,?,1)""",
            (huser2, "Riverside Medical Centre", "River View Road", "Chennai", 13.0569, 80.2425))
        hid2 = cur.lastrowid
        for bg, units in zip(BLOOD_GROUPS, [6, 3, 4, 2, 5, 2, 8, 1]):
            con.execute("INSERT INTO stock(hospital_id,blood_group,units,threshold,updated_at) VALUES(?,?,?,?,?)",
                        (hid2, bg, units, 5, now()))
    con.commit()
    con.close()

def current_user():
    if not session.get("user_id"):
        return None
    con = db()
    user = con.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    con.close()
    return user

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper

def role_required(*roles):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            user = current_user()
            if user["role"] not in roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard"))
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def hospital_for_user(user_id):
    con = db()
    row = con.execute("SELECT * FROM hospitals WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row

def donor_for_user(user_id):
    con = db()
    row = con.execute("SELECT * FROM donors WHERE user_id=?", (user_id,)).fetchone()
    con.close()
    return row

def notify(user_id, title, message, link=""):
    con = db()
    con.execute("INSERT INTO notifications(user_id,title,message,link,created_at) VALUES(?,?,?,?,?)",
                (user_id, title, message, link, now()))
    con.commit()
    con.close()

def distance_km(lat1, lon1, lat2, lon2):
    r = 6371
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp = math.radians(float(lat2) - float(lat1))
    dl = math.radians(float(lon2) - float(lon1))
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))

@app.context_processor
def inject_globals():
    user = current_user()
    unread = 0
    if user:
        con = db()
        unread = con.execute("SELECT COUNT(*) n FROM notifications WHERE user_id=? AND read=0", (user["id"],)).fetchone()["n"]
        con.close()
    return {"current_user": user, "unread_count": unread, "blood_groups": BLOOD_GROUPS}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        role = request.form.get("role", "")
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        if role not in ("hospital", "donor") or not name or not email or len(password) < 8:
            flash("Choose a valid account type and provide all required details. Password must be at least 8 characters.", "danger")
            return redirect(url_for("register"))
        try:
            con = db()
            cur = con.execute("INSERT INTO users(name,email,password,role,phone,created_at) VALUES(?,?,?,?,?,?)",
                              (name, email, generate_password_hash(password), role, phone, now()))
            uid = cur.lastrowid
            if role == "hospital":
                hname = request.form.get("hospital_name", "").strip()
                address = request.form.get("address", "").strip()
                city = request.form.get("city", "").strip()
                lat = float(request.form.get("latitude", "0"))
                lon = float(request.form.get("longitude", "0"))
                if not hname or not address or not city:
                    raise ValueError("Hospital name, address and city are required.")
                con.execute("INSERT INTO hospitals(user_id,hospital_name,address,city,latitude,longitude,verified) VALUES(?,?,?,?,?,?,0)",
                            (uid, hname, address, city, lat, lon))
            else:
                bg = request.form.get("blood_group", "")
                city = request.form.get("city", "").strip()
                lat = float(request.form.get("latitude", "0"))
                lon = float(request.form.get("longitude", "0"))
                if bg not in BLOOD_GROUPS or not city:
                    raise ValueError("Select a valid blood group and enter your city.")
                con.execute("INSERT INTO donors(user_id,blood_group,city,latitude,longitude,available,last_donation,consent) VALUES(?,?,?,?,?,?,?,1)",
                            (uid, bg, city, lat, lon, 1, request.form.get("last_donation", "")))
            con.commit()
            con.close()
            flash("Registration successful. Hospital accounts require admin verification before participating in transfers.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email address is already registered.", "danger")
        except Exception as e:
            flash(str(e), "danger")
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        con = db()
        user = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        con.close()
        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash("Welcome to BloodLink.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    con = db()
    if user["role"] == "hospital":
        h = con.execute("SELECT * FROM hospitals WHERE user_id=?", (user["id"],)).fetchone()
        stocks = con.execute("SELECT * FROM stock WHERE hospital_id=? ORDER BY blood_group", (h["id"],)).fetchall()
        emergencies = con.execute("SELECT * FROM emergencies WHERE hospital_id=? ORDER BY id DESC LIMIT 6", (h["id"],)).fetchall()
        transfers = con.execute("""SELECT t.*, h.hospital_name other_name FROM transfers t
          JOIN hospitals h ON h.id=CASE WHEN t.from_hospital_id=? THEN t.to_hospital_id ELSE t.from_hospital_id END
          WHERE t.from_hospital_id=? OR t.to_hospital_id=? ORDER BY t.id DESC LIMIT 6""",
          (h["id"], h["id"], h["id"])).fetchall()
        counts = {"donors": con.execute("SELECT COUNT(*) n FROM donors").fetchone()["n"],
                  "emergencies": con.execute("SELECT COUNT(*) n FROM emergencies WHERE hospital_id=? AND status='Open'", (h["id"],)).fetchone()["n"],
                  "low": sum(1 for s in stocks if s["units"] <= s["threshold"])}
        con.close()
        return render_template("hospital_dashboard.html", hospital=h, stocks=stocks, emergencies=emergencies, transfers=transfers, counts=counts)
    if user["role"] == "donor":
        d = con.execute("SELECT * FROM donors WHERE user_id=?", (user["id"],)).fetchone()
        invites = con.execute("""SELECT dr.*, e.blood_group,e.units,e.priority,e.needed_at,e.status emergency_status,
             h.hospital_name,h.city,h.latitude,h.longitude FROM donor_responses dr
             JOIN emergencies e ON e.id=dr.emergency_id JOIN hospitals h ON h.id=e.hospital_id
             WHERE dr.donor_id=? ORDER BY dr.id DESC""", (d["id"],)).fetchall()
        con.close()
        return render_template("donor_dashboard.html", donor=d, invites=invites)
    if user["role"] == "admin":
        stats = {
            "hospitals": con.execute("SELECT COUNT(*) n FROM hospitals").fetchone()["n"],
            "verified": con.execute("SELECT COUNT(*) n FROM hospitals WHERE verified=1").fetchone()["n"],
            "donors": con.execute("SELECT COUNT(*) n FROM donors").fetchone()["n"],
            "emergencies": con.execute("SELECT COUNT(*) n FROM emergencies WHERE status='Open'").fetchone()["n"],
            "transfers": con.execute("SELECT COUNT(*) n FROM transfers WHERE status='Pending'").fetchone()["n"]
        }
        hospitals = con.execute("SELECT h.*,u.email FROM hospitals h JOIN users u ON u.id=h.user_id ORDER BY h.id DESC").fetchall()
        con.close()
        return render_template("admin_dashboard.html", stats=stats, hospitals=hospitals)
    con.close()
    return redirect(url_for("index"))

@app.route("/stock", methods=["GET", "POST"])
@role_required("hospital")
def stock_management():
    h = hospital_for_user(session["user_id"])
    con = db()
    if request.method == "POST":
        bg = request.form.get("blood_group")
        try:
            units = int(request.form.get("units", "-1"))
            threshold = int(request.form.get("threshold", "5"))
            reason = request.form.get("reason", "").strip() or "Manual stock update"
            if bg not in BLOOD_GROUPS or units < 0 or threshold < 0:
                raise ValueError("Enter valid stock values.")
            old = con.execute("SELECT units FROM stock WHERE hospital_id=? AND blood_group=?", (h["id"], bg)).fetchone()
            old_units = old["units"] if old else 0
            con.execute("""INSERT INTO stock(hospital_id,blood_group,units,threshold,updated_at) VALUES(?,?,?,?,?)
                         ON CONFLICT(hospital_id,blood_group) DO UPDATE SET units=excluded.units,threshold=excluded.threshold,updated_at=excluded.updated_at""",
                        (h["id"], bg, units, threshold, now()))
            con.execute("INSERT INTO stock_log(hospital_id,blood_group,old_units,new_units,reason,updated_by,created_at) VALUES(?,?,?,?,?,?,?)",
                        (h["id"], bg, old_units, units, reason, session["user_id"], now()))
            con.commit()
            if units == 0:
                flash(f"{bg} stock is EMPTY. Review the shortage and start recruitment if needed.", "danger")
            elif units <= threshold:
                flash(f"{bg} stock is LOW. Staff review is recommended.", "warning")
            else:
                flash(f"{bg} stock updated successfully.", "success")
        except Exception as e:
            flash(str(e), "danger")
        con.close()
        return redirect(url_for("stock_management"))
    stocks = con.execute("SELECT * FROM stock WHERE hospital_id=? ORDER BY blood_group", (h["id"],)).fetchall()
    logs = con.execute("""SELECT l.*,u.name staff_name FROM stock_log l JOIN users u ON u.id=l.updated_by
                          WHERE l.hospital_id=? ORDER BY l.id DESC LIMIT 10""", (h["id"],)).fetchall()
    con.close()
    return render_template("stock.html", hospital=h, stocks=stocks, logs=logs)

@app.route("/emergency", methods=["GET", "POST"])
@role_required("hospital")
def emergency():
    h = hospital_for_user(session["user_id"])
    if request.method == "POST":
        bg = request.form.get("blood_group")
        try:
            units = int(request.form.get("units", "0"))
            radius = float(request.form.get("radius", "10"))
            priority = request.form.get("priority", "Urgent")
            needed = request.form.get("needed_at", "").strip() or "As soon as possible"
            notes = request.form.get("notes", "").strip()
            if bg not in BLOOD_GROUPS or units < 1 or radius < 1 or radius > 500 or priority not in ("Routine", "Urgent", "Critical"):
                raise ValueError("Check blood group, units, radius and priority.")
            con = db()
            cur = con.execute("""INSERT INTO emergencies(hospital_id,blood_group,units,priority,radius_km,needed_at,notes,status,created_at)
                                 VALUES(?,?,?,?,?,?,?,?,?)""",
                              (h["id"], bg, units, priority, radius, needed, notes, "Open", now()))
            eid = cur.lastrowid
            donors = con.execute("""SELECT d.*,u.id user_id FROM donors d JOIN users u ON u.id=d.user_id
                                    WHERE d.blood_group=? AND d.available=1 AND d.consent=1""", (bg,)).fetchall()
            matched = 0
            for d in donors:
                dist = distance_km(h["latitude"], h["longitude"], d["latitude"], d["longitude"])
                if dist <= radius:
                    con.execute("INSERT OR IGNORE INTO donor_responses(emergency_id,donor_id,status) VALUES(?,?,?)",
                                (eid, d["id"], "Pending"))
                    con.execute("INSERT INTO notifications(user_id,title,message,link,created_at) VALUES(?,?,?,?,?)",
                                (d["user_id"], "BloodLink emergency request",
                                 f"{priority} request: {bg}, {units} unit(s) requested by {h['hospital_name']}. Approx. {dist:.1f} km away. Needed: {needed}. Please respond in your donor dashboard.",
                                 "/dashboard", now()))
                    matched += 1
            con.commit()
            con.close()
            flash(f"Emergency request created. {matched} registered donor(s) within {radius:g} km were notified in the app. Hospital blood-bank staff must confirm compatibility and eligibility.", "success")
            return redirect(url_for("emergency_detail", emergency_id=eid))
        except Exception as e:
            flash(str(e), "danger")
    return render_template("emergency.html", hospital=h)

@app.route("/emergency/<int:emergency_id>")
@role_required("hospital")
def emergency_detail(emergency_id):
    h = hospital_for_user(session["user_id"])
    con = db()
    e = con.execute("SELECT * FROM emergencies WHERE id=? AND hospital_id=?", (emergency_id, h["id"])).fetchone()
    if not e:
        con.close()
        flash("Emergency request not found.", "danger")
        return redirect(url_for("dashboard"))
    responses = con.execute("""SELECT dr.*,u.name,u.phone,d.blood_group,d.city FROM donor_responses dr
        JOIN donors d ON d.id=dr.donor_id JOIN users u ON u.id=d.user_id
        WHERE dr.emergency_id=? ORDER BY CASE dr.status WHEN 'Accepted' THEN 0 WHEN 'Pending' THEN 1 ELSE 2 END""",
        (emergency_id,)).fetchall()
    con.close()
    return render_template("emergency_detail.html", emergency=e, responses=responses)

@app.route("/donor/respond/<int:response_id>/<action>", methods=["POST"])
@role_required("donor")
def donor_respond(response_id, action):
    if action not in ("Accepted", "Rejected"):
        return redirect(url_for("dashboard"))
    d = donor_for_user(session["user_id"])
    con = db()
    row = con.execute("""SELECT dr.*,e.hospital_id,h.user_id hospital_user,h.hospital_name
                         FROM donor_responses dr JOIN emergencies e ON e.id=dr.emergency_id
                         JOIN hospitals h ON h.id=e.hospital_id
                         WHERE dr.id=? AND dr.donor_id=?""", (response_id, d["id"])).fetchone()
    if row:
        con.execute("UPDATE donor_responses SET status=?,responded_at=? WHERE id=?",
                    (action, now(), response_id))
        con.execute("INSERT INTO notifications(user_id,title,message,link,created_at) VALUES(?,?,?,?,?)",
                    (row["hospital_user"], "Donor response received",
                     f"A donor has {action.lower()} your {row['hospital_name']} emergency request.", "/dashboard", now()))
        con.commit()
        flash(f"Your response was recorded: {action}. The hospital will coordinate next steps.", "success")
    else:
        flash("Request not found.", "danger")
    con.close()
    return redirect(url_for("dashboard"))

@app.route("/donor/availability", methods=["POST"])
@role_required("donor")
def donor_availability():
    d = donor_for_user(session["user_id"])
    available = 1 if request.form.get("available") == "1" else 0
    con = db()
    con.execute("UPDATE donors SET available=? WHERE id=?", (available, d["id"]))
    con.commit()
    con.close()
    flash("Availability updated.", "success")
    return redirect(url_for("dashboard"))

@app.route("/nearby")
@role_required("hospital")
def nearby():
    h = hospital_for_user(session["user_id"])
    bg = request.args.get("blood_group", "O+")
    try:
        units = max(1, int(request.args.get("units", "1")))
    except ValueError:
        units = 1
    con = db()
    rows = con.execute("""SELECT h.*,s.units,s.blood_group,u.name contact_name,u.phone
                          FROM hospitals h JOIN stock s ON s.hospital_id=h.id
                          JOIN users u ON u.id=h.user_id
                          WHERE h.verified=1 AND s.blood_group=? AND h.id<>?""", (bg, h["id"])).fetchall()
    results = []
    for r in rows:
        dist = distance_km(h["latitude"], h["longitude"], r["latitude"], r["longitude"])
        results.append({**dict(r), "distance": dist, "sufficient": r["units"] >= units})
    results.sort(key=lambda x: (not x["sufficient"], x["distance"]))
    con.close()
    return render_template("nearby.html", hospital=h, results=results, selected_bg=bg, units=units)

@app.route("/transfer", methods=["POST"])
@role_required("hospital")
def create_transfer():
    h = hospital_for_user(session["user_id"])
    try:
        target = int(request.form.get("to_hospital_id"))
        bg = request.form.get("blood_group")
        units = int(request.form.get("units", "0"))
        con = db()
        dest = con.execute("SELECT * FROM hospitals WHERE id=? AND verified=1", (target,)).fetchone()
        if not dest or target == h["id"] or bg not in BLOOD_GROUPS or units < 1:
            raise ValueError("Invalid transfer request.")
        stock = con.execute("SELECT units FROM stock WHERE hospital_id=? AND blood_group=?", (target, bg)).fetchone()
        if not stock or stock["units"] < units:
            raise ValueError("The selected hospital does not currently show enough stock.")
        cur = con.execute("INSERT INTO transfers(from_hospital_id,to_hospital_id,blood_group,units,status,created_at) VALUES(?,?,?,?,?,?)",
                          (h["id"], target, bg, units, "Pending", now()))
        tid = cur.lastrowid
        con.execute("INSERT INTO notifications(user_id,title,message,link,created_at) VALUES(?,?,?,?,?)",
                    (dest["user_id"], "Blood transfer request",
                     f"{h['hospital_name']} requests {units} unit(s) of {bg}. Review the request in your hospital dashboard.", "/transfers", now()))
        con.commit()
        con.close()
        flash(f"Transfer request #{tid} sent. Stock is not reserved or deducted until the providing hospital approves and records the transfer.", "success")
    except Exception as e:
        try: con.close()
        except: pass
        flash(str(e), "danger")
    return redirect(url_for("nearby", blood_group=bg if 'bg' in locals() else "O+"))

@app.route("/transfers", methods=["GET", "POST"])
@role_required("hospital")
def transfers():
    h = hospital_for_user(session["user_id"])
    con = db()
    if request.method == "POST":
        tid = int(request.form.get("transfer_id", "0"))
        action = request.form.get("action")
        row = con.execute("SELECT * FROM transfers WHERE id=? AND to_hospital_id=?", (tid, h["id"])).fetchone()
        if row and action in ("Approved", "Rejected"):
            if action == "Approved":
                stock = con.execute("SELECT units FROM stock WHERE hospital_id=? AND blood_group=?", (h["id"], row["blood_group"])).fetchone()
                if not stock or stock["units"] < row["units"]:
                    flash("Insufficient stock to approve this transfer.", "danger")
                else:
                    con.execute("UPDATE stock SET units=units-?,updated_at=? WHERE hospital_id=? AND blood_group=?",
                                (row["units"], now(), h["id"], row["blood_group"]))
                    con.execute("UPDATE transfers SET status='Approved' WHERE id=?", (tid,))
                    con.commit()
                    flash("Transfer approved. Stock was reduced at the providing hospital; record receipt and verification separately at the receiving hospital.", "success")
            else:
                con.execute("UPDATE transfers SET status='Rejected' WHERE id=?", (tid,))
                con.commit()
                flash("Transfer request rejected.", "info")
        con.close()
        return redirect(url_for("transfers"))
    rows = con.execute("""SELECT t.*,hf.hospital_name from_name,ht.hospital_name to_name
                          FROM transfers t JOIN hospitals hf ON hf.id=t.from_hospital_id
                          JOIN hospitals ht ON ht.id=t.to_hospital_id
                          WHERE t.from_hospital_id=? OR t.to_hospital_id=? ORDER BY t.id DESC""", (h["id"], h["id"])).fetchall()
    con.close()
    return render_template("transfers.html", hospital=h, transfers=rows)

@app.route("/notifications")
@login_required
def notifications():
    con = db()
    rows = con.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100", (session["user_id"],)).fetchall()
    con.execute("UPDATE notifications SET read=1 WHERE user_id=?", (session["user_id"],))
    con.commit()
    con.close()
    return render_template("notifications.html", notifications=rows)

@app.route("/admin/verify/<int:hospital_id>", methods=["POST"])
@role_required("admin")
def verify_hospital(hospital_id):
    con = db()
    con.execute("UPDATE hospitals SET verified=1 WHERE id=?", (hospital_id,))
    con.commit()
    con.close()
    flash("Hospital marked as verified. Complete real-world verification before enabling live use.", "success")
    return redirect(url_for("dashboard"))

@app.route("/admin/low-stock")
@role_required("admin")
def admin_low_stock():
    con = db()
    rows = con.execute("""SELECT s.*,h.hospital_name,h.city FROM stock s JOIN hospitals h ON h.id=s.hospital_id
                          WHERE s.units<=s.threshold ORDER BY s.units ASC""").fetchall()
    con.close()
    return render_template("admin_low_stock.html", rows=rows)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
