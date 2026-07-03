# GroupAlarm HA Connect v0.3.8

## Fixed

- Behebt die Erkennung von `Aktive Alarmierung`: Ein laufender Alarm bleibt sichtbar, auch wenn keine Rückmeldefrist vorhanden ist oder die Rückmeldefrist bereits abgelaufen ist.
- `scheduledEndtime`/Rückmeldefrist wird nicht mehr als Kriterium verwendet, um einen Alarm auszublenden.
- `Meine Rückmeldung` wird nur noch aus der Rückmeldung des konfigurierten Benutzers ermittelt. Rückmeldungen anderer Personen färben die eigenen Buttons nicht mehr ein.
- Neue Einsätze starten neutral mit `offen`, solange keine eigene Rückmeldung vom GroupAlarm-Server bestätigt wurde.
- Rückmeldefrist-/Countdown-Sensoren bleiben als Anzeige erhalten, steuern aber nicht mehr die Alarm-Sichtbarkeit.

## Changed

- Version auf `0.3.8` angehoben.
- Robusteres Handling optionaler GroupAlarm-Felder für Rückmeldung und Alarm-Ende.

## Upload-Hinweis

1. ZIP lokal entpacken.
2. Inhalt in das GitHub-Repository `GroupAlarm_HA_Connect` kopieren.
3. Änderungen committen, z. B. `Fix active alarm and personal feedback state`.
4. Tag `v0.3.8` erstellen.
5. GitHub Release `v0.3.8` mit diesen Release Notes veröffentlichen.
