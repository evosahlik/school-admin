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

# Existing functions (unchanged)
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

# Modified students route with role-based access
@app.route('/', methods=['GET'])
@app.route('/students', methods=['GET'])
@login_required
def students():
    try:
        print("Fetching students data")
        students_response = supabase.table('students').select('*').execute()
        parents_response = supabase.table('parents').select('parent_id, first_name, last_name').execute()
        students_data = students_response.data
        parents_data = parents_response.data

        parent_map = {p['parent_id']: p for p in parents_data}
        processed_students = []
        for student in students_data:
            parent = parent_map.get(student['parent_id'], {'first_name': '', 'last_name': ''})
            student_copy = student.copy()
            student_copy['parent_first_name'] = parent['first_name']
            student_copy['parent_last_name'] = parent['last_name']
            # Filter for Parent role
            if current_user.role == 'parent' and student['parent_id'] != current_user.parent_id:
                continue
            processed_students.append(student_copy)

        print(f"Processed student: {processed_students}")
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

@app.route('/add_student', methods=['POST'])
@login_required
def add_student():
    try:
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        grade_level = request.form['grade_level'].lower()
        parent_id = request.form['parent_id'] or None
        medicines = request.form['medicines'] or None
        allergies = request.form['allergies'] or None
        medical_conditions = request.form['medical_conditions'] or None
        comments = request.form['comments'] or None
        data = {
            'first_name': first_name,
            'last_name': last_name,
            'grade_level': grade_level,
            'parent_id': parent_id,
            'medicines': medicines,
            'allergies': allergies,
            'medical_conditions': medical_conditions,
            'comments': comments
        }
        response = supabase.table('students').insert(data).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Error adding student: {response.error}")
            flash(f"Error adding student: {response.error}")
            return redirect(url_for('students'))
        flash('Student added successfully!')
        return redirect(url_for('students'))
    except Exception as e:
        print(f"Exception adding student: {str(e)}")
        flash(f"Error adding student: {str(e)}")
        return redirect(url_for('students'))

@app.route('/edit_student', methods=['POST'])
@login_required
def edit_student():
    try:
        student_id = request.form['student_id']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        grade_level = request.form['grade_level'].lower()
        parent_id = request.form['parent_id'] or None
        medicines = request.form['medicines'] or None
        allergies = request.form['allergies'] or None
        medical_conditions = request.form['medical_conditions'] or None
        comments = request.form['comments'] or None
        data = {
            'first_name': first_name,
            'last_name': last_name,
            'grade_level': grade_level,
            'parent_id': parent_id,
            'medicines': medicines,
            'allergies': allergies,
            'medical_conditions': medical_conditions,
            'comments': comments
        }
        response = supabase.table('students').update(data).eq('student_id', student_id).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Error updating student: {response.error}")
            flash(f"Error updating student: {response.error}")
            return redirect(url_for('students'))
        flash('Student updated successfully!')
        return redirect(url_for('students'))
    except Exception as e:
        print(f"Exception updating student: {str(e)}")
        flash(f"Error updating student: {str(e)}")
        return redirect(url_for('students'))

@app.route('/delete_student/<student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    try:
        response = supabase.table('students').delete().eq('student_id', student_id).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Error deleting student: {response.error}")
            flash(f"Error deleting student: {response.error}")
            return redirect(url_for('students'))
        flash('Student deleted successfully!')
        return redirect(url_for('students'))
    except Exception as e:
        print(f"Exception deleting student: {str(e)}")
        flash(f"Error deleting student: {str(e)}")
        return redirect(url_for('students'))


# Modified parents route
@app.route('/parents', methods=['GET'])
@login_required
def parents():
    if current_user.role == 'parent':
        flash('Access denied: Insufficient permissions', 'danger')
        return redirect(url_for('students'))
    try:
        parents_response = supabase.table('parents').select('*').execute()
        return render_template('index.html', 
                             active_tab='parents', 
                             parents=parents_response.data,
                             user_role=current_user.role)
    except Exception as e:
        flash(f"Error fetching parents: {str(e)}")
        print(f"Error fetching parents: {str(e)}")
        return render_template('index.html', active_tab='parents', parents=[], user_role=current_user.role)


@app.route('/add_parent', methods=['POST'])
@login_required
def add_parent():
    try:
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email'] or None
        phone = request.form['phone'] or None
        is_staff = request.form.get('is_staff') == 'on'
        data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'phone': phone,
            'is_staff': is_staff
        }
        response = supabase.table('parents').insert(data).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Error adding parent: {response.error}")
            flash(f"Error adding parent: {response.error}")
            return redirect(url_for('parents'))
        flash('Parent added successfully!')
        return redirect(url_for('parents'))
    except Exception as e:
        print(f"Exception adding parent: {str(e)}")
        flash(f"Error adding parent: {str(e)}")
        return redirect(url_for('parents'))

