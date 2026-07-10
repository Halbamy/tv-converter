# Changelog

All notable changes to this project are documented in this file.

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
