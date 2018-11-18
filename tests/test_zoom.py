# Copyright 2018 Minds.ai, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

import datetime
import time

from unittest.mock import MagicMock

import os
import responses
import zoom
import jwt

from configuration import ZoomConfig, SystemConfig

# pylint: disable=relative-beyond-top-level
from unittest_settings import TestSettingsBase


# pylint: disable=too-many-instance-attributes
class TestZoom(TestSettingsBase):
  # pylint: disable=invalid-name
  def setUp(self):
    super(TestZoom, self).setUp()

    self.zoom_object = ZoomConfig(self.zoom_config)
    self.sys_object = SystemConfig(self.internal_config)

    self.api = zoom.ZoomAPI(self.zoom_object, self.sys_object)

    # URLs
    self.single_recording_url = 'https://api.zoom.us/v2/meetings/some-meeting-id/recordings/rid'
    self.single_meeting_recording_info_url = 'https://api.zoom.us/v2/meetings/some-meeting-id/' \
                                             'recordings'
    self.single_recording_download = 'https://mindsai.zoom.us/recording/share/random-uid'
    self.signin_url = 'https://api.zoom.us/signin'

    # Test JSON payload to be returned from querying specific meeting ID for recordings.
    self.recording_return_payload = {'recording_files': [{
                                     'file_type': 'MP4',
                                     'recording_start': '2018-01-01T01:01:01Z',
                                     'download_url': self.single_recording_download,
                                     'id': 'some-recording-id'
                                     }]}

  def test_generate_jwt_valid_token(self):
    token = jwt.encode({'iss': self.zoom_object.key, 'exp': int(time.time() + 1800)},
                       str(self.zoom_object.secret),
                       algorithm='HS256')

    self.assertEqual(self.api.generate_jwt(), token)

  def test_generate_jwt_invalid_token(self):
    token = jwt.encode({'iss': 'fake', 'exp': int(time.time())},
                       str(self.zoom_object.secret),
                       algorithm='HS256')

    self.assertNotEqual(self.api.generate_jwt(), token)

  @responses.activate
  def test_delete_recording_errors(self):
    responses.add(responses.DELETE, self.single_recording_url, status=404)

    with self.assertRaises(zoom.ZoomAPIException):
      self.api.delete_recording('some-meeting-id', 'rid', b'token')

  @responses.activate
  def test_get_url_success(self):
    responses.add(responses.GET, self.single_meeting_recording_info_url, status=200,
                  json=self.recording_return_payload)

    self.assertEqual(self.api.get_recording_url('some-meeting-id', b'token'),
                     {'date': datetime.datetime(2018, 1, 1, 1, 1, 1),
                      'id': 'some-recording-id',
                      'url': self.single_recording_download}
                     )

  @responses.activate
  def test_get_recording_url_fail(self):
    responses.add(responses.GET, self.single_meeting_recording_info_url, status=404)

    with self.assertRaises(zoom.ZoomAPIException):
      self.api.get_recording_url('some-meeting-id', b'token')

    responses.add(responses.GET, self.single_meeting_recording_info_url, status=300)

    with self.assertRaises(zoom.ZoomAPIException):
      self.api.get_recording_url('some-meeting-id', b'token')

    responses.add(responses.GET, self.single_meeting_recording_info_url, status=500)

    with self.assertRaises(zoom.ZoomAPIException):
      self.api.get_recording_url('some-meeting-id', b'token')

  @responses.activate
  def test_downloading_file(self):
    responses.add(responses.POST, self.signin_url, status=200)
    responses.add(responses.GET, self.single_recording_download, status=200, stream=True)

    self.assertEqual(self.api.download_recording(self.single_recording_download),
                     '/tmp/random-uid.mp4')

    os.remove('/tmp/random-uid.mp4')

  @responses.activate
  def test_delete_meeting_recording(self):
    # For downloading recording.
    responses.add(responses.POST, self.signin_url, status=200)
    responses.add(responses.GET, self.single_recording_download, status=200, stream=True)

    # For sending DELETE http request for
    responses.add(responses.DELETE, self.single_meeting_recording_info_url, status=200,
                  json=self.recording_return_payload)

    self.assertEqual(self.api.pull_file_from_zoom('some-meeting-id', True),
                     {'success': False, 'date': None, 'filename': None})

  @responses.activate
  def test_delete_chat_transcript(self):
    responses.add(responses.DELETE, self.single_meeting_recording_info_url, status=200,
                  json={'recording_files': [{'file_type': 'CHAT'}]})

    self.assertEqual(self.api.pull_file_from_zoom('some-meeting-id', True),
                     {'success': False, 'date': None, 'filename': None})

  @responses.activate
  def test_handling_zoom_errors_file_pull(self):
    responses.add(responses.GET, self.single_meeting_recording_info_url, status=404)

    self.assertEqual(self.api.pull_file_from_zoom('some-meeting-id', True),
                     {'success': False, 'date': None, 'filename': None})

  @responses.activate
  def test_filesystem_errors_file_pull(self):
    responses.add(responses.GET, self.single_meeting_recording_info_url, status=200,
                  json=self.recording_return_payload)

    self.api.download_recording = MagicMock(side_effect=OSError('Could not write file!'))
    self.assertEqual(self.api.pull_file_from_zoom('some-meeting-id', True),
                     {'success': False, 'date': None, 'filename': None})