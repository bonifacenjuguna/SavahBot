import pytest

from app import config


def test_boots_with_empty_environment():
    s = config.Settings(env={}, env_file=None)
    assert s.bot_mode == "demo"
    assert s.telegram_mode == "webhook"
    assert s.mod_mode == "suggest"
    assert s.owner_timezone == "Africa/Nairobi"


def test_env_overrides_and_coercion():
    s = config.Settings(
        env={"MOD_SCORE_DELETE": "70", "MOD_CAPS_RATIO": "0.9", "URLFETCH_ENABLED": "false",
             "BOT_MODE": "live", "TELEGRAM_OWNER_ID": "12345"},
        env_file=None,
    )
    assert s.mod_score_delete == 70 and isinstance(s.mod_score_delete, int)
    assert s.mod_caps_ratio == 0.9
    assert s.urlfetch_enabled is False
    assert s.bot_mode == "live"
    assert s.telegram_owner_id == 12345


def test_blank_and_garbage_values_fall_back_to_defaults():
    s = config.Settings(env={"MOD_SCORE_DELETE": "", "MOD_SCORE_FLAG": "banana"}, env_file=None)
    assert s.mod_score_delete == 55
    assert s.mod_score_flag == 30


def test_public_url_prefers_explicit_then_railway():
    assert config.Settings(env={"PUBLIC_BASE_URL": "https://x.test/"}, env_file=None).public_url == "https://x.test"
    assert config.Settings(env={"RAILWAY_PUBLIC_DOMAIN": "bot.up.railway.app"}, env_file=None).public_url == \
        "https://bot.up.railway.app"
    assert config.Settings(env={}, env_file=None).public_url == ""


def test_cors_includes_frontend_and_localhost():
    s = config.Settings(env={"FRONTEND_URL": "https://dash.vercel.app/"}, env_file=None)
    assert "https://dash.vercel.app" in s.cors_list and "http://localhost:5173" in s.cors_list


def test_env_file_is_read_and_real_env_wins(tmp_path):
    f = tmp_path / ".env"
    f.write_text('MOD_SCORE_DELETE=61\nCOMMAND_PREFIX="?"\n# comment\n')
    s = config.Settings(env={"MOD_SCORE_DELETE": "62"}, env_file=str(f))
    assert s.mod_score_delete == 62
    assert s.command_prefix == "?"


def test_every_field_is_in_env_example_and_names_are_unique():
    names = [f.name for f in config.FIELDS]
    assert len(names) == len(set(names))
    text = config.render_env_example()
    for n in names:
        assert text.count(f"\n{n.upper()}=") == 1, n
    assert len(names) > 130  # "as many placeholders as possible"


def test_editable_rules():
    assert config.is_editable("mod_caps_ratio")
    assert config.is_editable("bot_mode")
    assert not config.is_editable("telegram_bot_token")
    assert not config.is_editable("owner_password")
    assert not config.is_editable("database_url")
    assert not config.is_editable("does_not_exist")


def test_validate_value():
    assert config.validate_value("mod_caps_ratio", "0.5") == 0.5
    assert config.validate_value("mod_caps_enabled", "off") is False
    assert config.validate_value("mod_mode", "auto") == "auto"
    with pytest.raises(ValueError):
        config.validate_value("mod_mode", "chaos")


def test_env_example_is_up_to_date():
    from pathlib import Path
    from app.config import render_env_example
    target = Path(__file__).resolve().parents[1] / ".env.example"
    assert target.read_text() == render_env_example(), "run: python scripts/gen_env_example.py"


def test_env_example_works_as_is_and_edit_me_is_ignored():
    """Loading the shipped file must change nothing: every value is the default, a blank, or the edit-me marker."""
    from pathlib import Path
    from app.config import FIELDS, PLACEHOLDER, Settings, _read_env_file
    target = Path(__file__).resolve().parents[1] / ".env.example"
    loaded = Settings(env={}, env_file=str(target))
    plain = Settings(env={}, env_file="")
    for f in FIELDS:
        assert loaded.get(f.name) == plain.get(f.name) == f.default, f.name
    values = _read_env_file(str(target))
    assert len(values) == len(FIELDS)
    assert sum(v == PLACEHOLDER for v in values.values()) >= 5
    assert Settings(env={"OWNER_PASSWORD": "edit-me", "TELEGRAM_BOT_TOKEN": "Edit-Me"}, env_file="").owner_password == ""
    assert Settings(env={"OWNER_PASSWORD": "real-pass"}, env_file="").owner_password == "real-pass"
