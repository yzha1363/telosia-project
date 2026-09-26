"""Local startup selects the project configuration without exposing secrets."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_local_backend as launcher


@pytest.mark.parametrize("reload", [True, False])
def test_launcher_uses_own_env_and_overrides_stale_shell(monkeypatch, tmp_path, capsys, reload):
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / ".venv/Scripts/python.exe"))
    monkeypatch.setattr(launcher.sys, "path", list(launcher.sys.path))
    args = ["launcher", "--port", "18001"] + ([] if reload else ["--no-reload"])
    monkeypatch.setattr(launcher.sys, "argv", args)
    monkeypatch.setenv("NVIDIA_API_KEY", "stale-test-key")
    monkeypatch.setenv("DATABASE_URL", "stale-test-db")
    (tmp_path / ".env").write_text("NVIDIA_API_KEY=private-test-key\nDATABASE_URL=sqlite://\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)
    calls = []
    monkeypatch.setitem(launcher.sys.modules, "uvicorn", SimpleNamespace(run=lambda *a, **kw: calls.append((a, kw))))
    launcher.main()
    assert launcher.os.environ["NVIDIA_API_KEY"] == "private-test-key"
    assert launcher.os.environ["DATABASE_URL"] == "sqlite://"
    assert Path.cwd() == tmp_path
    assert launcher.sys.path[0] == str(tmp_path)
    assert calls == [(('app.main:app',), {
        "host": "127.0.0.1", "port": 18001, "reload": reload,
        "reload_dirs": [str(tmp_path)] if reload else None,
    })]
    assert "private-test-key" not in capsys.readouterr().out


def test_launcher_rejects_other_environment(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / "other/python.exe"))
    monkeypatch.setattr(launcher.sys, "argv", ["launcher"])
    with pytest.raises(SystemExit) as failure:
        launcher.main()
    assert failure.value.code == 2


def test_launcher_requires_real_env_not_template(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / ".venv/Scripts/python.exe"))
    monkeypatch.setattr(launcher.sys, "argv", ["launcher"])
    (tmp_path / ".env.example").write_text("DATABASE_URL=template\n", encoding="utf-8")
    with pytest.raises(SystemExit) as failure:
        launcher.main()
    assert failure.value.code == 2
