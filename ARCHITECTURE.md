# Fool Bot architecture

## Goal

D12Ball must support Discord and a web frontend without implementing the game
twice.

Both frontends use the same state, rules, prompts, and turn sequence. A
frontend only translates user input into an action and displays the result.

## The design

```text
Discord button ─┐
                ├──> Action ──> GameService ──> driver.apply()
Web request ────┘                       │
                                       ├──> save MatchState
                                       └──> GameResult
                                                │
                          ┌─────────────────────┴────────────────────┐
                          ▼                                          ▼
                  Discord presenter                          Web presenter
```

There are four parts.

### 1. Game model

`d12ball/` owns the game.

It contains:

- `MatchState`, which is the authoritative match position;
- `RulesEngine`, which answers rule questions;
- `PendingPrompt`, which says what the match is waiting for;
- `Action`, which describes one player's answer;
- the flow steps and driver, which apply an action and run automatic steps.

The model must not import Discord or web-framework code. It must not send
messages or save files.

### 2. Game service

`GameService` is the small entry point shared by Discord and the web frontend.

```python
class GameService:
    def apply_action(self, game_id: str, action: Action) -> GameResult:
        game = self.games[game_id]
        match = self.engine.load_match_state(game)

        result = driver.apply(self.engine, game, match, action)
        if isinstance(result, Refusal):
            return GameResult(refusal=result.message)

        game.match_state = match.to_dict()
        self.save_games()
        return GameResult.from_driver_run(result)
```

The service has four responsibilities:

1. Load the game.
2. Apply the action.
3. Save the changed match once.
4. Return the result.

It does not format Discord messages or HTTP responses.

Lobby operations can use small service methods such as `join_game`,
`leave_game`, and `start_game`. They do not need to pass through the turn
driver.

### 3. Discord frontend

The Discord frontend owns:

- Discord user authentication and helper permissions;
- slash commands, buttons, menus, and modals;
- Discord messages, attachments, pins, and message IDs;
- rate-limit batching;
- conversion of a button click into an `Action`;
- presentation of a `GameResult`.

A gameplay callback should be small:

```python
async def pick_maneuver(self, interaction, side, maneuver_key):
    if not self.may_act_for_side(interaction, side):
        return

    result = self.game_service.apply_action(
        self.game_id,
        Action(
            kind=PromptKind.MANEUVER_ACTION,
            arguments={
                "side": side,
                "maneuver_key": maneuver_key,
            },
        ),
    )

    await self.presenter.show(interaction, result)
```

The callback checks the Discord identity. The shared model checks whether the
action is legal in the current match.

### 4. Web frontend

The web frontend owns:

- web authentication;
- HTTP or websocket handling;
- conversion of a request into an `Action`;
- conversion of a `GameResult` into JSON;
- browser-specific presentation.

It calls the same service:

```python
async def answer_prompt(request):
    action = action_from_request(request)
    result = game_service.apply_action(request.game_id, action)
    return result_as_json(result)
```

## Shared result

Both frontends need a small, frontend-neutral result.

```python
@dataclass(frozen=True)
class GameResult:
    public_messages: tuple[str, ...] = ()
    private_message: str | None = None
    prompt: PendingPrompt | None = None
    board_changed: bool = False
    detail: object | None = None
    refusal: str | None = None
```

`detail` contains structured information needed for presentation, such as dice
values or a matchup. Discord can render it as an image. The web frontend can
render it as HTML or JSON.

The result must not contain `discord.Interaction`, Discord views, message IDs,
HTTP responses, or HTML.

## State-changing and read-only operations

State-changing gameplay uses `apply_action`:

```text
input -> Action -> driver.apply -> save -> GameResult
```

Read-only operations do not use the driver:

```text
board request -> load game -> render board
stats request -> load game -> calculate stats
rules request -> read rules -> return text
```

Frontend-only operations stay in the frontend. Examples are opening a modal,
closing a confirmation, and enlarging an image.

## AI

The AI must choose an `Action` and use `GameService.apply_action`. It must not
mutate `MatchState` through a separate path.

```text
AI strategy -> Action -> GameService -> same driver as a human action
```

## Persistence

`MatchState` remains the source of truth. This design does not use event
sourcing.

The game service saves the match after a successful action. Flow steps do not
save. Frontend presenters do not save game state.

Discord message IDs are transport metadata. Discord can store them after it
creates a message without resaving the match transition.

## What to remove

As frontends move to this path, remove:

- direct flow-step calls from Discord views;
- game-rule validation duplicated in Discord callbacks;
- match persistence from views and flow wrappers;
- cog methods that only forward to `RulesEngine` or a flow function;
- the cog's `follow_on_methods` table;
- domain work inside methods such as `begin_maneuver_skill_test`;
- Discord emoji values from the shared rules engine;
- separate AI mutation paths;
- transitional comments and tests after their structures are deleted.

Keep Discord authorization and presentation in the Discord frontend. Move only
game rules and game sequencing into the shared model.

## Migration order

1. Add `GameService.apply_action` and `GameResult`.
2. Route one simple Discord action through the service.
3. Route the remaining prompt answers through the service.
4. Route AI choices through the service.
5. Move the remaining domain work out of cog follow-on methods.
6. Delete unused wrappers, dispatch tables, and duplicate validation.
7. Build the web frontend on the same service.

Each step must leave the Discord game playable. Do not create a second game
loop for the web frontend.
