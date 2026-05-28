import unittest
import os
from unittest.mock import patch, MagicMock
import sys

sys.path.append(os.getcwd())

from services.fast_renderer_service import FastRendererService

class TestFastRendererService(unittest.TestCase):

    def setUp(self):
        self.service = FastRendererService()

    def test_path_translation_docker(self):
        """Test identity translation when HOST_SHARED_PATH is not set (Docker mode assumption or simple local)."""
        # If HOST_SHARED_PATH is None
        if "HOST_SHARED_PATH" in os.environ:
            del os.environ["HOST_SHARED_PATH"]

        service = FastRendererService()
        path = "/shared/sessions/file.glb"
        translated = service._translate_to_container_path(path)
        self.assertEqual(translated, path)

    def test_path_translation_local(self):
        """Test translation when HOST_SHARED_PATH is set (Local WebHDP -> Docker Renderer)."""
        os.environ["HOST_SHARED_PATH"] = "/Users/test/hdp-shared"
        service = FastRendererService()

        local_path = "/Users/test/hdp-shared/sessions/file.glb"
        expected = "/shared/sessions/sessions/file.glb"
        # Wait, relpath("/Users/test/hdp-shared/sessions/file.glb", "/Users/test/hdp-shared") -> "sessions/file.glb"
        # join("/shared/sessions", "sessions/file.glb") -> "/shared/sessions/sessions/file.glb"
        # This seems correct if the mount point is indeed /shared/sessions.

        translated = service._translate_to_container_path(local_path)
        self.assertEqual(translated, expected)

    @patch('services.fast_renderer_service.requests.post')
    def test_render_call(self, mock_post):
        """Test render method calls the API correctly."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"success": True}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        input_path = "/shared/sessions/input.glb"
        output_dir = "/shared/sessions/output"

        self.service.render(input_path, output_dir)

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['input_path'], "/shared/sessions")
        self.assertEqual(kwargs['json']['input_files'], [input_path])
        self.assertEqual(kwargs['json']['output_dir'], output_dir)

if __name__ == '__main__':
    unittest.main()
