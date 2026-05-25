from src.main import create_app


def test_grading_routes_are_registered():
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/api/grading/{assignment_id}/start" in paths
    assert "/api/grading/{assignment_id}" in paths
    assert "/api/grading/{assignment_id}/dispute" in paths
