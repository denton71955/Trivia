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
    data = json.dumps(message).encode("utf-8")
    game = games[game_code]
    users = [game["host"]] + list(game["players"].keys())
    for u in users:
        conn = clients.get(u)
        if conn:
            try:
                conn.sendall(data)
            except:
                pass


def start_question_timer(game_code):
    for t in range(15, 0, -1):
        broadcast(game_code, {"type": "timer", "remaining": t})
        time.sleep(1)

    with lock:
        game = games[game_code]
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

        # NEW: signal clients that this question phase is over
        broadcast(game_code, {"type": "end_question"})

        # move to next question or end game
        game["index"] += 1
        if game["index"] < len(game["questions"]):
            time.sleep(3)
            send_next_question(game_code)
        else:
            broadcast(game_code, {"type": "system", "message": "🎉 Game over! Thanks for playing."})


def send_next_question(game_code):
    game = games[game_code]
    if game["index"] >= len(game["questions"]):
        return
    q = game["questions"][game["index"]]
    for p in game["players"].values():
        p["choice"] = None
        p["answered"] = False
    broadcast(game_code, {
        "type": "question",
        "question": q["question"],
        "choices": q["choices"]
    })
    threading.Thread(target=start_question_timer, args=(game_code,), daemon=True).start()


def update_scores(game_code):
    if game_code in games:
        score_list = [{"username": u, "score": s} for u, s in games[game_code]["scores"].items()]
        broadcast(game_code, {"type": "player_list", "players": score_list})


def handle_client(conn, addr):
    username = None
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            msg = json.loads(data.decode("utf-8"))
            act = msg.get("action")

            if act == "login":
                username = msg["username"]
                clients[username] = conn
                conn.sendall(json.dumps({"status": "success"}).encode("utf-8"))
                print(f"[LOGIN] {username} connected.")

            elif act == "create_game":
                # random 4-digit code per game
                while True:
                    game_code = str(random.randint(1000, 9999))
                    if game_code not in games:
                        break
                games[game_code] = {
                    "host": username,
                    "players": {},
                    "questions": [],
                    "index": 0,
                    "scores": {}
                }
                user_game[username] = game_code
                send(username, {"type": "system", "message": f"Game code: {game_code}"})
                print(f"[HOST] {username} created {game_code}")

            elif act == "join_game":
                code = msg["game_code"]
                if code not in games:
                    send(username, {"type": "system", "message": "Invalid game code."})
                    continue
                games[code]["players"][username] = {"answered": False, "choice": None}
                games[code]["scores"][username] = 0
                user_game[username] = code
                broadcast(code, {"type": "system", "message": f"{username} joined!"})
                update_scores(code)

            elif act == "upload_questions":
                code = user_game.get(username)
                if not code:
                    continue
                games[code]["questions"] = msg["questions"]
                send(username, {"type": "system", "message": f"{len(msg['questions'])} questions uploaded."})

            elif act == "start_game":
                code = user_game.get(username)
                if not code:
                    continue
                broadcast(code, {"type": "system", "message": "Game starting!"})
                send_next_question(code)

            elif act == "answer":
                code = user_game.get(username)
                if not code:
                    continue
                game = games[code]
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

    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        if username:
            code = user_game.pop(username, None)
            clients.pop(username, None)
            if code and code in games:
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
            conn.sendall(json.dumps(message).encode("utf-8"))
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
