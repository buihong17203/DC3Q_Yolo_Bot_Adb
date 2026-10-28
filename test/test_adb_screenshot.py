from __future__ import annotations

import struct
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from app.adb.client import AdbClient
from app.adb.device import AdbDevice
from app.adb.screenshot import AdbScreenshot
from app.vision.image import ImageFrame


class TestAdbScreenshot(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock(spec=AdbClient)
        self.device = MagicMock(spec=AdbDevice)
        self.device.serial = "emulator-5554"
        self.screenshot = AdbScreenshot(self.client, self.device)

    def test_capture_socket_raw_success(self):
        w, h = 10, 10
        raw_rgba = np.zeros((h, w, 4), dtype=np.uint8)
        raw_rgba[:, :, 0] = 255  # Red channel
        raw_rgba[:, :, 3] = 255  # Alpha

        header = struct.pack("<IIII", w, h, 1, 0)
        payload = header + raw_rgba.tobytes()

        mock_sock = MagicMock()
        # recv(4) for OKAY responses, then header, then body
        mock_sock.recv.side_effect = [b"OKAY", b"OKAY", header]
        
        def mock_recv_into(buf, n):
            body = raw_rgba.tobytes()
            buf[:len(body)] = body
            mock_sock.recv_into.side_effect = lambda b, m: 0
            return len(body)
            
        mock_sock.recv_into.side_effect = mock_recv_into

        with patch("socket.create_connection", return_value=mock_sock):
            frame = self.screenshot.capture_frame()

        self.assertIsInstance(frame, ImageFrame)
        self.assertEqual(frame.width, w)
        self.assertEqual(frame.height, h)
        self.assertEqual(frame.data.shape, (h, w, 3))
        self.assertEqual(frame.data[0, 0, 0], 255)

    def test_capture_fallback_on_socket_failure(self):
        mock_completed = MagicMock()
        import cv2
        dummy_img = np.zeros((20, 20, 3), dtype=np.uint8)
        encoded_png = cv2.imencode(".png", dummy_img)[1].tobytes()
        mock_completed.stdout = encoded_png
        self.client.run.return_value = mock_completed

        with patch("socket.create_connection", side_effect=OSError("Connection refused")):
            img = self.screenshot.capture_cv2()

        self.assertEqual(img.shape, (20, 20, 3))
        self.client.run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
