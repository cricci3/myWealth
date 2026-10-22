"""Smartphone entry, desktop side (SPEC §16.4–16.6): pairing key and QR, inbox folder,
import with dedup by id. Only temporary folders are used, never the real Downloads."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from urllib.parse import quote

import pytest

from mywealth import accounts, csvio, mobile, settings
from mywealth.errors import ValidationError

from .helpers import balance, make_account

HEADER = "data;tipo;conto_origine;conto_destinazione;importo;importo_destinazione;categoria;descrizione;id;creato_il"


@pytest.fixture
def conto(db):
    return make_account(db, "Conto", "EUR", "100", "2026-01-01")


def _csv(*rows: tuple[str, str]) -> str:
    """rows of (id, description): expenses of 1,50 on the account Conto."""
    lines = [HEADER] + [f"05/03/2026;spesa;Conto;;1,50;;Spesa alimentare;{d};{i};2026-03-05T10:00:00Z" for i, d in rows]
    return "\r\n".join(lines) + "\r\n"


def _enc_file(folder, name, body="xyz"):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text(f"{mobile.FILE_MAGIC}\n{body}\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------- key --


def test_key_created_once_and_regenerated(db, tmp_path):
    data = tmp_path / "d"
    assert mobile.status(data) == {"paired": False, "kid": None, "created": None}
    first = mobile.pairing(db, data)
    raw = base64.urlsafe_b64decode(json.loads((data / mobile.KEY_FILENAME).read_text())["key"] + "=")
    assert len(raw) == 32 and first["kid"] == hashlib.sha256(raw).hexdigest()[:16]
    assert mobile.pairing(db, data)["kid"] == first["kid"]  # "Mostra QR" keeps the key
    again = mobile.pairing(db, data, regenerate=True)
    assert again["kid"] != first["kid"] and mobile.status(data)["kid"] == again["kid"]


def test_corrupted_key_file_means_not_paired(tmp_path):
    (tmp_path / mobile.KEY_FILENAME).write_text('{"key": "abc", "kid": "x"}')
    assert mobile.load_key(tmp_path) is None


def test_payload_has_active_accounts_and_categories(db, conto, tmp_path):
    other = make_account(db, "Vecchio", "CHF", "0", "2026-01-01")
    accounts.update_account(db, other["id"], {"archived": True})
    out = mobile.pairing(db, tmp_path)
    data = json.loads(out["text"])
    assert data["mw"] == 1 and data["kid"] == out["kid"] and len(data["key"]) == 43
    assert data["accounts"] == [["Conto", "EUR", 2]]
    assert "Spesa alimentare" in data["categories"]["expense"] and data["categories"]["transfer"]
    assert out["qr"][0].startswith("<svg") and len(out["qr"]) == 1


def test_large_configuration_is_split_in_several_qr():
    text = "x" * 1600
    parts = mobile.split_payload(text, 700)
    assert [p.split(":")[1] for p in parts] == ["1/3", "2/3", "3/3"]
    assert "".join(p.split(":", 2)[2] for p in parts) == text
    assert mobile.split_payload("short") == ["short"]


# ------------------------------------------------------------------ inbox --


def test_scan_inbox_only_reads_valid_mywealth_files(tmp_path):
    inbox = tmp_path / "Downloads"
    good = _enc_file(inbox, "mywealth-20261022-1030.txt")
    _enc_file(inbox, "mywealth-20261022-1031 (1).txt")  # renamed by the browser: still found
    (inbox / "mywealth-notes.txt").write_text("just a note")  # wrong header
    (inbox / "bank.txt").write_text(f"{mobile.FILE_MAGIC}\n")  # wrong name: never opened
    (inbox / "mywealth-dir.txt").mkdir()
    big = inbox / "mywealth-big.txt"
    big.write_bytes(mobile.FILE_MAGIC.encode() + b"\n" + b"a" * (mobile.MAX_FILE_BYTES + 1))
    names = [f["name"] for f in mobile.scan_inbox(inbox)]
    assert sorted(names) == [good.name, "mywealth-20261022-1031 (1).txt"]
    assert mobile.scan_inbox(None) == [] and mobile.scan_inbox(tmp_path / "missing") == []


def test_inbox_dir_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(mobile, "downloads_dir", lambda: tmp_path / "Downloads")
    prefs = dict(settings.DEFAULTS)
    assert mobile.inbox_dir(prefs, tmp_path / "data") == tmp_path / "Downloads"
    assert mobile.inbox_dir(prefs, tmp_path / "data", demo=True) == tmp_path / "data" / "inbox"
    assert mobile.inbox_dir({**prefs, "mobile_inbox_dir": str(tmp_path / "x")}, tmp_path) == tmp_path / "x"
    assert mobile.inbox_dir({**prefs, "mobile_inbox_enabled": False}, tmp_path) is None


def test_inbox_setting_validation(db, tmp_path):
    assert settings.update(db, {"mobile_inbox_dir": f" {tmp_path} "})["mobile_inbox_dir"] == str(tmp_path)
    with pytest.raises(settings.SettingsError):
        settings.update(db, {"mobile_inbox_dir": "relative/folder"})
    assert "mobile_inbox_dir" in settings.MACHINE_KEYS and "mobile_inbox_enabled" in settings.MACHINE_KEYS


def test_read_and_delete_refuse_other_files(tmp_path):
    inbox = tmp_path / "in"
    _enc_file(inbox, "mywealth-a.txt", "payload")
    (tmp_path / "mywealth-outside.txt").write_text(f"{mobile.FILE_MAGIC}\n")
    assert mobile.read_inbox_file(inbox, "mywealth-a.txt").splitlines()[1] == "payload"
    for bad in ("../mywealth-outside.txt", "..\\mywealth-outside.txt", "secret.txt", "mywealth-a.csv"):
        with pytest.raises(ValidationError):
            mobile.read_inbox_file(inbox, bad)
    assert mobile.delete_inbox_files(inbox, ["../mywealth-outside.txt", "mywealth-a.txt"]) == ["mywealth-a.txt"]
    assert (tmp_path / "mywealth-outside.txt").exists() and not (inbox / "mywealth-a.txt").exists()


# ------------------------------------------------------------ dedup by id --


def test_ids_already_imported_are_skipped(db, conto):
    a, b, c = (str(uuid.uuid4()) for _ in range(3))
    res = csvio.import_csv(db, _csv((a, "pane"), (b, "latte")), track_ids=True)
    assert res["imported"] == 2 and res["skipped"] == 0
    prev = csvio.preview(db, _csv((a, "pane"), (c, "uova"), (c, "uova")), track_ids=True)
    assert prev["valid"] == 1 and prev["skipped"] == 2
    assert [r.get("skipped") for r in prev["rows"]] == ["già importata", None, "già importata"]
    res = csvio.import_csv(db, _csv((a, "pane"), (b, "latte"), (c, "uova")), track_ids=True)
    assert res["imported"] == 1 and res["skipped"] == 2
    assert balance(db, conto["id"]) == "95.50"
    again = csvio.import_csv(db, _csv((c, "uova")), track_ids=True)
    assert again["imported"] == 0 and again["skipped"] == 1


def test_missing_or_bad_id_is_an_error(db, conto):
    prev = csvio.preview(db, _csv(("", "pane"), ("not-a-uuid", "latte")), track_ids=True)
    assert prev["errors"] == 2 and "id mancante" in prev["rows"][0]["errors"]


def test_failed_import_records_no_id(db, conto):
    a = str(uuid.uuid4())
    text = _csv((a, "pane")) + "05/03/2026;spesa;Inesistente;;1;;Spesa alimentare;x;" + str(uuid.uuid4()) + ";\r\n"
    with pytest.raises(ValidationError):
        csvio.import_csv(db, text, track_ids=True)
    assert csvio.import_csv(db, _csv((a, "pane")), track_ids=True)["imported"] == 1


def test_plain_csv_import_ignores_ids(db, conto):
    a = str(uuid.uuid4())
    assert csvio.import_csv(db, _csv((a, "pane")))["imported"] == 1
    assert csvio.import_csv(db, _csv((a, "pane")))["imported"] == 1  # only a duplicate warning


# -------------------------------------------------------------------- API --


def test_api_pair_inbox_and_import(server, tmp_path):
    httpd, client = server
    ctx = httpd.ctx
    make_account(ctx.db, "Conto", "EUR", "0", "2026-01-01")
    assert client.json("GET", "/api/mobile/key")[0] == 404
    status, pair = client.json("POST", "/api/mobile/pair", {})
    assert status == 200 and pair["qr"]
    assert client.json("GET", "/api/mobile/key")[1]["kid"] == pair["kid"]
    status, st = client.json("GET", "/api/mobile")
    assert st["paired"] and st["inbox"]["dir"] == str(ctx.data_dir / "inbox")  # demo: never the real Downloads

    inbox = tmp_path / "inbox"
    assert client.json("PUT", "/api/settings", {"mobile_inbox_dir": str(inbox)})[0] == 200
    _enc_file(inbox, "mywealth-1.txt", "abc")
    _enc_file(inbox, "mywealth-2.txt", "def")
    _, found = client.json("GET", "/api/mobile/inbox")
    assert [f["name"] for f in found["files"]] == ["mywealth-1.txt", "mywealth-2.txt"]
    _, f = client.json("GET", "/api/mobile/inbox/file?name=mywealth-1.txt")
    assert f["content"].splitlines() == [mobile.FILE_MAGIC, "abc"]
    assert client.json("GET", "/api/mobile/inbox/file?name=..%2Fx.txt")[0] == 400

    text = _csv((str(uuid.uuid4()), "pane")).encode()
    status, prev = client.json("POST", "/api/mobile/preview", text)
    assert status == 200 and prev["valid"] == 1
    bad = (_csv((str(uuid.uuid4()), "pane")) + "05/03/2026;spesa;Nessuno;;1;;Spesa alimentare;x;"
           + str(uuid.uuid4()) + ";\r\n").encode()
    assert client.json("POST", "/api/mobile/import?files=mywealth-1.txt", bad)[0] == 400
    assert (inbox / "mywealth-1.txt").exists()  # not imported: the file stays
    status, res = client.json("POST", "/api/mobile/import?files=" + quote("mywealth-1.txt/mywealth-2.txt"), text)
    assert status == 200 and res["imported"] == 1 and res["deleted"] == ["mywealth-1.txt", "mywealth-2.txt"]
    assert client.json("GET", "/api/mobile/inbox")[1]["files"] == []

    assert client.json("PUT", "/api/settings", {"mobile_inbox_enabled": False})[0] == 200
    assert client.json("GET", "/api/mobile/inbox")[1] == {"enabled": False, "dir": None, "files": []}


# ------------------------------------------------------- shared test vector --


def test_vector_matches_python_side(db):
    """tests/vectors/mobile-v1.*: written by the PWA code with a published TEST key; the JS
    tests decrypt it, here the key id and the CSV are checked against the desktop."""
    from pathlib import Path

    vectors = Path(__file__).parent / "vectors"
    meta = json.loads((vectors / "mobile-v1.json").read_text(encoding="utf-8"))
    assert meta["kid"] == mobile.key_id(bytes(range(32)))
    magic, body = (vectors / "mobile-v1.txt").read_text(encoding="ascii").splitlines()
    assert magic == mobile.FILE_MAGIC
    header = json.loads(base64.urlsafe_b64decode(body.split(".")[0] + "=="))
    assert header["kid"] == meta["kid"] and header["alg"] == "AES-256-GCM" and header["v"] == 1
    make_account(db, "Conto corrente", "EUR", "0", "2026-01-01")
    make_account(db, "Conto svizzero", "CHF", "0", "2026-01-01")
    text = (vectors / "mobile-v1.csv").read_text(encoding="utf-8")
    res = csvio.import_csv(db, text, track_ids=True)
    assert res["imported"] == 3
    assert [r["description"] for r in res["rows"]][0] == 'Panetteria "Da Mario"; centro'
    assert csvio.preview(db, text, track_ids=True)["skipped"] == 3
