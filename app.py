from flask import Flask, render_template, request, redirect, url_for
from supabase import create_client, Client

app = Flask(__name__)

# Supabase setup
url = "https://vemywpbjbubftpvthaen.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZlbXl3cGJqYnViZnRwdnRoYWVuIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDQxMjAzOTQsImV4cCI6MjA1OTY5NjM5NH0.qxMKhyg2uMBylrvP5JdSy3LCHM46uZeOtcuOjeJbAmM"
supabase: Client = create_client(url, key)

@app.route('/')
def index():
    return redirect(url_for('students'))  # Default to students

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
    return redirect(url_for('students'))

@app.route('/classes')
def classes():
    response = supabase.table('classes').select('*').execute()
    classes = response.data
    return render_template('index.html', classes=classes, active_tab='classes')

@app.route('/add_class', methods=['POST'])
def add_class():
    name = request.form['name']
    days_attending = request.form['days_attending'].split(',')  # Convert comma-separated to list
    additional_costs = float(request.form['additional_costs'] or 0)
    data = {
        'name': name,
        'days_attending': days_attending,
        'additional_costs': additional_costs
    }
    response = supabase.table('classes').insert(data).execute()
    if hasattr(response, 'error') and response.error:
        return f"Error adding class: {response.error}", 500
    return redirect(url_for('classes'))

if __name__ == '__main__':
    app.run(debug=True)