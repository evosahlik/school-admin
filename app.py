import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import pandas as pd
import io
import uuid
import re


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    filename='app.log',
    format='%(asctime)s - %(levelname)s - %(message)s'
)
handler = RotatingFileHandler('app.log', maxBytes=1000000, backupCount=5)
handler.setFormatter(logging.Formatter('%asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger(__name__)
logger.addHandler(handler)

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default-secret-key')

# Initialize Bcrypt and LoginManager
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

load_dotenv()
supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_KEY')

if not supabase_url or not supabase_key:
    print("Error: SUPABASE_URL and SUPABASE_KEY must be set in .env file")
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env file")

try:
    supabase: Client = create_client(supabase_url, supabase_key)
except Exception as e:
    print(f"Error initializing Supabase client: {str(e)}")
    raise

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_id, email, role, parent_id=None):
        self.id = user_id
        self.email = email
        self.role = role
        self.parent_id = parent_id

@login_manager.user_loader
def load_user(user_id):
    response = supabase.table('users').select('*').eq('user_id', user_id).execute()
    if response.data:
        user_data = response.data[0]
        return User(user_data['user_id'], user_data['email'], user_data['role'], user_data.get('parent_id'))
    return None

# Utility functions
def format_phone(phone):
    if not phone:
        return ""
    digits = ''.join(filter(str.isdigit, phone))
    if len(digits) != 10:
        return phone
    return f"({digits[:3]}){digits[3:6]}-{digits[6:]}"

app.jinja_env.filters['format_phone'] = format_phone

def parse_student_name(name):
    """Parse StudentName into first_name and last_name, handling nicknames."""
    if not name or not isinstance(name, str):
        return None, None
    # Remove leading/trailing spaces and quotes
    name = name.strip().strip('"')
    # Match patterns like "Last, First (Nickname)" or "Last, First"
    match = re.match(r"([^,]+),\s*([^\(]+)(?:\s*\((.+)\))?", name)
    if not match:
        return None, None
    last_name = match.group(1).strip()
    first_name = match.group(2).strip()
    # Use nickname as first_name if present, otherwise keep first_name
    first_name = match.group(3).strip() if match.group(3) else first_name
    return first_name, last_name

def normalize_grade(grade):
    """Normalize Grade to grade_level (e.g., '9th Grade' -> '9', 'Kindergarten' -> 'K')."""
    if not grade or not isinstance(grade, str):
        return None
    grade = grade.strip().lower()
    if 'kindergarten' in grade:
        return 'K'
    # Match '9th Grade', '3rd Grade', etc.
    match = re.match(r"(\d+)(?:st|nd|rd|th)\s*grade", grade)
    if match:
        return match.group(1)
    # Fallback: return as-is if numeric
    if grade.isdigit():
        return grade
    return None

def calculate_student_tuition(grade, days):
    pricing = {
        'K': {'morning': 2000, 'afternoon': 3000},
        '1-2': {'full': 4000, 'enrichment': 1500, 'academic': 2000},
        '3-8': {'full': 4500, 'enrichment': 1700, 'academic': 2200},
        '9-12': {'full': 5000, 'enrichment': 2000, 'academic': 2500}
    }
    total = 0
    grade_key = 'K' if grade == 'K' else '1-2' if grade in ['1', '2'] else '3-8' if grade in [str(i) for i in range(3, 9)] else '9-12'
    for day, type in days.items():
        if type and type in pricing[grade_key]:
            total += pricing[grade_key][type]
    return total

def apply_sibling_discount(total_amount, parent_id, parent_student_count):
    if parent_student_count.get(parent_id, 0) > 1:
        return total_amount * 0.9
    return total_amount

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('students'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        response = supabase.table('users').select('*').eq('email', email).execute()
        if response.data and bcrypt.check_password_hash(response.data[0]['password_hash'], password):
            user = User(response.data[0]['user_id'], response.data[0]['email'], response.data[0]['role'], response.data[0].get('parent_id'))
            login_user(user)
            flash('Logged in successfully', 'success')
            return redirect(request.args.get('next') or url_for('students'))
        flash('Invalid email or password', 'danger')
    return render_template('login.html')

# Logout route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

# Students route
@app.route('/', methods=['GET'])
@app.route('/students', methods=['GET'])
@login_required
def students():
    try:
        students_response = supabase.table('students').select('*').execute()
        parents_response = supabase.table('parents').select('parent_id, first_name, last_name').execute()
        student_parents_response = supabase.table('student_parents').select('student_id, parent_id').execute()

        students_data = sorted(students_response.data, key=lambda x: x['last_name'].lower() if x['last_name'] else '')
        parents_data = parents_response.data
        student_parents_data = student_parents_response.data

        parent_map = {p['parent_id']: p for p in parents_data}
        student_parents_map = {}
        for sp in student_parents_data:
            student_id = sp['student_id']
            parent_id = sp['parent_id']
            if student_id not in student_parents_map:
                student_parents_map[student_id] = []
            if parent_id in parent_map:
                student_parents_map[student_id].append(parent_map[parent_id])

        processed_students = []
        for student in students_data:
            parents = student_parents_map.get(student['student_id'], [])
            if current_user.role == 'parent' and current_user.parent_id not in [p['parent_id'] for p in parents]:
                continue
            student_copy = student.copy()
            student_copy['parents'] = parents
            processed_students.append(student_copy)
        # Removed: print(f"Processed students: {processed_students}")
        # Removed: print("Rendering students tab")
        return render_template('index.html', 
                             active_tab='students', 
                             students=processed_students, 
                             parents=parents_data,
                             user_role=current_user.role)
    except Exception as e:
        flash(f"Error fetching students: {str(e)}")
        logger.error(f"Error fetching students: {str(e)}")
        return render_template('index.html', active_tab='students', students=[], parents=[], user_role=current_user.role)
    
# Add student route
@app.route('/add_student', methods=['POST'])
@login_required
def add_student():
    if current_user.role not in ['admin', 'teacher']:
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        student_id = str(uuid.uuid4())
        data = {
            'student_id': student_id,
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'grade_level': request.form.get('grade_level'),
            'email': request.form.get('email') or None,
            'phone': format_phone(request.form.get('phone')) or None,
            'medicines': request.form.get('medicines') or None,
            'allergies': request.form.get('allergies') or None,
            'medical_conditions': request.form.get('medical_conditions') or None,
            'comments': request.form.get('comments') or None
        }
        if not data['first_name'] or not data['last_name'] or not data['grade_level']:
            flash('First Name, Last Name, and Grade Level are required', 'danger')
            return redirect(url_for('students'))
        # Insert student
        supabase.table('students').insert(data).execute()
        # Insert parent relationships
        parent_ids = request.form.getlist('parent_ids')
        print(f"Adding student {data['first_name']} {data['last_name']}, parent_ids: {parent_ids}")
        if not parent_ids:
            flash('Warning: No parents selected', 'warning')
        valid_parent_ids = supabase.table('parents').select('parent_id').in_('parent_id', parent_ids).execute().data
        valid_parent_ids = [p['parent_id'] for p in valid_parent_ids]
        for parent_id in parent_ids:
            if parent_id and parent_id in valid_parent_ids:
                supabase.table('student_parents').insert({
                    'student_id': student_id,
                    'parent_id': parent_id
                }).execute()
            else:
                print(f"Invalid parent_id: {parent_id}")
        flash('Student added successfully', 'success')
        return redirect(url_for('students'))
    except Exception as e:
        flash(f"Error adding student: {str(e)}", 'danger')
        print(f"Error adding student: {str(e)}")
        return redirect(url_for('students'))

# Edit student route
@app.route('/edit_student', methods=['POST'])
@login_required
def edit_student():
    if current_user.role not in ['admin', 'teacher']:
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        student_id = request.form.get('student_id')
        data = {
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'grade_level': request.form.get('grade_level'),
            'email': request.form.get('email') or None,
            'phone': format_phone(request.form.get('phone')) or None,
            'medicines': request.form.get('medicines') or None,
            'allergies': request.form.get('allergies') or None,
            'medical_conditions': request.form.get('medical_conditions') or None,
            'comments': request.form.get('comments') or None
        }
        if not data['first_name'] or not data['last_name'] or not data['grade_level']:
            flash('First Name, Last Name, and Grade Level are required', 'danger')
            return redirect(url_for('students'))
        # Update student
        supabase.table('students').update(data).eq('student_id', student_id).execute()
        # Update parent relationships
        parent_ids = request.form.getlist('parent_ids')
        logger.info(f"Editing student {student_id}, parent_ids: {parent_ids}")  # Log parent list
        if not parent_ids:
            flash('Warning: No parents selected', 'warning')
        supabase.table('student_parents').delete().eq('student_id', student_id).execute()
        valid_parent_ids = supabase.table('parents').select('parent_id').in_('parent_id', parent_ids).execute().data
        valid_parent_ids = [p['parent_id'] for p in valid_parent_ids]        
        for parent_id in parent_ids:
            if parent_id and parent_id in valid_parent_ids:
                supabase.table('student_parents').insert({
                    'student_id': student_id,
                    'parent_id': parent_id
                }).execute()
            else:
                logger.warning(f"Invalid parent_id: {parent_id}")
        flash('Student updated successfully', 'success')
        return redirect(url_for('students'))
    except Exception as e:
        flash(f"Error updating student: {str(e)}", 'danger')
        logger.error(f"Error updating student: {str(e)}")
        return redirect(url_for('students'))
    
# Delete student route
@app.route('/delete_student/<student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('students'))
    try:
        supabase.table('student_parents').delete().eq('student_id', student_id).execute()
        supabase.table('students').delete().eq('student_id', student_id).execute()
        flash('Student deleted successfully', 'success')
        return redirect(url_for('students'))
    except Exception as e:
        flash(f"Error deleting student: {str(e)}", 'danger')
        print(f"Error deleting student: {str(e)}")
        return redirect(url_for('students'))

# Parents route
@app.route('/parents', methods=['GET'])
@login_required
def parents():
    if current_user.role == 'parent':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        parents_response = supabase.table('parents').select('*').execute()
        sorted_parents = sorted(parents_response.data, key=lambda x: x['last_name'].lower() if x['last_name'] else '')
        # Sanitize parent data for logging (exclude sensitive fields like email, phone)
        parent_summary = [{k: v for k, v in p.items() if k in ['parent_id', 'first_name', 'last_name', 'is_staff']} for p in sorted_parents]
        logger.info(f"Parent tab data: {parent_summary}")
        return render_template('index.html', 
                             active_tab='parents', 
                             parents=sorted_parents,
                             user_role=current_user.role)
    except Exception as e:
        flash(f"Error fetching parents: {str(e)}")
        logger.error(f"Error fetching parents: {str(e)}")
        return render_template('index.html', active_tab='parents', parents=[], user_role=current_user.role)
    
# Add parent route
@app.route('/add_parent', methods=['POST'])
@login_required
def add_parent():
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('parents'))
    try:
        data = {
            'parent_id': str(uuid.uuid4()),
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'email': request.form.get('email') or None,
            'phone': format_phone(request.form.get('phone')) or None,
            'is_staff': 'is_staff' in request.form
        }
        if not data['first_name'] or not data['last_name']:
            flash('First Name and Last Name are required', 'danger')
            return redirect(url_for('parents'))
        supabase.table('parents').insert(data).execute()
        # Log parent addition (sanitized)
        parent_summary = {k: v for k, v in data.items() if k in ['parent_id', 'first_name', 'last_name', 'is_staff']}
        logger.info(f"Added parent: {parent_summary}")
        flash('Parent added successfully', 'success')
        return redirect(url_for('parents'))
    except Exception as e:
        flash(f"Error adding parent: {str(e)}", 'danger')
        logger.error(f"Error adding parent: {str(e)}")
        return redirect(url_for('parents'))
    
# Edit parent route
@app.route('/edit_parent', methods=['POST'])
@login_required
def edit_parent():
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('parents'))
    try:
        parent_id = request.form.get('parent_id')
        data = {
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'email': request.form.get('email') or None,
            'phone': format_phone(request.form.get('phone')) or None,
            'is_staff': 'is_staff' in request.form
        }
        if not data['first_name'] or not data['last_name']:
            flash('First Name and Last Name are required', 'danger')
            return redirect(url_for('parents'))
        supabase.table('parents').update(data).eq('parent_id', parent_id).execute()
        # Log parent edit (sanitized)
        parent_summary = {k: v for k, v in data.items() if k in ['first_name', 'last_name', 'is_staff']}
        parent_summary['parent_id'] = parent_id
        logger.info(f"Edited parent: {parent_summary}")
        flash('Parent updated successfully', 'success')
        return redirect(url_for('parents'))
    except Exception as e:
        flash(f"Error updating parent: {str(e)}", 'danger')
        logger.error(f"Error updating parent: {str(e)}")
        return redirect(url_for('parents'))
    
# Delete parent route
@app.route('/delete_parent/<parent_id>', methods=['POST'])
@login_required
def delete_parent(parent_id):
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('parents'))
    try:
        students = supabase.table('student_parents').select('student_id').eq('parent_id', parent_id).execute()
        if students.data:
            flash('Cannot delete parent with associated students', 'danger')
            return redirect(url_for('parents'))
        supabase.table('parents').delete().eq('parent_id', parent_id).execute()
        logger.info(f"Deleted parent: {parent_id}")
        flash('Parent deleted successfully', 'success')
        return redirect(url_for('parents'))
    except Exception as e:
        flash(f"Error deleting parent: {str(e)}", 'danger')
        logger.error(f"Error deleting parent: {str(e)}")
        return redirect(url_for('parents'))
    
