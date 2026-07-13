# Changelog

## [2.3.1]

### Added

- Existing destination MKVs are inspected for tv-converter metadata.
- Legacy HEVC MKVs without metadata are upgraded through a metadata-only stream-copy remux.
- Added `--repair-moved-recordings` with repeatable `--search-directory`
  options to repair missing TVHeadend paths through `dvr/entry/filemoved`.
- Added `--refresh-plex` to call the configured Plex refresh URL without
  starting the converter.
- Configuration read and YAML errors now produce a concise CLI error and full
  command help instead of a Python traceback.
- Source deletion is disabled for MythTV recordings; the configured
  `delete_source_after_import` setting applies only to non-MythTV sources.
- Moved-recording repair now reads `dvr/entry/grid_removed`, processes only
  entries with TVHeadend status `File missing`, ignores intentionally removed
  files, and never selects the unchanged old path as a repair target.

### Changed

- MKVs whose `encoded_by` tag starts with `tv-converter` are skipped as already processed.
- An existing MKV that cannot be analyzed is left untouched and reported with a warning for manual review.
- A failed Plex refresh no longer prevents configured source file deletion after
  a successful TVHeadend import.

## [2.3.0]

### Added

- Automatic TVHeadend source notifications through the `/comet/ws` WebSocket.
- Automatic reconnection after a TVHeadend WebSocket disconnect.
- Automatic `/api/dvr/entry/filemoved` use when source and destination refer to
  the same TVHeadend instance.
- Source-specific change detection: MythTV polling and TVHeadend events.

### Changed

- Each recording is now transcoded, imported, postprocessed, and optionally
  deleted before the next queue item starts.
- TVHeadend busy checks run before transcoding and again before import.
- Relevant WebSocket events received during transcoding are coalesced and cause
  one source rescan after the current recording is completed.
- Removed the HTTP wakeup server and post-record hook workflow.

### Configuration changes

The configuration layout is not backward compatible with 2.2.x:

- `source.<type>.output.directory` moved to
  `destination.tvheadend.output.directory`.
- `source.<type>.delete_after_import` was replaced by
  `destination.tvheadend.delete_source_after_import`.
- The former top-level `tvheadend` destination section moved to
  `destination.tvheadend`.
- `service.poll_interval` moved to `source.mythtv.poll_interval` and now applies
  only to MythTV sources.
- The complete `http` section was removed. TVHeadend sources now use the
  WebSocket automatically and require no wakeup configuration.

Existing `/etc/tv-converter/config.yaml` files must be migrated manually using
`config.yaml.example` before starting version 2.3.0.

## [2.2.0]

### Added

- Authenticated HTTP wakeup endpoint.

## [2.1.0]

### Added

- MKV metadata.

## [2.0.0]

### Added

- Debian packaging and automated GitHub releases.
