from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import pandas as pd
import io
import uuid

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
        print("Fetching students data")
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
            # Filter for Parent role
            if current_user.role == 'parent' and current_user.parent_id not in [p['parent_id'] for p in parents]:
                continue
            student_copy = student.copy()
            student_copy['parents'] = parents  # List of parent dicts
            processed_students.append(student_copy)

        print(f"Processed students: {processed_students}")
        print("Rendering students tab")
        return render_template('index.html', 
                             active_tab='students', 
                             students=processed_students, 
                             parents=parents_data,
                             user_role=current_user.role)
    except Exception as e:
        flash(f"Error fetching students: {str(e)}")
        print(f"Error fetching students: {str(e)}")
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
        print(f"Editing student {student_id}, parent_ids: {parent_ids}")
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
                print(f"Invalid parent_id: {parent_id}")
        flash('Student updated successfully', 'success')
        return redirect(url_for('students'))
    except Exception as e:
        flash(f"Error updating student: {str(e)}", 'danger')
        print(f"Error updating student: {str(e)}")
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
        return render_template('index.html', 
                             active_tab='parents', 
                             parents=sorted_parents,
                             user_role=current_user.role)
    except Exception as e:
        flash(f"Error fetching parents: {str(e)}")
        print(f"Error fetching parents: {str(e)}")
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
        flash('Parent added successfully', 'success')
        return redirect(url_for('parents'))
    except Exception as e:
        flash(f"Error adding parent: {str(e)}", 'danger')
        print(f"Error adding parent: {str(e)}")
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
        flash('Parent updated successfully', 'success')
        return redirect(url_for('parents'))
    except Exception as e:
        flash(f"Error updating parent: {str(e)}", 'danger')
        print(f"Error updating parent: {str(e)}")
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
        flash('Parent deleted successfully', 'success')
        return redirect(url_for('parents'))
    except Exception as e:
        flash(f"Error deleting parent: {str(e)}", 'danger')
        print(f"Error deleting parent: {str(e)}")
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

        student_mappings = {
            'student_id': ['Student ID', 'ID', 'StudentID'],
            'first_name': ['First Name', 'FirstName', 'Given Name', 'Name'],
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
            flash('Invalid CSV: No recognizable First Name column')
            print("Error: No recognizable First Name column")
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
                if supabase_field == 'is_staff':
                    data[supabase_field] = value.lower() in ['yes', 'true', '1'] if value else False
                elif supabase_field == 'grade_level':
                    data[supabase_field] = str(value).lower() if value else None
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
@app.route('/add_teacher', methods=['POST'])
@login_required
def add_teacher():
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('teachers'))
    flash('Add teacher not implemented yet', 'warning')
    return redirect(url_for('teachers'))

@app.route('/edit_teacher', methods=['POST'])
@login_required
def edit_teacher():
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('teachers'))
    flash('Edit teacher not implemented yet', 'warning')
    return redirect(url_for('teachers'))

@app.route('/delete_teacher/<teacher_id>', methods=['POST'])
@login_required
def delete_teacher(teacher_id):
    if current_user.role != 'admin':
        flash('Access denied: Admins only', 'danger')
        return redirect(url_for('teachers'))
    flash('Delete teacher not implemented yet', 'warning')
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

if __name__ == '__main__':
    app.run(debug=True)