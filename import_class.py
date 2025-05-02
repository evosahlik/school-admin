import csv
import uuid
import logging
from logging.handlers import RotatingFileHandler
import re
import os
from supabase import create_client, Client
from typing import List, Optional
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(filename='import_classes.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    filename='import_classes.log',
    format='%(asctime)s - %(levelname)s - %(message)s'
)
handler = RotatingFileHandler('import_classes.log', maxBytes=1000000, backupCount=5)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.addHandler(handler)


# CSV column names (update these if your CSV headers differ)
CSV_COLUMNS = {
    'class_name': 'Class Name',
    'grade_level': 'Grade Level',
    'term': 'Term',
    'schedule': 'Schedule',
    'teacher': 'Teacher',
    'student_count_max': 'Student Count/Max'
}

# Supabase credentials (replace with your values)
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


def normalize_term(term: str) -> str:
    """Map CSV term to database term (e.g., 'S1, S2' -> 'Both')."""
    term = clean_string(term).strip()
    if term == 'S1,S2':
        return 'Both'
    elif term == 'S1':
        return 'Semester 1'
    elif term == 'S2':
        return 'Semester 2'
    return term  # Log invalid terms later

def parse_schedule(schedule: str) -> tuple[Optional[List[int]], Optional[List[int]]]:
    """Parse Schedule to extract days and block (e.g., '- B1' -> ([2], 'B1'))."""
    schedule = clean_string(schedule)
    logging.info(f"Processing schedule: {schedule}")
    if not schedule or schedule in ['* not scheduled', 'MM', '- MM']:
        return None, None
    days = []
    blocks = []
    # Split multiple schedules (e.g., 'B1, B2' or '- B5, B6')
    entries = [s.strip() for s in schedule.split(',')]
    for entry in entries:
        # Count dashes to determine day
        dash_count = entry.count('-')
        day = None
        if dash_count == 0 and re.match(r'B\d', entry):
            day = 1  # Monday
        elif dash_count == 1 and re.match(r'-\s*B\d', entry):
            day = 2  # Tuesday
        elif dash_count == 2 and re.match(r'--\s*B\d', entry):
            day = 3  # Wednesday
        elif dash_count == 3 and re.match(r'---\s*B\d', entry):
            day = 4  # Thursday
        if day and day not in days:
            days.append(day)
        # Extract block (e.g., 'B1')
        block_match = re.search(r'B(\d)', entry)
        if block_match:
            block = int(block_match.group(1))
            if block not in blocks:
                blocks.append(block)
    # If multiple blocks, join them (e.g., ['B1', 'B2'] -> 'B1, B2')
    # block_str = ', '.join(sorted(blocks)) if blocks else None
    return sorted(days) if days else None, blocks

def parse_teacher_name(teacher: str) -> tuple[Optional[str], Optional[str]]:
    """Parse teacher name (e.g., 'Pfeil, Teandra' -> ('Teandra', 'Pfeil'))."""
    teacher = clean_string(teacher).strip()
    if not teacher or teacher == '':
        return None, None
    # Handle 'Last, First (Nickname)' or 'Last, First'
    match = re.match(r'([^,]+),\s*([^\(]+)(?:\s*\((.+)\))?', teacher.strip())
    if not match:
        logger.warning(f"Invalid teacher name format: {teacher}")
        return None, None
    last_name, first_name, _ = match.groups()
    return first_name.strip(), last_name.strip()

def get_teacher_id(first_name: str, last_name: str) -> Optional[str]:
    """Look up teacher_id by first_name and last_name."""
    try:
        response = supabase.table('teachers').select('teacher_id').eq('first_name', first_name).eq('last_name', last_name).execute()
        if response.data:
            return response.data[0]['teacher_id']
    except Exception as e:
        logger.error(f"Error looking up teacher {first_name} {last_name}: {str(e)}")
    return None

def parse_student_count_max(count_max: str) -> tuple[Optional[int], Optional[int]]:
    """Parse '10 / 15' or '* no students' -> (student_count, max_size)."""
    count_max = clean_string(count_max).strip()
    if count_max == '* no students':
        return 0, None
    match = re.match(r'(\d+)\s*/\s*(\d+)', count_max)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None

def validate_csv_headers(reader: csv.DictReader) -> bool:
    """Validate that required CSV headers are present, handling BOM."""
    required_headers = list(CSV_COLUMNS.values())
    actual_headers = [h.replace('\ufeff', '') for h in reader.fieldnames]
    missing_headers = [h for h in required_headers if h not in actual_headers]
    if missing_headers:
        logging.error(f"Missing CSV headers: {', '.join(missing_headers)}")
        return False
    return True


def import_classes(csv_file: str):
    """Import classes from CSV into Supabase."""
    seen_classes = set()
    try:
        with open(csv_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if not validate_csv_headers(reader):
                logging.error(f"CSV file {csv_file} has invalid headers")
                return
            
            for row in reader:
                row = {k.replace('\ufeff', ''): clean_string(v) for k, v in row.items()}
                logging.info(f"Processing row: {row}")
                
                class_name = re.sub(r'\s*\[.*\]', '', row[CSV_COLUMNS['class_name']]).strip()
                
                class_key = (class_name, row[CSV_COLUMNS['term']])
                if class_key in seen_classes:
                    logging.warning(f"Skipping duplicate class: {class_name}, term: {row[CSV_COLUMNS['term']]}, row: {row}")
                    continue
                seen_classes.add(class_key)
                
                try:
                    grade_level = normalize_grade_level(row[CSV_COLUMNS['grade_level']])
                    
                    term = normalize_term(row[CSV_COLUMNS['term']])
                    if term not in ['Semester 1', 'Semester 2', 'Both']:
                        logging.warning(f"Invalid term for class {class_name}: {term}")
                        continue
                    
                    days, schedule_block = parse_schedule(row[CSV_COLUMNS['schedule']])
                    
                    first_name, last_name = parse_teacher_name(row[CSV_COLUMNS['teacher']])
                    teacher_id = get_teacher_id(first_name, last_name) if first_name and last_name else None
                    if not teacher_id and first_name and last_name:
                        logging.warning(f"Teacher not found for class {class_name}: {first_name} {last_name}")
                    
                    student_count, max_size = parse_student_count_max(row[CSV_COLUMNS['student_count_max']])
                    
                    classroom_id = None
                    
                    class_data = {
                        'class_id': str(uuid.uuid4()),
                        'name': class_name,
                        'days': days,
                        'teacher_id': teacher_id,
                        'grade_level': grade_level,
                        'max_size': max_size,
                        'term': term,
                        'schedule_block': schedule_block,
                        'classroom_id': classroom_id
                    }
                    
                    logging.info(f"Inserting class_data: {class_data}")
                    supabase.table('classes').insert(class_data).execute()
                    logging.info(f"Inserted class: {class_name}")
                    
                    if student_count:
                        logging.info(f"Class {class_name} has {student_count} students to assign manually")
                    
                except Exception as e:
                    logging.error(f"Error importing class {class_name}: {str(e)}")
                    continue
    except FileNotFoundError:
        logging.error(f"CSV file {csv_file} not found")
    except Exception as e:
        logging.error(f"Error opening CSV file {csv_file}: {str(e)}")


if __name__ == "__main__":
    import_classes('VLA_classes.csv')