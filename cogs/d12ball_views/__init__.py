"""
The discord.ui.View classes that drive D12 Ball's interaction flow --
one per prompt a player can be shown (team selection, coin flip, a
maneuver challenge, a skill test, substitutions, and so on). Every view
holds a reference to the D12Ball cog (as `self.cog`) and calls back into
it to run game logic; the views themselves are concerned with rendering
prompts and turning button/select clicks into calls on the cog.

Forty-nine of them in one 6,531-line file is what this package replaced,
split along the clusters they already fell into. This module re-exports
every name that file held, so `from cogs.d12ball_views import X` goes on
working for every X and no call site moved -- the same arrangement
`cogs/d12ball_helpers.py` has with `d12ball/formatting.py`, and for the
same reason: the split says where the code lives, not how it is reached.

`base` imports from no sibling and everything else imports from `base`,
which is what keeps this a DAG. The cross-cluster edges beyond it are
`loose_ball` and `shootout` on `rolls`, `loose_ball` on `turn`, and
`turn` and `effects` on `rolls` -- `ScoreAttemptView`'s Back button
rebuilds whichever prompt offered the shot: the turn prompt itself
(`turn.PlayerActionView`, the same way `TimeOutConfirmView` does) for an
ordinary shot, or the scoring opportunity's own choice
(`effects.SetUpAttemptChoiceView`) for a set-up's.
"""

from cogs.d12ball_views.base import (
    HelperConfirmationView,
    SafeView,
    contestant_detail,
    describe_coaches,
    render_contest_dice,
)
from cogs.d12ball_views.setup import (
    CoinFlipView,
    GameConfigurationView,
    HomeAwaySelectionView,
    RematchView,
    TeamSelectionView,
)
from cogs.d12ball_views.lobby import (
    HubRolesView,
    LobbyNameModal,
    LobbyView,
    NewGameHubView,
    hub_button_emoji,
)
from cogs.d12ball_views.turn import (
    BallHandlerSelectionView,
    TimeOutConfirmView,
    MAX_BUTTONS_PER_ROW,
    MAX_BUTTON_ROWS,
    ManeuverActionPromptView,
    ManeuverChallengeView,
    PlayerActionView,
    even_button_rows,
)
from cogs.d12ball_views.rolls import (
    InjuryTestView,
    OwnGoalRollView,
    ScoreAttemptView,
    SkillTestView,
)
from cogs.d12ball_views.runback import (
    FlyView,
    RunBackChoiceView,
    RunBackPlayerChoiceView,
)
from cogs.d12ball_views.effects import (
    DribbleAdvanceChoiceView,
    DribbleBurstChoiceView,
    HighPassChoiceView,
    LowPassChoiceView,
    LowPassReceiverView,
    JoinTheBallView,
    MindPullView,
    SmoothView,
    SetUpAttemptChoiceView,
    SetupPassChoiceView,
    SetupPassPushBackView,
    ShooterChoiceView,
    SpeedDeltaChoiceView,
    TutorialContinueView,
)
from cogs.d12ball_views.coaching import (
    CoachingFormationView,
    CoachingHubView,
    CoachingOfferView,
    CoachingPlaceSpaceView,
    CoachingPlaceSwapView,
    CoachingPlaceView,
    CoachingSubstitutionInView,
    CoachingSubstitutionOutView,
    CoachingView,
    CoachingZoneView,
)
from cogs.d12ball_views.halftime import (
    HalftimeExtraTokenView,
    HalftimeView,
)
from cogs.d12ball_views.loose_ball import (
    BallRecoveryView,
    LooseBallChoiceView,
    LooseBallSkillTestView,
)
from cogs.d12ball_views.shootout import (
    ShootoutOrderPromptView,
    ShootoutOrderSelectView,
    ShootoutPickPromptView,
    ShootoutPickSelectView,
    ShootoutTestView,
    ShootoutView,
)

__all__ = [
    "HelperConfirmationView",
    "SafeView",
    "contestant_detail",
    "describe_coaches",
    "render_contest_dice",
    "CoinFlipView",
    "GameConfigurationView",
    "HomeAwaySelectionView",
    "RematchView",
    "TeamSelectionView",
    "HubRolesView",
    "LobbyNameModal",
    "LobbyView",
    "NewGameHubView",
    "hub_button_emoji",
    "BallHandlerSelectionView",
    "TimeOutConfirmView",
    "MAX_BUTTONS_PER_ROW",
    "MAX_BUTTON_ROWS",
    "ManeuverActionPromptView",
    "ManeuverChallengeView",
    "PlayerActionView",
    "even_button_rows",
    "InjuryTestView",
    "OwnGoalRollView",
    "ScoreAttemptView",
    "SkillTestView",
    "RunBackChoiceView",
    "RunBackPlayerChoiceView",
    "DribbleAdvanceChoiceView",
    "DribbleBurstChoiceView",
    "HighPassChoiceView",
    "LowPassChoiceView",
    "LowPassReceiverView",
    "MindPullView",
    "JoinTheBallView",
    "FlyView",
    "SmoothView",
    "SetUpAttemptChoiceView",
    "SetupPassChoiceView",
    "SetupPassPushBackView",
    "ShooterChoiceView",
    "SpeedDeltaChoiceView",
    "TutorialContinueView",
    "CoachingFormationView",
    "CoachingHubView",
    "CoachingOfferView",
    "CoachingPlaceSpaceView",
    "CoachingPlaceSwapView",
    "CoachingPlaceView",
    "CoachingSubstitutionInView",
    "CoachingSubstitutionOutView",
    "CoachingView",
    "CoachingZoneView",
    "HalftimeExtraTokenView",
    "HalftimeView",
    "BallRecoveryView",
    "LooseBallChoiceView",
    "LooseBallSkillTestView",
    "ShootoutOrderPromptView",
    "ShootoutOrderSelectView",
    "ShootoutPickPromptView",
    "ShootoutPickSelectView",
    "ShootoutTestView",
    "ShootoutView",
]
