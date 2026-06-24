import pytest

from dungml_backend import render_token as rt


def test_mint_verify_roundtrip():
    tok = rt.mint("inst-1", "fog", now=1000)
    assert rt.verify(tok, "inst-1", now=1001) == "fog"


def test_verify_rejects_wrong_external_id():
    tok = rt.mint("inst-1", "gm", now=1000)
    with pytest.raises(rt.TokenError):
        rt.verify(tok, "inst-2", now=1001)


def test_verify_rejects_expired():
    tok = rt.mint("inst-1", "fog", now=1000)
    with pytest.raises(rt.TokenError):
        rt.verify(tok, "inst-1", now=10**9)  # far future → expired


def test_verify_rejects_tamper():
    tok = rt.mint("inst-1", "fog", now=1000)
    with pytest.raises(rt.TokenError):
        rt.verify(tok[:-2] + ("aa" if tok[-2:] != "aa" else "bb"), "inst-1", now=1001)
