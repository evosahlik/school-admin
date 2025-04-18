from flask import Flask, render_template, request, redirect, url_for, flash
from supabase import create_client, Client
import os
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default-secret-key')

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

@app.route('/')
@app.route('/students')
def students():
    try:
        print("Fetching students data")
        students_response = supabase.table('students').select('student_id, first_name, last_name, grade_level, parent_id, medicines, allergies, medical_conditions, comments').execute()
        students_data = students_response.data or []
        print(f"Students data: {students_data}")
        
        parents_response = supabase.table('parents').select('parent_id, first_name, last_name').execute()
        parents_data = parents_response.data or []
        print(f"Parents data: {parents_data}")
        
        parent_map = {p['parent_id']: p for p in parents_data}
        for s in students_data:
            parent = parent_map.get(s['parent_id'], {})
            s['parent_first_name'] = parent.get('first_name', '')
            s['parent_last_name'] = parent.get('last_name', '')
            print(f"Processed student: {s}")
        
        print("Rendering students tab")
        return render_template('index.html', active_tab='students', students=students_data, parents=parents_data)
    except Exception as e:
        print(f"Error fetching students: {str(e)}")
        flash(f"Error fetching students: {str(e)}")
        return render_template('index.html', active_tab='students', students=[], parents=[])

@app.route('/add_student', methods=['POST'])
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
        print(f"Adding student: {data}")
        response = supabase.table('students').insert(data).execute()
        if response.data:
            print(f"Student added: {response.data}")
            flash('Student added successfully!')
            return redirect(url_for('students'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error adding student: {error}")
            flash(f"Error adding student: {error}")
            return redirect(url_for('students'))
    except Exception as e:
        print(f"Exception adding student: {str(e)}")
        flash(f"Error adding student: {str(e)}")
        return redirect(url_for('students'))

@app.route('/edit_student', methods=['POST'])
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
        print(f"Updating student {student_id}: {data}")
        response = supabase.table('students').update(data).eq('student_id', student_id).execute()
        if response.data:
            print(f"Student updated: {response.data}")
            flash('Student updated successfully!')
            return redirect(url_for('students'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error updating student: {error}")
            flash(f"Error updating student: {error}")
            return redirect(url_for('students'))
    except Exception as e:
        print(f"Exception updating student: {str(e)}")
        flash(f"Error updating student: {str(e)}")
        return redirect(url_for('students'))

@app.route('/delete_student/<student_id>', methods=['POST'])
def delete_student(student_id):
    try:
        print(f"Deleting student {student_id}")
        # Delete related tuition records
        tuition_response = supabase.table('tuition').delete().eq('student_id', student_id).execute()
        print(f"Deleted tuition records for student {student_id}: {tuition_response.data}")
        # Delete student
        response = supabase.table('students').delete().eq('student_id', student_id).execute()
        if response.data or not response.error:
            print(f"Student deleted: {response.data}")
            flash('Student deleted successfully!')
            print(f"Flashed: Student deleted successfully! for student {student_id}")
            return redirect(url_for('students'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error deleting student: {error}")
            flash(f"Error deleting student: {error}")
            print(f"Flashed: Error deleting student: {error}")
            return redirect(url_for('students'))
    except Exception as e:
        print(f"Exception deleting student: {str(e)}")
        flash(f"Error deleting student: {str(e)}")
        print(f"Flashed: Error deleting student: {str(e)}")
        return redirect(url_for('students'))

@app.route('/parents')
def parents():
    try:
        parents_response = supabase.table('parents').select('parent_id, first_name, last_name, email, phone, is_staff').execute()
        parents = parents_response.data or []
        for parent in parents:
            if not parent.get('parent_id'):
                print(f"Warning: Parent {parent.get('first_name', 'Unknown')} {parent.get('last_name', '')} has no parent_id")
        return render_template('index.html', active_tab='parents', parents=parents)
    except Exception as e:
        print(f"Error fetching parents: {str(e)}")
        flash(f"Error fetching parents: {str(e)}")
        return render_template('index.html', active_tab='parents', parents=[])

@app.route('/add_parent', methods=['POST'])
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
        print(f"Adding parent: {data}")
        response = supabase.table('parents').insert(data).execute()
        if response.data:
            print(f"Parent added: {response.data}")
            flash('Parent added successfully!')
            return redirect(url_for('parents'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error adding parent: {error}")
            flash(f"Error adding parent: {error}")
            return redirect(url_for('parents'))
    except Exception as e:
        print(f"Exception adding parent: {str(e)}")
        flash(f"Error adding parent: {str(e)}")
        return redirect(url_for('parents'))

@app.route('/edit_parent', methods=['POST'])
def edit_parent():
    try:
        parent_id = request.form.get('parent_id')
        print(f"Received form data: {dict(request.form)}")
        if not parent_id:
            print("Error: No parent_id provided")
            flash('Error: No parent ID provided.')
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
        print(f"Updating parent {parent_id}: {data}")
        response = supabase.table('parents').update(data).eq('parent_id', parent_id).execute()
        if response.data:
            print(f"Parent updated: {response.data}")
            flash('Parent updated successfully!')
            return redirect(url_for('parents'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error updating parent: {error}")
            flash(f"Error updating parent: {error}")
            return redirect(url_for('parents'))
    except Exception as e:
        print(f"Exception updating parent: {str(e)}")
        flash(f"Error updating parent: {str(e)}")
        return redirect(url_for('parents'))

@app.route('/delete_parent/<parent_id>', methods=['POST'])
def delete_parent(parent_id):
    try:
        print(f"Deleting parent {parent_id}")
        # Nullify student parent_id references
        students_response = supabase.table('students').update({'parent_id': None}).eq('parent_id', parent_id).execute()
        print(f"Nullified student parent_id for parent {parent_id}: {students_response.data}")
        # Delete related tuition records
        tuition_response = supabase.table('tuition').delete().eq('parent_id', parent_id).execute()
        print(f"Deleted tuition records for parent {parent_id}: {tuition_response.data}")
        # Delete parent
        response = supabase.table('parents').delete().eq('parent_id', parent_id).execute()
        if response.data or not response.error:
            print(f"Parent deleted: {response.data}")
            flash('Parent deleted successfully!')
            print(f"Flashed: Parent deleted successfully! for parent {parent_id}")
            return redirect(url_for('parents'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error deleting parent: {error}")
            flash(f"Error deleting parent: {error}")
            print(f"Flashed: Error deleting parent: {error}")
            return redirect(url_for('parents'))
    except Exception as e:
        print(f"Exception deleting parent: {str(e)}")
        flash(f"Error deleting parent: {str(e)}")
        print(f"Flashed: Error deleting parent: {str(e)}")
        return redirect(url_for('parents'))

@app.route('/teachers')
def teachers():
    try:
        teachers = supabase.table('teachers').select('teacher_id, first_name, last_name, email, phone').execute().data or []
        return render_template('index.html', active_tab='teachers', teachers=teachers)
    except Exception as e:
        print(f"Error fetching teachers: {str(e)}")
        flash(f"Error fetching teachers: {str(e)}")
        return render_template('index.html', active_tab='teachers', teachers=[])

@app.route('/add_teacher', methods=['POST'])
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
        print(f"Adding teacher: {data}")
        response = supabase.table('teachers').insert(data).execute()
        if response.data:
            print(f"Teacher added: {response.data}")
            flash('Teacher added successfully!')
            return redirect(url_for('teachers'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error adding teacher: {error}")
            flash(f"Error adding teacher: {error}")
            return redirect(url_for('teachers'))
    except Exception as e:
        print(f"Exception adding teacher: {str(e)}")
        flash(f"Error adding teacher: {str(e)}")
        return redirect(url_for('teachers'))

@app.route('/edit_teacher', methods=['POST'])
def edit_teacher():
    try:
        teacher_id = request.form.get('teacher_id')
        print(f"Received form data: {dict(request.form)}")
        if not teacher_id:
            print("Error: No teacher_id provided")
            flash('Error: No teacher ID provided.')
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
        print(f"Updating teacher {teacher_id}: {data}")
        response = supabase.table('teachers').update(data).eq('teacher_id', teacher_id).execute()
        if response.data:
            print(f"Teacher updated: {response.data}")
            flash('Teacher updated successfully!')
            return redirect(url_for('teachers'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error updating teacher: {error}")
            flash(f"Error updating teacher: {error}")
            return redirect(url_for('teachers'))
    except Exception as e:
        print(f"Exception updating teacher: {str(e)}")
        flash(f"Error updating teacher: {str(e)}")
        return redirect(url_for('teachers'))

@app.route('/delete_teacher/<teacher_id>', methods=['POST'])
def delete_teacher(teacher_id):
    try:
        print(f"Deleting teacher {teacher_id}")
        response = supabase.table('teachers').delete().eq('teacher_id', teacher_id).execute()
        if response.data or not response.error:
            print(f"Teacher deleted: {response.data}")
            flash('Teacher deleted successfully!')
            return redirect(url_for('teachers'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error deleting teacher: {error}")
            flash(f"Error deleting teacher: {error}")
            return redirect(url_for('teachers'))
    except Exception as e:
        print(f"Exception deleting teacher: {str(e)}")
        flash(f"Error deleting teacher: {str(e)}")
        return redirect(url_for('teachers'))

@app.route('/tuition')
def tuition():
    try:
        print("Fetching tuition data")
        tuition_response = supabase.table('tuition').select('tuition_id, student_id, parent_id, grade, days, total_amount, paid_in_full').execute()
        tuition_data = tuition_response.data or []
        print(f"Tuition data: {tuition_data}")
        
        students_response = supabase.table('students').select('student_id, first_name, last_name, parent_id').execute()
        students_data = students_response.data or []
        print(f"Students data (tuition): {students_data}")
        
        parents_response = supabase.table('parents').select('parent_id, first_name, last_name, is_staff').execute()
        parents_data = parents_response.data or []
        print(f"Parents data (tuition): {parents_data}")
        
        student_map = {s['student_id']: s for s in students_data}
        parent_map = {p['parent_id']: p for p in parents_data}
        
        parent_student_count = {}
        for s in students_data:
            parent_id = s['parent_id']
            parent_student_count[parent_id] = parent_student_count.get(parent_id, 0) + 1
        
        for t in tuition_data:
            student = student_map.get(t['student_id'], {})
            parent = parent_map.get(t['parent_id'], {})
            t['student_name'] = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip()
            t['parent_name'] = f"{parent.get('first_name', '')} {parent.get('last_name', '')}".strip()
            t['has_sibling_discount'] = parent_student_count.get(t['parent_id'], 0) > 1
            t['is_staff'] = parent.get('is_staff', False)
            print(f"Processed tuition: {t}")
        
        print("Rendering tuition tab")
        return render_template('index.html', active_tab='tuition', tuition=tuition_data)
    except Exception as e:
        print(f"Error fetching tuition: {str(e)}")
        flash(f"Error fetching tuition: {str(e)}")
        return render_template('index.html', active_tab='tuition', tuition=[])

@app.route('/tuition/edit/<tuition_id>', methods=['GET'])
def edit_tuition(tuition_id):
    try:
        print(f"Fetching tuition for edit: {tuition_id}")
        tuition_response = supabase.table('tuition').select('tuition_id, student_id, parent_id, grade, days, total_amount, paid_in_full').eq('tuition_id', tuition_id).execute()
        print(f"Tuition response: {tuition_response.data}")
        if not tuition_response.data:
            print(f"No tuition record found for {tuition_id}")
            flash("Tuition record not found.")
            return redirect(url_for('tuition'))
        tuition_data = tuition_response.data[0]
        
        student_response = supabase.table('students').select('student_id, first_name, last_name').eq('student_id', tuition_data['student_id']).execute()
        print(f"Student response: {student_response.data}")
        student = student_response.data[0] if student_response.data else {}
        tuition_data['student_name'] = f"{student.get('first_name', '')} {student.get('last_name', '')}".strip()
        
        print(f"Rendering with tuition_edit: {tuition_data}")
        print(f"tuition_edit keys: {list(tuition_data.keys())}")
        print(f"tuition_edit days: {tuition_data.get('days', 'No days')}")
        return render_template('index.html', active_tab='tuition', tuition_edit=tuition_data)
    except Exception as e:
        print(f"Error fetching tuition for edit: {str(e)}")
        flash(f"Error: {str(e)}")
        return redirect(url_for('tuition'))

@app.route('/tuition/update', methods=['POST'])
def update_tuition():
    try:
        print("Processing tuition update")
        data = request.form
        tuition_id = data['tuition_id']
        grade = data['grade']
        days = {
            'Mon': data.get('mon', ''),
            'Tue': data.get('tue', ''),
            'Wed': data.get('wed', ''),
            'Thu': data.get('thu', ''),
            'Fri': data.get('fri', '')
        }
        days = {k: v for k, v in days.items() if v}
        paid_in_full = data.get('paid_in_full') == 'on'

        print(f"Form data: tuition_id={tuition_id}, grade={grade}, days={days}, paid_in_full={paid_in_full}")

        # Validate days for grade K
        if grade == 'K':
            valid_types = ['morning', 'afternoon']
            for day, type in days.items():
                if type not in valid_types:
                    print(f"Invalid day type for K: {type}")
                    flash(f"Invalid day type '{type}' for Kindergarten. Use 'Morning' or 'Afternoon'.")
                    return redirect(url_for('tuition'))

        # Calculate base tuition
        base_tuition = calculate_student_tuition(grade, days)
        print(f"Base tuition: {base_tuition}")

        # Fetch parent_id and sibling count
        tuition = supabase.table('tuition').select('parent_id').eq('tuition_id', tuition_id).execute().data
        if not tuition:
            print(f"No tuition record found for {tuition_id}")
            flash("Tuition record not found.")
            return redirect(url_for('tuition'))
        parent_id = tuition[0]['parent_id']

        students = supabase.table('students').select('parent_id').execute().data
        parent_student_count = {}
        for s in students:
            parent_student_count[s['parent_id']] = parent_student_count.get(s['parent_id'], 0) + 1

        # Apply discounts
        total_amount = apply_sibling_discount(base_tuition, parent_id, parent_student_count)
        parent = supabase.table('parents').select('is_staff').eq('parent_id', parent_id).execute().data
        if parent and parent[0]['is_staff']:
            total_amount *= 0.8
        if paid_in_full:
            total_amount *= 0.95
        total_amount = round(total_amount, 2)
        print(f"Final total_amount: {total_amount}")

        # Update Supabase
        update_data = {
            'grade': grade,
            'days': days,
            'total_amount': total_amount,
            'paid_in_full': paid_in_full
        }
        print(f"Updating Supabase with: {update_data}")
        response = supabase.table('tuition').update(update_data).eq('tuition_id', tuition_id).execute()
        print(f"Supabase update response: {response.data}")
        if response.data:
            print(f"Tuition updated: {response.data}")
            flash("Tuition updated successfully.")
            return redirect(url_for('tuition'))
        else:
            error = getattr(response, 'error', 'Unknown error')
            print(f"Error updating tuition: {error}")
            flash(f"Error updating tuition: {error}")
            return redirect(url_for('tuition'))
    except Exception as e:
        print(f"Exception updating tuition: {str(e)}")
        flash(f"Error updating tuition: {str(e)}")
        return redirect(url_for('tuition'))

if __name__ == '__main__':
    app.run(debug=True)