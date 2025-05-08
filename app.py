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
from typing import List, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    filename='app.log',
    format='%(asctime)s - %(levelname)s - %(message)s'
)
handler = RotatingFileHandler('app.log', maxBytes=1000000, backupCount=5)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger(__name__)
if not logger.handlers:
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
    logger.error("Missing SUPABASE_URL or SUPABASE_KEY in .env file")
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env file")

try:
    supabase: Client = create_client(supabase_url, supabase_key)
except Exception as e:
    logger.error(f"Error initializing Supabase client: {str(e)}")
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
    if not name or not isinstance(name, str):
        return None, None
    name = name.strip().strip('"')
    match = re.match(r"([^,]+),\s*([^\(]+)(?:\s*\((.+)\))?", name)
    if not match:
        return None, None
    last_name = match.group(1).strip()
    first_name = match.group(2).strip()
    first_name = match.group(3).strip() if match.group(3) else first_name
    return first_name, last_name

def normalize_grade(grade):
    if not grade or not isinstance(grade, str):
        return None
    grade = grade.strip().lower()
    if 'kindergarten' in grade:
        return 'K'
    match = re.match(r"(\d+)(?:st|nd|rd|th)\s*grade", grade)
    if match:
        return match.group(1)
    if grade.isdigit():
        return grade
    return None

def calculate_student_tuition(grade, assignments):
    pricing = {
        'K': {
            'morning': 1600,  # Per day/week
            'afternoon': 800   # Add-on per day/week
        },
        '1-2': {
            'full': 2400,     # Per day/week
            'enrichment': 2400  # Assume same as full
        },
        '3-8': {
            'enrichment': 2300,  # Per day/week
            'academic': 2800     # Per day/week (Academic + Enrichment)
        },
        '9-12': {
            'enrichment': 2400,  # Per day/week
            'academic': 2900     # Per day/week (Academic + Enrichment)
        }
    }
    total = 0
    academic_fee = 500  # Annual fee for academic programs
    grade_key = 'K' if grade == 'K' else '1-2' if grade in ['1', '2'] else '3-8' if grade in [str(i) for i in range(3, 9)] else '9-12'
    
    has_academic = False
    for assignment in assignments:
        program_type = assignment.get('program_type', '').lower()
        class_id = assignment.get('class_id')
        if not class_id:
            continue
        # Fetch class days
        class_response = supabase.table('classes').select('days').eq('class_id', class_id).execute()
        if not class_response.data:
            continue
        days = class_response.data[0]['days'] or []
        num_days = len(days) if days else 0
        
        if program_type in pricing[grade_key] and num_days > 0:
            # Tuition is per day/week multiplied by number of days
            total += pricing[grade_key][program_type] * num_days
            if program_type == 'academic':
                has_academic = True
    
    # Add academic fee if enrolled in academic program
    if has_academic:
        total += academic_fee
    
    return total

def apply_sibling_discount(total_amount, parent_id, parent_student_count):
    if parent_student_count.get(parent_id, 0) > 1:
        return total_amount * 0.9
    return total_amount

def format_days(days_array):
    if not days_array:
        return ""
    day_names = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
    sorted_days = sorted([int(day) for day in days_array if day is not None])
    return ', '.join(day_names[day] for day in sorted_days if 0 <= day < 7)

def clean_string(s: str) -> str:
    """Replace non-breaking spaces (\xa0) with regular spaces and normalize hyphens."""
    if not s:
        return s
    # Replace non-breaking spaces with regular spaces
    s = s.replace('\xa0', ' ')
    # Replace multiple spaces with single space
    s = re.sub(r'\s+', ' ', s)
    # Ensure dashes are standard hyphens
    s = s.replace('–', '-').replace('—', '-')
    return s.strip()


