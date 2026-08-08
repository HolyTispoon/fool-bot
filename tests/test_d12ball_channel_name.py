import unittest

from cogs.d12ball_helpers import (
    CHANNEL_NAME_MAX_LENGTH,
    CHANNEL_NAME_PATTERN,
    build_game_channel_name,
)


class D12BallChannelNameTests(unittest.TestCase):
    def test_players_name_the_channel_when_no_game_name_is_given(self):
        self.assertEqual(
            build_game_channel_name(12, "Username", "Dinky AI"),
            "d12ball-pbd12-username-vs-dinky-ai",
        )

    def test_game_name_replaces_the_players(self):
        self.assertEqual(
            build_game_channel_name(
                12,
                "Username",
                "Dinky AI",
                game_name="The Cup Final!",
            ),
            "d12ball-pbd12-the-cup-final",
        )

    def test_blank_game_name_falls_back_to_the_players(self):
        self.assertEqual(
            build_game_channel_name(3, "One", "Two", game_name="   "),
            "d12ball-pbd3-one-vs-two",
        )

    def test_a_name_with_nothing_usable_leaves_just_the_number(self):
        self.assertEqual(
            build_game_channel_name(5, "One", "Two", game_name="!!!"),
            "d12ball-pbd5",
        )

    def test_long_names_are_cut_to_discords_limit(self):
        name = build_game_channel_name(4, "x" * 60, "y" * 60)
        self.assertLessEqual(len(name), CHANNEL_NAME_MAX_LENGTH)
        self.assertTrue(name.startswith("d12ball-pbd4-"))
        self.assertFalse(name.endswith("-"))

    def test_non_latin_names_survive_the_slug(self):
        self.assertEqual(
            build_game_channel_name(7, "Тимур", "Dinky AI"),
            "d12ball-pbd7-тимур-vs-dinky-ai",
        )

    def test_every_name_is_still_recognised_as_a_game_channel(self):
        names = [
            build_game_channel_name(12, "Username", "Dinky AI"),
            build_game_channel_name(12, "A", "B", game_name="Cup Final"),
            build_game_channel_name(5, "One", "Two", game_name="!!!"),
            # Channels created before the suffix existed.
            "d12ball-pbd9",
        ]

        for name in names:
            with self.subTest(name=name):
                match = CHANNEL_NAME_PATTERN.fullmatch(name)
                self.assertIsNotNone(match)

        self.assertIsNone(CHANNEL_NAME_PATTERN.fullmatch("d12ball-pbd"))
        self.assertIsNone(CHANNEL_NAME_PATTERN.fullmatch("general"))


if __name__ == "__main__":
    unittest.main()
