from flask import Flask, render_template, request, redirect, url_for, flash
from supabase import create_client, Client

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Replace with your unique key

# Supabase setup
url = "https://vemywpbjbubftpvthaen.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZlbXl3cGJqYnViZnRwdnRoYWVuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDQxMjAzOTQsImV4cCI6MjA1OTY5NjM5NH0.qxMKhyg2uMBylrvP5JdSy3LCHM46uZeOtcuOjeJbAmM"
supabase: Client = create_client(url, key)

def format_phone(phone):
    if not phone:
        return ""
    digits = ''.join(filter(str.isdigit, phone))
    if len(digits) != 10:
        return phone
    return f"({digits[:3]}){digits[3:6]}-{digits[6:]}"

app.jinja_env.filters['format_phone'] = format_phone

@app.route('/')
def index():
    return redirect(url_for('students'))

@app.route('/students')
def students():
    student_response = supabase.table('students').select('*, parents(first_name, last_name)').execute()
    parent_response = supabase.table('parents').select('*').execute()
    students = student_response.data
    parents = parent_response.data
    return render_template('index.html', students=students, parents=parents, active_tab='students')

@app.route('/add_student', methods=['POST'])
def add_student():
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
        return f"Error adding student: {response.error}", 500
    flash('Student added successfully!')
    return redirect(url_for('students'))

@app.route('/edit_student', methods=['POST'])
def edit_student():
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
        return f"Error updating student: {response.error}", 500
    flash('Parent updated successfully!')
    return redirect(url_for('students'))

@app.route('/parents')
def parents():
    parent_response = supabase.table('parents').select('*, students(first_name, last_name)').execute()
    parents = parent_response.data
    for parent in parents:
        if not parent.get('parent_id'):
            print(f"Warning: Parent {parent.get('first_name', 'Unknown')} {parent.get('last_name', '')} has no parent_id")
    return render_template('index.html', parents=parents, active_tab='parents')

@app.route('/add_parent', methods=['POST'])
def add_parent():
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
    response = supabase.table('parents').insert(data).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error adding parent: {response.error}", 500
    flash('Parent added successfully!')
    return redirect(url_for('parents'))

@app.route('/edit_parent', methods=['POST'])
def edit_parent():
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
    data = {
        'first_name': first_name,
        'last_name': last_name,
        'email': email,
        'phone': phone
    }
    try:
        response = supabase.table('parents').update(data).eq('parent_id', parent_id).execute()
        if hasattr(response, 'error') and response.error:
            print(f"Supabase error updating parent: {response.error}")
            return f"Error updating parent: {response.error}", 500
        print(f"Parent updated successfully: {parent_id}", data)
        flash('Parent updated successfully!')
    except Exception as e:
        print(f"Exception updating parent: {str(e)}")
        flash(f"Error updating parent: {str(e)}")
        return redirect(url_for('parents'))
    return redirect(url_for('parents'))

@app.route('/delete_parent/<parent_id>', methods=['POST'])
def delete_parent(parent_id):
    supabase.table('students').update({'parent_id': None}).eq('parent_id', parent_id).execute()
    response = supabase.table('parents').delete().eq('parent_id', parent_id).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error deleting parent: {response.error}", 500
    flash('Parent deleted successfully!')
    return redirect(url_for('parents'))

@app.route('/classes')
def classes():
    class_response = supabase.table('classes').select('*, teachers(first_name, last_name), classrooms(name)').execute()
    classes = class_response.data
    enroll_response = supabase.table('enrollments').select('class_id, student_id, students(first_name, last_name)').execute()
    enrollments = enroll_response.data
    student_response = supabase.table('students').select('*').execute()
    students = student_response.data
    teacher_response = supabase.table('teachers').select('*').execute()
    teachers = teacher_response.data
    classroom_response = supabase.table('classrooms').select('*').execute()
    classrooms = classroom_response.data
    parent_response = supabase.table('parents').select('*').execute()
    parents = parent_response.data
    return render_template('index.html', classes=classes, enrollments=enrollments, students=students, teachers=teachers, classrooms=classrooms, parents=parents, active_tab='classes')

@app.route('/add_class', methods=['POST'])
def add_class():
    name = request.form['name']
    days_attending = request.form.getlist('days_attending')
    valid_days = {"Monday", "Tuesday", "Wednesday", "Thursday"}
    if not all(day in valid_days for day in days_attending):
        flash('Invalid days selected. Only Monday, Tuesday, Wednesday, Thursday allowed.')
        return redirect(url_for('classes'))
    additional_costs = float(request.form['additional_costs'] or 0)
    teacher_id = request.form['teacher_id'] or None
    classroom_id = request.form['classroom_id'] or None
    data = {
        'name': name,
        'days_attending': days_attending,
        'additional_costs': additional_costs,
        'teacher_id': teacher_id,
        'classroom_id': classroom_id
    }
    response = supabase.table('classes').insert(data).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error adding class: {response.error}", 500
    flash('Class added successfully!')
    return redirect(url_for('classes'))