def normalize_grade_level(grade: str) -> List[str]:
    """Normalize grade level to a TEXT[] (e.g., '1st, 2nd' -> ['1', '2'], 'K-12' -> ['K', '1', ..., '12'])."""
    logging.info(f"Processing grade level: {grade}")
    grade = clean_string(grade).replace('"', '')
    if not grade:
        logging.warning("Empty grade level provided")
        return []
    
    # Valid grades per constraint
    valid_grades = ['K', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']
    
    # Helper to convert grade to string ('K' or '1', '2', etc.)
    def grade_to_str(g: str) -> Optional[str]:
        g = g.strip().lower()
        if g == 'k':
            return 'K'
        match = re.search(r'\d+', g)
        if match:
            num = match.group()
            if num in valid_grades:
                return num
        return None
    
    # Handle range (e.g., 'K-12', '1st-2nd')
    if '-' in grade:
        try:
            start, end = grade.split('-')
            start_num = grade_to_str(start)
            end_num = grade_to_str(end)
            if start_num is None or end_num is None:
                logging.warning(f"Invalid grade range format: {grade}")
                return []
            start_idx = valid_grades.index(start_num)
            end_idx = valid_grades.index(end_num)
            if start_idx > end_idx:
                logging.warning(f"Invalid grade range: {start_num} > {end_num}")
                return [start_num] if start_num in valid_grades else []
            # Generate range of grades
            grades = valid_grades[start_idx:end_idx + 1]
            return grades
        except Exception as e:
            logging.error(f"Error normalizing grade level {grade}: {str(e)}")
            return []
    
    # Handle comma-separated grades (e.g., '1st, 2nd')
    if ',' in grade:
        try:
            grades = [grade_to_str(g) for g in grade.split(',')]
            grades = [g for g in grades if g in valid_grades]
            if not grades:
                logging.warning(f"No valid grades in comma-separated list: {grade}")
                return []
            return sorted(set(grades))  # Remove duplicates and sort
        except Exception as e:
            logging.error(f"Error normalizing comma-separated grade level {grade}: {str(e)}")
            return []
    
    # Handle single grade (e.g., 'K', '1st')
    grade_str = grade_to_str(grade)
    if grade_str in valid_grades:
        return [grade_str]
    logging.warning(f"Invalid grade format: {grade}")
    return []

def apply_sibling_discount_per_family(parent_student_tuitions):
    """
    Apply sibling discount: first student pays full price, others get 10% off.
    parent_student_tuitions: List of {'student_id', 'student_name', 'grade', 'amount', 'parent_id'}
    Returns: Updated list with discounted amounts
    """
    if len(parent_student_tuitions) <= 1:
        return parent_student_tuitions
    
    # Sort by student_id to ensure consistent "first" student
    sorted_students = sorted(parent_student_tuitions, key=lambda x: x['student_id'])
    
    # First student pays full price
    result = [sorted_students[0].copy()]  # Copy to avoid modifying original
    
    # Apply 10% discount to others
    for student in sorted_students[1:]:
        student_copy = student.copy()
        student_copy['amount'] = student_copy['amount'] * 0.9
        result.append(student_copy)
    
    return result

# Routes
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

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

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
        return render_template('index.html', 
                             active_tab='students', 
                             students=processed_students, 
                             parents=parents_data,
                             user_role=current_user.role)
    except Exception as e:
        logger.error(f"Error fetching students: {str(e)}")
        flash(f"Error fetching students: {str(e)}", 'danger')
        return render_template('index.html', active_tab='students', students=[], parents=[], user_role=current_user.role)

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
        supabase.table('students').insert(data).execute()
        parent_ids = request.form.getlist('parent_ids')
        for parent_id in parent_ids:
            if parent_id:
                supabase.table('student_parents').insert({
                    'student_id': student_id,
                    'parent_id': parent_id
                }).execute()
        flash('Student added successfully', 'success')
    except Exception as e:
        logger.error(f"Error adding student: {str(e)}")
        flash(f"Error adding student: {str(e)}", 'danger')
    return redirect(url_for('students'))

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
        supabase.table('students').update(data).eq('student_id', student_id).execute()
        supabase.table('student_parents').delete().eq('student_id', student_id).execute()
        parent_ids = request.form.getlist('parent_ids')
        for parent_id in parent_ids:
            if parent_id:
                supabase.table('student_parents').insert({
                    'student_id': student_id,
                    'parent_id': parent_id
                }).execute()
        flash('Student updated successfully', 'success')
    except Exception as e:
        logger.error(f"Error editing student: {str(e)}")
        flash(f"Error editing student: {str(e)}", 'danger')
    return redirect(url_for('students'))

@app.route('/delete_student/<student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        supabase.table('student_parents').delete().eq('student_id', student_id).execute()
        supabase.table('class_students').delete().eq('student_id', student_id).execute()
        supabase.table('students').delete().eq('student_id', student_id).execute()
        flash('Student deleted successfully', 'success')
    except Exception as e:
        logger.error(f"Error deleting student: {str(e)}")
        flash(f"Error deleting student: {str(e)}", 'danger')
    return redirect(url_for('students'))

@app.route('/parents', methods=['GET'])
@login_required
def parents():
    if current_user.role == 'parent':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        response = supabase.table('parents').select('*').execute()
        parents_data = sorted(response.data, key=lambda x: x['last_name'].lower() if x['last_name'] else '')
        return render_template('index.html', active_tab='parents', parents=parents_data, user_role=current_user.role)
    except Exception as e:
        logger.error(f"Error fetching parents: {str(e)}")
        flash(f"Error fetching parents: {str(e)}", 'danger')
        return render_template('index.html', active_tab='parents', parents=[], user_role=current_user.role)

@app.route('/add_parent', methods=['POST'])
@login_required
def add_parent():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('parents'))
    try:
        parent_id = str(uuid.uuid4())
        data = {
            'parent_id': parent_id,
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'email': request.form.get('email') or None,
            'phone': format_phone(request.form.get('phone')) or None,
            'is_staff': request.form.get('is_staff') == 'on'
        }
        supabase.table('parents').insert(data).execute()
        flash('Parent added successfully', 'success')
    except Exception as e:
        logger.error(f"Error adding parent: {str(e)}")
        flash(f"Error adding parent: {str(e)}", 'danger')
    return redirect(url_for('parents'))

@app.route('/edit_parent', methods=['POST'])
@login_required
def edit_parent():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('parents'))
    try:
        parent_id = request.form.get('parent_id')
        data = {
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'email': request.form.get('email') or None,
            'phone': format_phone(request.form.get('phone')) or None,
            'is_staff': request.form.get('is_staff') == 'on'
        }
        supabase.table('parents').update(data).eq('parent_id', parent_id).execute()
        flash('Parent updated successfully', 'success')
    except Exception as e:
        logger.error(f"Error editing parent: {str(e)}")
        flash(f"Error editing parent: {str(e)}", 'danger')
    return redirect(url_for('parents'))

