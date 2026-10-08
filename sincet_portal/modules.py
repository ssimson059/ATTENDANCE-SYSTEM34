"""SINCET portal - campus modules (v8).  Routes are attached to features.bp (imported from features.init).

  1. Study materials   faculty uploads notes per subject / class  ->  students of that class download
  2. Faculty feedback  admin opens a survey (faculty x subject)   ->  students rate (anonymous)  ->  admin / faculty reports
  3. Library           admin catalogues books, issues, takes returns, fines  ->  student sees own books, dues, catalogue
"""
import csv
import io
import mimetypes
import os
import re
import secrets
import urllib.error
from datetime import date, datetime, timedelta

from flask import Response, abort, jsonify, render_template, request, session

import db
from features import (A, MAX_UPLOAD, UPLOAD_EXT, _audit, _faculty, _int, _json, _date, _student, bp, need,
                      storage_delete, storage_put, _file_response)

# --------------------------------------------------------------------------- settings
LOAN_DAYS = int(os.getenv("LIB_LOAN_DAYS", "14"))
FINE_PER_DAY = float(os.getenv("LIB_FINE_PER_DAY", "2"))     # rupees
MAX_BOOKS = int(os.getenv("LIB_MAX_BOOKS", "3"))
MIN_RESPONSES = int(os.getenv("FEEDBACK_MIN_RESPONSES", "3"))  # faculty sees a report only after this many ratings
QUESTIONS = [
    ("q1", "Subject knowledge & preparation"),
    ("q2", "Clarity of explanation"),
    ("q3", "Punctuality & syllabus coverage"),
    ("q4", "Interaction & doubt clearing"),
    ("q5", "Overall teaching quality"),
]


def _admin_name():
    return session.get("username", "admin")


def _today():
    return date.today()


def _d(s):
    return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()


def _fmt_size(n):
    return f"{max(1, round(n / 1024))} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


# =========================================================================== 1. STUDY MATERIALS
def _clean_name(f):
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(f.filename or ""))[:100]
    if "." not in name or name.rsplit(".", 1)[1].lower() not in UPLOAD_EXT:
        return None
    return name


@bp.route("/faculty/materials")
@need("faculty")
def faculty_materials_page():
    return render_template("faculty/materials.html", me=_faculty(),
                           depts=db.query("SELECT id, code, name FROM departments ORDER BY name"),
                           exts=sorted(UPLOAD_EXT), max_mb=MAX_UPLOAD // (1024 * 1024))


@bp.route("/faculty/api/materials", methods=["GET", "POST"])
@need("faculty")
def faculty_materials_api():
    me = _faculty()
    if request.method == "GET":
        rows = db.query(
            "SELECT m.id, m.title, m.unit_no, m.file_name, m.file_size, m.downloads, m.year_no, m.created_at, "
            "sb.code AS subject_code, (SELECT s.name FROM sections s WHERE s.id=m.section_id) AS section_name "
            "FROM study_materials m JOIN subjects sb ON sb.id=m.subject_id WHERE m.uploaded_by=%s "
            "ORDER BY m.id DESC LIMIT 200", (me["id"],))
        for r in rows:
            r["size"] = _fmt_size(r["file_size"])
        return jsonify(ok=True, rows=rows)
    f = request.form
    dept, year, subject = _int(f.get("dept")), _int(f.get("year")), _int(f.get("subject"))
    section = _int(f.get("section")) if f.get("section", "").strip() else None
    unit = _int(f.get("unit")) if f.get("unit", "").strip() else None
    if None in (dept, year, subject):
        return A.bad("Select department, year and subject.")
    sub = db.query_one("SELECT id, department_id, year_no FROM subjects WHERE id=%s", (subject,))
    if not sub or sub["department_id"] != dept or sub["year_no"] != year:
        return A.bad("That subject does not belong to the selected department / year.")
    if section and not db.query_one("SELECT id FROM sections WHERE id=%s AND department_id=%s AND year_no=%s",
                                    (section, dept, year)):
        return A.bad("Section not found.")
    if unit is not None and not 1 <= unit <= 10:
        return A.bad("Unit must be between 1 and 10.")
    title = f.get("title", "").strip()
    if not re.fullmatch(r"[\w &.,'()/\-:+]{2,150}", title):
        return A.bad("Enter a valid title.")
    up = request.files.get("file")
    if not up or not up.filename:
        return A.bad("Choose a file to upload.")
    name = _clean_name(up)
    if not name:
        return A.bad("File type not allowed. Allowed: " + ", ".join(sorted(UPLOAD_EXT)) + ".")
    data = up.read(MAX_UPLOAD + 1)
    if not data:
        return A.bad("The file is empty.")
    if len(data) > MAX_UPLOAD:
        return A.bad(f"File is too large (max {MAX_UPLOAD // (1024 * 1024)} MB).", 413)
    key = f"materials/{subject}/{secrets.token_hex(5)}_{name}"
    try:
        storage_put(key, data, mimetypes.guess_type(name)[0] or "application/octet-stream")
    except (OSError, urllib.error.URLError):
        return A.bad("Could not store the file. Please try again.", 502)
    mid = db.insert(
        "INSERT INTO study_materials (subject_id, department_id, year_no, section_id, unit_no, title, description, "
        "file_name, file_key, file_size, uploaded_by, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (subject, dept, year, section, unit, title, f.get("description", "").strip()[:500] or None, name, key,
         len(data), me["id"], A.now()))
    A.audit("material_uploaded", f"{mid} {title}")
    return jsonify(ok=True, id=mid)


