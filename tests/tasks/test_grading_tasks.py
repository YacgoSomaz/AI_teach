from pathlib import Path

from src.tasks.grading_tasks import read_assignment_image


class Assignment:
    def __init__(self, storage_url, mime_type="image/jpeg"):
        self.storage_url = storage_url
        self.mime_type = mime_type


def test_read_assignment_image_supports_file_url(tmp_path: Path):
    image_path = tmp_path / "question.jpg"
    image_path.write_bytes(b"image-bytes")

    image_bytes, mime_type = read_assignment_image(
        Assignment(f"file://{image_path}", "image/jpeg")
    )

    assert image_bytes == b"image-bytes"
    assert mime_type == "image/jpeg"


def test_read_assignment_image_supports_plain_local_path(tmp_path: Path):
    image_path = tmp_path / "question.jpg"
    image_path.write_bytes(b"image-bytes")

    image_bytes, mime_type = read_assignment_image(
        Assignment(str(image_path), "image/jpeg")
    )

    assert image_bytes == b"image-bytes"
    assert mime_type == "image/jpeg"
