# tv-converter v2.3.1

`tv-converter` converts recordings from MythTV or TVHeadend and imports the
result into TVHeadend.

## Source handling

The source type determines how new recordings are detected automatically:

- `source.type: mythtv` uses the configured MythTV database polling interval.
- `source.type: tvheadend` listens to `ws(s)://<host>/comet/ws` and rescans the
  finished DVR entries after relevant `dvrentry`, `subscriptions`, or
  `connections` notifications.

WebSocket notifications are only wake-up signals. Events received during a
conversion are coalesced into one pending source scan and processed after the
current recording has completed its import and postprocessing flow.

## Processing flow

Each recording is completed before the next one starts:

1. Wait until TVHeadend has no active recordings and no active subscriptions.
2. Transcode one recording.
3. Wait until TVHeadend is idle again.
4. Update the destination TVHeadend instance.
5. Refresh Plex when configured.
6. Delete the source when `delete_source_after_import` is enabled and the
   TVHeadend import succeeded. A failed Plex refresh does not prevent deletion.

When the TVHeadend source and destination URLs refer to the same instance,
`/api/dvr/entry/filemoved` updates the existing DVR entry. Otherwise a new DVR
entry is created with `/api/dvr/entry/create`.

## Existing MKV detection

The destination MKV is the persistent processing state:

- MKVs whose `encoded_by` tag starts with `tv-converter` are considered fully
  processed and are skipped.
- Existing HEVC MKVs without tv-converter metadata are treated as legacy
  outputs. They are remuxed with stream copy and receive the current metadata;
  the video is not transcoded again.
- If an existing MKV cannot be analyzed with `ffprobe`, tv-converter logs a
  warning and skips it. The file is never replaced or repaired automatically.

The metadata-only remux writes to a temporary file and replaces the existing
MKV only after FFmpeg completed successfully.

## Configuration

The application distinguishes source and destination explicitly:

```yaml
source:
  type: tvheadend
  tvheadend:
    url: http://192.168.0.33:9981
    authentication:
      type: basic
      username: tv-converter
      password: secret
      auth_code:

destination:
  type: tvheadend
  tvheadend:
    enabled: true
    url: http://192.168.0.33:9981
    authentication:
      type: basic
      username: tv-converter
      password: secret
      auth_code:
    output:
      directory: /media/storage0/tvheadend/imported
    delete_source_after_import: false
```

Persistent authentication remains supported by the client. Some administrative
TVHeadend endpoints, including status and `filemoved`, may require Basic Auth
with sufficient privileges on TVHeadend 4.3.

For the complete configuration, see `config.yaml.example`.

## systemd

The Debian service reads `/etc/tv-converter/config.yaml`. Use an override for a
different user, group, or configuration path:

The package also installs a `tv-converter` command in the system `PATH`. It
uses the packaged virtual environment and `/etc/tv-converter/config.yaml` by
default:

```bash
tv-converter --dry-run
```

Moved TVHeadend recording paths can be repaired without starting the converter.
The configured destination output directory is searched recursively first;
additional directories are searched in the order given. Only missing paths are
changed, and the first exact filename match is sent to
`/api/dvr/entry/filemoved`:

```bash
tv-converter --repair-moved-recordings \
  --search-directory /media/archive \
  --search-directory /mnt/recordings
```

Use `--dry-run` to display the changes without updating TVHeadend.

The configured Plex refresh URL can be called independently without starting
the converter or processing its queue:

```bash
tv-converter --refresh-plex
```

This explicit command also performs the call when automatic Plex
postprocessing is disabled.

```bash
sudo systemctl edit tv-converter
```

Example:

```ini
[Service]
User=plex
Group=plex
ExecStart=
ExecStart=/var/lib/tv-converter/venv/bin/python /var/lib/tv-converter/main.py --config /home/plex/.config/tv-converter/config.yaml
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart tv-converter
```

## Tests

```bash
python3 -m compileall -q .
python3 -m unittest discover -s tests -v
```
