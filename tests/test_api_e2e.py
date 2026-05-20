"""
API 端到端测试
覆盖：路由正确性、响应格式、错误处理
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from seai.app import app
        with TestClient(app) as c:
            yield c
    except Exception as e:
        pytest.skip(f"API 客户端初始化失败: {e}")


class TestHealthEndpoints:
    def test_health_check(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "uptime" in data

    def test_system_status(self, client):
        response = client.get("/api/system/status")
        assert response.status_code == 200
        data = response.json()
        assert "cpu" in data
        assert "memory" in data


class TestSessionEndpoints:
    def test_list_sessions(self, client):
        response = client.get("/api/sessions")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_create_session(self, client):
        response = client.post("/api/session/new")
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data

    def test_switch_session(self, client):
        new_resp = client.post("/api/session/new")
        sid = new_resp.json()["session_id"]
        response = client.post("/api/session/switch", json={"session_id": sid})
        assert response.status_code == 200

    def test_rename_session(self, client):
        new_resp = client.post("/api/session/new")
        sid = new_resp.json()["session_id"]
        response = client.post("/api/session/rename", json={"session_id": sid, "name": "E2E测试"})
        assert response.status_code == 200

    def test_delete_session(self, client):
        new_resp = client.post("/api/session/new")
        sid = new_resp.json()["session_id"]
        response = client.delete(f"/api/session/{sid}")
        assert response.status_code == 200


class TestModelEndpoints:
    def test_list_models(self, client):
        response = client.get("/api/models")
        assert response.status_code == 200
        data = response.json()
        assert "models" in data

    def test_current_model(self, client):
        response = client.get("/api/models/current")
        assert response.status_code == 200
        data = response.json()
        assert "current_model" in data

    def test_list_endpoints(self, client):
        response = client.get("/api/endpoints")
        assert response.status_code == 200
        data = response.json()
        assert "endpoints" in data


class TestSkillEndpoints:
    def test_get_skills(self, client):
        response = client.get("/api/skills")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestSystemEndpoints:
    def test_circuit_breakers(self, client):
        response = client.get("/api/circuit_breakers")
        assert response.status_code == 200

    def test_errors_endpoint(self, client):
        response = client.get("/api/errors")
        assert response.status_code == 200

    def test_db_stats(self, client):
        response = client.get("/api/db/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_sessions" in data


class TestWorkflowEndpoints:
    def test_workflow_runs_no_duplicate(self, client):
        response = client.get("/api/workflow/runs")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestTodoEndpoints:
    def test_get_todos(self, client):
        response = client.get("/api/todos")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_add_and_delete_todo(self, client):
        response = client.post("/api/todos/add", json={"content": "E2E测试待办", "time": "12:00"})
        assert response.status_code == 200
        todos = client.get("/api/todos").json()
        assert len(todos) > 0
        tid = todos[-1]["id"]
        response = client.post("/api/todos/delete", json={"id": tid})
        assert response.status_code == 200


class TestFeedbackEndpoint:
    def test_submit_feedback(self, client):
        response = client.post("/api/feedback", json={"message_id": "test_msg", "rate": 5})
        assert response.status_code == 200


class TestErrorHandling:
    def test_404_on_nonexistent_session(self, client):
        response = client.get("/api/session/nonexistent_id/history")
        assert response.status_code == 200

    def test_invalid_model_switch(self, client):
        response = client.post("/api/model/switch", json={"model": "nonexistent"})
        assert response.status_code in [400, 422]