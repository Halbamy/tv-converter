from __future__ import annotations

from pathlib import Path

import mysql.connector

from models import Recording
from sources.base import RecordingSource


QUERY = '''
SELECT
    r.recordedid,
    r.title,
    r.subtitle,
    r.description,
    c.name AS sender,
    r.starttime,
    r.endtime,
    CONCAT(s.dirname, '/', r.basename) AS dateipfad,
    TIMESTAMPDIFF(MINUTE, r.starttime, r.endtime) AS laufzeit_minuten,
    COALESCE(r.deletepending, 0) AS deletepending
FROM recorded r
LEFT JOIN channel c
       ON r.chanid = c.chanid
LEFT JOIN storagegroup s
       ON s.groupname = r.storagegroup
      AND s.hostname = r.hostname
WHERE
    COALESCE(r.deletepending, 0) = 0
ORDER BY r.starttime ASC
'''


class MythTVSource(RecordingSource):
    def __init__(self, config: dict):
        self.config = config

    def get_recordings(self) -> list[Recording]:
        conn = mysql.connector.connect(
            host=self.config["host"],
            user=self.config["user"],
            password=self.config["password"],
            database=self.config["database"],
        )

        try:
            cur = conn.cursor()
            cur.execute(QUERY)
            recordings: list[Recording] = []

            for row in cur:
                (
                    recordedid,
                    title,
                    subtitle,
                    desc,
                    channel,
                    start,
                    end,
                    filename,
                    minutes,
                    deletepending,
                ) = row

                if not filename:
                    continue

                if bool(deletepending):
                    continue

                recordings.append(
                    Recording(
                        source="mythtv",
                        recording_id=str(recordedid),
                        title=title or "",
                        subtitle=subtitle or "",
                        description=desc or "",
                        channel=channel or "",
                        starttime=start,
                        endtime=end,
                        filename=Path(filename),
                        duration_minutes=int(minutes or 0),
                        deletepending=bool(deletepending),
                    )
                )

            return recordings

        finally:
            conn.close()