# Import CSV route
@app.route('/import_from_csv', methods=['POST'])
@login_required
def import_from_csv():
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(request.referrer or url_for('students'))
    try:
        print("Starting CSV import")
        if 'file' not in request.files:
            flash('No file uploaded')
            print("Error: No file uploaded")
            return redirect(request.referrer or url_for('students'))
        file = request.files['file']
        if not file.filename.endswith('.csv'):
            flash('Please upload a CSV file')
            print("Error: File is not a CSV")
            return redirect(request.referrer or url_for('students'))

        file_content = file.read()
        print(f"File size: {len(file_content)} bytes")
        if len(file_content) == 0:
            flash('Uploaded file is empty')
            print("Error: Uploaded file is empty")
            return redirect(request.referrer or url_for('students'))

        df = pd.read_csv(io.BytesIO(file_content))
        print(f"CSV headers: {list(df.columns)}")
        print(f"CSV rows: {len(df)}")

        # Normalize column names (strip spaces)
        df.columns = [col.strip() for col in df.columns]

        # Check for students.csv format (StudentName, Grade)
        if 'StudentName' in df.columns and 'Grade' in df.columns:
            table = 'students'
            required = ['StudentName', 'Grade']
            if not all(col in df.columns for col in required):
                flash(f'Missing required columns: {", ".join(r for r in required if r not in df.columns)}')
                print(f"Error: Missing required columns: {', '.join(r for r in required if r not in df.columns)}")
                return redirect(request.referrer or url_for('students'))

            for _, row in df.iterrows():
                first_name, last_name = parse_student_name(row['StudentName'])
                grade_level = normalize_grade(row['Grade'])
                if not first_name or not last_name or not grade_level:
                    print(f"Skipping invalid row: {row.to_dict()}")
                    continue
                data = {
                    'student_id': str(uuid.uuid4()),
                    'first_name': first_name,
                    'last_name': last_name,
                    'grade_level': grade_level,
                    'email': None,
                    'phone': None,
                    'medicines': None,
                    'allergies': None,
                    'medical_conditions': None,
                    'comments': None
                }
                print(f"Inserting student record: {data}")
                supabase.table(table).insert(data).execute()

        # Existing logic for other formats
        else:
            student_mappings = {
                'student_id': ['Student ID', 'ID', 'StudentID'],
                'first_name': ['First Name', 'FirstName', 'Given Name', 'Name', 'StudentName'],
                'last_name': ['Last Name', 'LastName', 'Surname'],
                'grade_level': ['Grade Level', 'Grade', 'Year'],
                'email': ['Email', 'E-mail'],
                'phone': ['Phone', 'Phone Number', 'Contact'],
                'medicines': ['Medicines', 'Medication'],
                'allergies': ['Allergies', 'Allergy'],
                'medical_conditions': ['Medical Conditions', 'Medical', 'Conditions'],
                'comments': ['Comments', 'Notes']
            }
            parent_mappings = {
                'parent_id': ['Parent ID', 'ID', 'ParentID'],
                'first_name': ['First Name', 'FirstName', 'Given Name', 'Name'],
                'last_name': ['Last Name', 'LastName', 'Surname'],
                'email': ['Email', 'E-mail'],
                'phone': ['Phone', 'Phone Number', 'Contact'],
                'is_staff': ['Is Staff', 'Staff', 'Employee']
            }

            table = None
            mappings = None
            parent_headers = ['email', 'phone', 'is_staff']
            if any(any(h.lower() in [m.lower() for m in parent_mappings[field]] for h in df.columns) for field in parent_headers):
                table = 'parents'
                mappings = parent_mappings
            elif any(any(h.lower() == m.lower() for m in student_mappings['first_name']) for h in df.columns):
                table = 'students'
                mappings = student_mappings
            else:
                flash('Invalid CSV: No recognizable First Name or StudentName column')
                print("Error: No recognizable First Name or StudentName column")
                return redirect(request.referrer or url_for('students'))

            column_map = {}
            for supabase_field, possible_headers in mappings.items():
                for header in possible_headers:
                    if header in df.columns or header.lower() in [c.lower() for c in df.columns]:
                        column_map[supabase_field] = next(c for c in df.columns if c.lower() == header.lower())
                        break

            required = ['first_name', 'last_name'] if table == 'parents' else ['first_name', 'last_name', 'grade_level']
            if not all(f in column_map for f in required):
                flash(f'Missing required columns: {", ".join(r for r in required if r not in column_map)}')
                print(f"Error: Missing required columns: {', '.join(r for r in required if r not in column_map)}")
                return redirect(request.referrer or url_for('students'))

            for _, row in df.iterrows():
                data = {}
                for supabase_field, csv_column in column_map.items():
                    value = row[csv_column] if csv_column in row and pd.notna(row[csv_column]) else None
                    if supabase_field == 'first_name' and csv_column == 'StudentName':
                        first_name, last_name = parse_student_name(value)
                        if first_name and last_name:
                            data['first_name'] = first_name
                            data['last_name'] = last_name
                        continue
                    if supabase_field == 'grade_level' and csv_column == 'Grade':
                        data['grade_level'] = normalize_grade(value) if value else None
                    elif supabase_field == 'is_staff':
                        data[supabase_field] = value.lower() in ['yes', 'true', '1'] if value else False
                    elif supabase_field == 'phone':
                        data[supabase_field] = format_phone(str(value)) if value else None
                    else:
                        data[supabase_field] = value

                if 'student_id' not in column_map and table == 'students':
                    data['student_id'] = str(uuid.uuid4())
                if 'parent_id' not in column_map and table == 'parents':
                    data['parent_id'] = str(uuid.uuid4())

                print(f"Inserting {table} record: {data}")
                supabase.table(table).insert(data).execute()

        flash(f"Successfully imported {len(df)} records into {table}")
        print(f"Flashed: Successfully imported {len(df)} records into {table}")
        return redirect(request.referrer or url_for('students'))
    except Exception as e:
        flash(f"Error importing CSV: {str(e)}")
        print(f"Error importing CSV: {str(e)}")
        return redirect(request.referrer or url_for('students'))

