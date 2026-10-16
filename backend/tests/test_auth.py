from tests.conftest import signup_and_login


def test_register_and_login(client):
    res = client.post(
        "/auth/register", json={"email": "Nana@Example.com", "password": "supersecret1"}
    )
    assert res.status_code == 201
    assert res.json()["email"] == "nana@example.com"  # normalized
    assert "password" not in res.json()

    res = client.post(
        "/auth/login", data={"username": "nana@example.com", "password": "supersecret1"}
    )
    assert res.status_code == 200
    assert res.json()["token_type"] == "bearer"


def test_register_rejects_duplicate_and_short_password(client):
    payload = {"email": "a@b.com", "password": "supersecret1"}
    assert client.post("/auth/register", json=payload).status_code == 201
    assert client.post("/auth/register", json=payload).status_code == 409
    bad = {"email": "c@d.com", "password": "short"}
    assert client.post("/auth/register", json=bad).status_code == 422


def test_login_wrong_password(client):
    client.post("/auth/register", json={"email": "a@b.com", "password": "supersecret1"})
    res = client.post("/auth/login", data={"username": "a@b.com", "password": "nope-nope"})
    assert res.status_code == 401


def test_me_requires_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    headers = signup_and_login(client)
    assert client.get("/auth/me", headers=headers).json()["email"] == "nana@example.com"
