"""The deck's faces at screen size, and a row of them as one picture: what
the bot's `/tethyscards` commands show for a hand, a draw and the discard.

`Faces` draws all 72 once (`cards.deck_cards`, about two seconds) and keeps
them small, so a picture after that is only pasting; the cog builds one as
it loads, off the event loop, and never draws a face again. Nothing here
reads Discord -- see docs/design/tethys-deck.md, "On Discord".
"""
import io

from PIL import Image

from tethysdeck.cards import deck_cards
from tethysdeck.relief import IconSet

# A face on screen: the printed card (750 x 1050) at 0.24, where its rank and pieces
# still read.
FACE_W, FACE_H = 180, 252
GAP = 12
PER_ROW = 9  # a hand of up to nine is one row; the whole deck is eight


class Faces:
    """Every face, drawn once and kept at FACE_W x FACE_H, by (suit, rank)."""

    def __init__(self, faces: dict[tuple[str, str], Image.Image] | None = None):
        if faces is None:
            faces = deck_cards(IconSet())
        self._faces = {
            key: face if face.size == (FACE_W, FACE_H) else face.resize((FACE_W, FACE_H), Image.LANCZOS)
            for key, face in faces.items()
        }

    def row(self, cards: list[tuple[str, str]]) -> Image.Image:
        """The cards left to right, wrapping after PER_ROW, on transparency."""
        columns = min(len(cards), PER_ROW)
        rows = -(-len(cards) // PER_ROW)
        image = Image.new("RGBA", (columns * FACE_W + (columns - 1) * GAP,
                                   rows * FACE_H + (rows - 1) * GAP), (0, 0, 0, 0))
        for i, key in enumerate(cards):
            row, column = divmod(i, PER_ROW)
            image.alpha_composite(self._faces[key], (column * (FACE_W + GAP), row * (FACE_H + GAP)))
        return image

    def row_png(self, cards: list[tuple[str, str]]) -> bytes:
        out = io.BytesIO()
        self.row(cards).save(out, format="PNG", optimize=True)
        return out.getvalue()

