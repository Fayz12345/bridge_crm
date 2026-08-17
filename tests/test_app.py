def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["db"] == "ok"


def test_login_page_renders(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"login" in response.data.lower() or b"sign" in response.data.lower()


def test_unauthenticated_dashboard_redirects(client):
    response = client.get("/dashboard/", follow_redirects=False)
    assert response.status_code in {302, 303, 307, 308}
