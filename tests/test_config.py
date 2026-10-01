from backend import config


def _write_prefs(appdata, data_dir, use_data_dir=True):
    profile = appdata / "Zotero" / "Zotero" / "Profiles" / "abc.default"
    profile.mkdir(parents=True)
    escaped = str(data_dir).replace("\\", "\\\\")
    (profile / "prefs.js").write_text(
        f'user_pref("extensions.zotero.dataDir", "{escaped}");\n'
        f'user_pref("extensions.zotero.useDataDir", {"true" if use_data_dir else "false"});\n',
        encoding="utf-8",
    )


def test_reads_moved_data_dir_from_zotero_prefs(tmp_path, monkeypatch):
    data_dir = tmp_path / "Zotero Daten"
    data_dir.mkdir()
    (data_dir / "zotero.sqlite").touch()
    _write_prefs(tmp_path, data_dir)
    monkeypatch.delenv("ZOTERO_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config._zotero_data_dir() == data_dir


def test_env_variable_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("ZOTERO_DATA_DIR", str(tmp_path / "custom"))
    assert config._zotero_data_dir() == tmp_path / "custom"


def test_falls_back_to_default_when_pref_points_nowhere(tmp_path, monkeypatch):
    _write_prefs(tmp_path, tmp_path / "missing")
    monkeypatch.delenv("ZOTERO_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config._zotero_data_dir().name == "Zotero"
    assert config._zotero_data_dir() != tmp_path / "missing"


def test_ignores_pref_when_custom_dir_disabled(tmp_path, monkeypatch):
    data_dir = tmp_path / "elsewhere"
    data_dir.mkdir()
    (data_dir / "zotero.sqlite").touch()
    _write_prefs(tmp_path, data_dir, use_data_dir=False)
    monkeypatch.delenv("ZOTERO_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config._zotero_data_dir() != data_dir


def test_finds_zotero_profile_on_macos(tmp_path, monkeypatch):
    data_dir = tmp_path / "Zotero-Daten"
    data_dir.mkdir()
    (data_dir / "zotero.sqlite").touch()
    mac_profiles = tmp_path / "home" / "Library" / "Application Support"
    _write_prefs(mac_profiles, data_dir)  # writes <root>/Zotero/Zotero/Profiles/...
    # macOS layout is .../Application Support/Zotero/Profiles/<profile>/prefs.js
    (mac_profiles / "Zotero" / "Zotero" / "Profiles").rename(mac_profiles / "Zotero" / "Profiles")
    monkeypatch.delenv("ZOTERO_DATA_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "no-windows-profile"))
    monkeypatch.setattr(config.Path, "home", lambda: tmp_path / "home")
    assert config._zotero_data_dir() == data_dir


def test_reads_linked_attachment_base_directory(tmp_path, monkeypatch):
    profile = tmp_path / "Zotero" / "Zotero" / "Profiles" / "abc.default"
    profile.mkdir(parents=True)
    (profile / "prefs.js").write_text(
        'user_pref("extensions.zotero.baseAttachmentPath", "D:\\\\Papers");\n', encoding="utf-8"
    )
    monkeypatch.delenv("ZOTERO_BASE_ATTACHMENT_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert config._zotero_base_attachment_dir() == config.Path("D:\\Papers")
