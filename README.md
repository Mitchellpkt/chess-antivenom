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