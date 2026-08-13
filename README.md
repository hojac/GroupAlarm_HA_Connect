# GroupAlarm HA Connect

Inoffizielle Home-Assistant-Custom-Integration für
[GroupAlarm](https://www.groupalarm.com/). Sie liest Alarmierungen ausgewählter
Organisationen ein und stellt normalisierte Alarm- und Rückmeldedaten als
Home-Assistant-Entitäten bereit.

> [!IMPORTANT]
> Dieses Projekt steht in keiner offiziellen Verbindung zur GroupAlarm GmbH.
> Version `0.5.3` basiert auf dem vollständigen asynchronen Neubau. Die
> Rückmeldefrist ist eine bewusst lokale Frist, die nur für einen offenen
> persönlichen `WAITING`-Zustand angelegt wird.

## Funktionsumfang

- vollständig asynchroner GroupAlarm-Client
- Einrichtung, Reauthentifizierung und Neukonfiguration über die Oberfläche
- mehrere Organisationen pro Config Entry und mehrere überschneidungsfreie
  Config Entries pro GroupAlarm-Benutzer
- ein gemeinsamer, trafficarmer Coordinator pro Config Entry
- isolierte Fehlerbehandlung je Organisation
- dreizehn lesende Sensoren, ein Aktivitäts-Binary-Sensor, zwei
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

### Upgrade von v0.3.x

Beim ersten Start nach dem Upgrade übernimmt die Integration vorhandene
Registry-Einträge für `Rückmeldefrist Ende` und `Rückmeldefrist Countdown` in
das v0.5-Schema. Die bisherigen Entity-IDs, benutzerdefinierten Namen, Symbole
und Historien bleiben dabei erhalten; es entstehen keine zusätzlichen
Entity-IDs mit dem Suffix `_2`.

Installationen, in denen v0.5.1 oder v0.5.2 bereits aktive Fristentitäten mit
dem Suffix `_2` angelegt haben, werden beim ersten Start von v0.5.3 automatisch
zusammengeführt. Die aktive v0.5-Entität übernimmt die bisherige Entity-ID ohne
`_2`; benutzerdefinierte Namen, Symbole, Deaktivierung und weitere relevante
Registry-Einstellungen bleiben erhalten.

Die nicht mehr bereitgestellten Einzelsensoren `Einsatzort`, `Latitude` und
`Longitude` werden aus der Entity Registry entfernt. Der Standort wird ab v0.5
über den Device Tracker `Einsatzort` bereitgestellt. Vor dem Upgrade müssen
keine Entitäten manuell gelöscht werden.

Wer noch v0.5.2 nutzt, kann ein Dashboard vorübergehend auf die tatsächlich
aktive `_2`-Countdown-Entität umstellen. Nach dem Upgrade auf v0.5.3 muss das
Dashboard wieder die kanonische Entity-ID ohne `_2` verwenden.

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
| Rückmeldefrist Ende | lokale Erkennungszeit plus Organisations-Timeout |
| Rückmeldefrist Countdown | lokal berechnete Restsekunden; nach Ablauf `0` |
| Rückmeldefrist Status | `no_alarm`, `known_active`, `known_expired`, `answered` oder `unknown` |
| Einsatznummer | belegter Name des zugehörigen Events |
| Rückmeldungen positiv | bestätigte aggregierte Anzahl |
| Rückmeldungen negativ | bestätigte aggregierte Anzahl |
| Rückmeldungen offen | aggregierte unbekannte/offene Anzahl |
| Meine Rückmeldung | `no_alarm`, `unknown`, `komme` oder `komme_nicht` |
| Benutzer-ID | standardmäßig deaktivierte Diagnoseentität |

### Weitere Plattformen

| Typ | Entität | Verhalten |
|---|---|---|
| Binary Sensor | Aktive Alarmierung | `on`, solange `alarm.endDate` fehlt und kein `event.abort` vorliegt; danach `off` |
| Button | Komme | verfügbar nur bei `WAITING`, unbekannter eigener Antwort und Countdown größer `0` |
| Button | Komme nicht | gleiche Sicherheitsbedingung wie `Komme` |
| Device Tracker | Einsatzort | GPS-Position aus gültigen WGS84-Koordinaten; eine vorhandene Adresse wird als Ortsname verwendet |

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
geladen. Bei einer neuen Alarm-ID wird zuerst das Alarmdetail normalisiert.
Nur wenn es eine offene persönliche Rückmeldung mit `WAITING` belegt, wird der
Organisations-Timeout einmal geladen und die lokale Frist erzeugt.

Die API dokumentiert keine Sortierreihenfolge der Alarmliste. Liegen mehr als
zehn Alarme vor, ist deshalb formal nicht garantiert, dass das erste Fenster
den global neuesten Alarm enthält.

## Persönliche Rückmeldung

Der vollständige Versandpfad ist fail-safe implementiert. Die produktiven
Buttons sind nur bei einem passenden `WAITING`-Eintrag und während einer
laufenden lokalen Rückmeldefrist verfügbar.

Dabei gilt:

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

GroupAlarm liefert über
`GET /api/v1/messaging/timeout/{organizationID}` die Timeout-Dauer in Sekunden,
aber keinen absoluten Beginn der persönlichen Frist. Deshalb verwendet die
Integration die ausdrücklich festgelegte lokale Semantik:

1. Beim ersten Erkennen einer neuen Alarm-ID wird das Detail geprüft. Nur für
   einen offenen persönlichen `WAITING`-Zustand wird der Timeout einmal geladen.
2. Die lokale Frist ist Erkennungszeit plus Timeout.
3. Der Countdown läuft lokal im Sekundentakt; es entsteht kein API-Aufruf pro
   Sekunde.
4. Bei `0` werden beide Rückmelde-Buttons gesperrt. Dieselbe Fristprüfung läuft
   nochmals unmittelbar vor jedem Feedback-POST.
5. `RESPONDED`, `TIMEDOUT`, `UNAVAILABLE` oder ein geschlossener Alarm sperren
   Rückmeldungen unabhängig vom lokalen Restwert und erhalten keine neue lokale
   Frist.

Diese lokale Frist ist nicht die unbekannte serverseitige Benachrichtigungszeit.
Wird Home Assistant während eines noch auf `WAITING` stehenden Alarms neu
gestartet, beginnt deshalb eine neue lokale Frist. GroupAlarm kann eine
Rückmeldung serverseitig bereits früher ablehnen.

Der Countdown-Sensor schreibt während einer laufenden Frist einmal pro Sekunde
einen Zustand. Wer diese Historie nicht benötigt, sollte ihn vom Recorder
ausschließen:

```yaml
recorder:
  exclude:
    entities:
      - sensor.<deine_entity_id_fuer_den_ruckmeldefrist_countdown>
```

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
bestätigten Wert enthält. Ein numerischer aktiver Countdown erscheint wie die
Rückmeldungszähler in 34 Pixeln und in der Home-Assistant-Warnfarbe; nicht
numerische Zustände werden als `Unbekannt` dargestellt. Vor Verwendung müssen
alle Beispiel-Entity-IDs durch die IDs der eigenen Installation ersetzt werden.

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

Prüfe den Sensor `Rückmeldefrist Status`. Die Buttons bleiben gesperrt, wenn
kein passender `WAITING`-Eintrag vorliegt, die Frist `0` erreicht hat, bereits
eine Antwort bestätigt wurde oder der Alarm geschlossen ist.

### Standort fehlt

Der Tracker wird nur bei einem vollständigen, gültigen WGS84-Koordinatenpaar
verfügbar. Prüfe, ob der aktuelle Alarm unter `optionalContent` sowohl
`locationLatitude` als auch `locationLongitude` enthält. Teilwerte, ungültige
Bereiche und andere Koordinatensysteme werden bewusst nicht verwendet; es gibt
keine Ersatzposition.

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

Version `0.5.3` behebt den im realen Upgradepfad verbliebenen `_2`-Konflikt und
härtet die Wall-Display-Vorlage ab. Weitere Feld- und Upgrade-Tests werden mit
anonymisierten Referenzfällen fortgesetzt.

## Lizenz

[MIT](LICENSE)
