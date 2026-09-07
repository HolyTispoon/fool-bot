"""
The rules-only slice of D12 Ball's cog: decisions and candidate lists
that read a match, a catalog, or a ruleset and never touch Discord --
no bot, no interaction, no games dict, no board refresh. Everything
here is answerable by constructing a RulesEngine directly, with no
cog and no fakes for discord.py's objects.

Moved out of cogs/d12ball.py rather than left there: nothing about
these methods is an accident of where the class happens to live, and
splitting them out is what lets a test build one without going through
`commands.Bot`. What stayed behind in the cog either touches Discord
directly, formats text that needs the emoji dicts `cog_load` fetches
(`format_role_bracket` and everything built on it -- an emoji dict is
live Discord data, not a fact about the match), or orchestrates a
multi-step flow across several of these decisions plus a board refresh
-- `continue_run_back` is the clearest example: it is *built from*
`next_run_back_step` and `apply_forced_run_backs` below, but the loop
itself sends messages and batches board writes, which is exactly the
Discord-facing half this module has no business holding.

Some methods here build prompt text or a `ChallengeSide` for the
matchup image -- `build_turn_prompt`, `challenge_side`, and their
kind. That is presentation, not a rule, but it is presentation over
nothing but the match and the catalogs: no emoji, no interaction, no
cog. `d12ball/formatting.py` is where the plain-text half of that
lives (space codes, team-side labels, player names), imported here the
same way it is imported into cogs/d12ball_helpers.py -- see that
module's own docstring for why the split runs where it does.

`D12Ball.engine` is the one instance a game's cog builds at startup,
from the same four things `RulesEngine.__init__` takes: the player
catalog, the basic ruleset, the maneuver catalog, and the AI
strategies. Every method that used to read `self.player_catalog` (and
so on) on the cog reads `self.player_catalog` here instead -- the
attribute names did not change, only which object they live on -- so
moving a method's body across was mechanical and the diff on the cog
side is only ever "insert `.engine`" at each call site.
"""

import random
from collections.abc import Collection
from dataclasses import dataclass
from typing import Optional

from d12ball.ai import AIStrategy
from d12ball.components import (
    DRIBBLE_BURST_MAX_DISTANCE,
    SETUP_PASS_DISTANCES,
    SETUP_PASS_FULLBACK_DISTANCE,
    SKILLED_PASS_REACH,
    MANEUVER_TIER_ADVANCED,
    MANEUVER_TIER_BASIC,
    CYBORG_DRAINED_AT,
    OVERDRIVE_BONUS,
    OVERDRIVE_DRAIN_COST,
    SETUP_AREAS,
    SPECIES_CYBORG,
    SPECIES_FIRE_DEMON,
    SPECIES_OOZE,
    SPECIES_TELEKINETIC,
    BasicRuleset,
    CoachingOccasion,
    FormationShape,
    ManeuverCatalog,
    ManeuverDefinition,
    MatchState,
    PlayerCatalog,
    PlayerDefinition,
    PlayerRole,
    ShotDefender,
    TeamSetup,
    TeamSide,
    Zone,
    formation_space_order,
    zone_for_area,
)
from d12ball.formatting import (
    ROLE_INITIALS,
    ball_space_label,
    contest_noun,
    destination_display_name,
    format_player_with_team,
    format_team_side_label,
    space_label,
    travel_space_label,
)
from d12ball.game import (
    AIOpponent,
    D12BallGame,
    Formation,
    GameMode,
    Team,
    team_display_name,
)
from d12ball.render import TEAM_COLORS, ChallengeSide


@dataclass(frozen=True)
class IgnitedRoll:
    """
    What a species ability did to one d12 -- Volatile's ignite, today,
    and the shape anything else that reads a die will report through.

    It deliberately does **not** carry the total. The die's own face is
    what the dice image draws and what every roll site already has in
    hand; an ignite is arithmetic on top of it, exactly like the
    Midfielder's +3 or the ball speed modifier, so it is reported as a
    `modifier` and a `detail` line the caller adds to what it was
    already building. That is what let all six roll sites take this
    without changing how they roll, display or total anything.

    `second` is the ignite's own die, `surge` says which way it went,
    and `modifier` is 0 for every roll that did not ignite -- which is
    every roll in a basic game, and most rolls in an advanced one.
    """

    face: int
    modifier: int = 0
    second: Optional[int] = None
    surge: bool = False

    @property
    def ignited(self) -> bool:
        return self.second is not None

    @property
    def backfire(self) -> bool:
        return self.ignited and not self.surge

    @property
    def detail(self) -> Optional[str]:
        """
        The line this adds to the dice image's modifier list, or None
        when nothing happened. Worded so a coach can see the second die
        that produced it -- "+9 Volatile surge (9)" rather than a bare
        number nothing on the image explains.
        """
        if not self.ignited:
            return None
        word = "surge" if self.surge else "backfire"
        return f"{self.modifier:+d} Volatile {word} ({self.second})"


# The faces that ignite a Fire Demon's die, and the lowest second roll
# that surges rather than backfires -- see "Volatile (Fire Demon)" in
# docs/living-rules.md. Named rather than written into the predicate
# because both numbers are the author's and neither is derivable.
VOLATILE_IGNITE_FACES = (6, 7)
VOLATILE_SURGE_MINIMUM = 5


# The halftime sequence's stages, in order -- see
# RulesEngine.next_halftime_stage. Each side gets its own
# extra-exhaustion-token choice and its own Coaching Choice, **the
# visitors first** throughout: they kick off the second half, so they
# are the side whose arrangement the restart depends on.
HALFTIME_STAGES = (
    "extra_token_visiting",
    "extra_token_home",
    "coaching_visiting",
    "coaching_home",
)

# Both coaches get a Coaching Choice before kickoff -- see
# RulesEngine.next_setup_stage. **Home first**, since they kick off the
# first half, the same reason the visitors go first at halftime.
SETUP_STAGES = (
    "coaching_home",
    "coaching_visiting",
)

# And both get one more between the whistle and the shootout, on a
# level score -- see RulesEngine.next_full_time_stage. Nobody kicks
# anything off here, so there is nothing to key the order on; **home
# first** is the author's call, and it matches setup.
FULL_TIME_STAGES = (
    "coaching_home",
    "coaching_visiting",
)

# What a game saved mid-halftime under the old sequence comes back as.
# Halftime used to run substitutions and free any-zone repositioning as
# two stages a side; the Coaching Choice is one, so both old stages map
# onto it. A game paused in either resumes at that side's hub.
LEGACY_HALFTIME_STAGES = {
    "subs_home": "coaching_home",
    "subs_visiting": "coaching_visiting",
    "reposition_home": "coaching_home",
    "reposition_visiting": "coaching_visiting",
}