@app.route('/delete_parent/<parent_id>', methods=['POST'])
@login_required
def delete_parent(parent_id):
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('parents'))
    try:
        supabase.table('student_parents').delete().eq('parent_id', parent_id).execute()
        supabase.table('parents').delete().eq('parent_id', parent_id).execute()
        flash('Parent deleted successfully', 'success')
    except Exception as e:
        logger.error(f"Error deleting parent: {str(e)}")
        flash(f"Error deleting parent: {str(e)}", 'danger')
    return redirect(url_for('parents'))

@app.route('/teachers', methods=['GET'])
@login_required
def teachers():
    if current_user.role == 'parent':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        response = supabase.table('teachers').select('*').execute()
        teachers_data = sorted(response.data, key=lambda x: x['last_name'].lower() if x['last_name'] else '')
        return render_template('index.html', active_tab='teachers', teachers=teachers_data, user_role=current_user.role)
    except Exception as e:
        logger.error(f"Error fetching teachers: {str(e)}")
        flash(f"Error fetching teachers: {str(e)}", 'danger')
        return render_template('index.html', active_tab='teachers', teachers=[], user_role=current_user.role)

@app.route('/add_teacher', methods=['POST'])
@login_required
def add_teacher():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('teachers'))
    try:
        teacher_id = str(uuid.uuid4())
        data = {
            'teacher_id': teacher_id,
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'email': request.form.get('email') or None,
            'phone': format_phone(request.form.get('phone')) or None
        }
        supabase.table('teachers').insert(data).execute()
        flash('Teacher added successfully', 'success')
    except Exception as e:
        logger.error(f"Error adding teacher: {str(e)}")
        flash(f"Error adding teacher: {str(e)}", 'danger')
    return redirect(url_for('teachers'))

