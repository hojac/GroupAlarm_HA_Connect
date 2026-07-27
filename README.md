# GroupAlarm HA Connect

Inoffizielle Home-Assistant-Custom-Integration für
[GroupAlarm](https://www.groupalarm.com/). Sie liest Alarmierungen ausgewählter
Organisationen ein und stellt normalisierte Alarm- und Rückmeldedaten als
Home-Assistant-Entitäten bereit.

> [!IMPORTANT]
> Dieses Projekt steht in keiner offiziellen Verbindung zur GroupAlarm GmbH.
> Version `0.5.0` ist ein vollständiger Neubau. Rückmeldefrist, Alarmaktivität,
> Button-Freigabe und Einsatzort bleiben absichtlich unbekannt beziehungsweise
> nicht verfügbar, solange ihre realen JSON-Pfade nicht durch anonymisierte
> aktuelle Payloads belegt sind.

## Funktionsumfang

- vollständig asynchroner GroupAlarm-Client
- Einrichtung, Reauthentifizierung und Neukonfiguration über die Oberfläche
- mehrere Organisationen pro Config Entry und mehrere überschneidungsfreie
  Config Entries pro GroupAlarm-Benutzer
- ein gemeinsamer, trafficarmer Coordinator pro Config Entry
- isolierte Fehlerbehandlung je Organisation
- zehn lesende Sensoren, ein Aktivitäts-Binary-Sensor, zwei
  Rückmelde-Buttons und ein Standort-Tracker je Organisation
- serverbestätigte persönliche Rückmeldung ohne optimistische Zustandsänderung
- optionale Anfahrtszeit für positive Rückmeldungen
- Schutz gegen Doppelklicks und unklare doppelte POST-Anfragen
- pseudonymisierte Home-Assistant-Diagnostics und ein Repair-Hinweis für eine
  ungültige gespeicherte Geräte-ID
- deutsche und englische UI-Texte

## Voraussetzungen

- Home Assistant `2026.6.0` oder neuer
- ein GroupAlarm-Konto mit Zugriff auf mindestens eine Organisation
- ein persönlicher GroupAlarm Personal Access Token (PAT)
- optional HACS für Installation und Updates

### Personal Access Token erstellen

Folge ausschließlich der offiziellen GroupAlarm-Anleitung
[Profil – Sicherheit](https://docs.groupalarm.com/de/article/profil-sicherheit-15o21cd/).
Erstelle dort einen Personal-Access-Token, keinen Organisations-API-Token.

Behandle den PAT wie ein Passwort. Stelle ihn niemals in Issues, Screenshots,
Diagnosedateien oder Automationen ein.

## Installation

### HACS

1. Öffne HACS und wähle **Integrationen**.
2. Füge über **Benutzerdefinierte Repositorys** dieses Repository als
   **Integration** hinzu:

   ```text
   https://github.com/hojac/GroupAlarm_HA_Connect
   ```

3. Installiere **GroupAlarm HA Connect**.
4. Starte Home Assistant neu.

### Manuell

1. Lade das gewünschte Release herunter.
2. Kopiere den Ordner `custom_components/groupalarm_ha_connect` nach
   `/config/custom_components/groupalarm_ha_connect`.
3. Starte Home Assistant neu.

Die Zieldatei muss anschließend unter
`/config/custom_components/groupalarm_ha_connect/manifest.json` liegen.

## Einrichtung und Änderungen

1. Öffne **Einstellungen → Geräte & Dienste**.
2. Wähle **Integration hinzufügen** und suche nach
   **GroupAlarm HA Connect**.
3. Gib den PAT und ein Abfrageintervall von 30 bis 900 Sekunden ein.
4. Wähle mindestens eine Organisation.

**Neu konfigurieren** prüft einen PAT erneut und ändert die
Organisationsauswahl. Über **Optionen** lassen sich Organisationsauswahl,
Abfrageintervall und je Organisation eine Anfahrtszeit von 1 bis 180 Minuten
setzen. Sobald mindestens eine Anfahrtszeit konfiguriert ist, muss ein aktives
GroupAlarm-App-Gerät ausgewählt werden. Gespeichert wird nur dessen numerische
ID; Push-Tokens werden nie in das Domainmodell übernommen.

Lehnt GroupAlarm den PAT später ab, startet Home Assistant den
Reauthentifizierungsdialog. Der neue PAT muss zum selben GroupAlarm-Konto
gehören.

## Entitäten und Zustände

Home Assistant legt für jede ausgewählte Organisation ein Service-Gerät an.
Fachliche Unique IDs enthalten Benutzer-, Organisations- und
Entitätsschlüssel, aber weder Token noch Namen. Eine Umbenennung der
Organisation ändert diese Identitäten daher nicht.

Die sichtbare Entity-ID hängt von Sprache, Organisationstitel und vorhandenen
Registry-Einträgen ab. Verwende in Dashboards immer die Entity-IDs deiner
Installation.

### Sensoren

| Entität | Wert |
|---|---|
| Alarm ID | technische ID des sichtbaren Alarms |
| Einsatzmeldung | Alarmtext |
| Alarmierung Start | UTC-basierter Home-Assistant-Timestamp |
| Alarmzeitpunkt | lokal formatierter Kompatibilitätswert |
| Einsatznummer | belegter Name des zugehörigen Events |
| Rückmeldungen positiv | bestätigte aggregierte Anzahl |
| Rückmeldungen negativ | bestätigte aggregierte Anzahl |
| Rückmeldungen offen | aggregierte unbekannte/offene Anzahl |
| Meine Rückmeldung | `no_alarm`, `unknown`, `komme` oder `komme_nicht` |
| Benutzer-ID | standardmäßig deaktivierte Diagnoseentität |

### Weitere Plattformen

| Typ | Entität | Verhalten |
|---|---|---|
| Binary Sensor | Aktive Alarmierung | `unknown`, bis offene/geschlossene Real-Payloads die Statuszuordnung belegen |
| Button | Komme | verfügbar nur bei belegter offener Rückmeldung und unbekannter eigener Antwort |
| Button | Komme nicht | gleiche Sicherheitsbedingung wie `Komme` |
| Device Tracker | Einsatzort | unavailable, bis belegte und gültige Koordinaten vorliegen |

Ein Alarm kann sichtbar bleiben, obwohl Aktivität, Rückmeldungszulässigkeit
oder Frist unbekannt sind. Diese Achsen werden bewusst nicht voneinander
abgeleitet.

## Datenaktualisierung und Traffic

Das konfigurierte Intervall gilt für eine kleine Listenabfrage je Organisation.
Der Coordinator lädt ein begrenztes Fenster von zehn Alarmreferenzen und wählt
darin deterministisch nach validiertem Startzeitpunkt und Alarm-ID.

Der vollständige Alarmdatensatz wird nur geladen:

- bei einer neuen Alarm-ID,
- bei einem geänderten dokumentierten Listen-Fingerprint,
- nach einer Rückmeldeaktion beziehungsweise für einen ungeklärten Pending-Fall,
- oder als Sicherheitsabgleich nach 15 Minuten.

Benutzer und Organisationen werden nur beim Setup beziehungsweise Reload
geladen. Der Organisations-Timeout wird noch nicht abgefragt, weil ohne
belegten Referenzzeitpunkt keine sichere Deadline daraus berechnet werden kann.

Die API dokumentiert keine Sortierreihenfolge der Alarmliste. Liegen mehr als
zehn Alarme vor, ist deshalb formal nicht garantiert, dass das erste Fenster
den global neuesten Alarm enthält.

## Persönliche Rückmeldung

Der vollständige Versandpfad ist fail-safe implementiert. Die produktiven
Buttons bleiben momentan unavailable, weil noch keine anonymisierte reale
Payload das Feld für „Rückmeldung offen“ belegt.

Sobald diese Zuordnung belegt ist, gilt:

1. Ein nicht wartendes Lock verhindert parallele Rückmeldungen für denselben
   Alarm.
2. Ohne Anfahrtszeit oder bei negativer Antwort wird
   `/messaging/feedback` verwendet.
3. Eine positive Antwort mit Anfahrtszeit nutzt `/app/feedback`.
4. Home Assistant ändert den persönlichen Status erst nach einem bestätigenden
   Detail-GET.
5. Der Abgleich erfolgt höchstens dreimal: sofort, nach einer und nach weiteren
   zwei Sekunden.
6. Timeout, Verbindungsabbruch oder `5xx` führen nie zu einem blinden zweiten
   POST.
7. Nur eine eindeutige Ablehnung des App-Endpunkts darf einmalig auf die
   Standardrückmeldung ohne Zeit ausweichen.

Ein ungeklärter Schreibvorgang bleibt pending. Die Buttons bleiben gesperrt,
und der normale Pollingzyklus lädt bis zur Bestätigung gezielt das Detail nach.

## Rückmeldefrist und Countdown

Noch kein dokumentiertes oder reales Feld ist als persönliche
Rückmeldefrist belegt:

- `alarm.endDate` ist laut API der Zeitpunkt, zu dem der Alarm geschlossen
  wurde.
- `event.endDate` ist das Eventende.
- `event.scheduledEndtime` ist das geplante Eventende.
- die konfigurierte Anfahrtszeit ist keine Rückmeldefrist.

Version `0.5.0` erzeugt deshalb noch keine Deadline- oder Countdown-Entitäten.
Der Zustand bleibt fachlich `unknown`; es wird kein lokaler Timer gestartet.
Die endgültige Zuordnung folgt erst nach anonymisierten Listen-, Detail-,
Timeout- und Feedback-Payloads desselben realen Alarms.

## Mehrere Organisationen und Config Entries

Ein Config Entry darf mehrere Organisationen enthalten. Bis zu vier
Organisationsabfragen laufen parallel; ein Fehler einer Organisation macht die
anderen nicht unavailable.

Mehrere Config Entries desselben Benutzers sind möglich, solange sich ihre
Organisationsmengen nicht überschneiden. Das verhindert doppelte Abfragen und
doppelte Rückmelde-Entitäten für dieselbe fachliche Organisation.

## Datenschutz, Diagnostics und Repairs

Diagnostics enthalten ausschließlich:

- Integrations- und Config-Entry-Version
- Abfrageintervall und Organisationsanzahl
- pseudonymisierte Benutzer-, Organisations-, Alarm- und Event-IDs
- letzten erfolgreichen Update-Zeitpunkt
- Fehlerklasse und normalisierte Zustandsflags je Organisation
- erkannte Feldpfade ohne deren Inhalte

Nicht enthalten sind PAT, Push-Token, Namen, E-Mail-Adressen, Telefonnummern,
Alarmtexte, Kommentare, Adressen, Koordinaten oder rohe API-Payloads.

Wenn Anfahrtszeiten gespeichert sind, aber keine gültige Geräte-ID vorhanden
ist, erzeugt Home Assistant einen Repair-Hinweis. Öffne die Integrationsoptionen
und wähle ein aktives App-Gerät oder entferne alle Anfahrtszeiten.

## Dashboard

[`dashboard_templates/wall_display_card.yaml`](dashboard_templates/wall_display_card.yaml)
enthält eine optionale Wall-Display-Vorlage. Sie benötigt
[`custom:button-card`](https://github.com/custom-cards/button-card); die
Integration selbst benötigt keine Custom Card.

Die Vorlage zeigt unbekannte Frist- und Aktivitätszustände neutral und färbt
eine Rückmeldung erst, wenn der Sensor `Meine Rückmeldung` den vom Server
bestätigten Wert enthält. Vor Verwendung müssen alle Beispiel-Entity-IDs durch
die IDs der eigenen Installation ersetzt werden.

## Fehlerbehebung

### Integration lässt sich nicht einrichten

- Prüfe den PAT anhand der offiziellen GroupAlarm-Anleitung.
- Prüfe, ob das Konto Zugriff auf mindestens eine Organisation besitzt.
- Bei temporären Netzwerk- oder Serverfehlern versucht Home Assistant das Setup
  später erneut.

### Eine Organisation ist unavailable

Andere Organisationen bleiben weiter aktiv. Prüfe das Home-Assistant-Protokoll
auf die einmalig geloggte Fehlerklasse. Nach Wiederherstellung wird ebenfalls
genau ein Übergang protokolliert.

### Rückmelde-Buttons sind unavailable

Das ist im aktuellen evidenzbasierten Mapper beabsichtigt. Alte sichtbare
Alarme dürfen nicht versehentlich eine Rückmeldung ermöglichen. Für die
Freigabe wird eine anonymisierte offene Alarm-Payload benötigt.

### Standort oder Countdown fehlt

Beide Zuordnungen sind bis zu realen anonymisierten Payloads blockiert. Es wird
keine Ersatzposition und keine ähnlich benannte Zeit als Deadline verwendet.

### Integration entfernen

Entferne zuerst alle zugehörigen Config Entries unter
**Einstellungen → Geräte & Dienste**. Lösche anschließend bei manueller
Installation den Ordner
`/config/custom_components/groupalarm_ha_connect` und starte Home Assistant
neu. Bei HACS verwende danach **Entfernen** im HACS-Eintrag.

## Entwicklung

Die Abhängigkeiten sind in `uv.lock` festgeschrieben:

```bash
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/groupalarm_ha_connect
uv run pytest \
  --cov=custom_components/groupalarm_ha_connect \
  --cov-report=term-missing \
  --cov-fail-under=95
uv run python scripts/check_repository.py
```

Reale JSON-Payloads müssen vor Aufnahme als Fixture mit
`scripts/anonymize_fixture.py` verarbeitet und anschließend manuell geprüft
werden. Die CI kontrolliert zusätzlich Cache-Dateien, bekannte
Credential-Muster und den Anonymisierungsmarker aller JSON-Fixtures.

Release Notes, Git-Tag `v0.5.0` und GitHub-Release entstehen erst nach
Realtest, Upgrade-/Migrationstest und ausdrücklicher Freigabe.

## Lizenz

[MIT](LICENSE)
