"""
The tokens narration leaves for a frontend, and Discord's rendering of
them -- step 9 of docs/architecture-migration.md.

The model writes `{team:purple}`, `{role:fullback:orange}`,
`{condition:exhaust}`, `{species:cyborg}` and `{coach:1}`
(`d12ball/tokens.py`), and knows no emoji and no mention;
`cogs.d12ball_helpers.DiscordTokens` draws each from what the cog has
fetched, with the same fallbacks the model used to hold. Two things
are pinned here: that the spelling is the builders' alone, and that
nothing the bot posts still carries a token -- the three golden
transcripts are what the cog sent, so a `{` in one is a sentence the
frontend forgot to render.
"""

import pathlib
import unittest

from cogs.d12ball_helpers import (
    DiscordTokens,
    SPECIES_ABILITY_EMOJI_FALLBACKS,
    TEAM_EMOJI_FALLBACKS,
)
from d12ball import tokens
from d12ball.components import PlayerRole, SPECIES_CYBORG
from d12ball.game import AIOpponent, D12BallGame, GameMode, Team
from prompt_fixtures import CASES

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"


def build_game(**overrides) -> D12BallGame:
    fields = dict(
        game_id="g1",
        game_number=1,
        guild_id=1,
        channel_id=2,
        message_id=3,
        player_1_id=111,
        player_2_id=222,
        player_1_name="Player One",
        player_2_name="Player Two",
        player_1_team=Team.PURPLE,
        player_2_team=Team.TEAL,
        mode=GameMode.BASIC,
    )
    fields.update(overrides)
    return D12BallGame(**fields)


class TokenSpellingTests(unittest.TestCase):
    """The builders are the one place a token is written."""

    def test_each_builder_spells_its_kind(self) -> None:
        self.assertEqual(tokens.team(Team.PURPLE), "{team:purple}")
        self.assertEqual(tokens.role(PlayerRole.FULLBACK), "{role:fullback}")
        self.assertEqual(
            tokens.role(PlayerRole.FULLBACK, Team.ORANGE),
            "{role:fullback:orange}",
        )
        self.assertEqual(
            tokens.condition(tokens.CONDITION_EXHAUST), "{condition:exhaust}",
        )
        self.assertEqual(tokens.species(SPECIES_CYBORG), "{species:cyborg}")
        self.assertEqual(tokens.coach(1), "{coach:1}")

    def test_a_mark_that_does_not_exist_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            tokens.condition("tired")
        with self.assertRaises(ValueError):
            tokens.coach(3)

    def test_find_lists_every_token_in_order(self) -> None:
        text = f"{tokens.team(Team.TEAL)} Hellguard {tokens.role(PlayerRole.FULLBACK, Team.TEAL)} gains 1 token {tokens.condition('exhaust')}"
        self.assertEqual(
            tokens.find(text),
            [
                ("team", ("teal",)),
                ("role", ("fullback", "teal")),
                ("condition", ("exhaust",)),
            ],
        )

    def test_render_leaves_what_the_resolver_declines(self) -> None:
        text = "{team:teal} and {coach:1}"
        self.assertEqual(
            tokens.render(text, lambda kind, args: "T" if kind == "team" else None),
            "T and {coach:1}",
        )

    def test_braces_that_are_not_a_token_are_left_alone(self) -> None:
        for text in ("{}", "{team}", "{TEAM:teal}", "{ team:teal }", "{coach:}"):
            with self.subTest(text=text):
                self.assertEqual(tokens.find(text), [])
                self.assertEqual(tokens.render(text, lambda k, a: "X"), text)