@app.route('/edit_teacher', methods=['POST'])
@login_required
def edit_teacher():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('teachers'))
    try:
        teacher_id = request.form.get('teacher_id')
        data = {
            'first_name': request.form.get('first_name'),
            'last_name': request.form.get('last_name'),
            'email': request.form.get('email') or None,
            'phone': format_phone(request.form.get('phone')) or None
        }
        supabase.table('teachers').update(data).eq('teacher_id', teacher_id).execute()
        flash('Teacher updated successfully', 'success')
    except Exception as e:
        logger.error(f"Error editing teacher: {str(e)}")
        flash(f"Error editing teacher: {str(e)}", 'danger')
    return redirect(url_for('teachers'))

@app.route('/delete_teacher/<teacher_id>', methods=['POST'])
@login_required
def delete_teacher(teacher_id):
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('teachers'))
    try:
        supabase.table('teachers').delete().eq('teacher_id', teacher_id).execute()
        flash('Teacher deleted successfully', 'success')
    except Exception as e:
        logger.error(f"Error deleting teacher: {str(e)}")
        flash(f"Error deleting teacher: {str(e)}", 'danger')
    return redirect(url_for('teachers'))

@app.route('/classes', methods=['GET'])
@login_required
def classes():
    if current_user.role not in ['admin', 'teacher']:
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        # Test a simple query without joins
        simple_classes_response = supabase.table('classes').select('class_id, name').execute()
        logger.info(f"Simple classes query result: {simple_classes_response.data}")

        # Original query with joins
        classes_response = supabase.table('classes').select('*, teachers(*), classrooms(*)').execute()
        logger.info(f"Classes query result: {classes_response.data}")

        # Fetch class-student relationships
        class_students_response = supabase.table('class_students').select('class_id, student_id, program_type').execute()
        logger.info(f"Class students query result: {class_students_response.data}")

        # Fetch student details
        students_response = supabase.table('students').select('student_id, first_name, last_name, grade_level').execute()
        logger.info(f"Students query result: {students_response.data}")

        # Fetch teachers and classrooms for modals
        teachers_response = supabase.table('teachers').select('teacher_id, first_name, last_name').execute()
        logger.info(f"Teachers query result: {teachers_response.data}")

        classrooms_response = supabase.table('classrooms').select('classroom_id, building_number, room_number').execute()
        logger.info(f"Classrooms query result: {classrooms_response.data}")

        classes_data = classes_response.data
        class_students_data = class_students_response.data
        students_data = students_response.data
        teachers_data = teachers_response.data
        classrooms_data = classrooms_response.data

        if not classes_data:
            logger.warning("No classes data returned from query")
            flash("No classes found in the database", 'warning')

        # Build class-student mapping
        class_student_map = {}
        for cs in class_students_data:
            class_id = cs['class_id']
            if class_id not in class_student_map:
                class_student_map[class_id] = []
            class_student_map[class_id].append({
                'student_id': cs['student_id'],
                'program_type': cs['program_type']
            })

        processed_classes = []
        for cls in classes_data:
            cls_copy = cls.copy()
            cls_copy['days_array'] = cls['days'] or []
            cls_copy['days'] = format_days(cls['days'])
            cls_copy['teachers'] = cls.get('teachers', None)
            cls_copy['classrooms'] = cls.get('classrooms', None)
            student_assignments = class_student_map.get(cls['class_id'], [])
            cls_copy['students'] = [
                {**s, 'program_type': sa['program_type']}
                for s in students_data
                for sa in student_assignments
                if s['student_id'] == sa['student_id']
            ]
            processed_classes.append(cls_copy)

        processed_classes = sorted(processed_classes, key=lambda x: x['name'].lower() if x['name'] else '')
        return render_template('index.html', 
                             active_tab='classes', 
                             classes=processed_classes,
                             teachers=teachers_data,
                             classrooms=classrooms_data,
                             students=students_data,
                             user_role=current_user.role)
    except Exception as e:
        logger.error(f"Error fetching classes: {str(e)}")
        flash(f"Error fetching classes: {str(e)}", 'danger')
        return render_template('index.html', active_tab='classes', classes=[], teachers=[], classrooms=[], students=[], user_role=current_user.role)

