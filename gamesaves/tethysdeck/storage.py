import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_FOLDER = PROJECT_ROOT / "data"
DECKS_FILE = DATA_FOLDER / "tethysdeck_decks.json"


@dataclass
class ChannelDeck:
    deck: list[str] = field(default_factory=list)
    discard: list[str] = field(default_factory=list)
    hands: dict[str, list[str]] = field(default_factory=dict)
    status_message_id: Optional[int] = None


def load_decks() -> dict[str, ChannelDeck]:
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)

    if not DECKS_FILE.exists():
        return {}

    try:
        with DECKS_FILE.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)
    except (json.JSONDecodeError, OSError) as error:
        LOGGER.error("Could not load Tethys deck state: %s", error)
        return {}

    decks: dict[str, ChannelDeck] = {}

    for channel_id, deck_data in raw_data.items():
        try:
            decks[channel_id] = ChannelDeck(**deck_data)
        except TypeError as error:
            LOGGER.error(
                "Skipping invalid saved deck for channel %s: %s",
                channel_id, error,
            )

    return decks


def save_decks(decks: dict[str, ChannelDeck]) -> None:
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)

    serialized_decks = {
        channel_id: asdict(deck)
        for channel_id, deck in decks.items()
    }

    temporary_file = DECKS_FILE.with_suffix(".tmp")

    with temporary_file.open("w", encoding="utf-8") as file:
        json.dump(serialized_decks, file, indent=2)

    temporary_file.replace(DECKS_FILE)
