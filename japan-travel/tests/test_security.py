from app.security import hash_password, verify_password


def test_hash_and_verify_roundtrip():
    password_hash, salt = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", password_hash, salt)


def test_verify_rejects_wrong_password():
    password_hash, salt = hash_password("correct-horse-battery-staple")
    assert not verify_password("wrong-password", password_hash, salt)


def test_salts_are_unique_per_call():
    _, salt_a = hash_password("same-password")
    _, salt_b = hash_password("same-password")
    assert salt_a != salt_b
