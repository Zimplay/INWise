from flask import Flask, request, jsonify, send_from_directory, redirect, url_for, render_template, flash
from flask_cors import CORS
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import StaticPool
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
import subprocess
import re
import logging
import sys
from datetime import datetime, timedelta
import sqlite3

# Настройка логирования
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Измените на реальный секретный ключ
CORS(app)

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database setup
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(BASE_DIR, 'errors.db')

# Убедимся, что директория для базы данных существует
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Удаляем файл базы данных, если он существует
if os.path.exists(db_path):
    try:
        os.remove(db_path)
        logger.info(f"Существующий файл базы данных удален: {db_path}")
    except Exception as e:
        logger.error(f"Ошибка при удалении файла базы данных: {e}")

try:
    # Создаем подключение к базе данных
    engine = create_engine(
        f'sqlite:///{db_path}',
        echo=True,
        connect_args={
            'check_same_thread': False,
            'timeout': 30
        },
        poolclass=StaticPool
    )
    
    Base = declarative_base()
    
    # Используем scoped_session для потокобезопасности
    session_factory = sessionmaker(bind=engine)
    Session = scoped_session(session_factory)
    
    # Проверяем соединение с базой данных
    with engine.connect() as conn:
        # Проверяем, можем ли мы выполнить простой запрос
        conn.execute("SELECT 1")
        logger.info("Подключение к базе данных успешно установлено")
        
except Exception as e:
    logger.error(f"Ошибка при подключении к базе данных: {e}")
    sys.exit(1)

# Модель пользователя
class User(UserMixin, Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    password_hash = Column(String(120), nullable=False)
    email = Column(String(120), unique=True, nullable=True)
    full_name = Column(String(120), nullable=True)
    role = Column(String(20), default='user')
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Модель ошибки
class Error(Base):
    __tablename__ = 'errors'
    
    id = Column(Integer, primary_key=True)
    error_type = Column(String(100))
    message = Column(Text)
    stack_trace = Column(Text)
    environment = Column(String(50))
    user_agent = Column(String(200))
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default='open')
    resolution = Column(Text, nullable=True)
    resolution_time = Column(DateTime, nullable=True)
    affected_component = Column(String(100))
    severity = Column(String(20))
    impact = Column(Text)
    source = Column(String(50), default='manual')
    inwise_id = Column(String(100), nullable=True)

# Создаем все таблицы
try:
    Base.metadata.create_all(engine)
    logger.info("Таблицы базы данных успешно созданы")
except Exception as e:
    logger.error(f"Ошибка при создании таблиц: {e}")
    sys.exit(1)

def get_db_session():
    try:
        session = Session()
        return session
    except Exception as e:
        logger.error(f"Ошибка при создании сессии базы данных: {e}")
        raise

# Создаем тестового пользователя, если его нет
def create_test_user():
    session = None
    try:
        session = get_db_session()
        # Проверяем, есть ли уже пользователи
        if not session.query(User).first():
            # Создаем тестового пользователя
            test_user = User(
                username='admin',
                email='admin@example.com',
                full_name='Administrator',
                role='admin'
            )
            test_user.set_password('admin')
            session.add(test_user)
            session.commit()
            logger.info("Создан тестовый пользователь: admin/admin")
    except Exception as e:
        logger.error(f"Ошибка при создании тестового пользователя: {e}")
        if session:
            session.rollback()
    finally:
        if session:
            session.close()

@app.teardown_appcontext
def shutdown_session(exception=None):
    Session.remove()

# Создаем тестового пользователя при запуске
create_test_user()

@login_manager.user_loader
def load_user(user_id):
    session = None
    try:
        session = get_db_session()
        return session.query(User).get(int(user_id))
    except Exception as e:
        logger.error(f"Ошибка при загрузке пользователя: {e}")
        return None
    finally:
        if session:
            session.close()

