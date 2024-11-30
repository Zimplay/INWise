import sys
import xml.etree.ElementTree as ET
import json
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QLabel, 
                           QWidget, QTabWidget, QVBoxLayout, QHBoxLayout,
                           QFileDialog, QLineEdit, QDialog, QScrollArea, QFrame,
                           QMessageBox, QTextEdit, QPlainTextEdit, QInputDialog,
                           QTableWidget, QTableWidgetItem)
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import Qt
import os
import argparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import numpy as np
import pandas as pd
from datetime import datetime
import webbrowser
import telegram
import asyncio
import traceback
from functools import wraps
import requests
import aiohttp

# Определяем API_KEY в глобальной области видимости
API_KEY = "e6e1ebbc30b1441b873a352140c7ec5f"

# Инициализация модели и токенизатора
# model_name = "gpt2"
# tokenizer = GPT2Tokenizer.from_pretrained(model_name)
# model = GPT2LMHeadModel.from_pretrained(model_name)

# Функция для анализа текста с использованием модели GPT-2
# def analyze_with_gpt(text):
#     inputs = tokenizer.encode(text, return_tensors="pt")
#     outputs = model.generate(inputs, max_length=100, num_return_sequences=1)
#     generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
#     return generated_text

class ErrorAnalyzer:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(max_features=100)
        self.kmeans = KMeans(n_clusters=3, random_state=42)
        self.scaler = StandardScaler()
        
    def analyze_errors(self, errors):
        if not errors:
            return []
            
        # Подготовка текстовых данных
        texts = [f"{error.get('error_type', '')} {error.get('message', '')} {error.get('stack_trace', '')}" 
                for error in errors]
        
        # Векторизация текста
        text_features = self.vectorizer.fit_transform(texts)
        
        # Подготовка числовых признаков
        numeric_features = []
        for error in errors:
            features = [
                len(error.get('stack_trace', '')),
                1 if error.get('severity') == 'high' else 0.5 if error.get('severity') == 'medium' else 0,
                len(error.get('affected_component', '')),
            ]
            numeric_features.append(features)
            
        numeric_features = self.scaler.fit_transform(numeric_features)
        
        # Объединение признаков
        combined_features = np.hstack([text_features.toarray(), numeric_features])
        
        # Кластеризация
        clusters = self.kmeans.fit_predict(combined_features)
        
        # Анализ кластеров
        cluster_info = []
        for cluster_id in range(self.kmeans.n_clusters):
            cluster_errors = [error for i, error in enumerate(errors) if clusters[i] == cluster_id]
            
            # Анализ характеристик кластера
            severity_counts = pd.Series([e.get('severity') for e in cluster_errors]).value_counts()
            common_components = pd.Series([e.get('affected_component') for e in cluster_errors]).value_counts()
            
            info = {
                'cluster_id': cluster_id,
                'size': len(cluster_errors),
                'main_severity': severity_counts.index[0] if not severity_counts.empty else 'unknown',
                'main_component': common_components.index[0] if not common_components.empty else 'unknown',
                'sample_errors': cluster_errors[:3]
            }
            cluster_info.append(info)
            
        return cluster_info

class TelegramNotifier:
    def __init__(self):
        self.bot_token = None
        self.chat_id = None
        self.bot = None
        self.enabled = False
        
    def initialize(self, bot_token, chat_id):
        try:
            self.bot_token = bot_token
            self.chat_id = chat_id
            self.bot = telegram.Bot(token=bot_token)
            self.enabled = True
            # Проверяем подключение, отправляя тестовое сообщение
            asyncio.get_event_loop().run_until_complete(
                self.send_message("INWise Error Tracking initialized successfully!")
            )
            return True
        except Exception as e:
            print(f"Failed to initialize Telegram bot: {str(e)}")
            self.enabled = False
            return False
            
    async def send_message(self, message):
        if not self.enabled:
            return
            
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Failed to send Telegram message: {str(e)}")
            
    def send_error(self, error_type, error_message, stack_trace=None):
        if not self.enabled:
            return
            
        message = f"❌ <b>Error in INWise</b>\n\n"
        message += f"<b>Type:</b> {error_type}\n"
        message += f"<b>Message:</b> {error_message}\n"
        
        if stack_trace:
            message += f"\n<b>Stack trace:</b>\n<pre>{stack_trace}</pre>"
            
        asyncio.get_event_loop().run_until_complete(self.send_message(message))