def normalize_term(term):
    if not term:
        return None
    term = term.strip()
    if term.startswith('Spring'):
        return 'Spring'
    if term.startswith('Fall'):
        return 'Fall'
    if term.startswith('Summer'):
        return 'Summer'
    return term

@app.route('/add_class', methods=['POST'])
@login_required
def add_class():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('classes'))
    try:
        valid_terms = ['Semester 1', 'Semester 2', 'Both']
        term = request.form.get('term')
        if term not in valid_terms:
            flash(f"Invalid term: {term}. Must be one of {', '.join(valid_terms)}", 'danger')
            return redirect(url_for('classes'))
        
        class_id = str(uuid.uuid4())
        days = request.form.getlist('days')
        data = {
            'class_id': class_id,
            'name': request.form.get('name'),
            'days': days if days else None,
            'teacher_id': request.form.get('teacher_id') or None,
            'grade_level': request.form.get('grade_level') or None,
            'max_size': int(request.form.get('max_size')) if request.form.get('max_size') else None,
            'term': term,
            'schedule_block': int(request.form.get('schedule_block')) if request.form.get('schedule_block') else None,
            'classroom_id': request.form.get('classroom_id') or None
        }
        supabase.table('classes').insert(data).execute()
        flash('Class added successfully', 'success')
    except Exception as e:
        logger.error(f"Error adding class: {str(e)}")
        flash(f"Error adding class: {str(e)}", 'danger')
    return redirect(url_for('classes'))

@app.route('/edit_class', methods=['POST'])
@login_required
def edit_class():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('classes'))
    
    try:
        valid_terms = ['Semester 1', 'Semester 2', 'Both']
        term = request.form.get('term')
        if term not in valid_terms:
            flash(f"Invalid term: {term}. Must be one of {', '.join(valid_terms)}", 'danger')
            return redirect(url_for('classes'))
        
        class_id = request.form.get('class_id')
        if not class_id:
            flash('Class ID is required', 'danger')
            return redirect(url_for('classes'))
        
        # Normalize days (INTEGER[])
        days = request.form.getlist('days')
        days = [int(day) for day in days if day.isdigit()] if days else None
        
        # Normalize schedule_block (INTEGER[])
        schedule_block = request.form.get('schedule_block')
        logger.info(f"Raw schedule_block input: {schedule_block}")
        schedule_block = [int(schedule_block)] if schedule_block and schedule_block.isdigit() else None
        
        # Build update data, excluding None values for schedule_block to preserve existing
        data = {
            'name': request.form.get('name') or None,
            'days': days,
            'teacher_id': request.form.get('teacher_id') or None,
            'grade_level': normalize_grade_level(request.form.get('grade_level') or ''),
            'max_size': int(request.form.get('max_size')) if request.form.get('max_size') and request.form.get('max_size').isdigit() else None,
            'term': term,
            'classroom_id': request.form.get('classroom_id') or None
        }
        # Only include schedule_block if a valid value is provided
        if schedule_block:
            data['schedule_block'] = schedule_block
        
        logger.info(f"Updating class {class_id} with data: {data}")
        
        # Perform the update
        response = supabase.table('classes').update(data).eq('class_id', class_id).execute()
        
        if response.data:
            flash('Class updated successfully', 'success')
        else:
            flash('Class not found or no changes made', 'warning')
            
    except Exception as e:
        logger.error(f"Error editing class {class_id}: {str(e)}")
        flash(f"Error editing class: {str(e)}", 'danger')
    
    return redirect(url_for('classes'))