def parse_inwise_output(output):
    """Парсит вывод из INWise и преобразует в структурированные данные"""
    logger.info("Parsing INWise output")
    errors = []
    current_error = {}
    
    for line in output.split('\n'):
        line = line.strip()
        if not line:
            if current_error:
                logger.debug(f"Parsed error: {current_error}")
                errors.append(current_error)
                current_error = {}
            continue
            
        if line.startswith('Error:'):
            current_error['error_type'] = line[6:].strip()
        elif line.startswith('Message:'):
            current_error['message'] = line[8:].strip()
        elif line.startswith('Component:'):
            current_error['affected_component'] = line[10:].strip()
        elif line.startswith('Severity:'):
            current_error['severity'] = line[9:].strip().lower()
        elif line.startswith('Stack:'):
            current_error['stack_trace'] = line[6:].strip()
        elif line.startswith('ID:'):
            current_error['inwise_id'] = line[3:].strip()
        elif line.startswith('Impact:'):
            current_error['impact'] = line[7:].strip()
            
    if current_error:
        logger.debug(f"Parsed error: {current_error}")
        errors.append(current_error)
    
    logger.info(f"Total parsed errors: {len(errors)}")
    return errors

def get_inwise_errors():
    """Получает ошибки из INWise через командную строку"""
    try:
        logger.info("Attempting to get errors from INWise")
        # Проверяем наличие INWise CLI
        inwise_path = os.environ.get('INWISE_PATH', 'inwise')
        
        # Пробуем получить данные из файла или другого источника, если INWise недоступен
        if not os.path.exists('sample_errors.json'):
            # Создаем пример данных
            sample_errors = [
                {
                    'error_type': 'DatabaseConnection',
                    'message': 'Failed to connect to database',
                    'affected_component': 'Database',
                    'severity': 'high',
                    'stack_trace': 'at Database.connect():line 45\nat App.start():line 23',
                    'inwise_id': 'INW-001',
                    'impact': 'Service unavailable'
                },
                {
                    'error_type': 'APITimeout',
                    'message': 'API request timed out',
                    'affected_component': 'API',
                    'severity': 'medium',
                    'stack_trace': 'at API.request():line 78\nat Service.call():line 34',
                    'inwise_id': 'INW-002',
                    'impact': 'Slow response time'
                }
            ]
            with open('sample_errors.json', 'w') as f:
                json.dump(sample_errors, f)
        
        try:
            # Пробуем использовать INWise CLI
            cmd = [inwise_path, 'errors', '--format=detailed', '--last=24h']
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info("Successfully retrieved errors from INWise")
                return parse_inwise_output(result.stdout)
            else:
                logger.warning(f"INWise CLI error: {result.stderr}")
                # Если INWise недоступен, используем данные из файла
                raise FileNotFoundError
                
        except FileNotFoundError:
            logger.info("INWise CLI not found, using sample data")
            with open('sample_errors.json', 'r') as f:
                return json.load(f)
                
    except Exception as e:
        logger.error(f"Error getting INWise errors: {str(e)}")
        return []