class RulesEngine:
    """
    D12 Ball's rules, over a fixed player catalog, ruleset, maneuver
    catalog and set of AI strategies -- all loaded once at startup and
    read-only from here on, same as on the cog. A match is passed into
    each method rather than held, since a RulesEngine serves every game
    a process is running at once.
    """

    def __init__(
        self,
        player_catalog: PlayerCatalog,
        basic_ruleset: BasicRuleset,
        maneuver_catalog: ManeuverCatalog,
        ai_strategies: dict[AIOpponent, AIStrategy],
    ) -> None:
        self.player_catalog = player_catalog
        self.basic_ruleset = basic_ruleset
        self.maneuver_catalog = maneuver_catalog
        self.ai_strategies = ai_strategies

    def advanced_maneuvers_apply(self, game: D12BallGame) -> bool:
        """
        Whether this game is playing the **advanced maneuvers** -- the
        first of the two modules advanced mode turns on.

        Advanced mode is one switch and brings both modules with it; a
        game may then take just one of the two (the author, PR #177
        review), which is what `game.advanced_maneuvers` says. Both
        halves are asked here so no call site can check the mode and
        forget the opt-out, or the other way round.
        """
        return game.mode == GameMode.ADVANCED and game.advanced_maneuvers

    def species_abilities_apply(self, game: D12BallGame) -> bool:
        """
        Whether this game is playing the **species abilities** -- the
        second module, and the twin of `advanced_maneuvers_apply`.

        In a basic game species is only a name on the card and every
        player follows the standard rules; see "Species abilities" in
        docs/living-rules.md.
        """
        return game.mode == GameMode.ADVANCED and game.species_abilities

    def species_of(self, player_id: str) -> str:
        """
        The species a card belongs to, or `""` when the id names nobody
        the catalog knows or a roster written before the column existed.

        Tolerant rather than raising, because every caller is a
        predicate asking whether an ability fires: a stale id left on a
        match by a period reset should answer "no ability", the same
        way `turn_handler_candidates` treats a stale carrier as
        harmless. A caller that genuinely needs the definition should
        ask `player_catalog.player_by_id` and let it raise.
        """
        try:
            return self.player_catalog.player_by_id(player_id).species
        except ValueError:
            return ""

    def has_species_ability(
        self,
        game: D12BallGame,
        player_id: str,
        species: str,
    ) -> bool:
        """
        **The one question every species-ability site asks**: does this
        card, in this game, right now, have that species' ability?

        It folds the module gate and the species check together for the
        reason `settled_maneuver_winner` is one predicate over three
        call sites -- the two are always asked in the same breath, and
        a site that checks the species and forgets the module plays a
        basic game by advanced rules. Nothing may read
        `PlayerDefinition.species` to decide a rule without coming
        through here.

        A player fielded on both sides of one game carries the ability
        on both cards, which falls out for free: `species_of` resolves
        a duplicate card id to the same person (see
        `PlayerCatalog.player_by_id`).
        """
        if not self.species_abilities_apply(game):
            return False
        return self.species_of(player_id) == species

    def ignite(
        self,
        game: D12BallGame,
        player_id: Optional[str],
        face: int,
    ) -> IgnitedRoll:
        """
        **Every d12 a player rolls comes through here**, and comes back
        saying what -- if anything -- their species did to it. Volatile
        is the only ability that reads a die today; the funnel is what
        stops the next one being written at six call sites.

        It takes the face rather than rolling it. Each site already
        knows how to get its own dice -- `random.randint(1, 12)`, or
        the tutorial's scripted faces through `tutorial_dice` -- and
        taking that over would have meant threading the tutorial's
        script through here for no gain. What it owns is the *reading*:
        a natural 6 or 7 on a Fire Demon's die ignites, a second d12 is
        rolled, and 5-12 adds it while 1-4 subtracts it.

        Three things the rules say that fall out of the shape:

        - **The face is the natural die, before any skill or
          modifier.** Callers add their skill to the total afterwards,
          so what arrives here is always the bare roll -- which is what
          the ignite condition is written against.
        - **The second die never ignites in turn.** It is rolled here
          and returned as a number, never passed back through.
        - **A die belonging to no player never ignites**, which is why
          `player_id` is optional: the defending coach's die in a score
          attempt is the board's, not a card's, and a roll with no
          Fire Demon behind it comes back as the face and nothing else.
        """
        if face not in VOLATILE_IGNITE_FACES:
            return IgnitedRoll(face=face)
        if player_id is None:
            return IgnitedRoll(face=face)
        if not self.has_species_ability(game, player_id, SPECIES_FIRE_DEMON):
            return IgnitedRoll(face=face)

        second = random.randint(1, 12)
        surge = second >= VOLATILE_SURGE_MINIMUM
        return IgnitedRoll(
            face=face,
            modifier=second if surge else -second,
            second=second,
            surge=surge,
        )

    def overdrive_candidates(
        self,
        game: D12BallGame,
        match: MatchState,
        player_ids: Collection[Optional[str]],
    ) -> list[str]:
        """
        Which of the players about to roll may still declare Overdrive
        -- the Cyborgs among them who have not already declared and are
        not injured.

        Every roll prompt asks this with whoever is rolling on it, and
        builds a button per answer. Passing the rollers in rather than
        deriving them here is what lets one method serve six prompts
        that each know their own rollers and nothing else: a score
        attempt has a shooter, a contest has two sides, a shootout test
        has one a side.

        `None` is allowed in and filtered out, since a score attempt's
        second die belongs to no player.
        """
        if not self.species_abilities_apply(game):
            return []
        return [
            player_id
            for player_id in player_ids
            if player_id is not None
            and player_id not in match.pending_overdrive
            and player_id not in match.injured
            and self.has_species_ability(game, player_id, SPECIES_CYBORG)
        ]

    def overdrive_detail(self, match: MatchState, player_id: str) -> str:
        """
        The line a declared Overdrive adds to the dice image's modifier
        list, or "" -- the twin of `IgnitedRoll.detail`, and worded the
        same way so a coach reads one list of modifiers however they
        were earned.
        """
        modifier = match.overdrive_modifier(player_id)
        return f"+{modifier} Overdrive" if modifier else ""

    def slip_in_candidates(
        self, game: D12BallGame, match: MatchState,
    ) -> list[str]:
        """
        **Slip in**: the Oozes standing on the ball who may take the
        handler's turn from whoever the resolution left it with.

        Every one of them is already an eligible ball handler -- an
        Ooze on the ball's space, for the side in possession, is one by
        definition -- so this narrows that list rather than adding to
        it. `MatchState.turn_handler_candidates` is where it is spent.

        **"Of the same side" is `eligible_ball_handlers`' own
        answer**, which is what makes this safe on a space both sides
        are standing on: that helper is already "everyone of the
        possessing team on the ball", so an opponent's Ooze is never
        in it. The rules say the same thing twice for the same reason.

        It answers `[]` for the common case -- a resolution that named
        no carrier at all leaves the coach the whole choice already,
        and there is nothing to widen.
        """
        if not self.species_abilities_apply(game):
            return []
        if match.ball_carrier_id is None:
            return []
        return [
            player_id
            for player_id in match.eligible_ball_handlers()
            if self.has_species_ability(game, player_id, SPECIES_OOZE)
        ]

    def turn_handler_candidates(
        self, game: D12BallGame, match: MatchState,
    ) -> list[str]:
        """
        Who may take this turn, Slimey included -- the answer every
        prompt, the AI and the click that answers should ask, so none
        of them can offer a different list from the others.
        """
        return match.turn_handler_candidates(
            self.slip_in_candidates(game, match),
        )

    def mind_pull_candidates(
        self, game: D12BallGame, match: MatchState,
    ) -> list[str]:
        """
        The Telekinetics the ball just crossed who may try to pull it
        in, **in the order the ball reached them** -- which is the
        whole of "each may try in the order the ball reaches them; the
        first to succeed stops the ball there and the rest get no
        roll".

        Read off `match.last_ball_path`, which `set_ball_space`
        recorded, so this needs no argument beyond the match and
        answers the same way after a restart.

        Three things narrow it, and each is a sentence of the rule:

        - **The opposing side only.** "Only the opposing team's ball"
          -- a Telekinetic never pulls their own side's ball in, so
          this is the side *not* in possession at the moment the ball
          moved.
        - **Injured players are out**, because a pull costs an
          exhaustion token and an injured player cannot gain one. That
          is the ordinary rule reaching here rather than an exception:
          `add_exhaustion` would silently refuse, leaving a coach
          paying nothing for a free roll.
        - **One roll per Telekinetic per movement.** A player standing
          on two spaces of the path is impossible, but a path that
          doubles back is not worth relying on being impossible, so
          the list is de-duplicated.
        """
        if not self.species_abilities_apply(game):
            return []

        defending = match.defending_side()
        theirs = set(match.setup_for_side(defending).field_players)

        candidates: list[str] = []
        for zone_value, space_index in match.last_ball_path:
            for player_id in match.board.spaces[Zone(zone_value)][space_index]:
                if player_id not in theirs or player_id in candidates:
                    continue
                if player_id in match.injured:
                    continue
                if not self.has_species_ability(
                    game, player_id, SPECIES_TELEKINETIC,
                ):
                    continue
                candidates.append(player_id)
        return candidates

    def merge_bonus(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        rolling: Collection[Optional[str]],
        skill: str,
    ) -> tuple[int, list[str]]:
        """
        **Merge**: what the Oozes standing on the ball who are *not*
        rolling add to their own side's total, and the lines saying so.

        `skill` is "offense" or "defense" -- the rules split it by
        which side of the contest this is, not by anything about the
        Ooze: "their **offensive** skill on the attacking side, their
        **defensive** skill on the defending side". A score attempt
        asks for the attack alone, and passes "offense".

        **Every such Ooze adds** -- "two of them add twice" -- so this
        is a sum rather than a pick. An **injured** Ooze adds nothing,
        which is the ordinary rule about an injured player's skill
        modifier applying here rather than an exception to it.

        `rolling` is whoever is actually contesting, struck out because
        their own skill is already in the total; it is a collection so
        a score attempt can pass its shooter and a contest its two.
        """
        if not self.species_abilities_apply(game):
            return 0, []

        contesting = {player_id for player_id in rolling if player_id}
        total = 0
        lines: list[str] = []
        for player_id in match.contest_occupants(side):
            if player_id in contesting or player_id in match.injured:
                continue
            if not self.has_species_ability(game, player_id, SPECIES_OOZE):
                continue
            player = self.get_player_definition(player_id)
            profile = self.player_catalog.effective_profile(player)
            value = profile.offense if skill == "offense" else profile.defense
            if not value:
                continue
            total += value
            lines.append(f"+{value} {player.name} (Merge)")
        return total, lines

    def volatile_raises_tier(
        self,
        game: D12BallGame,
        winner: IgnitedRoll,
        loser: IgnitedRoll,
    ) -> bool:
        """
        Whether Volatile's tier rider fires on a settled maneuver skill
        test -- **the winner's maneuver resolves at its advanced
        version**.

        The rules name two cases and they are the same case. "A surge
        on the winning side resolves *that side's* maneuver as its
        advanced version"; "a backfire on the losing side resolves *the
        opponent's*" -- and the opponent of the losing side is the
        winning side. So both raise the winner's card, which is why
        `MatchState.volatile_tier_upgrade` is one flag and not a side.

        Gated on the advanced maneuvers as well as the species
        abilities: in a game that took one module without the other
        there is no tier to change and the ignite is only the number.
        Asking here rather than at the read is what lets
        `resolving_maneuver` stay a question about the match alone.
        """
        if not self.advanced_maneuvers_apply(game):
            return False
        return winner.surge or loser.backfire

    def volatile_loser_cost(
        self, game: D12BallGame, loser: IgnitedRoll,
    ) -> Optional[bool]:
        """
        What the losing side's own ignite does to the advanced cost
        they would otherwise pay -- the other half of Volatile's rider
        (the author, 2026-09-07).

        `False` where they **surged and lost**: they pay no cost even
        where the cards would have charged one. `True` where they
        **backfired and lost**: they pay theirs even where the cards
        alone would not, which makes a backfire the one thing in the
        game that puts a cost in force off the dice. `None` otherwise,
        leaving `advanced_cost_applies` the whole answer.

        Read from the losing player's own die rather than from the
        matchup, which is why this is separate from
        `volatile_raises_tier` rather than derivable from it: a surge
        that loses suppresses a cost *and* raises nothing, and a
        backfire that loses charges one *and* raises the opponent's
        card.

        Gated on the advanced maneuvers for the same reason the tier
        is: with no advanced cards in play there is no cost to change.
        """
        if not self.advanced_maneuvers_apply(game):
            return None
        if loser.surge:
            return False
        if loser.backfire:
            return True
        return None

    def maneuver_tiers(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> tuple[str, ...]:
        """
        Which tiers a coach may pick from **this turn** -- the whole of
        who holds which cards, asked in one place so the hand a coach
        is shown, the buttons built under it and the click that answers
        cannot disagree.

        Two things narrow it, and both are rules rather than settings:

        - **A basic game is the basic three**, and so is an advanced
          game that took the species abilities without this module --
          `advanced_maneuvers_apply` is both halves of that.
        - **An unchallenged maneuver is always basic** (the author):
          *"Advanced maneuver can only be played when a maneuver is
          challenged."* That is answerable here because all three
          routes into the unopposed branch settle it before the offense
          is prompted, so `maneuver_uncontested` is already set by the
          time a hand is drawn. It also makes declining a challenge a
          defensive weapon rather than only a saving -- sending nobody
          denies the offense their advanced cards.
        """
        if not self.advanced_maneuvers_apply(game) or match.maneuver_uncontested:
            return (MANEUVER_TIER_BASIC,)
        return (MANEUVER_TIER_BASIC, MANEUVER_TIER_ADVANCED)

    def maneuver_pick_sides(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> tuple[str, ...]:
        """
        Which sides the maneuver prompt has to offer buttons for --
        every side of this maneuver a **person** still picks for.

        Two things take a side off it, and both are settled before the
        prompt is ever built:

        - **An unchallenged maneuver has no defense to pick for.** There
          is no challenger and there never will be one, so the offense
          is the whole prompt.
        - **Dinky's side is picked before the prompt exists.**
          `D12Ball.begin_maneuver_action_selection` writes the AI's
          maneuver straight into the match and only then builds the
          prompt, so a solo game's prompt is one hand and one row of
          buttons.

        **It is read off persisted state alone**, which is what lets a
        restart rebuild the identical view: the prompt is never edited
        once it is up (see `D12Ball.close_maneuver_prompt`), so the
        buttons on the message and the buttons the restored view
        dispatches have to agree, and a side that has *already picked*
        must therefore keep its buttons. `ManeuverActionPromptView.pick`
        refuses the second click rather than the button being taken
        away.
        """
        sides = ["offense"]
        if not match.maneuver_uncontested:
            sides.append("defense")

        if game.is_solo_game:
            ai_side = (
                "offense"
                if self.possession_player_number(game, match) == 2
                else "defense"
            )
            sides = [side for side in sides if side != ai_side]

        return tuple(sides)

    def maneuver_hand(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
    ) -> tuple[ManeuverDefinition, ...]:
        """One side's playable cards this turn, in the order they read."""
        tiers = self.maneuver_tiers(game, match)
        return tuple(
            sorted(
                (
                    maneuver
                    for maneuver in self.maneuver_catalog.side(side)
                    if maneuver.tier in tiers
                ),
                key=lambda item: (
                    item.rank,
                    item.tier != MANEUVER_TIER_BASIC,
                ),
            )
        )

    def cards_outcome(self, match: MatchState) -> Optional[str]:
        """
        What the **cards** said, before any die was thrown:
        `"offense"`, `"defense"`, `"tie"` -- or None where there was no
        contest to decide.

        An unchallenged maneuver has no opposing card, so it answers
        None and every advanced effect falls away with it.
        """
        if match.maneuver_uncontested:
            return None
        if match.offense_maneuver is None or match.defense_maneuver is None:
            return None
        return self.maneuver_catalog.resolve(
            match.offense_maneuver, match.defense_maneuver,
        )

    def maneuver_side(
        self, match: MatchState, key: Optional[str],
    ) -> Optional[str]:
        """
        Which side played this card **in this match** -- `"offense"`,
        `"defense"`, or None where it is neither.

        Read off the match rather than off the card, because a
        `ManeuverDefinition` carries no side of its own: the catalog
        splits them by side, and the two questions below are about this
        matchup rather than about the card in general.
        """
        if key is None:
            return None
        if key == match.offense_maneuver:
            return "offense"
        if key == match.defense_maneuver:
            return "defense"
        return None

    def advanced_benefit_applies(
        self, match: MatchState, key: Optional[str],
    ) -> bool:
        """
        Whether this card carries its advanced **benefit** -- which is
        exactly "it won on the cards" (the author, 2026-09-07).

        **Not "the cards were decisive".** That was the shape this took
        until 2026-09-07, off the author's own 2026-08-19 wording, and
        it was imprecise in one case: a decisive matchup whose
        card-winner is injured is settled by a skill test, and the
        *other* side can win it. Their card lost on the cards, so it
        resolves basic -- where "the cards were decisive" would have
        handed it an advanced benefit it never earned.

        A tie is still the common case where nothing fires, but it is
        no longer the test.
        """
        side = self.maneuver_side(match, key)
        return side is not None and self.cards_outcome(match) == side

    def advanced_cost_applies(
        self, match: MatchState, key: Optional[str],
    ) -> bool:
        """
        Whether this card owes its advanced **cost** -- which is
        exactly "it lost on the cards" (the author, 2026-09-07), and
        the mirror of `advanced_benefit_applies`.

        The case this corrects: a player who **won** on the cards, was
        injured, and lost the forced skill test. Their card never lost
        on the cards, so it owes nothing -- where the old "the cards
        were decisive" reading charged them for a matchup they had
        actually won.

        Both readings the rules used to call out fall straight out of
        this and are not exceptions to it: an injured player's
        automatic loss of a tie carries nothing (nobody lost on the
        cards), and a skill test the cards did not tie carries whatever
        the cards themselves settled.
        """
        side = self.maneuver_side(match, key)
        if side is None:
            return False
        outcome = self.cards_outcome(match)
        return outcome in ("offense", "defense") and outcome != side

    def resolving_maneuver(self, match: MatchState, winner_key: str) -> str:
        """
        Which card's effect actually runs. It is the winner's own,
        except that an advanced card resolves at its own tier only
        where it **won on the cards** -- see
        `advanced_benefit_applies`. An advanced card that wins a tie,
        or that wins an injury-forced skill test the cards had gone
        against it, resolves as the basic card on its rank.

        **Volatile's tier rider is the one thing that raises a card
        here**, and it is read off `match.volatile_tier_upgrade`, which
        the skill test sets when the winner surged or the loser
        backfired. It beats the tie downgrade above -- the rules say
        "even where the cards tied and the basic card would otherwise
        resolve" -- and it only ever raises: a card already resolving
        at advanced gains nothing, which falls out of the counterpart
        of an advanced card being itself.

        The flag is already gated on both modules being in play (see
        `volatile_raises_tier`), so nothing here needs the game.

        **It raises the winner's card and nothing else.** The loser's
        cost is `advanced_cost`'s, which asks whether the *cards* were
        decisive -- an ignite decides a tier, not who won -- so a tie
        raised to advanced by a surge still carries no cost. That is
        the rules read literally: the rider speaks only to the card
        that resolves.
        """
        maneuver = self.maneuver_catalog.get(winner_key)
        if maneuver is None:
            return winner_key

        if match.volatile_tier_upgrade and not maneuver.is_advanced:
            return self.maneuver_catalog.counterpart(maneuver).key

        if not maneuver.is_advanced:
            return winner_key
        if match.volatile_tier_upgrade or self.advanced_benefit_applies(
            match, winner_key,
        ):
            return winner_key
        return self.maneuver_catalog.counterpart(maneuver).key

    def advanced_cost(
        self, match: MatchState, winner_key: str,
    ) -> Optional[str]:
        """
        The **losing** card's key, when that card is advanced and its
        cost is in force -- otherwise None.

        Each of the six costs is a rule the *opponent* gets to use, and
        every one of them bites somewhere inside the winning maneuver's
        own resolution rather than as a step after it: an unopposed Low
        Pass once a steal has landed, a turnover that skips the speed
        reset, a reception that is not contested. So there is no
        cost-tail dispatcher -- the winner's handler asks this what the
        card it just beat was, which is also the only place that knows
        where the cost belongs.
        """
        loser_key = match.opposing_maneuver(winner_key)
        loser = (
            self.maneuver_catalog.get(loser_key)
            if loser_key is not None
            else None
        )
        if loser is None or not loser.is_advanced:
            return None

        # **Volatile overrides the cards, both ways.** A surge that
        # lost pays nothing even where the card lost on the cards; a
        # backfire that lost pays even where it did not. Asked before
        # `advanced_cost_applies` because that is exactly what it
        # overrides -- see `volatile_loser_cost`.
        if match.volatile_loser_cost is False:
            return None
        if match.volatile_loser_cost is True:
            return loser.key

        if not self.advanced_cost_applies(match, loser.key):
            return None
        return loser.key

    def maneuver_name(self, key: Optional[str]) -> str:
        """What to print for a stored maneuver key."""
        return self.maneuver_catalog.display_name(key)

    def formation_shape(
        self,
        match: MatchState,
        formation: Formation,
    ) -> FormationShape:
        """
        A formation's counts on this match's board, which refuses a
        shape that board does not play -- see
        BasicRuleset.formations_for_board.
        """
        return self.basic_ruleset.formation_shape(
            formation, match.board.layout.board_size,
        )

    def available_formations(
        self,
        match: MatchState,
    ) -> dict[Formation, FormationShape]:
        """The shapes a coach may pick on this match's board."""
        return self.basic_ruleset.formations_for_board(
            match.board.layout.board_size
        )

    def initialize_standard_match(
        self,
        game: D12BallGame,
    ) -> MatchState:
        if not game.home_and_visiting_selected:
            raise ValueError(
                "Home and visiting teams must be selected first."
            )
        if game.player_1_team is None or game.player_2_team is None:
            raise ValueError("Both teams must be selected first.")

        home_team = (
            game.player_1_team
            if game.home_player_number == 1
            else game.player_2_team
        )
        visiting_team = (
            game.player_1_team
            if game.visiting_player_number == 1
            else game.player_2_team
        )
        match = MatchState.standard(
            catalog=self.player_catalog,
            ruleset=self.basic_ruleset,
            board_size=game.board_size,
            home_team=home_team,
            visiting_team=visiting_team,
        )
        game.ruleset_id = match.ruleset_id
        game.player_data_version = match.player_data_version
        game.match_state = match.to_dict()
        return match

    def load_match_state(self, game: D12BallGame) -> MatchState:
        if game.match_state is None:
            raise ValueError("This game does not have initialized match state.")
        match = MatchState.from_dict(
            game.match_state,
            self.basic_ruleset,
        )
        match.validate(self.player_catalog)
        return match

    def side_for_user(
        self,
        game: D12BallGame,
        user_id: int,
    ) -> Optional[TeamSide]:
        """
        Which side (home/visiting) a Discord user controls in this
        game, or None if they are not one of its two players, or the
        home/visiting assignment has not been made yet.
        """
        if not game.home_and_visiting_selected:
            return None

        if user_id == game.player_1_id:
            player_number = 1
        elif game.player_2_id is not None and user_id == game.player_2_id:
            player_number = 2
        else:
            return None

        if player_number == game.home_player_number:
            return TeamSide.HOME
        if player_number == game.visiting_player_number:
            return TeamSide.VISITING
        return None

    def get_player_definition(
        self,
        player_id: str,
    ) -> PlayerDefinition:
        return self.player_catalog.player_by_id(player_id)

    def possession_player_number(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        if match.ball.possession == TeamSide.HOME:
            return game.home_player_number
        return game.visiting_player_number

    def possession_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        player_number = self.possession_player_number(game, match)
        if player_number == 1:
            return game.player_1_id
        if player_number == 2:
            return game.player_2_id
        return None

    def user_controls_possession(
        self,
        user_id: int,
        game: D12BallGame,
        match: MatchState,
    ) -> bool:
        return self.possession_user_id(game, match) == user_id

    def defending_player_number(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        offense_number = self.possession_player_number(game, match)
        if offense_number == 1:
            return 2
        if offense_number == 2:
            return 1
        return None

    def defending_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> Optional[int]:
        player_number = self.defending_player_number(game, match)
        if player_number == 1:
            return game.player_1_id
        if player_number == 2:
            return game.player_2_id
        return None

    def user_controls_defense(
        self,
        user_id: int,
        game: D12BallGame,
        match: MatchState,
    ) -> bool:
        return self.defending_user_id(game, match) == user_id

    def get_ai_strategy(self, game: D12BallGame) -> AIStrategy:
        return self.ai_strategies[game.ai_opponent or AIOpponent.DINKY]

    def intervening_defenders(
        self,
        match: MatchState,
    ) -> list[ShotDefender]:
        """
        Every defending player between the ball and the goal it is
        being shot at, with the defensive skill they have and the part
        of it the shot is up against -- all of it on the ball's own
        space, half of it further along. `ShotDefender.value` is the
        rule; the roll and the image both read it rather than the raw
        skill, and neither may go back to summing `defense`.
        """
        defenders = []
        for player_id, on_ball in match.defenders_between_ball_and_goal():
            player = self.get_player_definition(player_id)
            defense = self.player_catalog.effective_profile(player).defense
            defenders.append(ShotDefender(player, defense, on_ball))
        return defenders

    def settled_maneuver_winner(self, match: MatchState) -> Optional[str]:
        """
        Which maneuver wins outright, or None when a skill test still
        has to decide it.

        This is the whole of who wins a maneuver, and the only place
        that ranking and the injured player's disadvantage are put
        together -- see "Injured players" under Exhaustion and injury
        in docs/living-rules.md. Three call sites ask it and none of
        them may re-derive the answer from
        `maneuver_catalog.resolve()` alone: injury both takes wins away
        (a decisive one owed to an injured player becomes a skill test)
        and hands them out (a tie against exactly one injured player is
        their automatic loss, with no test to roll), so the ranking on
        its own now disagrees with the turn in both directions. The two
        that reconstruct a prompt after a restart -- `on_ready` and
        `build_effect_choice_view` -- would otherwise restore a skill
        test nobody owes, or an effect choice for a test that hasn't
        been rolled.

        An uncontested maneuver wins whatever the offense picked, injured
        or not: there is no opponent to be disadvantaged against, and no
        challenge to lose. A tie where both participants are injured is
        an ordinary tie for the same reason -- the disadvantage is
        measured against a healthy opponent. Both are the author's
        (2026-08-09); see "The maneuver with nobody to challenge it" in
        CLAUDE.md.
        """
        if match.maneuver_uncontested:
            return match.offense_maneuver

        outcome = self.maneuver_catalog.resolve(
            match.offense_maneuver, match.defense_maneuver,
        )
        offense_injured = match.active_player_id in match.injured
        defense_injured = match.challenger_id in match.injured

        if outcome != "tie":
            winner_injured = (
                offense_injured if outcome == "offense" else defense_injured
            )
            if winner_injured:
                return None
            return (
                match.offense_maneuver
                if outcome == "offense"
                else match.defense_maneuver
            )

        if offense_injured == defense_injured:
            # Both or neither: no relative disadvantage, so an
            # ordinary tie.
            return None
        return (
            match.offense_maneuver
            if defense_injured
            else match.defense_maneuver
        )

    def controlling_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
    ) -> Optional[int]:
        """
        The Discord user controlling whichever team `player_id` belongs
        to, independent of ball possession -- safe to call right after
        a turnover flips possession, unlike possession_user_id.
        """
        side = (
            TeamSide.HOME
            if player_id in match.home.field_players
            else TeamSide.VISITING
        )
        number = (
            game.home_player_number
            if side == TeamSide.HOME
            else game.visiting_player_number
        )
        if number == 1:
            return game.player_1_id
        if number == 2:
            return game.player_2_id
        return None

    def side_controlled_by_ai(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
    ) -> bool:
        if not game.is_solo_game:
            return False
        number = (
            self.possession_player_number(game, match)
            if side == "offense"
            else self.defending_player_number(game, match)
        )
        return number == 2

    def low_pass_candidates(
        self,
        match: MatchState,
    ) -> list[tuple[int, str]]:
        """
        A Low Pass has at most three destinations, as (distance,
        receiver) pairs ordered back-to-front for display: the nearest
        teammate ahead of the ball within 2 spaces, the nearest one
        behind it within 2, and a teammate sharing the ball's own
        space. The ball can only be passed to a space someone is
        already standing on.

        **Nearest, not any.** A teammate 2 spaces ahead is no longer a
        destination when another one stands 1 space ahead -- each
        direction offers only the closest, so the choice is between
        directions rather than between distances (2026-08-07).

        **A pass has to reach a different player.** The ball handler
        can't pass to themselves to hold the ball, so distance 0 is a
        candidate only when a *second* offensive player is standing on
        the ball's space, and the receiver named for it is that other
        player. A handler with nobody within two spaces has no legal
        Low Pass at all -- see resolve_low_pass, which is where that
        case is handled rather than here.

        The receiver named here is only the *first* teammate on that
        space, which is all a destination button needs. Where more
        than one is standing there -- ordinary under a formation that
        stacks -- who actually receives the pass is the passer's
        choice: see low_pass_receivers.
        """
        offense_side = match.ball.possession
        offense_players = set(match.setup_for_side(offense_side).field_players)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )

        candidates: list[tuple[int, str]] = []
        # Each run stops at its first hit: the nearest teammate is the
        # only one that direction offers.
        for distances in ((-1, -2), (0,), (1, 2)):
            for distance in distances:
                receivers = self.low_pass_receivers(match, distance)
                if receivers:
                    candidates.append((distance, receivers[0]))
                    break
        return candidates

    def setup_pass_distances(self, match: MatchState) -> list[int]:
        """
        Which of Setup Pass's distances -- 0, 1 and 3, plus 4 for a
        Fullback -- the passer may pick out.

        **A distance is offered because it fits on the field, not
        because somebody is standing there** (the author, 2026-08-25).
        A pass landing on a space the passing side has nobody on is
        not a pass that never happened: the ball is picked out into
        that space and settles there exactly as a Deflect's does --
        loose if it is empty, the other side's outright if only they
        are there. Refusing those distances used to make the card
        unplayable from most of the field and turned a bad choice into
        no choice at all.

        **0 is the exception, and it is the only one.** It means "a
        teammate sharing the passer's own space", and a passer never
        receives their own pass (2026-08-12) -- so with nobody else
        standing there it is not a short pass into an empty space, it
        is the ball not being passed at all.

        With nothing left on the list the pass goes out; see
        `D12Ball.apply_setup_pass_out`. That needs the passer on the
        very last space of the field -- the only position from which
        even 1 runs off the end -- with no teammate beside them, which
        is the whole of when a Setup Pass can go out of play.

        **The Fullback's ability is +1 distance, and that is what it
        inherits** (the author, 2026-08-19). Its sentence reads "High
        pass up to 4", which read as a number is a fourth distance
        against a card that offers 0, 1 and 3 -- and read as the rule
        behind the number is the same +1 that takes a basic High Pass
        from 3 to 4 and a Clear from 3 to 4. The rule is what carries,
        so the extra distance is appended rather than replacing the 3.
        """
        offense_side = match.ball.possession
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )

        handler = self.get_player_definition(match.active_player_id)
        distances = list(SETUP_PASS_DISTANCES)
        if handler.role == PlayerRole.FULLBACK:
            distances.append(SETUP_PASS_FULLBACK_DISTANCE)

        legal = []
        for distance in distances:
            if distance == 0:
                # `high_pass_receivers_at` is the passing side on that
                # space less the passer, which is exactly what 0 asks.
                if match.high_pass_receivers_at(offense_side, 0):
                    legal.append(0)
                continue
            target_flat = match.relative_flat_index(
                origin_flat, offense_side, distance,
            )
            # Off the end of the field: a clamped throw is a shorter
            # pass wearing a longer one's label, which is the reason
            # `high_pass_distances` drops one too.
            if abs(target_flat - origin_flat) != distance:
                continue
            legal.append(distance)
        return legal

    def double_team_partner(self, match: MatchState) -> Optional[str]:
        """
        The teammate a Double Team brings in with the challenger: the
        defending player, other than the challenger, standing nearest
        the ball.

        **Nearest the ball, which is where the play started.** The card
        says "closest to the space where the play started", and by the
        time a maneuver resolves the ball has not moved yet -- the
        challenger was walked onto it and the handler is still standing
        there. So `distance_to_ball` is that measurement rather than an
        approximation of it. Ties break on `field_players` order, the
        way every other list a coach could be offered does, so the same
        question asked twice comes back the same way.

        None when the defending side has nobody else on the field,
        which `validate()` makes unreachable from a game that loads --
        the branch is a guard, not a state.
        """
        defense = match.setup_for_side(match.defending_side())
        candidates = [
            player_id
            for player_id in defense.field_players
            if player_id != match.challenger_id
            and match.board.meeple_position(player_id) is not None
        ]
        if not candidates:
            return None
        return min(candidates, key=match.distance_to_ball)

    def double_team_defenders(self, match: MatchState) -> list[str]:
        """
        Everyone challenging this maneuver: the challenger, and the
        second defender a Double Team left on the ball last time.
        Ordered challenger-first, so the skill test reads as one
        defender with help rather than as a pair with no lead.

        Empty of the second whenever a Double Team is not in force,
        which is nearly always -- `pending_double_team` is set by one
        card and cleared by a new play.
        """
        defenders = [match.challenger_id] if match.challenger_id else []
        for player_id in match.pending_double_team:
            if (
                player_id not in defenders
                and player_id in match.setup_for_side(
                    match.defending_side()
                ).field_players
            ):
                defenders.append(player_id)
        return defenders

    def pass_speed_bonus(self, maneuver_key: str) -> int:
        """
        What a pass adds to ball speed: Low Pass's +1, or Skilled
        Pass's +3. Both are capped at 12 by the caller, the way every
        speed change is.
        """
        return 3 if maneuver_key == "skilled_pass" else 1

    def skilled_pass_candidates(
        self,
        match: MatchState,
    ) -> list[tuple[int, str]]:
        """
        Skilled Pass's destinations: **any** teammate within
        `SKILLED_PASS_REACH` spaces either way, as (distance,
        receiver) pairs ordered back-to-front, rather than the nearest
        one each way within two spaces.

        That is the whole of what the card buys over a Low Pass -- a
        teammate the nearest-each-way rule hides, and one space more
        of it -- so it is written as the same shape:
        `LowPassChoiceView`, the receiver pick behind it and `DinkyAI`
        all read whichever list `pass_candidates` hands them and
        cannot tell the two apart.

        **The reach is a number now, and it used to be the board.** The
        card was Precise Pass and read "any teammate", which on board
        9 is a pass eight spaces across the whole field; the author
        bounded it at 3 and renamed it on 2026-08-26. Distances that
        run off the end are dropped by `low_pass_receivers`, so a
        short board narrows this without the reach knowing about it.
        """
        candidates: list[tuple[int, str]] = []
        for distance in range(-SKILLED_PASS_REACH, SKILLED_PASS_REACH + 1):
            receivers = self.low_pass_receivers(match, distance)
            if receivers:
                candidates.append((distance, receivers[0]))
        return candidates

    def dribble_burst_distances(self, match: MatchState) -> list[int]:
        """
        How far a Dribble Burst may be run: 1 up to
        `DRIBBLE_BURST_MAX_DISTANCE`, cut short by the field. It is
        the coach's pick, and it is charged a token a space -- which
        is what makes the shorter runs worth offering.

        **It used to be no choice at all.** The card ran the handler
        to the last space of the goal they attack, so the distance was
        read off the board and the only thing the coach settled was
        the ball speed after it. The author bounded the run at 4 on
        2026-08-26; a burst from deep now stops short of the goal, and
        a burst from inside 4 spaces of the end still reaches it.

        Empty from the last space of the field itself, which is the
        one position with nothing to ask -- `resolve_dribble_burst`
        applies a run of 0 rather than putting up a menu with no
        buttons on it. The Playmaker's ability is deliberately not
        here: it is a token off the cost, not a space onto the run
        (the author, 2026-08-19), so it does not change what is
        offered.
        """
        reach = min(
            DRIBBLE_BURST_MAX_DISTANCE,
            match.spaces_to_attacking_end(
                match.active_player_id, match.ball.possession,
            ),
        )
        return list(range(1, reach + 1))

    def pass_candidates(
        self,
        match: MatchState,
        maneuver_key: Optional[str] = None,
    ) -> list[tuple[int, str]]:
        """
        The destinations the pass being resolved actually offers --
        Skilled Pass's any-teammate-within-3, or a Low Pass's nearest
        each way. Asked in one place so the buttons, the AI and the
        click that answers cannot disagree about what was on offer.
        """
        if maneuver_key is None:
            maneuver_key = self.resolving_maneuver(
                match, match.offense_maneuver,
            ) if match.offense_maneuver else None
        if maneuver_key == "skilled_pass":
            return self.skilled_pass_candidates(match)
        return self.low_pass_candidates(match)

    def low_pass_receivers(
        self,
        match: MatchState,
        distance: int,
    ) -> list[str]:
        """
        Every teammate a Low Pass of `distance` could be played to --
        the offensive players standing on that space, minus the
        handler, who cannot pass to themselves.

        Usually one, and then the destination *is* the choice. A
        formation that stacks (2-3-1 or 1-3-2 on a six-space board)
        makes two ordinary, and which of them receives the ball is the
        passer's to pick: it decides who a Winger's set-up hands the
        shot to. Empty when the distance runs off the end of the
        board, or when the space holds nobody but the handler.
        """
        offense_side = match.ball.possession
        offense_players = set(match.setup_for_side(offense_side).field_players)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, distance,
        )
        # relative_flat_index() clamps to the board edge -- if that
        # shortened the move, this distance doesn't reach an actual
        # space and isn't a candidate.
        if abs(target_flat - origin_flat) != abs(distance):
            return []

        zone, space_index = match.board.position_at_flat_index(target_flat)
        return [
            player_id
            for player_id in match.board.spaces[zone][space_index]
            if player_id in offense_players
            and player_id != match.active_player_id
        ]

    def high_pass_distance_options(self, match: MatchState) -> list[int]:
        """
        The distances this High Pass may be thrown at: the handler's
        maximum -- 4 for a Fullback, 3 for everyone else -- less any
        that run out of field. Empty when even the shortest does,
        which is the overshoot-before-anyone-chooses case.

        One home for both halves of that, because three things have to
        agree about what is on offer: the menu a coach sees, what the
        AI picks from, and the refusal that catches a click on a menu
        the ball has moved out from under.
        """
        handler = self.get_player_definition(match.active_player_id)
        max_distance = 4 if handler.role == PlayerRole.FULLBACK else 3
        return match.high_pass_distances(match.ball.possession, max_distance)

    def high_pass_receiver_candidates(
        self,
        match: MatchState,
        offense_side: TeamSide,
    ) -> list[str]:
        """
        Who a High Pass reached: the offense on the space it landed
        on, less the passer -- **a passer never receives their own
        pass** (2026-08-12). See "High Pass" in the living rules.

        It is the one reading of that, asked by the overshoot's
        set-up, the ordinary 2-space one, and the long-pass contest
        behind both. They have to agree: the receiver who fights to
        keep the ball is the same player the shot was offered to, and
        the occupant list is in no particular order.

        **The exclusion can only ever bite on a pass the field clamped
        to 0 spaces**, since a High Pass moves the ball and not the
        handler -- that is the only way the passer is still standing on
        it when it lands. It is written as a rule about every High Pass
        rather than about that one case so a later maneuver that moves
        a handler cannot reopen the hole quietly. With nobody else on
        the space the pass reaches no one: not a loose ball, since the
        offense is standing on it, and not a contest either.

        Distinct from `scoring_opportunity_candidates`, which this
        reads and which still means "everyone of that side on the
        ball" -- Deflect's set-up asks it about the *defense*,
        where the passer exclusion would mean nothing.
        """
        return [
            player_id
            for player_id in self.scoring_opportunity_candidates(
                match, offense_side,
            )
            if player_id != match.active_player_id
        ]

    def scoring_opportunity_candidates(
        self,
        match: MatchState,
        offense_side: TeamSide,
    ) -> list[str]:
        """
        Offensive players occupying the ball's current (overshot)
        space -- the field of shooter candidates a set-up offers,
        shared by High Pass and a Winger's Low Pass.
        """
        offense_setup = match.setup_for_side(offense_side)
        occupants = match.board.spaces[match.ball.zone][
            match.ball.space_index
        ]
        return [
            player_id
            for player_id in occupants
            if player_id in offense_setup.field_players
        ]

    def loose_ball_candidates(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        Who `side` puts up for a loose ball. It is one of two pools and
        never a mixture of them -- the same shape as
        MatchState.challenge_candidates, and for the same reason.

        **Whoever of theirs is standing on the ball contests it**, for
        nothing, and a side with somebody there may not withhold them
        (may_decline_loose_ball). Only a side with nobody there sends
        anyone, from the nearest either side of the space
        (MatchState.contest_candidates). Where a side has several
        standing there the coach picks between them -- the author,
        2026-08-18, the same call as the maneuver challenge's.

        The passer is struck out of the offense's pool in a High Pass
        contest -- see MatchState.loose_ball_occupants, which is the one
        reading of who is standing on the ball here.

        A side with nobody fielded at all puts nobody up, which is not
        a failure state. resolve_loose_ball takes it from there.
        """
        return (
            match.loose_ball_occupants(side)
            or match.contest_candidates(side)
        )

    def loose_ball_sides_ready(
        self,
        match: MatchState,
    ) -> tuple[bool, bool]:
        """
        Whether the offense/defense pick is settled -- made, declined,
        or moot because that side has nobody left to send at all.
        """
        offense_ready = (
            match.loose_ball_offense_player is not None
            or match.loose_ball_offense_declined
            or not self.loose_ball_candidates(match, match.ball.possession)
        )
        defense_ready = (
            match.loose_ball_defense_player is not None
            or match.loose_ball_defense_declined
            or not self.loose_ball_candidates(match, match.defending_side())
        )
        return offense_ready, defense_ready

    def auto_resolve_loose_ball_picks(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> None:
        """
        Settle whichever side can't get a real human choice, i.e. is
        AI-controlled. A side with no candidates at all is left unset
        -- resolve_loose_ball reads that as "nobody available", not
        "still deciding".

        A lone candidate is *not* auto-picked, unlike a forced run
        back: sending them is optional, and declining is what puts the
        ball out of bounds, so one candidate is still a real choice
        between two outcomes.

        **A lone player standing on the ball is**, because there is
        nothing to ask: they contest for nothing and their side may not
        withhold them, so the only choice a prompt could offer is one
        the rules refuse. Two is the coach's pick, the same count-not-a-
        flag reading choose_action makes of automatic_challengers.
        """
        for side, skill_type, choose in (
            (
                match.ball.possession,
                "offense",
                match.choose_loose_ball_offense_player,
            ),
            (
                match.defending_side(),
                "defense",
                match.choose_loose_ball_defense_player,
            ),
        ):
            picked, declined = (
                (match.loose_ball_offense_player,
                 match.loose_ball_offense_declined)
                if skill_type == "offense"
                else (match.loose_ball_defense_player,
                      match.loose_ball_defense_declined)
            )
            if picked is not None or declined:
                continue

            on_the_ball = match.loose_ball_occupants(side)
            if len(on_the_ball) == 1:
                choose(on_the_ball[0])
                continue

            candidates = self.loose_ball_candidates(match, side)
            if not candidates:
                continue
            if self.side_controlled_by_ai(game, match, skill_type):
                # The AI always contests -- it has no decline policy,
                # and going out of bounds by choice is never obviously
                # right (see d12ball/ai.py).
                choose(
                    self.get_ai_strategy(game).choose_loose_ball_player(
                        match, candidates, skill_type,
                    )
                )

    def loose_ball_side_on_the_clock(
        self,
        match: MatchState,
    ) -> Optional[str]:
        """
        Which side still owes a pick, "offense" or "defense" -- or
        None when the contest is settled either way.

        The side that last held possession chooses first and alone.
        Both used to be offered at once, which handed whoever clicked
        second the other's answer to decide against; a loose ball is
        theirs to lose, so they commit first.
        """
        offense_ready, defense_ready = self.loose_ball_sides_ready(match)
        if not offense_ready:
            return "offense"
        if not defense_ready:
            return "defense"
        return None

    def build_loose_ball_headline(self, match: MatchState) -> str:
        """
        How the ball's arrival is announced, read off the position
        rather than off what made it. Three positions, three different
        questions to the two coaches -- and **only the first of them is
        a loose ball** (the author, 2026-08-26).

        It is asked before anybody has been sent, which is the only
        moment the space still holds what the ball came down on.
        A High Pass never reaches here: it carries its own headline,
        because the ball is on a receiver both coaches watched catch
        it.

        **Each one says what the position is, never what it is not**
        (the author, 2026-08-27). The one-side case led with "**Not
        loose.**" and closed with "nobody may be sent after it", which
        is two ways of saying the same thing wrong: the first is a
        sentence fragment defining the position by the one it is not,
        and the second answers a question no coach had asked -- nothing
        in the message had offered a send. The subject is spelled out
        for the same reason. "It comes down..." followed a sentence
        about the maneuver, so the pronoun read as the maneuver rather
        than the ball.
        """
        offense = match.setup_for_side(match.ball.possession)
        defense = match.setup_for_side(match.defending_side())
        offense_there = bool(match.loose_ball_occupants(match.ball.possession))
        defense_there = bool(
            match.loose_ball_occupants(match.defending_side())
        )

        if not offense_there and not defense_there:
            return (
                "**Loose ball!** The ball comes down on an empty space, "
                "so each side may send a nearby player after it."
            )
        if offense_there and defense_there:
            return (
                "**Contest!** The ball comes down to a space where both "
                "teams have a player, so those two roll for it."
            )
        taking = offense if offense_there else defense
        return (
            "The ball comes down to a space where "
            f"{format_team_side_label(taking)} has a player, so they get "
            "the ball."
        )

    def loose_ball_prompt_side(self, match: MatchState) -> TeamSide:
        """The board side whose turn it is to pick."""
        return (
            match.ball.possession
            if self.loose_ball_side_on_the_clock(match) == "offense"
            else match.defending_side()
        )

    def side_is_ai(
        self,
        game: D12BallGame,
        side: TeamSide,
    ) -> bool:
        if not game.is_solo_game:
            return False
        return self.side_player_number(game, side) == 2

    def side_player_number(
        self,
        game: D12BallGame,
        side: TeamSide,
    ) -> int:
        return (
            game.home_player_number
            if TeamSide(side) == TeamSide.HOME
            else game.visiting_player_number
        )

    def side_controller_id(
        self,
        game: D12BallGame,
        side: TeamSide,
    ) -> Optional[int]:
        """
        The Discord user coaching `side`. Unlike controlling_user_id
        this needs no player card, so it can be asked about a side
        that has nobody selected -- which is the case throughout a
        substitution window.
        """
        number = self.side_player_number(game, side)
        if number == 1:
            return game.player_1_id
        if number == 2:
            return game.player_2_id
        return None

    def substitution_allowance_label(self, match: MatchState) -> str:
        """
        What the open window has left, for a button label or a prompt.
        Setup has no limit at all, which is not the same as a large
        number and reads differently.
        """
        remaining = match.substitutions_remaining()
        if remaining is None:
            return "No substitution limit"
        if not remaining:
            return "No substitutions left"
        return (
            f"{remaining} substitution"
            f"{'s' if remaining != 1 else ''} left"
        )

    def defense_ordered_field_players(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        A side's six, best defender first. Ties break at random, which
        never happens between the six standard roles -- their defences
        are 1 to 6 -- but a shuffled tie is better than one settled by
        whatever order the zones happened to be in.
        """
        players = list(match.setup_for_side(side).field_players)
        random.shuffle(players)
        return sorted(
            players,
            key=lambda player_id: -self.player_catalog.effective_profile(
                self.get_player_definition(player_id)
            ).defense,
        )

    def formation_placement(
        self,
        match: MatchState,
        side: TeamSide,
        formation: Formation,
    ) -> list[tuple[str, Zone, int]]:
        """
        Where a side's six stand after switching to `formation`: the
        whole line-up, cards and spaces together, dealt by defensive
        skill from the coach's own goal forward -- see "Changing
        formation" in docs/living-rules.md.

        This is the whole of what a formation change asks of a coach.
        It used to put each zone's cards to them one select at a time,
        six picks to change shape; a coach who wants a particular card
        somewhere particular now moves it afterwards, with zone
        assignment and space positioning.
        """
        side = TeamSide(side)
        shape = self.formation_shape(match, formation)
        ordered = self.defense_ordered_field_players(match, side)

        placement: list[tuple[str, Zone, int]] = []
        cursor = 0
        for area in SETUP_AREAS:
            count = shape.count(area)
            zone = zone_for_area(side, area)
            spaces = formation_space_order(
                side, zone, len(match.board.spaces[zone]), count,
            )
            for offset in range(count):
                placement.append(
                    (ordered[cursor + offset], zone, spaces[offset])
                )
            cursor += count
        return placement

    def current_formation(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> Optional[Formation]:
        """
        The formation a side is standing in, or None for a shape no
        formation describes -- which /coach and /ref can leave behind,
        since they move cards one at a time and answer to nothing.

        Only the shapes this board plays are candidates, so a side
        pushed by hand into a shape their board does not offer reads as
        no shape at all rather than as one the Formation button would
        refuse.
        """
        setup = match.setup_for_side(side)
        counts = {
            area: len(setup.zones[zone_for_area(side, area)])
            for area in SETUP_AREAS
        }
        for formation, shape in self.available_formations(match).items():
            if shape.counts() == counts:
                return formation
        return None

    def substitution_button_label(self, match: MatchState) -> str:
        """
        The bracket on the hub's Substitution button. Which allowance
        is being counted down is worth saying: halftime's two and full
        time's one are their own rather than either half's, and setup
        has no limit at all.
        """
        remaining = match.substitutions_remaining()
        if remaining is None:
            return "no limit"
        if not remaining:
            return "none left"
        where = {
            CoachingOccasion.HALFTIME: "at halftime",
            CoachingOccasion.FULL_TIME: "before the shootout",
        }.get(match.coaching_occasion, "this half")
        return f"{remaining} left {where}"

    def run_back_displaced(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        The players of `side` a run back moves whether anybody likes it
        or not: `match.displaced_players(side)`, everyone standing
        outside their own zone, less the player holding the ball (see
        begin_run_back). Each of them has to come back, so the only
        question left is which space.
        """
        stays_player_id = match.pending_run_back_stays_player_id
        return [
            player_id
            for player_id in match.displaced_players(side)
            if player_id != stays_player_id
        ]

    def run_back_crowded(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        The players of `side` a stack could send back --
        `match.crowded_candidates(side)`, which offers every teammate
        on a shared space rather than picking one, because which of
        them goes is the coach's call.
        """
        return match.crowded_candidates(side)

    def run_back_movers(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        Everyone this side's run back still has to account for --
        those who must return and those a stack may send. Asked to
        find out whether a run back has anything to do at all; which
        of them moves next is next_run_back_step's.
        """
        return (
            self.run_back_displaced(match, side)
            + self.run_back_crowded(match, side)
        )

    def charge_up_players(
        self, game: D12BallGame, match: MatchState,
    ) -> list[str]:
        """
        Every Cyborg on the field who **did not move** during the run
        back that has just finished -- Lithium Powered's Charge-up, one
        drain token off each.

        **It is about movement, not about being obliged to move** (the
        author, 2026-09-07): *"any player that moves is running back.
        Charging up only occurs when a player does not move during
        run-back."* So this reads `match.run_back_moved`, which
        `run_back_player` fills in as it places people, rather than
        asking who was displaced.

        That distinction is the whole of what a stack decides. A player
        outside their own zone has to return and can never charge up; a
        player already in their own zone charges up unless something
        moved them anyway -- and where several share a space and one of
        them must go, **the one the coach sends loses their token and
        the one left keeps theirs**. Holding a Cyborg still is a real
        reason to send somebody else.

        This is also why it can only be asked once the run back is
        over. It was first built at `begin_run_back`, off
        `run_back_displaced`, which charged up both players of a stack
        whichever one the coach then sent.

        It answers with the ids rather than charging them, so the
        caller can word the result and save in its own breath; the
        removal itself is `MatchState.recover_exhaustion`.
        """
        if not self.species_abilities_apply(game):
            return []

        moved = set(match.run_back_moved)
        charged: list[str] = []
        for side in (TeamSide.HOME, TeamSide.VISITING):
            for player_id in match.setup_for_side(side).field_players:
                if player_id in moved:
                    continue
                if not self.has_species_ability(
                    game, player_id, SPECIES_CYBORG,
                ):
                    continue
                # Never below zero, and nothing to say for a Cyborg
                # carrying none -- see "A move that costs nothing says
                # nothing" in CLAUDE.md.
                if match.exhaustion.get(player_id, 0) <= 0:
                    continue
                charged.append(player_id)
        return charged

    def apply_forced_run_backs(
        self, game: D12BallGame, match: MatchState,
    ) -> None:
        """
        Place every run-back that isn't a choice: a zone whose open
        spaces exactly match the players who need one has only one
        arrangement, so nobody is asked. Repeats until a pass changes
        nothing, since placing one zone's players can settle another.

        A stack is counted in only where it has nothing to decide --
        one candidate, which means the other player on the space is
        holding the ball. A stack with two of them to choose between
        is the coach's (see `crowded_candidates`), so it is left out
        of the arithmetic entirely rather than being zipped into a
        space: the displaced players of that zone may still be forced
        around it, and settling them can take the zone's last open
        space and leave the stack alone after all.

        Silent, and it does not save -- the caller does both.
        """
        applied_forced = True
        while applied_forced:
            applied_forced = False
            for side in (TeamSide.HOME, TeamSide.VISITING):
                setup = match.setup_for_side(side)
                by_zone: dict[Zone, list[str]] = {}
                for player_id in self.run_back_displaced(match, side):
                    by_zone.setdefault(
                        setup.assigned_zone(player_id), [],
                    ).append(player_id)

                settled: dict[Zone, list[str]] = {}
                for player_id in self.run_back_crowded(match, side):
                    settled.setdefault(
                        setup.assigned_zone(player_id), [],
                    ).append(player_id)

                for zone in Zone:
                    players = list(by_zone.get(zone, []))
                    from_stack = settled.get(zone, [])
                    if len(from_stack) == 1:
                        players += from_stack
                    if not players:
                        continue

                    open_spaces = match.open_spaces_in_zone(side, zone)
                    if len(open_spaces) != len(players):
                        continue
                    for player_id, space_index in zip(players, open_spaces):
                        distance = match.run_back_player(
                            player_id, zone, space_index,
                        )
                        match.add_exhaustion(player_id, distance)
                        # A forced run back is applied silently, so
                        # there is no message here to carry the
                        # threshold test the way apply_exhaustion's
                        # does -- but the flag still has to be set
                        # before the caller's save.
                        self.retest_exhausted(game, match, player_id)
                    applied_forced = True

    def next_run_back_step(
        self,
        match: MatchState,
    ) -> Optional[tuple[TeamSide, list[str]]]:
        """
        The next side owed a run-back with a real choice in it, and the
        players that choice is between -- home before visiting, or None
        when both sides are settled.

        **One name or several, and the difference is what is being
        asked.** One means the player is settled and only the space is
        open: everyone standing outside their zone has to come back,
        and so does the one player a stack can spare when the other is
        holding the ball. Several means a stack has to send somebody
        and the coach picks which of them goes (the author, 2026-08-17)
        -- the space question follows once they have.

        Those who must return are answered before any stack, because a
        player coming home covers a space, and a zone with no space
        left uncovered has no stack to break up.
        """
        for side in (TeamSide.HOME, TeamSide.VISITING):
            displaced = self.run_back_displaced(match, side)
            if displaced:
                return side, [displaced[0]]
            crowded = self.run_back_crowded(match, side)
            if crowded:
                return side, crowded
        return None

    def next_setup_stage(self, match: MatchState) -> None:
        stage = match.pending_setup_stage
        if stage not in SETUP_STAGES:
            match.pending_setup_stage = None
            return
        index = SETUP_STAGES.index(stage)
        match.pending_setup_stage = (
            SETUP_STAGES[index + 1]
            if index + 1 < len(SETUP_STAGES)
            else None
        )

    @staticmethod
    def halftime_stage(match: MatchState) -> Optional[str]:
        """
        The stage a match is at, with a stage saved under the old
        sequence translated -- see LEGACY_HALFTIME_STAGES.
        """
        stage = match.pending_halftime_stage
        return LEGACY_HALFTIME_STAGES.get(stage, stage)

    def next_halftime_stage(self, match: MatchState) -> None:
        """
        Advance `match.pending_halftime_stage` to the next entry in
        HALFTIME_STAGES, or clear it once the sequence is exhausted.
        Callers are responsible for saving the match afterward.
        """
        stage = self.halftime_stage(match)
        if stage not in HALFTIME_STAGES:
            match.pending_halftime_stage = None
            return
        index = HALFTIME_STAGES.index(stage)
        match.pending_halftime_stage = (
            HALFTIME_STAGES[index + 1]
            if index + 1 < len(HALFTIME_STAGES)
            else None
        )

    def next_full_time_stage(self, match: MatchState) -> None:
        stage = match.pending_full_time_stage
        if stage not in FULL_TIME_STAGES:
            match.pending_full_time_stage = None
            return
        index = FULL_TIME_STAGES.index(stage)
        match.pending_full_time_stage = (
            FULL_TIME_STAGES[index + 1]
            if index + 1 < len(FULL_TIME_STAGES)
            else None
        )

    def shootout_running_score(self, match: MatchState) -> str:
        """
        The shootout's own score, which is not the scoreboard's: the
        goals are on that too, but 6:5 says nothing about how many of
        the six have gone.
        """
        home = match.shootout_goals_for(TeamSide.HOME)
        visiting = match.shootout_goals_for(TeamSide.VISITING)
        return (
            f"{team_display_name(match.home.team)} {home} — {visiting} "
            f"{team_display_name(match.visiting.team)}"
        )

    def shootout_heading(self, match: MatchState) -> str:
        """
        Where the shootout has got to, above the test it is asking
        for. **Only ever a question, never an answer**: the test
        number it names is the one about to be rolled, and by the time
        a result is posted the shooters have been retired and that
        number has moved on -- so a result carries the running score
        alone (see ShootoutTestView.roll).
        """
        if match.shootout_round > 1:
            where = f"sudden death, round {match.shootout_round}"
        else:
            taken = match.shootout_tests_taken(TeamSide.HOME)
            where = f"skill test {taken + 1} of 6"

        return (
            f"### Extreme shootout — {where}\n"
            f"{self.shootout_running_score(match)}"
        )

    def exhaustion_threshold(
        self, game: D12BallGame, player_id: str,
    ) -> int:
        """
        The token count a player's own must **exceed** to be
        Exhausted -- their defensive skill, or a Cyborg's flat Drained
        line.

        **A Cyborg's tokens are drain**, gained and spent exactly as
        exhaustion tokens, and the only thing that differs is where the
        line sits: Drained at 7 or more, whatever their defensive
        skill. `mark_exhausted_if_needed` marks on *greater than*, so
        the threshold that produces "7 or more" is 6 -- which is why
        this returns `CYBORG_DRAINED_AT - 1` rather than the constant
        itself, and why the arithmetic is done here once instead of at
        the two call sites.

        It is a large durability gain for the low-defence roles: a
        Cyborg striker is Exhausted at 2 normally and is fine until 7.
        That is the author's, and the reason the ability is worth a
        module.
        """
        if self.has_species_ability(game, player_id, SPECIES_CYBORG):
            return CYBORG_DRAINED_AT - 1
        player = self.get_player_definition(player_id)
        return self.player_catalog.effective_profile(player).defense

    def retest_exhausted(
        self, game: D12BallGame, match: MatchState, player_id: str,
    ) -> bool:
        """
        Re-test a player's Exhausted flag against their own threshold.
        True only on the transition, so callers can announce it once.

        `MatchState` deliberately does not carry the skill the
        threshold is measured against, so this test can only happen up
        here -- which is exactly why it has to run before the state is
        written out. See `apply_exhaustion`.

        It takes the `game` since the threshold is a Cyborg's own in a
        game playing the species abilities. Passing the *game* rather
        than reading a flag off the match is deliberate: the modules a
        game is playing are the game record's, and a copy of them on
        the match would be a second thing that can disagree.
        """
        return match.mark_exhausted_if_needed(
            player_id,
            self.exhaustion_threshold(game, player_id),
        )

    def roster_setups_for_user(
        self,
        game: D12BallGame,
        match: MatchState,
        user_id: int,
        all_teams: bool = False,
    ) -> Optional[list[TeamSetup]]:
        """
        Whose rosters `user_id` gets to see: their own team's by
        default, both when they asked for both or when they are running
        both sides of a test game, and None when they are not playing
        this game at all -- callers turn that into an explanation.
        """
        if all_teams or (game.test_game and user_id == game.player_1_id):
            return [match.home, match.visiting]
        side = self.side_for_user(game, user_id)
        if side is None:
            return None
        return [match.setup_for_side(side)]

    def high_pass_destination_note(
        self, match: MatchState, distance: int,
    ) -> str:
        """
        What a pass of `distance` would find waiting, for the
        HighPassChoiceView and SetupPassChoiceView buttons -- the space
        it lands on plus the first teammate standing there, or that
        there is none. A coach choosing a distance is choosing a
        destination, and "3 spaces" alone does not say whether anybody
        of theirs is there to catch it.

        **The space is named either way.** A pass nobody is standing
        under still lands somewhere, and where it lands is what decides
        whether it comes back -- a Setup Pass into an empty space is
        loose and one into a space only the defense holds is simply
        theirs, so "no teammate" on its own withholds the half of the
        answer the coach is weighing.
        """
        offense_side = match.ball.possession
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, distance,
        )
        zone, space_index = match.board.position_at_flat_index(target_flat)
        offense_players = set(
            match.setup_for_side(offense_side).field_players,
        )
        occupants = [
            player_id
            for player_id in match.board.spaces[zone][space_index]
            if player_id in offense_players
            and player_id != match.active_player_id
        ]
        if not occupants:
            return f"{space_label(zone, space_index)}, no teammate"
        teammate = self.get_player_definition(occupants[0])
        role_initial = ROLE_INITIALS[teammate.role.value]
        return (
            f"{space_label(zone, space_index)}-{teammate.name} "
            f"[{role_initial}]"
        )

    def build_loose_ball_prompt(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        """
        Who is being asked, and for what.

        It names the space as well as the contest, because this prompt
        outlives the message that announced it: `/d12ball resume` puts
        it back up on its own, and a restart re-arms it wherever it is
        in the channel.
        """
        skill_type = self.loose_ball_side_on_the_clock(match)
        number = (
            self.possession_player_number(game, match)
            if skill_type == "offense"
            else self.defending_player_number(game, match)
        )
        mention = format_player_with_team(game, number, mention=True)
        noun = contest_noun(match)
        where = ball_space_label(match)
        side = self.loose_ball_prompt_side(match)
        # A coach with several of theirs standing on the ball is
        # picking which one contests, not whether to send anybody --
        # the wording follows the button that is actually there (see
        # LooseBallChoiceView).
        if not match.may_decline_loose_ball(side):
            return (
                f"{mention}, more than one of yours is standing on the "
                f"{noun} on {where} -- choose which of them contests it:"
            )
        if skill_type == "offense":
            return (
                f"{mention}, you had the ball -- send the nearest player "
                f"either side of the {noun} on {where}, or send nobody:"
            )
        return (
            f"{mention}, choose who contests the {noun} on {where}, "
            "or send nobody:"
        )

    def apply_formation(
        self,
        match: MatchState,
        side: TeamSide,
        formation: Formation,
    ) -> str:
        """Switch a side into `formation` and describe where they land."""
        side = TeamSide(side)
        placement = self.formation_placement(match, side, formation)
        match.deploy_side(side, placement)

        setup = match.setup_for_side(side)
        board_size = match.board.layout.board_size
        lines = [
            f"**{format_team_side_label(setup)} switch to "
            f"{formation.value}.** Best defenders furthest back; "
            "rearranging costs no exhaustion."
        ]
        for area in SETUP_AREAS:
            zone = zone_for_area(side, area)
            names = ", ".join(
                f"{self.format_roster_player(player_id)} "
                f"({space_label(zone, space_index)})"
                for player_id, placed_zone, space_index in placement
                if placed_zone == zone
            )
            lines.append(
                f"{destination_display_name(zone.value, board_size)}: {names}"
            )
        return "\n".join(lines)

    def coaching_title(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> str:
        """The line drawn across the top of a coach's own half-field."""
        setup = match.setup_for_side(side)
        formation = self.current_formation(match, side)
        shape = f" - {formation.value}" if formation else ""
        return f"{format_team_side_label(setup)}{shape}"

    def coaching_prompt(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        note: str = "",
        lead_in: str = "",
    ) -> str:
        """
        The text above the coaching image. Rebuilt on every step, so
        `note` is whatever that step has to say -- the question it is
        asking, or what the last action did.
        """
        side = TeamSide(side)
        setup = match.setup_for_side(side)
        controller_id = self.side_controller_id(game, side)
        mention = f"<@{controller_id}>" if controller_id else "Someone"
        header = (
            f"{mention}, **{format_team_side_label(setup)}** -- "
            f"{self.substitution_allowance_label(match)}."
        )
        return "\n".join(
            part
            for part in (lead_in, "# Coaching Choice", header, note)
            if part
        )

    def coaching_finish_refusal(
        self,
        match: MatchState,
        side: TeamSide,
    ) -> Optional[str]:
        """
        Why this side may not finish yet, or None. The only thing that
        can hold a coach in the flow is the kickoff space: **every
        arrangement covers its own side's** (see "Coaching Choice" in
        docs/living-rules.md), and nothing else in a Coaching Choice
        guarantees it.

        It used to be asked of the side kicking off the coming period,
        at setup and halftime alone. It is asked of both sides at every
        occasion that positions anybody, because it is now a property
        of an arrangement rather than of a kickoff -- which is what
        lets a goal restart without the conceding side dropping
        somebody back and paying for it. A window that positions
        nothing (full time) has no arrangement to hold to it.

        On board 6 the two sides kick off from different midfield
        spaces, so this asks each about their own; on 7 and 9 it is one
        space and both have to cover it.
        """
        side = TeamSide(side)
        occasion = match.coaching_occasion
        if occasion is None or not occasion.offers_positioning:
            return None
        if match.kickoff_space_occupied_by(side):
            return None
        return (
            "Every arrangement has to cover its own kickoff space, so "
            f"{side.value} need a player on "
            f"{space_label(Zone.MIDFIELD, match.kickoff_space_for(side))} "
            "before finishing."
        )

    def cede_confirmation(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        """
        What the coach is agreeing to, in place of the turn prompt --
        see CedeConfirmView. Everything it names is a cost or a
        consequence the button label has no room for: who gets the
        ball, where, that the declaration goes with it, and that the
        other coach is handed a window of their own on the back of it.
        """
        receiving = format_team_side_label(
            match.setup_for_side(match.defending_side())
        )
        lines = [
            "# Cede the ball?",
            f"{receiving} take possession at "
            f"{space_label(match.ball.zone, match.ball.space_index)}, where "
            "it stands, and you open a Coaching Choice -- formation, "
            "substitutions, zone assignment, space positioning, free of "
            "exhaustion.",
            "It uses up your Coaching Choice for this half, and "
            f"{receiving} get one of their own to answer it.",
        ]
        if match.scoreboard.last_possession:
            # The one case where the coaching never happens: a turnover
            # under last possession is the end of the period, and
            # ceding is a turnover.
            lines.append(
                "**This is last possession, so this ends the period "
                "instead -- neither side gets to coach.**"
            )
        return "\n".join(lines)

    def describe_run_back_options(
        self,
        match: MatchState,
        side: TeamSide,
        player_id: str,
    ) -> str:
        """The spaces `player_id` may run back to in their own zone,
        with what each costs -- so the coach sees every option up
        front, alongside the buttons that offer the same choice and
        carry the same labels."""
        zone = match.setup_for_side(side).assigned_zone(player_id)
        spaces = match.placement_spaces_in_zone(side, zone, player_id)
        if not spaces:
            return "No space in their zone."
        options = ", ".join(
            travel_space_label(
                zone, index, match.run_back_distance(player_id, zone, index),
            )
            for index in spaces
        )
        return f"Options: {options} — one exhaustion token per space."

    def shootout_mentions(
        self,
        game: D12BallGame,
        match: MatchState,
        sides: list[TeamSide],
    ) -> str:
        """Whoever a shootout step is still waiting on, named."""
        parts = []
        for side in sides:
            controller_id = self.side_controller_id(game, side)
            parts.append(
                f"<@{controller_id}>"
                if controller_id
                else format_team_side_label(match.setup_for_side(side))
            )
        return " and ".join(parts) or "Someone"

    def shootout_button_label(
        self,
        match: Optional[MatchState],
        player_id: str,
    ) -> str:
        """
        One player, on a button in the shootout's ephemeral menus. The
        offensive skill is the whole of what a coach is choosing on --
        it is the only modifier a shootout roll adds -- so it is on
        the label rather than a card the coach has to go and find.
        """
        player = self.get_player_definition(player_id)
        role = ROLE_INITIALS[player.role.value]
        if match is not None and player_id in match.injured:
            return f"{player.name} [{role}] injured"
        offense = self.player_catalog.effective_profile(player).offense
        return f"{player.name} [{role}] +{offense}"

    def challenge_side(
        self,
        player_id: str,
        team: Team,
        attacking: bool,
        modifiers: tuple[str, ...] = (),
        contribution: Optional[int] = None,
        halved: bool = False,
    ) -> ChallengeSide:
        """
        A player as a matchup image draws them. The ability is the
        short form: this is a caption under a portrait, next to
        another player's, and the sentence version wrapped to three
        lines and set the height of the whole image. The full text is
        still what the roster and the rules listing show.

        `contribution` and `halved` are a score attempt's defenders
        only -- everyone else adds their whole skill and is drawn
        without a word about it. `team` is which of the player's two
        rosters this match is fielding them as -- read by both callers
        off `match.team_for_player`, since a player's own definition no
        longer carries one.
        """
        player = self.get_player_definition(player_id)
        profile = self.player_catalog.effective_profile(player)
        return ChallengeSide(
            name=player.name,
            role=ROLE_INITIALS[player.role.value],
            team_color=TEAM_COLORS[Team(team)],
            team_label=team_display_name(team),
            skill_name="Offensive" if attacking else "Defensive",
            skill=profile.offense if attacking else profile.defense,
            ability=profile.short_ability,
            modifiers=modifiers,
            contribution=contribution,
            halved=halved,
        )

    def format_roster_player(self, player_id: str) -> str:
        player = self.get_player_definition(player_id)
        initials = ROLE_INITIALS[player.role.value]
        return f"{player.name} ({initials})"

    def format_roster_player_with_team(
        self, player_id: str, team: Team,
    ) -> str:
        player = self.get_player_definition(player_id)
        initials = ROLE_INITIALS[player.role.value]
        return f"{player.name} ({team_display_name(team)}, {initials})"

    def roster_places(
        self,
        match: MatchState,
        setup: TeamSetup,
    ) -> list[tuple[str, list[tuple[str, Optional[str]]]]]:
        """
        The team's roster grouped by where its players actually are:
        each board zone in board order, then the bench, then the back
        bench. Each group is (heading, [(player_id, space label or
        None)]), with the players inside a zone ordered by space.

        Grouped by the meeple's *current* zone rather than the zone its
        card is assigned to, because that is where the player is -- a
        maneuver can leave a player standing outside their zone until
        they run back (see MatchState.displaced_players). Every roster
        player appears exactly once: anyone without a meeple falls
        through to whichever bench holds them.
        """
        # Keyed by card id, not by the catalog's: this side may be
        # holding the duplicate of a player the other side fields, and
        # its meeple is on the board under that id. See "One player,
        # both sides" in CLAUDE.md.
        roster_order = {
            setup.card_id_for(player.player_id): index
            for index, player in enumerate(
                self.player_catalog.teams[setup.team].players
            )
        }
        placed: dict[Zone, list[tuple[int, int, str]]] = {
            zone: [] for zone in Zone
        }
        for player_id in roster_order:
            position = match.board.meeple_position(player_id)
            if position is None:
                continue
            zone, space_index = position
            placed[zone].append(
                (space_index, roster_order[player_id], player_id)
            )

        on_board = {
            player_id
            for occupants in placed.values()
            for _, _, player_id in occupants
        }
        board_size = match.board.layout.board_size
        groups: list[tuple[str, list[tuple[str, Optional[str]]]]] = [
            (
                destination_display_name(zone.value, board_size),
                [
                    (player_id, space_label(zone, space_index))
                    for space_index, _, player_id in sorted(placed[zone])
                ],
            )
            for zone in Zone
        ]
        for bench, benched in (
            ("bench", setup.team_board.bench),
            ("back_bench", setup.team_board.back_bench),
        ):
            groups.append(
                (
                    destination_display_name(bench, board_size),
                    [
                        (player_id, None)
                        for player_id in benched
                        if player_id not in on_board
                    ],
                )
            )
        return groups

    def build_turn_prompt(
        self,
        game: D12BallGame,
        match: MatchState,
        carrying: bool = False,
    ) -> str:
        player_number = self.possession_player_number(game, match)
        controller = format_player_with_team(
            game,
            player_number,
            mention=player_number is not None,
        )

        if match.active_player_id is None:
            return (
                f"{controller}, it is your turn.\n\n"
                "Choose which player in the ball's space will take "
                "an action."
            )

        handler = self.format_roster_player(match.active_player_id)
        # `carrying` is passed in rather than read off the match:
        # select_ball_handler has already consumed ball_carrier_id by
        # the time the prompt is built, so only the caller that did the
        # selecting still knows the handler was forced.
        handler_line = (
            f"The ball was left with {handler}, who takes this turn."
            if carrying
            else f"{handler} will be handling the ball."
        )
        # PlayerActionView drops the shoot button short of shooting
        # range and offers the cede in its place, so say why rather
        # than leaving a coach to wonder where either went. The two are
        # the same read: out of range is exactly when ceding is on
        # offer, and the only thing that can take it away as well is a
        # declaration already spent.
        if match.can_attempt_score():
            action_line = "Choose an action:"
        elif match.may_cede_possession():
            action_line = (
                "The ball is out of shooting range, so there is no shot "
                "from here. Maneuver, or cede the ball to coach:"
            )
        else:
            action_line = (
                "The ball is out of shooting range and your side has "
                "already called its Coaching Choice this half, so there "
                "is no shot and no cede -- only a maneuver:"
            )
        return (
            f"{controller}, it is your turn.\n\n"
            f"{handler_line}\n\n"
            f"{action_line}"
        )