@app.route('/delete_class/<class_id>', methods=['POST'])
@login_required
def delete_class(class_id):
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('classes'))
    try:
        supabase.table('class_students').delete().eq('class_id', class_id).execute()
        supabase.table('classes').delete().eq('class_id', class_id).execute()
        flash('Class deleted successfully', 'success')
    except Exception as e:
        logger.error(f"Error deleting class: {str(e)}")
        flash(f"Error deleting class: {str(e)}", 'danger')
    return redirect(url_for('classes'))

@app.route('/assign_students_to_class', methods=['POST'])
@login_required
def assign_students_to_class():
    if current_user.role not in ['admin', 'teacher']:
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('classes'))
    try:
        class_id = request.form.get('class_id')
        student_ids = request.form.getlist('student_ids')
        program_types = request.form.getlist('program_types')  # Expect one program_type per student
        # Clear existing student assignments
        supabase.table('class_students').delete().eq('class_id', class_id).execute()
        # Assign new students with program_type
        for student_id, program_type in zip(student_ids, program_types):
            if student_id and program_type:
                supabase.table('class_students').insert({
                    'class_id': class_id,
                    'student_id': student_id,
                    'program_type': program_type or None
                }).execute()
        flash('Students assigned successfully', 'success')
    except Exception as e:
        logger.error(f"Error assigning students to class: {str(e)}")
        flash(f"Error assigning students: {str(e)}", 'danger')
    return redirect(url_for('classes'))

@app.route('/classrooms', methods=['GET'])
@login_required
def classrooms():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        response = supabase.table('classrooms').select('*').execute()
        classrooms_data = sorted(response.data, key=lambda x: (x['building_number'].lower(), x['room_number'].lower()) if x['building_number'] and x['room_number'] else ('', ''))
        return render_template('index.html', active_tab='classrooms', classrooms=classrooms_data, user_role=current_user.role)
    except Exception as e:
        logger.error(f"Error fetching classrooms: {str(e)}")
        flash(f"Error fetching classrooms: {str(e)}", 'danger')
        return render_template('index.html', active_tab='classrooms', classrooms=[], user_role=current_user.role)

@app.route('/add_classroom', methods=['POST'])
@login_required
def add_classroom():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('classrooms'))
    try:
        classroom_id = str(uuid.uuid4())
        data = {
            'classroom_id': classroom_id,
            'building_number': request.form.get('building_number'),
            'room_number': request.form.get('room_number')
        }
        supabase.table('classrooms').insert(data).execute()
        flash('Classroom added successfully', 'success')
    except Exception as e:
        logger.error(f"Error adding classroom: {str(e)}")
        flash(f"Error adding classroom: {str(e)}", 'danger')
    return redirect(url_for('classrooms'))

@app.route('/edit_classroom', methods=['POST'])
@login_required
def edit_classroom():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('classrooms'))
    try:
        classroom_id = request.form.get('classroom_id')
        data = {
            'building_number': request.form.get('building_number'),
            'room_number': request.form.get('room_number')
        }
        supabase.table('classrooms').update(data).eq('classroom_id', classroom_id).execute()
        flash('Classroom updated successfully', 'success')
    except Exception as e:
        logger.error(f"Error editing classroom: {str(e)}")
        flash(f"Error editing classroom: {str(e)}", 'danger')
    return redirect(url_for('classrooms'))

