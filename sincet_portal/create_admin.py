"""Create (or reset the password of) an admin account.

Usage:  python create_admin.py USERNAME PASSWORD [--name "Full Name"] [--scope super|accounts|exam] [--force]

* If USERNAME already exists its password is replaced and any lock is cleared.
* Passwords must be 8+ chars with upper-case, lower-case and a digit; --force skips that check
  (not recommended - then change it later from Admin > Change Password).
"""
import argparse

import app as A
import db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("username")
    ap.add_argument("password")
    ap.add_argument("--name", default=None)
    ap.add_argument("--scope", default="super", choices=["super", "accounts", "exam"],
                    help="super = everything, accounts = fees only, exam = marks/results only")
    ap.add_argument("--force", action="store_true", help="skip the password-strength check")
    a = ap.parse_args()
    if not a.force and A.password_problem(a.password):
        raise SystemExit(f"Weak password: {A.password_problem(a.password)}  (use --force to override)")
    A.bootstrap()
    with A.app.app_context():
        row = db.query_one("SELECT id FROM admins WHERE username=%s", (a.username,))
        if row:
            db.execute("UPDATE admins SET password_hash=%s, failed_attempts=0, locked_until=NULL WHERE id=%s",
                       (A.hash_pw(a.password), row["id"]))
            print(f"Admin '{a.username}' already existed - password updated.")
        else:
            db.insert("INSERT INTO admins (username, password_hash, full_name, scope, created_at) VALUES (%s,%s,%s,%s,%s)",
                      (a.username, A.hash_pw(a.password), a.name or a.username, a.scope, A.now()))
            print(f"Admin '{a.username}' created.")
        with A.app.test_request_context():
            A.audit("create_admin", a.username)
    print("Sign in at the secret admin URL printed by `python app.py` (also stored in .admin_path).")


if __name__ == "__main__":
    main()