class DiscordTokensTests(unittest.TestCase):
    """How Discord draws each kind, with and without an upload."""

    def test_a_team_is_its_upload_or_its_circle(self) -> None:
        discord = DiscordTokens({Team.PURPLE: "<:team_purple:100>"}, {}, {}, {})
        self.assertEqual(discord.render("{team:purple}"), "<:team_purple:100>")
        self.assertEqual(
            discord.render("{team:teal}"), TEAM_EMOJI_FALLBACKS[Team.TEAL],
        )

    def test_a_role_falls_three_steps(self) -> None:
        role_emojis = {
            (PlayerRole.STRIKER, None): "<:role_striker:100>",
            (PlayerRole.STRIKER, Team.ORANGE): "<:role_striker_orange:101>",
        }
        discord = DiscordTokens({}, role_emojis, {}, {})
        self.assertEqual(
            discord.render("{role:striker:orange}"), "<:role_striker_orange:101>",
        )
        self.assertEqual(discord.render("{role:striker:teal}"), "<:role_striker:100>")
        self.assertEqual(discord.render("{role:striker}"), "<:role_striker:100>")
        self.assertEqual(discord.render("{role:fullback:teal}"), "[FB]")

    def test_a_condition_and_a_species_are_their_uploads_or_fallbacks(
        self,
    ) -> None:
        discord = DiscordTokens(
            {}, {}, {"exhaust": "<:exhaust:1>"}, {"cyborg": "<:cyborg_color:2>"},
        )
        self.assertEqual(discord.render("{condition:exhaust}"), "<:exhaust:1>")
        self.assertEqual(discord.render("{condition:injured}"), "🤕")
        self.assertEqual(discord.render("{species:cyborg}"), "<:cyborg_color:2>")
        self.assertEqual(
            discord.render("{species:ooze}"),
            SPECIES_ABILITY_EMOJI_FALLBACKS["ooze"],
        )

    def test_a_coach_is_mentioned_and_the_ai_is_named(self) -> None:
        game = build_game(player_2_id=None, player_2_name=None, ai_opponent=AIOpponent.DINKY)
        discord = DiscordTokens({}, {}, {}, {}, game)
        self.assertEqual(discord.render("{coach:1}"), "<@111>")
        self.assertEqual(discord.render("{coach:2}"), "Dinky AI")

    def test_a_test_game_names_both_seats(self) -> None:
        game = build_game(test_game=True, player_2_id=111)
        discord = DiscordTokens({}, {}, {}, {}, game)
        self.assertEqual(discord.render("{coach:1}, {coach:2}"), "Player 1, Player 2")

    def test_a_coach_with_no_game_to_read_is_left_as_a_token(self) -> None:
        discord = DiscordTokens({}, {}, {}, {})
        self.assertEqual(discord.render("{coach:1}"), "{coach:1}")

    def test_a_value_discord_does_not_know_is_left_as_a_token(self) -> None:
        discord = DiscordTokens({}, {}, {}, {}, build_game())
        for text in (
            "{team:plaid}", "{role:goalie}", "{condition:tired}",
            "{coach:9}", "{coach:one}",
        ):
            with self.subTest(text=text):
                self.assertEqual(discord.render(text), text)


class NothingLeaksTests(unittest.TestCase):
    """A token is the model's; nothing a coach reads carries one."""

    def test_every_prompts_ask_renders_clean(self) -> None:
        for case in CASES:
            with self.subTest(case.name):
                fixture = case.build()
                rendered = DiscordTokens({}, {}, {}, {}, fixture.game).render(
                    fixture.ask,
                )
                self.assertEqual(tokens.find(rendered), [], rendered)

    def test_the_golden_transcripts_carry_no_token(self) -> None:
        transcripts = sorted(GOLDEN_DIR.glob("*_transcript.txt"))
        self.assertGreaterEqual(len(transcripts), 3)
        for path in transcripts:
            with self.subTest(path.name):
                if path.name.startswith("service_"):
                    # The service golden pins the model's voice, tokens
                    # included; it is the one transcript that must
                    # carry them.
                    self.assertNotEqual(tokens.find(path.read_text()), [])
                    continue
                self.assertEqual(tokens.find(path.read_text()), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