# Teachers route
@app.route('/teachers', methods=['GET'])
@login_required
def teachers():
    if current_user.role == 'parent':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        teachers_response = supabase.table('teachers').select('*').execute()
        return render_template('index.html', 
                             active_tab='teachers', 
                             teachers=teachers_response.data,
                             user_role=current_user.role)
    except Exception as e:
        flash(f"Error fetching teachers: {str(e)}")
        print(f"Error fetching teachers: {str(e)}")
        return render_template('index.html', active_tab='teachers', teachers=[], user_role=current_user.role)

# Placeholder teacher routes
# New Add Teacher route
@app.route('/add_teacher', methods=['POST'])
@login_required
def add_teacher():
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('teachers'))
    try:
        data = {
            'teacher_id': str(uuid.uuid4()),
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'email': request.form.get('email') or None,
            'phone': request.form.get('phone') or None
        }
        if not data['first_name'] or not data['last_name']:
            flash('First Name and Last Name are required', 'danger')
            return redirect(url_for('teachers'))
        supabase.table('teachers').insert(data).execute()
        logger.info(f"Added teacher: {data['teacher_id']}, {data['first_name']} {data['last_name']}")
        flash('Teacher added successfully', 'success')
        return redirect(url_for('teachers'))
    except Exception as e:
        flash(f"Error adding teacher: {str(e)}", 'danger')
        logger.error(f"Error adding teacher: {str(e)}")
        return redirect(url_for('teachers'))
    
