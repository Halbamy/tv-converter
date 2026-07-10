# Changelog

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
