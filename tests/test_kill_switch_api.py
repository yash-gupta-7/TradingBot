import live.api as api_module


class _StubEngine:
    def __init__(self):
        self.killed_with = None

    def kill(self, reason):
        self.killed_with = reason
        return {"closed_position": False, "halted": True}


def test_kill_endpoint_calls_engine_kill():
    api_module._engine = _StubEngine()
    client = api_module.app.test_client()

    resp = client.post("/api/kill")

    assert resp.status_code == 200
    assert resp.get_json() == {"closed_position": False, "halted": True}
    assert api_module._engine.killed_with == "dashboard kill switch"


def test_kill_endpoint_without_engine_returns_400():
    api_module._engine = None
    client = api_module.app.test_client()

    resp = client.post("/api/kill")

    assert resp.status_code == 400
