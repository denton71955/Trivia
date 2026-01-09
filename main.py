import sys
import json
import socket
import csv
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QMessageBox, QFileDialog, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal


# ───────────────────────────────────────────────
# LOGIN WINDOW
# ───────────────────────────────────────────────
class LoginWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Trivia Login")
        self.setFixedSize(300, 200)

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
            sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
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
# LISTENER THREAD (QThread)
# ───────────────────────────────────────────────
class ListenerThread(QThread):
    message_received = pyqtSignal(dict)

    def __init__(self, conn):
        super().__init__()
        self.conn = conn

    def run(self):
        decoder = json.JSONDecoder()
        buffer = ""

        while True:
            try:
                data = self.conn.recv(4096)
                if not data:
                    break

                buffer += data.decode("utf-8")

                # Try to peel off as many complete JSON objects as we can
                while True:
                    buffer = buffer.lstrip()
                    if not buffer:
                        break

                    try:
                        obj, idx = decoder.raw_decode(buffer)
                    except json.JSONDecodeError:
                        # Not enough data yet to decode a full JSON object
                        break

                    # We got one complete JSON object
                    self.message_received.emit(obj)
                    buffer = buffer[idx:]
            except Exception as e:
                print(f"[LISTENER ERROR] {e}")
                break



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
        self.game_active = False
        self.has_answered = False
        self.in_room = False
        self.room_code = None


        # Timer / visual state
        self.timer_remaining = 0
        self.blink_state = False

        # Root layout
        layout = QHBoxLayout()
        left = QVBoxLayout()
        right = QVBoxLayout()
        self.setLayout(layout)

        # ───────────────────────────────────────
        # LEFT: CHAT + GAME
        # ───────────────────────────────────────
        # Pinned "Logged in as" (top-left)
        self.logged_in_label = QLabel(f"Logged in as: {username}")
        self.logged_in_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.logged_in_label.setStyleSheet("padding: 4px;")

        top_bar = QWidget()
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(0, 0, 0, 0)
        top_bar_layout.setSpacing(0)
        top_bar_layout.addWidget(self.logged_in_label)
        top_bar_layout.addStretch()

        top_bar.setFixedHeight(26)  # keeps it pinned; won't shift with timer changes
        left.addWidget(top_bar)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        left.addWidget(self.chat_display)

        self.chat_input = QLineEdit()
        self.chat_input.returnPressed.connect(self.send_chat)
        left.addWidget(self.chat_input)

        # GAME FRAME
        self.game_frame = QFrame()
        self.game_frame.setStyleSheet("""
            QFrame {
                background-color: #1e1e1e;
                border-radius: 12px;
            }
        """)
        game_layout = QVBoxLayout()
        self.game_frame.setLayout(game_layout)
        self.game_frame.hide()
        left.addWidget(self.game_frame)

        # Timer label (floating above question)
        self.timer_label = QLabel("")
        self.timer_label.setFixedHeight(160)
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setStyleSheet("""
            font-size: 40px;
            font-weight: bold;
            color: #00c8ff;
            margin-top: 5px;
            margin-bottom: 10px;
        """)
        self.timer_label.hide()
        game_layout.addWidget(self.timer_label)

        # Question label
        self.question_label = QLabel("QUESTION TEXT")
        self.question_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.question_label.setWordWrap(True)
        self.question_label.setStyleSheet("""
            font-size: 20px;
            font-weight: bold;
            color: #00c8ff;
            margin: 10px;
        """)
        game_layout.addWidget(self.question_label)

        # Answer buttons (A–D)
        self.answer_buttons = []
        for i in range(4):
            btn = QPushButton(f"Choice {i+1}")
            btn.setFixedHeight(45)
            btn.choice_letter = chr(65 + i)  # 'A', 'B', 'C', 'D'
            btn.clicked.connect(self.handle_answer)
            btn.setStyleSheet("""
                QPushButton {
                    border: 2px solid #00c8ff;
                    border-radius: 20px;
                    padding: 10px;
                    background-color: #2b2b2b;
                    color: #00c8ff;
                    font-size: 16px;
                    text-align: left;
                }
                QPushButton:hover { background-color: #3a3a3a; }
                QPushButton:pressed { background-color: #444444; }
                QPushButton:disabled { border-color: #555555; color: #555555; }
            """)
            btn.setEnabled(False)
            game_layout.addWidget(btn)
            self.answer_buttons.append(btn)

        # ───────────────────────────────────────
        # RIGHT: SCORES + HOST/PLAYER CONTROLS
        # ───────────────────────────────────────
        self.player_list = QListWidget()
        right.addWidget(QLabel("Scores:"))
        right.addWidget(self.player_list)

        if self.is_host:
            self.upload_btn = QPushButton("Upload Questions (CSV)")
            self.create_btn = QPushButton("Create Game")
            self.start_btn = QPushButton("Start Game")
            self.start_btn.setEnabled(False)

            self.upload_btn.clicked.connect(self.upload_questions)
            self.create_btn.clicked.connect(self.create_game)
            self.start_btn.clicked.connect(self.host_game_button_clicked)

            right.addWidget(self.upload_btn)
            right.addWidget(self.create_btn)
            right.addWidget(self.start_btn)
        else:
            self.join_label = QLabel("Enter Game Code:")
            self.join_input = QLineEdit()
            self.join_input.returnPressed.connect(self.join_game)
            
            self.join_btn = QPushButton("Join Game")
            self.join_btn.clicked.connect(self.join_game)

            right.addWidget(self.join_label)
            right.addWidget(self.join_input)
            right.addWidget(self.join_btn)

        layout.addLayout(left, 3)
        layout.addLayout(right, 1)

        # Blink timer for last 5 seconds
        self.blink_timer = QTimer()
        self.blink_timer.timeout.connect(self.update_blink)

        # Listener thread
        self.listener = ListenerThread(self.conn)
        self.listener.message_received.connect(self.handle_server_message)
        self.listener.start()
        
        if self.is_host:
            QTimer.singleShot(0, self.auto_create_game_on_houst_login)
            

    # ───────────────────────────────────────────────
    # HOST: START / END GAME
    # ───────────────────────────────────────────────
    def apply_game_started_ui(self):
        self.game_active = True

        if self.is_host:
            self.start_btn.setText("End Game")
            self.create_btn.setEnabled(False)
        else:
            if hasattr(self, "join_btn"):
                self.join_btn.setEnabled(False)
            if hasattr(self, "join_input"):
                self.join_input.setEnabled(False)

    def host_game_button_clicked(self):
        if not self.game_active:
            self.start_game()
        else:
            self.end_game()
            
    def auto_create_game_on_houst_login(self):
        if not self.is_host:
            return
        self.create_game()
        
        if hasattr(self, "create_btn"):
            self.create_btn.setEnabled(True)
            self.create_btn.setText("New Room")

    def start_game(self):
        msg = {"action": "start_game"}
        self.send_json(msg)

        # Host applies immediately
        self.apply_game_started_ui()

    def end_game(self):
        msg = {"action": "end_game"}
        self.send_json(msg)

        # Immediate local reset for host
        self.game_active = False
        self.hide_question()
        if self.is_host:
            self.start_btn.setText("Start Game")
            self.create_btn.setEnabled(True)

    def handle_end_game(self):
        """Called when server broadcasts 'end_game' to everyone."""
        # Hard reset local state
        self.game_active = False
        self.has_answered = False
        self.waiting_for_join = False

        # Stop any visuals/timers
        self.stop_blinking()
        self.reset_timer_display()

        # Force UI back to chat/lobby view
        self.hide_question()

        # Disable answer buttons
        for b in self.answer_buttons:
            b.setEnabled(False)

        if self.is_host:
            self.start_btn.setText("Start Game")
            self.create_btn.setEnabled(True)
        else:
            # ALWAYS re-enable join controls when game ends
            if hasattr(self, "join_btn"):
                self.join_btn.setEnabled(True)
            if hasattr(self, "join_input"):
                self.join_input.setEnabled(True)


    # ───────────────────────────────────────────────
    # NETWORK ACTIONS
    # ───────────────────────────────────────────────
    def send_json(self, msg: dict):
        self.conn.sendall((json.dumps(msg) + "\n").encode("utf-8"))
    
    def send_chat(self):
        txt = self.chat_input.text().strip()
        if not txt:
            return
        msg = {"action": "chat", "message": txt}
        self.send_json(msg)
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
                        questions.append({
                            "question": row[0],
                            "choices": row[1:5],
                            "answer": row[5]
                        })
            msg = {"action": "upload_questions", "questions": questions}
            self.send_json(msg)
            self.start_btn.setEnabled(True)
            self.upload_btn.setEnabled(False)
            QMessageBox.information(self, "Upload Complete", f"{len(questions)} questions uploaded.")
        except Exception as e:
            QMessageBox.critical(self, "Upload Error", str(e))

    def create_game(self):
        msg = {"action": "create_game"}
        self.upload_btn.setEnabled(True)
        self.send_json(msg)

    def join_game(self):
        code = self.join_input.text().strip()
        if not code:
            QMessageBox.warning(self, "Missing Code", "Please enter a game code.")
            return

        msg = {"action": "join_game", "game_code": code}
        self.waiting_for_join = True
        self.send_json(msg)

        def _re_enable_if_still_waiting():
            if getattr(self, "waiting_for_join", False) and not self.game_active:
                self.join_btn.setEnabled(True)
                self.join_input.setEnabled(True)


        QTimer.singleShot(3000, _re_enable_if_still_waiting)


        # Disable join controls for the duration of the game
        #self.join_btn.setEnabled(False)
        #self.join_input.setEnabled(False)

    # ───────────────────────────────────────────────
    # ANSWER HANDLING / HIGHLIGHTING
    # ───────────────────────────────────────────────
    def handle_answer(self):
        if self.has_answered:
            return

        sender = self.sender()
        choice_letter = sender.choice_letter

        msg = {"action": "answer", "choice": choice_letter}
        self.send_json(msg)

        self.has_answered = True

        # Highlight selected
        sender.setStyleSheet("""
            QPushButton {
                border: 2px solid #00c8ff;
                border-radius: 20px;
                padding: 10px;
                background-color: #005f7f;
                color: #00c8ff;
                font-size: 16px;
                text-align: left;
            }
        """)

        # Dim others and disable all
        for b in self.answer_buttons:
            if b is not sender:
                b.setStyleSheet("""
                    QPushButton {
                        border: 2px solid #444444;
                        border-radius: 20px;
                        padding: 10px;
                        background-color: #1c1c1c;
                        color: #444444;
                        font-size: 16px;
                        text-align: left;
                    }
                """)
            b.setEnabled(False)

    # ───────────────────────────────────────────────
    # SCOREBOARD
    # ───────────────────────────────────────────────
    def update_scores(self, players):
        self.player_list.clear()
        for p in players:
            self.player_list.addItem(f"{p['username']}: {p['score']}")

    # ───────────────────────────────────────────────
    # TIMER HELPERS
    # ───────────────────────────────────────────────
    def get_font_size_for_timer(self, remaining: int) -> int:
        if remaining <= 1:
            return 140
        if remaining == 2:
            return 120
        if remaining == 3:
            return 100
        if remaining == 4:
            return 80
        if remaining == 5:
            return 60
        return 40

    def set_timer_style(self, size: int, color: str):
        self.timer_label.setStyleSheet(f"""
            font-size: {size}px;
            font-weight: bold;
            color: {color};
            margin-top: 40px;
            margin-bottom: 0px;
        """)

    def start_blinking(self):
        if not self.blink_timer.isActive():
            self.blink_state = False
            self.blink_timer.start(350)

    def stop_blinking(self):
        if self.blink_timer.isActive():
            self.blink_timer.stop()
        self.blink_state = False

    def update_blink(self):
        size = self.get_font_size_for_timer(self.timer_remaining)
        color = "#ff3b3b" if self.blink_state else "#ffd93b"
        self.set_timer_style(size, color)
        self.blink_state = not self.blink_state

    def reset_timer_display(self):
        self.stop_blinking()
        self.timer_label.hide()
        self.timer_label.setText("")
        self.set_timer_style(40, "#00c8ff")

    # ───────────────────────────────────────────────
    # QUESTION UI
    # ───────────────────────────────────────────────
    def show_question(self, question, choices):
        self.has_answered = False

        # Reset timer visuals
        self.timer_remaining = 0
        self.reset_timer_display()
        self.timer_label.show()

        # Hide chat, show game UI
        self.chat_display.hide()
        self.chat_input.hide()

        self.question_label.setText(question)

        padded = list(choices)[:4]
        while len(padded) < 4:
            padded.append("")

        for i, b in enumerate(self.answer_buttons):
            b.setText(padded[i])
            b.setEnabled(bool(padded[i]))
            b.setStyleSheet("""
                QPushButton {
                    border: 2px solid #00c8ff;
                    border-radius: 20px;
                    padding: 10px;
                    background-color: #2b2b2b;
                    color: #00c8ff;
                    font-size: 16px;
                    text-align: left;
                }
                QPushButton:hover { background-color: #3a3a3a; }
                QPushButton:pressed { background-color: #444444; }
                QPushButton:disabled { border-color: #555555; color: #555555; }
            """)

        self.game_frame.show()

    def hide_question(self):
        self.game_frame.hide()
        self.chat_display.show()
        self.chat_input.show()

        for b in self.answer_buttons:
            b.setEnabled(False)

        self.reset_timer_display()

    # ───────────────────────────────────────────────
    # HANDLE SERVER MESSAGES (runs on GUI thread)
    # ───────────────────────────────────────────────
    def handle_server_message(self, msg: dict):
        t = msg.get("type")

        if t == "system":
            self.chat_display.append(f"[System] {msg.get('message', '')}")

        elif t == "chat":
            self.chat_display.append(f"{msg.get('username')}: {msg.get('message')}")

        elif t == "join_ok":
            # If you joined a new room while any game UI is up, force lobby view
            self.hide_question()
            self.game_active = False
            self.has_answered = False
            self.waiting_for_join = False
            self.reset_timer_display()

            self.in_room = True
            self.room_code = msg.get("game_code")

            joined_code = msg.get("game_code", "")
            self.chat_display.append(f"[System] Joined game {joined_code}.")

            # ✅ Join stays enabled unless a game is active
            if hasattr(self, "join_btn"):
                self.join_btn.setEnabled(not self.game_active)
            if hasattr(self, "join_input"):
                self.join_input.setEnabled(not self.game_active)

        elif t == "join_fail":
            self.waiting_for_join = False
            self.in_room = False
            reason = msg.get("reason", "Unable to join.")
            self.chat_display.append(f"[System] {reason}")

            # Keep join controls enabled
            if hasattr(self, "join_btn"):
                self.join_btn.setEnabled(True)
            if hasattr(self, "join_input"):
                self.join_input.setEnabled(True)

        elif t == "question":
            # Ignore questions if you are not currently joined to a room
            if not getattr(self, "in_room", False):
                return

            # Enter game mode on first question of a room session
            if not self.game_active:
                self.apply_game_started_ui()

            self.show_question(msg["question"], msg.get("choices", []))

        elif t == "timer":
            remaining = int(msg.get("remaining", 0))
            self.timer_remaining = remaining
            self.timer_label.setText(str(remaining))
            self.timer_label.show()

            if remaining <= 5:
                self.start_blinking()
            else:
                self.stop_blinking()
                size = self.get_font_size_for_timer(remaining)
                self.set_timer_style(size, "#00c8ff")

        elif t == "round_end":
            correct = msg.get("correct", "")
            players = msg.get("players", [])
            self.chat_display.append(f"\n✅ Correct answer: {correct}\n")
            self.update_scores(players)
            for b in self.answer_buttons:
                b.setEnabled(False)

        elif t == "end_question":
            self.hide_question()

        elif t == "end_game":
            self.handle_end_game()

        elif t == "player_list":
            self.update_scores(msg.get("players", []))

            
    def closeEvent(self, event):
        try:
            self.send_json({"action": "disconnect"})
        except:
            pass
        try:
            self.conn.shutdown(socket.SHUT_RDWR)
        except:
            pass
        try:
            self.conn.close()
        except:
            pass
        event.accept()




# ───────────────────────────────────────────────
# MAIN
# ───────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginWindow()
    login.show()
    sys.exit(app.exec())
