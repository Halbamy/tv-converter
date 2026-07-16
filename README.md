# tv-converter

`tv-converter` converts recordings from MythTV or TVHeadend and imports the
result into TVHeadend.

## Source handling

The source type determines how new recordings are detected automatically:

- `source.type: mythtv` uses the configured MythTV database polling interval.
- `source.type: tvheadend` listens to `ws(s)://<host>/comet/ws` and rescans the
  finished DVR entries after relevant `dvrentry`, `subscriptions`, or
  `connections` notifications.

WebSocket notifications wake both source scanning and TVHeadend busy-state
checks. If TVHeadend starts recording or gains an active subscription while
FFmpeg is running, conversion is paused until TVHeadend is idle again. While
TVHeadend is busy, repeated WebSocket messages are coalesced and the REST busy
status is checked at most once per minute.

Source deletion is disabled for MythTV recordings so the converter cannot
leave MythTV's database and related metadata in an inconsistent state.
`delete_source_after_import` applies only to non-MythTV sources.

## Processing flow

Each recording is completed before the next one starts:

1. Wait until TVHeadend has no active recordings and no active subscriptions.
2. Transcode one recording, pausing it if TVHeadend becomes busy.
3. Wait until TVHeadend is idle again.
4. Update the destination TVHeadend instance.
5. Delete the source when `delete_source_after_import` is enabled and the
   TVHeadend import succeeded.
6. Refresh Plex as the final postprocessing step when configured.

Pause reasons such as `PV`, `TVH`, `MANUAL`, and `MQTT` are combined. FFmpeg
resumes only after every active reason has been cleared. Before resuming from a
TVHeadend pause, the source file and DVR UUID are checked again. If the user
removed the recording, FFmpeg is stopped, its `.part` file is deleted, and the
next queued recording is processed.

When the TVHeadend source and destination URLs refer to the same instance,
`/api/dvr/entry/filemoved` updates the existing DVR entry. Otherwise a new DVR
entry is created with `/api/dvr/entry/create`.

## Output file naming

Output files are named according to the pattern: `{title}_{subtitle/description}_YYYYMMDD_hhmm.mkv`

Examples:
- `Tatort_Mord_20260714_2030.mkv`
- `Die_Sendung_Ohne_Untertitel_20260714_2100.mkv`

The subtitle field is used if available; otherwise the first 25 characters of
the description are used. If neither is available, "ohne_Untertitel" is used.
Invalid filename characters are sanitized automatically.

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
    output: original
    delete_source_after_import: false
```

Both `output: original` and the expanded form below write each converted file
beside its source recording:

```yaml
output:
  directory: original
```

To use one fixed destination directory, specify its path:

```yaml
output:
  directory: /media/storage0/tvheadend/imported
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
`/api/dvr/entry/filemoved`. Only entries returned by TVHeadend with the exact
status `File missing` are processed. If the file still exists at TVHeadend's
registered path, it is re-registered by sending the same path as `src` and
`dst`. Recordings intentionally removed through TVHeadend are ignored:

When `output: original` or `output.directory: original` is configured and no
additional search directory is supplied, every missing recording is searched
recursively below its own previously registered parent directory. For example,
`/dir/aufnahme/rec.mkv` is found again as
`/dir/aufnahme/serien/rec.mkv`.

```bash
tv-converter --repair-moved-recordings \
  --search-directory /media/archive \
  --search-directory /mnt/recordings
```

Use `--dry-run` to display the changes without updating TVHeadend.

Search for TVHeadend recordings by substring without starting the converter:

```bash
tv-converter --search "Tatort"
```

All DVR entries are searched, including upcoming, finished, failed, and removed
recordings. The search output displays the UUID, title, channel, timestamps,
filename, status, file size, removal and duplicate flags, comment, and error
details. The UUID can be used with `--rename-recordings --uuid "..."`.

Rename completed TVHeadend recordings to the current naming schema and notify
TVHeadend about the file moves:

```bash
tv-converter --rename-recordings --dry-run
```

To rename only a specific recording by UUID:

```bash
tv-converter --rename-recordings --uuid "12345678-1234-1234-1234-123456789abc"
```

Transcode a specific TVHeadend recording by UUID:

```bash
tv-converter --transcode --uuid "12345678-1234-1234-1234-123456789abc"
```

Use `--dry-run` to preview the transcode plan without starting the conversion:

```bash
tv-converter --transcode --uuid "12345678-1234-1234-1234-123456789abc" --dry-run
```

When `delete_source_after_import` is enabled, dry-run output also reports which
source file would be deleted after a successful TVHeadend update.

The recording is fetched from TVHeadend by UUID and converted using the
configured encoder. After a successful conversion, `/api/dvr/entry/filemoved`
updates the existing DVR entry from the source path to the converted file, so
the recording keeps its existing UUID. If `delete_source_after_import` is
enabled, the old TVHeadend source file is then deleted. The configured Plex
refresh runs last, after source deletion.

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

## Bash completion

Bash autocompletion is automatically installed when using the Debian package.
The completion script is installed to `/etc/bash_completion.d/tv-converter` and
will be automatically sourced by your shell.

After installation, reload your shell or run:

```bash
source /etc/bash_completion.d/tv-converter
```

### Manual setup (for manual installation or development)

If you installed tv-converter manually or want to enable completion in development:

Add this line to your `~/.bashrc` file:

```bash
source /path/to/tv-converter-completion.bash
```

Or install to `/etc/bash_completion.d/`:

```bash
sudo cp tv-converter-completion.bash /etc/bash_completion.d/tv-converter
```

Then reload your shell:

```bash
exec bash
```

The completion script requires argcomplete (installed as a dependency) and will automatically
use the venv-installed Python when available.

## Tests

```bash
python3 -m compileall -q .
python3 -m unittest discover -s tests -v
```
