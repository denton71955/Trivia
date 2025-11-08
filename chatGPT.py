import sys
import json
import socket
import threading
import csv
import pandas as pd
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer

# ---------------- LOGIN WINDOW ----------------
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trivia Login")
        self.setFixedSize(300, 200)

        self.client_socket = None

        self.label_username = QLabel("Username:")
        self.input_username = QLineEdit()
        self.label_password = QLabel("Password:")
        self.input_password = QLineEdit()
        self.input_password.setEchoMode(QLineEdit.EchoMode.Password)

        self.host_button = QPushButton("☐ Host Game")
        self.host_button.setCheckable(True)
        self.host_button.setStyleSheet(
            "QPushButton { font-weight: bold; }"
            "QPushButton:checked { background-color: #0078D7; color: white; }"
        )
        self.host_button.clicked.connect(self.toggle_host_button)

        self.button_login = QPushButton("Login")
        self.button_login.clicked.connect(self.handle_login)

        layout = QVBoxLayout()
        layout.addWidget(self.label_username)
        layout.addWidget(self.input_username)
        layout.addWidget(self.label_password)
        layout.addWidget(self.input_password)
        layout.addWidget(self.host_button)
        layout.addWidget(self.button_login)
        self.setLayout(layout)

    def toggle_host_button(self):
        self.host_button.setText("☑ Host Game" if self.host_button.isChecked() else "☐ Host Game")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.handle_login()

    def handle_login(self):
        username = self.input_username.text().strip()
        password = self.input_password.text().strip()
        host_request = self.host_button.isChecked()

        if not username or not password:
            QMessageBox.warning(self, "Missing Info", "Please enter username and password.")
            return

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("127.0.0.1", 65432))
            msg = {"action": "login", "username": username, "password": password, "host_request": host_request}
            sock.sendall(json.dumps(msg).encode("utf-8"))

            data = sock.recv(4096).decode("utf-8")
            response = json.loads(data)

            if response.get("status") == "success":
                self.hide()
                self.chat_window = ChatWindow(sock, username, is_host=host_request)
                self.chat_window.show()
            else:
                QMessageBox.critical(self, "Login Failed", response.get("message", "Unknown error"))
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))


