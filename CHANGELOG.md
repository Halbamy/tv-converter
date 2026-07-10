# Changelog

All notable changes to this project are documented in this file.

## [2.2.0]

### Added

- Authenticated HTTP wakeup endpoint `POST /ping` for event-driven source scans.
- Client address filtering with IPv4 or IPv6 addresses and CIDR networks.
- HTTP listener reload through the existing systemd configuration reload.

### Changed

- `service.poll_interval: 0` now disables periodic polling. After the initial
  source scan, the service waits for a valid HTTP wakeup.

### Configuration changes ⚠️

Add the optional HTTP wakeup section:

```yaml
http:
  enabled: false
  bind: 0.0.0.0
  allow: 192.168.0.0/24
  port: 8080
  token:
```

When `http.enabled` is `true`, `http.token` must be set. Setting
`service.poll_interval` to `0` also requires the HTTP wakeup service to be
enabled, otherwise configuration validation fails.

## [2.1.0]

### Added

- MKV container metadata for title, summary, description, channel, recording
  date, converter version, encoder, and encoding profile.

### Changed

- `encoder.type: none` now uses an FFmpeg stream-copy remux to MKV so metadata
  is written without re-encoding video or audio.

## [2.0.1]

### Fixed

- TVHeadend idle detection now uses only active subscriptions and no longer
  treats scheduled recordings as active.

## [2.0.0]

### Added

- Debian package build with an application-owned Python virtual environment.
- Tag-triggered GitHub Actions release workflow.
- Automatic `.deb`, source ZIP, and `SHA256SUMS` release artifacts.
- Configurable systemd service user and group through debconf.
- Default system account and group `tvc` when no custom values are selected.

### Changed

- Application files and the virtual environment are installed below
  `/var/lib/tv-converter`.
- The active configuration is stored at `/etc/tv-converter/config.yaml`.
- `config.yaml.example` is shipped below `/var/lib/tv-converter` and copied to
  `/etc/tv-converter/config.yaml` only when no active configuration exists.