@app.route('/delete_classroom/<classroom_id>', methods=['POST'])
@login_required
def delete_classroom(classroom_id):
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('classrooms'))
    try:
        supabase.table('classrooms').delete().eq('classroom_id', classroom_id).execute()
        flash('Classroom deleted successfully', 'success')
    except Exception as e:
        logger.error(f"Error deleting classroom: {str(e)}")
        flash(f"Error deleting classroom: {str(e)}", 'danger')
    return redirect(url_for('classrooms'))

@app.route('/users', methods=['GET'])
@login_required
def users():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        users_response = supabase.table('users').select('user_id, email, role, parent_id').execute()
        parents_response = supabase.table('parents').select('parent_id, first_name, last_name').execute()
        users_data = users_response.data
        parents_data = parents_response.data
        parent_map = {p['parent_id']: f"{p['last_name']}, {p['first_name']}" for p in parents_data}
        for user in users_data:
            user['parent_name'] = parent_map.get(user['parent_id'], None)
        users_data = sorted(users_data, key=lambda x: x['email'].lower() if x['email'] else '')
        return render_template('index.html', active_tab='users', users=users_data, parents=parents_data, user_role=current_user.role)
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        flash(f"Error fetching users: {str(e)}", 'danger')
        return render_template('index.html', active_tab='users', users=[], parents=[], user_role=current_user.role)