@bp.route("/faculty/api/materials/<int:mid>", methods=["DELETE"])
@need("faculty")
def faculty_material_delete(mid):
    row = db.query_one("SELECT * FROM study_materials WHERE id=%s AND uploaded_by=%s", (mid, session["uid"]))
    if not row:
        return A.bad("Material not found.", 404)
    storage_delete(row["file_key"])
    db.execute("DELETE FROM study_materials WHERE id=%s", (mid,))
    A.audit("material_deleted", str(mid))
    return jsonify(ok=True)


@bp.route("/faculty/materials/<int:mid>/file")
@need("faculty")
def faculty_material_file(mid):
    row = db.query_one("SELECT * FROM study_materials WHERE id=%s AND uploaded_by=%s", (mid, session["uid"]))
    if not row:
        abort(404)
    return _file_response(row)


def student_materials(me, subject=None):
    sql = ("SELECT m.id, m.title, m.description, m.unit_no, m.file_name, m.file_size, m.downloads, m.created_at, "
           "sb.id AS subject_id, sb.code AS subject_code, sb.name AS subject_name, u.name AS faculty "
           "FROM study_materials m JOIN subjects sb ON sb.id=m.subject_id JOIN users u ON u.id=m.uploaded_by "
           "WHERE m.department_id=%s AND m.year_no=%s AND (m.section_id IS NULL OR m.section_id=%s)")
    args = [me["department_id"], me["year_no"], me["section_id"]]
    if subject:
        sql += " AND m.subject_id=%s"
        args.append(subject)
    rows = db.query(sql + " ORDER BY sb.code, m.unit_no, m.id DESC", tuple(args))
    for r in rows:
        r["size"] = _fmt_size(r["file_size"])
        r["ext"] = r["file_name"].rsplit(".", 1)[-1].upper()
    return rows


@bp.route("/student/materials")
@need("student")
def student_materials_page():
    me = _student()
    subject = _int(request.args.get("subject", ""))
    rows = student_materials(me)
    subjects = sorted({(r["subject_id"], r["subject_code"], r["subject_name"]) for r in rows}, key=lambda x: x[1])
    return render_template("student/materials.html", me=me, rows=rows, subjects=subjects, sel=subject)


@bp.route("/student/materials/<int:mid>/file")
@need("student")
def student_material_file(mid):
    me = _student()
    row = db.query_one("SELECT * FROM study_materials WHERE id=%s AND department_id=%s AND year_no=%s "
                       "AND (section_id IS NULL OR section_id=%s)",
                       (mid, me["department_id"], me["year_no"], me["section_id"]))
    if not row:
        abort(404)
    db.execute("UPDATE study_materials SET downloads=downloads+1 WHERE id=%s", (mid,))
    return _file_response(row)


# =========================================================================== 2. FACULTY FEEDBACK SURVEY
def _survey_open(s):
    return bool(s["is_open"]) and (not s["closes_on"] or s["closes_on"] >= A.today())


