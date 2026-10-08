# SINCET – Smart Attendance & Student Performance Monitoring System

Flask + **Supabase (PostgreSQL)** (MySQL still supported). **No camera, no face recognition, no extra hardware.**

## Three completely separate portals
| Portal | URL | Notes |
|---|---|---|
| Student | `/student/login` | sees only own profile, attendance, marks, insights |
| Faculty | `/faculty/login` | own profile, run attendance sessions, class reports |
| **Admin** | **secret URL** (printed when the server starts, stored in `.admin_path`) | never linked from any page; `/admin/...` returns 404 to everyone not signed in as admin |

Each portal has its own login page **and its own session cookie**, so a student, a faculty member and the admin can be
signed in at the same time in one browser without ever sharing a session. A faculty account cannot sign in on the student
page (and vice-versa).

Admin hardening: change the secret URL with `ADMIN_LOGIN_PATH=my-private-slug`, and optionally restrict to your office
network with `ADMIN_ALLOWED_IPS=192.168.1.10,192.168.1.11`. First run creates the admin from `ADMIN_USERNAME`
(default `admin`) / `ADMIN_PASSWORD`; if you don't set a password a random one is printed once in the console.

## How attendance works - the AI attendance engine (automatic, hardware-free)
Faculty presses **Start AI attendance** (Dept → Year → Section → Subject; optional classroom GPS lock). Students just sign in
on their own phone and keep the page open - nobody types anything. Every ~20 s the student page sends a presence beacon and the
engine produces an explainable **confidence score (0-100)**:

| Signal | Points |
|---|---|
| Registered phone (device binding) | 25 (15 for a brand-new phone, registered on first success) |
| Place proof: GPS inside the class area (50 if accurate, 35 if coarse) / same campus network as faculty (+20) / valid class code (+50) | up to 50 |
| Steady presence for 60 s (3+ beacons) | up to 25 |
| Penalties | impossible location jump -40, frozen/mock GPS -30 |

Decision: **≥ 90 → AI marks Present by itself** · **60-89 after a fair observation time, or any suspicious flag → faculty review
queue** · otherwise keep verifying. Hard blocks (never auto): attendance attempted from a phone registered to another student, or one
phone used by two students in the same class. Faculty only touches the **review queue** (Approve / Reject, even after the session
has closed). When the session ends (or its timer expires) everybody not marked is set to Absent automatically.

Proxy detection flags (shown to faculty with the reason): `device_mismatch`, `shared_device`, `teleport`, `static_gps`,
`outside_area`, `code_far_away`, `code_guessing`. A rotating 6-digit class code (changes every 15 s) remains as a backup for a student whose GPS fails.

Honest limits: this is a rule-based, explainable scoring engine (no camera/biometrics); a determined cheater with a spoofed GPS
and a cloned browser profile is *reduced*, not eliminated - which is why doubtful cases go to the faculty. The student's page must
stay open during the class. Browser GPS needs **HTTPS** (or localhost); without GPS only "same network" + registered phone are
available and those cases go to review.

## Connect to Supabase (database)
1. Supabase > **SQL Editor** > New query > paste `supabase_schema.sql` > **Run** (creates all tables with Row Level Security on).
   *(Optional - the app also creates the tables itself on first start.)*
2. Supabase > **Project Settings > Database > Connection string > URI** - copy it.
3. `cp .env.example .env`, paste it as `DATABASE_URL=...` (put your DB password in place of `[YOUR-PASSWORD]`).
4. `pip install -r requirements.txt` then `python app.py`. When `DATABASE_URL` is set the app uses Supabase; otherwise MySQL.

## Fees (student -> admin)
* Admin > **Fees & Payments > Assign fee**: charge a fee to one student or to a whole department / year.
* Student dashboard > **Fees > Pay**: enter amount, method and the UPI/bank transaction reference. Partial payments allowed.
* The payment appears instantly in Admin > Fees & Payments (status *Pending*); admin clicks **Received** (a receipt number
  `RCP-YYYY-NNNNN` is issued and shown to the student) or **Reject** with a reason. Set `FEE_UPI_ID` so students see where to pay.
* This records and verifies payments; it does not move money itself (no payment gateway such as Razorpay is wired in).

## Assignments
Admin > **Assignments** > Add: student ID, subject, assignment name, marks / out of. Students see them under **Assignments** on their dashboard.

## v7 - new features
All new code lives in `features.py` (student / faculty / payments), `features_admin.py` (admin) and `notify.py`
(SMS / email / WhatsApp). New tables are created automatically on start (and are in `supabase_schema.sql`).
Upgrading a Supabase DB that already has v6 data: run the new `CREATE TABLE` blocks from `supabase_schema.sql`
(or just start the app once) - existing data is untouched.