@app.route('/add_user', methods=['POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('users'))
    try:
        user_id = str(uuid.uuid4())
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        parent_id = request.form.get('parent_id') or None
        if role == 'parent' and not parent_id:
            flash('Parent ID is required for parent role', 'danger')
            return redirect(url_for('users'))
        data = {
            'user_id': user_id,
            'email': email,
            'password_hash': bcrypt.generate_password_hash(password).decode('utf-8'),
            'role': role,
            'parent_id': parent_id
        }
        supabase.table('users').insert(data).execute()
        flash('User added successfully', 'success')
    except Exception as e:
        logger.error(f"Error adding user: {str(e)}")
        flash(f"Error adding user: {str(e)}", 'danger')
    return redirect(url_for('users'))

@app.route('/edit_user', methods=['POST'])
@login_required
def edit_user():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('users'))
    try:
        user_id = request.form.get('user_id')
        data = {
            'email': request.form.get('email'),
            'role': request.form.get('role'),
            'parent_id': request.form.get('parent_id') or None
        }
        if data['role'] == 'parent' and not data['parent_id']:
            flash('Parent ID is required for parent role', 'danger')
            return redirect(url_for('users'))
        password = request.form.get('password')
        if password:
            data['password_hash'] = bcrypt.generate_password_hash(password).decode('utf-8')
        supabase.table('users').update(data).eq('user_id', user_id).execute()
        flash('User updated successfully', 'success')
    except Exception as e:
        logger.error(f"Error editing user: {str(e)}")
        flash(f"Error editing user: {str(e)}", 'danger')
    return redirect(url_for('users'))

@app.route('/delete_user/<user_id>', methods=['POST'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('users'))
    try:
        supabase.table('users').delete().eq('user_id', user_id).execute()
        flash('User deleted successfully', 'success')
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        flash(f"Error deleting user: {str(e)}", 'danger')
    return redirect(url_for('users'))

@app.route('/tuition', methods=['GET'])
@login_required
def tuition():
    try:
        students_response = supabase.table('students').select('student_id, first_name, last_name, grade_level').execute()
        student_parents_response = supabase.table('student_parents').select('student_id, parent_id').execute()
        class_students_response = supabase.table('class_students').select('class_id, student_id, program_type').execute()
        classes_response = supabase.table('classes').select('class_id, name, days').execute()

        students_data = students_response.data
        student_parents_data = student_parents_response.data
        class_students_data = class_students_response.data
        classes_data = classes_response.data

        # Build class-student mapping
        student_classes_map = {}
        for cs in class_students_data:
            student_id = cs['student_id']
            if student_id not in student_classes_map:
                student_classes_map[student_id] = []
            student_classes_map[student_id].append({
                'class_id': cs['class_id'],
                'program_type': cs['program_type']
            })

        # Build parent-student mapping
        parent_student_map = {}
        for sp in student_parents_data:
            parent_id = sp['parent_id']
            student_id = sp['student_id']
            if parent_id not in parent_student_map:
                parent_student_map[parent_id] = []
            parent_student_map[parent_id].append(student_id)

        # Calculate base tuition for each student
        tuition_records_by_parent = {}
        for student in students_data:
            student_id = student['student_id']
            if current_user.role == 'parent':
                parent_students = parent_student_map.get(current_user.parent_id, [])
                if student_id not in parent_students:
                    continue
            assignments = student_classes_map.get(student_id, [])
            amount = calculate_student_tuition(student['grade_level'], assignments)
            parent_id = next((sp['parent_id'] for sp in student_parents_data if sp['student_id'] == student_id), None)
            
            if parent_id not in tuition_records_by_parent:
                tuition_records_by_parent[parent_id] = []
            
            tuition_records_by_parent[parent_id].append({
                'student_id': student_id,
                'student_name': f"{student['last_name']}, {student['first_name']}",
                'grade': student['grade_level'],
                'amount': amount,
                'parent_id': parent_id
            })

        # Apply sibling discount per family
        tuition_records = []
        for parent_id, records in tuition_records_by_parent.items():
            discounted_records = apply_sibling_discount_per_family(records)
            for record in discounted_records:
                status = 'Pending' if record['amount'] > 0 else 'No Charge'
                tuition_records.append({
                    'student_name': record['student_name'],
                    'grade': record['grade'],
                    'amount': f"${record['amount']:.2f}",
                    'status': status
                })

        tuition_records = sorted(tuition_records, key=lambda x: x['student_name'].lower())
        return render_template('index.html', active_tab='tuition', tuition=tuition_records, user_role=current_user.role)
    except Exception as e:
        logger.error(f"Error fetching tuition: {str(e)}")
        flash(f"Error fetching tuition: {str(e)}", 'danger')
        return render_template('index.html', active_tab='tuition', tuition=[], user_role=current_user.role)
    
@app.route('/import_from_csv', methods=['POST'])
@login_required
def import_from_csv():
    if current_user.role != 'admin':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        file = request.files['file']
        if not file or not file.filename.endswith('.csv'):
            flash('Please upload a valid CSV file', 'danger')
            return redirect(url_for('students'))
        df = pd.read_csv(io.StringIO(file.read().decode('utf-8')))
        for _, row in df.iterrows():
            first_name, last_name = parse_student_name(row.get('StudentName'))
            if not first_name or not last_name:
                continue
            grade_level = normalize_grade(row.get('Grade'))
            if not grade_level:
                continue
            student_id = str(uuid.uuid4())
            data = {
                'student_id': student_id,
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
            supabase.table('students').insert(data).execute()
        flash('Students imported successfully', 'success')
    except Exception as e:
        logger.error(f"Error importing CSV: {str(e)}")
        flash(f"Error importing CSV: {str(e)}", 'danger')
    return redirect(url_for('students'))

@app.route('/api/class/<class_id>')
@login_required
def get_class(class_id):
    try:
        response = supabase.table('classes').select('*').eq('class_id', class_id).execute()
        if response.data:
            return response.data[0], 200
        return {"error": "Class not found"}, 404
    except Exception as e:
        logger.error(f"Error fetching class {class_id}: {str(e)}")
        return {"error": str(e)}, 500

if __name__ == '__main__':
    app.run(debug=True)