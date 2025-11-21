import sys
import json
import socket
import threading
import csv
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QMessageBox, QFileDialog, QFrame
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
        # Press Enter = login
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
        self.setLayout(layout)

        # ───────────────────────────────────────────
        # CHAT AREA
        # ───────────────────────────────────────────
        left.addWidget(QLabel(f"Logged in as: {username}"))

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        left.addWidget(self.chat_display)

        self.chat_input = QLineEdit()
        self.chat_input.returnPressed.connect(self.send_chat)
        left.addWidget(self.chat_input)

        # ───────────────────────────────────────────
        # GAME UI (hidden by default)
        # ───────────────────────────────────────────
        self.game_frame = QFrame()
        game_layout = QVBoxLayout()
        self.game_frame.setLayout(game_layout)
        self.game_frame.hide()  # start hidden

        # Question label
        self.question_label = QLabel("QUESTION TEXT")
        self.question_label.setWordWrap(True)
        self.question_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.question_label.setStyleSheet("font-size: 20px; font-weight: bold; margin: 10px;")
        game_layout.addWidget(self.question_label)

        # Full-width bubble answer buttons
        self.answer_buttons = []
        for i in range(4):
            btn = QPushButton(f"Choice {i+1}")
            btn.setFixedHeight(45)
            btn.clicked.connect(self.handle_answer)

            # store letter mapping A/B/C/D while showing full text
            btn.choice_letter = chr(65 + i)  # 'A', 'B', 'C', 'D'

            btn.setStyleSheet("""
                QPushButton {
                    border: 2px solid #666;
                    border-radius: 20px;
                    padding: 10px;
                    font-size: 16px;
                    background-color: #f2f2f2;
                    text-align: left;
                }
                QPushButton:hover {
                    background-color: #e6e6e6;
                }
                QPushButton:pressed {
                    background-color: #cccccc;
                }
            """)

            btn.setEnabled(False)
            game_layout.addWidget(btn)
            self.answer_buttons.append(btn)

        left.addWidget(self.game_frame)

        # ───────────────────────────────────────────
        # PLAYER LIST + HOST / JOIN CONTROLS
        # ───────────────────────────────────────────
        self.player_list = QListWidget()
        right.addWidget(QLabel("Scores:"))
        right.addWidget(self.player_list)

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

        layout.addLayout(left, 3)
        layout.addLayout(right, 1)

        # Listener
        self.listener = ListenerThread(self.conn, self)
        self.listener.start()

        # Timer (currently unused but kept to avoid breaking anything)
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

    # ───────────────────────────────────────────────
    # ANSWER HANDLING (BUBBLE BUTTONS)
    # ───────────────────────────────────────────────
    def handle_answer(self):
        if self.has_answered:
            return

        sender = self.sender()
        # We send the LETTER (A/B/C/D) so server scoring logic remains unchanged.
        choice_letter = getattr(sender, "choice_letter", sender.text())

        msg = {"action": "answer", "choice": choice_letter}
        self.conn.sendall(json.dumps(msg).encode("utf-8"))

        self.has_answered = True
        for b in self.answer_buttons:
            b.setEnabled(False)

    # ───────────────────────────────────────────────
    # TIMER + DISPLAY (server still sends timer messages)
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
    # NEW: QUESTION DISPLAY (BUBBLE UI)
    # ───────────────────────────────────────────────
    def show_question(self, question, choices):
        """
        Show the question + 4 answer bubbles and hide the chat UI.
        choices: list of 4 answer strings.
        """
        self.has_answered = False

        # hide chat widgets
        self.chat_display.hide()
        self.chat_input.hide()

        # update question and buttons
        self.question_label.setText(question)

        for i in range(4):
            text = choices[i] if i < len(choices) else ""
            self.answer_buttons[i].setText(text)
            self.answer_buttons[i].setEnabled(bool(text))

        self.game_frame.show()

    def hide_question(self):
        """
        Hide the game UI and bring chat back (used when 'end_question' arrives).
        """
        self.game_frame.hide()
        self.chat_display.show()
        self.chat_input.show()

        # just in case, disable buttons until the next question
        for b in self.answer_buttons:
            b.setEnabled(False)

    # ───────────────────────────────────────────────
    # LEGACY: TEXT QUESTION (kept but no longer used)
    # ───────────────────────────────────────────────
    def display_question(self, question, choices):
        """
        Old behavior: print question/answers into chat and enable A–D buttons.
        Left here in case anything else calls it, but Listener now uses show_question().
        """
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
            # NEW: use the bubble UI instead of printing in chat
            q = msg.get("question")
            c = msg.get("choices", [])
            # Always expect 4 choices; pad/trim just in case
            while len(c) < 4:
                c.append("")
            self.window.show_question(q, c[:4])

        elif t == "end_question":
            # NEW: end of this question → bring back chat UI
            self.window.hide_question()

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
