"""Default academic data: sections for every department/year and a separate subject list per department.

Subject strings: "Name" = theory (3 credits), "Name|L" = lab (2 credits), "Name|4" = theory with 4 credits.
Subject code = <DEPT><semester><nn>, e.g. AIDS305 = AI & DS, semester 3, 5th subject.
Year = (semester + 1) // 2.  Admin can edit / add / delete everything afterwards.
"""
import db

SECTIONS = ["A", "B"]          # created for every department and every year (1-4)

_COMMON_1 = ["Communicative English", "Engineering Mathematics I|4", "Engineering Physics", "Engineering Chemistry"]
_COMMON_2 = ["Technical English", "Engineering Mathematics II|4", "Environmental Science"]

CATALOGUE = {
    "AIDS": {
        1: _COMMON_1 + ["Problem Solving using Python|4", "Python Programming Lab|L", "Physics & Chemistry Lab|L"],
        2: _COMMON_2 + ["Data Structures|4", "Digital Principles & Computer Organization", "Data Structures Lab|L", "Engineering Graphics"],
        3: ["Discrete Mathematics", "Database Management Systems|4", "Object Oriented Programming", "Design & Analysis of Algorithms",
            "Artificial Intelligence", "DBMS Lab|L", "OOP Lab|L"],
        4: ["Probability & Statistics", "Operating Systems", "Machine Learning|4", "Data Exploration & Visualization",
            "Computer Networks", "Machine Learning Lab|L", "Data Visualization Lab|L"],
        5: ["Big Data Analytics", "Deep Learning|4", "Natural Language Processing", "Software Engineering", "Cloud Computing",
            "Deep Learning Lab|L", "Big Data Lab|L"],
        6: ["Computer Vision", "Reinforcement Learning", "Data Mining & Warehousing", "Internet of Things", "Professional Elective I",
            "Computer Vision Lab|L", "Mini Project|L"],
        7: ["Generative AI", "Ethics in AI", "Professional Elective II", "Open Elective I", "Project Phase I|L"],
        8: ["Professional Elective III", "Professional Elective IV", "Project Phase II|L"],
    },
    "AIML": {
        1: _COMMON_1 + ["Programming in Python|4", "Python Programming Lab|L", "Physics & Chemistry Lab|L"],
        2: _COMMON_2 + ["Data Structures & Algorithms|4", "Digital Logic & Computer Architecture", "Data Structures Lab|L", "Engineering Graphics"],
        3: ["Discrete Mathematics", "Database Technology|4", "Object Oriented Programming", "Linear Algebra for ML",
            "Foundations of AI", "Database Lab|L", "OOP Lab|L"],
        4: ["Probability & Statistics", "Operating Systems", "Machine Learning Techniques|4", "Python for Data Science",
            "Computer Networks", "Machine Learning Lab|L", "Data Science Lab|L"],
        5: ["Neural Networks & Deep Learning|4", "Natural Language Processing", "Knowledge Engineering", "Software Engineering",
            "Cloud & Edge Computing", "Deep Learning Lab|L", "NLP Lab|L"],
        6: ["Computer Vision", "Reinforcement Learning", "Robotics & Automation", "Big Data Technologies", "Professional Elective I",
            "Computer Vision Lab|L", "Mini Project|L"],
        7: ["Generative AI & LLMs", "AI Ethics & Governance", "Professional Elective II", "Open Elective I", "Project Phase I|L"],
        8: ["Professional Elective III", "Professional Elective IV", "Project Phase II|L"],
    },
    "CSE": {
        1: _COMMON_1 + ["Problem Solving & Programming in C|4", "C Programming Lab|L", "Physics & Chemistry Lab|L"],
        2: _COMMON_2 + ["Data Structures|4", "Digital Principles & System Design", "Data Structures Lab|L", "Engineering Graphics"],
        3: ["Discrete Mathematics", "Database Management Systems|4", "Object Oriented Programming in Java", "Design & Analysis of Algorithms",
            "Computer Organization & Architecture", "DBMS Lab|L", "Java Programming Lab|L"],
        4: ["Probability & Queueing Theory", "Operating Systems|4", "Theory of Computation", "Computer Networks",
            "Software Engineering", "Operating Systems Lab|L", "Networks Lab|L"],
        5: ["Compiler Design", "Artificial Intelligence", "Web Technology", "Cryptography & Network Security",
            "Cloud Computing", "Web Technology Lab|L", "Compiler Lab|L"],
        6: ["Machine Learning", "Mobile Application Development", "Distributed Systems", "Internet of Things",
            "Professional Elective I", "Mobile App Lab|L", "Mini Project|L"],
        7: ["Software Project Management", "Human Values & Ethics", "Professional Elective II", "Open Elective I", "Project Phase I|L"],
        8: ["Professional Elective III", "Professional Elective IV", "Project Phase II|L"],
    },
    "IT": {
        1: _COMMON_1 + ["Programming in C|4", "C Programming Lab|L", "Physics & Chemistry Lab|L"],
        2: _COMMON_2 + ["Data Structures & Algorithms|4", "Digital Electronics", "Data Structures Lab|L", "Engineering Graphics"],
        3: ["Discrete Mathematics", "Database Management Systems|4", "Object Oriented Programming", "Computer Architecture",
            "Information Theory & Coding", "DBMS Lab|L", "OOP Lab|L"],
        4: ["Probability & Statistics", "Operating Systems", "Computer Networks|4", "Web Technology",
            "Software Engineering", "Networks Lab|L", "Web Technology Lab|L"],
        5: ["Data Science & Analytics", "Cloud Computing", "Information Security", "Mobile Computing",
            "Machine Learning", "Full Stack Development Lab|L", "Cloud Lab|L"],
        6: ["Big Data Analytics", "Internet of Things", "Software Testing & Automation", "DevOps",
            "Professional Elective I", "IoT Lab|L", "Mini Project|L"],
        7: ["Blockchain Technology", "Professional Ethics", "Professional Elective II", "Open Elective I", "Project Phase I|L"],
        8: ["Professional Elective III", "Professional Elective IV", "Project Phase II|L"],
    },
    "EEE": {
        1: _COMMON_1 + ["Basic Electrical & Electronics Engineering|4", "Engineering Graphics", "Physics & Chemistry Lab|L"],
        2: _COMMON_2 + ["Circuit Theory|4", "Electromagnetic Fields", "Electric Circuits Lab|L", "Engineering Practices Lab|L"],
        3: ["Transforms & Partial Differential Equations", "Electrical Machines I|4", "Electronic Devices & Circuits", "Digital Logic Circuits",
            "Measurements & Instrumentation", "Electrical Machines Lab I|L", "Electronics Lab|L"],
        4: ["Numerical Methods", "Electrical Machines II|4", "Transmission & Distribution", "Linear Integrated Circuits",
            "Control Systems", "Electrical Machines Lab II|L", "Integrated Circuits Lab|L"],
        5: ["Power System Analysis|4", "Microprocessors & Microcontrollers", "Power Electronics", "Solid State Drives",
            "Professional Elective I", "Power Electronics Lab|L", "Microcontroller Lab|L"],
        6: ["Protection & Switchgear", "Power System Operation & Control", "Renewable Energy Systems", "Embedded Systems",
            "Professional Elective II", "Control & Instrumentation Lab|L", "Mini Project|L"],
        7: ["High Voltage Engineering", "Electric Vehicles", "Professional Elective III", "Open Elective I", "Project Phase I|L"],
        8: ["Professional Elective IV", "Professional Elective V", "Project Phase II|L"],
    },
    "MECH": {
        1: _COMMON_1 + ["Basic Electrical & Electronics Engineering", "Engineering Graphics|4", "Physics & Chemistry Lab|L"],
        2: _COMMON_2 + ["Engineering Mechanics|4", "Engineering Materials", "Workshop Practice Lab|L", "Computer Aided Drafting Lab|L"],
        3: ["Transforms & Partial Differential Equations", "Engineering Thermodynamics|4", "Fluid Mechanics & Machinery", "Manufacturing Technology I",
            "Strength of Materials", "Fluid Mechanics Lab|L", "Manufacturing Lab I|L"],
        4: ["Numerical Methods", "Thermal Engineering|4", "Kinematics of Machinery", "Manufacturing Technology II",
            "Electrical Drives & Controls", "Thermal Engineering Lab|L", "Strength of Materials Lab|L"],
        5: ["Dynamics of Machinery|4", "Design of Machine Elements", "Heat & Mass Transfer", "Metrology & Measurements",
            "Professional Elective I", "Dynamics Lab|L", "Heat Transfer Lab|L"],
        6: ["Finite Element Analysis", "Design of Transmission Systems", "Refrigeration & Air Conditioning", "Mechatronics",
            "Professional Elective II", "CAD/CAM Lab|L", "Mini Project|L"],
        7: ["Power Plant Engineering", "Industrial Engineering & Management", "Professional Elective III", "Open Elective I", "Project Phase I|L"],
        8: ["Professional Elective IV", "Professional Elective V", "Project Phase II|L"],
    },
}