@bp.route("/admin/feedback")
@need("admin")
def admin_feedback_page():
    return render_template("admin/feedback.html", active="feedback", questions=QUESTIONS, min_resp=MIN_RESPONSES,
                           depts=db.query("SELECT id, code, name FROM departments ORDER BY name"))


@bp.route("/admin/api/feedback")
@need("admin")
def admin_feedback_list():
    rows = db.query(
        "SELECT s.*, d.code AS dept, (SELECT sc.name FROM sections sc WHERE sc.id=s.section_id) AS section_name, "
        "(SELECT COUNT(*) FROM feedback_items i WHERE i.survey_id=s.id) AS items, "
        "(SELECT COUNT(*) FROM feedback_responses r JOIN feedback_items i ON i.id=r.item_id WHERE i.survey_id=s.id) AS responses "
        "FROM feedback_surveys s JOIN departments d ON d.id=s.department_id ORDER BY s.id DESC LIMIT 100")
    for r in rows:
        r["live"] = _survey_open(r)
    return jsonify(ok=True, rows=rows)


@bp.route("/admin/api/feedback/setup")
@need("admin")
def admin_feedback_setup():
    dept, year = _int(request.args.get("dept", "")), _int(request.args.get("year", ""))
    if dept is None or year is None:
        return A.bad("Select department and year.")
    return jsonify(
        ok=True,
        sections=db.query("SELECT id, name FROM sections WHERE department_id=%s AND year_no=%s ORDER BY name", (dept, year)),
        subjects=db.query("SELECT id, code, name FROM subjects WHERE department_id=%s AND year_no=%s ORDER BY code", (dept, year)),
        faculty=db.query("SELECT id, name, username FROM users WHERE role='faculty' AND status='active' "
                         "AND department_id=%s ORDER BY name", (dept,)))


@bp.route("/admin/api/feedback", methods=["POST"])
@need("admin")
def admin_feedback_create():
    d = _json()
    title = str(d.get("title", "")).strip()
    dept, year = _int(d.get("dept")), _int(d.get("year"))
    section = _int(d.get("section")) if str(d.get("section", "")).strip() else None
    closes = _date(d.get("closes_on")) if str(d.get("closes_on", "")).strip() else None
    if not re.fullmatch(r"[\w &.,'()/\-:]{3,120}", title) or dept is None or year is None:
        return A.bad("Enter a title and select department and year.")
    if str(d.get("closes_on", "")).strip() and not closes:
        return A.bad("Check the closing date.")
    pairs = []
    for it in d.get("items") or []:
        sid, fid = _int(it.get("subject")), _int(it.get("faculty"))
        if sid is None or fid is None:
            continue
        if not db.query_one("SELECT id FROM subjects WHERE id=%s AND department_id=%s AND year_no=%s", (sid, dept, year)):
            return A.bad("A subject does not belong to this department / year.")
        if not db.query_one("SELECT id FROM users WHERE id=%s AND role='faculty' AND status='active'", (fid,)):
            return A.bad("Faculty member not found.")
        pairs.append((sid, fid))
    if not pairs:
        return A.bad("Pick a faculty member for at least one subject.")
    if section and not db.query_one("SELECT id FROM sections WHERE id=%s AND department_id=%s AND year_no=%s",
                                    (section, dept, year)):
        return A.bad("Section not found.")
    sid_ = db.insert("INSERT INTO feedback_surveys (title, department_id, year_no, section_id, closes_on, is_open, "
                     "created_by, created_at) VALUES (%s,%s,%s,%s,%s,1,%s,%s)",
                     (title, dept, year, section, closes, _admin_name(), A.now()))
    for sub, fac in dict.fromkeys(pairs):
        db.execute("INSERT INTO feedback_items (survey_id, faculty_id, subject_id) VALUES (%s,%s,%s)",
                   (sid_, fac, sub), commit=False)
    db.commit()
    A.audit("feedback_survey_created", f"{sid_} {title}")
    return jsonify(ok=True, id=sid_)


@bp.route("/admin/api/feedback/<int:sid>/toggle", methods=["POST"])
@need("admin")
def admin_feedback_toggle(sid):
    s = db.query_one("SELECT * FROM feedback_surveys WHERE id=%s", (sid,))
    if not s:
        return A.bad("Survey not found.", 404)
    db.execute("UPDATE feedback_surveys SET is_open=%s WHERE id=%s", (0 if s["is_open"] else 1, sid))
    A.audit("feedback_survey_toggled", str(sid))
    return jsonify(ok=True)


