import json
import os
import sqlite3
import zipfile

import appsettings
import maintenance


def test_settings_defaults_and_roundtrip(tmp_path):
    p = str(tmp_path / "s.json")
    s = appsettings.AppSettings(p)
    assert s.language == "pt" and s.scale_value() is None and s.backup_on
    s.language, s.ui_scale, s.stop_losses, s.goal_wins = "en", "150%", 3, 5
    assert s.save()
    t = appsettings.AppSettings(p)
    assert (t.language, t.scale_value(), t.stop_losses, t.goal_wins) == ("en", 1.5, 3, 5)


def test_settings_ignore_invalid_values(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"language": "xx", "ui_scale": "999%", "stop_losses": 77,
                             "backup_keep": "a", "close_to_tray": "sim"}), encoding="utf-8")
    s = appsettings.AppSettings(str(p))
    assert (s.language, s.ui_scale, s.stop_losses, s.backup_keep, s.close_to_tray) == ("pt", "auto", 0, 7, False)
    p.write_text("[1,2", encoding="utf-8")
    assert appsettings.AppSettings(str(p)).language == "pt"


def _data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    (d / "profiles.json").write_text("{}", encoding="utf-8")
    (d / "ai.json").write_text('{"api_key": "SEGREDO"}', encoding="utf-8")
    (d / "ballchasing.json").write_text('{"token": "SEGREDO"}', encoding="utf-8")
    c = sqlite3.connect(d / "history.db")
    c.execute("CREATE TABLE t(a)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()
    return str(d)


def test_zip_has_no_secrets(tmp_path):
    d = _data_dir(tmp_path)
    out = str(tmp_path / "x.zip")
    files = maintenance.write_zip(out, d)
    assert sorted(files) == ["history.db", "profiles.json"]
    z = zipfile.ZipFile(out)
    assert not any("SEGREDO" in z.read(n).decode("latin-1") for n in z.namelist())
    # a copia da base de dados abre e tem os dados
    z.extract("history.db", tmp_path / "ex")
    assert sqlite3.connect(tmp_path / "ex" / "history.db").execute("SELECT a FROM t").fetchone() == (1,)


def test_backup_daily_and_prune(tmp_path):
    d = _data_dir(tmp_path)
    folder = str(tmp_path / "bk")
    for day in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"):
        os.makedirs(folder, exist_ok=True)
        open(maintenance.backup_path(folder, day), "wb").write(b"x")
    assert maintenance.backup_due(folder)
    path, _ = maintenance.make_backup(d, folder, keep=3)
    assert os.path.exists(path) and not maintenance.backup_due(folder)
    names = maintenance.list_backups(folder)
    assert len(names) == 3 and names[-1].endswith(".zip") and "2026-10-01" not in "".join(names)
    maintenance.make_backup(d, folder, keep=3)          # no mesmo dia: substitui, nao acumula
    assert len(maintenance.list_backups(folder)) == 3


def test_single_instance():
    a = maintenance.SingleInstance(port=0)
    # porta 0 nao serve para o teste de colisao: escolhe uma porta livre real
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    first, second = maintenance.SingleInstance(port), maintenance.SingleInstance(port)
    assert first.acquire()
    assert not second.acquire()                 # 2.a instancia avisa a 1.a
    import time
    for _ in range(20):
        if first.take_show_request():
            break
        time.sleep(0.05)
    else:
        raise AssertionError("pedido 'show' nao chegou")
    first.release()
    third = maintenance.SingleInstance(port)
    assert third.acquire()
    third.release()
