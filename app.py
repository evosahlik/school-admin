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
    # Remove non-digits
    digits = ''.join(filter(str.isdigit, phone))
    if len(digits) != 10:
        return phone  # Return as-is if not 10 digits
    return f"({digits[:3]}){digits[3:6]}-{digits[6:]}"

app.jinja_env.filters['format_phone'] = format_phone

@app.route('/')
def index():
    return redirect(url_for('students'))

@app.route('/students')
def students():
    response = supabase.table('students').select('*').execute()
    students = response.data
    return render_template('index.html', students=students, active_tab='students')

@app.route('/add_student', methods=['POST'])
def add_student():
    first_name = request.form['first_name']
    last_name = request.form['last_name']
    grade_level = request.form['grade_level']
    parent_email = request.form['parent_email']
    data = {
        'first_name': first_name,
        'last_name': last_name,
        'grade_level': grade_level,
        'parent_email': parent_email
    }
    response = supabase.table('students').insert(data).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error adding student: {response.error}", 500
    flash('Student added successfully!')
    return redirect(url_for('students'))

@app.route('/classes')
def classes():
    class_response = supabase.table('classes').select('*, teachers(first_name, last_name)').execute()
    classes = class_response.data
    enroll_response = supabase.table('enrollments').select('class_id, student_id, students(first_name, last_name)').execute()
    enrollments = enroll_response.data
    student_response = supabase.table('students').select('*').execute()
    students = student_response.data
    teacher_response = supabase.table('teachers').select('*').execute()
    teachers = teacher_response.data
    return render_template('index.html', classes=classes, enrollments=enrollments, students=students, teachers=teachers, active_tab='classes')

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
    data = {
        'name': name,
        'days_attending': days_attending,
        'additional_costs': additional_costs,
        'teacher_id': teacher_id
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
    return render_template('index.html', teachers=teachers, active_tab='teachers')

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
    data = {
        'name': name,
        'days_attending': days_attending,
        'additional_costs': additional_costs,
        'teacher_id': teacher_id
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

if __name__ == '__main__':
    app.run(debug=True)