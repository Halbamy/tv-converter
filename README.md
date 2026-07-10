# tv-converter v2.3.0

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
6. Delete the source only when `delete_source_after_import` is enabled and all
   preceding steps succeeded.

When the TVHeadend source and destination URLs refer to the same instance,
`/api/dvr/entry/filemoved` updates the existing DVR entry. Otherwise a new DVR
entry is created with `/api/dvr/entry/create`.

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
