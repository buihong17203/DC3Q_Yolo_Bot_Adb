from __future__ import annotations


class HomeAction:
    """Handle safe HOME popups and run the configured HOME target once."""

    def __init__(self, adb_input, vision, config):
        self.input = adb_input
        self.vision = vision
        self.config = config
        self.reset()

    def reset(self) -> None:
        self.confirmations = 0
        self.target_index = 0
        self.recovery_attempts = 0

    @property
    def target_done(self) -> bool:
        return self.target_index >= len(self.config.home_targets or [])

    @property
    def current_task(self) -> str:
        targets = self.config.home_targets or []
        if self.target_index >= len(targets):
            return "LOGOUT"
        return getattr(targets[self.target_index], "runtime_task", type(targets[self.target_index]).__name__.upper())

    def handle_known_event(self, image) -> bool:
        for state_template, close_template, threshold in self.config.home_events or []:
            state = self.vision.find_template(
                image, "random_event_state", state_template, threshold,
            ).match
            if not state.found:
                continue
            close = self.vision.find_template(
                image, "random_event_close", close_template, threshold,
            ).match
            if not close.found:
                raise RuntimeError(
                    f"Sự kiện ngẫu nhiên đã nhận diện nhưng thiếu nút đóng: {state_template}"
                )
            self.input.tap(close.x + close.width // 2, close.y + close.height // 2)
            return True
        return False

    def process(self, image, *, logged_in: bool) -> bool:
        """Return True only after HOME target and stable HOME confirmations."""
        if self.handle_known_event(image):
            self.confirmations = 0
            return False
        if not logged_in:
            self.confirmations = 0
            return False
        targets = self.config.home_targets or []
        if self.target_index < len(targets):
            try:
                if targets[self.target_index].run():
                    self.target_index += 1
                    self.recovery_attempts = 0
            except RuntimeError:
                target = targets[self.target_index]
                recover = getattr(target, "recover_home", None)
                if recover is None or self.recovery_attempts >= 2 or not recover():
                    raise
                self.recovery_attempts += 1
                # Do not advance: restart the same target from its first state.
            self.confirmations = 0
            return False
        self.confirmations += 1
        return self.confirmations >= self.config.logged_in_confirmations
