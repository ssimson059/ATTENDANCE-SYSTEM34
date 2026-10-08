-- SINCET portal - Supabase / PostgreSQL schema
-- Paste this whole file into Supabase > SQL Editor > New query > Run.
-- (The app also creates these tables automatically on first start when DATABASE_URL is set.)

CREATE TABLE IF NOT EXISTS admins (
  id SERIAL PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  full_name VARCHAR(100) NOT NULL,
  scope VARCHAR(20) NOT NULL DEFAULT 'super',
  failed_attempts INT NOT NULL DEFAULT 0,
  locked_until TIMESTAMP NULL,
  last_login TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS departments (
  id SERIAL PRIMARY KEY,
  code VARCHAR(10) NOT NULL UNIQUE,
  name VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS sections (
  id SERIAL PRIMARY KEY,
  department_id INT NOT NULL,
  year_no INT NOT NULL,
  name VARCHAR(10) NOT NULL,
  UNIQUE (department_id, year_no, name),
  FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE TABLE IF NOT EXISTS subjects (
  id SERIAL PRIMARY KEY,
  department_id INT NOT NULL,
  year_no INT NOT NULL,
  semester INT NULL,
  code VARCHAR(20) NOT NULL UNIQUE,
  name VARCHAR(120) NOT NULL,
  kind VARCHAR(10) NOT NULL DEFAULT 'Theory',
  credits INT NULL,
  FOREIGN KEY (department_id) REFERENCES departments(id)
);

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  role VARCHAR(10) NOT NULL,
  department_id INT NOT NULL,
  year_no INT NULL,
  section_id INT NULL,
  username VARCHAR(40) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  status VARCHAR(10) NOT NULL DEFAULT 'active',
  must_change_password SMALLINT NOT NULL DEFAULT 1,
  failed_attempts INT NOT NULL DEFAULT 0,
  locked_until TIMESTAMP NULL,
  last_login TIMESTAMP NULL,
  created_at TIMESTAMP NOT NULL,
  created_by VARCHAR(50) NOT NULL,
  FOREIGN KEY (department_id) REFERENCES departments(id),
  FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS sequences (
  role VARCHAR(10) NOT NULL,
  dept_code VARCHAR(10) NOT NULL,
  last_no INT NOT NULL DEFAULT 0,
  PRIMARY KEY (role, dept_code)
);

CREATE TABLE IF NOT EXISTS generation_history (
  id SERIAL PRIMARY KEY,
  batch_id VARCHAR(20) NOT NULL,
  user_id INT NULL,
  username VARCHAR(40) NOT NULL,
  role VARCHAR(10) NOT NULL,
  department_code VARCHAR(10) NOT NULL,
  generated_by VARCHAR(50) NOT NULL,
  generated_at TIMESTAMP NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS attendance (
  id SERIAL PRIMARY KEY,
  student_id INT NOT NULL,
  subject_id INT NOT NULL,
  att_date DATE NOT NULL,
  status VARCHAR(10) NOT NULL,
  method VARCHAR(10) NOT NULL DEFAULT 'manual',
  marked_by VARCHAR(50) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  UNIQUE (student_id, subject_id, att_date),
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS marks (
  id SERIAL PRIMARY KEY,
  student_id INT NOT NULL,
  subject_id INT NOT NULL,
  exam_type VARCHAR(30) NOT NULL,
  marks DECIMAL(5,2) NOT NULL,
  max_marks DECIMAL(5,2) NOT NULL DEFAULT 100,
  created_at TIMESTAMP NOT NULL,
  UNIQUE (student_id, subject_id, exam_type),
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_log (
  id SERIAL PRIMARY KEY,
  actor VARCHAR(50) NOT NULL,
  action VARCHAR(60) NOT NULL,
  detail VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS class_sessions (
  id SERIAL PRIMARY KEY,
  faculty_id INT NOT NULL,
  subject_id INT NOT NULL,
  department_id INT NOT NULL,
  year_no INT NOT NULL,
  section_id INT NOT NULL,
  att_date DATE NOT NULL,
  secret VARCHAR(64) NOT NULL,
  started_at TIMESTAMP NOT NULL,
  ends_at TIMESTAMP NOT NULL,
  closed_at TIMESTAMP NULL,
  status VARCHAR(10) NOT NULL DEFAULT 'open',
  lat DOUBLE PRECISION NULL,
  lon DOUBLE PRECISION NULL,
  radius_m INT NULL,
  faculty_ip VARCHAR(45) NULL,
  FOREIGN KEY (faculty_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
  FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS session_marks (
  id SERIAL PRIMARY KEY,
  session_id INT NOT NULL,
  student_id INT NOT NULL,
  device_hash VARCHAR(64) NOT NULL,
  distance_m INT NULL,
  marked_at TIMESTAMP NOT NULL,
  UNIQUE (session_id, student_id),
  UNIQUE (session_id, device_hash),
  FOREIGN KEY (session_id) REFERENCES class_sessions(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS student_devices (
  student_id INT NOT NULL PRIMARY KEY,
  device_hash VARCHAR(64) NOT NULL UNIQUE,
  bound_at TIMESTAMP NOT NULL,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS presence_state (
  session_id INT NOT NULL,
  student_id INT NOT NULL,
  device_hash VARCHAR(64) NULL,
  first_ok_ts DOUBLE PRECISION NULL,
  last_ts DOUBLE PRECISION NOT NULL,
  ok_count INT NOT NULL DEFAULT 0,
  same_count INT NOT NULL DEFAULT 0,
  jitter_count INT NOT NULL DEFAULT 0,
  last_lat DOUBLE PRECISION NULL,
  last_lon DOUBLE PRECISION NULL,
  score INT NOT NULL DEFAULT 0,
  decision VARCHAR(10) NOT NULL DEFAULT 'pending',
  reasons VARCHAR(400) NULL,
  review VARCHAR(10) NULL,
  PRIMARY KEY (session_id, student_id),
  FOREIGN KEY (session_id) REFERENCES class_sessions(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS presence_flags (
  id SERIAL PRIMARY KEY,
  session_id INT NOT NULL,
  student_id INT NOT NULL,
  kind VARCHAR(30) NOT NULL,
  detail VARCHAR(200) NULL,
  created_at TIMESTAMP NOT NULL,
  UNIQUE (session_id, student_id, kind),
  FOREIGN KEY (session_id) REFERENCES class_sessions(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fees (
  id SERIAL PRIMARY KEY,
  student_id INT NOT NULL,
  title VARCHAR(120) NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  due_date DATE NULL,
  created_by VARCHAR(50) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS fee_payments (
  id SERIAL PRIMARY KEY,
  fee_id INT NOT NULL,
  student_id INT NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  method VARCHAR(20) NOT NULL,
  reference VARCHAR(60) NULL,
  status VARCHAR(12) NOT NULL DEFAULT 'pending',
  paid_at TIMESTAMP NOT NULL,
  receipt_no VARCHAR(30) NULL UNIQUE,
  reviewed_by VARCHAR(50) NULL,
  reviewed_at TIMESTAMP NULL,
  note VARCHAR(200) NULL,
  FOREIGN KEY (fee_id) REFERENCES fees(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assignments (
  id SERIAL PRIMARY KEY,
  student_id INT NOT NULL,
  subject_id INT NOT NULL,
  name VARCHAR(120) NOT NULL,
  marks DECIMAL(5,2) NOT NULL,
  max_marks DECIMAL(5,2) NOT NULL DEFAULT 100,
  created_at TIMESTAMP NOT NULL,
  UNIQUE (student_id, subject_id, name),
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS student_contacts (
  student_id INT NOT NULL PRIMARY KEY,
  phone VARCHAR(20) NULL,
  email VARCHAR(120) NULL,
  parent_phone VARCHAR(20) NULL,
  parent_email VARCHAR(120) NULL,
  updated_at TIMESTAMP NOT NULL,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS outbox (
  id SERIAL PRIMARY KEY,
  channel VARCHAR(10) NOT NULL,
  recipient VARCHAR(120) NOT NULL,
  subject VARCHAR(150) NULL,
  body VARCHAR(1000) NOT NULL,
  kind VARCHAR(30) NOT NULL,
  ref VARCHAR(40) NULL,
  status VARCHAR(10) NOT NULL,
  error VARCHAR(250) NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS gateway_orders (
  id SERIAL PRIMARY KEY,
  fee_id INT NOT NULL,
  student_id INT NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  provider VARCHAR(15) NOT NULL,
  order_id VARCHAR(60) NOT NULL UNIQUE,
  gateway_payment_id VARCHAR(60) NULL,
  status VARCHAR(10) NOT NULL DEFAULT 'created',
  payment_row_id INT NULL,
  created_at TIMESTAMP NOT NULL,
  paid_at TIMESTAMP NULL,
  FOREIGN KEY (fee_id) REFERENCES fees(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assignment_tasks (
  id SERIAL PRIMARY KEY,
  subject_id INT NOT NULL,
  department_id INT NOT NULL,
  year_no INT NOT NULL,
  section_id INT NULL,
  title VARCHAR(120) NOT NULL,
  description VARCHAR(1000) NULL,
  due_date DATE NULL,
  max_marks DECIMAL(5,2) NOT NULL DEFAULT 100,
  created_by INT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
  FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
  FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assignment_submissions (
  id SERIAL PRIMARY KEY,
  task_id INT NOT NULL,
  student_id INT NOT NULL,
  file_name VARCHAR(160) NOT NULL,
  file_key VARCHAR(240) NOT NULL,
  file_size INT NOT NULL,
  uploaded_at TIMESTAMP NOT NULL,
  is_late SMALLINT NOT NULL DEFAULT 0,
  marks DECIMAL(5,2) NULL,
  feedback VARCHAR(300) NULL,
  graded_by VARCHAR(50) NULL,
  graded_at TIMESTAMP NULL,
  UNIQUE (task_id, student_id),
  FOREIGN KEY (task_id) REFERENCES assignment_tasks(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS timetable (
  id SERIAL PRIMARY KEY,
  department_id INT NOT NULL,
  year_no INT NOT NULL,
  section_id INT NOT NULL,
  day_no INT NOT NULL,
  period_no INT NOT NULL,
  subject_id INT NULL,
  label VARCHAR(60) NULL,
  room VARCHAR(30) NULL,
  UNIQUE (section_id, day_no, period_no),
  FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
  FOREIGN KEY (section_id) REFERENCES sections(id) ON DELETE CASCADE,
  FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS exam_schedule (
  id SERIAL PRIMARY KEY,
  department_id INT NOT NULL,
  year_no INT NOT NULL,
  subject_id INT NOT NULL,
  exam_type VARCHAR(30) NOT NULL,
  exam_date DATE NOT NULL,
  session VARCHAR(2) NOT NULL DEFAULT 'FN',
  venue VARCHAR(60) NULL,
  UNIQUE (subject_id, exam_type),
  FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
  FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS announcements (
  id SERIAL PRIMARY KEY,
  title VARCHAR(150) NOT NULL,
  body VARCHAR(2000) NOT NULL,
  audience VARCHAR(10) NOT NULL DEFAULT 'all',
  department_id INT NULL,
  year_no INT NULL,
  pinned SMALLINT NOT NULL DEFAULT 0,
  author VARCHAR(50) NOT NULL,
  author_name VARCHAR(100) NOT NULL,
  author_role VARCHAR(10) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  expires_on DATE NULL
);

CREATE TABLE IF NOT EXISTS leave_requests (
  id SERIAL PRIMARY KEY,
  student_id INT NOT NULL,
  kind VARCHAR(5) NOT NULL,
  from_date DATE NOT NULL,
  to_date DATE NOT NULL,
  reason VARCHAR(300) NOT NULL,
  status VARCHAR(10) NOT NULL DEFAULT 'pending',
  reviewed_by VARCHAR(50) NULL,
  reviewed_at TIMESTAMP NULL,
  note VARCHAR(200) NULL,
  created_at TIMESTAMP NOT NULL,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Upgrading an existing database? Also run:
-- ALTER TABLE admins ADD COLUMN IF NOT EXISTS scope VARCHAR(20) NOT NULL DEFAULT 'super';

-- Row Level Security: blocks Supabase's public REST API (anon key) from reading these tables.
-- The Flask app connects with the database owner role (DATABASE_URL), which is not affected.
ALTER TABLE admins ENABLE ROW LEVEL SECURITY;
ALTER TABLE departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE sequences ENABLE ROW LEVEL SECURITY;
ALTER TABLE generation_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance ENABLE ROW LEVEL SECURITY;
ALTER TABLE marks ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE class_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_marks ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE presence_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE presence_flags ENABLE ROW LEVEL SECURITY;
ALTER TABLE fees ENABLE ROW LEVEL SECURITY;
ALTER TABLE fee_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE student_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE gateway_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignment_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignment_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE timetable ENABLE ROW LEVEL SECURITY;
ALTER TABLE exam_schedule ENABLE ROW LEVEL SECURITY;
ALTER TABLE announcements ENABLE ROW LEVEL SECURITY;
ALTER TABLE leave_requests ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS study_materials (
  id SERIAL PRIMARY KEY,
  subject_id INT NOT NULL,
  department_id INT NOT NULL,
  year_no INT NOT NULL,
  section_id INT NULL,
  unit_no INT NULL,
  title VARCHAR(150) NOT NULL,
  description VARCHAR(500) NULL,
  file_name VARCHAR(120) NOT NULL,
  file_key VARCHAR(255) NOT NULL,
  file_size INT NOT NULL DEFAULT 0,
  downloads INT NOT NULL DEFAULT 0,
  uploaded_by INT NOT NULL,
  created_at TIMESTAMP NOT NULL,
  FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
  FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE,
  FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback_surveys (
  id SERIAL PRIMARY KEY,
  title VARCHAR(120) NOT NULL,
  department_id INT NOT NULL,
  year_no INT NOT NULL,
  section_id INT NULL,
  closes_on DATE NULL,
  is_open SMALLINT NOT NULL DEFAULT 1,
  created_by VARCHAR(50) NOT NULL,
  created_at TIMESTAMP NOT NULL,
  FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback_items (
  id SERIAL PRIMARY KEY,
  survey_id INT NOT NULL,
  faculty_id INT NOT NULL,
  subject_id INT NOT NULL,
  UNIQUE (survey_id, faculty_id, subject_id),
  FOREIGN KEY (survey_id) REFERENCES feedback_surveys(id) ON DELETE CASCADE,
  FOREIGN KEY (faculty_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback_responses (
  id SERIAL PRIMARY KEY,
  item_id INT NOT NULL,
  student_id INT NOT NULL,
  q1 INT NOT NULL,
  q2 INT NOT NULL,
  q3 INT NOT NULL,
  q4 INT NOT NULL,
  q5 INT NOT NULL,
  comment VARCHAR(500) NULL,
  created_at TIMESTAMP NOT NULL,
  UNIQUE (item_id, student_id),
  FOREIGN KEY (item_id) REFERENCES feedback_items(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS lib_books (
  id SERIAL PRIMARY KEY,
  accession_no VARCHAR(30) NOT NULL UNIQUE,
  isbn VARCHAR(20) NULL,
  title VARCHAR(200) NOT NULL,
  author VARCHAR(120) NOT NULL,
  category VARCHAR(60) NOT NULL DEFAULT 'General',
  rack VARCHAR(20) NULL,
  copies INT NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS lib_issues (
  id SERIAL PRIMARY KEY,
  book_id INT NOT NULL,
  student_id INT NOT NULL,
  issued_on DATE NOT NULL,
  due_on DATE NOT NULL,
  returned_on DATE NULL,
  fine_amount DECIMAL(8,2) NOT NULL DEFAULT 0,
  fine_status VARCHAR(10) NOT NULL DEFAULT 'none',
  issued_by VARCHAR(50) NOT NULL,
  note VARCHAR(200) NULL,
  FOREIGN KEY (book_id) REFERENCES lib_books(id) ON DELETE CASCADE,
  FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE
);

ALTER TABLE study_materials ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_surveys ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE lib_books ENABLE ROW LEVEL SECURITY;
ALTER TABLE lib_issues ENABLE ROW LEVEL SECURITY;