@app.route('/edit_parent', methods=['POST'])
@login_required
def edit_parent():
    try:
        parent_id = request.form.get('parent_id') or request.form.get('parent_id_fallback')
        print('Received form data:', dict(request.form))
        if not parent_id or parent_id.strip() == '':
            flash('Error: No parent ID provided.')
            print('Edit parent failed: Invalid parent_id', parent_id, dict(request.form))
            return redirect(url_for('parents'))
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email'] or None
        phone = request.form['phone'] or None
        is_staff = request.form.get('is_staff') == 'on'
        data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'phone': phone,
            'is_staff': is_staff
        }
        response = supabase.table('parents').update(data).eq('parent_id', parent_id).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Supabase error updating parent: {response.error}")
            flash(f"Error updating parent: {response.error}")
            return redirect(url_for('parents'))
        print(f"Parent updated successfully: {parent_id}", data)
        flash('Parent updated successfully!')
        return redirect(url_for('parents'))
    except Exception as e:
        print(f"Exception updating parent: {str(e)}")
        flash(f"Error updating parent: {str(e)}")
        return redirect(url_for('parents'))

@app.route('/delete_parent/<parent_id>', methods=['POST'])
@login_required
def delete_parent(parent_id):
    try:
        supabase.table('students').update({'parent_id': None}).eq('parent_id', parent_id).execute()
        response = supabase.table('parents').delete().eq('parent_id', parent_id).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Error deleting parent: {response.error}")
            flash(f"Error deleting parent: {response.error}")
            return redirect(url_for('parents'))
        flash('Parent deleted successfully!')
        return redirect(url_for('parents'))
    except Exception as e:
        print(f"Exception deleting parent: {str(e)}")
        flash(f"Error deleting parent: {str(e)}")
        return redirect(url_for('parents'))

# Modified import_from_csv route
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
            'parent_id': ['Parent ID', 'ParentID'],
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

# Placeholder for other routes (add @login_required as needed)
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

@app.route('/add_teacher', methods=['POST'])
@login_required
def add_teacher():
    try:
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        phone = request.form['phone']
        data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'phone': phone
        }
        response = supabase.table('teachers').insert(data).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Error adding teacher: {response.error}")
            flash(f"Error adding teacher: {response.error}")
            return redirect(url_for('teachers'))
        flash('Teacher added successfully!')
        return redirect(url_for('teachers'))
    except Exception as e:
        print(f"Exception adding teacher: {str(e)}")
        flash(f"Error adding teacher: {str(e)}")
        return redirect(url_for('teachers'))

@app.route('/edit_teacher', methods=['POST'])
@login_required
def edit_teacher():
    try:
        teacher_id = request.form.get('teacher_id') or request.form.get('teacher_id_fallback')
        print('Received form data:', dict(request.form))
        if not teacher_id or teacher_id.strip() == '':
            flash('Error: No teacher ID provided.')
            print('Edit teacher failed: Invalid teacher_id', teacher_id, dict(request.form))
            return redirect(url_for('teachers'))
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email'] or None
        phone = request.form['phone'] or None
        data = {
            'first_name': first_name,
            'last_name': last_name,
            'email': email,
            'phone': phone
        }
        response = supabase.table('teachers').update(data).eq('teacher_id', teacher_id).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Supabase error updating teacher: {response.error}")
            flash(f"Error updating teacher: {response.error}")
            return redirect(url_for('teachers'))
        print(f"Teacher updated successfully: {teacher_id}", data)
        flash('Teacher updated successfully!')
        return redirect(url_for('teachers'))
    except Exception as e:
        print(f"Exception updating teacher: {str(e)}")
        flash(f"Error updating teacher: {str(e)}")
        return redirect(url_for('teachers'))

@app.route('/delete_teacher/<teacher_id>', methods=['POST'])
@login_required
def delete_teacher(teacher_id):
    try:
        response = supabase.table('teachers').delete().eq('teacher_id', teacher_id).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Error deleting teacher: {response.error}")
            flash(f"Error deleting teacher: {response.error}")
            return redirect(url_for('teachers'))
        flash('Teacher deleted successfully!')
        return redirect(url_for('teachers'))
    except Exception as e:
        print(f"Exception deleting teacher: {str(e)}")
        flash(f"Error deleting teacher: {str(e)}")
        return redirect(url_for('teachers'))


@app.route('/tuition', methods=['GET'])
@login_required
def tuition():
    try:
        # Placeholder: Fetch tuition data
        tuition_data = []
        return render_template('index.html', 
                             active_tab='tuition', 
                             tuition=tuition_data,
                             user_role=current_user.role)
    except Exception as e:
        flash(f"Error fetching tuition: {str(e)}")
        print(f"Error fetching tuition: {str(e)}")
        return render_template('index.html', active_tab='tuition', tuition=[], user_role=current_user.role)

# Add other routes (add_student, edit_student, delete_student, add_parent, edit_parent, delete_parent, etc.) with @login_required
# For brevity, only key routes are shown. Add role checks as needed.

if __name__ == '__main__':
    app.run(debug=True)