@app.route('/edit_teacher', methods=['POST'])
@login_required
def edit_teacher():
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('teachers'))
    try:
        teacher_id = request.form.get('teacher_id')
        data = {
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'email': request.form.get('email') or None,
            'phone': request.form.get('phone') or None
        }
        if not data['first_name'] or not data['last_name']:
            flash('First Name and Last Name are required', 'danger')
            return redirect(url_for('teachers'))
        supabase.table('teachers').update(data).eq('teacher_id', teacher_id).execute()
        logger.info(f"Edited teacher: {teacher_id}, {data['first_name']} {data['last_name']}")
        flash('Teacher updated successfully', 'success')
        return redirect(url_for('teachers'))
    except Exception as e:
        flash(f"Error updating teacher: {str(e)}", 'danger')
        logger.error(f"Error updating teacher: {str(e)}")
        return redirect(url_for('teachers'))

@app.route('/delete_teacher/<teacher_id>', methods=['POST'])
@login_required
def delete_teacher(teacher_id):
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('teachers'))
    try:
        # Check if teacher is assigned to any classes
        classes_response = supabase.table('classes').select('class_id').eq('teacher_id', teacher_id).execute()
        if classes_response.data and len(classes_response.data) > 0:
            logger.warning(f"Attempted to delete teacher {teacher_id} assigned to {len(classes_response.data)} classes")
            flash('Cannot delete teacher assigned to classes', 'danger')
            return redirect(url_for('teachers'))
        supabase.table('teachers').delete().eq('teacher_id', teacher_id).execute()
        logger.info(f"Deleted teacher: {teacher_id}")
        flash('Teacher deleted successfully', 'success')
        return redirect(url_for('teachers'))
    except Exception as e:
        flash(f"Error deleting teacher: {str(e)}", 'danger')
        logger.error(f"Error deleting teacher {teacher_id}: {str(e)}")
        return redirect(url_for('teachers'))

