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

Some methods here build prompt text -- `build_turn_prompt` and its
kind. That is presentation, not a rule, but it is presentation over
nothing but the match and the catalogs: no emoji, no interaction, no
cog, and no Pillow (the matchup image's brief, `challenge_side`, left
here in step 9 of docs/architecture-migration.md and is in
`d12ball/dice_brief.py`, beside the renderer, so this module imports
nothing from `d12ball/render.py`). `d12ball/formatting.py`
is where the plain-text half of that lives (space codes, team-side
labels, player names), imported here the same way it is imported into
cogs/d12ball_helpers.py -- see that module's own docstring for why
the split runs where it does.

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
from dataclasses import dataclass, replace
from typing import Optional

from d12ball.ai import AIStrategy
from d12ball.components import (
    BALL_SPEED_MAX,
    DRIBBLE_BURST_MAX_DISTANCE,
    HIGH_PASS_CLOCK_COST,
    MANEUVER_CLOCK_COST,
    SETUP_PASS_CLOCK_COST,
    SETUP_PASS_DISTANCES,
    SETUP_PASS_FULLBACK_DISTANCE,
    SKILLED_PASS_REACH,
    MANEUVER_TIER_BASIC,
    MANEUVER_TIER_GAMBIT,
    CYBORG_DRAINED_AT,
    DOUBLE_TEAM_PARTNER_KIND,
    MIND_PULL_SUCCESS_FACES,
    MIND_PULL_TOKEN_COST,
    OVERDRIVE_BONUS,
    OVERDRIVE_DRAIN_COST,
    SETUP_AREAS,
    SPECIES_CYBORG,
    SPECIES_FIRE_DEMON,
    SPECIES_OOZE,
    SPECIES_TELEKINETIC,
    VOLATILE_IGNITE_FACES,
    VOLATILE_BLAZE_MINIMUM,
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
    catalog_player_id,
    formation_space_order,
    zone_for_area,
)
from d12ball.formatting import (
    ball_space_label,
    contest_noun,
    destination_display_name,
    format_player_with_team,
    format_team_side_label,
    score_side_label,
    player_with_role,
    space_label,
    travel_space_phrase,
    side_coach_number,
    side_display_name,
)
from d12ball.game import (
    COIN_FACE_WORDS,
    AIOpponent,
    CoinFace,
    D12BallGame,
    Formation,
    GameMode,
    Team,
    team_display_name,
)
from d12ball import tokens
from d12ball.special_abilities import (
    BOOST_BONUS,
    BRIGHTBURN_BURN_RECOVERY,
    BULWARK_DRAINED_AT,
    EMBERDASH_ADVANCE_MAX,
    KINDLEFINGER_TOKEN,
    SPECIAL_ABILITIES,
    SCORCHIT_FORCED_TEST_TOKENS,
    SIZZIFIZIK_IGNITE_FACES,
    SPECTRA_PULL_MINIMUM,
    STRIDER_CHARGE_UP,
    STRIDER_RUN_BACK_MAXIMUM,
    VISCOR_MERGE_BONUS,
    VOLTUS_OVERDRIVE_DRAIN_COST,
    SpecialAbility,
    without_shot_condition,
)


#: Under every Coaching Choice a side fielding Spreadable Oozes takes --
#: see `RulesEngine.spreadable_note`. Italic by asterisks, which both
#: frontends render (Discord's client, and `webapp.present`'s subset).
SPREADABLE_NOTE = (
    "*Note: Your Spreadable Oozes may be positioned in the same space "
    "as a teammate.*"
)


