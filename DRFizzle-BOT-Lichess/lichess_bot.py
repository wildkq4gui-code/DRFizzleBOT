#!/usr/bin/env python3
"""
Lichess Bot using Stockfish with minimal settings.
Plays casual standard games at low rating.
"""

import os
import sys
import json
import time
import random
import threading
import logging
import signal
import re
import requests
import chess
import chess.engine
import berserk

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

STOCKFISH_PATH = "/nix/store/l4y0zjkvmnbqwz8grmb34d280n599i75-stockfish-17/bin/stockfish"

STOCKFISH_DEPTH = 1
STOCKFISH_THREADS = 1
STOCKFISH_HASH = 1
STOCKFISH_SKILL_LEVEL = 0  # 0-20, 0 is weakest

CHALLENGE_MAX_RATING = 1700
CHALLENGE_CLOCK_LIMIT = 60  # 1 minute in seconds
CHALLENGE_CLOCK_INCREMENT = 0  # 0 seconds increment
CHALLENGE_INTERVAL = 5  # Seconds between challenge attempts


class LichessBot:
    def __init__(self, api_token: str):
        self.api_token = api_token
        self.session = berserk.TokenSession(api_token)
        self.client = berserk.Client(self.session)
        self.username: str = ""
        self.engine: chess.engine.SimpleEngine | None = None
        self.is_playing = False
        self.challenger_running = True
        # When True the bot is in standby mode: stop issuing/accepting new games
        self.standby = False
        
    def start(self):
        try:
            account = self.client.account.get()
            self.username = account['username']
            logger.info(f"Logged in as: {self.username}")
            
            if account.get('title') != 'BOT':
                logger.warning("This account is not a BOT account.")
                logger.info("You need to upgrade your account to a BOT account on Lichess.")
                logger.info("Note: Once upgraded, you cannot play as a human anymore.")
                return
                
        except Exception as e:
            logger.error(f"Failed to authenticate: {e}")
            return

        self._init_engine()
        
        # Register signal handlers: standby and graceful shutdown
        try:
            signal.signal(signal.SIGUSR1, self._on_standby_signal)
            signal.signal(signal.SIGTERM, self._on_terminate_signal)
            signal.signal(signal.SIGINT, self._on_terminate_signal)
        except Exception:
            # In some environments (e.g., non-main threads) signal registration may fail
            logger.debug("Failed to register signal handlers; signals may not work in this environment")

        threading.Thread(target=self._challenger_loop, daemon=True).start()
        logger.info("Started bot challenger thread")
        
        logger.info("Starting event stream...")
        logger.info("Bot is ready! Waiting for challenges and games...")
        
        try:
            for event in self.client.bots.stream_incoming_events():
                if event['type'] == 'challenge':
                    self._handle_challenge(event['challenge'])
                elif event['type'] == 'gameStart':
                    game_id = event['game'].get('id') or event['game'].get('gameId')
                    if self.is_playing:
                        logger.info(f"Ignoring game {game_id}: Already playing another game")
                        try:
                            self.client.bots.resign_game(game_id)
                        except Exception:
                            pass
                        continue
                    logger.info(f"Game started: {game_id}")
                    self.is_playing = True
                    threading.Thread(
                        target=self._play_game,
                        args=(game_id,),
                        daemon=True
                    ).start()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self.challenger_running = False
            self._cleanup()

    def _init_engine(self):
        logger.info("Initializing Stockfish engine...")
        logger.info(f"  Depth: {STOCKFISH_DEPTH}")
        logger.info(f"  Skill Level: {STOCKFISH_SKILL_LEVEL} (0=weakest, 20=strongest)")
        logger.info(f"  Threads: {STOCKFISH_THREADS}")
        logger.info(f"  Hash: {STOCKFISH_HASH} MB")
        
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
            self.engine.configure({
                "Threads": STOCKFISH_THREADS,
                "Hash": STOCKFISH_HASH,
                "Skill Level": STOCKFISH_SKILL_LEVEL
            })
            logger.info("Stockfish engine initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Stockfish: {e}")
            sys.exit(1)

    def _on_standby_signal(self, signum, frame):
        """Signal handler to enter standby: stop accepting/challenging new games."""
        logger.info(f"Received standby signal (signal={signum}). Entering standby mode.")
        self.standby = True

    def _on_terminate_signal(self, signum, frame):
        """Signal handler for SIGTERM/SIGINT to request graceful shutdown."""
        logger.info(f"Received termination signal (signal={signum}). Initiating graceful shutdown.")
        # Stop challenger and mark standby so no new games are accepted
        self.challenger_running = False
        self.standby = True
        # Attempt a graceful cleanup and then exit
        try:
            self._cleanup()
        except Exception:
            pass
        sys.exit(0)

    def _handle_challenge(self, challenge: dict):
        challenge_id = challenge['id']
        challenger = challenge['challenger']['name']
        variant = challenge['variant']['key']
        rated = challenge['rated']
        speed = challenge['speed']
        
        # If in standby mode, decline all new challenges
        if getattr(self, 'standby', False):
            logger.info(f"In standby: declining challenge {challenge_id} from {challenger}")
            try:
                self.client.bots.decline_challenge(challenge_id, reason="standby")
            except Exception:
                pass
            return
        
        if challenger.lower() == self.username.lower():
            return
        
        logger.info(f"Received challenge from {challenger}")
        logger.info(f"  Variant: {variant}, Rated: {rated}, Speed: {speed}")
        
        if self.is_playing:
            logger.info(f"Declining challenge {challenge_id}: Already playing a game")
            self.client.bots.decline_challenge(challenge_id, reason="later")
            return
        
        if rated:
            logger.info(f"Declining challenge {challenge_id}: Only accepting casual games")
            self.client.bots.decline_challenge(challenge_id, reason="casual")
            return
            
        allowed_variants = ['standard', 'chess960']
        if variant not in allowed_variants:
            logger.info(f"Declining challenge {challenge_id}: Only accepting standard and chess960 variants")
            self.client.bots.decline_challenge(challenge_id, reason="standard")
            return
        
        logger.info(f"Accepting challenge {challenge_id}")
        try:
            self.client.bots.accept_challenge(challenge_id)
        except Exception as e:
            logger.error(f"Failed to accept challenge: {e}")

    def _play_game(self, game_id: str):
        logger.info(f"Playing game: {game_id}")
        board = chess.Board()
        is_white = True
        initial_fen = None
        is_chess960 = False
        
        try:
            for event in self.client.bots.stream_game_state(game_id):
                if event['type'] == 'gameFull':
                    white_player = event['white']
                    white_name = white_player.get('name') or white_player.get('id', 'Anonymous')
                    black_player = event['black']
                    black_name = black_player.get('name') or black_player.get('id', 'Anonymous')
                    variant = event.get('variant', {}).get('key', 'standard')
                    is_chess960 = variant == 'chess960'
                    initial_fen = event.get('initialFen', chess.STARTING_FEN)
                    if initial_fen == 'startpos':
                        initial_fen = chess.STARTING_FEN
                    
                    logger.info(f"Game: {white_name} vs {black_name} ({variant})")
                    
                    is_white = str(white_name).lower() == self.username.lower()
                    
                    moves = event['state'].get('moves', '')
                    board = chess.Board(initial_fen, chess960=is_chess960)
                    if moves:
                        for move in moves.split():
                            board.push_uci(move)
                    
                    if self._is_my_turn(board, is_white):
                        self._make_move(game_id, board)
                        
                elif event['type'] == 'gameState':
                    status = event.get('status')
                    if status in ['mate', 'resign', 'stalemate', 'timeout', 'draw', 'outoftime', 'aborted']:
                        logger.info(f"Game {game_id} ended: {status}")
                        self.is_playing = False
                        return
                    
                    moves = event.get('moves', '')
                    board = chess.Board(initial_fen if initial_fen else chess.STARTING_FEN, chess960=is_chess960)
                    if moves:
                        for move in moves.split():
                            board.push_uci(move)
                    
                    if not board.is_game_over() and self._is_my_turn(board, is_white):
                        self._make_move(game_id, board)
                            
                elif event['type'] == 'chatLine':
                    pass
                    
        except Exception as e:
            logger.error(f"Error in game {game_id}: {e}")
        finally:
            self.is_playing = False

    def _is_my_turn(self, board: chess.Board, is_white: bool) -> bool:
        return (board.turn == chess.WHITE and is_white) or (board.turn == chess.BLACK and not is_white)

    def _make_move(self, game_id: str, board: chess.Board):
        if board.is_game_over():
            return
        
        if self.engine is None:
            logger.error("Engine not initialized")
            return
            
        try:
            result = self.engine.play(
                board,
                chess.engine.Limit(depth=STOCKFISH_DEPTH)
            )
            move = result.move
            
            if move is None:
                logger.error("Engine returned no move")
                return
            
            logger.info(f"Playing move: {move.uci()}")
            self.client.bots.make_move(game_id, move.uci())
            
        except Exception as e:
            logger.error(f"Failed to make move: {e}")

    def _get_online_bots(self) -> list:
        """Fetch list of online bots from Lichess API."""
        try:
            url = "https://lichess.org/api/bot/online"
            headers = {
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/x-ndjson"
            }
            response = requests.get(url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            bots = []
            for line in response.iter_lines():
                if line:
                    bot = json.loads(line.decode('utf-8'))
                    bots.append(bot)
            return bots
        except Exception as e:
            logger.error(f"Failed to fetch online bots: {e}")
            return []

    def _challenger_loop(self):
        """Background thread that challenges other bots."""
        time.sleep(5)
        logger.info(f"Bot challenger: Looking for bots rated {CHALLENGE_MAX_RATING} or less")
        logger.info(f"Bot challenger: Will send 3+0 casual challenges every {CHALLENGE_INTERVAL} seconds")
        
        while self.challenger_running:
            # stop challenger loop if standby engaged
            if getattr(self, 'standby', False):
                logger.info("Standby engaged: stopping challenger loop")
                break
            try:
                if self.is_playing:
                    time.sleep(10)
                    continue
                
                bots = self._get_online_bots()
                
                eligible_bots = []
                for bot in bots:
                    if bot.get('id', '').lower() == self.username.lower():
                        continue
                    
                    perfs = bot.get('perfs', {})
                    blitz_rating = perfs.get('blitz', {}).get('rating', 1500)
                    
                    if blitz_rating <= CHALLENGE_MAX_RATING:
                        eligible_bots.append({
                            'username': bot.get('username') or bot.get('id'),
                            'rating': blitz_rating
                        })
                
                if eligible_bots and not self.is_playing:
                    target = random.choice(eligible_bots)
                    logger.info(f"Challenging bot: {target['username']} (rating: {target['rating']})")
                    self.send_challenge(
                        target['username'],
                        clock_limit=60,
                        clock_increment=0,
                        variant='standard'
                    )
                elif not eligible_bots:
                    logger.info("No eligible bots found online")
                
            except Exception as e:
                logger.error(f"Error in challenger loop: {e}")
            
            time.sleep(CHALLENGE_INTERVAL)

    def send_challenge(self, username: str, clock_limit: int = 300, clock_increment: int = 3, variant: str = 'standard'):
        """
        Send a casual challenge to a user.
        clock_limit: Initial time in seconds (default 5 minutes)
        clock_increment: Increment in seconds (default 3)
        variant: 'standard' or 'chess960' (default 'standard')
        """
        allowed_variants = ['standard', 'chess960']
        if variant not in allowed_variants:
            logger.error(f"Invalid variant '{variant}'. Only {allowed_variants} are supported.")
            return
            
        try:
            logger.info(f"Sending casual {variant} challenge to {username}")
            self.client.challenges.create(
                username,
                rated=False,
                clock_limit=clock_limit,
                clock_increment=clock_increment,
                variant=variant
            )
            logger.info(f"Challenge sent to {username}")
        except Exception as e:
            logger.error(f"Failed to send challenge: {e}")

    def _cleanup(self):
        if self.engine:
            logger.info("Closing Stockfish engine...")
            self.engine.quit()


def main():
    api_token = os.environ.get('LICHESS_API_TOKEN')

    # If environment variable is not set, attempt to read a local config fallback.
    if not api_token:
        cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'lichess_api.yml')
        cfg_path = os.path.normpath(cfg_path)
        if os.path.exists(cfg_path):
            try:
                with open(cfg_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        m = re.search(r"api_token:\s*[\"']?([^\"'\n\r]+)[\"']?", line)
                        if m:
                            api_token = m.group(1).strip()
                            logger.info("Loaded LICHESS_API_TOKEN from config/lichess_api.yml (fallback).")
                            break
            except Exception as e:
                logger.error(f"Failed to read config fallback at {cfg_path}: {e}")

    if not api_token:
        logger.error("LICHESS_API_TOKEN not found in environment or config file.")
        logger.error("Please set your Lichess API token (prefer repository secret `LICHESS_API_TOKEN`).")
        sys.exit(1)
    
    bot = LichessBot(api_token)
    bot.start()


if __name__ == "__main__":
    main()
