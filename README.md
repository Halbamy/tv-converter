# tv-converter v2.1.0

`tv-converter` converts or migrates MythTV and TVHeadend recordings and imports
results into TVHeadend.

Version 2.0.0 introduced Debian packages and tag-based GitHub releases. Runtime
behaviour is based on v1.3.3.

## Debian installation

Download the `.deb` file from the matching GitHub release and install it:

```bash
sudo apt install ./tv-converter_2.1.0_all.deb
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
./packaging/build-deb.sh 2.1.0
```

The package is written to:

```text
dist/tv-converter_2.1.0_all.deb
```

## GitHub release workflow

Pushing a version tag builds and publishes the Debian package, source archive,
and checksums:

```bash
git tag v2.1.0
git push origin v2.1.0
```

The release contains:

```text
tv-converter_2.1.0_all.deb
tv-converter-2.1.0.zip
SHA256SUMS
```


## MKV metadata

Every MKV created by `tv-converter` contains container metadata. The metadata
is always enabled and does not require configuration.

The following tags are written:

- `title`: recording title
- `summary`: subtitle or episode title
- `description`: full programme description
- `network`: channel name
- `date`: recording date in `YYYY-MM-DD` format
- `comment`: `Imported by tv-converter`
- `encoded_by`: `tv-converter` including its version
- `encoder`: selected encoder (`hevc_vaapi`, `hevc_qsv`, `libx265`, or `copy`)
- `profile`: selected encoding profile, such as `hd` or `sd`

`encoder.type: none` now performs a stream-copy remux into MKV instead of a
filesystem copy. Video and audio are not re-encoded, but the output receives the
same metadata as transcoded recordings.

Inspect the tags with:

```bash
ffprobe -v error -show_entries format_tags output.mkv
```
