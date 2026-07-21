# GroupAlarm HA Connect v0.3.9

## Behoben

- Die persönliche Rückmeldung wird nur noch dann als `komme` oder `komme_nicht` angezeigt, wenn GroupAlarm den eigenen Feedback-Eintrag mit `state: RESPONDED` bestätigt.
- `UNAVAILABLE`, `TIMEDOUT`, fehlende oder nicht eindeutig zuordenbare Rückmeldungen erscheinen als `unbekannt`; beide Dashboard-Buttons bleiben damit neutral.
- Ein erfolgreicher Sendevorgang färbt keinen Button mehr lokal ein. Maßgeblich ist ausschließlich die anschließend per `GET /alarm/{alarmID}?update_for_user=true` gelesene Serverantwort. Dadurch werden auch Rückmeldungen aus App, Weboberfläche oder anderen Kanälen korrekt dargestellt.
- Beim Wechsel auf eine neue Alarm-ID wird kein persönlicher Rückmeldestatus des vorherigen Alarms übernommen.
- `alarm.endDate` wird nun als Ende der Rückmeldefrist ausgewertet. Dadurch funktionieren die Sensoren `Rückmeldefrist Ende`, `Rückmeldefrist Countdown` und `Rückmeldefrist Status` mit den tatsächlichen GroupAlarm-Daten.
- Zeitangaben des gesamten Events werden nicht mehr als Ersatz für die Rückmeldefrist verwendet.

## Testhinweis

Nach der Installation Home Assistant neu starten und die Integration neu laden. Bei einem neuen Alarm müssen beide Rückmeldebuttons zunächst neutral bleiben. Nach einer Rückmeldung darf sich die Farbe erst ändern, wenn die GroupAlarm-GET-Antwort den eigenen Eintrag mit `state: RESPONDED` enthält.

Closes #2
Closes #3
Closes #5
Closes #9
