from __future__ import annotations

from app.adb.input import DailyCutoff


class GameRestartRequired(RuntimeError):
    def __init__(self, task: str, error: str):
        super().__init__(error)
        self.task = task


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
        self.last_task_error = ""
        self.completed_tasks: set[str] = set()

    def set_completed_tasks(self, tasks: set[str]) -> None:
        self.completed_tasks = set(tasks)
        self._skip_completed()

    def _skip_completed(self) -> None:
        targets = self.config.home_targets or []
        while self.target_index < len(targets):
            task = getattr(targets[self.target_index], "runtime_task", "")
            if task not in self.completed_tasks:
                break
            self.target_index += 1

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
                target = targets[self.target_index]
                if not target.run():
                    raise RuntimeError(f"{self.current_task} returned False")
                self.last_task_error = "; ".join(getattr(target, "soft_errors", []))
                self.target_index += 1
                self.recovery_attempts = 0
            except DailyCutoff:
                raise
            except Exception as exc:
                target = targets[self.target_index]
                recover = getattr(target, "recover_home", None)
                if recover is None:
                    raise
                task = self.current_task
                limit = int(getattr(self.config, "target_retry_limit", 3))
                recovered = False
                for attempt in range(1, limit + 1):
                    try:
                        recovered = bool(recover())
                    except Exception as recovery_error:
                        __import__("logging").getLogger("dc3q").warning(
                            "HOME | recovery lỗi | task=%s | lần=%d/%d | lỗi=%s",
                            task, attempt, limit, recovery_error,
                        )
                    if recovered:
                        break
                if not recovered:
                    raise GameRestartRequired(task, str(exc)) from exc
                # Module failed but HOME is safe: record ERROR and continue.
                self.last_task_error = str(exc)
                self.target_index += 1
                self.recovery_attempts = 0
            self.confirmations = 0
            self._skip_completed()
            return False
        self.confirmations += 1
        return self.confirmations >= self.config.logged_in_confirmations

    def resume_after_game_restart(self, task: str) -> None:
        if task != self.current_task:
            raise RuntimeError(f"Checkpoint restart lệch: {task} != {self.current_task}")
        self.confirmations = 0

    def continue_after_esc_home(self, task: str) -> None:
        """ESC recovered canonical HOME: preserve ERROR and advance one module."""
        if task != self.current_task:
            raise RuntimeError(f"Checkpoint ESC lệch: {task} != {self.current_task}")
        self.last_task_error = ""
        self.target_index += 1
        self.confirmations = 0
        self._skip_completed()