# ---------------- CHAT WINDOW ----------------
class ChatWindow(QWidget):
    def __init__(self, connection, username, is_host=False):
        super().__init__()
        self.setWindowTitle("Trivia Game")
        self.setFixedSize(750, 520)
        self.connection = connection
        self.username = username
        self.is_host = is_host

        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_input = QLineEdit()
        self.chat_input.returnPressed.connect(self.send_message)

        left_layout.addWidget(QLabel(f"Logged in as: {username}"))
        left_layout.addWidget(self.chat_display)
        left_layout.addWidget(self.chat_input)

        self.player_list_label = QLabel("Players:")
        self.player_list = QListWidget()
        right_layout.addWidget(self.player_list_label)
        right_layout.addWidget(self.player_list)

        # -------- Join Game for non-hosts --------
        if not self.is_host:
            self.join_label = QLabel("Enter Game Code:")
            self.join_input = QLineEdit()
            self.join_button = QPushButton("Join Game")
            self.join_button.clicked.connect(self.join_game)
            right_layout.addWidget(self.join_label)
            right_layout.addWidget(self.join_input)
            right_layout.addWidget(self.join_button)

        # -------- Host controls --------
        self.upload_btn = QPushButton("Upload Questions")
        self.start_btn = QPushButton("Start Game")
        self.next_btn = QPushButton("Next Question")
        self.end_btn = QPushButton("End Game")
        for btn in [self.upload_btn, self.start_btn, self.next_btn, self.end_btn]:
            btn.setVisible(self.is_host)

        self.upload_btn.clicked.connect(self.upload_questions)
        self.start_btn.clicked.connect(self.start_game)
        self.next_btn.clicked.connect(self.next_question)
        self.end_btn.clicked.connect(self.end_game)

        right_layout.addWidget(self.upload_btn)
        right_layout.addWidget(self.start_btn)
        right_layout.addWidget(self.next_btn)
        right_layout.addWidget(self.end_btn)

        main_layout.addLayout(left_layout, 3)
        main_layout.addLayout(right_layout, 1)
        self.setLayout(main_layout)

        self.listener = ClientListener(self.connection, self)
        self.listener.start()

        if self.is_host:
            self.create_game()

    # -------- Networking --------
    def create_game(self):
        self.connection.sendall(json.dumps({"action": "host_game"}).encode("utf-8"))

    def join_game(self):
        code = self.join_input.text().strip().upper()
        if not code:
            QMessageBox.warning(self, "Missing Code", "Please enter a valid game code.")
            return
        self.connection.sendall(json.dumps({"action": "join_game", "game_code": code}).encode("utf-8"))

    def send_message(self):
        text = self.chat_input.text().strip()
        if not text:
            return
        self.connection.sendall(json.dumps({"action": "chat", "message": text}).encode("utf-8"))
        self.chat_input.clear()

    # -------- Upload Questions (CSV + XLSX) --------
    def upload_questions(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Questions File", "", "CSV or Excel Files (*.csv *.xlsx)")
        if not file_path:
            return
        try:
            questions = []
            if file_path.lower().endswith(".csv"):
                with open(file_path, newline="", encoding="utf-8") as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        q = row.get("question", "").strip()
                        choices = [row.get(f"choice{i}", "").strip() for i in range(1, 5)]
                        answer = row.get("answer", "").strip()
                        if q and all(choices) and answer:
                            questions.append({"question": q, "choices": choices, "answer": answer})
            else:
                df = pd.read_excel(file_path, header=None)
                for _, row in df.iterrows():
                    q = str(row.iloc[0]).strip() if not pd.isna(row.iloc[0]) else ""
                    choices = [str(row.iloc[i]).strip() for i in range(1, 5) if not pd.isna(row.iloc[i])]
                    answer = str(row.iloc[5]).strip() if len(row) > 5 and not pd.isna(row.iloc[5]) else ""
                    if q and len(choices) == 4 and answer:
                        questions.append({"question": q, "choices": choices, "answer": answer})

            if not questions:
                QMessageBox.warning(self, "No Data", "No valid questions found.")
                return

            self.connection.sendall(json.dumps({"action": "upload_questions", "questions": questions}).encode("utf-8"))
            QMessageBox.information(self, "Upload Complete", f"Uploaded {len(questions)} questions successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Upload Error", str(e))

    def start_game(self):
        self.connection.sendall(json.dumps({"action": "start_game"}).encode("utf-8"))

    def next_question(self):
        self.connection.sendall(json.dumps({"action": "next_question"}).encode("utf-8"))

    def end_game(self):
        self.connection.sendall(json.dumps({"action": "end_game"}).encode("utf-8"))

    # -------- Timer / Scoreboard --------
    def start_timer(self, seconds):
        self.time_remaining = seconds
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)
        self.timer.start(1000)

    def update_timer(self):
        if self.time_remaining > 0:
            self.time_remaining -= 1
            self.chat_display.append(f"[Timer] {self.time_remaining}s left...")
        else:
            self.timer.stop()
            self.chat_display.append("[Timer] Time’s up!")

    def update_scoreboard(self, players):
        self.player_list.clear()
        for p in players:
            label = f"{p['username']}: {p['score']}"
            if p.get("is_host"):
                label += " (HOST)"
            self.player_list.addItem(label)


# ---------------- CLIENT LISTENER ----------------
class ClientListener(threading.Thread):
    def __init__(self, connection, chat_window):
        super().__init__(daemon=True)
        self.connection = connection
        self.chat_window = chat_window

    def run(self):
        while True:
            try:
                data = self.connection.recv(4096)
                if not data:
                    break
                self.handle_message(json.loads(data.decode("utf-8")))
            except Exception as e:
                print(f"[LISTENER ERROR] {e}")
                break

    def handle_message(self, message):
        t = message.get("type")
        if t == "system":
            msg = message.get("message", "")
            self.chat_window.chat_display.append(f"[System] {msg}")
        elif t == "chat":
            self.chat_window.chat_display.append(f"{message.get('username')}: {message.get('message')}")
        elif t == "player_list":
            self.chat_window.update_scoreboard(message.get("players", []))
        elif t in ("question_start", "question"):
            q, c = message.get("question", ""), message.get("choices", [])
            timer = message.get("timer", 15)
            self.chat_window.chat_display.append(f"\n[QUESTION] {q}")
            for i, choice in enumerate(c, 1):
                self.chat_window.chat_display.append(f"{i}. {choice}")
            self.chat_window.chat_display.append(f"\n⏱️ You have {timer} seconds to answer!")
            self.chat_window.start_timer(timer)
        elif t == "round_end":
            correct = message.get("correct", "")
            self.chat_window.chat_display.append(f"\n✅ Round ended! Correct answer: {correct}\n")
            self.chat_window.update_scoreboard(message.get("players", []))


# ---------------- MAIN APP ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = LoginWindow()
    win.show()
    sys.exit(app.exec())
