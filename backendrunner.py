from flask import Flask, request
import chess
from stockfish import Stockfish
import os
from pyngrok import ngrok
import time
import threading

app = Flask(__name__)

class ChessBrain:
    def __init__(self):
        self.board = chess.Board()
        self.app_color = None
        self.game_active = False
        self.last_position_snapshot = None
        self.first_move_received = False

        self.ai = Stockfish(path=self._find_stockfish(), depth=20, parameters={
            "Threads": 4,
            "Hash": 2048,
            "Skill Level": 20,
            "UCI_LimitStrength": False
        })

    def _find_stockfish(self):
        import shutil
        possible_paths = ["/usr/games/stockfish", "/usr/bin/stockfish", "stockfish"]
        for path in possible_paths:
            if os.path.isfile(path) or os.access(path, os.X_OK):
                return path
        return shutil.which("stockfish")

    def start_game(self, color):
        color = color.strip().lower()
        if color not in ['white', 'black']:
            return "Invalid"

        self.app_color = chess.WHITE if color == 'white' else chess.BLACK
        self.board.reset()
        self.game_active = True
        self.first_move_received = False
        self.last_position_snapshot = self._get_piece_snapshot()

        if self.app_color == chess.WHITE:
            move = self._get_best_move()
            return move if move else "Game Over"
        else:
            return ""

    def process_move(self, incoming):
        print(f"📥 Incoming: {incoming}")

        if not self.game_active:
            return "Game Over"

        # ===== ALWAYS CHECK IF IT'S A UCI MOVE FIRST =====
        if self._is_uci_move(incoming):
            try:
                move = chess.Move.from_uci(incoming.strip().lower())
                if move in self.board.legal_moves:
                    self.board.push(move)
                    self.last_position_snapshot = self._get_piece_snapshot()
                    print(f"✅ Move detected: {move.uci()}")

                    if self.board.is_checkmate():
                        self.game_active = False
                        threading.Thread(target=self._delayed_game_over).start()
                        return ""

                    ai_move = self._get_best_move()
                    print(f"🎯 AI response: {ai_move}")
                    return ai_move if ai_move else ""
                else:
                    return "Invalid"
            except:
                return "Invalid"

        # ===== POSITION FORMAT PROCESSING =====
        positions = self._parse_positions(incoming)
        if positions is None:
            return ""

        current_board_snapshot = self._get_piece_snapshot()

        # Compare if same as current board
        if positions == current_board_snapshot:
            return ""

        # Compare drastic change against CURRENT BOARD
        if self._is_drastic_change(positions, current_board_snapshot):
            return ""

        # Convert position snapshot into a best guess move
        move = self._deduce_move_from_snapshot(positions, current_board_snapshot)
        if not move:
            return ""

        print(f"✅ Move detected: {move}")

        try:
            move_obj = chess.Move.from_uci(move)
            if move_obj in self.board.legal_moves:
                self.board.push(move_obj)
                self.last_position_snapshot = self._get_piece_snapshot()
            else:
                return ""
        except:
            return ""

        if self.board.is_checkmate():
            self.game_active = False
            threading.Thread(target=self._delayed_game_over).start()
            return ""

        ai_move = self._get_best_move()
        print(f"🎯 AI response: {ai_move}")
        return ai_move if ai_move else ""

    # ====================== HELPERS ======================

    def _is_uci_move(self, text):
        text = text.strip().lower()
        if len(text) == 4 and text[0] in 'abcdefgh' and text[1] in '12345678' and text[2] in 'abcdefgh' and text[3] in '12345678':
            return True
        if len(text) == 5 and text[0] in 'abcdefgh' and text[1] in '12345678' and text[2] in 'abcdefgh' and text[3] in '12345678' and text[4] in 'qnrb':
            return True
        return False

    def _delayed_game_over(self):
        time.sleep(8)
        print("⚠️ Game Over")

    def _get_best_move(self):
        self.ai.set_fen_position(self.board.fen())
        best_move = self.ai.get_best_move_time(2000)
        if best_move:
            move = chess.Move.from_uci(best_move)
            if move in self.board.legal_moves:
                self.board.push(move)
                if self.board.is_checkmate():
                    self.game_active = False
                    threading.Thread(target=self._delayed_game_over).start()
                return best_move
        return None

    def _parse_positions(self, txt):
        try:
            txt = txt.strip().lower()

            if ';' in txt:
                parts = txt.split(';')
            else:
                parts = txt.split()

            white_squares = []
            black_squares = []

            for part in parts:
                part = part.strip()
                if part.startswith("white:"):
                    squares_str = part.split(":")[1]
                    white_squares = [sq.strip() for sq in squares_str.split(",") if sq.strip()]
                elif part.startswith("black:"):
                    squares_str = part.split(":")[1]
                    black_squares = [sq.strip() for sq in squares_str.split(",") if sq.strip()]

            valid_squares = {f"{file}{rank}" for file in 'abcdefgh' for rank in '12345678'}
            white_squares = [sq for sq in white_squares if sq in valid_squares]
            black_squares = [sq for sq in black_squares if sq in valid_squares]

            return {"white": sorted(white_squares), "black": sorted(black_squares)}

        except:
            return None

    def _get_piece_snapshot(self):
        w = []
        b = []
        for square, piece in self.board.piece_map().items():
            square_name = chess.square_name(square)
            if piece.color == chess.WHITE:
                w.append(square_name)
            else:
                b.append(square_name)
        return {"white": sorted(w), "black": sorted(b)}

    def _is_drastic_change(self, new_pos, current_pos):
        if current_pos is None:
            return False

        current_white = set(current_pos["white"])
        current_black = set(current_pos["black"])
        new_white = set(new_pos["white"])
        new_black = set(new_pos["black"])

        white_removed = current_white - new_white
        white_added = new_white - current_white
        black_removed = current_black - new_black
        black_added = new_black - current_black

        total_removed = len(white_removed) + len(black_removed)
        total_added = len(white_added) + len(black_added)

        if total_removed == 1 and total_added == 2:
            return True

        current_count = len(current_pos["white"]) + len(current_pos["black"])
        new_count = len(new_pos["white"]) + len(new_pos["black"])
        diff = abs(current_count - new_count)

        return diff > 2

    # ====================== UPDATED FUNCTION WITH CASTLING ======================

    def _deduce_move_from_snapshot(self, new_pos, current_pos):
        current_white = set(current_pos["white"])
        current_black = set(current_pos["black"])
        new_white = set(new_pos["white"])
        new_black = set(new_pos["black"])

        white_removed = current_white - new_white
        white_added = new_white - current_white
        black_removed = current_black - new_black
        black_added = new_black - current_black

        # ---- CASTLING DETECTION ----
        if white_removed == {"e1", "h1"} and white_added == {"g1", "f1"}:
            return "e1g1"
        if white_removed == {"e1", "a1"} and white_added == {"c1", "d1"}:
            return "e1c1"
        if black_removed == {"e8", "h8"} and black_added == {"g8", "f8"}:
            return "e8g8"
        if black_removed == {"e8", "a8"} and black_added == {"c8", "d8"}:
            return "e8c8"

        # ---- NORMAL MOVE ----
        if len(white_removed) == 1 and len(white_added) == 1 and not black_removed and not black_added:
            return list(white_removed)[0] + list(white_added)[0]

        if len(black_removed) == 1 and len(black_added) == 1 and not white_removed and not white_added:
            return list(black_removed)[0] + list(black_added)[0]

        # ---- CAPTURE ----
        if len(white_removed) == 1 and len(white_added) == 1 and len(black_removed) == 1 and not black_added:
            if list(white_added)[0] in black_removed:
                return list(white_removed)[0] + list(white_added)[0]

        if len(black_removed) == 1 and len(black_added) == 1 and len(white_removed) == 1 and not white_added:
            if list(black_added)[0] in white_removed:
                return list(black_removed)[0] + list(black_added)[0]

        return None


brain = ChessBrain()

@app.route('/start', methods=['POST'])
def start():
    color = request.get_data(as_text=True).strip()
    print(f"🎨 /start called with color: {color}")
    result = brain.start_game(color)
    print(f"🤖 AI First Move Output: {result}")
    return result, 200, {'Content-Type': 'text/plain'}

@app.route('/move', methods=['POST'])
def move():
    msg = request.get_data(as_text=True).strip()
    result = brain.process_move(msg)
    return result, 200, {'Content-Type': 'text/plain'}

ngrok.set_auth_token("36TsBVWahjhYRd3RdkwkI8vlldi_7p8EKoNKTLMKrpV9We6FY")
port = 5000
public_url = ngrok.connect(port)

print("✅ BACKEND LIVE!")
print("🌍 Public URL:", public_url)
print("🕹  POST /start   (body: 'white' or 'black')")
print("♟  POST /move    (body: 'e2e4' or 'white:a1,a2 black:a7,a8' or 'white:a1,a2;black:a7,a8')")
print("=" * 60)

app.run(host="0.0.0.0", port=port)