# Tuition route
@app.route('/tuition', methods=['GET'])
@login_required
def tuition():
    try:
        tuition_data = []
        return render_template('index.html', 
                             active_tab='tuition', 
                             tuition=tuition_data,
                             user_role=current_user.role)
    except Exception as e:
        flash(f"Error fetching tuition: {str(e)}")
        print(f"Error fetching tuition: {str(e)}")
        return render_template('index.html', active_tab='tuition', tuition=[], user_role=current_user.role)

# Classes route
@app.route('/classes', methods=['GET'])
@login_required
def classes():
    if current_user.role == 'parent':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        classes_response = supabase.table('classes').select('*, teachers(first_name, last_name)').execute()
        class_students_response = supabase.table('class_students').select('class_id, student_id').execute()
        students_response = supabase.table('students').select('student_id, first_name, last_name').execute()

        classes_data = classes_response.data
        class_students_data = class_students_response.data
        students_data = students_response.data

        student_map = {s['student_id']: s for s in students_data}
        class_students_map = {}
        for cs in class_students_data:
            class_id = cs['class_id']
            student_id = cs['student_id']
            if class_id not in class_students_map:
                class_students_map[class_id] = []
            if student_id in student_map:
                class_students_map[class_id].append(student_map[student_id])

        processed_classes = []
        for cls in classes_data:
            cls_copy = cls.copy()
            cls_copy['students'] = class_students_map.get(cls['class_id'], [])  # Ensure empty list if no students
            processed_classes.append(cls_copy)

        # Log class data (sanitized: exclude student details)
        class_summary = [{'class_id': c['class_id'], 'name': c['name'], 'days': c['days'], 'teacher_id': c['teacher_id']} for c in processed_classes]
        logger.info(f"Classes tab data: {class_summary}")

        # Debug logging for student IDs
        for cls in processed_classes:
            student_ids = [s['student_id'] for s in cls['students']]
            logger.debug(f"Class {cls['class_id']} student IDs: {student_ids}")

        return render_template('index.html',
                             active_tab='classes',
                             classes=processed_classes,
                             teachers=supabase.table('teachers').select('*').execute().data,
                             students=students_data,
                             user_role=current_user.role)
    except Exception as e:
        flash(f"Error fetching classes: {str(e)}", 'danger')
        logger.error(f"Error fetching classes: {str(e)}")
        return render_template('index.html', active_tab='classes', classes=[], teachers=[], students=[], user_role=current_user.role)

