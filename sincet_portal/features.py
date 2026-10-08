"""SINCET portal - extension features (v7).

Registered from app.py with  features.init(globals()).  Everything lives in one Flask blueprint so the
original app.py stays readable.  The admin-side features are in features_admin.py (same blueprint).

  Faculty : bulk marks grid, assignment tasks + grading, leave/OD approval, announcements, low-attendance report
  Student : online fee payment (Razorpay), receipt PDF, assignment upload, timetable / exams / hall ticket,
            announcements, leave / OD, results + CGPA + mark sheet PDF
  Admin   : see features_admin.py
"""
import base64
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Blueprint, Response, abort, jsonify, render_template, request, session)

import db
import notify

BASE = os.path.dirname(os.path.abspath(__file__))
bp = Blueprint("feat", __name__)
_G = {}


class _App:
    """Late-bound access to helpers that live in app.py (avoids a circular import)."""

    def __getattr__(self, name):
        return _G[name]


A = _App()

PERIOD_TIMES = ["09:00-09:50", "09:50-10:40", "10:50-11:40", "11:40-12:30",
                "13:15-14:05", "14:05-14:55", "15:05-15:55", "15:55-16:45"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
SESSIONS = ["FN", "AN"]
# Anna University style 10-point grading on the Semester exam percentage (edit if your scale differs)
GRADES = [(91, "O", 10), (81, "A+", 9), (71, "A", 8), (61, "B+", 7), (56, "B", 6), (50, "C", 5)]
PASS_PCT = 50.0
DEFAULT_CREDITS = 3
FACULTY_ANY_DEPT = os.getenv("FACULTY_MARKS_ANY_DEPT", "0") == "1"
HALLTICKET_BLOCK_DUES = os.getenv("HALLTICKET_BLOCK_DUES", "0") == "1"
MAX_UPLOAD = 8 * 1024 * 1024
UPLOAD_EXT = {"pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt", "zip", "png", "jpg", "jpeg"}
UPLOAD_DIR = os.path.join(BASE, "uploads")
CSRF_EXEMPT = {"/payments/razorpay/webhook"}


# --------------------------------------------------------------------------- small helpers
def need(*roles):
    """Same as app.role_required, resolved lazily."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            return A.role_required(*roles)(fn)(*a, **kw)
        return wrapper
    return deco


def _json():
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def _num(v, lo, hi):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, 2) if lo <= x <= hi else None


def _int(v):
    return int(v) if str(v).strip().lstrip("-").isdigit() else None


def _date(v):
    try:
        return datetime.strptime(str(v).strip(), "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _audit(actor, action, detail=""):
    try:
        db.insert("INSERT INTO audit_log (actor, action, detail, created_at) VALUES (%s,%s,%s,%s)",
                  (actor, action, detail[:250], A.now()))
    except db.DatabaseError:
        pass


def _week_key():
    y, w, _ = date.today().isocalendar()
    return f"{y}-W{w:02d}"


def pdf_response(name, data):
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={name}"})


def _faculty():
    return db.query_one("SELECT u.*, d.name AS dept_name, d.code AS dept_code FROM users u "
                        "JOIN departments d ON d.id=u.department_id WHERE u.id=%s", (session["uid"],))


def _student():
    return db.query_one(
        "SELECT u.*, d.name AS dept_name, d.code AS dept_code, s.name AS section_name FROM users u "
        "JOIN departments d ON d.id=u.department_id LEFT JOIN sections s ON s.id=u.section_id WHERE u.id=%s",
        (session["uid"],))


def _class_roster(dept, year, section=None):
    sql = ("SELECT u.id, u.username, u.name FROM users u WHERE u.role='student' AND u.status='active' "
           "AND u.department_id=%s AND u.year_no=%s")
    args = [dept, year]
    if section:
        sql += " AND u.section_id=%s"
        args.append(section)
    return db.query(sql + " ORDER BY u.username", tuple(args))


# --------------------------------------------------------------------------- admin scopes (role-wise admins)
ADMIN_SCOPES = {"super": "Super admin (everything)", "accounts": "Accounts office (fees & reminders)",
                "exam": "Exam cell (marks, schedule, results, feedback)",
                "library": "Librarian (books, issue, return, fines)"}
_COMMON = ("/admin", "/admin/dashboard", "/admin/password", "/admin/logout", "/admin/ping", "/admin/api/stats")
_ALLOW = {
    "accounts": ("/admin/fees", "/admin/api/fees", "/admin/reports", "/admin/api/reports",
                 "/admin/notifications", "/admin/api/notify", "/admin/announcements", "/admin/api/announcements"),
    "library": ("/admin/library", "/admin/api/library"),
    "exam": ("/admin/feedback", "/admin/api/feedback", "/admin/marks", "/admin/assignments", "/admin/api/e/marks", "/admin/api/e/assignments",
             "/admin/schedule", "/admin/api/schedule", "/admin/results", "/admin/api/results",
             "/admin/reports", "/admin/api/reports", "/admin/announcements", "/admin/api/announcements"),
}
_CAN = {  # template switch -> scopes that see it
    "fees": ("super", "accounts"), "notify": ("super", "accounts"), "marks": ("super", "exam"),
    "schedule": ("super", "exam"), "reports": ("super", "accounts", "exam"),
    "announce": ("super", "accounts", "exam"), "super": ("super",),
    "library": ("super", "library"), "feedback": ("super", "exam"),
}


def admin_scope():
    return session.get("scope") or "super" if session.get("role") == "admin" else None


@bp.before_app_request
def scope_guard():
    if session.get("role") != "admin" or not request.path.startswith("/admin"):
        return None
    scope = session.get("scope") or "super"
    if scope == "super":
        return None
    p = request.path.rstrip("/") or "/"
    if p in _COMMON or any(p == a or p.startswith(a + "/") for a in _ALLOW.get(scope, ())):
        return None
    if A.is_api():
        return jsonify(ok=False, error="Your admin role does not have access to this section."), 403
    abort(403)


@bp.app_context_processor
def _ctx():
    scope = admin_scope()
    return dict(admin_scope=scope, can=lambda sec: scope in _CAN.get(sec, ()), gateway_on=gateway_enabled(),
                period_times=PERIOD_TIMES, day_names=DAYS)


# --------------------------------------------------------------------------- schema upgrade
def migrate():
    """Upgrade path for databases created by v6 (new tables are created by init_db from schema.sql)."""
    for stmt in ("ALTER TABLE admins ADD COLUMN scope VARCHAR(20) NOT NULL DEFAULT 'super'",):
        try:
            db.execute(stmt)
        except db.DatabaseError:
            db.rollback()   # column already exists


# =========================================================================== FACULTY: bulk marks grid
def _check_class(me, dept, year, section, subject):
    """Validates a class selection made by faculty. Returns (subject_row, error)."""
    if not FACULTY_ANY_DEPT and dept != me["department_id"]:
        return None, "You can enter marks only for your own department."
    sub = db.query_one("SELECT id, code, name, department_id, year_no FROM subjects WHERE id=%s", (subject,))
    if not sub or sub["department_id"] != dept or sub["year_no"] != year:
        return None, "That subject does not belong to the selected department / year."
    if not db.query_one("SELECT id FROM sections WHERE id=%s AND department_id=%s AND year_no=%s",
                        (section, dept, year)):
        return None, "Section not found."
    return sub, None


def _grid_args(src):
    keys = ("dept", "year", "section", "subject")
    vals = [_int(src.get(k)) for k in keys]
    return vals if all(v is not None for v in vals) else None


@bp.route("/faculty/marks")
@need("faculty")
def faculty_marks_page():
    me = _faculty()
    depts = db.query("SELECT id, code, name FROM departments ORDER BY name")
    return render_template("faculty/marks.html", me=me, depts=depts, exams=A.EXAMS, any_dept=FACULTY_ANY_DEPT)


@bp.route("/faculty/api/marks/grid")
@need("faculty")
def faculty_marks_grid():
    args = _grid_args(request.args)
    if not args:
        return A.bad("Select department, year, section and subject.")
    dept, year, section, subject = args
    me = _faculty()
    sub, err = _check_class(me, dept, year, section, subject)
    if err:
        return A.bad(err, 403)
    kind = request.args.get("kind", "marks")
    label = request.args.get("label", "").strip()
    if kind == "marks" and label not in A.EXAMS:
        return A.bad("Choose the exam.")
    if kind == "assignment" and not (1 <= len(label) <= 120):
        return A.bad("Enter the assignment name.")
    if kind not in ("marks", "assignment"):
        return A.bad("Invalid type.")
    table, col = ("marks", "exam_type") if kind == "marks" else ("assignments", "name")
    have = {r["student_id"]: r for r in db.query(
        f"SELECT student_id, marks, max_marks FROM {table} WHERE subject_id=%s AND {col}=%s", (subject, label))}
    out = [dict(id=s["id"], username=s["username"], name=s["name"],
                marks=have[s["id"]]["marks"] if s["id"] in have else None) for s in _class_roster(dept, year, section)]
    max_marks = next(iter(have.values()))["max_marks"] if have else 100
    return jsonify(ok=True, students=out, max_marks=max_marks, subject=f"{sub['code']} {sub['name']}")


@bp.route("/faculty/api/marks/save", methods=["POST"])
@need("faculty")
def faculty_marks_save():
    d = _json()
    args = _grid_args(d)
    if not args:
        return A.bad("Select department, year, section and subject.")
    dept, year, section, subject = args
    me = _faculty()
    sub, err = _check_class(me, dept, year, section, subject)
    if err:
        return A.bad(err, 403)
    kind, label = d.get("kind", "marks"), str(d.get("label", "")).strip()
    if kind == "marks":
        if label not in A.EXAMS:
            return A.bad("Choose the exam.")
        table, col = "marks", "exam_type"
    elif kind == "assignment":
        if not re.fullmatch(r"[\w &.,'()/\-]{1,120}", label):
            return A.bad("Enter a valid assignment name.")
        table, col = "assignments", "name"
    else:
        return A.bad("Invalid type.")
    max_marks = _num(d.get("max_marks"), 1, 1000)
    if max_marks is None:
        return A.bad("Enter the maximum marks (1-1000).")
    entries = d.get("entries")
    if not isinstance(entries, list) or len(entries) > 400:
        return A.bad("Nothing to save.")
    roster = {s["id"] for s in _class_roster(dept, year, section)}
    clean, errors = [], []
    for e in entries:
        if not isinstance(e, dict) or _int(e.get("student_id")) not in roster:
            return A.bad("The list contains a student who is not in this class. Reload the grid.")
        raw = e.get("marks")
        if raw is None or str(raw).strip() == "":
            continue                      # blank = leave as it is
        m = _num(raw, 0, max_marks)
        if m is None:
            errors.append(e.get("student_id"))
            continue
        clean.append((int(e["student_id"]), m))
    if errors:
        return A.bad(f"{len(errors)} mark(s) are invalid - marks must be between 0 and {max_marks:g}.")
    if not clean:
        return A.bad("Enter at least one mark.")
    existing = {r["student_id"] for r in db.query(
        f"SELECT student_id FROM {table} WHERE subject_id=%s AND {col}=%s", (subject, label))}
    with db.transaction():
        for sid, m in clean:
            if sid in existing:
                db.execute(f"UPDATE {table} SET marks=%s, max_marks=%s WHERE student_id=%s AND subject_id=%s "
                           f"AND {col}=%s", (m, max_marks, sid, subject, label), commit=False)
            else:
                db.execute(f"INSERT INTO {table} (student_id, subject_id, {col}, marks, max_marks, created_at) "
                           "VALUES (%s,%s,%s,%s,%s,%s)", (sid, subject, label, m, max_marks, A.now()), commit=False)
    A.audit("marks_bulk_saved", f"{kind} {sub['code']} '{label}' {len(clean)} students")
    return jsonify(ok=True, saved=len(clean))


# =========================================================================== FEES: gateway, receipts, reminders
def gateway_enabled():
    return (os.getenv("PAYMENT_GATEWAY", "").lower() == "razorpay"
            and bool(os.getenv("RAZORPAY_KEY_ID")) and bool(os.getenv("RAZORPAY_KEY_SECRET")))


def _rz_request(path, body):
    key, secret = os.environ["RAZORPAY_KEY_ID"], os.environ["RAZORPAY_KEY_SECRET"]
    auth = base64.b64encode(f"{key}:{secret}".encode()).decode()
    _status, text = notify._post("https://api.razorpay.com/v1/" + path, headers={"Authorization": "Basic " + auth},
                                 json_body=body)
    return json.loads(text)


def rz_create_order(amount_paise, receipt, notes):
    """Creates a Razorpay order. Isolated in one function so tests can replace it."""
    return _rz_request("orders", {"amount": amount_paise, "currency": "INR", "receipt": receipt, "notes": notes})


def rz_signature_ok(order_id, payment_id, signature):
    secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    expect = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expect, str(signature or ""))


def settle_gateway(order_id, gw_payment_id, actor="razorpay"):
    """Idempotently turns a paid gateway order into a *received* fee payment with a receipt number.
    Returns the payment row (dict) or None when the order is unknown."""
    o = db.query_one("SELECT * FROM gateway_orders WHERE order_id=%s", (order_id,))
    if not o:
        return None
    if o["status"] != "paid":
        with db.transaction():
            won = db.execute("UPDATE gateway_orders SET status='paid', gateway_payment_id=%s, paid_at=%s "
                             "WHERE order_id=%s AND status='created'", (gw_payment_id, A.now(), order_id), commit=False)
            if won:      # we are the first to settle it (verify call and webhook can race)
                pid = db.insert(
                    "INSERT INTO fee_payments (fee_id, student_id, amount, method, reference, status, paid_at, "
                    "reviewed_by, reviewed_at, note) VALUES (%s,%s,%s,%s,%s,'received',%s,%s,%s,%s)",
                    (o["fee_id"], o["student_id"], o["amount"], "Razorpay", gw_payment_id, A.now(), actor, A.now(),
                     "Auto-verified by payment gateway"), commit=False)
                db.execute("UPDATE fee_payments SET receipt_no=%s WHERE id=%s",
                           (f"RCP-{datetime.now().year}-{pid:05d}", pid), commit=False)
                db.execute("UPDATE gateway_orders SET payment_row_id=%s WHERE order_id=%s", (pid, order_id),
                           commit=False)
        _audit(actor, "fee_gateway_paid", f"order {order_id} payment {gw_payment_id} Rs{o['amount']}")
    o = db.query_one("SELECT * FROM gateway_orders WHERE order_id=%s", (order_id,))
    return db.query_one("SELECT id, receipt_no, amount FROM fee_payments WHERE id=%s", (o["payment_row_id"],)) \
        if o and o["payment_row_id"] else None


@bp.route("/student/api/fees/gateway/order", methods=["POST"])
@need("student")
def student_gateway_order():
    if not gateway_enabled():
        return A.bad("Online payment is not enabled. Use the manual payment option.", 400)
    d = _json()
    fee_id, amount = _int(d.get("fee_id")), _num(d.get("amount"), 1, 1000000)
    if fee_id is None or amount is None:
        return A.bad("Select a fee and enter a valid amount.")
    fee = next((f for f in A.fee_records(student_id=session["uid"]) if f["id"] == fee_id), None)
    if not fee:
        return A.bad("Fee not found.", 404)
    if amount > fee["balance"] + 0.005:
        return A.bad(f"Amount exceeds the balance (₹{fee['balance']:.2f}) for this fee.")
    try:
        order = rz_create_order(int(round(amount * 100)), f"fee{fee_id}-{secrets.token_hex(3)}",
                                {"fee_id": str(fee_id), "student_id": str(session["uid"])})
    except (urllib.error.URLError, ValueError, KeyError, OSError):
        return A.bad("The payment gateway is not reachable right now. Please try again.", 502)
    if not order.get("id"):
        return A.bad("The payment gateway rejected the request.", 502)
    db.insert("INSERT INTO gateway_orders (fee_id, student_id, amount, provider, order_id, status, created_at) "
              "VALUES (%s,%s,%s,'razorpay',%s,'created',%s)", (fee_id, session["uid"], amount, order["id"], A.now()))
    return jsonify(ok=True, key_id=os.environ["RAZORPAY_KEY_ID"], order_id=order["id"],
                   amount=int(round(amount * 100)), name=A.FEE_PAYEE, description=fee["title"],
                   prefill=dict(name=session.get("name", "")))


@bp.route("/student/api/fees/gateway/verify", methods=["POST"])
@need("student")
def student_gateway_verify():
    d = _json()
    oid, pid, sig = (str(d.get(k, "")) for k in ("razorpay_order_id", "razorpay_payment_id", "razorpay_signature"))
    o = db.query_one("SELECT * FROM gateway_orders WHERE order_id=%s AND student_id=%s", (oid, session["uid"]))
    if not o:
        return A.bad("Unknown payment order.", 404)
    if not rz_signature_ok(oid, pid, sig):
        _audit(session.get("username", "-"), "fee_gateway_bad_signature", f"order {oid}")
        return A.bad("Payment could not be verified. If money was deducted it will be reconciled automatically.", 400)
    pay = settle_gateway(oid, pid, actor="razorpay")
    return jsonify(ok=True, receipt_no=pay["receipt_no"] if pay else None,
                   message="Payment successful and verified automatically.")


@bp.route("/payments/razorpay/webhook", methods=["POST"])
def razorpay_webhook():
    """Razorpay -> server callback. Settles the payment even if the student closed the browser."""
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        abort(404)
    raw = request.get_data()
    expect = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, request.headers.get("X-Razorpay-Signature", "")):
        return jsonify(ok=False), 400
    try:
        ev = json.loads(raw)
        pay = (ev.get("payload", {}).get("payment") or {}).get("entity") or {}
        order = (ev.get("payload", {}).get("order") or {}).get("entity") or {}
        oid, payid = pay.get("order_id") or order.get("id"), pay.get("id")
        if ev.get("event") in ("payment.captured", "order.paid") and oid and payid:
            settle_gateway(oid, payid)
    except (ValueError, AttributeError):
        pass
    return jsonify(ok=True)


# ----- receipts
_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _words(n):
    if n < 20:
        return _ONES[n]
    if n < 100:
        return (_TENS[n // 10] + " " + _ONES[n % 10]).strip()
    if n < 1000:
        return (_ONES[n // 100] + " Hundred " + _words(n % 100)).strip()
    for div, name in ((10 ** 7, "Crore"), (10 ** 5, "Lakh"), (1000, "Thousand")):
        if n >= div:
            return (_words(n // div) + f" {name} " + _words(n % div)).strip()
    return ""


def rupees_in_words(amount):
    rupees, paise = divmod(int(round(float(amount) * 100)), 100)
    out = "Rupees " + (_words(rupees) or "Zero")
    if paise:
        out += " and " + _words(paise) + " Paise"
    return out + " Only"


def receipt_row(pid, student_id=None):
    sql = ("SELECT p.id, p.amount, p.method, p.reference, p.paid_at, p.receipt_no, p.reviewed_by, p.reviewed_at, "
           "p.fee_id, f.title, f.amount AS fee_amount, u.name, u.username, u.year_no, d.name AS dept_name, "
           "s.name AS section_name FROM fee_payments p JOIN fees f ON f.id=p.fee_id "
           "JOIN users u ON u.id=p.student_id JOIN departments d ON d.id=u.department_id "
           "LEFT JOIN sections s ON s.id=u.section_id WHERE p.id=%s AND p.status='received'")
    args = [pid]
    if student_id:
        sql += " AND p.student_id=%s"
        args.append(student_id)
    return db.query_one(sql, tuple(args))


def build_receipt_pdf(p):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A5, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    paid_so_far = db.query_one("SELECT COALESCE(SUM(amount),0) AS t FROM fee_payments WHERE fee_id=%s "
                               "AND status='received' AND id<=%s", (p["fee_id"], p["id"]))["t"]
    balance = max(0.0, float(p["fee_amount"]) - float(paid_so_far))
    st = getSampleStyleSheet()
    head = ParagraphStyle("h", parent=st["Title"], fontSize=15, textColor=colors.HexColor("#0b2a5b"), spaceAfter=2)
    sub = ParagraphStyle("s", parent=st["Normal"], alignment=1, fontSize=9, textColor=colors.HexColor("#445"))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A5), leftMargin=30, rightMargin=30, topMargin=24,
                            bottomMargin=24, title=f"Receipt {p['receipt_no']}")
    rows = [["Receipt No", p["receipt_no"], "Date", (p["reviewed_at"] or p["paid_at"])[:10]],
            ["Student", p["name"], "Student ID", p["username"]],
            ["Department", p["dept_name"], "Year / Section", f"{p['year_no'] or '-'} / {p['section_name'] or '-'}"],
            ["Fee", p["title"], "Payment mode", p["method"]],
            ["Reference", p["reference"] or "-", "Fee total", f"Rs. {float(p['fee_amount']):,.2f}"],
            ["Amount received", f"Rs. {float(p['amount']):,.2f}", "Balance after this", f"Rs. {balance:,.2f}"]]
    t = Table(rows, colWidths=[85, 150, 90, 130])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9aa7bd")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3fb")), ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef3fb")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 5), (1, 5), "Helvetica-Bold"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    doc.build([Paragraph("Sir Issac College of Engineering and Technology", head),
               Paragraph("FEE RECEIPT", sub), Spacer(1, 12), t, Spacer(1, 10),
               Paragraph(f"<b>Amount in words:</b> {rupees_in_words(p['amount'])}", st["Normal"]), Spacer(1, 18),
               Paragraph(f"Verified by: {p['reviewed_by'] or 'Accounts Office'} &nbsp;|&nbsp; "
                         "This is a computer-generated receipt and needs no signature.", sub)])
    return buf.getvalue()


@bp.route("/student/fees/receipt/<int:pid>.pdf")
@need("student")
def student_receipt(pid):
    p = receipt_row(pid, session["uid"])
    if not p:
        abort(404)
    return pdf_response(f"{p['receipt_no']}.pdf", build_receipt_pdf(p))


@bp.route("/admin/fees/receipt/<int:pid>.pdf")
@need("admin")
def admin_receipt(pid):
    p = receipt_row(pid)
    if not p:
        abort(404)
    return pdf_response(f"{p['receipt_no']}.pdf", build_receipt_pdf(p))


# ----- fee due reminders
def open_fees(dept=None, year=None):
    """Active students' fees with received / pending-verification totals (no row limit)."""
    sql = ("SELECT f.id AS fee_id, f.student_id, u.username, u.name, u.department_id, u.year_no, d.code AS dept_code, "
           "d.name AS dept_name, f.title, f.amount, f.due_date, "
           "COALESCE((SELECT SUM(p.amount) FROM fee_payments p WHERE p.fee_id=f.id AND p.status='received'),0) AS paid, "
           "COALESCE((SELECT SUM(p.amount) FROM fee_payments p WHERE p.fee_id=f.id AND p.status='pending'),0) AS pending "
           "FROM fees f JOIN users u ON u.id=f.student_id JOIN departments d ON d.id=u.department_id "
           "WHERE u.status='active'")
    args = []
    if dept:
        sql += " AND u.department_id=%s"
        args.append(dept)
    if year:
        sql += " AND u.year_no=%s"
        args.append(year)
    rows = db.query(sql + " ORDER BY d.code, u.username, f.id", tuple(args))
    for r in rows:
        r["paid"], r["pending"] = float(r["paid"] or 0), float(r["pending"] or 0)
        r["due_amount"] = round(max(0.0, r["amount"] - r["paid"]), 2)          # still owed (received only)
        r["balance"] = round(max(0.0, r["amount"] - r["paid"] - r["pending"]), 2)  # not yet even submitted
    return rows


def contacts_map():
    return {c["student_id"]: c for c in db.query("SELECT * FROM student_contacts")}


def reminder_channels():
    chans = [c.strip() for c in os.getenv("REMINDER_CHANNELS", "email,sms").split(",")]
    return [c for c in chans if c in ("email", "sms", "whatsapp")]


def run_reminders(actor="system"):
    """Sends due-date reminders. Safe to run every day (each reminder is sent once). Returns a summary."""
    try:
        days = sorted({int(x) for x in os.getenv("REMINDER_DAYS", "7,3,1,0").split(",") if x.strip()}, reverse=True)
    except ValueError:
        days = [7, 3, 1, 0]
    chans, cmap, today_d = reminder_channels(), contacts_map(), date.today()
    res = dict(considered=0, sent=0, logged=0, failed=0, duplicate=0, no_contact=0)
    for f in open_fees():
        if not f["due_date"] or f["balance"] <= 0:
            continue
        delta = (date.fromisoformat(f["due_date"]) - today_d).days
        if delta in days:
            kind, ref = f"fee_due:{delta}", str(f["fee_id"])
            when = "today" if delta == 0 else f"in {delta} day(s) ({f['due_date']})"
            text = (f"SINCET: Dear {f['name']}, your fee '{f['title']}' (balance Rs {f['balance']:.2f}) is due {when}. "
                    "Please pay through the student portal. - Accounts Office")
        elif delta < 0:
            kind, ref = "fee_overdue", f"{f['fee_id']}:{_week_key()}"
            text = (f"SINCET: Dear {f['name']}, your fee '{f['title']}' (balance Rs {f['balance']:.2f}) was due on "
                    f"{f['due_date']} and is overdue. Please pay at the earliest. - Accounts Office")
        else:
            continue
        res["considered"] += 1
        c = cmap.get(f["student_id"]) or {}
        sent_any = False
        for ch in chans:
            to = c.get("email") if ch == "email" else c.get("phone")
            if not to:
                continue
            out = notify.send(ch, to, "Fee due reminder", text, kind, ref, A.now())
            if out in res:
                res[out] += 1
            sent_any = sent_any or out in ("sent", "logged", "duplicate")
        if not sent_any:
            res["no_contact"] += 1
    _audit(actor, "fee_reminders_run", json.dumps(res))
    return res


def send_parent_alerts(kind, rows, channel):
    """rows: low-attendance rows (student_id, name, username, pct) or open-fee rows. Returns a summary."""
    cmap, res = contacts_map(), dict(considered=0, sent=0, logged=0, failed=0, duplicate=0, no_contact=0)
    for r in rows:
        res["considered"] += 1
        c = cmap.get(r["student_id"]) or {}
        to = c.get("parent_email") if channel == "email" else c.get("parent_phone")
        if not to:
            res["no_contact"] += 1
            continue
        if kind == "low_attendance":
            text = (f"SINCET: Your ward {r['name']} ({r['username']}) has {r['pct']}% attendance, below the required "
                    f"{r['threshold']:g}%. Please contact the department. - Principal")
            ref = f"{r['student_id']}:{_week_key()}"
        else:
            text = (f"SINCET: Fee '{r['title']}' (Rs {r['due_amount']:.2f}) of your ward {r['name']} "
                    f"({r['username']}) is pending{(' since ' + r['due_date']) if r['due_date'] else ''}. "
                    "Kindly pay at the earliest. - Accounts Office")
            ref = f"{r['fee_id']}:{_week_key()}"
        out = notify.send(channel, to, "SINCET parent alert", text, "parent_" + kind, ref, A.now())
        if out in res:
            res[out] += 1
    return res


# =========================================================================== file storage (Supabase Storage / local disk)
def _sb_cfg():
    url, key = os.getenv("SUPABASE_URL", "").rstrip("/"), os.getenv("SUPABASE_SERVICE_KEY", "")
    return (url, key, os.getenv("SUPABASE_BUCKET", "submissions")) if url and key else None


def _sb_request(method, key, data=None, ctype=None):
    url, svc, bucket = _sb_cfg()
    path = "/".join(urllib.parse.quote(p) for p in key.split("/"))
    h = {"Authorization": "Bearer " + svc, "apikey": svc}
    if ctype:
        h["Content-Type"] = ctype
        h["x-upsert"] = "true"
    req = urllib.request.Request(f"{url}/storage/v1/object/{bucket}/{path}", data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (project URL from env)
        return r.read()


def _local_path(key):
    parts = [p for p in key.split("/") if p and p not in (".", "..")]
    return os.path.join(UPLOAD_DIR, *parts)


def storage_put(key, data, ctype="application/octet-stream"):
    if _sb_cfg():
        _sb_request("POST", key, data, ctype)
        return
    path = _local_path(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data)


def storage_get(key):
    if _sb_cfg():
        return _sb_request("GET", key)
    with open(_local_path(key), "rb") as fh:
        return fh.read()


def storage_delete(key):
    try:
        if _sb_cfg():
            _sb_request("DELETE", key)
        else:
            os.remove(_local_path(key))
    except (OSError, urllib.error.URLError):
        pass


def _file_response(row):
    try:
        data = storage_get(row["file_key"])
    except (OSError, urllib.error.URLError):
        abort(404)
    ctype = mimetypes.guess_type(row["file_name"])[0] or "application/octet-stream"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", row["file_name"])
    return Response(data, mimetype=ctype, headers={"Content-Disposition": f'attachment; filename="{safe}"'})


# =========================================================================== ASSIGNMENT SUBMISSION
@bp.route("/student/assignments")
@need("student")
def student_assignments_page():
    return render_template("student/assignments.html", me=_student(), tasks=student_tasks(session["uid"]),
                           exts=sorted(UPLOAD_EXT), max_mb=MAX_UPLOAD // (1024 * 1024))


def student_tasks(uid):
    me = db.query_one("SELECT department_id, year_no, section_id FROM users WHERE id=%s", (uid,))
    rows = db.query(
        "SELECT t.id, t.title, t.description, t.due_date, t.max_marks, sb.code AS subject_code, sb.name AS subject_name, "
        "sub.id AS sub_id, sub.file_name, sub.uploaded_at, sub.is_late, sub.marks, sub.feedback "
        "FROM assignment_tasks t JOIN subjects sb ON sb.id=t.subject_id "
        "LEFT JOIN assignment_submissions sub ON sub.task_id=t.id AND sub.student_id=%s "
        "WHERE t.department_id=%s AND t.year_no=%s AND (t.section_id IS NULL OR t.section_id=%s) ORDER BY t.id DESC",
        (uid, me["department_id"], me["year_no"], me["section_id"]))
    today_s = A.today()
    for r in rows:
        r["overdue"] = bool(r["due_date"] and r["due_date"] < today_s)
    return rows


@bp.route("/student/api/assignments/<int:tid>/submit", methods=["POST"])
@need("student")
def student_submit(tid):
    me = _student()
    task = db.query_one("SELECT * FROM assignment_tasks WHERE id=%s AND department_id=%s AND year_no=%s "
                        "AND (section_id IS NULL OR section_id=%s)", (tid, me["department_id"], me["year_no"], me["section_id"]))
    if not task:
        return A.bad("Assignment not found.", 404)
    f = request.files.get("file")
    if not f or not f.filename:
        return A.bad("Choose a file to upload.")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(f.filename))[:100]
    if "." not in name or name.rsplit(".", 1)[1].lower() not in UPLOAD_EXT:
        return A.bad("File type not allowed. Allowed: " + ", ".join(sorted(UPLOAD_EXT)) + ".")
    data = f.read(MAX_UPLOAD + 1)
    if not data:
        return A.bad("The file is empty.")
    if len(data) > MAX_UPLOAD:
        return A.bad(f"File is too large (max {MAX_UPLOAD // (1024 * 1024)} MB).", 413)
    old = db.query_one("SELECT * FROM assignment_submissions WHERE task_id=%s AND student_id=%s", (tid, me["id"]))
    if old and old["marks"] is not None:
        return A.bad("This submission has already been graded and can no longer be replaced.", 409)
    key = f"tasks/{tid}/{me['id']}_{secrets.token_hex(4)}_{name}"
    try:
        storage_put(key, data, mimetypes.guess_type(name)[0] or "application/octet-stream")
    except (OSError, urllib.error.URLError):
        return A.bad("Could not store the file. Please try again.", 502)
    late = 1 if task["due_date"] and A.today() > task["due_date"] else 0
    if old:
        db.execute("UPDATE assignment_submissions SET file_name=%s, file_key=%s, file_size=%s, uploaded_at=%s, is_late=%s "
                   "WHERE id=%s", (name, key, len(data), A.now(), late, old["id"]))
        storage_delete(old["file_key"])
    else:
        db.insert("INSERT INTO assignment_submissions (task_id, student_id, file_name, file_key, file_size, uploaded_at, "
                  "is_late) VALUES (%s,%s,%s,%s,%s,%s,%s)", (tid, me["id"], name, key, len(data), A.now(), late))
    A.audit("assignment_submitted", f"task {tid}")
    return jsonify(ok=True, message="Submitted ✔" + (" (late)" if late else ""))


@bp.route("/student/submissions/<int:sid>/file")
@need("student")
def student_submission_file(sid):
    row = db.query_one("SELECT * FROM assignment_submissions WHERE id=%s AND student_id=%s", (sid, session["uid"]))
    if not row:
        abort(404)
    return _file_response(row)


# ----- faculty side
@bp.route("/faculty/tasks")
@need("faculty")
def faculty_tasks_page():
    return render_template("faculty/tasks.html", me=_faculty(), depts=db.query(
        "SELECT id, code, name FROM departments ORDER BY name"))


def _own_task(tid, me):
    t = db.query_one("SELECT t.*, sb.code AS subject_code, sb.name AS subject_name FROM assignment_tasks t "
                     "JOIN subjects sb ON sb.id=t.subject_id WHERE t.id=%s", (tid,))
    if not t or (t["created_by"] != me["id"] and t["department_id"] != me["department_id"]):
        return None
    return t


@bp.route("/faculty/api/tasks", methods=["GET", "POST"])
@need("faculty")
def faculty_tasks_api():
    me = _faculty()
    if request.method == "GET":
        rows = db.query(
            "SELECT t.id, t.title, t.due_date, t.max_marks, t.year_no, t.section_id, sb.code AS subject_code, "
            "(SELECT s.name FROM sections s WHERE s.id=t.section_id) AS section_name, "
            "(SELECT COUNT(*) FROM assignment_submissions x WHERE x.task_id=t.id) AS submitted, "
            "(SELECT COUNT(*) FROM assignment_submissions x WHERE x.task_id=t.id AND x.marks IS NOT NULL) AS graded "
            "FROM assignment_tasks t JOIN subjects sb ON sb.id=t.subject_id WHERE t.created_by=%s OR t.department_id=%s "
            "ORDER BY t.id DESC LIMIT 200", (me["id"], me["department_id"]))
        return jsonify(ok=True, rows=rows)
    d = _json()
    dept, year, subject = _int(d.get("dept")), _int(d.get("year")), _int(d.get("subject"))
    section = _int(d.get("section")) if str(d.get("section", "")).strip() else None
    if None in (dept, year, subject):
        return A.bad("Select department, year and subject.")
    if not FACULTY_ANY_DEPT and dept != me["department_id"]:
        return A.bad("You can create assignments only for your own department.", 403)
    sub = db.query_one("SELECT id, department_id, year_no FROM subjects WHERE id=%s", (subject,))
    if not sub or sub["department_id"] != dept or sub["year_no"] != year:
        return A.bad("That subject does not belong to the selected department / year.")
    if section and not db.query_one("SELECT id FROM sections WHERE id=%s AND department_id=%s AND year_no=%s",
                                    (section, dept, year)):
        return A.bad("Section not found.")
    title = str(d.get("title", "")).strip()
    if not re.fullmatch(r"[\w &.,'()/\-]{1,120}", title):
        return A.bad("Enter a valid assignment title.")
    mx = _num(d.get("max_marks"), 1, 1000)
    due = _date(d.get("due_date")) if str(d.get("due_date", "")).strip() else None
    if mx is None or (str(d.get("due_date", "")).strip() and not due):
        return A.bad("Check the maximum marks and due date.")
    tid = db.insert("INSERT INTO assignment_tasks (subject_id, department_id, year_no, section_id, title, description, "
                    "due_date, max_marks, created_by, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (subject, dept, year, section, title, str(d.get("description", ""))[:1000] or None, due, mx,
                     me["id"], A.now()))
    A.audit("assignment_task_created", f"task {tid} {title}")
    return jsonify(ok=True, id=tid)


@bp.route("/faculty/api/tasks/<int:tid>", methods=["DELETE"])
@need("faculty")
def faculty_task_delete(tid):
    t = _own_task(tid, _faculty())
    if not t or t["created_by"] != session["uid"]:
        return A.bad("Only the faculty who created an assignment can delete it.", 403)
    for r in db.query("SELECT file_key FROM assignment_submissions WHERE task_id=%s", (tid,)):
        storage_delete(r["file_key"])
    db.execute("DELETE FROM assignment_tasks WHERE id=%s", (tid,))
    A.audit("assignment_task_deleted", str(tid))
    return jsonify(ok=True)


@bp.route("/faculty/api/tasks/<int:tid>/submissions")
@need("faculty")
def faculty_task_submissions(tid):
    t = _own_task(tid, _faculty())
    if not t:
        return A.bad("Assignment not found.", 404)
    subs = {r["student_id"]: r for r in db.query("SELECT * FROM assignment_submissions WHERE task_id=%s", (tid,))}
    out = []
    for s in _class_roster(t["department_id"], t["year_no"], t["section_id"]):
        x = subs.get(s["id"])
        out.append(dict(student_id=s["id"], username=s["username"], name=s["name"], sub_id=x["id"] if x else None,
                        file_name=x["file_name"] if x else None, uploaded_at=x["uploaded_at"] if x else None,
                        is_late=bool(x and x["is_late"]), marks=x["marks"] if x else None,
                        feedback=x["feedback"] if x else None))
    return jsonify(ok=True, task=dict(id=t["id"], title=t["title"], max_marks=t["max_marks"], due_date=t["due_date"],
                                      subject=f"{t['subject_code']} {t['subject_name']}"), rows=out)


@bp.route("/faculty/api/tasks/<int:tid>/grade", methods=["POST"])
@need("faculty")
def faculty_task_grade(tid):
    t = _own_task(tid, _faculty())
    if not t:
        return A.bad("Assignment not found.", 404)
    entries = _json().get("entries")
    if not isinstance(entries, list) or not entries or len(entries) > 400:
        return A.bad("Nothing to save.")
    subs = {r["student_id"]: r for r in db.query("SELECT id, student_id FROM assignment_submissions WHERE task_id=%s",
                                                  (tid,))}
    existing = {r["student_id"] for r in db.query("SELECT student_id FROM assignments WHERE subject_id=%s AND name=%s",
                                                   (t["subject_id"], t["title"]))}
    n = 0
    with db.transaction():
        for e in entries:
            sid = _int(e.get("student_id")) if isinstance(e, dict) else None
            if sid not in subs or str(e.get("marks", "")).strip() == "":
                continue
            m = _num(e["marks"], 0, t["max_marks"])
            if m is None:
                raise ValueError("bad marks")
            db.execute("UPDATE assignment_submissions SET marks=%s, feedback=%s, graded_by=%s, graded_at=%s WHERE id=%s",
                       (m, str(e.get("feedback", ""))[:300] or None, session["username"], A.now(), subs[sid]["id"]),
                       commit=False)
            if sid in existing:       # mirror into the existing "Assignments" marks list the student already sees
                db.execute("UPDATE assignments SET marks=%s, max_marks=%s WHERE student_id=%s AND subject_id=%s AND name=%s",
                           (m, t["max_marks"], sid, t["subject_id"], t["title"]), commit=False)
            else:
                db.execute("INSERT INTO assignments (student_id, subject_id, name, marks, max_marks, created_at) "
                           "VALUES (%s,%s,%s,%s,%s,%s)", (sid, t["subject_id"], t["title"], m, t["max_marks"], A.now()),
                           commit=False)
            n += 1
    A.audit("assignment_graded", f"task {tid} x{n}")
    return jsonify(ok=True, saved=n)


@bp.errorhandler(ValueError)
def _bad_value(_e):
    db.rollback()
    return A.bad("One of the marks is invalid.", 400)


@bp.route("/faculty/submissions/<int:sid>/file")
@need("faculty")
def faculty_submission_file(sid):
    row = db.query_one("SELECT s.* FROM assignment_submissions s WHERE s.id=%s", (sid,))
    if not row or not _own_task(row["task_id"], _faculty()):
        abort(404)
    return _file_response(row)


# =========================================================================== ANNOUNCEMENTS
def visible_announcements(role, me, limit=50):
    sql = ("SELECT id, title, body, audience, pinned, author_name, author_role, created_at FROM announcements WHERE "
           "(expires_on IS NULL OR expires_on >= %s) AND audience IN ('all', %s) "
           "AND (department_id IS NULL OR department_id=%s)")
    args = [A.today(), role, me["department_id"]]
    if role == "student":
        sql += " AND (year_no IS NULL OR year_no=%s)"
        args.append(me["year_no"])
    return db.query(sql + " ORDER BY pinned DESC, id DESC LIMIT %s", tuple(args + [limit]))


@bp.route("/student/announcements")
@need("student")
def student_announcements_page():
    me = _student()
    return render_template("student/announcements.html", me=me, rows=visible_announcements("student", me, 100))


@bp.route("/student/api/announcements")
@need("student")
def student_announcements_api():
    return jsonify(ok=True, rows=visible_announcements("student", _student(), min(20, _int(request.args.get("limit")) or 3)))


@bp.route("/faculty/announcements")
@need("faculty")
def faculty_announcements_page():
    me = _faculty()
    return render_template("faculty/announcements.html", me=me, rows=visible_announcements("faculty", me, 100),
                           mine=db.query("SELECT id, title, body, audience, year_no, created_at FROM announcements "
                                         "WHERE author=%s ORDER BY id DESC LIMIT 50", (me["username"],)))


def _announce_fields(d):
    title, body = str(d.get("title", "")).strip(), str(d.get("body", "")).strip()
    if not (3 <= len(title) <= 150) or not (3 <= len(body) <= 2000):
        return None, "Enter a title (3-150 characters) and a message (3-2000 characters)."
    exp = _date(d.get("expires_on")) if str(d.get("expires_on", "")).strip() else None
    if str(d.get("expires_on", "")).strip() and not exp:
        return None, "Expiry date is invalid."
    return dict(title=title, body=body, expires_on=exp), None


@bp.route("/faculty/api/announcements", methods=["POST"])
@need("faculty")
def faculty_announce_create():
    me, d = _faculty(), _json()
    f, err = _announce_fields(d)
    if err:
        return A.bad(err)
    year = _int(d.get("year")) if str(d.get("year", "")).strip() else None
    aid = db.insert("INSERT INTO announcements (title, body, audience, department_id, year_no, pinned, author, author_name, "
                    "author_role, created_at, expires_on) VALUES (%s,%s,'student',%s,%s,0,%s,%s,'faculty',%s,%s)",
                    (f["title"], f["body"], me["department_id"], year, me["username"], me["name"], A.now(), f["expires_on"]))
    A.audit("announcement_created", f"{aid} {f['title']}")
    return jsonify(ok=True, id=aid)


@bp.route("/faculty/api/announcements/<int:aid>", methods=["DELETE"])
@need("faculty")
def faculty_announce_delete(aid):
    if not db.execute("DELETE FROM announcements WHERE id=%s AND author=%s", (aid, session["username"])):
        return A.bad("Announcement not found (you can delete only your own).", 404)
    A.audit("announcement_deleted", str(aid))
    return jsonify(ok=True)


# =========================================================================== LEAVE / OD
def _date_range(a, b):
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def leave_map(student_ids, day):
    """{student_id: 'OD' | 'Leave'} for approved requests covering `day` (used when a class session closes)."""
    if not student_ids:
        return {}
    rows = db.query("SELECT student_id, kind FROM leave_requests WHERE status='approved' AND from_date<=%s AND to_date>=%s",
                    (day, day))
    ids = set(student_ids)
    return {r["student_id"]: r["kind"] for r in rows if r["student_id"] in ids}


def apply_leave(req):
    """Reflects an approved request in attendance for classes already held.
    OD -> Present (method 'od').  Leave -> stays Absent but is tagged method 'leave' (excused).
    Classes that close later are handled by finalize_session via leave_map()."""
    me = db.query_one("SELECT department_id, year_no, section_id FROM users WHERE id=%s", (req["student_id"],))
    if not me or not me["section_id"]:
        return 0
    sessions = db.query("SELECT DISTINCT subject_id, att_date FROM class_sessions WHERE department_id=%s AND year_no=%s "
                        "AND section_id=%s AND att_date>=%s AND att_date<=%s",
                        (me["department_id"], me["year_no"], me["section_id"], req["from_date"], req["to_date"]))
    n = 0
    for s in sessions:
        if req["kind"] == "OD":
            A.upsert_attendance(req["student_id"], s["subject_id"], "Present", "od", f"od-{req['id']}", s["att_date"])
            n += 1
        else:
            n += db.execute("UPDATE attendance SET method='leave', marked_by=%s WHERE student_id=%s AND subject_id=%s "
                            "AND att_date=%s AND status='Absent'", (f"leave-{req['id']}", req["student_id"],
                                                                   s["subject_id"], s["att_date"]), commit=False)
    return n


@bp.route("/student/leave")
@need("student")
def student_leave_page():
    me = _student()
    rows = db.query("SELECT * FROM leave_requests WHERE student_id=%s ORDER BY id DESC LIMIT 50", (me["id"],))
    return render_template("student/leave.html", me=me, rows=rows, today=A.today())


@bp.route("/student/api/leave", methods=["POST"])
@need("student")
def student_leave_apply():
    d = _json()
    kind, reason = d.get("kind"), str(d.get("reason", "")).strip()
    a, b = _date(d.get("from_date")), _date(d.get("to_date"))
    if kind not in ("Leave", "OD") or not a or not b:
        return A.bad("Choose Leave / OD and valid dates.")
    if b < a or (date.fromisoformat(b) - date.fromisoformat(a)).days > 30:
        return A.bad("To-date must be on or after the from-date (maximum 31 days).")
    if not 5 <= len(reason) <= 300:
        return A.bad("Give a reason (5-300 characters).")
    if db.query_one("SELECT id FROM leave_requests WHERE student_id=%s AND status IN ('pending','approved') "
                    "AND from_date<=%s AND to_date>=%s", (session["uid"], b, a)):
        return A.bad("You already have a request that overlaps these dates.", 409)
    rid = db.insert("INSERT INTO leave_requests (student_id, kind, from_date, to_date, reason, status, created_at) "
                    "VALUES (%s,%s,%s,%s,%s,'pending',%s)", (session["uid"], kind, a, b, reason, A.now()))
    A.audit("leave_applied", f"{rid} {kind} {a}..{b}")
    return jsonify(ok=True, message="Request sent to your faculty for approval.")


@bp.route("/student/api/leave/<int:rid>/cancel", methods=["POST"])
@need("student")
def student_leave_cancel(rid):
    if not db.execute("UPDATE leave_requests SET status='cancelled' WHERE id=%s AND student_id=%s AND status='pending'",
                      (rid, session["uid"])):
        return A.bad("Only pending requests can be cancelled.", 409)
    return jsonify(ok=True)


@bp.route("/faculty/leave")
@need("faculty")
def faculty_leave_page():
    return render_template("faculty/leave.html", me=_faculty())


@bp.route("/faculty/api/leave")
@need("faculty")
def faculty_leave_list():
    me = _faculty()
    st = request.args.get("status", "pending")
    sql = ("SELECT r.*, u.username, u.name, u.year_no, s.name AS section_name FROM leave_requests r "
           "JOIN users u ON u.id=r.student_id LEFT JOIN sections s ON s.id=u.section_id WHERE u.department_id=%s")
    args = [me["department_id"]]
    if st in ("pending", "approved", "rejected", "cancelled"):
        sql += " AND r.status=%s"
        args.append(st)
    return jsonify(ok=True, rows=db.query(sql + " ORDER BY r.id DESC LIMIT 200", tuple(args)))


@bp.route("/faculty/api/leave/<int:rid>/review", methods=["POST"])
@need("faculty")
def faculty_leave_review(rid):
    me, d = _faculty(), _json()
    action, note = d.get("action"), str(d.get("note", "")).strip()[:200] or None
    if action not in ("approve", "reject"):
        return A.bad("Invalid action.")
    if action == "reject" and not note:
        return A.bad("Please give a reason for rejecting.")
    req = db.query_one("SELECT r.*, u.department_id FROM leave_requests r JOIN users u ON u.id=r.student_id "
                       "WHERE r.id=%s", (rid,))
    if not req or req["department_id"] != me["department_id"]:
        return A.bad("Request not found.", 404)
    new = "approved" if action == "approve" else "rejected"
    with db.transaction():
        if not db.execute("UPDATE leave_requests SET status=%s, reviewed_by=%s, reviewed_at=%s, note=%s WHERE id=%s "
                          "AND status='pending'", (new, session["username"], A.now(), note, rid), commit=False):
            return A.bad("This request was already processed.", 409)
        touched = apply_leave(req) if new == "approved" else 0
    A.audit(f"leave_{new}", f"{rid} attendance rows {touched}")
    return jsonify(ok=True, updated=touched)


# =========================================================================== TIMETABLE / EXAMS / HALL TICKET (student)
def student_timetable(me):
    if not me["section_id"]:
        return {}
    grid = {}
    for r in db.query("SELECT t.day_no, t.period_no, t.label, t.room, sb.code, sb.name FROM timetable t "
                      "LEFT JOIN subjects sb ON sb.id=t.subject_id WHERE t.section_id=%s", (me["section_id"],)):
        grid[(r["day_no"], r["period_no"])] = r
    return grid


def student_exams(me):
    return db.query("SELECT e.id, e.exam_type, e.exam_date, e.session, e.venue, sb.code, sb.name FROM exam_schedule e "
                    "JOIN subjects sb ON sb.id=e.subject_id WHERE e.department_id=%s AND e.year_no=%s "
                    "ORDER BY e.exam_date, e.session", (me["department_id"], me["year_no"]))


@bp.route("/student/timetable")
@need("student")
def student_timetable_page():
    me = _student()
    exams = student_exams(me)
    return render_template("student/timetable.html", me=me, grid=student_timetable(me), exams=exams,
                           exam_types=sorted({e["exam_type"] for e in exams}), today_no=date.today().isoweekday(),
                           dues_block=HALLTICKET_BLOCK_DUES)


@bp.route("/student/hallticket.pdf")
@need("student")
def student_hallticket():
    me = _student()
    et = request.args.get("exam_type", "")
    rows = [e for e in student_exams(me) if e["exam_type"] == et]
    if not rows:
        abort(404)
    if HALLTICKET_BLOCK_DUES and any(f["due_amount"] > 0 for f in open_fees() if f["student_id"] == me["id"]):
        return Response("Hall ticket is blocked because fees are pending. Please clear your dues with the accounts office.",
                        status=403, mimetype="text/plain")
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    st = getSampleStyleSheet()
    head = ParagraphStyle("h", parent=st["Title"], fontSize=16, textColor=colors.HexColor("#0b2a5b"), spaceAfter=2)
    sub = ParagraphStyle("s", parent=st["Normal"], alignment=1, fontSize=10)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36,
                            title=f"Hall ticket {me['username']}")
    info = Table([["Name", me["name"], "Register / ID", me["username"]],
                  ["Department", me["dept_name"], "Year / Section", f"{me['year_no'] or '-'} / {me['section_name'] or '-'}"],
                  ["Examination", et, "Issued on", A.today()]], colWidths=[80, 190, 90, 150])
    info.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9),
                              ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3fb")),
                              ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef3fb")),
                              ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold")]))
    data = [["Subject code", "Subject", "Date", "Session", "Venue"]] + [
        [r["code"], r["name"], r["exam_date"], r["session"], r["venue"] or "-"] for r in rows]
    t = Table(data, repeatRows=1, colWidths=[75, 210, 70, 50, 105])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b2a5b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    notes = ["Carry this hall ticket and your college ID card to every examination.",
             "Reach the hall 15 minutes before the session starts (FN / AN as shown).",
             "Mobile phones and unauthorised material are not permitted in the hall."]
    doc.build([Paragraph("Sir Issac College of Engineering and Technology", head), Paragraph("HALL TICKET", sub),
               Spacer(1, 14), info, Spacer(1, 14), t, Spacer(1, 16)]
              + [Paragraph("&bull; " + n, st["Normal"]) for n in notes]
              + [Spacer(1, 48), Table([["Signature of student", "Controller of Examinations"]], colWidths=[260, 260])])
    return pdf_response(f"hallticket_{me['username']}_{et.replace(' ', '')}.pdf", buf.getvalue())


