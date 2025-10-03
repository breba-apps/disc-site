from collections import defaultdict
from unittest.mock import Mock, patch

from breba_app.storage import list_s3_structured, register_file, make_dir_tree, format_tree, list_files_in_private


class MockBlob:
    def __init__(self, name, metadata=None):
        self.name = name
        self.metadata = metadata


def test_register_file():
    """Test the register_file helper function"""
    directory = make_dir_tree()
    parts = ["images", "folder1", "test.png"]

    result = register_file(parts, directory)

    assert "images" in directory
    assert "folder1" in directory["images"]
    assert result is directory["images"]["folder1"]


def test_list_s3_structured_empty():
    """Test with no files"""
    with patch('google.cloud.storage.Client') as mock_client:
        # Setup mock bucket and blobs
        mock_bucket = Mock()
        mock_client.return_value.bucket.return_value = mock_bucket
        mock_bucket.list_blobs.return_value = []

        result = list_s3_structured("test_session")
        assert result == {}


def test_list_s3_structured_single_file():
    """Test with a single file"""
    with patch('google.cloud.storage.Client'):
        # Setup mock bucket
        mock_bucket = Mock()
        mock_blob = MockBlob(
            "test_session/images/test.png",
            {"description": "A test image"}
        )
        mock_bucket.list_blobs.return_value = [mock_blob]

        # Patch the private_bucket in the storage module
        with patch('breba_app.storage.private_bucket', mock_bucket):
            result = list_s3_structured("test_session")

        expected = defaultdict(dict, {
            "images": defaultdict(dict, {
                "test.png": {"__description__": "A test image"}
            })
        })
        assert result == expected


def test_list_s3_structured_nested():
    """Test with nested directory structure"""
    with patch('google.cloud.storage.Client'):
        # Setup mock bucket with multiple blobs
        mock_bucket = Mock()
        mock_blobs = [
            MockBlob("test_session/images/folder1/test1.png", {"description": "Image 1"}),
            MockBlob("test_session/images/folder1/test2.png", {"description": "Image 2"}),
            MockBlob("test_session/images/folder2/test3.png", {"description": "Image 3"}),
        ]
        mock_bucket.list_blobs.return_value = mock_blobs

        with patch('breba_app.storage.private_bucket', mock_bucket):
            result = list_s3_structured("test_session")

        expected = defaultdict(dict, {
            "images": defaultdict(dict, {
                "folder1": defaultdict(dict, {
                    "test1.png": {"__description__": "Image 1"},
                    "test2.png": {"__description__": "Image 2"}
                }),
                "folder2": defaultdict(dict, {
                    "test3.png": {"__description__": "Image 3"}
                })
            })
        })
        assert result == expected


def test_list_s3_structured_no_metadata():
    """Test files without metadata"""
    with patch('google.cloud.storage.Client'):
        mock_bucket = Mock()
        mock_blob = MockBlob("test_session/images/no_meta.png")
        mock_bucket.list_blobs.return_value = [mock_blob]

        with patch('breba_app.storage.private_bucket', mock_bucket):
            result = list_s3_structured("test_session")

        expected = defaultdict(dict, {
            "images": defaultdict(dict, {
                "no_meta.png": {"__description__": "No description"}
            })
        })
        assert result == expected


def test_list_s3_structured_multiple_sessions():
    """Test that files from different sessions are separated"""
    with patch('google.cloud.storage.Client'):
        mock_bucket = Mock()
        mock_blobs = [
            MockBlob("session1/images/test1.png", {"description": "Session 1"}),
            MockBlob("session2/images/test2.png", {"description": "Session 2"}),
        ]
        mock_bucket.list_blobs.return_value = mock_blobs

        with patch('breba_app.storage.private_bucket', mock_bucket):
            result = list_s3_structured("session1")

        # Assert list_blobs was called with the correct prefix
        mock_bucket.list_blobs.assert_called_once_with(prefix="session1")


def test_format_tree_simple():
    """Test formatting a simple flat tree"""
    tree = {
        "images": {
            "photo.png": {"__description__": "A photo"},
            "photo2.png": {"__description__": "A photo"}
        },
        "docs": {
            "readme.txt": {"__description__": "Readme"},
            "license.txt": {"__description__": "Readme"}
        }
    }

    lines = format_tree(tree)
    expected_lines = [
        "docs/",
        "  - license.txt (Readme)",
        "  - readme.txt (Readme)",
        "images/",
        "  - photo.png (A photo)",
        "  - photo2.png (A photo)",
    ]

    assert lines == expected_lines


def test_list_files_in_private():
    """Test final human-readable output with formatting"""
    mock_bucket = Mock()
    mock_blobs = [
        MockBlob("test_session/images/photo.png", {"description": "A photo"}),
        MockBlob("test_session/docs/readme.txt", {"description": "Readme"}),
    ]
    mock_bucket.list_blobs.return_value = mock_blobs

    with patch('breba_app.storage.private_bucket', mock_bucket):
        result = list_files_in_private("test_session")

    expected = (
        "docs/\n"
        "  - readme.txt (Readme)\n"
        "images/\n"
        "  - photo.png (A photo)"
    )

    assert result == expected


def test_list_files_in_private_no_metadata():
    """Test final human-readable output with formatting"""
    mock_bucket = Mock()
    mock_blobs = [
        MockBlob("test_session/images/photo.png", None),
    ]
    mock_bucket.list_blobs.return_value = mock_blobs

    with patch('breba_app.storage.private_bucket', mock_bucket):
        result = list_files_in_private("test_session")

    expected = (
        "images/\n"
        "  - photo.png (No description)"
    )

    assert result == expected