# Add class route
@app.route('/add_class', methods=['POST'])
@login_required
def add_class():
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('classes'))
    try:
        days_list = request.form.getlist('days')
        if not days_list:
            flash('At least one day must be selected', 'danger')
            return redirect(url_for('classes'))
        data = {
            'class_id': str(uuid.uuid4()),
            'name': request.form.get('name'),
            'days': ','.join(days_list),  # Join checkbox values
            'teacher_id': request.form.get('teacher_id') or None
        }
        if not data['name']:
            flash('Name is required', 'danger')
            return redirect(url_for('classes'))
        supabase.table('classes').insert(data).execute()
        logger.info(f"Added class: {data}")
        flash('Class added successfully', 'success')
        return redirect(url_for('classes'))
    except Exception as e:
        flash(f"Error adding class: {str(e)}", 'danger')
        logger.error(f"Error adding class: {str(e)}")
        return redirect(url_for('classes'))

@app.route('/edit_class', methods=['POST'])
@login_required
def edit_class():
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('classes'))
    try:
        class_id = request.form.get('class_id')
        days_list = request.form.getlist('days')
        if not days_list:
            flash('At least one day must be selected', 'danger')
            return redirect(url_for('classes'))
        data = {
            'name': request.form.get('name'),
            'days': ','.join(days_list),  # Join checkbox values
            'teacher_id': request.form.get('teacher_id') or None
        }
        if not data['name']:
            flash('Name is required', 'danger')
            return redirect(url_for('classes'))
        supabase.table('classes').update(data).eq('class_id', class_id).execute()
        logger.info(f"Edited class: {class_id}, data: {data}")
        flash('Class updated successfully', 'success')
        return redirect(url_for('classes'))
    except Exception as e:
        flash(f"Error updating class: {str(e)}", 'danger')
        logger.error(f"Error updating class: {str(e)}")
        return redirect(url_for('classes'))
    
