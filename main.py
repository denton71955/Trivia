import sys
import json
import socket
import threading
import csv
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QMessageBox, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer


# ───────────────────────────────────────────────
# LOGIN WINDOW
# ───────────────────────────────────────────────
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trivia Login")
        self.setFixedSize(300, 200)

        self.client_socket = None

        self.label_username = QLabel("Username:")
        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("Enter your username")

        self.host_button = QPushButton("☐ Host Game")
        self.host_button.setCheckable(True)
        self.host_button.clicked.connect(self.toggle_host_button)

        self.button_login = QPushButton("Login")
        self.button_login.clicked.connect(self.handle_login)

        layout = QVBoxLayout()
        layout.addWidget(self.label_username)
        layout.addWidget(self.input_username)
        layout.addWidget(self.host_button)
        layout.addWidget(self.button_login)
        self.setLayout(layout)

    def keyPressEvent(self, event):
        # ← NEW: Press Enter = login
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.handle_login()
            
    def toggle_host_button(self):
        self.host_button.setText("☑ Host Game" if self.host_button.isChecked() else "☐ Host Game")

    def handle_login(self):
        username = self.input_username.text().strip()
        if not username:
            QMessageBox.warning(self, "Missing Info", "Please enter a username.")
            return
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(("127.0.0.1", 65432))
            msg = {"action": "login", "username": username}
            sock.sendall(json.dumps(msg).encode("utf-8"))
            data = sock.recv(4096).decode("utf-8")
            res = json.loads(data)
            if res.get("status") == "success":
                is_host = self.host_button.isChecked()
                self.hide()
                self.chat_window = ChatWindow(sock, username, is_host)
                self.chat_window.show()
            else:
                QMessageBox.critical(self, "Login Failed", "Unable to connect.")
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))


