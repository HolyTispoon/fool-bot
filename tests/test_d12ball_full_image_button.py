import asyncio
import unittest

import discord

from cogs.d12ball import (
    FULL_IMAGE_BUTTON_LABEL,
    add_full_image_button,
    build_full_image_button,
)


# The signed form Discord hands back for an upload. The ex/is/hm
# parameters are what expires, and they have to survive into the button
# or the link is dead on arrival.
SIGNED_URL = (
    "https://cdn.discordapp.com/attachments/1/2/d12ball-pbd7.png"
    "?ex=6a1b2c3d&is=6a1a1b1c&hm=abc123"
)
PROXY_URL = (
    "https://media.discordapp.net/attachments/1/2/d12ball-pbd7.png"
    "?ex=6a1b2c3d&is=6a1a1b1c&hm=abc123"
)


class FakeAttachment:
    def __init__(self, url: str, proxy_url: str) -> None:
        self.url = url
        self.proxy_url = proxy_url


class FakeMessage:
    """
    Stands in for a message that has already been posted, and records
    the edit that puts the link on it.
    """

    def __init__(self, attachments: list = None, error: Exception = None):
        self.attachments = attachments or []
        self.error = error
        self.edits: list[dict] = []

    async def edit(self, **fields):
        if self.error is not None:
            raise self.error

        self.edits.append(fields)
        return self


class FakeResponse:
    """The bare minimum discord.HTTPException reads off a response."""

    status = 500
    reason = "Internal Server Error"


def build_message() -> FakeMessage:
    return FakeMessage([FakeAttachment(SIGNED_URL, PROXY_URL)])


class D12BallFullImageButtonTests(unittest.TestCase):
    def test_the_link_points_at_the_original_upload(self) -> None:
        # media.discordapp.net is the resized copy Android already
        # shows, so linking to it would fix nothing.
        button = build_full_image_button(build_message())

        self.assertEqual(
            button.to_component_dict(),
            {
                "type": 2,
                "style": 5,
                "disabled": False,
                "label": FULL_IMAGE_BUTTON_LABEL,
                "url": SIGNED_URL,
            },
        )

    def test_a_message_without_an_image_gets_no_button(self) -> None:
        self.assertIsNone(build_full_image_button(FakeMessage()))

    def test_a_message_without_an_image_is_not_edited(self) -> None:
        message = FakeMessage()

        asyncio.run(add_full_image_button(message))

        self.assertEqual(message.edits, [])

    def test_the_link_goes_out_on_a_view_of_its_own(self) -> None:
        message = build_message()

        asyncio.run(add_full_image_button(message))

        view = message.edits[0]["view"]
        self.assertEqual(
            [item.url for item in view.children],
            [SIGNED_URL],
        )

    def test_the_message_keeps_its_own_buttons(self) -> None:
        # Editing a view replaces it, so anything already on the
        # message has to be handed back in alongside the link.
        message = build_message()
        view = discord.ui.View(timeout=None)
        view.add_item(
            discord.ui.Button(
                label="Choose Your Maneuver",
                custom_id="d12ball:maneuver_prompt:test-game",
            )
        )

        asyncio.run(add_full_image_button(message, view))

        self.assertEqual(
            [item.label for item in message.edits[0]["view"].children],
            ["Choose Your Maneuver", FULL_IMAGE_BUTTON_LABEL],
        )

    def test_the_attachments_are_left_alone(self) -> None:
        # Passing attachments here would re-upload the image; leaving
        # the field out is what makes Discord keep the one it has.
        message = build_message()

        asyncio.run(add_full_image_button(message))

        self.assertEqual(list(message.edits[0]), ["view"])

    def test_a_failed_edit_does_not_take_the_turn_down(self) -> None:
        message = FakeMessage(
            [FakeAttachment(SIGNED_URL, PROXY_URL)],
            error=discord.HTTPException(
                FakeResponse(),
                "edit failed",
            ),
        )

        asyncio.run(add_full_image_button(message))

        self.assertEqual(message.edits, [])


if __name__ == "__main__":
    unittest.main()
