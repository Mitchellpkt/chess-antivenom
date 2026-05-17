This is a hacky hobby project for finding optimal moves *if you know that your opponent is going to play a particular system*, which may be different from optimal moves if your adversary is fully unconstrained

We will refer to the "system player" and the "wildcard player".

This repository seeks to find best moves for the wildcard player against the anticipated moves of the system player.

## Input style

Systems are entered as PGN with wildcards, e.g.

`1. __ f6 2. __ c6 3. __`

## Motivation / principle

The goal is to exhaustively enumerate combinations of legal moves, and identify those leading to optimal engine evals for the wildcard player.

SPECIFICALLY we want the optimal evaluations for the wildcard player **at the end of the sequence**, with no regard to the intermediate evaluation.

## Illustration

### Normal gameplay (no system known in advance)

For contrast, suppose what we are in a scenario with **unconstrained** play, and black is the wildcard player.

If white plays `1. Nf3`, and we do NOT know what they will do next, then reasonable moves for black are the usual:

`1... Nf6`

`1... d5`

`1... e6`

In the unconstrained setting, `1... d6` is not a particularly strong move for black in response to the Zuckertort.

### Gameplay with a known system (this repository)

On the other hand, suppose we know that white **always plays the system**:

`1. Nf3 __ 2. Ne5 __`

In that case, `1... d6` is in fact a **very** strong move, because if we enumerate all possible sequences we find that the best outcome for the wildcard player (black) is:

`1. Nf3 d6 2. Ne5 dxe5!`

Suppose we set `num_solutions: int = 3` then I would assume that top solutions would include:

`1. Nf3 d6 2. Ne5 dxe5`

`1. Nf3 f6 2. Ne5 fxe5`

`1. Nf3 Nc6 2. Ne5 Nxe5`

(I could be wrong - I have written this example before writing the code, so this is just my guesses at likely solutions).

## Setup

Python deps:
```
pip install -r requirements.txt
```

Stockfish (the chess engine) is needed at runtime but isn't a pip package — install via your OS package manager:
```
sudo apt install stockfish        # Debian / Ubuntu
brew install stockfish            # macOS
```
Or grab a binary from https://stockfishchess.org/download/ and put it on your `PATH`. The code auto-detects it from `PATH` and the common install paths (`/usr/games/stockfish`, `/usr/bin/stockfish`, `/opt/homebrew/bin/stockfish`); you can also pass an explicit path via `config_engine_path` in `experiments/E1.py`.

## Running

```
python experiments/E1.py
```

Edit the config block at the top of `E1.py` to point at a different input file, change Stockfish depth/threads/hash, or adjust how many top solutions get printed. The full ranked list is always written to JSON; the top N is also logged to the console.