@bp.route("/admin/api/feedback/<int:sid>", methods=["DELETE"])
@need("admin")
def admin_feedback_delete(sid):
    db.execute("DELETE FROM feedback_surveys WHERE id=%s", (sid,))
    A.audit("feedback_survey_deleted", str(sid))
    return jsonify(ok=True)


def _eligible(s):
    sql = "SELECT COUNT(*) AS n FROM users WHERE role='student' AND status='active' AND department_id=%s AND year_no=%s"
    args = [s["department_id"], s["year_no"]]
    if s["section_id"]:
        sql += " AND section_id=%s"
        args.append(s["section_id"])
    return db.query_one(sql, tuple(args))["n"]


def feedback_report(sid=None, faculty_id=None, survey=None):
    """Aggregated (anonymous) ratings per survey item."""
    sql = ("SELECT i.id, i.survey_id, i.faculty_id, f.name AS faculty, f.username AS faculty_id_no, sb.code AS subject_code, "
           "sb.name AS subject, sv.title AS survey, COUNT(r.id) AS n, AVG(r.q1) AS q1, AVG(r.q2) AS q2, AVG(r.q3) AS q3, "
           "AVG(r.q4) AS q4, AVG(r.q5) AS q5 FROM feedback_items i JOIN users f ON f.id=i.faculty_id "
           "JOIN subjects sb ON sb.id=i.subject_id JOIN feedback_surveys sv ON sv.id=i.survey_id "
           "LEFT JOIN feedback_responses r ON r.item_id=i.id WHERE 1=1")
    args = []
    if sid:
        sql += " AND i.survey_id=%s"
        args.append(sid)
    if faculty_id:
        sql += " AND i.faculty_id=%s"
        args.append(faculty_id)
    sql += (" GROUP BY i.id, i.survey_id, i.faculty_id, f.name, f.username, sb.code, sb.name, sv.title "
            "ORDER BY i.survey_id DESC, f.name, sb.code")
    out = []
    for r in db.query(sql, tuple(args)):
        n = r["n"] or 0
        avgs = [round(float(r[k]), 2) if n else None for k, _ in QUESTIONS]
        r["avgs"] = avgs
        r["overall"] = round(sum(avgs) / len(avgs), 2) if n else None
        r["comments"] = [c["comment"] for c in db.query(
            "SELECT comment FROM feedback_responses WHERE item_id=%s AND comment IS NOT NULL AND comment<>'' "
            "ORDER BY id DESC LIMIT 30", (r["id"],))] if n else []
        for k, _ in QUESTIONS:
            r.pop(k, None)
        out.append(r)
    return out


@bp.route("/admin/api/feedback/<int:sid>/report")
@need("admin")
def admin_feedback_report(sid):
    s = db.query_one("SELECT * FROM feedback_surveys WHERE id=%s", (sid,))
    if not s:
        return A.bad("Survey not found.", 404)
    return jsonify(ok=True, eligible=_eligible(s), title=s["title"], rows=feedback_report(sid=sid),
                   questions=[q[1] for q in QUESTIONS])


@bp.route("/admin/feedback/<int:sid>/export.csv")
@need("admin")
def admin_feedback_csv(sid):
    s = db.query_one("SELECT * FROM feedback_surveys WHERE id=%s", (sid,))
    if not s:
        abort(404)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Survey", "Faculty", "Faculty ID", "Subject", "Responses", "Eligible"] + [q[1] for q in QUESTIONS] + ["Overall (out of 5)"])
    el = _eligible(s)
    for r in feedback_report(sid=sid):
        w.writerow([r["survey"], r["faculty"], r["faculty_id_no"], f"{r['subject_code']} {r['subject']}", r["n"], el] +
                   [a if a is not None else "" for a in r["avgs"]] + [r["overall"] if r["overall"] is not None else ""])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=feedback_{sid}.csv"})