@app.route('/enroll_student', methods=['POST'])
def enroll_student():
    class_id = request.form['class_id']
    student_id = request.form['student_id']
    check = supabase.table('enrollments').select('enrollment_id').eq('class_id', class_id).eq('student_id', student_id).execute()
    if check.data:
        flash('Student is already enrolled in this class.')
        return redirect(url_for('classes'))
    data = {
        'class_id': class_id,
        'student_id': student_id
    }
    response = supabase.table('enrollments').insert(data).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error enrolling student: {response.error}", 500
    flash('Student enrolled successfully!')
    return redirect(url_for('classes'))

@app.route('/teachers')
def teachers():
    response = supabase.table('teachers').select('*').execute()
    teachers = response.data
    parent_response = supabase.table('parents').select('*').execute()
    parents = parent_response.data
    return render_template('index.html', teachers=teachers, parents=parents, active_tab='teachers')

@app.route('/add_teacher', methods=['POST'])
def add_teacher():
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
        return f"Error adding teacher: {response.error}", 500
    flash('Teacher added successfully!')
    return redirect(url_for('teachers'))

@app.route('/edit_class', methods=['POST'])
def edit_class():
    class_id = request.form['class_id']
    name = request.form['name']
    days_attending = request.form.getlist('days_attending')
    valid_days = {"Monday", "Tuesday", "Wednesday", "Thursday"}
    if not all(day in valid_days for day in days_attending):
        flash('Invalid days selected. Only Monday, Tuesday, Wednesday, Thursday allowed.')
        return redirect(url_for('classes'))
    additional_costs = float(request.form['additional_costs'] or 0)
    teacher_id = request.form['teacher_id'] or None
    classroom_id = request.form['classroom_id'] or None
    data = {
        'name': name,
        'days_attending': days_attending,
        'additional_costs': additional_costs,
        'teacher_id': teacher_id,
        'classroom_id': classroom_id
    }
    response = supabase.table('classes').update(data).eq('class_id', class_id).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error updating class: {response.error}", 500
    flash('Class updated successfully!')
    return redirect(url_for('classes'))

@app.route('/delete_class/<class_id>', methods=['POST'])
def delete_class(class_id):
    supabase.table('enrollments').delete().eq('class_id', class_id).execute()
    response = supabase.table('classes').delete().eq('class_id', class_id).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error deleting class: {response.error}", 500
    flash('Class deleted successfully!')
    return redirect(url_for('classes'))

@app.route('/delete_teacher/<teacher_id>', methods=['POST'])
def delete_teacher(teacher_id):
    supabase.table('classes').update({'teacher_id': None}).eq('teacher_id', teacher_id).execute()
    response = supabase.table('teachers').delete().eq('teacher_id', teacher_id).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error deleting teacher: {response.error}", 500
    flash('Teacher deleted successfully!')
    return redirect(url_for('teachers'))

@app.route('/delete_student/<student_id>', methods=['POST'])
def delete_student(student_id):
    supabase.table('enrollments').delete().eq('student_id', student_id).execute()
    response = supabase.table('students').delete().eq('student_id', student_id).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error deleting student: {response.error}", 500
    flash('Student deleted successfully!')
    return redirect(url_for('students'))

@app.route('/classrooms')
def classrooms():
    response = supabase.table('classrooms').select('*').execute()
    classrooms = response.data
    parent_response = supabase.table('parents').select('*').execute()
    parents = parent_response.data
    return render_template('index.html', classrooms=classrooms, parents=parents, active_tab='classrooms')

@app.route('/add_classroom', methods=['POST'])
def add_classroom():
    name = request.form['name']
    capacity = int(request.form['capacity'])
    data = {
        'name': name,
        'capacity': capacity
    }
    response = supabase.table('classrooms').insert(data).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error adding classroom: {response.error}", 500
    flash('Classroom added successfully!')
    return redirect(url_for('classrooms'))

@app.route('/delete_classroom/<classroom_id>', methods=['POST'])
def delete_classroom(classroom_id):
    supabase.table('classes').update({'classroom_id': None}).eq('classroom_id', classroom_id).execute()
    response = supabase.table('classrooms').delete().eq('classroom_id', classroom_id).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error deleting classroom: {response.error}", 500
    flash('Classroom deleted successfully!')
    return redirect(url_for('classrooms'))

@app.route('/reports')
def reports():
    response = supabase.table('students').select('grade_level').execute()
    students = response.data
    parent_response = supabase.table('parents').select('*').execute()
    parents = parent_response.data
    grade_counts = {'K-2': 0, '3-5': 0, '6-8': 0, '9-12': 0}
    for student in students:
        grade = student['grade_level']
        try:
            if grade.lower() == 'k':
                grade_counts['K-2'] += 1
            else:
                grade_num = int(grade)
                if 1 <= grade_num <= 2:
                    grade_counts['K-2'] += 1
                elif 3 <= grade_num <= 5:
                    grade_counts['3-5'] += 1
                elif 6 <= grade_num <= 8:
                    grade_counts['6-8'] += 1
                elif 9 <= grade_num <= 12:
                    grade_counts['9-12'] += 1
        except ValueError:
            continue
    return render_template('index.html', grade_counts=grade_counts, parents=parents, active_tab='reports')

if __name__ == '__main__':
    app.run(debug=True)