# =========================================================================== RESULTS / CGPA
def grade_for(pct):
    for floor, letter, gp in GRADES:
        if pct >= floor:
            return letter, gp
    return "U", 0


def student_results(student_id):
    rows = db.query("SELECT m.marks, m.max_marks, sb.code, sb.name, sb.semester, sb.credits FROM marks m "
                    "JOIN subjects sb ON sb.id=m.subject_id WHERE m.student_id=%s AND m.exam_type='Semester' "
                    "ORDER BY sb.semester, sb.code", (student_id,))
    sems, assumed = {}, False
    for r in rows:
        pct = 100.0 * r["marks"] / r["max_marks"] if r["max_marks"] else 0.0
        letter, gp = grade_for(pct)
        credits = r["credits"]
        if credits is None:
            credits, assumed = DEFAULT_CREDITS, True
        sems.setdefault(r["semester"] or 0, []).append(dict(
            code=r["code"], name=r["name"], credits=credits, marks=r["marks"], max_marks=r["max_marks"],
            pct=round(pct, 1), grade=letter, gp=gp, passed=pct >= PASS_PCT))
    out, tc, tp = [], 0, 0
    for sem in sorted(sems):
        subs = sems[sem]
        c, p = sum(s["credits"] for s in subs), sum(s["credits"] * s["gp"] for s in subs)
        tc, tp = tc + c, tp + p
        out.append(dict(semester=sem, subjects=subs, credits=c, gpa=round(p / c, 2) if c else 0.0,
                        arrears=sum(1 for s in subs if not s["passed"])))
    return dict(semesters=out, cgpa=round(tp / tc, 2) if tc else None, credits=tc,
                arrears=sum(s["arrears"] for s in out), credits_assumed=assumed)


