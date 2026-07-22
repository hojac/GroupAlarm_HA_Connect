# GroupAlarm HA Connect

Inoffizielle Home-Assistant-Integration für [GroupAlarm](https://www.groupalarm.com/). Sie liest Alarmierungen ausgewählter Organisationseinheiten ein, stellt Einsatz- und Rückmeldedaten als Entitäten bereit und ermöglicht persönliche Rückmeldungen direkt aus Home Assistant.

> [!IMPORTANT]
> Dieses Projekt ist unabhängig und steht in keiner offiziellen Verbindung zur GroupAlarm GmbH. Die Integration befindet sich in aktiver Entwicklung.

## Inhalt

- [Funktionen](#funktionen)
- [Voraussetzungen](#voraussetzungen)
- [Installation](#installation)
- [Einrichtung](#einrichtung)
- [Aktualisierung](#aktualisierung)
- [Entitäten](#entitäten)
- [Rückmeldungen und Rückmeldefrist](#rückmeldungen-und-rückmeldefrist)
- [Dashboard-Vorlage](#dashboard-vorlage)
- [Wichtige Hinweise zu bestehenden Installationen](#wichtige-hinweise-zu-bestehenden-installationen)
- [Fehler melden und Funktionen vorschlagen](#fehler-melden-und-funktionen-vorschlagen)
- [Entwicklung und Releases](#entwicklung-und-releases)

## Funktionen

- Anmeldung mit einem GroupAlarm Personal Access Token (PAT)
- automatische Erkennung verfügbarer Organisationseinheiten
- Auswahl mehrerer Organisationseinheiten pro Instanz
- mehrere parallele Instanzen mit unterschiedlichen Organisationsauswahlen
- Alarmstatus, Alarmtext, Einsatznummer, Alarmzeit und Einsatzort
- Rückmeldungen `Komme` und `Komme nicht` aus Home Assistant
- serverbestätigter persönlicher Rückmeldestatus
- Statistik positiver, negativer und offener Rückmeldungen
- Ende und Countdown der Rückmeldefrist
- Koordinaten und Device Tracker für eine Kartenansicht
- Einrichtung und Optionen über die Home-Assistant-Oberfläche
- Installation und Aktualisierung über HACS
- fertige Lovelace-Vorlage für einen Alarmmonitor

## Voraussetzungen

- Home Assistant 2024.6.0 oder neuer
- ein GroupAlarm-Konto mit Zugriff auf mindestens eine Organisationseinheit
- ein gültiger GroupAlarm Personal Access Token
- HACS für die empfohlene Installation
- die Custom Card [`button-card`](https://github.com/custom-cards/button-card) nur bei Verwendung der mitgelieferten Dashboard-Vorlage

## Installation

### Über HACS (empfohlen)

1. In HACS **Integrationen** öffnen.
2. Über das Drei-Punkte-Menü **Benutzerdefinierte Repositorys** auswählen.
3. Dieses Repository eintragen:

   ```text
   https://github.com/hojac/GroupAlarm_HA_Connect
   ```

4. Als Typ **Integration** auswählen und das Repository hinzufügen.
5. **GroupAlarm HA Connect** installieren.
6. Home Assistant vollständig neu starten.

### Manuell

1. Die [aktuelle Version](https://github.com/hojac/GroupAlarm_HA_Connect/releases/latest) herunterladen.
2. Den Ordner `custom_components/groupalarm_ha_connect` nach `/config/custom_components/groupalarm_ha_connect` kopieren.
3. Home Assistant vollständig neu starten.

Die resultierende Struktur muss so aussehen:

```text
/config/custom_components/groupalarm_ha_connect/manifest.json
```

## Einrichtung

1. In Home Assistant **Einstellungen → Geräte & Dienste** öffnen.
2. **Integration hinzufügen** wählen.
3. Nach **GroupAlarm HA Connect** suchen.
4. Den Personal Access Token und das gewünschte Abfrageintervall eingeben.
5. Eine oder mehrere Organisationseinheiten auswählen.

Die Organisationsauswahl und das Abfrageintervall können später über **Konfigurieren** geändert werden.

Mehrere Instanzen mit demselben GroupAlarm-Benutzer sind möglich, sofern unterschiedliche Organisationsauswahlen verwendet werden. Das ist beispielsweise nützlich, wenn Organisationseinheiten auf getrennten Dashboards erscheinen sollen.

## Aktualisierung

Bei einer HACS-Installation:

1. Das Update in HACS installieren.
2. Home Assistant vollständig neu starten.
3. Bei ausbleibender Update-Anzeige die Repository-Informationen in HACS neu laden.

Die aktuelle stabile Version und ihre Änderungen stehen unter [GitHub Releases](https://github.com/hojac/GroupAlarm_HA_Connect/releases). Die vollständige Versionshistorie befindet sich im [Changelog](CHANGELOG.md).

## Entitäten

Für jede ausgewählte Organisationseinheit wird ein eigenes Gerät mit den zugehörigen Entitäten erstellt. Die automatisch erzeugten Entity-IDs enthalten einen aus dem Organisationsnamen gebildeten Slug, zum Beispiel:

```text
sensor.groupalarm_ha_connect_lgw_fuhrung_einsatzmeldung
binary_sensor.groupalarm_ha_connect_lgw_fuhrung_aktive_alarmierung
button.groupalarm_ha_connect_lgw_fuhrung_komme
```

Home Assistant kann die konkreten Entity-IDs bei Namenskonflikten abweichend vergeben. Verwende daher für Dashboards immer die IDs aus deiner eigenen Entitätenliste.

### Sensoren

| Entität | Inhalt |
|---|---|
| Alarm ID | technische ID der aktuellen Alarmierung |
| Einsatzmeldung | Alarmtext |
| Alarmierung Start | Startzeitpunkt der Alarmierung |
| Alarmzeitpunkt | formatiert lesbare Alarmzeit |
| Rückmeldefrist Ende | von GroupAlarm gemeldetes Ende der Rückmeldefrist |
| Rückmeldefrist Countdown | verbleibende Zeit beziehungsweise `abgelaufen` |
| Rückmeldefrist Status | Status der Rückmeldefrist |
| Einsatznummer | Einsatznummer oder Einsatzstichwort |
| Einsatzort | zusammengesetzte Alarmadresse |
| Latitude / Longitude | Koordinaten des Einsatzortes |
| Rückmeldungen Positive | Anzahl positiver Rückmeldungen |
| Rückmeldungen Negative | Anzahl negativer Rückmeldungen |
| Rückmeldungen Offen | Anzahl noch offener Rückmeldungen |
| Meine Rückmeldung | `komme`, `komme_nicht` oder `unbekannt` |
| User ID | eigene GroupAlarm-Benutzer-ID |

### Weitere Entitäten

| Typ | Entität | Funktion |
|---|---|---|
| Binary Sensor | Aktive Alarmierung | zeigt eine aktuell laufende Alarmierung an |
| Button | Komme | sendet eine positive Rückmeldung |
| Button | Komme nicht | sendet eine negative Rückmeldung |
| Device Tracker | Einsatzort | zeigt den Einsatzort auf einer Karte an |

## Rückmeldungen und Rückmeldefrist

Die Integration sendet persönliche Rückmeldungen an die GroupAlarm API. Eine Rückmeldung wird in Home Assistant erst als `komme` oder `komme_nicht` angezeigt, nachdem GroupAlarm sie bestätigt und die Integration den aktualisierten Alarmdatensatz abgerufen hat. Bis dahin bleiben beide Dashboard-Buttons neutral.

Unbeantwortete, nicht verfügbare oder abgelaufene Rückmeldungen werden als `unbekannt` behandelt. Der persönliche Status ist stets an die aktuelle Alarm-ID gebunden und wird nicht auf eine neue Alarmierung übertragen.

Das von GroupAlarm gelieferte Feld `alarm.endDate` bestimmt das Ende und den Countdown der Rückmeldefrist. Die aktive Alarmierung wird davon unabhängig ermittelt, sodass ein Einsatz auch nach Ablauf der Rückmeldefrist sichtbar bleiben kann.

> [!NOTE]
> Eine Alarmierung kann ohne Adresse oder Koordinaten eintreffen, beispielsweise bei einem Einsatzabbruch. In diesem Fall steht dem Device Tracker keine Kartenposition zur Verfügung.

## Dashboard-Vorlage

Im Repository liegt unter [`dashboard_templates/wall_display_card.yaml`](dashboard_templates/wall_display_card.yaml) eine vollständige Lovelace-Vorlage mit:

- Alarmzeit, Einsatznummer und Einsatzmeldung
- positiver, negativer und offener Rückmeldungsanzahl
- Rückmeldefrist und Countdown
- persönlichen Rückmeldebuttons
- Einsatzort und Karte

### Verwendung

1. Die Custom Card [`button-card`](https://github.com/custom-cards/button-card) über HACS installieren.
2. Den vollständigen Inhalt der Vorlagendatei in eine manuelle Lovelace-Karte kopieren.
3. Jedes Vorkommen von `__GA_PREFIX__` durch den Präfix der gewünschten Organisation ersetzen.

Beispiel:

```text
__GA_PREFIX__
```

wird zu:

```text
groupalarm_ha_connect_lgw_lg_luchem
```

Für jede Organisationseinheit kann dieselbe Vorlage mit einem anderen Präfix verwendet werden.

## Wichtige Hinweise zu bestehenden Installationen

### Domain-Änderung seit Version 0.3.0

Die Integrations-Domain wurde von `groupalarm` auf `groupalarm_ha_connect` geändert. Wer noch eine ältere Testversion mit der früheren Domain verwendet, muss diese entfernen und die aktuelle Integration neu einrichten.

### Entity-IDs seit Version 0.3.5

Home Assistant erlaubt in Entity-IDs keine Bindestriche. Die Integration verwendet daher den Präfix `groupalarm_ha_connect`.

Seit Version 0.3.5 lautet der Gerätename `GroupAlarm HA Connect <Organisation>`. Bereits registrierte Entity-IDs benennt Home Assistant bei einem Update nicht automatisch um. Eine Neueinrichtung erzeugt die aktuellen Namen; alternativ können bestehende Entity-IDs in Home Assistant manuell angepasst werden. Prüfe danach alle Dashboards und Automationen, die diese IDs verwenden.

## Fehler melden und Funktionen vorschlagen

Bekannte Aufgaben und geplante Erweiterungen werden in den [GitHub Issues](https://github.com/hojac/GroupAlarm_HA_Connect/issues) gepflegt. Bitte prüfe vor einem neuen Eintrag, ob das Thema bereits vorhanden ist.

Ein hilfreicher Fehlerbericht enthält:

- installierte Integrations- und Home-Assistant-Version
- betroffene Organisationseinheit und Entität
- erwartetes und tatsächliches Verhalten
- relevante Protokollmeldung
- reproduzierbare Schritte
- anonymisierte API- oder Diagnosedaten, sofern sie für den Fehler erforderlich sind

> [!WARNING]
> Personal Access Tokens sowie personenbezogene Alarm-, Standort- und Rückmeldedaten niemals öffentlich in ein Issue einstellen.

## Entwicklung und Releases

### Repository-Struktur

```text
custom_components/groupalarm_ha_connect/  Integration
dashboard_templates/                     Lovelace-Vorlagen
tests/                                   Regressionstests
CHANGELOG.md                             vollständige Versionshistorie
RELEASE_NOTES_vX.Y.Z.md                  Hinweise zu einem einzelnen Release
```

### Änderungen lokal prüfen

Die vorhandenen Regressionstests verwenden Pythons eingebaute Testbibliothek:

```bash
python -m unittest discover -s tests -v
```

Zusätzlich können alle Python-Dateien auf Syntaxfehler geprüft werden:

```bash
python -m compileall -q custom_components/groupalarm_ha_connect tests
```

### Empfohlener Release-Ablauf

1. Umfang über ein oder mehrere Issues festlegen.
2. Änderung und Regressionstests umsetzen.
3. Tests und Syntaxprüfung ausführen.
4. Versionsnummer in `manifest.json` erhöhen.
5. `CHANGELOG.md` ergänzen – neueste Version immer zuerst.
6. Release Notes für die Version erstellen.
7. Änderungen committen und in Home Assistant testen.
8. Tag `vX.Y.Z` aus dem getesteten Commit erstellen.
9. GitHub-Release aus demselben Tag veröffentlichen.
10. Erledigte Issues mit Verweis auf das Release schließen.

Die README beschreibt den dauerhaft gültigen Stand des Projekts. Detaillierte Änderungen einzelner Versionen gehören in das Changelog und in die GitHub-Releases; so bleibt der Einstieg übersichtlich, während die neuesten Änderungen trotzdem schnell auffindbar sind.

## Lizenz

Dieses Projekt steht unter der [MIT-Lizenz](LICENSE).
