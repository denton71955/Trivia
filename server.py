import socket
import threading
import json
import time
import random  # for random game codes

HOST = "0.0.0.0"
PORT = 65432

clients = {}
games = {}
user_game = {}
lock = threading.Lock()


def broadcast(game_code, message):
    if game_code not in games:
        return

    data = (json.dumps(message) + "\n").encode("utf-8")

    game = games[game_code]
    recipients = [game["host"]] + list(game["players"].keys())

    for u in recipients:
        conn = clients.get(u)
        if conn:
            try:
                conn.sendall(data)
            except:
                pass



def start_question_timer(game_code):
    # 15-second countdown; respects 'active' flag so End Game can interrupt.
    for t in range(15, 0, -1):
        with lock:
            game = games.get(game_code)
            if not game or not game.get("active", True):
                return
        broadcast(game_code, {"type": "timer", "remaining": t})
        time.sleep(1)

    with lock:
        game = games.get(game_code)
        if not game or not game.get("active", True):
            return

        q = game["questions"][game["index"]]
        correct = q["answer"].strip().lower()

        # score answers
        for uname, pdata in game["players"].items():
            if pdata["choice"] and pdata["choice"].lower() == correct:
                game["scores"][uname] += 1

        score_list = [{"username": u, "score": s} for u, s in game["scores"].items()]
        broadcast(game_code, {
            "type": "round_end",
            "correct": q["answer"],
            "players": score_list
        })

        # hide question UI after each round
        broadcast(game_code, {"type": "end_question"})

        # advance to next question or end
        game["index"] += 1
        if game["index"] < len(game["questions"]):
            # schedule next question outside the lock
            next_question = True
        else:
            # natural end of game
            game["active"] = False
            broadcast(game_code, {"type": "system", "message": "🎉 Game over! Thanks for playing."})
            broadcast(game_code, {"type": "end_game"})
            next_question = False

    if next_question:
        time.sleep(3)
        send_next_question(game_code)


def send_next_question(game_code):
    with lock:
        game = games.get(game_code)
        if not game or not game.get("active", True):
            return
        if game["index"] >= len(game["questions"]):
            # nothing more to ask
            game["active"] = False
            broadcast(game_code, {"type": "system", "message": "🎉 Game over! Thanks for playing."})
            broadcast(game_code, {"type": "end_game"})
            return

        q = game["questions"][game["index"]]
        for p in game["players"].values():
            p["choice"] = None
            p["answered"] = False

        question_payload = {
            "type": "question",
            "question": q["question"],
            "choices": q["choices"]
        }

    # send question and start timer thread
    broadcast(game_code, question_payload)
    threading.Thread(target=start_question_timer, args=(game_code,), daemon=True).start()


def update_scores(game_code):
    with lock:
        game = games.get(game_code)
        if not game:
            return
        score_list = [{"username": u, "score": s} for u, s in game["scores"].items()]
    broadcast(game_code, {"type": "player_list", "players": score_list})


