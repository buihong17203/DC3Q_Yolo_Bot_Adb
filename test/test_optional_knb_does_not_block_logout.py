from app.workflow.account_login import save_optional_knb


def test_optional_knb_failure_does_not_raise_or_save():
    saved = []

    result = save_optional_knb(
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("OCR hỏng")),
        object(), "icon.png", lambda account_id, value: saved.append((account_id, value)), "acc_001",
    )

    assert result is False
    assert saved == []