| Area | Feature | Where |
|---|---|---|
| Faculty | **Bulk marks grid** - pick class + exam (or assignment), type marks for the whole class, Enter/arrow keys to move, one Save | Faculty > Bulk marks entry |
| Faculty | Post assignments, download student uploads, grade (grades also appear in the student's Assignments list) | Faculty > Assignments & grading |
| Faculty | Approve / reject Leave & OD (OD becomes **Present** automatically, also for classes held later) | Faculty > Leave / OD |
| Faculty | Low-attendance list (Excel/PDF/CSV) + alert parents by SMS | Faculty > Low attendance |
| Fees | **Razorpay** checkout, auto-verified (signature check + webhook), receipt issued, admin does nothing | set `PAYMENT_GATEWAY=razorpay` + keys in `.env` |
| Fees | **Receipt PDF** for every *Received* payment (student + admin) | Student > Fees > Payment history |
| Fees | **Due reminders** (email / SMS / WhatsApp) 7, 3, 1, 0 days before due and weekly when overdue | Admin > Reminders & Contacts, `python send_reminders.py`, or `/internal/cron/reminders?token=CRON_TOKEN` |
| Student | Assignment upload (Supabase Storage, or `./uploads` if not configured) | Student > Submit assignments |
| Student | Timetable, exam schedule, **hall ticket PDF** (admin enters them under Timetable & Exams) | Student > Timetable |
| Student | Announcements (admin / faculty -> dashboards) | Student dashboard |
| Student | Leave / OD request | Student > Leave / OD |
| Student | **GPA / CGPA** + mark sheet PDF (from the *Semester* exam marks and subject credits) | Student > Results |
| Admin | Reports: fee collection dept-wise, pending fees, low attendance; **Excel / PDF / CSV** export; alert parents | Admin > Reports & Export |
| Admin | **Role-wise admins**: `super` (all), `accounts` (fees, reminders, fee reports), `exam` (marks, schedule, results, attendance report). New admins must change the generated password at first login | Admin > Admin Roles |
| Admin | **Audit log viewer** (search, filter by actor / action / date, paging, CSV) | Admin > Audit Log |

`python create_admin.py accounts1 Pass#1234 --scope accounts` also creates a role-limited admin from the command line.

### Setup notes
* **Razorpay**: put `PAYMENT_GATEWAY`, `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` in `.env`, and add the webhook
  `https://YOUR-DOMAIN/payments/razorpay/webhook` (events `payment.captured`, `order.paid`) in the Razorpay dashboard. Test with `rzp_test_` keys first.
  PhonePe is not wired in; the gateway code is isolated in `features.py` (`rz_*` functions) if you want to add it.
* **SMS / WhatsApp / email**: fill the `SMTP_*`, `SMS_PROVIDER` / `FAST2SMS_API_KEY` or `TWILIO_*` values. Until configured every message is only
  *logged* (dry run) in Admin > Reminders & Contacts > Message log. In India, SMS needs a DLT-registered sender / template and WhatsApp needs approved templates.
* Student and parent phone / email are entered in Admin > Reminders & Contacts (or imported by CSV).
* **Storage**: create a *private* Supabase bucket `submissions`, set `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service_role key - server only).
* Grading uses an Anna-University style scale (O >= 91 ... C >= 50, U below) on the *Semester* exam percentage - edit `GRADES` in `features.py`.
  Period timings: `PERIOD_TIMES` in `features.py`.
* Faculty can enter marks / post assignments only for their own department (`FACULTY_MARKS_ANY_DEPT=1` lifts this).

## v8 - Study materials, Faculty feedback, Library
All code is in `modules.py`; pages are under `templates/*/materials|feedback|library.html`. New tables are created automatically on start
(and are in `supabase_schema.sql`). Optional demo data: `python seed_demo.py` (also calls `seed_modules.py`).

| Module | Faculty | Student | Admin |
|---|---|---|---|
| **Study materials** | Upload notes per dept / year / section / subject / unit (PDF, DOCX, PPT, ...) and delete own uploads; sees download counts | Sees only material for their own class, filter + search, one-click download | - |
| **Faculty feedback** | **My feedback**: averages for 5 questions + anonymous comments, shown only after `FEEDBACK_MIN_RESPONSES` (default 3) ratings | Rates each faculty 1-5 on 5 questions + comment, once per faculty, only while the survey is open. Ratings are anonymous | Create a survey (class + faculty per subject + closing date), open/close, per-faculty report, **CSV export** |
| **Library** | - | Own issued books, due dates, live fine, history, catalogue search with availability | Catalogue (add / delete, copies, rack), **issue**, **return**, overdue list, fine **paid / waived**, CSV export, stats |

Library rules (env): `LIB_LOAN_DAYS=14`, `LIB_FINE_PER_DAY=2` (rupees), `LIB_MAX_BOOKS=3`. Fine = days late x rate, calculated live for overdue books and fixed on return.
A student with unpaid library fines cannot be issued new books. New admin role **Librarian** (`library`) sees only the Library; the **Exam cell** role also gets Faculty feedback.

## QR attendance
When a faculty starts a session, the **Take attendance** screen shows a **QR code** that changes every 15 s (it encodes the same rotating class code, drawn on the server - no internet/CDN needed).
Students either scan it with the phone's normal **camera app** (opens `/student/scan?c=...` and marks attendance) or press **📷 Scan class QR** on their dashboard.
Scanning goes through the normal check-in, so registered phone, geo-fence, proxy flags and the review queue still apply; a photo of the QR is useless after ~30 s.
The QR contains your server address: for phones to open it, run with `HOST=0.0.0.0` and/or set `QR_BASE_URL=https://your-domain-or-lan-ip:5000` in `.env`. Students must be signed in on that phone (keep the dashboard open).

## Run
1. Python 3.10+ and MySQL 8. `pip install -r requirements.txt`
2. Set DB login (database + tables are created automatically):
   - Windows CMD: `set DB_USER=root` / `set DB_PASSWORD=yourpassword`; PowerShell: `$env:DB_USER="root"; $env:DB_PASSWORD="yourpassword"`
   - Linux/Mac: `export DB_USER=root DB_PASSWORD=yourpassword`
3. `python app.py` – the three URLs (incl. the secret admin URL) are printed.
4. Optional demo data: `python seed_demo.py` (writes `demo_credentials.csv`).

Upgrading an existing database: just start the new version – new tables (`class_sessions`, `session_marks`,
`student_devices`, `presence_state`, `presence_flags`) are created automatically; old data is kept (the unused `face_descriptor` column is simply ignored).

## Add / reset an admin account
`python create_admin.py USERNAME PASSWORD [--name "Full Name"] [--force]`  (creates the admin, or resets the password if it exists).

## Admin features
Dashboard + charts, generate faculty/student accounts (hashed one-time passwords, forced change at first login), manage
users (search/filter/edit/deactivate/reset password/reset device/delete, CSV & PDF export), departments, sections, subjects,
attendance and marks records, generation history. Security: roles, CSRF, lock after 5 failed logins, 15-min idle timeout,
audit log, parameterised SQL.

Production: set `SECRET_KEY`, `COOKIE_SECURE=1` (HTTPS) and run with waitress/gunicorn (single process, as the wrong-code
throttle is in memory).


## Anti-proxy hardening (v9)
* **Location lock is always ON** - faculty can no longer start a session without the classroom GPS position.
* **GPS is mandatory** for every check-in (QR, typed code and the automatic "AI" check-in). No GPS = no attendance, and the student shows up in the faculty *doubtful* list (`no_gps`).
* **College network check** - the student's public IP must be on the college network. Set `CAMPUS_NETWORKS` (comma separated CIDRs/IPs of the college Wi-Fi's public address) in `.env`.
  If it is not set, the student must be on the same /24 network as the faculty who started the class. `NETWORK_CHECK=0` turns it off.
  Behind nginx/Render/etc. also set `TRUST_PROXY=1`, otherwise every user looks like the proxy's IP.
* **QR / code lifetime is 15 s** (a code is accepted for 15-30 s counting one step of grace).
* **Doubtful list**: `off_network`, `no_gps`, `weak_gps`, `code_far_away`, `outside_area`, `device_mismatch`, `shared_device`, `teleport`, `static_gps`, `code_guessing` are all shown to faculty with a plain label.
* Security fix: the automatic check-in no longer trusts a `code_ok` field sent by the browser.

* **QR + AI attendance (default)**: faculty projects the QR (15 s), students also get auto check-in. Set `ATTENDANCE_ALLOW_CODE=0` for AI-only (QR / code endpoints disabled).

* **3-round QR, then automatic Absent**: the QR changes `QR_ROUNDS` (default 3) times, one every `QR_STEP_SECONDS` (default 15 s). After the last QR (plus one step of grace for slow scans) the session closes by itself and every student who has not checked in is marked Absent (approved OD / leave is respected). "Open for" and "+5 min" are hidden in this mode. Set `QR_ROUNDS=0` to go back to timer-based sessions.
