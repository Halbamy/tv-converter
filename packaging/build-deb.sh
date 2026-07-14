#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=${1:-}

if [ -z "$VERSION" ]; then
    VERSION=$(sed -n 's/^VERSION = "\([^"]*\)"/\1/p' "$ROOT_DIR/models.py")
fi

VERSION=${VERSION#v}
PACKAGE=tv-converter
ARCH=all
BUILD_DIR="$ROOT_DIR/build/${PACKAGE}_${VERSION}_${ARCH}"
OUTPUT_DIR="$ROOT_DIR/dist"

rm -rf "$BUILD_DIR"
mkdir -p \
    "$BUILD_DIR/DEBIAN" \
    "$BUILD_DIR/usr/bin" \
    "$BUILD_DIR/var/lib/tv-converter" \
    "$OUTPUT_DIR"

cat > "$BUILD_DIR/DEBIAN/control" <<CONTROL
Package: $PACKAGE
Version: $VERSION
Section: video
Priority: optional
Architecture: $ARCH
Maintainer: Halbamy
Depends: python3 (>= 3.11), python3-venv, ca-certificates, ffmpeg, debconf, adduser
Description: Convert and migrate MythTV and TVHeadend recordings
 tv-converter transcodes or copies recordings, imports them into TVHeadend,
 supports PV surplus control over MQTT, and optional Plex refresh handling.
CONTROL

cp "$ROOT_DIR/packaging/debian/templates" "$BUILD_DIR/DEBIAN/templates"
cp "$ROOT_DIR/packaging/debian/config" "$BUILD_DIR/DEBIAN/config"
cp "$ROOT_DIR/packaging/debian/postinst" "$BUILD_DIR/DEBIAN/postinst"
cp "$ROOT_DIR/packaging/debian/prerm" "$BUILD_DIR/DEBIAN/prerm"
cp "$ROOT_DIR/packaging/debian/postrm" "$BUILD_DIR/DEBIAN/postrm"
chmod 0755 \
    "$BUILD_DIR/DEBIAN/config" \
    "$BUILD_DIR/DEBIAN/postinst" \
    "$BUILD_DIR/DEBIAN/prerm" \
    "$BUILD_DIR/DEBIAN/postrm"

find "$ROOT_DIR" -maxdepth 1 -type f \( \
    -name '*.py' -o \
    -name 'requirements.txt' -o \
    -name 'config.yaml.example' -o \
    -name 'README.md' -o \
    -name 'LICENSE' -o \
    -name 'CHANGELOG.md' \
\) -exec cp {} "$BUILD_DIR/var/lib/tv-converter/" \;

# Copy bash completion script separately
if [ -f "$ROOT_DIR/tv-converter-completion.bash" ]; then
    cp "$ROOT_DIR/tv-converter-completion.bash" "$BUILD_DIR/var/lib/tv-converter/"
fi

cp -a "$ROOT_DIR/sources" "$BUILD_DIR/var/lib/tv-converter/sources"
cp "$ROOT_DIR/packaging/tv-converter" "$BUILD_DIR/var/lib/tv-converter/tv-converter"
ln -s /var/lib/tv-converter/tv-converter "$BUILD_DIR/usr/bin/tv-converter"
find "$BUILD_DIR/var/lib/tv-converter" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$BUILD_DIR/var/lib/tv-converter" -type f -name '*.pyc' -delete
mkdir -p "$BUILD_DIR/var/lib/tv-converter/systemd"
cp "$ROOT_DIR/systemd/tv-converter.service.in" \
    "$BUILD_DIR/var/lib/tv-converter/systemd/tv-converter.service.in"

find "$BUILD_DIR/var/lib/tv-converter" -type d -exec chmod 0755 {} +
find "$BUILD_DIR/var/lib/tv-converter" -type f -exec chmod 0644 {} +
chmod 0755 "$BUILD_DIR/var/lib/tv-converter/main.py"
chmod 0755 "$BUILD_DIR/var/lib/tv-converter/tv-converter"

dpkg-deb --root-owner-group --build "$BUILD_DIR" \
    "$OUTPUT_DIR/${PACKAGE}_${VERSION}_${ARCH}.deb"

printf '%s\n' "$OUTPUT_DIR/${PACKAGE}_${VERSION}_${ARCH}.deb"