@dataclass(frozen=True)
class PlayerSkills:
    """
    A player's two skills as this game plays them -- the role's, or in
    advanced mode the player's own advanced scores where they have any
    (Law 21, "Advanced skills"). Not a `RoleProfile`, because an
    advanced score is not held to 1-6. `RulesEngine.skills` is the one
    way to get one.
    """

    offense: int
    defense: int

    def of(self, kind: str) -> int:
        return self.offense if kind == "offense" else self.defense


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

    `second` is the ignite's own die, `blaze` says which way it went,
    and `modifier` is 0 for every roll that did not ignite -- which is
    every roll in a training game, and most rolls in any other.

    **`second` is also a die a coach watches**, not only a number in
    `modifier`: it is drawn as an ignition die beside the roll's own dice
    and captioned with `explain` -- see `D12Ball.dice_file_with_ignitions`.
    That is why
    the face and which way it went are carried apart from the
    arithmetic rather than folded into it.
    """

    face: int
    modifier: int = 0
    second: Optional[int] = None
    blaze: bool = False
    # The Fire Demon's special ability, where one shaped this ignite
    # (Law 21): `always_blazes`, `wide_ignition` or `bright_burn`.
    special: Optional[str] = None
    # Brightburn's tokens shed by this burn -- set by the roll site,
    # which holds the match (`RulesEngine.settle_burn`).
    recovered: int = 0

    @property
    def upgrades_opponent(self) -> bool:
        """Whether a burn that loses hands the opponent the gambit."""
        return self.burn and self.special != SpecialAbility.BRIGHT_BURN

    @property
    def rule(self) -> Optional[str]:
        """
        The rule the ignition die is captioned with, where a special
        ability changed it -- None for the plain Volatile rule, which
        the renderer words for itself (`volatile_explainer_label`).
        """
        if self.special == SpecialAbility.WIDE_IGNITION:
            faces = SIZZIFIZIK_IGNITE_FACES
            return (
                f"a natural {faces[0]} to {faces[-1]} ignites — the second "
                f"d12 adds on {VOLATILE_BLAZE_MINIMUM}-12, subtracts on "
                f"1-{VOLATILE_BLAZE_MINIMUM - 1}"
            )
        if self.special == SpecialAbility.ALWAYS_BLAZES:
            faces = " or ".join(str(face) for face in VOLATILE_IGNITE_FACES)
            return f"a natural {faces} ignites — the second d12 always adds"
        return None

    @property
    def ignited(self) -> bool:
        return self.second is not None

    @property
    def burn(self) -> bool:
        return self.ignited and not self.blaze

    @property
    def detail(self) -> Optional[str]:
        """
        The line this adds to the dice image's modifier list, or None
        when nothing happened. Worded so a coach can see the second die
        that produced it -- "+9 Volatile blaze (9)" rather than a bare
        number nothing on the image explains.
        """
        if not self.ignited:
            return None
        word = "blaze" if self.blaze else "burn"
        return f"{self.modifier:+d} Volatile {word} ({self.second})"

    def explain(self, label: str) -> Optional[str]:
        """
        The sentence posted beside the ignition die -- what just
        happened to this roll, in words, or None when nothing did.

        **The twin of `detail`, and deliberately beside it.** The two
        are one ignite said in the two places a coach reads it: `detail`
        is the modifier line in the totals column of the roll's own dice
        image, which is arithmetic and has to add up; this is the
        sentence over the second die's own image, which has to explain
        why there is a second die at all. Written apart they come to
        disagree about which way a roll went.

        It names the numbers rather than the rule -- the natural face
        that ignited, the second die, and which side of
        `VOLATILE_BLAZE_MINIMUM` it fell -- because the rule itself is
        drawn on the image it captions (see `volatile_explainer_label`).
        `label` is the player as the caller already names them, emoji
        and role bracket included, so this reads like every other line
        about them.

        **What ignites is the ball** (the author, 2026-09-16), not the
        die. The rules state the trigger as a property of the die,
        which is what a player has to *check*; what a coach is watching
        is a Fire Demon setting the ball alight, and the message is the
        place that says so.
        """
        if not self.ignited:
            return None
        opening = (
            f"🔥 **Volatile** — {label} rolled a natural {self.face}, "
            f"so **the ball ignites**. The second d12 comes up "
            f"**{self.second}**"
        )
        if self.blaze and self.special == SpecialAbility.ALWAYS_BLAZES:
            return (
                f"{opening}, and they always blaze: "
                f"**{self.modifier:+d}** to their roll."
            )
        if self.blaze:
            return (
                f"{opening} — {VOLATILE_BLAZE_MINIMUM} or more, so it "
                f"**blazes**: **{self.modifier:+d}** to their roll."
            )
        sentence = (
            f"{opening} — under {VOLATILE_BLAZE_MINIMUM}, so it "
            f"**burns**: **{self.modifier:+d}** to their roll."
        )
        if self.special == SpecialAbility.BRIGHT_BURN:
            sentence += " Their burn upgrades nothing"
            sentence += (
                f", and sheds {self.recovered} token."
                if self.recovered
                else "."
            )
        return sentence

    def to_dict(self) -> dict:
        """The die, as a frontend with no dice image reads it."""
        return {
            "face": self.face,
            "modifier": self.modifier,
            "second": self.second,
            "blaze": self.blaze,
            "special": self.special,
            "recovered": self.recovered,
        }


# The halftime sequence's stages, in order -- see
# RulesEngine.next_halftime_stage. Each side gets its own
# extra-exhaustion-token choice and its own Coaching Choice, **the
# visitors first** throughout: they kick off the second half, so they
# are the side whose arrangement the restart depends on.
#: The one distance a Fullback's reach adds to a High Pass or a Setup
#: Pass menu -- "High pass up to 4", read as a number (the author,
#: 2026-08-19). `pass_ability_note` names it on the button.
FULLBACK_PASS_REACH = 4

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
        rng: Optional[random.Random] = None,
    ) -> None:
        self.player_catalog = player_catalog
        self.basic_ruleset = basic_ruleset
        self.maneuver_catalog = maneuver_catalog
        self.ai_strategies = ai_strategies
        # **Every draw the game makes comes from here** -- the dice,
        # the coin, the defensive tie-break's shuffle, and the AI's
        # own picks, since each strategy is handed this same stream
        # below. Nothing in `d12ball/` reads the module `random`
        # (decision 7 of docs/web-app.md; step 9 of
        # docs/architecture-migration.md): a test seeds `engine.rng`
        # and replays a whole game, and a web process running two
        # games is not sharing one process-wide stream with the
        # frontend. The service constructs nothing and rolls nothing.
        self.rng: random.Random = rng if rng is not None else random.Random()
        for strategy in ai_strategies.values():
            strategy.rng = self.rng
        # Nothing Discord-shaped is held here. The four emoji dicts
        # the engine carried until step 9 of
        # docs/architecture-migration.md -- a badge per role, a ring
        # per team, the condition marks and the species icons -- live
        # on the cog that fetches them, and a sentence that names one
        # writes a token for it (`d12ball/tokens.py`) that the cog
        # renders at its door.

    def apply_exhaustion(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        amount: int,
    ) -> str:
        """
        Charge `amount` exhaustion tokens, re-test Exhausted, and
        describe both.

        Charging and testing belong in one step. They used to be two:
        callers added the tokens, saved the match, and only then built
        the message that ran the threshold test -- so the flag the
        test set was never written out. The next interaction reloaded
        the saved state and saw a player over their defensive skill
        who was not marked Exhausted, which cost a skill test the
        injury check for anyone the test's own tokens pushed over.
        Anything that charges exhaustion should call this and save
        afterwards.

        It takes the `game` because the threshold is not always the
        player's defensive skill: a Cyborg's tokens are **drain** and
        the line is a flat 7 -- see `exhaustion_threshold`. Nothing
        else about charging a token differs by species, which is why
        this stayed one method rather than growing a branch.

        `RulesEngine.apply_exhaustion` forwards to this so no call site
        moved. It came down here with rank O2 of the model/Discord
        split: a Burst charges a token a space and a beaten
        Clear charges two, and a flow step that cannot word what it
        charged would have to hand the sentence back to the cog to
        write.
        """
        match.add_exhaustion(player_id, amount)
        return self.describe_exhaustion_gain(game, match, player_id, amount)

    def pickup_cost(self, match: MatchState, player_id: str) -> int:
        """
        The exhaustion `player_id` adds if sent to pick the ball up: 1
        for every space to the ball, whichever of the four pickups it
        is -- an out-of-bounds ball, a missed shot, an avoided own goal
        or a time out ("Picking the ball up" in docs/living-rules.md;
        the time out's was free until the author's 2026-09-26 change).
        The prompt carries it (`PlayerOptions.costs`), and the pickup
        charges the distance the same measure walks.
        """
        return match.distance_to_ball(player_id)

    def drain_wording(
        self, game: D12BallGame, player_id: str,
    ) -> bool:
        """
        Whether this player's exhaustion is read in the Cyborgs' own
        words -- **drain** tokens, **Drained**, **Damaged**.

        One question rather than a `has_species_ability` call at every
        site that words a condition, because the three words move
        together: a player counting drain tokens is a player who
        becomes Drained, and a line that got one of the three from
        this reading and another from its own would be wording one
        player two ways. See "Lithium Powered" in
        docs/living-rules.md.
        """
        return self.has_species_ability(game, player_id, SPECIES_CYBORG)

    def token_word_and_mark(
        self, game: D12BallGame, player_id: str,
    ) -> tuple[str, str]:
        """
        What this player's exhaustion tokens are called, and the mark
        a sentence counts them out in.
        """
        if self.drain_wording(game, player_id):
            return "drain", tokens.condition(tokens.CONDITION_DRAIN)
        return "exhaustion", tokens.condition(tokens.CONDITION_EXHAUST)

    def exhausted_word_and_mark(
        self, game: D12BallGame, player_id: str,
    ) -> tuple[str, str]:
        """
        What this player is called once their tokens pass their
        threshold, and the mark for it.
        """
        if self.drain_wording(game, player_id):
            return "drained", tokens.condition(tokens.CONDITION_DRAINED)
        return "exhausted", tokens.condition(tokens.CONDITION_EXHAUSTED)

    def injured_word_and_mark(
        self, game: D12BallGame, player_id: str,
    ) -> tuple[str, str]:
        """
        What this player is called once they are out of the contest,
        and the mark for it.

        `d12ball.flow.turn.injured_word_and_emoji` is the older name
        this answers under, kept because a dozen steps call it.
        """
        if self.drain_wording(game, player_id):
            return "damaged", tokens.condition(tokens.CONDITION_DAMAGED)
        return "injured", tokens.condition(tokens.CONDITION_INJURED)

    def injury_test_name(self, game: D12BallGame, player_id: str) -> str:
        """
        What this player's injury check is called: a Cyborg's is a
        **damage test**, since what it risks is Damaged (the author,
        2026-09-23). The same check under the Cyborgs' own word, like
        the other three `drain_wording` answers.
        """
        if self.drain_wording(game, player_id):
            return "damage test"
        return "injury test"

    def describe_exhaustion_gain(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        amount: int,
    ) -> str:
        """
        Text describing an exhaustion-token gain that has already been
        applied to `match` — the running total, plus a line the moment
        it pushes the player's token count past their own threshold.

        Testing the threshold is a state change, so this has to be
        called before `match` is saved -- prefer `apply_exhaustion`,
        which keeps the two together, wherever the tokens are being
        charged here rather than inside `MatchState`.
        """
        player = self.get_player_definition(player_id)
        # A Cyborg's tokens are drain, and are called that everywhere a
        # coach reads them -- the mechanic is the same and the word is
        # the ability. See "Lithium Powered" in docs/living-rules.md.
        noun, exhaust_emoji = self.token_word_and_mark(game, player_id)
        drain = self.drain_wording(game, player_id)
        if player_id in match.injured:
            out_word, out_emoji = self.injured_word_and_mark(game, player_id)
            gains_nothing = (
                "does not drain" if drain else "does not exhaust"
            )
            return (
                f"{self.format_player_label(match, player)} is {out_word} "
                f"{out_emoji} and {gains_nothing}."
            )
        if amount <= 0:
            # Nothing to say, and the silence is the answer (the
            # author, 2026-08-27). Every move that costs a token says
            # so right here, so a result carrying no exhaustion line
            # already tells a coach none was charged -- where "no
            # exhaustion cost" answered a question the message had not
            # raised, and "free" left it to the coach to work out what
            # was free about it. Callers join on what is there rather
            # than interpolating, or the empty string shows as a blank
            # line.
            return ""

        # The mark is the Cyborgs' own teal triangle where the word is
        # theirs (`token_word_and_mark`): the card draws a Cyborg's
        # tally in teal (`render.draw_exhaustion_badge`), and the same
        # tokens in two colours would read as two different costs.
        #
        # A Cyborg *drains* and everybody else *exhausts*: "drain 2"
        # is two drain tokens gained and "exhaust 2" two exhaustion
        # tokens (the author, 2026-09-23 and 2026-09-27); "clear" takes
        # either kind off.
        total = match.exhaustion.get(player_id, 0)
        gained = (
            f"drains {amount}" if drain
            else f"exhausts {amount}"
        )
        text = (
            f"{self.format_player_label(match, player)} {gained} "
            f"{exhaust_emoji * amount} (now {total} total)."
        )

        if self.retest_exhausted(game, match, player_id):
            word, emoji = self.exhausted_word_and_mark(game, player_id)
            text += (
                f"\n{self.format_player_label(match, player)} is now "
                f"*{word}* {emoji}"
            )
        return text

    def gambits_apply(self, game: D12BallGame) -> bool:
        """
        Whether this game is playing the **gambits**, which advanced
        mode adds and no other mode plays.

        `game.advanced_maneuvers` is the opt-out advanced mode carried
        until 2026-09-25, when the modes became three and the toggles
        went (see "Modes" in docs/design/species-abilities.md). Nothing
        sets it any more; it is still read so an advanced game saved
        with the gambits turned off plays on as it was started.
        """
        return game.mode == GameMode.ADVANCED and game.advanced_maneuvers

    def maneuver_reference_tier(
        self, game: Optional[D12BallGame],
    ) -> str:
        """
        Which hexagon a coach is handed: the one with the gambits on it
        for a game actually playing them, the basic one everywhere else
        -- including where there is no game to ask (a channel with none,
        the web app's front door). Through `gambits_apply` rather than
        off `game.mode`, or an advanced game that opted the maneuvers
        out would be handed a reference to six cards it will never hold.

        **The game's, deliberately, rather than the asking coach's.**
        A coach the 2026-09-20 gate has closed this turn still needs to
        read what the *other* side may be about to play, and the
        hexagon is the twelve relations rather than a hand -- so it
        asks the module and not `coin_holder`.

        It was the cog's `reference_tier` until the web app needed the
        same answer (step 11 of docs/web-app-next.md); a choice two
        frontends make is the model's.
        """
        if game is not None and self.gambits_apply(game):
            return MANEUVER_TIER_GAMBIT
        return MANEUVER_TIER_BASIC

    def species_abilities_apply(self, game: D12BallGame) -> bool:
        """
        Whether this game is playing the **species abilities**: standard
        and advanced mode do, training mode does not (2026-09-25; see
        "Species abilities" in docs/living-rules.md). In training mode
        species is only a name on the card.

        **A tutorial never does**, whatever its mode says. The tutorial
        is a training game, and one saved before training mode existed
        carries `basic` -- which now plays the species abilities its
        scripted beats were never written for. `game.species_abilities`
        is the legacy opt-out, read for the reason `gambits_apply`
        reads its twin.
        """
        return (
            game.mode in (GameMode.STANDARD, GameMode.ADVANCED)
            and game.species_abilities
            and not game.tutorial
        )

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
        training game by species rules. Nothing may read
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

    def special_abilities_apply(self, game: D12BallGame) -> bool:
        """
        Whether this game plays the **special abilities** and the
        advanced skill scores: advanced mode alone (Law 21), and never a
        tutorial, for the reason `species_abilities_apply` gives.
        """
        return game.mode == GameMode.ADVANCED and not game.tutorial

    def has_special_ability(
        self,
        game: Optional[D12BallGame],
        player_id: Optional[str],
        ability: SpecialAbility,
    ) -> bool:
        """
        **The one question every special-ability site asks**: does this
        card, in this game, hold that ability? The twin of
        `has_species_ability`, folding the mode gate into the lookup so
        no site can check the player and forget the mode.

        Tolerant of no game and no player, because several roll sites
        ask it of a die that belongs to nobody (the defensive wall's).
        A card fielded on the second side is the same person
        (`catalog_player_id`).
        """
        if game is None or player_id is None:
            return False
        if not self.special_abilities_apply(game):
            return False
        row = SPECIAL_ABILITIES.get(catalog_player_id(player_id))
        return row is not None and row[0] == ability

    def special_ability_text(
        self, game: D12BallGame, player_id: str,
    ) -> str:
        """
        The sentence a roster shows for a player's special ability:
        the sheet's own words, as the advanced face of the card prints
        them, in a game playing the special abilities, and `""`
        anywhere else or for a player who has none. For wording
        alone -- a rule asks `has_special_ability` or `skills`.

        The column also carries the four advanced-skill sentences
        ("High defensive skill."), which are shown too, since that is
        the card's own line for those players.
        """
        if not self.special_abilities_apply(game):
            return ""
        return self.get_player_definition(player_id).advanced_ability

    def special_ability_reminder(
        self, game: Optional[D12BallGame], player_id: str,
    ) -> str:
        """
        A player's special ability as a roll reminds of it -- the web
        page's chip beside a roll, and Flickerwing's line on the shot:
        `special_ability_text`, with the score attempt's condition
        dropped from Flickerwing's and Goopkeeper's, since each is only
        ever reminded of at a shot (the author, 2026-09-30). The rest of
        the sentence is the sheet's, never reworded.
        """
        text = self.special_ability_text(game, player_id)
        if any(
            self.has_special_ability(game, player_id, ability)
            for ability in (SpecialAbility.CLEAR_SHOT, SpecialAbility.FULL_BLOCK)
        ):
            return without_shot_condition(text)
        return text

    def skills(
        self, game: Optional[D12BallGame], player_id: str,
    ) -> PlayerSkills:
        """
        **A player's offensive and defensive skill, as this game plays
        them** -- the one reading every roll, threshold and bonus asks.
        The role's profile, with the player's advanced scores laid over
        it in a game playing the special abilities (Law 21, "Advanced
        skills"); a player with no advanced score of a kind keeps the
        role's.

        `game` may be None only for a caller that has no game to ask,
        which reads the role's skills, as a training game would.
        """
        player = self.get_player_definition(player_id)
        profile = self.player_catalog.effective_profile(player)
        offense, defense = profile.offense, profile.defense
        if game is not None and self.special_abilities_apply(game):
            offense = player.advanced_skills.get("offense", offense)
            defense = player.advanced_skills.get("defense", defense)
        return PlayerSkills(offense=offense, defense=defense)

    def card_skills(
        self, game: D12BallGame, match: MatchState,
    ) -> dict[str, tuple[int, int]]:
        """
        The `(offense, defense)` a board card should print wherever it
        is not the role's -- a player's advanced skills in an advanced
        game (Law 21). What `render.py`'s `card_skills` needs, answered
        here for the reason `cyborg_condition_ids` is: the renderer is
        handed the numbers and never the game. Every card of both sides
        is asked, bench and back bench included, since the team board
        draws them all.
        """
        if not self.special_abilities_apply(game):
            return {}
        answer: dict[str, tuple[int, int]] = {}
        for setup in (match.home, match.visiting):
            for player_id in (
                *setup.field_players,
                *setup.team_board.bench,
                *setup.team_board.back_bench,
            ):
                skills = self.skills(game, player_id)
                profile = self.player_catalog.effective_profile(
                    self.get_player_definition(player_id),
                )
                if (skills.offense, skills.defense) != (
                    profile.offense, profile.defense,
                ):
                    answer[player_id] = (skills.offense, skills.defense)
        return answer

    def cyborg_condition_ids(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> frozenset[str]:
        """
        Which of the players currently Exhausted, Injured or carrying
        an exhaustion token are Cyborgs playing with their own drain --
        the answer `render.py`'s `cyborg_ids` needs to draw
        Drained/Damaged instead of Exhausted/Injured, and the teal
        token count instead of the amber one, without the renderer
        being handed a `game` or a species to read itself.

        A rule rather than a rendering brief, which is why it is here:
        it is `has_species_ability` asked of everybody a condition mark
        would be drawn against, and **both frontends draw the same
        board off it** -- see "Lithium Powered" in
        docs/design/species-abilities.md and the `species_icons` flag
        it mirrors.
        """
        return frozenset(
            player_id
            for player_id in (
                match.exhausted | match.injured | match.exhaustion.keys()
            )
            if self.has_species_ability(game, player_id, SPECIES_CYBORG)
        )

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
        knows how to get its own dice -- `scripted_or_random`, the
        tutorial's scripted faces or this engine's `rng` -- and
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
        if player_id is None:
            return IgnitedRoll(face=face)
        if not self.has_species_ability(game, player_id, SPECIES_FIRE_DEMON):
            return IgnitedRoll(face=face)
        # Law 21: three Fire Demons read their own die differently.
        special = next(
            (
                ability
                for ability in (
                    SpecialAbility.WIDE_IGNITION,
                    SpecialAbility.ALWAYS_BLAZES,
                    SpecialAbility.BRIGHT_BURN,
                )
                if self.has_special_ability(game, player_id, ability)
            ),
            None,
        )
        faces = (
            SIZZIFIZIK_IGNITE_FACES
            if special == SpecialAbility.WIDE_IGNITION
            else VOLATILE_IGNITE_FACES
        )
        if face not in faces:
            return IgnitedRoll(face=face)

        second = self.rng.randint(1, 12)
        blaze = (
            special == SpecialAbility.ALWAYS_BLAZES
            or second >= VOLATILE_BLAZE_MINIMUM
        )
        return IgnitedRoll(
            face=face,
            modifier=second if blaze else -second,
            second=second,
            blaze=blaze,
            special=special.value if special else None,
        )

    def settle_burn(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: Optional[str],
        ignite: IgnitedRoll,
    ) -> IgnitedRoll:
        """
        **Brightburn sheds a token on every burn** (Law 21), in any roll
        Volatile covers. The roll site calls this beside `ignite`,
        because the ignite is read before there is a match to change;
        what comes back carries how many came off, for the sentence
        posted with the ignition die (`IgnitedRoll.explain`).
        """
        if not ignite.burn or ignite.special != SpecialAbility.BRIGHT_BURN:
            return ignite
        removed = match.recover_exhaustion(
            player_id,
            BRIGHTBURN_BURN_RECOVERY,
            self.exhaustion_threshold(game, player_id),
        )
        return replace(ignite, recovered=removed)

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
        return [
            player_id
            for player_id in self._may_drain_before_roll(
                game, match, player_ids,
            )
            if player_id not in match.pending_overdrive
        ]

    def _may_drain_before_roll(
        self,
        game: D12BallGame,
        match: MatchState,
        player_ids: Collection[Optional[str]],
    ) -> list[str]:
        """
        The rollers who could spend drain on this roll at all -- the
        uninjured Cyborgs among them -- whatever they have already
        declared. Overdrive and Boost each narrow it by their own
        declaration and nothing else, since Gearclaw may declare both
        on one roll (Law 21).

        A side whose coach has passed on Overdrive for this roll
        (`MatchState.overdrive_passed`) has closed its declarations.
        """
        if not self.species_abilities_apply(game):
            return []
        return [
            player_id
            for player_id in player_ids
            if player_id is not None
            and player_id not in match.injured
            and self.has_species_ability(game, player_id, SPECIES_CYBORG)
            and not (
                match.overdrive_passed
                and match.side_for_player(player_id).value
                in match.overdrive_passed
            )
        ]

    def overdrive_cost(self, game: D12BallGame, player_id: str) -> int:
        """
        The drain an Overdrive takes from this Cyborg: 3, or Voltus's 2
        (Law 21).
        """
        if self.has_special_ability(
            game, player_id, SpecialAbility.CHEAP_OVERDRIVE,
        ):
            return VOLTUS_OVERDRIVE_DRAIN_COST
        return OVERDRIVE_DRAIN_COST

    def boost_candidates(
        self,
        game: D12BallGame,
        match: MatchState,
        player_ids: Collection[Optional[str]],
    ) -> list[str]:
        """
        Which of the players about to roll may still declare **Boost**
        -- Gearclaw's special ability (Law 21), offered on every roll
        an Overdrive is and on the same terms, narrowed to the player
        who holds it. Once per roll, like Overdrive, and independent of
        it: an Overdrive declared on this roll leaves Boost open, and
        the other way round.
        """
        return [
            player_id
            for player_id in self._may_drain_before_roll(
                game, match, player_ids,
            )
            if player_id not in match.pending_boost
            and self.has_special_ability(
                game, player_id, SpecialAbility.BOOST,
            )
        ]

    def overdrive_details(
        self, match: MatchState, player_id: str,
    ) -> list[str]:
        """
        The lines a declared Overdrive and Boost add to the dice image's
        modifier list, one each, and none for neither -- the twin of
        `IgnitedRoll.detail`, and worded the same way so a coach reads
        one list of modifiers however they were earned. Two lines
        rather than one sum because Gearclaw may declare both on a roll
        (Law 21), and each is its own price.
        """
        lines = []
        if player_id in match.pending_overdrive:
            lines.append(f"+{OVERDRIVE_BONUS} Overdrive")
        if player_id in match.pending_boost:
            lines.append(f"+{BOOST_BONUS} Boost")
        return lines

    def smooth_candidates(
        self, game: D12BallGame, match: MatchState,
    ) -> list[str]:
        """
        **Smooth** (Mind Pull, Telekinetic): the Telekinetics of the
        side **in possession** standing on the space the ball just
        moved **to**, who may take it over as it arrives.

        The twin of `mind_pull_candidates`, and each difference is a
        clause of the rule:

        - **The space it comes to rest on, not the ones it passes
          over.** "Smooth only works when the ball gets to the space,
          not through" (the author, 2026-09-24) -- Slip in's gate
          rather than the pull's. So this reads only the last entry of
          `last_ball_path`, which `ball_path_to` always ends on where
          the ball lands; a Telekinetic the ball merely crosses is
          offered nothing, and a movement that goes nowhere (an empty
          path) offers nobody anything.

        - **Your own side, not the opponents'.** "When your team has
          possession" -- so this reads `match.ball.possession` where
          the pull reads `defending_side()`. The two lists can
          therefore never share a name on one movement, which is what
          lets the two queues run one after the other without either
          having to know about the other's members.
        - **Anyone this resolution moved is out**, the same as the
          pull and for the author's same sentence. It matters more
          here than there: the handler a dribble or a shove carries is
          on the possessing side and ends up standing on the ball, so
          without this they would be offered a Smooth on the ball they
          are already holding.
        - **Whoever the movement is handing the ball to is out**,
          which is the other way the same player can end up on the
          ball without the ball having arrived *at* them in any sense
          they could act on. "You may take it over" is an offer to
          take it off somebody, and the receiver of a pass, the
          challenger who has just stolen it and the shooter a set-up
          hands it to are each already the one holding it -- there is
          nothing for them to take over, and the button changes
          nothing (the author, 2026-09-20). `match.ball_carrier_id` is
          who that is, set by every effect that completes a delivery
          before the arrival gate is asked. **The pull needs no such
          clause**: a carrier is by definition on the side in
          possession, and a pull is only ever offered to the side that
          is not.
        - **No carrier, no Smooth.** The same sentence once more: with
          nobody holding the ball there is nobody to take it off. A
          ball left where nobody is named as holding it -- a Deflect,
          a pass that reaches nobody, a Clear, a beaten Cross, a High
          Pass contest -- is settled by what is standing on the space
          (Law 10.1): a lone Telekinetic there simply has it, one
          among teammates is their coach's pick, and one beside an
          opponent contests for it (the author, 2026-09-28). Every
          effect that hands the ball to somebody sets the carrier, and
          `select_ball_handler` clears it at the top of the turn, so
          `None` here is exactly an unheld ball.
        - **Injured players are in.** A pull excludes them because it
          costs an exhaustion token and an injured player cannot gain
          one, so `add_exhaustion` would silently hand them a free
          roll. Smooth costs nothing, so that reasoning does not reach
          here and an injured Telekinetic may take the ball over like
          anyone else -- an injured player is still playing (see
          "Playing injured" in docs/living-rules.md).

        Read off `match.last_ball_path` like the pull, so a restart --
        which clears the path rather than recording one -- offers
        nobody a Smooth either.
        """
        if not match.last_ball_path:
            return []
        zone_value, space_index = match.last_ball_path[-1]
        return self._smooth_takers(
            game, match, Zone(zone_value), space_index,
            set(match.last_ball_movers),
        )

    def smooth_candidates_after_contest(
        self, game: D12BallGame, match: MatchState,
    ) -> list[str]:
        """
        **Smooth off a contest's winner** (Law 20.4.11): the
        Telekinetics of the winning side sharing the ball's space with
        the teammate who has just won it, who may take it over from
        them.

        A Smooth may not skip a contest -- the ball is nobody's until
        it is won, and `smooth_candidates` offers nothing on an unheld
        ball -- but once a teammate has won it they are holding it,
        which is the case the ability is for (the author, 2026-09-28).
        The contest moved the ball nowhere, so this reads the ball's
        own space rather than a path, and nobody on it was carried
        there by the ball. Asked once, as the contest hands on (see
        `d12ball.flow.arrivals.check_for_smooth_after_contest`).
        """
        return self._smooth_takers(
            game, match, match.ball.zone, match.ball.space_index, set(),
        )

    def _smooth_takers(
        self,
        game: D12BallGame,
        match: MatchState,
        zone: Zone,
        space_index: int,
        moved: set[str],
    ) -> list[str]:
        """
        The side in possession's Telekinetics (and Shpritz) on one
        space who may take the ball off its carrier: everything the two
        Smooth readings share. Nobody when nobody is carrying it -- see
        "No carrier, no Smooth" in `smooth_candidates`.
        """
        if not self.species_abilities_apply(game):
            return []
        carrier_id = match.ball_carrier_id
        if carrier_id is None:
            return []

        ours = set(
            match.setup_for_side(match.ball.possession).field_players
        )
        candidates: list[str] = []
        for player_id in match.board.spaces[zone][space_index]:
            if player_id not in ours or player_id in candidates:
                continue
            if player_id in moved or player_id == carrier_id:
                continue
            # Shpritz has the Telekinetics' Smooth (Law 21); the early
            # return above already covers them, since every mode
            # playing special abilities plays species ones.
            if not (
                self.has_species_ability(
                    game, player_id, SPECIES_TELEKINETIC,
                )
                or self.has_special_ability(
                    game, player_id, SpecialAbility.SMOOTH,
                )
            ):
                continue
            candidates.append(player_id)
        return candidates

    def smooth_keeper(self, match: MatchState) -> Optional[str]:
        """
        Who holds the ball if the Smooth on offer is **declined** --
        the other half of the question `smooth_candidates` asks, and
        the one a frontend needs to say what the second button does.

        A Smooth is "take it over", so there is usually somebody to
        take it off: every effect that completes a delivery sets
        `ball_carrier_id` before the arrival gate is asked, and a
        dribble or a shove sets it on the handler who carried it. That
        player is standing on the ball and keeps it where nobody
        smooths.

        **Two arrivals are about to take it off them anyway, and
        neither leaves a keeper.** A loose ball comes down free --
        `begin_loose_ball` clears the carrier the moment the gate lets
        it through -- and a new play sends the ball back to the
        kickoff space with nobody on it, so the carrier still recorded
        at the gate is a receiver the goal has already made a former
        one. Both are read off `pending_smooth_resume`, the arrival
        this offer is holding back, which is the only thing that knows
        what declining leads to.
        """
        resume = match.pending_smooth_resume or {}
        if resume.get("kind") == "loose_ball" or resume.get("new_play"):
            return None
        return match.ball_carrier_id

    def turn_handler_candidates(
        self, game: D12BallGame, match: MatchState,
    ) -> list[str]:
        """
        Who may take this turn -- the answer every prompt, the AI and
        the click that answers should ask, so none of them can offer a
        different list from the others.

        It used to fold Slip in into the answer. Smooth replaced Slip
        in on 2026-09-20 and settles the same question at the arrival
        gate instead, so this is now a straight pass-through and is
        kept for the single-answer rule rather than for what it adds.
        """
        return match.turn_handler_candidates()

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
        - **Anyone this resolution moved is out.** "They move with the
          ball, while Mind Pull only works when the ball moves after"
          (the author, 2026-09-20). A player the maneuver carried never
          had the ball move *to or through* their space -- they and it
          arrived together -- so a Telekinetic who challenges a Pressure
          is not owed a pull on the ball they just shoved, even though
          the shove leaves them standing on it.
          `MatchState.last_ball_movers` is who those are.
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
        moved = set(match.last_ball_movers)

        board = match.board
        ordered = board.spaces_in_order()
        candidates: list[str] = []
        for zone_value, space_index in match.last_ball_path:
            flat = board.flat_index(Zone(zone_value), space_index)
            # The space itself, then the two beside it for Noxar alone,
            # who pulls from next to the ball as well (Law 21) -- in
            # that order, which is the order the ball reaches them.
            reached = [(player_id, False) for player_id in ordered[flat]]
            for beside in (flat - 1, flat + 1):
                if 0 <= beside < len(ordered):
                    reached.extend(
                        (player_id, True) for player_id in ordered[beside]
                    )
            for player_id, adjacent in reached:
                if player_id not in theirs or player_id in candidates:
                    continue
                if player_id in moved:
                    continue
                if player_id in match.injured:
                    continue
                if not self.has_species_ability(
                    game, player_id, SPECIES_TELEKINETIC,
                ):
                    continue
                if adjacent and not self.has_special_ability(
                    game, player_id, SpecialAbility.ADJACENT_PULL,
                ):
                    continue
                candidates.append(player_id)
        return candidates

    def injury_test_target(self, match: MatchState, player_id: str) -> int:
        """
        The lowest total an injury check is safe on (Law 15.3): a roll
        **higher** than the tokens the player carries now, so one more
        than them. Read at the roll, after anything the roll itself
        moved (Kindlefinger's token), and ahead of it by a frontend
        saying what the check needs.
        """
        return match.exhaustion.get(player_id, 0) + 1

    def mind_pull_cost(self, game: D12BallGame, player_id: str) -> int:
        """The tokens a Mind Pull costs: 1, or Quillon's none (Law 21)."""
        if self.has_special_ability(
            game, player_id, SpecialAbility.FREE_PULL,
        ):
            return 0
        return MIND_PULL_TOKEN_COST

    def mind_pull_minimum(self, game: D12BallGame, player_id: str) -> int:
        """
        The lowest total a Mind Pull lands on: 11, or Spectra's 9
        (Law 21). "On 11-12" is read as 11 or more, because an ignite
        could carry a total past 12 and a higher roll is never a worse
        one.
        """
        if self.has_special_ability(
            game, player_id, SpecialAbility.STRONG_PULL,
        ):
            return SPECTRA_PULL_MINIMUM
        return min(MIND_PULL_SUCCESS_FACES)

    def merge_bonus(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        rolling: Collection[Optional[str]],
        skill: str,
    ) -> tuple[int, list[str], list[tuple[str, int]]]:
        """
        **Merge**: what the Oozes standing on the ball who are *not*
        rolling add to their own side's total, the lines saying so, and
        who they were and what each one added -- `(name, value)` a
        contributor, for the dice image to draw them by rather than
        only total them.

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
        total = 0
        lines: list[str] = []
        contributors: list[tuple[str, int]] = []
        for player_id, value in self.merge_contributions(
            game, match, side, rolling, skill,
        ):
            player = self.get_player_definition(player_id)
            total += value
            lines.append(f"+{value} {player.name} (Merge)")
            contributors.append((player.name, value))
        return total, lines, contributors

    def merge_contributions(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        rolling: Collection[Optional[str]],
        skill: str,
    ) -> list[tuple[str, int]]:
        """
        `merge_bonus`'s reading, as `(player_id, value)` for each Ooze
        -- or Double Team partner -- that adds: the one answer to who Merges, for a caller that
        names them rather than totals them -- the Discord caption over
        a challenge image, which names a player with their role.
        """
        species = self.species_abilities_apply(game)
        # **A Double Team's partner gains Merge** for the next maneuver
        # (Law 19.10.5), on the defending side alone, and only while
        # that is still their side's job: the list is cleared when the
        # maneuver after the Double Team is over. An Ooze partner is in
        # both readings and Merges once.
        partners = (
            set(match.pending_double_team)
            if side == match.defending_side() else set()
        )
        if not species and not partners:
            return []

        contesting = {player_id for player_id in rolling if player_id}
        contributions: list[tuple[str, int]] = []
        for player_id in match.contest_occupants(side):
            if player_id in contesting or player_id in match.injured:
                continue
            if player_id not in partners and not (
                species
                and self.has_species_ability(game, player_id, SPECIES_OOZE)
            ):
                continue
            value = self.skills(game, player_id).of(skill)
            # Viscor adds 3 more whenever they Merge (Law 21).
            if self.has_special_ability(
                game, player_id, SpecialAbility.MERGES_HARDER,
            ):
                value += VISCOR_MERGE_BONUS
            if value:
                contributions.append((player_id, value))
        return contributions

    def spread_exempt_ids(
        self, game: D12BallGame, match: MatchState, side: TeamSide,
    ) -> set[str]:
        """
        **Spreadable**: which of `side`'s fielded Oozes count as 0
        toward their own zone's occupancy -- every one of them,
        automatically, with nothing for a coach to declare, whenever
        this game plays species abilities. `MatchState` does not know
        what a species is, so this is the id set every occupancy
        reading takes as a parameter (see `open_spaces_in_zone`,
        `placement_spaces_in_zone` and `crowded_candidates` below,
        and `smooth_candidates` for the same split elsewhere).
        """
        if not self.species_abilities_apply(game):
            return set()
        setup = match.setup_for_side(side)
        return {
            player_id
            for player_id in setup.field_players
            if self.has_species_ability(game, player_id, SPECIES_OOZE)
        }

    def open_spaces_in_zone(
        self, game: D12BallGame, match: MatchState, side: TeamSide, zone: Zone,
    ) -> list[int]:
        return match.open_spaces_in_zone(
            side, zone, self.spread_exempt_ids(game, match, side),
        )

    def placement_spaces_in_zone(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        zone: Zone,
        player_id: Optional[str] = None,
    ) -> list[int]:
        return match.placement_spaces_in_zone(
            side, zone, player_id,
            self.spread_exempt_ids(game, match, side),
        )

    def volatile_raises_tier(
        self,
        game: D12BallGame,
        winner: IgnitedRoll,
        loser: IgnitedRoll,
    ) -> bool:
        """
        Whether Volatile's tier rider fires on a settled maneuver skill
        test -- **the winner's maneuver resolves as the gambit on
        its rank**.

        The rules name two cases and they are the same case. "A blaze
        on the winning side resolves *that side's* maneuver as its
        gambit"; "a burn on the losing side resolves *the
        opponent's*" -- and the opponent of the losing side is the
        winning side. So both raise the winner's card, which is why
        `MatchState.volatile_tier_upgrade` is one flag and not a side.

        Gated on the gambits as well as the species
        abilities: in a game that took one module without the other
        there is no tier to change and the ignite is only the number.
        Asking here rather than at the read is what lets
        `resolving_maneuver` stay a question about the match alone.
        """
        if not self.gambits_apply(game):
            return False
        # Brightburn's burn upgrades nothing (Law 21), which the ignite
        # already knows (`IgnitedRoll.upgrades_opponent`).
        return winner.blaze or loser.upgrades_opponent

    def overdrive_raises_tier(
        self,
        game: D12BallGame,
        winner_id: Optional[str],
        overdriven: Collection[str],
    ) -> bool:
        """
        **Synapse's special ability** (Law 21): a maneuver skill test
        won on a roll Synapse Overdrove resolves the winner's maneuver
        as its gambit, whether or not the coach may play one -- the
        winning blaze's rider, reached by a different road, so it sets
        the same flag (`MatchState.volatile_tier_upgrade`). Gated on
        the gambits for the reason `volatile_raises_tier` is.
        """
        if not self.gambits_apply(game):
            return False
        return winner_id in overdriven and self.has_special_ability(
            game, winner_id, SpecialAbility.OVERDRIVE_UPGRADE,
        )

    def dice_resolve_gambit(
        self,
        game: D12BallGame,
        match: MatchState,
        winner_id: Optional[str],
        outcome: str,
        winner_key: Optional[str],
    ) -> bool:
        """
        **Dravox and Hexis** (Law 21): a maneuver skill test they win
        with a gambit they played resolves it as the gambit, where a
        card that did not win on the cards otherwise resolves as its
        basic maneuver. Dravox's is a defensive gambit, Hexis's an
        offensive one, so each is read from the side the win came on.
        A basic card is not upgraded. Sets the same flag a winning
        blaze does, which resolves the winner's own card as played.
        """
        if not self.gambits_apply(game) or winner_key is None:
            return False
        card = self.maneuver_catalog.get(winner_key)
        if card is None or not card.is_gambit:
            return False
        ability = (
            SpecialAbility.OFFENSIVE_GAMBITS
            if outcome == "offense"
            else SpecialAbility.DEFENSIVE_GAMBITS
        )
        return self.has_special_ability(game, winner_id, ability)

    def volatile_loser_cost(
        self, game: D12BallGame, loser: IgnitedRoll,
    ) -> Optional[bool]:
        """
        What the losing side's ignite does to the gambit's cost they
        would otherwise pay: **nothing**, since 2026-09-25 (Law 20, "an
        ignite never decides a gambit's cost"; the author dropped the
        cost half of the 2026-09-07 answer). Always `None`, which
        leaves `gambit_cost_applies` the whole answer.

        Kept rather than removed because `MatchState.volatile_loser_cost`
        is a saved field (CLAUDE.md: legacy fallbacks stay): a match
        saved between a skill test and its effect under the old rule
        still carries its `True` or `False`, and `gambit_cost` still
        reads it for that one maneuver.
        """
        return None

    def trailing(self, match: MatchState, side: TeamSide) -> bool:
        """Whether this team has scored fewer goals than the other."""
        side = TeamSide(side)
        home = match.scoreboard.home_score
        visiting = match.scoreboard.visiting_score
        return home < visiting if side == TeamSide.HOME else visiting < home

    def carrying_more_conditions(
        self, match: MatchState, side: TeamSide,
    ) -> bool:
        """
        Whether this team **fields** more Exhausted-or-Injured players
        than the other -- the bench does not count, and a Cyborg's
        Drained and Damaged are Exhausted and Injured under their own
        words (`match.exhausted` and `match.injured` hold both; the
        words are `injured_word_and_mark`'s and
        `exhausted_word_and_mark`'s).

        Widened from injured-only on 2026-09-20: an Exhausted player is
        already carrying a real disadvantage (one skill test roll away
        from being taken out entirely), so counting only the players
        already lost undercounted which side is actually hurting.

        Strictly more, so it is false for both sides on a level count,
        exactly as `trailing` is on a level score.
        """
        side = TeamSide(side)
        other = TeamSide.VISITING if side == TeamSide.HOME else TeamSide.HOME
        return (
            len(match.conditioned_field_players(side))
            > len(match.conditioned_field_players(other))
        )

    def behind(self, match: MatchState, side: TeamSide) -> bool:
        """
        Whether this team is **behind** (Law 19.3.4): fewer goals, or
        more Exhausted-or-Injured players on the field than the other.
        Either is enough, and both are asked of one team, so both teams
        can be behind at once -- one trailing while the other is the
        more hurt.

        Until 2026-09-28 this was the gate on making a gambit at all
        (the author's 2026-09-20 rule, "a gambit needs a reason"). The
        coin took that over, and being behind is now what lets a coach
        **answer** a gambit with one of their own -- `may_answer_gambit`.
        Read off the scoreboard and the field when the hand is drawn,
        so a restart draws the same hand, and nothing is persisted for
        it.
        """
        return self.trailing(match, side) or self.carrying_more_conditions(
            match, side,
        )

    def coin_holder(
        self, game: D12BallGame, match: MatchState,
    ) -> Optional[TeamSide]:
        """
        Which team's coach holds **the coin** (Law 19.3) -- `None` in a
        game not playing the gambits, where there is nothing to hold it
        for.

        The toss winner keeps it (Law 3.1.4) and a declaration hands it
        over (`MatchState.declare_gambit`), so the match records it only
        once it has moved; until then it is read off the game record.
        That is also the whole of the fallback for a game saved before
        the coin existed. A game seated without a toss -- a test game --
        has no winner to read, and the coin starts with the home team.
        """
        if not self.gambits_apply(game):
            return None
        if match.coin_holder is not None:
            return TeamSide(match.coin_holder)
        winner = game.coin_winner_player_number
        if winner is not None and winner == game.visiting_player_number:
            return TeamSide.VISITING
        return TeamSide.HOME

    def coin_face(
        self, game: D12BallGame, match: MatchState,
    ) -> Optional[CoinFace]:
        """
        The face the coin shows in front of the coach holding it (Law
        19.3.3) -- `None` wherever `coin_holder` is, in a game with no
        coin to hold. The face it landed on when a declaration last
        handed it over; until then the toss's (Law 3.1.4), which is the
        same face whoever flipped it, since a doom face hands the toss
        to the other coach. A game seated without a toss shows Fortune.
        It decides nothing: it is what the coin looks like.
        """
        if self.coin_holder(game, match) is None:
            return None
        if match.coin_face is not None:
            return CoinFace(match.coin_face)
        return game.coin_face or CoinFace.FORTUNE

    def may_declare_gambit(
        self, game: D12BallGame, match: MatchState, side: str,
    ) -> bool:
        """
        Whether this maneuver side's coach may declare a gambit right
        now (Law 19.3.2): the game plays the gambits, the maneuver is
        challenged, nobody has declared one this maneuver, and their
        team holds the coin. Whether the maneuver has already resolved
        is the prompt's question -- this is only asked while it is up.
        """
        if not self.gambits_apply(game) or match.maneuver_uncontested:
            return False
        if match.gambit_declared_by is not None:
            return False
        return self.coin_holder(game, match) == self.maneuver_side_team(
            match, side,
        )

    def may_answer_gambit(
        self, game: D12BallGame, match: MatchState, side: str,
    ) -> bool:
        """
        Whether this maneuver side's coach may answer this maneuver's
        gambit with one of their own (Law 19.3.4): the other side
        declared one, and their team is `behind`. Holding the coin they
        have just been handed does not come into it.
        """
        declared = match.gambit_declared_by
        if declared is None or declared == side:
            return False
        if not self.gambits_apply(game) or match.maneuver_uncontested:
            return False
        return self.behind(match, self.maneuver_side_team(match, side))

    def gambit_answer_owed(
        self, game: D12BallGame, match: MatchState,
    ) -> Optional[str]:
        """
        The maneuver side still to say whether it answers this
        maneuver's gambit with one of its own, or `None` (Law 19.3.4,
        the author, 2026-09-28): asked of a side that is behind, as
        soon as the gambit is declared and **before either side picks a
        card**, so neither hand is ever six.
        """
        declared = match.gambit_declared_by
        # Settled at the declaration for a side that was not behind
        # then (`declare_gambit_step`), so only ever owed before a card.
        if declared is None or match.gambit_answer is not None:
            return None
        other = "defense" if declared == "offense" else "offense"
        if not self.may_answer_gambit(game, match, other):
            return None
        return other

    def maneuver_side_team(self, match: MatchState, side: str) -> TeamSide:
        """Which team is playing this side of the maneuver."""
        return (
            match.ball.possession
            if side == "offense"
            else match.defending_side()
        )

    def maneuver_tiers(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
    ) -> tuple[str, ...]:
        """
        Which tiers **this side** may pick from this turn -- the whole
        of who holds which cards, asked in one place so the hand a
        coach is shown, the buttons built under it and the click that
        answers cannot disagree.

        - **A standard game is the basic three**, and so is an advanced
          game that took the species abilities without this module --
          `gambits_apply` is both halves of that.
        - **An unchallenged maneuver is always basic** (the author):
          *"Gambit can only be played when a maneuver is challenged."*
          All three routes into the unopposed branch settle it before
          the offense is prompted, so `maneuver_uncontested` is already
          set by the time a hand is drawn.
        - **Nobody holds a gambit until one is declared** (Law 19.3,
          the author, 2026-09-28). The coach holding the coin declares
          it, and from then on their hand is **the three advanced
          maneuvers alone** -- they set the basic three aside.
        - **The other coach, where behind, answers first** -- a gambit
          of their own or their basic cards (`gambit_answer_owed`,
          `MatchState.gambit_answer`) -- and plays the three that
          answer chose. **A hand is always three cards** (the author,
          2026-09-28: "each side should be shown only 3 cards").

        `side` is a maneuver side, so the two hands on one prompt can
        be different threes.
        """
        if not self.gambits_apply(game) or match.maneuver_uncontested:
            return (MANEUVER_TIER_BASIC,)
        if match.gambit_declared_by == side:
            return (MANEUVER_TIER_GAMBIT,)
        if match.gambit_declared_by is not None and match.gambit_answer == "gambit":
            return (MANEUVER_TIER_GAMBIT,)
        return (MANEUVER_TIER_BASIC,)

    def describe_gambit_access(
        self, game: D12BallGame, match: MatchState,
    ) -> str:
        """
        Who may make a gambit this maneuver, for the public prompt --
        `""` where the question does not arise.

        Before a declaration it names the coach holding the coin; after
        one, the coach who declared it and whether the other may answer.
        **Said out loud even though it is public knowledge** -- the coin
        is on the table and the card backs show a gambit -- because the
        prompt only draws a hand for a side a *person* still picks for,
        so in a solo game Dinky's cards are never on the message.
        """
        if not self.gambits_apply(game) or match.maneuver_uncontested:
            return ""
        declared = match.gambit_declared_by
        if declared is None:
            holder = self.coin_holder(game, match)
            if holder is None:
                return ""
            coach = format_player_with_team(
                game, self.side_player_number(game, holder),
            )
            face = self.coin_face(game, match)
            return (
                f"{coach} holds the coin, {tokens.coin(face)} "
                f"{COIN_FACE_WORDS[face]} up, and may declare a gambit."
            )

        other = "defense" if declared == "offense" else "offense"
        declarer = format_player_with_team(
            game,
            self.side_player_number(
                game, self.maneuver_side_team(match, declared),
            ),
        )
        answerer = format_player_with_team(
            game,
            self.side_player_number(
                game, self.maneuver_side_team(match, other),
            ),
        )
        if match.gambit_answer == "gambit":
            return (
                f"{declarer} has declared a gambit. {answerer} answers "
                "with one of their own."
            )
        if self.gambit_answer_owed(game, match) is not None:
            return (
                f"{declarer} has declared a gambit. {answerer} is behind "
                "and may answer with one of their own."
            )
        return f"{declarer} has declared a gambit."

    def maneuver_pick_sides(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> tuple[str, ...]:
        """
        Which sides the maneuver prompt has a hand on -- every side of
        this maneuver that is asked, or was asked on the message a
        coach is looking at.

        Two things take a side off it:

        - **An unchallenged maneuver has no defense to pick for.** There
          is no challenger and there never will be one, so the offense
          is the whole prompt.
        - **An AI side that has picked.** The AI answers the prompt
          through the service before any message goes up (step 7 of
          docs/architecture-migration.md), so its hand is on the
          prompt only while it is still owed; once it has picked, the
          prompt a coach sees is one hand and one row, as it always
          was.

        **It is read off persisted state alone**, which is what lets a
        restart rebuild the identical view: the prompt is never edited
        once it is up (see `D12Ball.close_maneuver_prompt`), so the
        buttons on the message and the buttons the restored view
        dispatches have to agree, and a coach's side that has *already
        picked* must therefore keep its buttons -- which is also what
        lets that coach change the pick while the other side is still
        choosing (`maneuver_pick_refusal`).
        """
        sides = ["offense"]
        if not match.maneuver_uncontested:
            sides.append("defense")

        def picked(side: str) -> bool:
            return (
                match.offense_maneuver if side == "offense"
                else match.defense_maneuver
            ) is not None

        return tuple(
            side for side in sides
            if not (
                self.side_controlled_by_ai(game, match, side)
                and picked(side)
                and match.pick_unconfirmed != side
            )
        )

    def maneuver_hand(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
    ) -> tuple[ManeuverDefinition, ...]:
        """One side's playable cards this turn, in the order they read."""
        tiers = self.maneuver_tiers(game, match, side)
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

    def withheld_gambits(
        self,
        game: D12BallGame,
        match: MatchState,
        side: str,
    ) -> tuple[ManeuverDefinition, ...]:
        """
        The gambits this side does not hold this maneuver -- held back
        until the coin holder declares, or from a side that is not behind
        enough to answer (Law 19.3) -- empty wherever the question does not
        arise: a game not playing the gambits, an unchallenged maneuver
        (always basic, for everybody), or a side that holds them.

        **For a frontend that shows the hand whole** (step 5 of
        docs/web-app-redesign.md): the web page draws these dimmed
        beside the cards that may be played, so a coach reads what
        being behind would put in their hand. They are never an answer
        -- `maneuver_hand` is the hand, and this is its complement
        within the side's cards, asked of `maneuver_tiers` so the two
        cannot disagree.
        """
        if not self.gambits_apply(game) or match.maneuver_uncontested:
            return ()
        # Once a gambit is declared each hand is its three cards and
        # nothing dimmed beside them (the author, 2026-09-28).
        if match.gambit_declared_by is not None:
            return ()
        if MANEUVER_TIER_GAMBIT in self.maneuver_tiers(game, match, side):
            return ()
        return tuple(
            sorted(
                (
                    maneuver
                    for maneuver in self.maneuver_catalog.side(side)
                    if maneuver.tier == MANEUVER_TIER_GAMBIT
                ),
                key=lambda item: item.rank,
            )
        )

    def cards_outcome(self, match: MatchState) -> Optional[str]:
        """
        What the **cards** said, before any die was thrown:
        `"offense"`, `"defense"`, `"tie"` -- or None where there was no
        contest to decide.

        An unchallenged maneuver has no opposing card, so it answers
        None and every gambit's effect falls away with it.
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

    def gambit_benefit_applies(
        self, match: MatchState, key: Optional[str],
    ) -> bool:
        """
        Whether this card carries its gambit **benefit** -- which is
        exactly "it won on the cards" (the author, 2026-09-07).

        **Not "the cards were decisive".** That was the shape this took
        until 2026-09-07, off the author's own 2026-08-19 wording, and
        it was imprecise in one case: a decisive matchup whose
        card-winner is injured is settled by a skill test, and the
        *other* side can win it. Their card lost on the cards, so it
        resolves basic -- where "the cards were decisive" would have
        handed it a benefit it never earned.

        A tie is still the common case where nothing fires, but it is
        no longer the test.
        """
        side = self.maneuver_side(match, key)
        return side is not None and self.cards_outcome(match) == side

    def gambit_cost_applies(
        self, match: MatchState, key: Optional[str],
    ) -> bool:
        """
        Whether this card owes its gambit **cost** -- which is
        exactly "it lost on the cards" (the author, 2026-09-07), and
        the mirror of `gambit_benefit_applies`.

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
        except that a gambit resolves at its own tier only
        where it **won on the cards** -- see
        `gambit_benefit_applies`. A gambit that wins a tie,
        or that wins an injury-forced skill test the cards had gone
        against it, resolves as the basic card on its rank.

        **Volatile's tier rider is the one thing that raises a card
        here**, and it is read off `match.volatile_tier_upgrade`, which
        the skill test sets when the winner blazed or the loser
        burned. It beats the tie downgrade above -- the rules say
        "even where the cards tied and the basic card would otherwise
        resolve" -- and it only ever raises: a card already resolving
        as a gambit gains nothing, which falls out of the counterpart
        of a gambit being itself.

        The flag is already gated on both modules being in play (see
        `volatile_raises_tier`), so nothing here needs the game.

        **It raises the winner's card and nothing else.** The loser's
        cost is `gambit_cost`'s, which asks whether the *cards* were
        decisive -- an ignite decides a tier, not who won -- so a tie
        raised to a gambit by a blaze still carries no cost. That is
        the rules read literally: the rider speaks only to the card
        that resolves.
        """
        maneuver = self.maneuver_catalog.get(winner_key)
        if maneuver is None:
            return winner_key

        if match.volatile_tier_upgrade and not maneuver.is_gambit:
            return self.maneuver_catalog.counterpart(maneuver).key

        if not maneuver.is_gambit:
            return winner_key
        if match.volatile_tier_upgrade or self.gambit_benefit_applies(
            match, winner_key,
        ):
            return winner_key
        return self.maneuver_catalog.counterpart(maneuver).key

    def maneuver_clock_cost(self, match: MatchState, winner_key: str) -> int:
        """
        What the clock is charged when `winner_key` wins (Law 16.2):
        2 for a High Pass or a Cross, 1 for every other maneuver.

        **It is the card that resolves**, `resolving_maneuver`'s answer,
        and never the loser's (Law 16.2.3): a High Pass beaten by a
        Deflect costs the Deflect's 1. A High Pass and a Cross are
        the one rank, so a tier raised or lowered on the dice never
        changes the answer -- asking the resolving card is only the
        honest question.
        """
        resolving = self.resolving_maneuver(match, winner_key)
        if resolving == "setup_pass":
            return SETUP_PASS_CLOCK_COST
        if resolving == "high_pass":
            return HIGH_PASS_CLOCK_COST
        return MANEUVER_CLOCK_COST

    def gambit_cost(
        self, match: MatchState, winner_key: str,
    ) -> Optional[str]:
        """
        The **losing** card's key, when that card is a gambit and its
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
        if loser is None or not loser.is_gambit:
            return None

        # **Volatile overrides the cards, both ways.** A blaze that
        # lost pays nothing even where the card lost on the cards; a
        # burn that lost pays even where it did not. Asked before
        # `gambit_cost_applies` because that is exactly what it
        # overrides -- see `volatile_loser_cost`.
        if match.volatile_loser_cost is False:
            return None
        if match.volatile_loser_cost is True:
            return loser.key

        if not self.gambit_cost_applies(match, loser.key):
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

    def flip_coin(self) -> CoinFace:
        """
        The coin toss that starts a game: a fair coin, read from the
        flipping coach's point of view by `D12BallGame.resolve_coin_toss`.
        The engine's rather than the service's, like every die (decision
        7 of docs/web-app.md: the `Random` is the engine's, or the
        match's, never the service's).
        """
        return self.rng.choice((CoinFace.FORTUNE, CoinFace.DOOM))

    def initialize_standard_match(
        self,
        game: D12BallGame,
    ) -> MatchState:
        if not game.home_and_visiting_selected:
            raise ValueError(
                "Home and Visitors must be assigned first."
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

    def load_match_state(
        self,
        game: D12BallGame,
        *,
        check_turn: bool = True,
    ) -> MatchState:
        """
        The game's saved match, checked against itself. `check_turn`
        is `MatchState.validate`'s: off only for a reader about to
        clear the turn (`GameService.reset_turn`).
        """
        if game.match_state is None:
            raise ValueError("This game does not have initialized match state.")
        match = MatchState.from_dict(
            game.match_state,
            self.basic_ruleset,
        )
        match.validate(self.player_catalog, saved=True, check_turn=check_turn)
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

        if game.player_1_id is not None and user_id == game.player_1_id:
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
        return self.side_player_number(game, match.ball.possession)

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
        game: Optional[D12BallGame] = None,
    ) -> list[ShotDefender]:
        """
        Every defending player between the ball and the goal it is
        being shot at, with the defensive skill they have and the part
        of it the shot is up against -- all of it on the ball's own
        space, half of it further along. `ShotDefender.value` is the
        rule; the roll and the image both read it rather than the raw
        skill, and neither may go back to summing `defense`.

        Two special abilities reach this (Law 21). **Goopkeeper counts
        as on the ball** anywhere between the ball and the goal, at
        their full skill (`full_block`); behind the ball they are not
        in the list, like anyone else. **Flickerwing's shot** -- every
        one, off a set-up or not -- is defended by the ball's space
        alone, so the players beyond it are `passed`: still in the
        list, since they are still in the way and both pictures say
        so, but worth nothing -- except a Goopkeeper, who counts as on
        it. The shooter is the handler, which is also who the preview
        before the shot is drawn for.
        """
        in_the_way = match.defenders_between_ball_and_goal()
        clear_shot = self.has_special_ability(
            game, match.active_player_id, SpecialAbility.CLEAR_SHOT,
        )
        defenders = []
        for player_id, on_ball in in_the_way:
            full_block = self.has_special_ability(
                game, player_id, SpecialAbility.FULL_BLOCK,
            )
            player = self.get_player_definition(player_id)
            defense = self.skills(game, player_id).defense
            defenders.append(ShotDefender(
                player, defense, on_ball, full_block=full_block,
                passed=clear_shot and not (on_ball or full_block),
            ))
        return defenders

    def clear_shot_note(
        self,
        game: Optional[D12BallGame],
        shooter_id: str,
        defenders: list[ShotDefender],
    ) -> str:
        """
        Flickerwing's special ability, said wherever the shot is drawn
        -- the composition before it and the dice after -- when it
        passes somebody, so a coach sees why the players in the way
        add nothing. Nobody passed says nothing: the ability changed
        nothing about this shot.

        **The sheet's own sentence**, as `special_ability_reminder`
        gives it at a shot -- never reworded here -- after "Special
        ability", the author's word for it on the page (2026-09-28).
        """
        if not any(defender.passed for defender in defenders):
            return ""
        text = self.special_ability_reminder(game, shooter_id)
        return f"Special ability: {text}" if text else ""

    def settled_maneuver_winner(
        self,
        match: MatchState,
        game: Optional[D12BallGame] = None,
    ) -> Optional[str]:
        """
        Which maneuver wins outright, or None when a skill test still
        has to decide it.

        **Scorchit may force a test off a lost card** (Law 21), the one
        way a healthy card-loser takes a win away: once they have said
        so, `match.forced_test_player` is read beside the injury. It is
        the answer, saved, so this needs no game; the parameter stays
        for the callers that pass one.

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
        docs/design/sending-a-player.md.
        """
        if match.maneuver_uncontested:
            return match.offense_maneuver

        # A tie the dice have settled is settled: the test's winner is
        # on the match from the roll to the end of the turn, so the
        # effect that follows -- and every prompt inside it -- reads as
        # that card's rather than as a test still owed.
        if match.skill_test_winner is not None:
            return match.skill_test_winner

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
            if match.forced_test_player is not None:
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

    def forced_test_by(
        self, game: Optional[D12BallGame], match: MatchState,
    ) -> Optional[str]:
        """The Scorchit who forced this maneuver's test, or None."""
        return match.forced_test_player

    def force_test_offer(
        self, game: Optional[D12BallGame], match: MatchState,
    ) -> Optional[str]:
        """
        **Scorchit** (Law 21): the participant whose card lost on the
        cards and who may force the skill test anyway -- or None.
        Asked once, at the reveal (`turn.resolve_maneuver`); the answer
        is `match.forced_test_player`.

        A test an injury already forces is that test, not Scorchit's:
        where the card-winner is injured this answers None, and the
        test costs its ordinary token each. An injured Scorchit is not
        asked either: the test costs them 2, and an injured player uses
        no ability that would exhaust them (Law 15.4.2 c). The gambits
        need nothing of their own here -- `gambit_cost_applies` and
        `gambit_benefit_applies` read the cards, so a forced test lands
        exactly as an injury-forced one does.
        """
        if game is None or match.maneuver_uncontested:
            return None
        outcome = self.cards_outcome(match)
        if outcome not in ("offense", "defense"):
            return None
        winner_id, loser_id = (
            (match.active_player_id, match.challenger_id)
            if outcome == "offense"
            else (match.challenger_id, match.active_player_id)
        )
        # **The handler can change after the cards resolve** -- the
        # stealer takes the free Low Pass a beaten Pinpoint owes, a
        # shooter takes a set-up -- so the two ids can come to name one
        # player. That is a maneuver already settled, and nothing here
        # is owed.
        if winner_id == loser_id or winner_id in match.injured:
            return None
        if loser_id in match.injured:
            return None
        if not self.has_special_ability(
            game, loser_id, SpecialAbility.FORCES_THE_TEST,
        ):
            return None
        return loser_id

    def skill_test_tokens(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: Optional[str],
        forced_by: Optional[str] = None,
    ) -> int:
        """
        What entering a maneuver skill test costs `player_id`: 1, or
        under a test Scorchit forced (`forced_by`) 2 to Scorchit and
        nothing to their opponent.
        """
        if forced_by is not None:
            return (
                SCORCHIT_FORCED_TEST_TOKENS if player_id == forced_by else 0
            )
        return 1

    def contest_auto_winner(
        self,
        game: D12BallGame,
        match: MatchState,
        offense_player_id: str,
        defense_player_id: str,
    ) -> Optional[str]:
        """
        The contestant who takes the ball without a roll, or None:
        **Slitheron** (Law 21), in every contest for the ball -- a High
        Pass's, a loose ball's, a ball come to rest between both sides
        (the author, 2026-09-26) -- where exactly one of the two holds
        the ability; and the side that beat a **failed Cross** (Law
        19.7.7).
        """
        offense_takes, defense_takes = (
            self.has_special_ability(
                game, player_id, SpecialAbility.WINS_CONTESTS,
            )
            for player_id in (offense_player_id, defense_player_id)
        )
        # **A failed Cross gives the contest to the side that beat it**
        # (Law 19.7.7) -- the defense here, which played the Deflect or
        # Clear and has not taken the ball yet. A Slitheron of the
        # passing side wins every contest too, and the two cancel
        # (19.7.9), as two Slitherons do.
        if self.failed_cross_contest(match):
            if offense_takes:
                offense_takes = False
            else:
                defense_takes = True
        if offense_takes == defense_takes:
            return None
        return offense_player_id if offense_takes else defense_player_id

    def failed_cross_contest(self, match: MatchState) -> bool:
        """
        Whether the contest being settled follows a failed Cross gambit
        (Law 19.7.7): the maneuver still under way was a Cross beaten
        by a Deflect or a Clear. The maneuver's cards stay set until
        `finish_maneuver_resolution`, and every contest the deflection
        leads to is settled before that.
        """
        if match.offense_maneuver != "setup_pass":
            return False
        winner = match.defense_maneuver
        return winner in ("deflect", "clear") and (
            self.gambit_cost(match, winner) == "setup_pass"
        )

    def join_candidates(
        self, game: D12BallGame, match: MatchState,
    ) -> list[str]:
        """
        **Glompex** (Law 21): who may step onto the ball's space before
        this maneuver's cards are chosen -- a player with the ability,
        of either side, standing a space from the ball, not one of the
        two players and not injured, since the step exhausts 1 (Law
        15.4.2 c). Only against a challenge: Merge adds to a
        roll, and an unchallenged maneuver rolls nothing. Offense first.
        """
        if match.maneuver_uncontested or match.challenger_id is None:
            return []
        if not self.special_abilities_apply(game):
            return []
        rolling = {match.active_player_id, match.challenger_id}
        return [
            player_id
            for side in (match.ball.possession, match.defending_side())
            for player_id in match.setup_for_side(side).field_players
            if player_id not in rolling
            and player_id not in match.injured
            and match.distance_to_ball(player_id) == 1
            and self.has_special_ability(
                game, player_id, SpecialAbility.JOINS_THE_BALL,
            )
        ]

    def fly_candidates(
        self, game: D12BallGame, match: MatchState,
    ) -> list[str]:
        """
        **Zenith** (Law 21): who may fly before this run back -- a
        fielded player with the ability, of either side, who is neither
        holding the ball nor injured. Home first.
        """
        if not self.special_abilities_apply(game):
            return []
        return [
            player_id
            for side in (TeamSide.HOME, TeamSide.VISITING)
            for player_id in match.setup_for_side(side).field_players
            if player_id != match.ball_carrier_id
            and player_id not in match.injured
            and self.has_special_ability(
                game, player_id, SpecialAbility.FLY,
            )
        ]

    def fly_spaces(
        self, match: MatchState, player_id: str,
    ) -> list[tuple[Zone, int, int]]:
        """
        Where Zenith may fly to, and what each costs: every space on
        the field but their own, at a token a space travelled.
        """
        here = match.board.flat_index(*match.board.meeple_position(player_id))
        spaces = []
        for flat in range(len(match.board.spaces_in_order())):
            if flat == here:
                continue
            zone, index = match.board.position_at_flat_index(flat)
            spaces.append((zone, index, abs(flat - here)))
        return spaces

    def ball_holder(self, match: MatchState) -> Optional[str]:
        """
        Who the ball is with right now: the carrier a resolution left
        it with, or else the handler the turn chose. What "the ball
        comes to" a player means in Law 21 (Inferno, Pulsar) is this
        changing to them.

        Read with `getattr` because the driver asks it around every
        step, and the suite's stubbed steps run over a bare namespace
        standing in for a match.
        """
        return (
            getattr(match, "ball_carrier_id", None)
            or getattr(match, "active_player_id", None)
        )

    def injury_ignite(
        self, game: D12BallGame, player_id: str, face: int,
    ) -> IgnitedRoll:
        """
        What Volatile does to an injury check's die: nothing, except
        for **Kindlefinger** (Law 21), whose check ignites exactly as
        a Volatile roll does. What the ignite then does to their tokens
        is `settle_injury_ignite`'s, once the check is read.
        """
        if not self.has_special_ability(
            game, player_id, SpecialAbility.INJURY_IGNITION,
        ):
            return IgnitedRoll(face=face)
        return self.ignite(game, player_id, face)

    def settle_injury_ignite(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
        ignite: IgnitedRoll,
    ) -> str:
        """
        Kindlefinger's tokens after their check's die ignited: a blaze
        clears 1 and a burn adds 1 (Law 21), before the check is
        compared with the count (the author, 2026-09-26). An injured
        player carries none and adds none. Returns what to say, or "".
        """
        if not ignite.ignited or player_id in match.injured:
            return ""
        if ignite.burn:
            return self.apply_exhaustion(
                game, match, player_id, KINDLEFINGER_TOKEN,
            )
        removed = match.recover_exhaustion(
            player_id,
            KINDLEFINGER_TOKEN,
            self.exhaustion_threshold(game, player_id),
        )
        if not removed:
            return ""
        player = self.get_player_definition(player_id)
        return (
            f"{self.format_player_label(match, player)}'s blaze clears "
            f"{removed} token."
        )

    def attacking_skill(
        self,
        game: Optional[D12BallGame],
        match: MatchState,
        player_id: str,
        roll: str,
    ) -> int:
        """
        The skill `player_id` adds on the attacking side of `roll`:
        their offensive skill, except **Umbrik's** defensive one
        (Law 21) in an own-goal roll and a maneuver skill test over
        Umbrik's own High Pass. A contest is always offensive -- the
        High Pass contest too, which the author ruled out (2026-09-26)
        -- and is asked here so every attacking roll reads one place.

        `roll` is `"own_goal"`, `"skill_test"` (the handler's side of a
        maneuver's test) or `"contest"` (the side in possession, in a
        contest for the ball).
        """
        skills = self.skills(game, player_id)
        if self._attacks_on_defense(game, match, player_id, roll):
            return skills.defense
        return skills.offense

    def attacking_skill_name(
        self,
        game: Optional[D12BallGame],
        match: MatchState,
        player_id: str,
        roll: str,
    ) -> str:
        """
        Which skill `attacking_skill` hands back, as a word for the
        line that adds it: "Offensive", or "Defensive" for **Umbrik**
        where his Law 21 ability swaps it in -- asked beside the number
        so a sentence never names one skill and adds the other.
        """
        if self._attacks_on_defense(game, match, player_id, roll):
            return "Defensive"
        return "Offensive"

    def _attacks_on_defense(
        self,
        game: Optional[D12BallGame],
        match: MatchState,
        player_id: str,
        roll: str,
    ) -> bool:
        """Umbrik's swap (Law 21): his defensive skill on the attack in
        an own-goal roll and a skill test over his own High Pass."""
        if not self.has_special_ability(
            game, player_id, SpecialAbility.DEFENSIVE_THROW,
        ):
            return False
        return roll == "own_goal" or (
            roll == "skill_test" and match.offense_maneuver == "high_pass"
        )

    def re_roll_tokens(
        self, game: D12BallGame, player_id: Optional[str],
    ) -> int:
        """
        The token a tie's re-roll costs `player_id`, in a maneuver
        skill test or a contest for the ball: 1 for everybody. It stays
        a question, asked of the player, because the answer used to
        depend on who was asked (Zorch's free tests, until 2026-09-27)
        and a special ability is the kind of thing that changes it.
        """
        return 1

    def speed_roll_bonus(
        self,
        game: Optional[D12BallGame],
        match: MatchState,
        player_id: Optional[str],
    ) -> tuple[int, str]:
        """
        **Zorch** adds a ball speed modifier of their own to every roll
        they make (Law 21.6.6): **half the speed, rounded down** -- not
        `BallState.speed_modifier`, the full speed everyone else adds
        (the author, 2026-10-01). The number, and the line the dice list
        it under, or `(0, "")` for anybody else or a ball at speed 1 --
        a bonus of nothing says nothing.

        The caller asks only where the roll does not already add the
        modifier to Zorch's side -- Zorch shooting, contesting a
        maneuver with Steal or Intercept, or holding the thrower's side
        of a High Pass contest -- because Zorch adds it once, not twice
        (the author, 2026-09-27) -- and there the full modifier is what
        is added, not this. It is never signed: a High Pass that reaches the goal zone counts the
        modifier against itself, and Zorch's own bonus is not that
        pass's.
        """
        if not self.has_special_ability(
            game, player_id, SpecialAbility.SPEED_ROLLS,
        ):
            return 0, ""
        modifier = match.ball.speed // 2
        if not modifier:
            return 0, ""
        return modifier, f"+{modifier} ball speed modifier"

    def controlling_player_number(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
    ) -> Optional[int]:
        """
        Which coach controls whichever team `player_id` belongs to,
        independent of ball possession -- safe to call right after a
        turnover flips possession, unlike `possession_player_number`.
        What a sentence addresses that coach by (`tokens.coach`);
        `controlling_user_id` below is the account behind it, for the
        frontend's gates.
        """
        side = (
            TeamSide.HOME
            if player_id in match.home.field_players
            else TeamSide.VISITING
        )
        return self.side_player_number(game, side)

    def controlling_user_id(
        self,
        game: D12BallGame,
        match: MatchState,
        player_id: str,
    ) -> Optional[int]:
        """
        The Discord user controlling whichever team `player_id` belongs
        to -- `controlling_player_number`'s account.
        """
        number = self.controlling_player_number(game, match, player_id)
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
        number = (
            self.possession_player_number(game, match)
            if side == "offense"
            else self.defending_player_number(game, match)
        )
        return game.ai_holds(number)

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
        Which of Cross's distances -- 0, 1 and 3, plus 4 for a
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
        last space before the goal zone -- the only position from which
        even 1 would reach it -- with no teammate beside them, which
        is the whole of when a Cross can go out of play.

        **The Fullback's ability is +1 distance, and that is what it
        inherits** (the author, 2026-08-19). Its sentence reads "High
        pass up to 4", which read as a number is a fourth distance
        against a card that offers 0, 1 and 3 -- and read as the rule
        behind the number is the same +1 that takes a basic High Pass
        from 3 to 4 and a Clear from 3 to 4. The rule is what carries,
        so the extra distance is appended rather than replacing the 3.
        """
        offense_side = match.ball.possession

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
            # A Cross never reaches the goal zone (Law 19.7.6): a
            # throw that would is a shorter pass wearing a longer one's
            # label, which is the reason `high_pass_distances` drops
            # one too.
            if match.ball_reaches_goal_zone(offense_side, distance):
                continue
            legal.append(distance)
        return legal

    def double_team_partner_candidates(self, match: MatchState) -> list[str]:
        """
        Who a Double Team's partner may be (Law 19.10.3): the defending
        players other than the challenger standing **nearest the ball,
        on its space or behind it** -- behind meaning toward the
        defending side's own goal -- every one tied for nearest, in
        `field_players` order. Empty where nobody else of theirs is on
        the ball's space or behind it, and then nobody joins.

        Measured before anything moves: by the time a maneuver resolves
        the ball has not moved yet, so the ball's space is where the
        play started. A defender ahead of the ball, between it and the
        goal the defense attacks, is never a candidate however near.
        """
        defense_side = match.defending_side()
        ball_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        # +1 where the defense attacks toward the higher indexes.
        forward = match.unclamped_flat_index(0, defense_side, 1)
        distances: list[tuple[int, str]] = []
        for player_id in match.setup_for_side(defense_side).field_players:
            if player_id == match.challenger_id:
                continue
            position = match.board.meeple_position(player_id)
            if position is None:
                continue
            ahead = (match.board.flat_index(*position) - ball_flat) * forward
            if ahead > 0:
                continue
            distances.append((-ahead, player_id))
        if not distances:
            return []
        nearest = min(distance for distance, _ in distances)
        return [
            player_id for distance, player_id in distances
            if distance == nearest
        ]

    def double_team_partner(self, match: MatchState) -> Optional[str]:
        """
        The partner a Double Team brings in, won or beaten: the one the
        defending coach chose where several tied
        (`DOUBLE_TEAM_PARTNER`), recorded on the maneuver's continuation
        as `{"kind": "double_team_partner", "player_id": ...}`, or the
        only candidate. None where nobody joins, or where a tie is still
        to be chosen -- `double_team_partner_owed` says which.

        Once the card has been applied the record is written whoever
        was asked, so a reading after the board has moved returns the
        partner the card used rather than measuring again from the
        wrong space.
        """
        recorded = match.pending_effect_continuation or {}
        if recorded.get("kind") == DOUBLE_TEAM_PARTNER_KIND:
            return recorded.get("player_id")
        candidates = self.double_team_partner_candidates(match)
        return candidates[0] if len(candidates) == 1 else None

    def double_team_partner_owed(
        self, match: MatchState, winner_key: str,
    ) -> bool:
        """
        Whether the defending coach still has to choose a Double Team's
        partner from a tie (Law 19.10.3) before the maneuver resolves:
        the card resolving is a won Double Team, or the card that beat
        one, which moves the same partner forward (19.10.6). Asked once
        the winner is settled and before its effect, so the partner is
        measured from where the play started.
        """
        recorded = match.pending_effect_continuation or {}
        if recorded.get("kind") == DOUBLE_TEAM_PARTNER_KIND:
            return False
        if "double_team" not in (
            winner_key, self.gambit_cost(match, winner_key),
        ):
            return False
        return len(self.double_team_partner_candidates(match)) > 1

    def record_double_team_partner(
        self,
        match: MatchState,
        partner_id: Optional[str],
        merges: bool = False,
    ) -> None:
        """
        Write down the Double Team's partner -- chosen by a coach, or
        the only one there was -- so every later reading this maneuver
        (`double_team_partner`) is that player. `reset_maneuver`
        clears it with the rest of the maneuver.

        `merges` marks the won Double Team that has just granted the
        partner Merge, which `finish_maneuver_resolution` reads to keep
        `pending_double_team` past this maneuver and no further.
        """
        record = {"kind": DOUBLE_TEAM_PARTNER_KIND, "player_id": partner_id}
        if merges:
            record["merges"] = True
        match.pending_effect_continuation = record

    def pass_speed_bonus(self, maneuver_key: str) -> int:
        """
        What a pass adds to ball speed: Low Pass's +1, or
        Pinpoint's +3. Both are capped at 12 by the caller, the way every
        speed change is.
        """
        return 3 if maneuver_key == "skilled_pass" else 1

    def skilled_pass_candidates(
        self,
        match: MatchState,
    ) -> list[tuple[int, str]]:
        """
        Pinpoint's destinations: **any** teammate within
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
        would reach the goal zone are dropped by `low_pass_receivers`,
        so a
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
        How far a Burst may be run: 1 up to
        `DRIBBLE_BURST_MAX_DISTANCE`, one more for a Playmaker, cut
        short by the field. It is the coach's pick, and it is charged
        a token a space -- which is what makes the shorter runs worth
        offering.

        **It used to be no choice at all.** The card ran the handler
        to the last space of the goal they attack, so the distance was
        read off the board and the only thing the coach settled was
        the ball speed after it. The author bounded the run at 4 on
        2026-08-26; a burst from deep now stops short of the goal, and
        a burst from inside 4 spaces of the end still reaches it.

        Empty from the last space of the field itself, which is the
        one position with nothing to ask -- `resolve_dribble_burst`
        applies a run of 0 rather than putting up a menu with no
        buttons on it. **The Playmaker's ability moved onto the run
        on 2026-09-26**, reversing the 2026-08-19/2026-08-26 reading
        that kept it a token off the cost instead -- the sheet's
        sentence now names an additional space on either Dribble card,
        so this is where that space is offered rather than
        `dribble_burst_cost` discounting it.
        """
        handler = self.get_player_definition(match.active_player_id)
        playmaker_bonus = 1 if handler.role == PlayerRole.PLAYMAKER else 0
        reach = min(
            DRIBBLE_BURST_MAX_DISTANCE + playmaker_bonus,
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
        Pinpoint's any-teammate-within-3, or a Low Pass's nearest
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

        Usually one, and then the destination *is* the choice. A space
        a coach has stacked makes two ordinary, and which of them
        receives the ball is the passer's to pick: it decides who a Winger's set-up hands the
        shot to. Empty when the distance would reach the goal zone, or
        when the space holds nobody but the handler.
        """
        offense_side = match.ball.possession
        offense_players = set(match.setup_for_side(offense_side).field_players)
        origin_flat = match.board.flat_index(
            match.ball.zone, match.ball.space_index,
        )
        # A pass is played to a teammate on a space, so a distance
        # that reaches the goal zone has nobody to reach and is no
        # candidate.
        if match.goal_zone_reached(
            origin_flat, offense_side, distance,
        ) is not None:
            return []
        target_flat = match.relative_flat_index(
            origin_flat, offense_side, distance,
        )

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
        that reach the goal zone. Empty when even the shortest does,
        which is the case where it reaches the goal zone before anyone
        chooses.

        One home for both halves of that, because three things have to
        agree about what is on offer: the menu a coach sees, what the
        AI picks from, and the refusal that catches a click on a menu
        the ball has moved out from under.
        """
        handler = self.get_player_definition(match.active_player_id)
        max_distance = (
            FULLBACK_PASS_REACH if handler.role == PlayerRole.FULLBACK else 3
        )
        return match.high_pass_distances(match.ball.possession, max_distance)

    def pass_ability_note(self, distance: int) -> str:
        """
        " (Fullback ability)" for the one distance only a Fullback's
        reach puts on a High Pass or Cross menu, else "". Which
        distance that is, is a rule (`high_pass_distance_options`,
        `setup_pass_distances`), so the menu asks here rather than
        knowing the number.
        """
        return " (Fullback ability)" if distance == FULLBACK_PASS_REACH else ""

    def dribble_burst_cost(
        self,
        match: MatchState,
        distance: int,
        game: Optional[D12BallGame] = None,
    ) -> int:
        """
        What a Burst of `distance` charges the handler: a token
        a space. Nothing at all for Emberdash (Law 21). The step
        charges this and the menu prices its buttons by it.

        **No longer a Playmaker discount** (the author, 2026-09-26):
        the ability moved onto `dribble_burst_distances` as the extra
        space its sheet sentence names, so the cost here is everybody's
        same token a space, including a Playmaker's fifth.
        """
        if self.has_special_ability(
            game, match.active_player_id, SpecialAbility.FREE_BURST,
        ):
            return 0
        return distance

    def pass_runner_on_field(
        self, game: Optional[D12BallGame], match: MatchState,
    ) -> Optional[str]:
        """
        **Quantor** (Law 21): the player of the side on the ball who
        could run onto a teammate's High Pass or Cross, whichever
        distance it goes -- never the handler, who is the one passing,
        and never an injured player -- or `None`. `pass_runner` narrows
        it to the distances a pass is offered; a frontend saying the
        ability is there before the cards are chosen asks this.
        """
        if game is None or not self.special_abilities_apply(game):
            return None
        return next(
            (
                player_id
                for player_id in match.setup_for_side(
                    match.ball.possession,
                ).field_players
                if player_id != match.active_player_id
                and player_id not in match.injured
                and self.has_special_ability(
                    game, player_id, SpecialAbility.RUN_ON,
                )
            ),
            None,
        )

    def pass_runner(
        self,
        game: Optional[D12BallGame],
        match: MatchState,
        distances: Collection[int],
    ) -> tuple[Optional[str], tuple[int, ...]]:
        """
        **Quantor** (Law 21): the passing side's player who may drain 3
        to run onto a teammate's High Pass or Cross, and the
        distances they may run onto -- or `(None, ())`.

        Never the passer, never an injured player, and only a distance
        that lands on a space: a High Pass that reaches the goal zone
        comes to rest short of where it was aimed, so there is no target
        space to run to. The distances are the prompt's own, so this
        narrows what is already offered rather than offering anything
        new. Carried on the prompt's options, so the button, the refusal
        and the web app read one answer.
        """
        runner = self.pass_runner_on_field(game, match)
        if runner is None:
            return None, ()
        side = match.ball.possession
        # A Cross only offers distances on the field already, so
        # the test only ever removes a High Pass into the goal zone; it is
        # asked of both so a Cross that grew one could not slip by.
        reachable = tuple(
            distance
            for distance in distances
            if not match.high_pass_reaches_goal_zone(side, distance)
        )
        return (runner, reachable) if reachable else (None, ())

    def dribble_advance_distances(
        self, game: Optional[D12BallGame], match: MatchState,
    ) -> tuple[int, ...]:
        """
        How far a Playmaker's Dribble may go: up to 2, or
        Emberdash's 3 (Law 21). Everybody else advances 1 and is not
        asked (`offer_dribble_advance`).
        """
        if self.has_special_ability(
            game, match.active_player_id, SpecialAbility.FREE_BURST,
        ):
            return tuple(range(1, EMBERDASH_ADVANCE_MAX + 1))
        return (1, 2)

    def dribble_burst_note(
        self, game: D12BallGame, match: MatchState, distance: int,
    ) -> str:
        """
        Where a burst of `distance` lands and what it costs -- "space 5,
        2 exhaustion" -- for the button offering it. The cost is named
        by what it is ("drain" for a Cyborg, `token_word_and_mark`),
        never as bare "tokens": the board carries other tokens too. Naming the destination
        is what "3 spaces" does not say: which way this side attacks
        and where that lands is read off the board, and the board has
        usually scrolled away.
        """
        zone, space_index = match.relative_move_destination(
            match.active_player_id, match.ball.possession, distance,
        )
        cost = self.dribble_burst_cost(match, distance, game)
        noun, _ = self.token_word_and_mark(game, match.active_player_id)
        where = space_label(zone, space_index, match.board)
        return f"{where}, {cost} {noun}"


    def speed_targets(
        self,
        match: MatchState,
        player_id: str,
        skill_type: str,
        game: Optional[D12BallGame] = None,
    ) -> list[int]:
        """
        The ball speeds a player's speed manipulation may set: every
        speed within their skill of the current one, clamped to the
        ball's range, ascending. `skill_type` says which of their two
        skills is the reach -- the offense's on a dribble or a
        Cross, the defense's on a steal.

        **One computation**, since step 6 of
        docs/architecture-migration.md: it used to be written in the
        driver, the view (with a hard-coded 12) and the full-game
        policy, and the three could only agree by care.
        """
        reach = self.skills(game, player_id).of(skill_type)
        return sorted({
            max(1, min(BALL_SPEED_MAX, match.ball.speed + delta))
            for delta in range(-reach, reach + 1)
        })

    def high_pass_receiver_candidates(
        self,
        match: MatchState,
        offense_side: TeamSide,
    ) -> list[str]:
        """
        Who a High Pass reached: the offense on the space it landed
        on, less the passer -- **a passer never receives their own
        pass** (2026-08-12). See "High Pass" in the living rules.

        It is the one reading of that, asked by the goal zone's
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
        Offensive players occupying the ball's current space (the
        last one, where a High Pass reached the goal zone) -- the field of shooter candidates a set-up offers,
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
        Settle whichever side has no choice to make. A side with no
        candidates at all is left unset -- resolve_loose_ball reads
        that as "nobody available", not "still deciding".

        A lone candidate is *not* auto-picked, unlike a forced run
        back: sending them is optional, and declining is what puts the
        ball out of bounds, so one candidate is still a real choice
        between two outcomes.

        **A lone player standing on the ball is**, because there is
        nothing to ask: they contest for nothing and their side may not
        withhold them, so the only choice a prompt could offer is one
        the rules refuse. Two is the coach's pick, the same count-not-a-
        flag reading choose_action makes of automatic_challengers.

        An AI side is asked like a coach and answers through the
        service (`AIStrategy.choose`); until step 7 of
        docs/architecture-migration.md this picked for it.
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

    def build_loose_ball_headline(
        self,
        match: MatchState,
        game: Optional[D12BallGame] = None,
    ) -> str:
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
            f"{format_team_side_label(taking, game)} has a player, so they get "
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
        return game.ai_holds(self.side_player_number(game, side))

    def side_player_number(
        self,
        game: D12BallGame,
        side: TeamSide,
    ) -> Optional[int]:
        """Which coach plays this side of the board -- `None` before
        the coin has seated anybody."""
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

    def half_substitutions_label(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> str:
        """
        What `side` has left of its two for the half, for the roster:
        "1 substitution left this half". Nothing once the second half
        is over -- the full-time window, the shootout, a finished game
        -- since there is no half left to spend them in, and full
        time's one is the window's own to say
        (`substitution_allowance_label`).
        """
        if (
            game.is_finished
            or match.pending_full_time_stage is not None
            or match.pending_shootout
        ):
            return ""
        left = match.half_substitutions_left(side)
        if not left:
            return "No substitutions left this half"
        return f"{left} substitution{'s' if left != 1 else ''} left this half"

    def defense_ordered_field_players(
        self,
        match: MatchState,
        side: TeamSide,
        game: Optional[D12BallGame] = None,
    ) -> list[str]:
        """
        A side's six, best defender first. Ties break at random, which
        never happens between the six standard roles -- their defences
        are 1 to 6 -- but a shuffled tie is better than one settled by
        whatever order the zones happened to be in.
        """
        players = list(match.setup_for_side(side).field_players)
        self.rng.shuffle(players)
        return sorted(
            players,
            key=lambda player_id: -self.skills(game, player_id).defense,
        )

    def formation_placement(
        self,
        match: MatchState,
        side: TeamSide,
        formation: Formation,
        game: Optional[D12BallGame] = None,
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
        ordered = self.defense_ordered_field_players(match, side, game)

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
            # Zenith flew, and does not run back (Law 21).
            and player_id not in match.run_back_flown
        ]

    def run_back_crowded(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> list[str]:
        """
        The players of `side` a stack could send back --
        `match.crowded_candidates(side)`, which offers every teammate
        on a shared space rather than picking one, because which of
        them goes is the coach's call.

        `spread_exempt_ids` rides along (see `spread_exempt_ids`): a
        Spreadable Ooze sharing a space with one zone-native teammate
        is a stack of one once the Ooze is disregarded, so the pair is
        never offered here at all -- see "Slimey" in docs/design/species-abilities.md.
        """
        return match.crowded_candidates(
            side, self.spread_exempt_ids(game, match, side),
        )

    def run_back_movers(
        self,
        game: D12BallGame,
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
            + self.run_back_crowded(game, match, side)
        )

    def charge_up_amount(self, game: D12BallGame, player_id: str) -> int:
        """
        The drain a Cyborg's Charge-up removes: 1, or Strider's 2
        (Law 21).
        """
        if self.has_special_ability(
            game, player_id, SpecialAbility.EFFICIENT_RUN,
        ):
            return STRIDER_CHARGE_UP
        return 1

    def run_back_cost(
        self, game: D12BallGame, player_id: str, distance: int,
    ) -> int:
        """
        The tokens a run back of `distance` spaces charges this player:
        one a space, or for Strider 1 at most (Law 21).
        """
        if self.has_special_ability(
            game, player_id, SpecialAbility.EFFICIENT_RUN,
        ):
            return min(distance, STRIDER_RUN_BACK_MAXIMUM)
        return distance

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
                # nothing" in docs/design/naming-and-wording.md.
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
                exempt_ids = self.spread_exempt_ids(game, match, side)
                by_zone: dict[Zone, list[str]] = {}
                for player_id in self.run_back_displaced(match, side):
                    by_zone.setdefault(
                        setup.assigned_zone(player_id), [],
                    ).append(player_id)

                settled: dict[Zone, list[str]] = {}
                for player_id in self.run_back_crowded(game, match, side):
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

                    open_spaces = match.open_spaces_in_zone(
                        side, zone, exempt_ids,
                    )
                    if len(open_spaces) != len(players):
                        continue
                    for player_id, space_index in zip(players, open_spaces):
                        distance = match.run_back_player(
                            player_id, zone, space_index, exempt_ids,
                        )
                        match.add_exhaustion(
                            player_id,
                            self.run_back_cost(game, player_id, distance),
                        )
                        # A forced run back is applied silently, so
                        # there is no message here to carry the
                        # threshold test the way apply_exhaustion's
                        # does -- but the flag still has to be set
                        # before the caller's save.
                        self.retest_exhausted(game, match, player_id)
                    applied_forced = True

    def next_run_back_step(
        self,
        game: D12BallGame,
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
            crowded = self.run_back_crowded(game, match, side)
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

    def shootout_running_score(
        self,
        match: MatchState,
        game: Optional[D12BallGame] = None,
    ) -> str:
        """
        The shootout's own score, which is not the scoreboard's: the
        goals are on that too, but 6:5 says nothing about how many of
        the six have gone. Each side the long way where a coach holds
        it (`score_side_label`).
        """
        home = match.shootout_goals_for(TeamSide.HOME)
        visiting = match.shootout_goals_for(TeamSide.VISITING)
        return (
            f"{score_side_label(match.home, game)} {home} — {visiting} "
            f"{score_side_label(match.visiting, game)}"
        )

    def shootout_heading(
        self,
        match: MatchState,
        game: Optional[D12BallGame] = None,
    ) -> str:
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
            f"{self.shootout_running_score(match, game)}"
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
            if self.has_special_ability(
                game, player_id, SpecialAbility.HIGH_DRAIN_THRESHOLD,
            ):
                return BULWARK_DRAINED_AT - 1
            return CYBORG_DRAINED_AT - 1
        return self.skills(game, player_id).defense

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
        whether it comes back -- a Cross into an empty space is
        loose and one into a space only the defense holds is simply
        theirs, so "no teammate" on its own withholds the half of the
        answer the coach is weighing.
        """
        offense_side = match.ball.possession
        zone, space_index = match.ball_destination(offense_side, distance)
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
            return f"{space_label(zone, space_index, match.board)}, no teammate"
        teammate = self.get_player_definition(occupants[0])
        return (
            f"{space_label(zone, space_index, match.board)}, "
            f"{player_with_role(teammate)}"
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

        The coach is named with their side's mark (see
        `format_player_with_team`).
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
        game: Optional[D12BallGame] = None,
    ) -> str:
        """Switch a side into `formation` and describe where they land."""
        side = TeamSide(side)
        placement = self.formation_placement(match, side, formation, game)
        match.deploy_side(side, placement)

        setup = match.setup_for_side(side)
        board_size = match.board.layout.board_size
        lines = [
            f"**{format_team_side_label(setup, game)} switches to "
            f"{formation.value}.** Best defenders furthest back; "
            "rearranging costs no exhaustion."
        ]
        for area in SETUP_AREAS:
            zone = zone_for_area(side, area)
            names = ", ".join(
                f"{self.format_roster_player_for_message(player_id, setup.team)} "
                f"({space_label(zone, space_index, match.board)})"
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
        header = (
            f"**{format_team_side_label(setup, game, mention=True)}** -- "
            f"{self.substitution_allowance_label(match)}."
        )
        return "\n".join(
            part
            for part in (
                lead_in,
                "# Coaching Choice",
                header,
                note,
                self.spreadable_note(game, match, side),
            )
            if part
        )

    def spreadable_note(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
    ) -> str:
        """
        The reminder every Coaching Choice carries for a side fielding
        **Spreadable** Oozes (the author, 2026-09-25): an Ooze counts as
        0 toward occupancy, so it may share a teammate's space -- see
        `spread_exempt_ids`.

        It rides on the window's text itself rather than on the note of
        the step that opened it, because that note is written over by
        the next action and this one holds for the whole window. A
        window that positions nobody (before the shootout) says
        nothing: where anybody stands is not a question there.
        """
        occasion = match.coaching_occasion
        if occasion is not None and not occasion.offers_positioning:
            return ""
        if not self.spread_exempt_ids(game, match, side):
            return ""
        return SPREADABLE_NOTE

    def coaching_finish_refusal(
        self,
        match: MatchState,
        side: TeamSide,
        game: Optional[D12BallGame] = None,
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

        Both sides kick off from the same midfield space, so both have
        to cover it; this still asks each side about its own, because
        the coverage belongs to the arrangement rather than to the
        space.
        """
        side = TeamSide(side)
        occasion = match.coaching_occasion
        if occasion is None or not occasion.offers_positioning:
            return None
        if match.kickoff_space_occupied_by(side):
            return None
        kickoff_space = space_label(
            Zone.MIDFIELD, match.kickoff_space_for(side), match.board,
        )
        # The coach and their end, as the long way names a side but
        # without the team's mark: a refusal reaches a coach as plain
        # text, which no frontend renders a token in.
        who = (
            format_team_side_label(match.setup_for_side(side), game, mark=False)
            if side_coach_number(game, side) is not None
            else side_display_name(side)
        )
        return (
            "Every arrangement has to cover its own kickoff space, so "
            f"{who} needs a player on "
            f"{kickoff_space} "
            "before finishing."
        )

    def turn_reset_refusal(self, match: MatchState) -> Optional[str]:
        """
        Why the turn may not be thrown away here, or None -- the gate
        on the recovery command's `force` (`GameService.reset_turn`).

        Setup, halftime, the window before the shootout, the shootout
        itself and a time out are **real positions in the game rather
        than a turn gone wrong**, and clearing "the turn" under any of
        them would drop something a coach has already done: the
        shootout most of all, where there is no turn to clear and the
        orders both coaches set would go with it; a time out has
        already reset the turn and handed the ball over, so a cleared
        one would ask the receiving side to act with nobody on the
        ball. A plain resume walks each of them on instead.
        """
        if (
            match.pending_setup_stage is not None
            or match.pending_halftime_stage is not None
            or match.pending_full_time_stage is not None
            or match.pending_shootout
            or match.pending_time_out
        ):
            return (
                "This game is in setup, at halftime, in the extreme "
                "shootout, or in a time out -- none of which clearing "
                "the turn can skip past."
            )
        return None

    def turn_in_progress(self, match: MatchState) -> Optional[str]:
        """
        What this turn is still waiting on, named -- "a maneuver
        challenge", "a score attempt", "an own goal roll", "an injury
        test" -- or `None` where the offense has nothing pending. The
        gate on starting the offensive choice over without `force`:
        a turn that is merely waiting wants its prompt back, not
        throwing away.

        An owed roll is read on its own because it leaves
        `pending_action` clear (choosing the challenger cleared it
        when the maneuver started).
        """
        if match.pending_action == "maneuver":
            return "a maneuver challenge"
        if match.pending_action == "shoot":
            return "a score attempt"
        if match.pending_own_goal:
            return "an own goal roll"
        if match.pending_injury_tests:
            return "an injury test"
        return None

    def time_out_confirmation(
        self,
        game: D12BallGame,
        match: MatchState,
    ) -> str:
        """
        What the coach is agreeing to, in place of the turn prompt --
        see TimeOutConfirmView. The author's wording, 2026-09-16.

        **It names no "Coaching Choice".** A coach reading a confirm
        screen has not read the rules document, and the term does not
        tell them what they get; the two things they actually get --
        substitutions, and moving people about -- are said in the words
        the buttons on the next screen use. The rules keep the name
        (see "Coaching Choice" in docs/living-rules.md); this message
        does not need it.

        **"May" is right here and is not vagueness.** Pressing Time out
        is itself the choice, and Back is still on this screen, so the
        coach genuinely may do this or not. What must not be vague is
        what *follows* from pressing it, which is why everything after
        the first sentence is flat future tense: play *will* stop, the
        other coach *would* then be allowed the same.

        It says who has the ball afterwards, which a cede's version of
        this message could not: possession does not move now, and that
        is the whole of what changed on 2026-09-16.
        """
        # No team mark: the view puts this up as it is (see
        # `format_team_side_label`'s `mark`).
        other = format_team_side_label(
            match.setup_for_side(match.defending_side()), game, mark=False,
        )
        where = ball_space_label(match)
        return "\n".join([
            "# Take a time out?",
            "You may take a time out once per half. If you do, play "
            "will stop and you'll be able to substitute players or "
            f"change formation/assignment. Then, {other} would be "
            "allowed to do the same. A time out is a new play: it takes "
            "1 minute, both teams go back to the positions their "
            "coaches set, and play resumes with the ball at "
            f"{where} at speed 1, with you in possession.",
        ])

    def describe_run_back_options(
        self,
        game: D12BallGame,
        match: MatchState,
        side: TeamSide,
        player_id: str,
    ) -> str:
        """
        The spaces `player_id` may run back to in their own zone, and
        how far off each one is -- the question the buttons underneath
        ask, said once as a sentence.

        It reads as the offer it is ("space 4 (1 away) or space 5 (2
        away)") rather than as a list with a rule under it. The
        "Options:" heading labelled something already sitting in front
        of the coach, and the token-a-space clause restated a price the
        distances are already quoting: every one of these buttons
        charges a token a space, so a coach comparing 1 against 2 is
        comparing the cost whether or not the sentence says so.
        """
        zone = match.setup_for_side(side).assigned_zone(player_id)
        spaces = match.placement_spaces_in_zone(
            side, zone, player_id, self.spread_exempt_ids(game, match, side),
        )
        if not spaces:
            return "No space in their zone."
        options = [
            travel_space_phrase(
                zone, index, match.run_back_distance(player_id, zone, index),
                match.board,
            )
            for index in spaces
        ]
        # "A or B", "A, B or C" -- the last one joined with the word
        # that says these are alternatives, since exactly one of them
        # is going to be pressed.
        if len(options) == 1:
            offer = options[0]
        else:
            offer = f"{', '.join(options[:-1])} or {options[-1]}"
        # The offer is a sentence of its own, and "space 4 ..." opens it.
        return f"{offer[:1].upper()}{offer[1:]}."

    def shootout_mentions(
        self,
        game: D12BallGame,
        match: MatchState,
        sides: list[TeamSide],
    ) -> str:
        """
        Whoever a shootout step is still waiting on, addressed -- the
        coach of each side (`{coach:n}`), or the side itself where
        nobody coaches it yet.
        """
        parts = []
        for side in sides:
            number = self.side_player_number(game, side)
            parts.append(
                tokens.coach(number)
                if number in (1, 2)
                else format_team_side_label(match.setup_for_side(side))
            )
        return " and ".join(parts) or "Someone"

    def shootout_button_label(
        self,
        game: D12BallGame,
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
        name = player_with_role(player)
        if match is not None and player_id in match.injured:
            word = (
                "damaged"
                if self.has_species_ability(game, player_id, SPECIES_CYBORG)
                else "injured"
            )
            return f"{name} {word}"
        offense = self.skills(game, player_id).offense
        return f"{name} +{offense}"

    def format_roster_player(self, player_id: str) -> str:
        """
        `player_with_role` for a caller holding a card id -- "Hellguard
        [FB]", the one spelling every label in the game uses. See
        "Naming a player" in docs/design/naming-and-wording.md.

        It spelled the role in parentheses until 2026-09-16, which read
        as a second form of the same thing and collided with whatever
        the caller put after it: the halftime buttons came out
        "Hellguard (FB) (3)" and the roster listing "Hellguard (FB)
        (M2)". Brackets leave the parentheses to mean one thing.
        """
        return player_with_role(self.get_player_definition(player_id))

    def format_roster_player_for_message(
        self, player_id: str, team: Optional[Team] = None,
    ) -> str:
        """
        `format_roster_player` for text going into a *message*, where
        the role badge renders -- "Hellguard {role:fullback:orange}",
        a token the frontend draws as the badge once uploaded and as
        the brackets until then (`d12ball/tokens.py`).

        Two methods rather than a flag because the plain form is the
        safe default: the same markup in a button label or an
        autocomplete choice shows as the raw `<:...:>`, and every
        caller of `format_roster_player` outside this module is one of
        those. The two message builders here (`apply_formation`
        and `build_turn_prompt`) are the ones that ask for this.

        `team` is which side the card is being fielded as, and asks
        for the badge in that side's colour -- see `role_badge`. Both
        callers have it in scope; it is optional only so that a third
        one with no side to give falls back to the plain badge rather
        than being unable to call this at all.
        """
        return player_with_role(
            self.get_player_definition(player_id), badge=True, team=team,
        )

    def format_player_label(
        self, match: MatchState, player: PlayerDefinition,
    ) -> str:
        """
        "🟠 Hellguard [FB]" -- a player named the way every message
        outside this engine's own two builders names them, with the
        team mark in front as well as the role badge, both as tokens
        (`{team:orange} Hellguard {role:fullback:orange}`) for the
        frontend to draw. `D12Ball.player_label` renders this so no
        call site moved.

        **Distinct from `format_roster_player_for_message` on
        purpose, not a flag on it.** That one is the narrower form --
        role badge only, no team emoji -- for `apply_formation` and
        `build_turn_prompt`, where a team emoji next to a card already
        on that team's board would say nothing new. This one wants
        both, for the run-back and injury-test prompts and every other
        message that names a player without a board already in view.
        Two methods by name keeps each caller asking for the form it
        actually wants, rather than threading a flag through both.
        """
        team = match.team_for_player(player.player_id)
        return (
            f"{tokens.team(team)} "
            f"{player_with_role(player, badge=True, team=team)}"
        )

    def format_roster_player_with_team(
        self, player_id: str, team: Team,
    ) -> str:
        """
        The same, plus the team in words -- for the two autocompletes
        that list *both* sides at once, where the name alone is
        ambiguous whenever the same person is fielded on each (see
        "One player, both sides"). The team is spelled out rather than
        drawn as an emoji because an autocomplete choice is plain text.
        """
        return (
            f"{self.format_roster_player(player_id)} "
            f"({team_display_name(team)})"
        )

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
        # both sides" in docs/design/teams-and-players.md.
        # The side's own cards, in the catalog roster's order: a game
        # saved before a roster change holds a player today's roster
        # no longer lists, and still lists them, after the rest (see "A
        # roster change and a saved game" in docs/design/gotchas.md).
        held = (
            setup.field_players
            + setup.team_board.bench
            + setup.team_board.back_bench
        )
        catalog_order = [
            setup.card_id_for(player.player_id)
            for player in self.player_catalog.teams[setup.team].players
        ]
        roster_order = {
            card_id: index
            for index, card_id in enumerate(
                [card_id for card_id in catalog_order if card_id in held]
                + [card_id for card_id in held if card_id not in catalog_order]
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
                    (player_id, space_label(zone, space_index, match.board))
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
            # There used to be a second line here, for Slip in: a
            # named carrier *plus* the Telekinetics who could take the
            # turn off them, which was the one case where this list
            # held more than one name while somebody already had the
            # ball. Smooth settles that at the arrival gate instead
            # (2026-09-20), so a carrier is now always the whole list
            # and the branch had become unreachable.
            return (
                f"{controller}, it is your turn.\n\n"
                "Choose which player in the ball's space will take "
                "an action."
            )

        handler = self.format_roster_player_for_message(
            match.active_player_id,
            match.team_for_player(match.active_player_id),
        )
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
        # range and offers the time out in its place, so say why rather
        # than leaving a coach to wonder where either went. The two are
        # the same read: out of range is exactly when a time out is on
        # offer, and what can take it away as well is the side's time
        # out already spent, or last possession declared.
        #
        # Each says the reason once and then names what is left. The
        # third used to spell out both absences as well ("so there is
        # no shot and no cede -- only a maneuver"), which listed two
        # buttons that are not on the message in order to introduce the
        # one that is -- and did it on every turn for the rest of a
        # half, since a spent time out does not come back.
        if match.can_attempt_score():
            action_line = "Choose an action:"
        elif match.may_call_time_out():
            action_line = (
                "Out of shooting range. Maneuver, or take a time out:"
            )
        else:
            action_line = (
                "Out of shooting range, and no time out available. "
                "Maneuver:"
            )
        return (
            f"{controller}, it is your turn.\n\n"
            f"{handler_line}\n\n"
            f"{action_line}"
        )
