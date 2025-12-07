# Lichess Bot

A simple Lichess bot that uses Stockfish engine to play casual standard chess games.

## Overview

This bot connects to Lichess using the Lichess API and plays chess games using the Stockfish engine configured with minimal settings for low-level play.

## Configuration

### Stockfish Settings
- **Skill Level**: 0 (weakest setting, range 0-20)
- **Depth**: 1 (minimal analysis depth for weak play)
- **Threads**: 1 (single thread)
- **Hash**: 1 MB (minimal memory usage)

### Game Settings
- Only accepts **casual** (unrated) games
- Accepts **standard** and **Chess960** variants
- Automatically declines rated games and other variants
- Automatically challenges other online bots rated 1700 or less (3+0 casual)

## Setup

1. Create a Lichess BOT account or upgrade an existing account to BOT status
2. Generate an API token at https://lichess.org/account/oauth/token
3. Set the `LICHESS_API_TOKEN` secret with your API token
4. Run the bot

## Project Structure

```
lichess_bot.py   # Main bot script
replit.md        # This documentation file
```

## Requirements

- Python 3.11
- berserk (Lichess API client)
- python-chess (Chess library with Stockfish interface)
- Stockfish engine (installed via system packages)

## Running

The bot runs as a console application and will:
1. Connect to Lichess with your API token
2. Initialize the Stockfish engine
3. Listen for incoming challenges
4. Accept casual standard games
5. Play moves using Stockfish analysis

## Notes

- The Lichess account must be a BOT account (title: BOT)
- Once an account is upgraded to BOT, it cannot be used for human play
- The bot will only play casual games to maintain a low rating
