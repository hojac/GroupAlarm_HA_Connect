# GroupAlarm HA Connect v0.3.10

Dieses Release bündelt die Issues #1, #10, #16 und #17.

## Neuerungen

- Das Integrationssymbol liegt im von aktuellen Home-Assistant-Versionen erwarteten lokalen `brand`-Ordner.
- Der Countdown verursacht nur noch während einer bekannten laufenden Rückmeldefrist sekündliche Zustandsaktualisierungen.
- Der Geräte-Tracker verwendet den aktuellen `TrackerEntity`-Import und ist damit auf die Entfernung des alten Alias in Home Assistant 2027.6 vorbereitet.
- Je Organisationseinheit kann optional eine Standard-Anfahrtszeit von 1 bis 180 Minuten konfiguriert werden.
- Sobald mindestens eine Zeit gesetzt ist, wird ein vorhandenes aktives GroupAlarm-Gerät ausgewählt. Gespeichert wird ausschließlich dessen Geräte-ID.
- Positive Rückmeldungen mit Zeit verwenden `POST /api/v1/app/feedback` und `answerData.duration`.
- Negative Rückmeldungen und positive Rückmeldungen ohne Zeit verwenden weiterhin `POST /api/v1/messaging/feedback`.
- Scheitert die Zeitübermittlung, sendet die Integration die Rückmeldung automatisch ohne Zeit und zeigt eine Home-Assistant-Warnung an.

## Aktualisierung

1. Version `0.3.10` über HACS installieren.
2. Home Assistant vollständig neu starten.
3. Die Integration über **Einstellungen → Geräte & Dienste → GroupAlarm HA Connect → Konfigurieren** öffnen.
4. Gewünschte Standard-Anfahrtszeiten setzen. Erst dann ist zusätzlich ein aktives GroupAlarm-Gerät auszuwählen.

Bestehende Konfigurationen funktionieren ohne gesetzte Anfahrtszeiten unverändert weiter.