def sync_inwise_errors():
    """Синхронизирует ошибки из INWise с локальной базой данных"""
    logger.info("Starting INWise sync")
    
    try:
        # Запускаем приложение INWise
        inwise_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'INWise', 'main.py')
        if not os.path.exists(inwise_path):
            logger.error(f"INWise application not found at {inwise_path}")
            return jsonify({"error": "INWise application not found"}), 404
            
        # Создаем временный файл для передачи данных
        temp_data_file = os.path.join(os.path.dirname(inwise_path), 'temp_data.json')
        
        # Экспортируем текущие ошибки для INWise
        session = get_db_session()
        try:
            current_errors = session.query(Error).filter(
                Error.source != 'inwise'
            ).all()
            
            export_data = [{
                'error_type': error.error_type,
                'message': error.message,
                'stack_trace': error.stack_trace,
                'severity': error.severity,
                'affected_component': error.affected_component,
                'impact': error.impact,
                'status': error.status,
                'resolution': error.resolution,
                'timestamp': error.timestamp.isoformat() if error.timestamp else None
            } for error in current_errors]
            
            with open(temp_data_file, 'w') as f:
                json.dump(export_data, f)
                
        finally:
            session.close()
            
        # Запускаем INWise в отдельном процессе с флагом импорта
        logger.info("Launching INWise application")
        process = subprocess.Popen([sys.executable, inwise_path, '--import', temp_data_file], 
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 text=True)
        
        try:
            stdout, stderr = process.communicate(timeout=30)
            if process.returncode != 0:
                logger.error(f"INWise process failed: {stderr}")
                return jsonify({"error": "INWise process failed", "details": stderr}), 500
        except subprocess.TimeoutExpired:
            process.kill()
            logger.error("INWise process timed out")
            return jsonify({"error": "INWise process timed out"}), 504
        finally:
            # Очищаем временный файл
            if os.path.exists(temp_data_file):
                os.remove(temp_data_file)
            
        # Проверяем наличие output файла от INWise
        inwise_output = os.path.join(os.path.dirname(inwise_path), 'errors.json')
        if not os.path.exists(inwise_output):
            logger.error("INWise output file not found")
            return jsonify({"error": "INWise output file not found"}), 404
            
        # Читаем данные из файла
        with open(inwise_output, 'r') as f:
            inwise_data = json.load(f)
            
        # Сохраняем данные в базу
        session = get_db_session()
        try:
            for error_data in inwise_data:
                existing_error = session.query(Error).filter_by(inwise_id=error_data.get('inwise_id')).first()
                
                if not existing_error:
                    logger.info(f"Adding new error from INWise: {error_data.get('inwise_id')}")
                    error = Error(
                        error_type=error_data.get('error_type'),
                        message=error_data.get('message'),
                        stack_trace=error_data.get('stack_trace'),
                        environment=error_data.get('environment', 'production'),
                        affected_component=error_data.get('affected_component'),
                        severity=error_data.get('severity', 'medium'),
                        impact=error_data.get('impact'),
                        source='inwise',
                        inwise_id=error_data.get('inwise_id')
                    )
                    session.add(error)
                else:
                    # Обновляем существующую ошибку
                    existing_error.severity = error_data.get('severity', existing_error.severity)
                    existing_error.impact = error_data.get('impact', existing_error.impact)
                    existing_error.status = error_data.get('status', existing_error.status)
                    
            session.commit()
            logger.info("Successfully synced INWise errors")
            return jsonify({"message": "Sync completed successfully", "errors_count": len(inwise_data)}), 200
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error syncing INWise data: {str(e)}")
            return jsonify({"error": "Database error", "details": str(e)}), 500
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Unexpected error during INWise sync: {str(e)}")
        return jsonify({"error": "Unexpected error", "details": str(e)}), 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        session = get_db_session()
        try:
            user = session.query(User).filter_by(username=request.form['username']).first()
            if user and user.check_password(request.form['password']):
                login_user(user)
                return redirect(url_for('index'))
            flash('Неверное имя пользователя или пароль')
        finally:
            session.close()
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        session = get_db_session()
        try:
            if session.query(User).filter_by(username=request.form['username']).first():
                flash('Пользователь с таким именем уже существует')
                return redirect(url_for('register'))
            
            user = User(username=request.form['username'])
            user.set_password(request.form['password'])
            session.add(user)
            session.commit()
            
            login_user(user)
            return redirect(url_for('index'))
        finally:
            session.close()
    return render_template('register.html')

@app.route('/')
@login_required
def index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
@login_required
def static_files(path):
    # Разрешаем доступ к login.html и register.html без авторизации
    if path in ['login.html', 'register.html']:
        return send_from_directory('static', path)
    return send_from_directory('static', path)