# ----- student
def student_surveys(me):
    surveys = db.query("SELECT * FROM feedback_surveys WHERE department_id=%s AND year_no=%s "
                       "AND (section_id IS NULL OR section_id=%s) ORDER BY id DESC",
                       (me["department_id"], me["year_no"], me["section_id"]))
    out = []
    for s in surveys:
        s["live"] = _survey_open(s)
        s["rows"] = db.query(
            "SELECT i.id, f.name AS faculty, sb.code AS subject_code, sb.name AS subject, "
            "(SELECT r.id FROM feedback_responses r WHERE r.item_id=i.id AND r.student_id=%s) AS done "
            "FROM feedback_items i JOIN users f ON f.id=i.faculty_id JOIN subjects sb ON sb.id=i.subject_id "
            "WHERE i.survey_id=%s ORDER BY sb.code", (me["id"], s["id"]))
        out.append(s)
    return out


@bp.route("/student/feedback")
@need("student")
def student_feedback_page():
    me = _student()
    return render_template("student/feedback.html", me=me, surveys=student_surveys(me), questions=QUESTIONS)


@bp.route("/student/api/feedback/<int:item_id>", methods=["POST"])
@need("student")
def student_feedback_submit(item_id):
    me = _student()
    it = db.query_one("SELECT i.id, s.* FROM feedback_items i JOIN feedback_surveys s ON s.id=i.survey_id "
                      "WHERE i.id=%s AND s.department_id=%s AND s.year_no=%s AND (s.section_id IS NULL OR s.section_id=%s)",
                      (item_id, me["department_id"], me["year_no"], me["section_id"]))
    if not it:
        return A.bad("Survey not found.", 404)
    if not _survey_open(it):
        return A.bad("This survey is closed.", 409)
    d = _json()
    vals = []
    for k, _ in QUESTIONS:
        v = _int(d.get(k))
        if v is None or not 1 <= v <= 5:
            return A.bad("Please rate every question from 1 to 5.")
        vals.append(v)
    comment = str(d.get("comment", "")).strip()[:500] or None
    try:
        db.insert("INSERT INTO feedback_responses (item_id, student_id, q1, q2, q3, q4, q5, comment, created_at) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (item_id, me["id"], *vals, comment, A.now()))
    except db.IntegrityViolation:
        return A.bad("You have already submitted feedback for this faculty.", 409)
    A.audit("feedback_submitted", f"item {item_id}")          # the audit entry carries no rating
    return jsonify(ok=True, message="Thank you! Your anonymous feedback is recorded ✔")


# ----- faculty (own report only, hidden until enough ratings so nobody can be identified)
@bp.route("/faculty/feedback")
@need("faculty")
def faculty_feedback_page():
    me = _faculty()
    rows = feedback_report(faculty_id=me["id"])
    for r in rows:
        if r["n"] < MIN_RESPONSES:
            r.update(hidden=True, avgs=[None] * len(QUESTIONS), overall=None, comments=[])
    return render_template("faculty/feedback.html", me=me, rows=rows, questions=QUESTIONS, min_resp=MIN_RESPONSES)


# =========================================================================== 3. LIBRARY
def _fine_for(due_on, end=None):
    late = (( end or _today()) - _d(due_on)).days
    return round(max(0, late) * FINE_PER_DAY, 2), max(0, late)


def _decorate_issue(r):
    r["overdue_days"] = 0
    r["live_fine"] = float(r["fine_amount"] or 0)
    if not r["returned_on"]:
        fine, late = _fine_for(r["due_on"])
        r.update(overdue_days=late, live_fine=fine, days_left=(_d(r["due_on"]) - _today()).days)
    return r


ISSUE_SELECT = ("SELECT x.id, x.book_id, x.student_id, x.issued_on, x.due_on, x.returned_on, x.fine_amount, x.fine_status, "
                "b.title, b.author, b.accession_no, u.username, u.name AS student, d.code AS dept, u.year_no "
                "FROM lib_issues x JOIN lib_books b ON b.id=x.book_id JOIN users u ON u.id=x.student_id "
                "JOIN departments d ON d.id=u.department_id")


def books_with_stock(q="", limit=200):
    sql = ("SELECT b.*, b.copies - (SELECT COUNT(*) FROM lib_issues x WHERE x.book_id=b.id AND x.returned_on IS NULL) "
           "AS available FROM lib_books b")
    args = []
    if q:
        sql += " WHERE b.title LIKE %s OR b.author LIKE %s OR b.accession_no LIKE %s OR b.isbn LIKE %s OR b.category LIKE %s"
        args = [f"%{q}%"] * 5
    return db.query(sql + " ORDER BY b.title LIMIT %s", tuple(args + [limit]))


@bp.route("/admin/library")
@need("admin")
def admin_library_page():
    return render_template("admin/library.html", active="library", loan_days=LOAN_DAYS, fine=FINE_PER_DAY, max_books=MAX_BOOKS)


@bp.route("/admin/api/library/stats")
@need("admin")
def admin_library_stats():
    active = db.query(ISSUE_SELECT + " WHERE x.returned_on IS NULL")
    overdue = [r for r in map(_decorate_issue, active) if r["overdue_days"] > 0]
    pending = db.query_one("SELECT COALESCE(SUM(fine_amount),0) AS s, COUNT(*) AS n FROM lib_issues WHERE fine_status='due'")
    return jsonify(ok=True,
                   titles=db.query_one("SELECT COUNT(*) AS n FROM lib_books")["n"],
                   copies=int(db.query_one("SELECT COALESCE(SUM(copies),0) AS n FROM lib_books")["n"]),
                   issued=len(active), overdue=len(overdue),
                   live_fines=round(sum(r["live_fine"] for r in overdue), 2),
                   pending_fines=float(pending["s"]), pending_n=pending["n"])


@bp.route("/admin/api/library/books")
@need("admin")
def admin_library_books():
    return jsonify(ok=True, rows=books_with_stock(request.args.get("q", "").strip()))


@bp.route("/admin/api/library/books", methods=["POST"])
@need("admin")
def admin_library_add_book():
    d = _json()
    title, author = str(d.get("title", "")).strip(), str(d.get("author", "")).strip()
    cat = str(d.get("category", "")).strip() or "General"
    isbn = re.sub(r"[^0-9Xx-]", "", str(d.get("isbn", ""))) or None
    copies = _int(d.get("copies") or 1)
    if not (2 <= len(title) <= 200) or not (2 <= len(author) <= 120) or copies is None or not 1 <= copies <= 500:
        return A.bad("Enter title, author and number of copies (1-500).")
    acc = str(d.get("accession_no", "")).strip()
    if acc and not re.fullmatch(r"[A-Za-z0-9\-/]{2,30}", acc):
        return A.bad("Accession number may contain letters, digits, - and / only.")
    if not acc:
        acc = f"SIN{(db.query_one('SELECT COALESCE(MAX(id),0) AS m FROM lib_books')['m'] + 1):05d}"
    try:
        bid = db.insert("INSERT INTO lib_books (accession_no, isbn, title, author, category, rack, copies, created_at) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (acc, isbn, title, author, cat[:60], str(d.get("rack", "")).strip()[:20] or None, copies, A.now()))
    except db.IntegrityViolation:
        return A.bad("That accession number already exists.", 409)
    A.audit("library_book_added", f"{acc} {title}")
    return jsonify(ok=True, id=bid, accession_no=acc)


@bp.route("/admin/api/library/books/<int:bid>", methods=["DELETE"])
@need("admin")
def admin_library_delete_book(bid):
    if db.query_one("SELECT id FROM lib_issues WHERE book_id=%s AND returned_on IS NULL", (bid,)):
        return A.bad("Copies of this book are still issued. Take them back first.", 409)
    db.execute("DELETE FROM lib_books WHERE id=%s", (bid,))
    A.audit("library_book_deleted", str(bid))
    return jsonify(ok=True)


def student_dues(student_id):
    """(unpaid fines on returned books, live fines on overdue books)"""
    paid_pending = db.query_one("SELECT COALESCE(SUM(fine_amount),0) AS s FROM lib_issues WHERE student_id=%s AND fine_status='due'",
                                (student_id,))["s"]
    live = 0.0
    for r in db.query("SELECT due_on FROM lib_issues WHERE student_id=%s AND returned_on IS NULL", (student_id,)):
        live += _fine_for(r["due_on"])[0]
    return float(paid_pending), round(live, 2)


@bp.route("/admin/api/library/issue", methods=["POST"])
@need("admin")
def admin_library_issue():
    d = _json()
    uname, bid = str(d.get("student", "")).strip(), _int(d.get("book"))
    stu = db.query_one("SELECT id, name, username FROM users WHERE username=%s AND role='student' AND status='active'", (uname,))
    if not stu:
        return A.bad("No active student with that ID.", 404)
    book = next(iter(books_with_stock_by_id(bid)), None) if bid is not None else None
    if not book:
        return A.bad("Select a book.", 404)
    if book["available"] < 1:
        return A.bad("No copy of this book is available right now.", 409)
    if db.query_one("SELECT id FROM lib_issues WHERE book_id=%s AND student_id=%s AND returned_on IS NULL", (bid, stu["id"])):
        return A.bad("This student already has a copy of this book.", 409)
    held = db.query_one("SELECT COUNT(*) AS n FROM lib_issues WHERE student_id=%s AND returned_on IS NULL", (stu["id"],))["n"]
    if held >= MAX_BOOKS:
        return A.bad(f"Limit reached - a student can hold {MAX_BOOKS} books at a time.", 409)
    unpaid, live = student_dues(stu["id"])
    if unpaid + live > 0:
        return A.bad(f"Student has library dues of ₹{unpaid + live:.0f}. Clear the fine before issuing.", 409)
    days = _int(d.get("days")) or LOAN_DAYS
    days = min(max(days, 1), 60)
    due = (_today() + timedelta(days=days)).isoformat()
    iid = db.insert("INSERT INTO lib_issues (book_id, student_id, issued_on, due_on, fine_amount, fine_status, issued_by) "
                    "VALUES (%s,%s,%s,%s,0,'none',%s)", (bid, stu["id"], A.today(), due, _admin_name()))
    A.audit("library_issue", f"{book['accession_no']} -> {stu['username']}")
    return jsonify(ok=True, id=iid, due_on=due, message=f"Issued to {stu['name']} · due {due}")


def books_with_stock_by_id(bid):
    return db.query("SELECT b.*, b.copies - (SELECT COUNT(*) FROM lib_issues x WHERE x.book_id=b.id AND x.returned_on IS NULL) "
                    "AS available FROM lib_books b WHERE b.id=%s", (bid,))


@bp.route("/admin/api/library/return/<int:iid>", methods=["POST"])
@need("admin")
def admin_library_return(iid):
    row = db.query_one("SELECT * FROM lib_issues WHERE id=%s", (iid,))
    if not row or row["returned_on"]:
        return A.bad("Issue record not found or already returned.", 404)
    fine, late = _fine_for(row["due_on"])
    db.execute("UPDATE lib_issues SET returned_on=%s, fine_amount=%s, fine_status=%s WHERE id=%s",
               (A.today(), fine, "due" if fine > 0 else "none", iid))
    A.audit("library_return", f"issue {iid} fine {fine}")
    return jsonify(ok=True, fine=fine, late=late,
                   message=f"Returned{f' · {late} days late, fine ₹{fine:.0f}' if fine else ''}")


@bp.route("/admin/api/library/fine/<int:iid>", methods=["POST"])
@need("admin")
def admin_library_fine(iid):
    action = _json().get("action")
    if action not in ("paid", "waived"):
        return A.bad("Invalid action.")
    n = db.execute("UPDATE lib_issues SET fine_status=%s WHERE id=%s AND fine_status='due'", (action, iid))
    if not n:
        return A.bad("No pending fine on this record.", 404)
    A.audit("library_fine_" + action, str(iid))
    return jsonify(ok=True)


@bp.route("/admin/api/library/issues")
@need("admin")
def admin_library_issues():
    status, q = request.args.get("status", "active"), request.args.get("q", "").strip()
    sql = ISSUE_SELECT + " WHERE 1=1"
    args = []
    if status in ("active", "overdue"):
        sql += " AND x.returned_on IS NULL"
    elif status == "returned":
        sql += " AND x.returned_on IS NOT NULL"
    elif status == "fines":
        sql += " AND x.fine_status='due'"
    if q:
        sql += " AND (u.username LIKE %s OR u.name LIKE %s OR b.title LIKE %s OR b.accession_no LIKE %s)"
        args = [f"%{q}%"] * 4
    rows = [_decorate_issue(r) for r in db.query(sql + " ORDER BY x.id DESC LIMIT 300", tuple(args))]
    if status == "overdue":
        rows = [r for r in rows if r["overdue_days"] > 0]
    return jsonify(ok=True, rows=rows)


@bp.route("/admin/library/issues.csv")
@need("admin")
def admin_library_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Student ID", "Name", "Dept", "Accession", "Title", "Issued", "Due", "Returned", "Fine (Rs)", "Fine status"])
    for r in map(_decorate_issue, db.query(ISSUE_SELECT + " ORDER BY x.id DESC")):
        w.writerow([r["username"], r["student"], r["dept"], r["accession_no"], r["title"], r["issued_on"], r["due_on"],
                    r["returned_on"] or "", r["live_fine"], r["fine_status"]])
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=library_issues.csv"})


@bp.route("/admin/api/library/student")
@need("admin")
def admin_library_student_lookup():
    uname = request.args.get("id", "").strip()
    stu = db.query_one("SELECT u.id, u.name, u.username, u.year_no, d.code AS dept FROM users u JOIN departments d "
                       "ON d.id=u.department_id WHERE u.username=%s AND u.role='student' AND u.status='active'", (uname,))
    if not stu:
        return A.bad("No active student with that ID.", 404)
    held = db.query_one("SELECT COUNT(*) AS n FROM lib_issues WHERE student_id=%s AND returned_on IS NULL", (stu["id"],))["n"]
    unpaid, live = student_dues(stu["id"])
    return jsonify(ok=True, student=stu, holding=held, max_books=MAX_BOOKS, dues=round(unpaid + live, 2))


# ----- student
@bp.route("/student/library")
@need("student")
def student_library_page():
    me = _student()
    mine = [_decorate_issue(r) for r in db.query(ISSUE_SELECT + " WHERE x.student_id=%s ORDER BY x.id DESC", (me["id"],))]
    unpaid, live = student_dues(me["id"])
    return render_template("student/library.html", me=me, current=[r for r in mine if not r["returned_on"]],
                           history=[r for r in mine if r["returned_on"]], unpaid=unpaid, live=live,
                           loan_days=LOAN_DAYS, fine=FINE_PER_DAY, max_books=MAX_BOOKS)


@bp.route("/student/api/library/books")
@need("student")
def student_library_books():
    rows = books_with_stock(request.args.get("q", "").strip(), 60)
    return jsonify(ok=True, rows=[{k: r[k] for k in ("id", "accession_no", "title", "author", "category", "rack", "available", "copies")}
                                  for r in rows])


# =========================================================================== 4. QR ATTENDANCE (opened by scanning the faculty's rotating QR)
@bp.route("/student/scan")
@need("student")
def student_scan_page():
    """The faculty QR encodes /student/scan?c=<rotating 6-digit code>. The page posts it to the normal check-in API,
    so device binding, geo-fence, proxy flags and the faculty review queue all still apply."""
    if not A.ALLOW_CODE:
        abort(404)
    code = request.args.get("c", "")
    return render_template("student/scan.html", me=_student(), code=code if re.fullmatch(r"\d{6}", code) else "")


@bp.route("/faculty/api/session/<int:sid>/qr.svg")
@need("faculty")
def faculty_session_qr(sid):
    """QR of the current rotating class code (drawn server-side with reportlab, so no CDN / internet is needed)."""
    if not A.ALLOW_CODE:
        abort(404)
    import time
    from reportlab.graphics import renderSVG
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    sess = db.query_one("SELECT * FROM class_sessions WHERE id=%s AND faculty_id=%s AND status='open'", (sid, session["uid"]))
    if not sess:
        abort(404)
    w = A.code_window(sess)
    if A.QR_ROUNDS > 0 and w >= A.QR_ROUNDS:
        abort(404)             # all QR rounds are over, nothing left to show
    code = A.code_for(sess["secret"], w)
    base = os.getenv("QR_BASE_URL", "").rstrip("/") or request.host_url.rstrip("/")
    w = QrCodeWidget(f"{base}/student/scan?c={code}", barLevel="M", barBorder=2)
    x0, y0, x1, y1 = w.getBounds()
    size = 300
    d = Drawing(size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    d.add(w)
    return Response(renderSVG.drawToString(d), mimetype="image/svg+xml", headers={"Cache-Control": "no-store"})
