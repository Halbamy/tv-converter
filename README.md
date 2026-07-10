# tv-converter v1.3.3

`tv-converter` konvertiert oder migriert TV-Aufnahmen aus MythTV oder TVHeadend
und importiert sie nach TVHeadend.

## Installation

```bash
cd /home/plex
unzip tv-converter-v1.3.0.zip
cd tv-converter-v1.3.0
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
```

## systemd User-Service

```bash
mkdir -p ~/.config/systemd/user
cp systemd/tv-converter.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable tv-converter.service
systemctl --user start tv-converter.service
```

Konfiguration neu laden:

```bash
systemctl --user reload tv-converter.service
```

Die Service-Datei enthält dafür:

```ini
ExecReload=/bin/kill -HUP $MAINPID
```

Die Konfiguration wird zwischen zwei Aufnahmen neu geladen. Eine laufende
Konvertierung wird dadurch nicht unterbrochen.

Hinweis: `systemctl --user` funktioniert zuverlässig nach einer direkten SSH-
Anmeldung als Benutzer `plex`. Eine per `su plex` geöffnete Shell besitzt meist
keinen User-Bus.

## Konfiguration

Wichtige Defaults:

```yaml
service:
  poll_interval: 300

mqtt:
  enabled: true
  broker: 192.168.0.13
  pause_watt: 0
  resume_watt: 50

tvheadend:
  url: http://192.168.0.33:9981
  idle:
    enabled: true
    poll_interval: 300
```

## TVHeadend Idle Protection

Vor der Konvertierung, vor dem Import, vor Plex-Refresh und vor dem Löschen
wartet der Converter, bis TVHeadend idle ist.

Idle bedeutet:

- keine laufenden Aufnahmen
- keine aktiven Subscriptions

## Löschen der Quelle

Pro Quelle:

```yaml
source:
  mythtv:
    delete_after_import: false
  tvheadend:
    delete_after_import: false
```

Gelöscht wird nur nach erfolgreichem:

1. Transcoding oder Copy
2. TVHeadend-Import
3. Plex-Refresh, falls aktiviert
4. TVHeadend idle

## Plex Postprocessing

```yaml
postprocessing:
  plex:
    enabled: true
    refresh_url: "https://192.168.0.28:32400/library/sections/4/refresh?X-Plex-Token=TOKEN"
    verify_ssl: false
    timeout: 10
```

Wenn Plex-Refresh fehlschlägt, werden Quelldateien nicht gelöscht.

## Encoder Defaults

Aus den Benchmarks übernommen:

```yaml
profiles:
  sd:
    qsv_global_quality: 28
    vaapi_qp: 29
  hd:
    qsv_global_quality: 24
    vaapi_qp: 25
```

VAAPI wird im Auto-Modus zuerst getestet, danach QSV, danach Software.

## MQTT

Status:

```text
tv-converter/status
```

Control:

```text
tv-converter/control
```

Befehle:

- `pause`
- `resume`
- `stop`

`reload` erfolgt bewusst über `systemctl reload`.

## Dry-Run

```bash
python main.py --dry-run --show-ffmpeg --show-tvh-json
```


## v1.3.1: TVHeadend Persistent Authentication

TVHeadend-Zugriffe verwenden jetzt einen gemeinsamen Client für Quelle, Ziel und
Idle-Monitor. Unterstützt werden Basic Auth und Persistent Authentication Code.

Beispiel:

```yaml
tvheadend:
  url: http://192.168.0.33:9981
  authentication:
    type: persistent_auth
    auth_code: "DEIN_CODE"
```

Für Basic Auth:

```yaml
tvheadend:
  url: http://192.168.0.33:9981
  authentication:
    type: basic
    username: tvh-user
    password: tvh-password
```

Dasselbe Schema gilt für `source.tvheadend`.

Hinweis: Der Idle-Monitor benötigt Zugriff auf TVHeadend-Status-Endpunkte. Dafür
muss der verwendete Persistent Authentication Code ausreichende Rechte besitzen.


## v1.3.2: MythTV deletepending Filter

MythTV-Aufnahmen, die bereits zum Löschen vorgemerkt sind, werden nicht mehr
für die Konvertierung ausgewählt.

Die MythTV-Abfrage filtert jetzt:

```sql
WHERE
    COALESCE(r.deletepending, 0) = 0
```

Damit verarbeitet `tv-converter` nur noch aktive MythTV-Aufnahmen und ignoriert
Einträge, die MythTV bereits für das Löschen markiert hat.


## v1.3.3: MythTV deletepending Safety

MythTV-Aufnahmen, die bereits zum Löschen vorgemerkt sind, werden vollständig
ignoriert.

Das bedeutet:

- kein Queue-Eintrag
- kein Transcoding
- kein TVHeadend-Import
- kein Plex-Refresh
- kein Löschen durch `tv-converter`

Die MythTV-Abfrage filtert weiterhin:

```sql
WHERE
    COALESCE(r.deletepending, 0) = 0
```

Zusätzlich enthält das Modell ein `deletepending`-Flag und es gibt Sicherheits-
prüfungen vor Verarbeitung, TVHeadend-Import und Löschen. Dadurch kann ein
deletepending-Eintrag auch dann nicht importiert oder gelöscht werden, falls er
durch spätere Änderungen doch in den Verarbeitungspfad gelangt.
