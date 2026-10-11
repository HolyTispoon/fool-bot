"""Best six of N: how often each Tethys poker set is a hand's best, by Monte Carlo.

The sample behind the table in docs/tethys-games.md, "Six of eight"
(2026-10-11, 40,000 hands a deal, seed 12). Kept with the parked
worksheet, not in scripts/, since nothing on main runs it:

    python3 docs/tethys-games/best_of_n.py . 40000
"""
import random, sys
from collections import Counter
from itertools import combinations
sys.path.insert(0, sys.argv[1])
from tethysdeck.deck import SUITS, RANKS
from tethysdeck.sets import SETS, set_of
ORDER = {s.key: i for i, s in enumerate(SETS)}
deck = [(s, r) for s in SUITS for r in RANKS]
rng = random.Random(12)
def best(cards, pocket=None, use=None):
    if pocket is None:
        return min((set_of(h) for h in combinations(cards, 6)), key=ORDER.get)
    board = [c for c in cards if c not in pocket]
    return min((set_of(pocket + list(b)) for b in combinations(board, 3)), key=ORDER.get)
for label, n, omaha in (("dealt 6", 6, False), ("best 6 of 8 (3+5)", 8, False), ("best 6 of 9 (3+6)", 9, False), ("3 pocket + exactly 3 of 5 board", 8, True)):
    trials = int(sys.argv[2])
    tally = Counter()
    for _ in range(trials):
        cards = rng.sample(deck, n)
        tally[best(cards, cards[:3]) if omaha else best(cards)] += 1
    print(f"\n{label}  ({trials} hands)")
    ranked = sorted(tally, key=lambda k: -tally[k])
    for s in SETS:
        print(f"  {s.name:24s} {100*tally[s.key]/trials:8.3f}%   rarity rank {ranked[::-1].index(s.key)+1 if s.key in tally else '-'}")
