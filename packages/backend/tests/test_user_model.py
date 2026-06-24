from dungml_backend import models


def test_user_has_subject_and_no_password():
    cols = set(models.User.__table__.columns.keys())
    assert "subject" in cols
    assert "password_hash" not in cols


def test_session_model_removed():
    assert not hasattr(models, "Session")
