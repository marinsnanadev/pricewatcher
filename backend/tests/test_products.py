from tests.conftest import signup_and_login

URL = "https://www.mercadolivre.com.br/fone-bluetooth-pro"


def create(client, auth, **extra):
    return client.post("/products", json={"url": URL, **extra}, headers=auth)


def test_create_product_seeds_history(client, auth):
    res = create(client, auth, target_price=99.9)
    assert res.status_code == 201
    product = res.json()
    assert product["store"] == "mercado_livre"
    assert product["name"] == "Fone Bluetooth Pro"
    assert product["current_price"] == 149.9
    assert product["target_price"] == 99.9
    assert product["active"] is True

    history = client.get(f"/products/{product['id']}/history", headers=auth).json()
    assert len(history) == 1
    assert history[0]["price"] == product["current_price"]


def test_create_rejects_invalid_url(client, auth):
    res = client.post("/products", json={"url": "not-a-url"}, headers=auth)
    assert res.status_code == 422


def test_create_maps_scrape_errors_to_http(client, auth):
    res = client.post("/products", json={"url": "https://unsupported.example/x"}, headers=auth)
    assert res.status_code == 422
    assert "supported" in res.json()["detail"]


def test_list_get_update_delete(client, auth):
    pid = create(client, auth).json()["id"]

    assert len(client.get("/products", headers=auth).json()) == 1
    assert client.get(f"/products/{pid}", headers=auth).json()["id"] == pid

    res = client.patch(f"/products/{pid}", json={"target_price": 50, "active": False}, headers=auth)
    assert res.json()["target_price"] == 50
    assert res.json()["active"] is False

    # null clears the target
    res = client.patch(f"/products/{pid}", json={"target_price": None}, headers=auth)
    assert res.json()["target_price"] is None
    assert res.json()["active"] is False  # untouched field stays

    assert client.delete(f"/products/{pid}", headers=auth).status_code == 204
    assert client.get(f"/products/{pid}", headers=auth).status_code == 404
    assert client.get(f"/products/{pid}/history", headers=auth).status_code == 404


def test_users_cannot_see_each_others_products(client, auth):
    pid = create(client, auth).json()["id"]
    other = signup_and_login(client, email="other@example.com")

    assert client.get("/products", headers=other).json() == []
    assert client.get(f"/products/{pid}", headers=other).status_code == 404
    assert client.patch(f"/products/{pid}", json={"active": False}, headers=other).status_code == 404
    assert client.delete(f"/products/{pid}", headers=other).status_code == 404


def test_products_require_auth(client):
    assert client.get("/products").status_code == 401
    assert client.post("/products", json={"url": URL}).status_code == 401


def test_create_sets_up_scheduling_and_first_run(client, auth):
    product = create(client, auth).json()
    assert product["check_interval_minutes"] == 360
    assert product["last_checked_at"] is not None
    assert product["next_check_at"] is not None
    assert product["consecutive_failures"] == 0

    runs = client.get(f"/products/{product['id']}/runs", headers=auth).json()
    assert len(runs) == 1
    assert (runs[0]["trigger"], runs[0]["status"], runs[0]["source"]) == ("create", "success", "json_ld")


def test_check_now_enqueues_and_is_owner_only(client, auth, enqueued):
    pid = create(client, auth).json()["id"]
    res = client.post(f"/products/{pid}/check", headers=auth)
    assert res.status_code == 202
    assert enqueued == [pid]

    other = signup_and_login(client, email="other@example.com")
    assert client.post(f"/products/{pid}/check", headers=other).status_code == 404
    assert client.get(f"/products/{pid}/runs", headers=other).status_code == 404
    assert enqueued == [pid]  # the intruder's call queued nothing


def test_check_now_reports_queue_down(client, auth):
    from app.main import app
    from app.routers.products import get_enqueue

    def broken(product_id):
        raise ConnectionError("redis down")

    app.dependency_overrides[get_enqueue] = lambda: broken
    pid = create(client, auth).json()["id"]
    assert client.post(f"/products/{pid}/check", headers=auth).status_code == 503


def test_patch_interval_reschedules_and_validates(client, auth):
    product = create(client, auth).json()
    res = client.patch(f"/products/{product['id']}", json={"check_interval_minutes": 30}, headers=auth)
    assert res.json()["check_interval_minutes"] == 30
    assert res.json()["next_check_at"] != product["next_check_at"]

    assert client.patch(f"/products/{product['id']}", json={"check_interval_minutes": 5}, headers=auth).status_code == 422
    # null can't clear a required field; it is ignored
    res = client.patch(f"/products/{product['id']}", json={"check_interval_minutes": None}, headers=auth)
    assert res.json()["check_interval_minutes"] == 30


def test_delete_removes_runs_too(client, auth):
    pid = create(client, auth).json()["id"]
    assert client.delete(f"/products/{pid}", headers=auth).status_code == 204