def _parse(item):
    name, _, tag = item.partition("|")
    if tag == "L":
        return name, "Lab", 2
    return name, "Theory", int(tag) if tag.isdigit() else 3


def seed_academics(only_empty=True):
    """Insert default sections + subjects. Idempotent (INSERT IGNORE on unique keys).

    only_empty=True  -> a department that already has subjects (or sections) is left alone, so records the admin
                        deleted are not silently re-created on every server start.
    only_empty=False -> fill in anything missing (used by the admin "Load default data" button).
    Returns (new_sections, new_subjects).
    """
    new_sec = new_sub = 0
    for d in db.query("SELECT id, code FROM departments"):
        if only_empty and db.query_one("SELECT id FROM subjects WHERE department_id=%s LIMIT 1", (d["id"],)):
            continue
        for year in range(1, 5):
            for name in SECTIONS:
                new_sec += db.execute("INSERT IGNORE INTO sections (department_id, year_no, name) VALUES (%s,%s,%s)",
                                      (d["id"], year, name), commit=False)
        plan = CATALOGUE.get(d["code"], {})
        for sem, items in plan.items():
            year = (sem + 1) // 2
            for i, item in enumerate(items, 1):
                name, kind, credits = _parse(item)
                new_sub += db.execute(
                    "INSERT IGNORE INTO subjects (department_id, year_no, semester, code, name, kind, credits) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (d["id"], year, sem, f"{d['code']}{sem}{i:02d}", name, kind, credits), commit=False)
    db.commit()
    return new_sec, new_sub
