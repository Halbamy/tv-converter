# tv-converter v2.0.0

`tv-converter` converts or migrates MythTV and TVHeadend recordings and imports
results into TVHeadend.

Version 2.0.0 introduces Debian packages and tag-based GitHub releases. Runtime
behaviour is based on v1.3.3.

## Debian installation

Download the `.deb` file from the matching GitHub release and install it:

```bash
sudo apt install ./tv-converter_2.0.0_all.deb
```

During interactive installation, Debian asks for the systemd service user and
group. Both default to `tvc`. When these defaults are selected, the package
creates the missing system user and group automatically.

For unattended installation, the defaults are used unless debconf was
preseeded.

## Installed paths

```text
/etc/tv-converter/config.yaml

/var/lib/tv-converter/
├── config.yaml.example
├── main.py
├── requirements.txt
├── sources/
├── systemd/
├── venv/
├── queue/
├── state/
└── cache/
```

The package ships `config.yaml.example` below `/var/lib/tv-converter`. During
installation, it is copied to `/etc/tv-converter/config.yaml` only if the active
configuration does not exist. Package upgrades therefore preserve the existing
configuration.

## First start

Edit the generated configuration:

```bash
sudo editor /etc/tv-converter/config.yaml
```

Then start the service:

```bash
sudo systemctl start tv-converter.service
sudo systemctl status tv-converter.service
```

The package enables the service but does not start it automatically during the
first installation.

Reload the configuration between recordings:

```bash
sudo systemctl reload tv-converter.service
```

Follow the journal:

```bash
journalctl -u tv-converter.service -f
```

## Changing the service user or group

Run the Debian configuration dialog again:

```bash
sudo dpkg-reconfigure tv-converter
```

The package regenerates `/etc/systemd/system/tv-converter.service` with the
selected `User=` and `Group=` values.

A custom user and group must already exist. Only the default `tvc` account and
group are created automatically.

The service account must have access to the configured recording directories
and, for hardware encoding, to the required `/dev/dri` device. Add it to groups
such as `video` or `render` when required.

## Building locally

```bash
./packaging/build-deb.sh 2.0.0
```

The package is written to:

```text
dist/tv-converter_2.0.0_all.deb
```

## GitHub release workflow

Pushing a version tag builds and publishes the Debian package, source archive,
and checksums:

```bash
git tag v2.0.0
git push origin v2.0.0
```

The release contains:

```text
tv-converter_2.0.0_all.deb
tv-converter-2.0.0.zip
SHA256SUMS
```


v2.0.1: Idle detection now uses only active subscriptions.
