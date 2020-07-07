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
import logging
import os
import time
from typing import TypeVar, cast, Dict, List

import schedule

from zoom_drive_connector import configuration as config, drive, slack, zoom

S = TypeVar("S", bound=config.APIConfigBase)


def download(
    zoom_conn: zoom.ZoomAPI, zoom_conf: config.ZoomConfig
) -> List[Dict[str, str]]:
    """Downloads all available recordings from Zoom and returns a list of dicts with all relevant
  information about the recording.

  :param zoom_conn: API object instance for Zoom.
  :param zoom_conf: configuration instance containing all Zoom API settings.
  :return: list of dictionaries containing meeting recording information.
  """
    result = []

    # Note, need type: ignore here as the return Union contains items without iterator
    meeting = {}  # type: Dict
    for meeting in zoom_conf.meetings:  # type: ignore
        meeting = cast(Dict, meeting)
        res = zoom_conn.pull_file_from_zoom(meeting["id"], rm=bool(zoom_conf.delete))
        if (res["success"]) and (res["filename"]):
            name = f'{res["date"].strftime("%Y%m%d")}-{meeting["name"]}.mp4'

            result.append(
                {
                    "meeting": meeting["name"],
                    "file": res["filename"],
                    "name": name,
                    "folder_id": meeting["folder_id"],
                    "slack_channel": meeting["slack_channel"],
                    "date": res["date"].strftime("%B %d, %Y at %H:%M"),
                    "unix": int(
                        res["date"].replace(tzinfo=datetime.timezone.utc).timestamp()
                    ),
                }
            )

    return result


def upload_and_notify(
    files: List, drive_conn: drive.DriveAPI, slack_conn: slack.SlackAPI
):
    """Uploads a list of files from the local filesystem to Google Drive.

  :param files: list of dictionaries containing file information.
  :param drive_conn: API instance for Google Drive.
  :param slack_conn: API instance for Slack.
  """
    for file in files:
        try:
            # Get url from upload function.
            file_url = drive_conn.upload_file(
                file["file"], file["name"], file["folder_id"]
            )

            # The formatted date/time string to be used for older Slack clients
            fall_back = f"{file['date']} UTC"

            # Only post message if the upload worked.
            message = (
                f'The recording of _{file["meeting"]}_ on '
                "_<!date^" + str(file["unix"]) + "^{date} at {time}|" + fall_back + ">_"
                f" is <{file_url}| now available>."
            )

            slack_conn.post_message(message, file["slack_channel"])
        except drive.DriveAPIException as e:
            raise e
        # Remove the file after uploading so we do not run out of disk space in our container.
        os.remove(file["file"])


def all_steps(
    zoom_conn: zoom.ZoomAPI,
    slack_conn: slack.SlackAPI,
    drive_conn: drive.DriveAPI,
    zoom_config: S,
):
    """Primary function dispatcher that calls functions which download files and then upload them and
  notifies people in Slack that they are on Google Drive.

  :param zoom_conn: API object instance for Zoom.
  :param slack_conn: API object instance for Slack.
  :param drive_conn: API object instance for Google Drive.
  :param zoom_config: configuration instance containing all Zoom API settings.
  """
    downloaded_files = download(zoom_conn, cast(config.ZoomConfig, zoom_config))
    upload_and_notify(downloaded_files, drive_conn, slack_conn)


def main():
    """Application entrypoint function. Configures logging, parses configuration file, and sets up
  proper container classes.
  """
    # App configuration.
    app_config = config.ConfigInterface(os.getenv("CONFIG", "/conf/config.yaml"))

    # Configure the logger interface to print to console with level INFO
    log = logging.getLogger("app")
    log.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(
        logging.Formatter("%(asctime)s %(module)s:%(levelname)s %(message)s")
    )
    log.addHandler(ch)

    log.info("Application starting up.")

    # Configure each API service module.
    zoom_api = zoom.ZoomAPI(app_config.zoom, app_config.internals)
    slack_api = slack.SlackAPI(app_config.slack)
    drive_api = drive.DriveAPI(
        app_config.drive, app_config.internals
    )  # This should open a prompt.

    # Run the application on a 10 minute schedule.
    all_steps(zoom_api, slack_api, drive_api, app_config.zoom)
    schedule.every(10).minutes.do(
        all_steps, zoom_api, slack_api, drive_api, app_config.zoom
    )
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