def build_marksheet_pdf(stu, res, sem=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, Spacer, SimpleDocTemplate, Table, TableStyle
    st = getSampleStyleSheet()
    head = ParagraphStyle("h", parent=st["Title"], fontSize=16, textColor=colors.HexColor("#0b2a5b"), spaceAfter=2)
    sub = ParagraphStyle("s", parent=st["Normal"], alignment=1, fontSize=10)
    small = ParagraphStyle("sm", parent=st["Normal"], fontSize=8, textColor=colors.HexColor("#555"))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36,
                            title=f"Mark sheet {stu['username']}")
    flow = [Paragraph("Sir Issac College of Engineering and Technology", head),
            Paragraph("STATEMENT OF MARKS (PROVISIONAL)", sub), Spacer(1, 12)]
    info = Table([["Name", stu["name"], "Register / ID", stu["username"]],
                  ["Department", stu["dept_name"], "Year", str(stu["year_no"] or "-")]], colWidths=[75, 200, 85, 160])
    info.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 9),
                              ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef3fb")),
                              ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#eef3fb"))]))
    flow += [info, Spacer(1, 12)]
    shown = [s for s in res["semesters"] if sem is None or s["semester"] == sem]
    for s in shown:
        flow.append(Paragraph(f"<b>Semester {s['semester'] or '-'}</b> &nbsp; GPA: <b>{s['gpa']:.2f}</b>", st["Normal"]))
        data = [["Code", "Subject", "Credits", "Marks", "%", "Grade", "Result"]] + [
            [x["code"], x["name"][:42], x["credits"], f"{x['marks']:g}/{x['max_marks']:g}", f"{x['pct']:.1f}", x["grade"],
             "PASS" if x["passed"] else "RE-APPEAR"] for x in s["subjects"]]
        t = Table(data, repeatRows=1, colWidths=[60, 205, 45, 60, 40, 40, 70])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0b2a5b")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                               ("FONTSIZE", (0, 0), (-1, -1), 8),
                               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fb")])]))
        flow += [Spacer(1, 4), t, Spacer(1, 12)]
    if not shown:
        flow.append(Paragraph("No published Semester results yet.", st["Normal"]))
    if res["cgpa"] is not None:
        flow.append(Paragraph(f"<b>CGPA (all semesters): {res['cgpa']:.2f}</b> &nbsp; | &nbsp; Credits: {res['credits']} "
                              f"&nbsp; | &nbsp; Arrears: {res['arrears']}", st["Normal"]))
    scale = " &nbsp;".join(f"{g}: &ge;{f}%" for f, g, _ in GRADES) + f" &nbsp; U: &lt;{int(GRADES[-1][0])}%"
    flow += [Spacer(1, 10), Paragraph("Grade scale on Semester exam percentage - " + scale, small),
             Paragraph("GPA = sum(credits x grade point) / sum(credits).  " + (
                 f"Subjects without credits are counted as {DEFAULT_CREDITS} credits. " if res["credits_assumed"] else "")
                 + f"Generated on {A.now()}. Computer-generated and provisional; the university statement prevails.", small)]
    doc.build(flow)
    return buf.getvalue()


@bp.route("/student/results")
@need("student")
def student_results_page():
    me = _student()
    return render_template("student/results.html", me=me, res=student_results(me["id"]), grades=GRADES)


@bp.route("/student/results/marksheet.pdf")
@need("student")
def student_marksheet():
    me = _student()
    sem = _int(request.args.get("sem")) if request.args.get("sem", "") != "" else None
    return pdf_response(f"marksheet_{me['username']}.pdf", build_marksheet_pdf(me, student_results(me["id"]), sem))


def init(app_globals):
    """Called once from app.py after all routes/helpers exist."""
    _G.update(app_globals)
    import features_admin  # noqa: F401  (attaches the admin routes to the same blueprint)
    import modules  # noqa: F401  (study materials, faculty feedback, library)
    app_globals["app"].register_blueprint(bp)
