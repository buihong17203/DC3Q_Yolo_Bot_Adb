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
        self.target_done = False

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
        if self.config.home_target is not None and not self.target_done:
            self.target_done = bool(self.config.home_target.run())
            self.confirmations = 0
            return False
        self.confirmations += 1
        return self.confirmations >= self.config.logged_in_confirmations