def handle_exceptions(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Получаем self из args (первый аргумент метода класса)
            if args and hasattr(args[0], 'telegram_notifier'):
                error_type = type(e).__name__
                error_message = str(e)
                stack_trace = traceback.format_exc()
                args[0].telegram_notifier.send_error(error_type, error_message, stack_trace)
            # Показываем сообщение об ошибке пользователю
            QMessageBox.critical(None, "Ошибка", f"Произошла ошибка: {str(e)}")
            raise
    return wrapper

class EditFileDialog(QDialog):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.setWindowTitle(f"Редактирование файла: {os.path.basename(file_path)}")
        self.setGeometry(100, 100, 800, 600)
        
        # Создаем layout
        layout = QVBoxLayout(self)
        
        # Создаем текстовый редактор
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Courier New", 10))
        layout.addWidget(self.editor)
        
        # Создаем кнопки
        button_layout = QHBoxLayout()
        
        save_button = QPushButton("Сохранить")
        save_button.clicked.connect(self.save_file)
        
        cancel_button = QPushButton("Отмена")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Загружаем содержимое файла
        self.load_file()
        
    def load_file(self):
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.editor.setPlainText(content)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть файл:\n{str(e)}")
            self.reject()
            
    def save_file(self):
        try:
            content = self.editor.toPlainText()
            with open(self.file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            QMessageBox.information(self, "Успех", "Файл успешно сохранен")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл:\n{str(e)}")

class HelpDialog(QDialog):
    def __init__(self, parent=None, error_analyzer=None):
        super().__init__(parent)
        self.error_analyzer = error_analyzer
        self.setWindowTitle("Анализ ошибок и рекомендации")
        self.setMinimumSize(800, 600)
        
        # Создаем основной layout
        layout = QVBoxLayout(self)
        
        # Создаем область прокрутки
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        # Создаем виджет для содержимого
        content = QWidget()
        content_layout = QVBoxLayout(content)
        
        # Добавляем заголовок
        title = QLabel("Анализ ошибок системы")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        content_layout.addWidget(title)
        
        # Добавляем таблицу для отображения анализа
        self.analysis_table = QTableWidget()
        self.analysis_table.setRowCount(0)
        self.analysis_table.setColumnCount(4)
        self.analysis_table.setHorizontalHeaderLabels(['Тип ошибки', 'Сообщение', 'Серьезность', 'Компонент'])
        content_layout.addWidget(self.analysis_table)
        
        # Добавляем кнопку обновления анализа
        update_button = QPushButton("Обновить анализ")
        update_button.clicked.connect(self.update_analysis)
        content_layout.addWidget(update_button)
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
        
        # Выполняем начальный анализ
        self.update_analysis()
        
    def update_analysis(self):
        try:
            # Загружаем текущие ошибки
            errors_file = os.path.join(os.path.dirname(__file__), 'errors.json')
            if os.path.exists(errors_file):
                with open(errors_file, 'r') as f:
                    errors = json.load(f)
            else:
                errors = []
            
            # Очищаем таблицу перед обновлением
            self.analysis_table.setRowCount(0)
            self.analysis_table.setColumnCount(4)
            self.analysis_table.setHorizontalHeaderLabels(['Тип ошибки', 'Сообщение', 'Серьезность', 'Компонент'])

            # Заполняем таблицу ошибками
            for error in errors:
                row_position = self.analysis_table.rowCount()
                self.analysis_table.insertRow(row_position)
                self.analysis_table.setItem(row_position, 0, QTableWidgetItem(error.get('error_type', '')))
                self.analysis_table.setItem(row_position, 1, QTableWidgetItem(error.get('message', '')[:100]))
                self.analysis_table.setItem(row_position, 2, QTableWidgetItem(error.get('severity', '')))
                self.analysis_table.setItem(row_position, 3, QTableWidgetItem(error.get('affected_component', '')))

            # Добавляем кнопку сохранения изменений
            save_button = QPushButton('Сохранить изменения')
            save_button.clicked.connect(lambda: self.save_changes(errors_file))
            self.layout().addWidget(save_button)

        except Exception as e:
            self.analysis_text.setText(f"Ошибка при анализе: {str(e)}")

    def save_changes(self, errors_file):
        errors = []
        for row in range(self.analysis_table.rowCount()):
            error = {
                'error_type': self.analysis_table.item(row, 0).text(),
                'message': self.analysis_table.item(row, 1).text(),
                'severity': self.analysis_table.item(row, 2).text(),
                'affected_component': self.analysis_table.item(row, 3).text()
            }
            errors.append(error)
        with open(errors_file, 'w') as f:
            json.dump(errors, f, indent=4)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("INWise")
        self.setGeometry(100, 100, 800, 600)
        self.setMinimumSize(400, 300)

        # Создаем центральный виджет
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Создаем основной layout для центрального виджета
        main_layout = QVBoxLayout(self.central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Создаем TabWidget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)

        # Создаем первую вкладку
        self.welcome_tab = QWidget()
        self.tab_widget.addTab(self.welcome_tab, "Welcome")
        self.setup_welcome_tab()

        # Создаем вторую вкладку
        self.feed_tab = QWidget()
        self.tab_widget.addTab(self.feed_tab, "Feed Manager")
        self.setup_feed_tab()

        # Создаем третью вкладку для ошибок
        self.errors_tab = QWidget()
        self.tab_widget.addTab(self.errors_tab, "Errors")
        self.setup_errors_tab()

        # Создаем четвертую вкладку для списка ошибок
        self.error_list_tab = QWidget()
        self.tab_widget.addTab(self.error_list_tab, "Исправленные ошибки")
        self.setup_error_list_tab()

        # Скрываем вкладки
        self.tab_widget.tabBar().hide()

        self.error_analyzer = ErrorAnalyzer()
        self.telegram_notifier = TelegramNotifier()

    def setup_welcome_tab(self):
        # Создаем layout для welcome tab
        welcome_layout = QVBoxLayout(self.welcome_tab)
        welcome_layout.setAlignment(Qt.AlignCenter)
        
        # Добавляем изображение
        image_label = QLabel()
        image_pixmap = QPixmap("C:/Users/Ta4anTu1/Downloads/11zon_cropped.png")
        if not image_pixmap.isNull():
            # Масштабируем изображение до размера 300x300 пикселей с сохранением пропорций
            scaled_pixmap = image_pixmap.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_label.setPixmap(scaled_pixmap)
            welcome_layout.addWidget(image_label, alignment=Qt.AlignCenter)
        
        # Добавляем приветственный текст
        welcome_text = QLabel("Добро пожаловать в INWise!")
        welcome_text.setStyleSheet("font-size: 24px; margin: 20px;")
        welcome_layout.addWidget(welcome_text, alignment=Qt.AlignCenter)
        
        # Добавляем описание
        description = QLabel("INWise поможет вам в работе с XML-фидами и анализе ошибок.")
        description.setStyleSheet("font-size: 16px; margin: 10px;")
        welcome_layout.addWidget(description, alignment=Qt.AlignCenter)
        
        # Создаем горизонтальный layout для кнопок
        buttons_layout = QHBoxLayout()
        
        # Добавляем кнопку "Начать работу"
        start_button = QPushButton("Начать работу")
        start_button.setFixedSize(180, 40)
        start_button.clicked.connect(self.on_next_clicked)
        
        # Добавляем кнопку "Исправленные ошибки"
        show_errors_button = QPushButton("Исправленные ошибки")
        show_errors_button.setFixedSize(180, 40)
        show_errors_button.clicked.connect(lambda: self.tab_widget.setCurrentIndex(3))

        # Добавляем кнопку для открытия сайта
        open_site_button = QPushButton("Открыть сайт")
        open_site_button.setFixedSize(180, 40)
        open_site_button.clicked.connect(self.open_website)
        
        # Добавляем кнопку настройки Telegram
        setup_telegram_button = QPushButton("Настроить Telegram")
        setup_telegram_button.setFixedSize(180, 40)
        setup_telegram_button.clicked.connect(self.setup_telegram)
        
        # Добавляем кнопки в горизонтальный layout
        buttons_layout.addStretch()
        buttons_layout.addWidget(start_button)
        buttons_layout.addWidget(show_errors_button)
        buttons_layout.addWidget(open_site_button)
        buttons_layout.addWidget(setup_telegram_button)
        buttons_layout.addStretch()
        
        welcome_layout.addLayout(buttons_layout)

    def setup_feed_tab(self):
        # Создаем layout для feed вкладки
        feed_layout = QVBoxLayout(self.feed_tab)
        feed_layout.setSpacing(20)
        feed_layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        title = QLabel("Управление фидами")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        feed_layout.addWidget(title)

        # Создаем поле для выбора файла
        file_layout = QHBoxLayout()
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Выберите файл...")
        self.file_input.textChanged.connect(self.toggle_input_fields)
        
        file_button = QPushButton("Обзор")
        file_button.clicked.connect(self.choose_file)
        
        edit_button = QPushButton("Редактировать")
        edit_button.clicked.connect(self.edit_file)
        edit_button.setEnabled(False)
        self.edit_button = edit_button  # Сохраняем ссылку на кнопку
        
        file_layout.addWidget(self.file_input)
        file_layout.addWidget(file_button)
        file_layout.addWidget(edit_button)
        feed_layout.addLayout(file_layout)

        # Создаем поле для ввода ссылки
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Введите ссылку на фид...")
        self.url_input.textChanged.connect(self.toggle_input_fields)
        url_layout.addWidget(self.url_input)
        feed_layout.addLayout(url_layout)

        # Добавляем растягивающийся элемент перед кнопками
        feed_layout.addStretch()

        # Создаем горизонтальный layout для кнопок
        buttons_layout = QHBoxLayout()
        
        # Кнопка "Назад"
        back_button = QPushButton("Назад")
        back_button.clicked.connect(lambda: self.tab_widget.setCurrentIndex(0))
        back_button.setFixedSize(120, 40)
        
        # Кнопка "Далее"
        next_button = QPushButton("Далее")
        next_button.clicked.connect(self.process_feed)
        next_button.setFixedSize(120, 40)
        
        # Добавляем кнопки в layout
        buttons_layout.addStretch()
        buttons_layout.addWidget(back_button)
        buttons_layout.addWidget(next_button)
        buttons_layout.addStretch()
        
        feed_layout.addLayout(buttons_layout)
        
        # Добавляем небольшой отступ после кнопок
        feed_layout.addSpacing(20)

    def toggle_input_fields(self):
        # Если в поле файла есть текст
        if self.file_input.text():
            self.url_input.setEnabled(False)
            self.url_input.setStyleSheet("background-color: #F0F0F0;")
            self.edit_button.setEnabled(True)  # Активируем кнопку редактирования
        # Если в поле ссылки есть текст
        elif self.url_input.text():
            self.file_input.setEnabled(False)
            self.file_input.setStyleSheet("background-color: #F0F0F0;")
            self.edit_button.setEnabled(False)  # Деактивируем кнопку редактирования
        # Если оба поля пустые
        else:
            self.file_input.setEnabled(True)
            self.url_input.setEnabled(True)
            self.file_input.setStyleSheet("")
            self.url_input.setStyleSheet("")
            self.edit_button.setEnabled(False)  # Деактивируем кнопку редактирования

    def edit_file(self):
        file_path = self.file_input.text()
        if file_path and os.path.exists(file_path):
            dialog = EditFileDialog(file_path, self)
            dialog.exec_()

    def setup_errors_tab(self):
        # Создаем layout для вкладки с ошибками
        errors_layout = QVBoxLayout(self.errors_tab)
        errors_layout.setSpacing(20)
        errors_layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        title = QLabel("Найденные ошибки")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        errors_layout.addWidget(title)

        # Создаем горизонтальный layout для кнопок вверху
        top_buttons_layout = QHBoxLayout()
        
        # Добавляем кнопку "Справка"
        help_button = QPushButton("Справка")
        help_button.setFixedSize(120, 40)
        help_button.clicked.connect(self.show_help)
        
        # Добавляем кнопку "Исправленные ошибки"
        show_errors_button = QPushButton("Исправленные ошибки")
        show_errors_button.setFixedSize(180, 40)
        show_errors_button.clicked.connect(lambda: self.tab_widget.setCurrentIndex(3))
        
        # Добавляем кнопки в верхний layout
        top_buttons_layout.addStretch()
        top_buttons_layout.addWidget(help_button)
        top_buttons_layout.addWidget(show_errors_button)
        
        errors_layout.addLayout(top_buttons_layout)

        # Добавляем растягивающийся элемент
        errors_layout.addStretch()

        # Создаем горизонтальный layout для кнопок навигации внизу
        buttons_layout = QHBoxLayout()
        
        # Кнопка "Назад"
        back_button = QPushButton("Назад")
        back_button.clicked.connect(lambda: self.tab_widget.setCurrentIndex(1))
        back_button.setFixedSize(120, 40)
        
        # Кнопка "Далее"
        next_button = QPushButton("Далее")
        next_button.clicked.connect(self.process_errors)
        next_button.setFixedSize(120, 40)
        
        # Добавляем кнопки в layout
        buttons_layout.addStretch()
        buttons_layout.addWidget(back_button)
        buttons_layout.addWidget(next_button)
        buttons_layout.addStretch()
        
        errors_layout.addLayout(buttons_layout)
        
        # Добавляем небольшой отступ после кнопок
        errors_layout.addSpacing(20)

    def setup_error_list_tab(self):
        # Создаем layout для вкладки со списком ошибок
        error_list_layout = QVBoxLayout(self.error_list_tab)
        error_list_layout.setSpacing(20)
        error_list_layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        title = QLabel("Исправленные ошибки")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        error_list_layout.addWidget(title)

        # Создаем область прокрутки
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        # Создаем виджет для содержимого
        content = QWidget()
        content_layout = QVBoxLayout(content)
        
        # Примеры ошибок
        example_errors = [
            {
                "title": "Ошибка в цене",
                "product": "Смартфон X1",
                "description": "Цена ниже себестоимости"
            },
            {
                "title": "Ошибка в скидке",
                "product": "Ноутбук Y2",
                "description": "Скидка превышает 100%"
            },
            {
                "title": "Ошибка в описании",
                "product": "Планшет Z3",
                "description": "Описание слишком короткое"
            },
            {
                "title": "Ошибка в названии",
                "product": "123_ABC",
                "description": "Название не информативное"
            }
        ]
        
        for error in example_errors:
            # Создаем виджет для каждой ошибки
            error_widget = QWidget()
            error_widget.setStyleSheet("""
                QWidget {
                    background-color: #FFE6E6;
                    border: 1px solid #FFCCCC;
                    border-radius: 5px;
                    padding: 15px;
                    margin: 5px;
                }
            """)
            
            # Создаем layout для ошибки
            error_layout = QVBoxLayout(error_widget)
            
            error_title = QLabel(f"{error['title']}")
            error_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #FF4444;")
            error_layout.addWidget(error_title)
            
            product_name = QLabel(f"Товар: {error['product']}")
            product_name.setStyleSheet("font-size: 14px;")
            error_layout.addWidget(product_name)
            
            error_desc = QLabel(f"Проблема: {error['description']}")
            error_desc.setStyleSheet("font-size: 14px;")
            error_desc.setWordWrap(True)
            error_layout.addWidget(error_desc)
            
            content_layout.addWidget(error_widget)
            content_layout.addSpacing(10)
        
        # Добавляем растягивающийся элемент в конец
        content_layout.addStretch()
        
        # Добавляем виджет с содержимым в область прокрутки
        scroll.setWidget(content)
        error_list_layout.addWidget(scroll)

        # Создаем горизонтальный layout для кнопок
        buttons_layout = QHBoxLayout()
        
        # Кнопка "Назад"
        back_button = QPushButton("Назад")
        back_button.clicked.connect(lambda: self.tab_widget.setCurrentIndex(2))
        back_button.setFixedSize(120, 40)
        
        # Добавляем кнопки в layout
        buttons_layout.addStretch()
        buttons_layout.addWidget(back_button)
        buttons_layout.addStretch()
        
        error_list_layout.addLayout(buttons_layout)
        
        # Добавляем небольшой отступ после кнопок
        error_list_layout.addSpacing(20)

    async def analyze_with_aiplayground_async(self, text, session):
        # Обновляем URL для API-запросов
        # url = "https://aimlapi.com/app/sign-in"
        url = ""  # URL удален
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "text": text
        }
        async with session.post(url, headers=headers, json=data) as response:
            if response.status == 200:
                result = await response.json()
                return result.get("result", "")
            else:
                return f"Error: {response.status}"

    async def process_feed_async(self):
        print(f"Attempting to parse file: {self.file_input.text()}")
        try:
            # Парсим XML файл
            tree = ET.parse(self.file_input.text())
            root = tree.getroot()
            print("XML parsing successful.")
        except ET.ParseError as e:
            print(f"XML parsing error: {str(e)}")
            QMessageBox.critical(self, "Ошибка", f"Ошибка при разборе XML: {str(e)}")
            return
        except Exception as e:
            print(f"Unexpected error during XML parsing: {str(e)}")
            QMessageBox.critical(self, "Ошибка", f"Неожиданная ошибка: {str(e)}")
            return

        try:
            # Словарь для хранения найденных ошибок
            errors = []

            # Проверяем каждый товар в фиде
            items = root.findall('.//offer')  # Изменено с item на offer
            if not items:
                items = root.findall('.//item')  # Пробуем искать теги item если offer не найдены
            print(f"Found {len(items)} items in the XML.")

            async with aiohttp.ClientSession() as session:
                tasks = []
                for item in items:
                    try:
                        # Получаем ID товара
                        item_id = item.get('id', 'Неизвестный ID')
                        print(f"Processing item ID: {item_id}")

                        # Получаем основные элементы товара
                        title = item.find('name')  # Сначала ищем тег name
                        if title is None:
                            title = item.find('title')  # Если name не найден, ищем title
                        title_text = title.text if title is not None else 'Без названия'
                        print(f"Title: {title_text}")

                        description = item.find('description')
                        description_text = description.text if description is not None else ''
                        print(f"Description: {description_text}")

                        price = item.find('price')
                        price_text = price.text if price is not None else '0'
                        print(f"Price: {price_text}")

                        # Добавляем задачу для асинхронного анализа
                        tasks.append(self.analyze_with_aiplayground_async(description_text, session))

                    except Exception as item_error:
                        print(f"Error processing item ID {item_id}: {str(item_error)}")
                        errors.append({
                            'type': 'Ошибка обработки товара',
                            'product': title_text,
                            'id': item_id,
                            'description': str(item_error)
                        })

                # Выполняем все задачи асинхронно
                analysis_results = await asyncio.gather(*tasks, return_exceptions=True)

                for item, analysis_result in zip(items, analysis_results):
                    # Проверяем название
                    if title_text and len(title_text) < 10:
                        errors.append({
                            'type': 'Непривлекательное название товара',
                            'product': title_text,
                            'id': item_id,
                            'description': 'Название слишком короткое'
                        })

                    # Проверяем описание
                    if description_text and len(description_text) < 50:
                        errors.append({
                            'type': 'Ошибка в описании товара',
                            'product': title_text,
                            'id': item_id,
                            'description': 'Описание слишком короткое'
                        })

                    # Проверяем цену
                    try:
                        price_value = float(price_text.replace(',', '.').replace(' ', ''))
                        if price_value <= 0:
                            errors.append({
                                'type': 'Некорректная цена товара',
                                'product': title_text,
                                'id': item_id,
                                'description': 'Цена должна быть больше нуля'
                            })
                    except ValueError:
                        errors.append({
                            'type': 'Некорректная цена товара',
                            'product': title_text,
                            'id': item_id,
                            'description': 'Неверный формат цены'
                        })

                    # Проверяем скидку
                    try:
                        discount_value = float(price_text.replace(',', '.').replace(' ', ''))
                        if discount_value < 0 or discount_value > 100:
                            errors.append({
                                'type': 'Ошибка в скидке',
                                'product': title_text,
                                'id': item_id,
                                'description': 'Скидка должна быть от 0 до 100%'
                            })
                    except ValueError:
                        if price_text != '0':
                            errors.append({
                                'type': 'Ошибка в скидке',
                                'product': title_text,
                                'id': item_id,
                                'description': 'Неверный формат скидки'
                            })

            # Проверяем, есть ли ошибки
            if errors:
                for error in errors:
                    print(f"Error: {error['type']} - {error['description']} (Product: {error['product']}, ID: {error['id']})")
            else:
                print("No errors found in the file.")

        except Exception as e:
            print(f"Unexpected error during file processing: {str(e)}")
            # Remove the blocking error message to allow the program to continue
            # QMessageBox.critical(self, "Ошибка", f"Ошибка при обработке файла: {str(e)}")
            return

    async def start_processing(self):
        await self.process_feed_async()

    def process_feed(self):
        asyncio.run(self.start_processing())

    def update_errors_tab(self, errors):
        # Очищаем текущее содержимое вкладки с ошибками
        for i in reversed(range(self.errors_tab.layout().count())):
            widget = self.errors_tab.layout().itemAt(i).widget()
            if widget is not None:
                widget.deleteLater()
        
        # Пересоздаем layout для вкладки с ошибками
        errors_layout = QVBoxLayout(self.errors_tab)
        errors_layout.setSpacing(20)
        errors_layout.setContentsMargins(20, 20, 20, 20)

        # Заголовок
        title = QLabel("Найденные ошибки")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        errors_layout.addWidget(title)

        # Создаем область прокрутки
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        # Создаем виджет для содержимого
        content = QWidget()
        content_layout = QVBoxLayout(content)
        
        if not errors:
            # Если ошибок нет
            no_errors_label = QLabel("Ошибок не найдено")
            no_errors_label.setStyleSheet("font-size: 16px; color: green;")
            no_errors_label.setAlignment(Qt.AlignCenter)
            content_layout.addWidget(no_errors_label)
        else:
            # Добавляем найденные ошибки
            for error in errors:
                error_widget = QWidget()
                error_widget.setStyleSheet("""
                    QWidget {
                        background-color: #FFE6E6;
                        border: 1px solid #FFCCCC;
                        border-radius: 5px;
                        padding: 15px;
                        margin: 5px;
                    }
                """)
                
                error_layout = QVBoxLayout(error_widget)
                
                error_title = QLabel(error['type'])
                error_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #FF4444;")
                error_layout.addWidget(error_title)
                
                product_name = QLabel(f"Товар: {error['product']}")
                product_name.setStyleSheet("font-size: 14px;")
                error_layout.addWidget(product_name)
                
                error_desc = QLabel(f"Проблема: {error['description']}")
                error_desc.setStyleSheet("font-size: 14px;")
                error_desc.setWordWrap(True)
                error_layout.addWidget(error_desc)
                
                content_layout.addWidget(error_widget)
                content_layout.addSpacing(10)

        # Добавляем растягивающийся элемент
        content_layout.addStretch()
        
        # Добавляем виджет с содержимым в область прокрутки
        scroll.setWidget(content)
        errors_layout.addWidget(scroll)

        # Создаем горизонтальный layout для кнопок
        buttons_layout = QHBoxLayout()
        
        # Кнопка "Назад"
        back_button = QPushButton("Назад")
        back_button.clicked.connect(lambda: self.tab_widget.setCurrentIndex(1))
        back_button.setFixedSize(120, 40)
        
        # Кнопка "Далее"
        next_button = QPushButton("Далее")
        next_button.clicked.connect(self.process_errors)
        next_button.setFixedSize(120, 40)
        
        # Добавляем кнопки в layout
        buttons_layout.addStretch()
        buttons_layout.addWidget(back_button)
        buttons_layout.addWidget(next_button)
        buttons_layout.addStretch()
        
        errors_layout.addLayout(buttons_layout)
        
        # Добавляем небольшой отступ после кнопок
        errors_layout.addSpacing(20)

    def process_errors(self):
        # Здесь будет логика обработки ошибок
        pass

    def resizeEvent(self, event):
        if hasattr(self, 'image_label') and hasattr(self, 'original_pixmap'):
            # Получаем размеры доступного пространства
            available_width = self.welcome_tab.width() - 40
            available_height = self.welcome_tab.height() - 150

            # Масштабируем изображение
            scaled_pixmap = self.original_pixmap.scaled(
                available_width,
                available_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled_pixmap)

            # Масштабируем шрифты
            scale_factor = min(self.width() / 800, self.height() / 600)
            title_font_size = max(16, int(24 * scale_factor))
            button_font_size = max(10, int(12 * scale_factor))
            
            self.title_label.setStyleSheet(f"font-size: {title_font_size}px; font-weight: bold;")
            self.next_button.setStyleSheet(f"font-size: {button_font_size}px;")
            self.next_button.setFixedSize(
                int(120 * scale_factor),
                int(40 * scale_factor)
            )

    def choose_file(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Выберите файл", "", "XML Files (*.xml);;All Files (*)")
        if file_name:
            self.file_input.setText(file_name)

    def on_next_clicked(self):
        # Start processing the feed
        asyncio.run(self.start_processing())

        # Переключаемся на вкладку с фидами
        self.tab_widget.setCurrentIndex(1)

    def show_help(self):
        """Показывает окно справки с анализом ошибок"""
        dialog = HelpDialog(self, self.error_analyzer)
        dialog.exec_()

    def open_website(self):
        try:
            webbrowser.open('http://localhost:5000')
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть сайт: {str(e)}")

    def setup_telegram(self):
        # Запрашиваем токен бота
        bot_token, ok = QInputDialog.getText(
            self, 
            'Настройка Telegram', 
            'Введите токен бота:\n(Получите его у @BotFather в Telegram)',
            QLineEdit.Normal
        )
        if not ok or not bot_token:
            return
            
        # Запрашиваем Chat ID
        chat_id, ok = QInputDialog.getText(
            self, 
            'Настройка Telegram', 
            'Введите Chat ID:\n(Получите его у @userinfobot)',
            QLineEdit.Normal
        )
        if not ok or not chat_id:
            return
            
        # Инициализируем бота
        if self.telegram_notifier.initialize(bot_token, chat_id):
            QMessageBox.information(
                self,
                "Успех",
                "Telegram бот успешно настроен!\nТестовое сообщение отправлено."
            )
        else:
            QMessageBox.critical(
                self,
                "Ошибка",
                "Не удалось настроить Telegram бота.\nПроверьте токен и Chat ID."
            )

def main():
    app = QApplication(sys.argv)
    
    # Обработка аргументов командной строки
    import argparse
    parser = argparse.ArgumentParser(description='INWise Error Management System')
    parser.add_argument('--import', dest='import_file', help='Import errors from JSON file')
    args = parser.parse_args()
    
    # Если указан файл для импорта, обрабатываем его
    if hasattr(args, 'import_file') and args.import_file:
        try:
            with open(args.import_file, 'r') as f:
                import_data = json.load(f)
                
            # Обработка импортированных данных
            output_data = []
            for error in import_data:
                # Генерируем INWise ID для ошибки
                inwise_id = f"INW-{len(output_data) + 1:03d}"
                
                # Добавляем дополнительные поля INWise
                error['inwise_id'] = inwise_id
                error['analysis_status'] = 'pending'
                error['priority'] = calculate_priority(error.get('severity', 'medium'),
                                                    error.get('impact', ''))
                output_data.append(error)
            
            # Сохраняем обработанные данные
            output_file = os.path.join(os.path.dirname(__file__), 'errors.json')
            with open(output_file, 'w') as f:
                json.dump(output_data, f, indent=2)
                
            sys.exit(0)  # Завершаем работу после обработки импорта
            
        except Exception as e:
            print(f"Error processing import file: {str(e)}", file=sys.stderr)
            sys.exit(1)
    
    # Запускаем GUI если нет флага импорта
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