@app.route('/api/errors', methods=['GET'])
@login_required
def get_errors():
    logger.info("Getting errors with filters")
    # Синхронизируем данные с INWise при каждом запросе
    sync_inwise_errors()
    
    session = get_db_session()
    try:
        status = request.args.get('status', 'all')
        source = request.args.get('source', 'all')
        severity = request.args.get('severity', 'all')
        component = request.args.get('component')
        
        query = session.query(Error)
        
        # Применяем фильтры
        if status != 'all':
            query = query.filter(Error.status == status)
        
        if source != 'all':
            query = query.filter(Error.source == source)
            
        if severity != 'all':
            query = query.filter(Error.severity == severity)
            
        if component:
            query = query.filter(Error.affected_component.ilike(f'%{component}%'))
            
        # Сортируем по времени (новые первыми) и серьезности
        query = query.order_by(Error.severity.desc(), Error.timestamp.desc())
        
        errors = query.all()
        logger.info(f"Found {len(errors)} errors matching filters")
        
        return jsonify([{
            'id': error.id,
            'error_type': error.error_type,
            'message': error.message,
            'stack_trace': error.stack_trace,
            'environment': error.environment,
            'timestamp': error.timestamp.isoformat(),
            'status': error.status,
            'resolution': error.resolution,
            'resolution_time': error.resolution_time.isoformat() if error.resolution_time else None,
            'severity': error.severity,
            'affected_component': error.affected_component,
            'impact': error.impact,
            'source': error.source,
            'inwise_id': error.inwise_id
        } for error in errors])
    except Exception as e:
        logger.error(f"Error getting errors: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@app.route('/api/errors', methods=['POST'])
@login_required
def log_error():
    logger.info("Logging new error")
    data = request.json
    session = get_db_session()
    
    try:
        error = Error(
            error_type=data.get('error_type'),
            message=data.get('message'),
            stack_trace=data.get('stack_trace'),
            environment=data.get('environment'),
            user_agent=request.headers.get('User-Agent'),
            severity=data.get('severity', 'medium'),
            affected_component=data.get('affected_component'),
            impact=data.get('impact'),
            source='manual'
        )
        
        session.add(error)
        session.commit()
        logger.info(f"Successfully logged error with id: {error.id}")
        return jsonify({"status": "success", "error_id": error.id})
    except Exception as e:
        session.rollback()
        logger.error(f"Error logging error: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@app.route('/api/errors/<int:error_id>/resolve', methods=['POST'])
@login_required
def resolve_error(error_id):
    logger.info(f"Resolving error {error_id}")
    session = get_db_session()
    data = request.json
    
    try:
        error = session.query(Error).get(error_id)
        if error:
            error.status = 'resolved'
            error.resolution = data.get('resolution')
            error.resolution_time = datetime.utcnow()
            session.commit()
            logger.info(f"Successfully resolved error {error_id}")
            return jsonify({"status": "success"})
        logger.warning(f"Error {error_id} not found")
        return jsonify({"status": "error", "message": "Error not found"}), 404
    except Exception as e:
        session.rollback()
        logger.error(f"Error resolving error {error_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@app.route('/api/errors/sync', methods=['POST'])
@login_required
def sync_errors():
    """Синхронизация ошибок с INWise"""
    try:
        logger.info("Starting error synchronization with INWise")
        data = request.get_json()
        
        if not data or 'errors' not in data:
            return jsonify({'error': 'No errors data provided'}), 400
            
        session = get_db_session()
        try:
            for error_data in data['errors']:
                # Проверяем существование ошибки с таким же описанием
                existing_error = session.query(Error).filter_by(
                    message=error_data['message'],
                    error_type=error_data['error_type'],
                    source='inwise'
                ).first()
                
                if not existing_error:
                    # Создаем новую ошибку
                    new_error = Error(
                        error_type=error_data['error_type'],
                        message=error_data['message'],
                        stack_trace=error_data.get('stack_trace', ''),
                        environment=error_data.get('environment', 'production'),
                        affected_component=error_data.get('affected_component', 'Unknown'),
                        severity=error_data.get('severity', 'medium'),
                        impact=error_data.get('impact', ''),
                        source='inwise',
                        status='open'
                    )
                    session.add(new_error)
                    logger.info(f"Added new error: {error_data['error_type']}")
                
            session.commit()
            return jsonify({'status': 'success', 'message': 'Errors synchronized successfully'}), 200
            
        except Exception as e:
            session.rollback()
            logger.error(f"Error during synchronization: {str(e)}")
            return jsonify({'error': str(e)}), 500
        finally:
            session.close()
            
    except Exception as e:
        logger.error(f"Error processing sync request: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/errors/stats', methods=['GET'])
@login_required
def get_error_stats():
    """Получение статистики по ошибкам"""
    logger.info("Getting error statistics")
    session = get_db_session()
    try:
        # Общее количество ошибок
        total_errors = session.query(Error).count()
        
        # Открытые ошибки по серьезности
        high_severity = session.query(Error).filter_by(status='open', severity='high').count()
        medium_severity = session.query(Error).filter_by(status='open', severity='medium').count()
        low_severity = session.query(Error).filter_by(status='open', severity='low').count()
        
        # Процент решенных ошибок
        resolved_errors = session.query(Error).filter_by(status='resolved').count()
        resolution_rate = (resolved_errors / total_errors * 100) if total_errors > 0 else 0
        
        # Ошибки по источникам
        inwise_errors = session.query(Error).filter_by(source='inwise').count()
        manual_errors = session.query(Error).filter_by(source='manual').count()
        
        stats = {
            'total_errors': total_errors,
            'high_severity_open': high_severity,
            'medium_severity_open': medium_severity,
            'low_severity_open': low_severity,
            'resolution_rate': round(resolution_rate, 2),
            'inwise_errors': inwise_errors,
            'manual_errors': manual_errors
        }
        
        logger.info(f"Statistics calculated: {stats}")
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting statistics: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

@app.route('/api/sync', methods=['POST'])
@login_required
def sync_with_inwise():
    """Endpoint для синхронизации с INWise"""
    try:
        logger.info("Starting sync with INWise")
        # Получаем параметры синхронизации из запроса
        sync_params = request.get_json() or {}
        force_sync = sync_params.get('force', False)
        
        # Проверяем время последней синхронизации
        last_sync_file = os.path.join(os.path.dirname(__file__), 'last_sync.txt')
        if os.path.exists(last_sync_file) and not force_sync:
            with open(last_sync_file, 'r') as f:
                last_sync = datetime.fromisoformat(f.read().strip())
                if datetime.now() - last_sync < timedelta(minutes=5):
                    logger.info("Skipping sync - too soon since last sync")
                    return jsonify({
                        "status": "skipped", 
                        "message": "Last sync was less than 5 minutes ago. Use force=true to override."
                    }), 200

        # Запускаем синхронизацию
        result = sync_inwise_errors()
        
        # Если синхронизация успешна, обновляем время последней синхронизации
        if isinstance(result, tuple):
            response, status_code = result
            if status_code == 200:
                with open(last_sync_file, 'w') as f:
                    f.write(datetime.now().isoformat())
                logger.info("Sync completed successfully")
            else:
                logger.error(f"Sync failed with status {status_code}: {response}")
            return response, status_code
        return result

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error in sync endpoint: {error_msg}")
        return jsonify({
            "status": "error",
            "message": f"Sync failed: {error_msg}"
        }), 500

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        session = get_db_session()
        try:
            user = session.query(User).get(current_user.id)
            if user:
                user.email = request.form.get('email', user.email)
                user.full_name = request.form.get('full_name', user.full_name)
                
                # Проверка и обновление пароля
                new_password = request.form.get('new_password')
                if new_password and request.form.get('current_password'):
                    if user.check_password(request.form.get('current_password')):
                        user.set_password(new_password)
                        flash('Пароль успешно обновлен', 'success')
                    else:
                        flash('Неверный текущий пароль', 'error')
                
                session.commit()
                flash('Профиль успешно обновлен', 'success')
                return redirect(url_for('profile'))
        except Exception as e:
            session.rollback()
            flash(f'Ошибка при обновлении профиля: {str(e)}', 'error')
        finally:
            session.close()
    
    return render_template('profile.html', user=current_user)

if __name__ == '__main__':
    app.run(debug=True)
