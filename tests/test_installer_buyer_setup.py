"""Buyer bootstrap accepts no plaintext-secret arguments or implicit grants."""
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('buyer_setup_tests', Path(__file__).resolve().parents[1] / 'installer/buyer_setup.py')
buyer = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(buyer)


@pytest.mark.parametrize('password', ['short', 'a' * 73, 'line\nbreak-password', 'x' * 10, '\u68c9' * 25])
def test_invalid_buyer_passwords_are_rejected_without_echo(password):
    with pytest.raises(ValueError):
        buyer.validate_inputs('tenant-a', 'buyer@example.com', 'Buyer profile', password)


def test_buyer_profile_fields_and_password_are_separate():
    assert buyer.validate_inputs('tenant-a', 'buyer@example.com', ' Buyer profile ', 'synthetic-password-123') == ('buyer@example.com', 'Buyer profile')


def test_noninteractive_buyer_creation_never_reads_or_creates(monkeypatch):
    monkeypatch.setattr(buyer.sys.stdin, 'isatty', lambda: False)
    with pytest.raises(ValueError, match='interactive terminal'):
        buyer.interactive('tenant-a', 'buyer@example.com', 'Buyer', create=lambda *a: pytest.fail('created'), secret_value=lambda *a: pytest.fail('prompted'))


def test_buyer_password_confirmation_precedes_creation(monkeypatch):
    monkeypatch.setattr(buyer.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(buyer.sys.stderr, 'isatty', lambda: True)
    inputs = iter(['synthetic-password-one', 'synthetic-password-two'])
    with pytest.raises(ValueError, match='do not match'):
        buyer.interactive('tenant-a', 'buyer@example.com', 'Buyer', create=lambda *a: pytest.fail('created'), secret_value=lambda *a: next(inputs))


def test_buyer_interactive_callback_contains_no_role_or_admin_input(monkeypatch, capsys):
    monkeypatch.setattr(buyer.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(buyer.sys.stderr, 'isatty', lambda: True)
    calls = []
    result = buyer.interactive('tenant-a', 'buyer@example.com', 'Buyer profile',
        secret_value=lambda prompt: 'synthetic-password-123', create=lambda *args: calls.append(args) or {'created': True})
    assert result == {'created': True}
    assert calls == [('tenant-a', 'buyer@example.com', 'Buyer profile', 'synthetic-password-123')]
    assert 'synthetic-password' not in capsys.readouterr().out