def handle_client(conn, addr):
    username = None
    try:
        buffer = ""

        while True:
            data = conn.recv(4096)
            if not data:
                break

            buffer += data.decode("utf-8")

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue

                msg = json.loads(line)
                act = msg.get("action")

                if act == "login":
                    username = msg["username"]
                    
                    # If username already exists, drop old connection/state
                    old = clients.get(username)
                    if old and old is not conn:
                        try: old.close()
                        except: pass
                        
                    clients[username] = conn
                    
                    # Optional but very helpful: reset mapping on login
                    user_game.pop(username, None)
    
                    conn.sendall((json.dumps({"status": "success"}) + "\n").encode("utf-8"))
                    print(f"[LOGIN] {username} connected.")

                elif act == "create_game":
                    # If this host already has a room, close it first
                    old_code = user_game.get(username)
                    if old_code and old_code in games:
                        with lock:
                            old_game = games.get(old_code)
                            # Only the host should be able to "replace" their room
                            if old_game and old_game.get("host") == username:
                                # Tell everyone in the old room it's over
                                broadcast(old_code, {"type": "system", "message": "🚪 Host started a new room. This room is now closed."})
                                broadcast(old_code, {"type": "end_question"})
                                broadcast(old_code, {"type": "end_game"})

                                # Detach players from old room
                                for p in list(old_game["players"].keys()):
                                    user_game.pop(p, None)

                                # Detach host and delete the room
                                user_game.pop(username, None)
                                del games[old_code]

                    # Now create the new room like you already do...
                    while True:
                        game_code = str(random.randint(1000, 9999))
                        if game_code not in games:
                            break
                    games[game_code] = {
                        "host": username,
                        "players": {},
                        "questions": [],
                        "index": 0,
                        "scores": {},
                        "active": False
                    }
                    user_game[username] = game_code
                    send(username, {"type": "system", "message": f"Game code: {game_code}"})

                elif act == "join_game":
                    # If user was in an old room, detach them first (good)
                    old = user_game.get(username)
                    if old and old in games:
                        with lock:
                            games[old]["players"].pop(username, None)
                            games[old]["scores"].pop(username, None)

                    code = str(msg.get("game_code", "")).strip()

                    with lock:
                        game = games.get(code)
                        if not game:
                            send(username, {"type": "join_fail", "reason": "Invalid game code."})
                            continue

                        # (Optional) prevent joining an active game mid-round if you want
                        if game.get("active"):
                            send(username, {"type": "join_fail", "reason": "Game already started."})
                            continue

                        game["players"][username] = {"answered": False, "choice": None}
                        game["scores"][username] = 0
                        user_game[username] = code

                    # ✅ Tell ONLY this user the join succeeded
                    send(username, {"type": "join_ok", "game_code": code})

                    # ✅ Tell everyone in the room that user joined
                    broadcast(code, {"type": "system", "message": f"{username} joined!"})
                    update_scores(code)

                elif act == "upload_questions":
                    code = user_game.get(username)
                    if not code:
                        continue
                    with lock:
                        game = games.get(code)
                        if not game:
                            continue
                        game["questions"] = msg["questions"]
                    send(username, {"type": "system", "message": f"{len(msg['questions'])} questions uploaded."})

                elif act == "start_game":
                    code = user_game.get(username)
                    if not code:
                        continue
                    with lock:
                        game = games.get(code)
                        if not game:
                            continue
                        if not game["questions"]:
                            send(username, {"type": "system", "message": "No questions uploaded."})
                            continue
                        game["active"] = True
                        game["index"] = 0  # start from first question
                        # Note: scores are NOT reset here; can change later if desired.

                    broadcast(code, {"type": "system", "message": "Game starting!"})
                    send_next_question(code)

                elif act == "end_game":
                    code = user_game.get(username)
                    if not code:
                        continue

                    with lock:
                        game = games.get(code)
                        if not game:
                            continue
                        if username != game["host"]:
                            send(username, {"type": "system", "message": "Only the host can end the game."})
                            continue

                        # ✅ Stop the round, but KEEP the room and membership
                        game["active"] = False
                        game["index"] = 0

                        # Optional: clear per-round answer state
                        for p in game["players"].values():
                            p["choice"] = None
                            p["answered"] = False

                    # Tell everyone to return to lobby/chat
                    broadcast(code, {"type": "system", "message": "Game ended by host."})
                    broadcast(code, {"type": "end_question"})
                    broadcast(code, {"type": "end_game"})




                elif act == "answer":
                    code = user_game.get(username)
                    if not code:
                        continue
                    with lock:
                        game = games.get(code)
                        if not game or not game.get("active", True):
                            send(username, {"type": "system", "message": "No active game."})
                            continue
                        if username in game["players"] and not game["players"][username]["answered"]:
                            game["players"][username]["answered"] = True
                            game["players"][username]["choice"] = msg["choice"]
                            send(username, {"type": "system", "message": f"Answer '{msg['choice']}' submitted."})
                        else:
                            send(username, {"type": "system", "message": "Already answered."})

                elif act == "chat":
                    code = user_game.get(username)
                    if not code:
                        continue
                    broadcast(code, {"type": "chat", "username": username, "message": msg["message"]})
                    
                elif act == "disconnect":
                    break


    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        if username:
            code = user_game.pop(username, None)
            clients.pop(username, None)
            if code and code in games:
                with lock:
                    game = games[code]
                    if username == game["host"]:
                        broadcast(code, {"type": "system", "message": "Host disconnected. Game closed."})
                        del games[code]
                    else:
                        game["players"].pop(username, None)
                        game["scores"].pop(username, None)
                        broadcast(code, {"type": "system", "message": f"{username} left."})
                        update_scores(code)
            conn.close()


def send(username, message):
    conn = clients.get(username)
    if conn:
        try:
            conn.sendall((json.dumps(message) + "\n").encode("utf-8"))
        except:
            pass


def start_server():
    print(f"[SERVER] Trivia running on {HOST}:{PORT}")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, PORT))
        s.listen()
        while True:
            conn, addr = s.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    start_server()
