"""Optional demo data for the v8 modules (study materials, feedback survey, library).
Run after seed_demo.py:   python seed_modules.py"""
import random
from datetime import date, timedelta

import app as A
import db
import features
import modules

random.seed(11)
BOOKS = [
    ("Introduction to Algorithms", "Cormen, Leiserson, Rivest, Stein", "Computer Science", "978-0262046305", 3, "R1-A"),
    ("Artificial Intelligence: A Modern Approach", "Stuart Russell, Peter Norvig", "Artificial Intelligence", "978-0134610993", 2, "R1-B"),
    ("Database System Concepts", "Silberschatz, Korth, Sudarshan", "Computer Science", "978-0078022159", 2, "R2-A"),
    ("Operating System Concepts", "Silberschatz, Galvin, Gagne", "Computer Science", "978-1119800361", 2, "R2-B"),
    ("Computer Networks", "Andrew S. Tanenbaum", "Networking", "978-0132126953", 2, "R3-A"),
    ("Pattern Recognition and Machine Learning", "Christopher Bishop", "Artificial Intelligence", "978-0387310732", 1, "R1-C"),
    ("Clean Code", "Robert C. Martin", "Software Engineering", "978-0132350884", 3, "R4-A"),
    ("Engineering Mathematics", "B.S. Grewal", "Mathematics", "978-8174091955", 4, "R5-A"),
    ("Digital Design", "M. Morris Mano", "Electronics", "978-0133072709", 2, "R6-A"),
    ("Wings of Fire", "A.P.J. Abdul Kalam", "Biography", "978-8173711466", 3, "R7-A"),
]


def main():
    A.bootstrap()
    with A.app.app_context():
        for i, (t, a, c, isbn, n, rack) in enumerate(BOOKS, 1):
            if not db.query_one("SELECT id FROM lib_books WHERE title=%s", (t,)):
                db.insert("INSERT INTO lib_books (accession_no, isbn, title, author, category, rack, copies, created_at) "
                          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (f"SIN{i:05d}", isbn, t, a, c, rack, n, A.now()))
        if db.query_one("SELECT id FROM feedback_surveys LIMIT 1"):
            print("Modules demo data already present.")
            return
        stamp = A.now()
        names = ["Dr. R. Meenakshi", "Prof. S. Karthikeyan", "Dr. P. Anitha", "Prof. M. Vijayakumar", "Dr. K. Subramanian", "Prof. L. Deepa"]
        for i, f in enumerate(db.query("SELECT id, name, username FROM users WHERE role='faculty' ORDER BY id")):
            if f["name"] == f["username"] or f["name"].startswith("FAC-"):
                db.execute("UPDATE users SET name=%s WHERE id=%s", (names[i % len(names)], f["id"]))
        for dept in db.query("SELECT * FROM departments"):
            facs = db.query("SELECT id, name FROM users WHERE role='faculty' AND department_id=%s ORDER BY id", (dept["id"],))
            studs = db.query("SELECT id FROM users WHERE role='student' AND department_id=%s AND year_no=2 ORDER BY id", (dept["id"],))
            subs = db.query("SELECT id, code, name FROM subjects WHERE department_id=%s AND year_no=2 ORDER BY code LIMIT 3", (dept["id"],))
            if not (facs and studs and subs):
                continue
            fac = facs[0]
            # study materials
            for n, s in enumerate(subs, 1):
                for unit in (1, 2):
                    name = f"{s['code']}_unit{unit}_notes.txt"
                    key = f"materials/{s['id']}/demo_{name}"
                    features.storage_put(key, f"{s['name']} - Unit {unit} lecture notes (demo file)\n".encode())
                    db.insert("INSERT INTO study_materials (subject_id, department_id, year_no, section_id, unit_no, title, description, "
                              "file_name, file_key, file_size, downloads, uploaded_by, created_at) VALUES (%s,%s,2,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                              (s["id"], dept["id"], unit, f"{s['name']} - Unit {unit} notes",
                               "Lecture notes with solved examples", name, key, 60, random.randint(0, 9), fac["id"], stamp))
            # feedback survey with anonymous responses
            sv = db.insert("INSERT INTO feedback_surveys (title, department_id, year_no, section_id, closes_on, is_open, created_by, created_at) "
                           "VALUES (%s,%s,2,NULL,%s,1,'demo-seed',%s)",
                           ("Mid-term faculty feedback", dept["id"], (date.today() + timedelta(days=10)).isoformat(), stamp))
            comments = ["Explains concepts very clearly.", "Please give more practical examples.", "Good pace, notes are helpful.", None]
            for k, s in enumerate(subs):
                item = db.insert("INSERT INTO feedback_items (survey_id, faculty_id, subject_id) VALUES (%s,%s,%s)", (sv, fac["id"], s["id"]))
                for st in studs[: (len(studs) - 1 if k else len(studs))]:   # last student has not rated the 2nd/3rd subject yet
                    q = [random.choice([3, 4, 4, 5, 5]) for _ in range(5)]
                    db.execute("INSERT INTO feedback_responses (item_id, student_id, q1,q2,q3,q4,q5, comment, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                               (item, st["id"], *q, random.choice(comments), stamp), commit=False)
            db.commit()
            # library activity
            books = db.query("SELECT id FROM lib_books ORDER BY id")
            for j, st in enumerate(studs[:4]):
                b = books[(j + dept["id"]) % len(books)]
                issued = date.today() - timedelta(days=[3, 10, 20, 30][j])
                due = issued + timedelta(days=14)
                db.execute("INSERT INTO lib_issues (book_id, student_id, issued_on, due_on, fine_amount, fine_status, issued_by) VALUES (%s,%s,%s,%s,0,'none','demo-seed')",
                           (b["id"], st["id"], issued.isoformat(), due.isoformat()), commit=False)
            st = studs[-1]
            b = books[(dept["id"] + 5) % len(books)]
            db.execute("INSERT INTO lib_issues (book_id, student_id, issued_on, due_on, returned_on, fine_amount, fine_status, issued_by) VALUES (%s,%s,%s,%s,%s,%s,'due','demo-seed')",
                       (b["id"], st["id"], (date.today() - timedelta(days=40)).isoformat(), (date.today() - timedelta(days=26)).isoformat(), (date.today() - timedelta(days=20)).isoformat(), 12), commit=False)
            db.commit()
    print("Demo data for study materials, feedback and library created.")


if __name__ == "__main__":
    main()