# ───────────────────────────────────────────────
# CHAT + GAME WINDOW
# ───────────────────────────────────────────────
class ChatWindow(QWidget):
    def __init__(self, conn, username, is_host=False):
        super().__init__()
        self.setWindowTitle("Trivia Game")
        self.setFixedSize(750, 500)

        self.conn = conn
        self.username = username
        self.is_host = is_host
        self.has_answered = False

        # Layout
        layout = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()

        # Chat area
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_input = QLineEdit()
        self.chat_input.returnPressed.connect(self.send_chat)
        left.addWidget(QLabel(f"Logged in as: {username}"))
        left.addWidget(self.chat_display)
        left.addWidget(self.chat_input)

        # Player list
        self.player_list = QListWidget()
        right.addWidget(QLabel("Scores:"))
        right.addWidget(self.player_list)

        # Host controls
        if self.is_host:
            self.upload_btn = QPushButton("Upload Questions (CSV)")
            self.create_btn = QPushButton("Create Game")
            self.start_btn = QPushButton("Start Game")
            self.upload_btn.clicked.connect(self.upload_questions)
            self.create_btn.clicked.connect(self.create_game)
            self.start_btn.clicked.connect(self.start_game)
            right.addWidget(self.upload_btn)
            right.addWidget(self.create_btn)
            right.addWidget(self.start_btn)
        else:
            self.join_label = QLabel("Enter Game Code:")
            self.join_input = QLineEdit()
            self.join_btn = QPushButton("Join Game")
            self.join_btn.clicked.connect(self.join_game)
            right.addWidget(self.join_label)
            right.addWidget(self.join_input)
            right.addWidget(self.join_btn)

        # Answer buttons
        self.answer_buttons = []
        ans_layout = QHBoxLayout()
        for opt in ["A", "B", "C", "D"]:
            btn = QPushButton(opt)
            btn.setFixedWidth(60)
            btn.clicked.connect(self.handle_answer)
            self.answer_buttons.append(btn)
            ans_layout.addWidget(btn)
        left.addLayout(ans_layout)

        for b in self.answer_buttons:
            b.setEnabled(False)

        layout.addLayout(left, 3)
        layout.addLayout(right, 1)
        self.setLayout(layout)

        # Listener
        self.listener = ListenerThread(self.conn, self)
        self.listener.start()

        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)
        self.time_left = 0

    # ───────────────────────────────────────────────
    # NETWORK ACTIONS
    # ───────────────────────────────────────────────
    def send_chat(self):
        msg = self.chat_input.text().strip()
        if not msg:
            return
        payload = {"action": "chat", "message": msg}
        self.conn.sendall(json.dumps(payload).encode("utf-8"))
        self.chat_input.clear()

    def upload_questions(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select CSV File", "", "CSV Files (*.csv)"
        )
        if not file_path:
            return
        questions = []
        try:
            with open(file_path, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    if len(row) >= 6:
                        q = {"question": row[0], "choices": row[1:5], "answer": row[5]}
                        questions.append(q)
            msg = {"action": "upload_questions", "questions": questions}
            self.conn.sendall(json.dumps(msg).encode("utf-8"))
            QMessageBox.information(self, "Upload Complete", f"Uploaded {len(questions)} questions.")
        except Exception as e:
            QMessageBox.critical(self, "Upload Error", str(e))

    def create_game(self):
        msg = {"action": "create_game"}
        self.conn.sendall(json.dumps(msg).encode("utf-8"))

    def join_game(self):
        code = self.join_input.text().strip()
        if not code:
            QMessageBox.warning(self, "Missing Code", "Please enter a game code.")
            return
        msg = {"action": "join_game", "game_code": code}
        self.conn.sendall(json.dumps(msg).encode("utf-8"))

    def start_game(self):
        msg = {"action": "start_game"}
        self.conn.sendall(json.dumps(msg).encode("utf-8"))

    def handle_answer(self):
        if self.has_answered:
            return
        sender = self.sender()
        choice = sender.text()
        msg = {"action": "answer", "choice": choice}
        self.conn.sendall(json.dumps(msg).encode("utf-8"))
        self.has_answered = True
        for b in self.answer_buttons:
            b.setEnabled(False)

    # ───────────────────────────────────────────────
    # TIMER + DISPLAY
    # ───────────────────────────────────────────────
    def update_timer(self):
        if self.time_left > 0:
            self.time_left -= 1
            self.chat_display.append(f"[Timer] {self.time_left}s left...")
        else:
            self.timer.stop()
            self.chat_display.append("[Timer] Time’s up!")

    def start_timer(self, seconds):
        self.time_left = seconds
        self.timer.start(1000)

    # ───────────────────────────────────────────────
    # SCOREBOARD
    # ───────────────────────────────────────────────
    def update_scores(self, players):
        self.player_list.clear()
        for p in players:
            self.player_list.addItem(f"{p['username']}: {p['score']}")

    # ───────────────────────────────────────────────
    # QUESTION DISPLAY
    # ───────────────────────────────────────────────
    def display_question(self, question, choices):
        self.chat_display.append(f"\n[QUESTION] {question}")
        for i, c in enumerate(choices):
            self.chat_display.append(f"{chr(65+i)}. {c}")
        for b in self.answer_buttons:
            b.setEnabled(True)
        self.has_answered = False
        self.start_timer(15)


# ───────────────────────────────────────────────
# LISTENER THREAD
# ───────────────────────────────────────────────
class ListenerThread(threading.Thread):
    def __init__(self, conn, window):
        super().__init__(daemon=True)
        self.conn = conn
        self.window = window

    def run(self):
        while True:
            try:
                data = self.conn.recv(4096)
                if not data:
                    break
                msg = json.loads(data.decode("utf-8"))
                self.handle_message(msg)
            except Exception as e:
                print(f"[LISTENER ERROR] {e}")
                break

    def handle_message(self, msg):
        t = msg.get("type")

        if t == "system":
            self.window.chat_display.append(f"[System] {msg.get('message', '')}")

        elif t == "chat":
            self.window.chat_display.append(f"{msg.get('username')}: {msg.get('message')}")

        elif t == "question":
            q = msg.get("question")
            c = msg.get("choices", [])
            self.window.display_question(q, c)

        elif t == "timer":
            remaining = msg.get("remaining")
            self.window.chat_display.append(f"[Timer] {remaining}s left...")

        elif t == "round_end":
            correct = msg.get("correct", "")
            players = msg.get("players", [])
            self.window.chat_display.append(f"\n✅ Correct answer: {correct}\n")
            self.window.update_scores(players)
            for b in self.window.answer_buttons:
                b.setEnabled(False)

        elif t == "player_list":
            self.window.update_scores(msg.get("players", []))


# ───────────────────────────────────────────────
# MAIN APP
# ───────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginWindow()
    login.show()
    sys.exit(app.exec())
