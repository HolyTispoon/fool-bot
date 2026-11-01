# D12 Ball 2.1, filed away

D12 Ball 2.1 was played on the Discord bot from 2026-10-31 to 2026-11-01. It
replaced 2.0's two-headed cards and advanced maneuvers, and **2.2 replaced it on
2026-11-01** (the author). The 2.1 games still in progress on the live bot are
abandoned as 2.2 ships (the author: *"I'm gonna abandon ongoing games"*), so
nothing in the bot plays 2.1 any more.

`rules-2.1.md` here is 2.1's rules file exactly as it stood on `main` the day
it was replaced, its links left relative to `docs/` where it lived. The bot
does not read it. The current rules are
[docs/rules-2.2.md](../../docs/rules-2.2.md), and every change between the two
is dated in [docs/rules-log.md](../../docs/rules-log.md).

## What 2.1 was

- **A deck of twenty-four single-faced cards per coach**, four for each basic
  maneuver: P1 to P4 Pass, B1 to B4 Dribble and H1 to H4 High Ball on offense,
  and F1 to F4 Deflect, S1 to S4 Steal and R1 to R4 Pressure on defense. The
  cards came from the sheet's `maneuvers 2.1` tab.
- **A secret hand of five**, drawn back up to five after every card played,
  and five again at halftime.
- **The flip.** On their turn a coach could play any card as the same rank's
  maneuver on the other side, without its special, by discarding a second
  card of their choice with it. That way a hand of five could always play
  every rank on either side.
- **Every card played its rank's basic effect, plus a special.** The special
  was a role interaction that applied when the player making the maneuver
  held a role it named. The four cards of a rank named all six roles once
  between them.

The rest of 2.1 is still in 2.2 unchanged:

- no advanced maneuvers and no gambit coin;
- the coin that settles every tie and is tossed again after it;
- roles belonging to the formation, with moving on the board costing a token
  a space;
- no shooting range.

## What 2.2 changed

- **The same twenty-four cards are printed two to a card.** Each 2.2 card is a
  2.1 offensive card on the top half and the 2.1 defensive card of the same
  rank and number on the bottom half: P*n*/F*n*, B*n*/S*n*, H*n*/R*n*. That
  makes twelve cards a deck, and every card plays on either side with its
  special.
- **The hand is three cards.**
- **The flip is gone**, since every card now plays on either side.

The card data did not change. `d12ball/data/maneuver_cards.json` still holds
the twenty-four rows of the `maneuvers 2.1` tab, and the bot pairs them into
cards (`maneuver_deck.deck_cards`).

## Where 2.1's code is

The 2.1 code is in git history only:

- the flip: `CardPlay.flip` and `extra_ids`, `FlipExtraView`, and the pick's
  `extra_card_id`;
- the single-faced card face, with its spec-ability space and green flip strip
  (`deck_faces.draw_face`);
- the hand of five (`maneuver_deck.HAND_SIZE`).

All of it was removed in the commit that brought in 2.2, so the last commit on
`main` before 2.2 merged is the place to read it.
