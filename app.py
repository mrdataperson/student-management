import re
import sqlite3
from flask import Flask, request, jsonify
from database import get_db, init_db

app = Flask(__name__)
init_db()

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SORT_COLUMNS = {"id", "name", "email", "age", "course", "created_at"}
REQUIRED_FIELDS = ["name", "email", "age", "course"]


# ---------- helpers ----------
def validate_student(data):
    """Return a list of error messages (empty list = valid)."""
    if not isinstance(data, dict):
        return ["Request body must be a JSON object"]

    errors = []
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"'{field}' is required")
    if errors:
        return errors

    name, email, age, course = (data[f] for f in REQUIRED_FIELDS)

    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        errors.append("'name' must be a non-empty string up to 100 characters")
    if not isinstance(email, str) or not EMAIL_REGEX.match(email.strip()):
        errors.append("'email' must be a valid email address")
    if isinstance(age, bool) or not isinstance(age, int) or not (5 <= age <= 100):
        errors.append("'age' must be an integer between 5 and 100")
    if not isinstance(course, str) or not course.strip() or len(course.strip()) > 100:
        errors.append("'course' must be a non-empty string up to 100 characters")
    return errors


def clean(data):
    return (data["name"].strip(), data["email"].strip().lower(),
            data["age"], data["course"].strip())


def get_json_or_none():
    return request.get_json(silent=True)


# ---------- routes ----------
@app.route("/")
def home():
    return jsonify({"message": "Student API is running"})


@app.route("/students", methods=["GET"])
def list_students():
    search = request.args.get("search", "").strip()
    course = request.args.get("course", "").strip()
    sort = request.args.get("sort", "id")
    order = request.args.get("order", "asc").lower()

    try:
        min_age = request.args.get("min_age", type=int)
        max_age = request.args.get("max_age", type=int)
        page = request.args.get("page", default=1, type=int)
        limit = request.args.get("limit", default=10, type=int)
    except ValueError:
        return jsonify({"error": "Invalid query parameter"}), 400

    if sort not in SORT_COLUMNS or order not in ("asc", "desc"):
        return jsonify({"error": "Invalid sort or order parameter"}), 400
    if page is None or limit is None or page < 1 or not (1 <= limit <= 100):
        return jsonify({"error": "page must be >= 1 and limit between 1 and 100"}), 400

    conditions, params = [], []
    if search:
        conditions.append("(name LIKE ? OR email LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if course:
        conditions.append("LOWER(course) = LOWER(?)")
        params.append(course)
    if min_age is not None:
        conditions.append("age >= ?")
        params.append(min_age)
    if max_age is not None:
        conditions.append("age <= ?")
        params.append(max_age)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    conn = get_db()
    total = conn.execute(f"SELECT COUNT(*) FROM students {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM students {where} ORDER BY {sort} {order} LIMIT ? OFFSET ?",
        params + [limit, (page - 1) * limit],
    ).fetchall()
    conn.close()

    return jsonify({
        "total": total,
        "page": page,
        "limit": limit,
        "students": [dict(r) for r in rows],
    })


@app.route("/students/<int:student_id>", methods=["GET"])
def get_student(student_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": "Student not found"}), 404
    return jsonify(dict(row))


@app.route("/students", methods=["POST"])
def add_student():
    data = get_json_or_none()
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400
    errors = validate_student(data)
    if errors:
        return jsonify({"errors": errors}), 400

    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO students (name, email, age, course) VALUES (?, ?, ?, ?)",
            clean(data),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM students WHERE id = ?", (cur.lastrowid,)).fetchone()
    except sqlite3.IntegrityError:
        return jsonify({"error": "A student with this email already exists"}), 409
    finally:
        conn.close()
    return jsonify({"message": "Student added", "student": dict(row)}), 201


@app.route("/students/<int:student_id>", methods=["PUT"])
def update_student(student_id):
    data = get_json_or_none()
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400
    errors = validate_student(data)
    if errors:
        return jsonify({"errors": errors}), 400

    conn = get_db()
    try:
        if conn.execute("SELECT id FROM students WHERE id = ?", (student_id,)).fetchone() is None:
            return jsonify({"error": "Student not found"}), 404
        conn.execute(
            "UPDATE students SET name = ?, email = ?, age = ?, course = ? WHERE id = ?",
            clean(data) + (student_id,),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    except sqlite3.IntegrityError:
        return jsonify({"error": "A student with this email already exists"}), 409
    finally:
        conn.close()
    return jsonify({"message": "Student updated", "student": dict(row)})


@app.route("/students/<int:student_id>", methods=["DELETE"])
def delete_student(student_id):
    conn = get_db()
    cur = conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        return jsonify({"error": "Student not found"}), 404
    return jsonify({"message": "Student deleted"})


# ---------- error handlers ----------
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Resource not found"}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(debug=True)