# Delete class route
@app.route('/delete_class/<class_id>', methods=['POST'])
@login_required
def delete_class(class_id):
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('classes'))
    try:
        # Check for enrolled students
        students_response = supabase.table('class_students').select('student_id').eq('class_id', class_id).execute()
        if students_response.data and len(students_response.data) > 0:
            logger.warning(f"Attempted to delete class {class_id} with {len(students_response.data)} enrolled students")
            flash('Cannot delete class with enrolled students', 'danger')
            return redirect(url_for('classes'))
        supabase.table('classes').delete().eq('class_id', class_id).execute()
        logger.info(f"Deleted class: {class_id}")
        flash('Class deleted successfully', 'success')
        return redirect(url_for('classes'))
    except Exception as e:
        flash(f"Error deleting class: {str(e)}", 'danger')
        logger.error(f"Error deleting class {class_id}: {str(e)}")
        return redirect(url_for('classes'))
    
# Assign students to class route
@app.route('/assign_students_to_class', methods=['POST'])
@login_required
def assign_students_to_class():
    if current_user.role not in ['admin', 'teacher']:
        flash('Access denied: Admins or teachers only', 'danger')
        return redirect(url_for('classes'))
    try:
        class_id = request.form.get('class_id')
        student_ids = request.form.getlist('student_ids')  # May be empty
        # Remove existing assignments
        supabase.table('class_students').delete().eq('class_id', class_id).execute()
        # Add new assignments (if any)
        if student_ids:
            for student_id in student_ids:
                if student_id:
                    supabase.table('class_students').insert({
                        'class_id': class_id,
                        'student_id': student_id
                    }).execute()
        logger.info(f"Assigned students to class {class_id}: {student_ids or 'none'}")
        flash('Students assigned successfully', 'success')
        return redirect(url_for('classes'))
    except Exception as e:
        flash(f"Error assigning students: {str(e)}", 'danger')
        logger.error(f"Error assigning students to class {class_id}: {str(e)}")
        return redirect(url_for('classes'))
    
if __name__ == '__main__':
    app.run(debug=True)