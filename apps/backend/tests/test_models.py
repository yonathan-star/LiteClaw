import main
from fastapi.testclient import TestClient

TOKEN = "test-token"


def authed() -> TestClient:
    return TestClient(main.app, headers={"Authorization": f"Bearer {TOKEN}"})


def test_model_workflow_stub(tmp_path) -> None:
    main.API_TOKEN = TOKEN
    previous_data_dir = main.DATA_DIR
    try:
        main.DATA_DIR = tmp_path
        main.reload_models()
        client = authed()

        initial = client.get("/v1/models")
        assert initial.status_code == 200
        assert initial.json()["installed_models"] == []

        add = client.post(
            "/v1/models/download",
            json={"model_id": "tiny-q4", "display_name": "Tiny Q4 Stub"},
        )
        assert add.status_code == 200, add.text
        payload = add.json()
        assert any(
            model["model_id"] == "tiny-q4" for model in payload["installed_models"]
        )
        assert payload["default_model_id"] == "tiny-q4"

        set_default = client.post(
            "/v1/models/set-default", json={"model_id": "tiny-q4"}
        )
        assert set_default.status_code == 200
        assert set_default.json()["default_model_id"] == "tiny-q4"
    finally:
        main.DATA_DIR = previous_data_dir
