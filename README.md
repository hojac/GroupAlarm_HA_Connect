# GroupAlarm_HA_Conmect
HACS-fähige Custom Integration für GroupAlarm in Home Assistant.

# GroupAlarm_HA_Conmect

HACS-fähige Custom Integration für GroupAlarm in Home Assistant.

## Funktionen

- UI-Konfiguration über Home Assistant Config Flow
- Personal Access Token
- Organisationen werden automatisch über die GroupAlarm API geladen
- Mehrfachauswahl von Organisationen
- Options Flow für Organisationen und Aktualisierungsintervall
- Abruf des aktuellen Benutzers
- Abruf des letzten Alarms je Organisation
- Sensoren für Einsatzmeldung, Alarmzeit, Einsatzort, Koordinaten und Rückmeldungen
- Binary Sensor `Aktive Alarmierung`
- Buttons `Komme` und `Komme nicht`
- Device Tracker `Einsatzort` für die Kartenansicht
- Entitäten werden pro Organisation als Gerät gruppiert

## Version 0.2.2

- Projektname auf `GroupAlarm_HA_Conmect` gesetzt
- Feedback wird über `POST /api/v1/messaging/feedback` gesendet
- Buttons ändern ihre Rückmelde-Farbe erst nach erfolgreicher Serverbestätigung
- Nach erfolgreicher Rückmeldung wird zusätzlich der vollständige Alarm per `GET /alarm/{alarmID}?update_for_user=true` nachgeladen
- Fallback: bestätigte Server-Rückmeldung bleibt für den aktuellen Alarm erhalten, falls der Listen-Endpunkt die eigene Rückmeldung nicht direkt ausliefert
- Timestamp-Sensoren liefern echte `datetime`-Werte statt Strings

## Installation manuell

1. Ordner `custom_components/groupalarm` nach `/config/custom_components/groupalarm` kopieren.
2. Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → `GroupAlarm HA Conmect`.
4. Personal Access Token eintragen.
5. Organisationen auswählen.

## Installation über HACS als Custom Repository

1. HACS → Integrationen → Drei Punkte → Benutzerdefinierte Repositories.
2. GitHub-Repository-URL eintragen.
3. Kategorie: Integration.
4. Installieren und Home Assistant neu starten.

## Lovelace Alarmblock

Voraussetzung: `custom:button-card` ist installiert.

Die Entity-IDs enthalten den Organisationsnamen. Passe sie daher an deine Entitäten an, z. B. `groupalarm_lgw_fuhrung`.

```yaml
type: vertical-stack
cards:
  - type: custom:button-card
    entity: binary_sensor.groupalarm_lgw_fuhrung_aktive_alarmierung
    icon: mdi:alarm-light
    show_icon: true
    show_name: true
    show_label: true
    name: >
      [[[ return states['sensor.groupalarm_lgw_fuhrung_einsatznummer']?.state || 'Kein Einsatz'; ]]]
    label: >
      [[[ return states['sensor.groupalarm_lgw_fuhrung_einsatzmeldung']?.state || ''; ]]]
    state:
      - value: "on"
        styles:
          card:
            - background-color: "#b71c1c"
          name:
            - color: white
          label:
            - color: white
          icon:
            - color: white
    styles:
      card:
        - padding: 20px
        - border-radius: 15px
      icon:
        - width: 40px
        - height: 40px
      name:
        - font-size: 30px
        - font-weight: bold
      label:
        - font-size: 22px
        - white-space: normal

  - type: horizontal-stack
    cards:
      - type: custom:button-card
        entity: sensor.groupalarm_lgw_fuhrung_meine_ruckmeldung
        name: Komme
        icon: mdi:check-circle
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.groupalarm_lgw_fuhrung_komme
        state:
          - value: komme
            styles:
              card:
                - background-color: "#2e7d32"
              icon:
                - color: white
              name:
                - color: white

      - type: custom:button-card
        entity: sensor.groupalarm_lgw_fuhrung_meine_ruckmeldung
        name: Komme nicht
        icon: mdi:close-circle
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.groupalarm_lgw_fuhrung_komme_nicht
        state:
          - value: komme_nicht
            styles:
              card:
                - background-color: "#b71c1c"
              icon:
                - color: white
              name:
                - color: white

  - type: custom:button-card
    entity: sensor.groupalarm_lgw_fuhrung_einsatzort
    show_icon: false
    name: >
      [[[ return states['sensor.groupalarm_lgw_fuhrung_einsatzort']?.state || 'Kein Einsatzort'; ]]]
    styles:
      card:
        - padding: 16px
        - border-radius: 14px
      name:
        - font-size: 22px
        - white-space: normal

  - type: map
    title: Einsatzort
    entities:
      - entity: device_tracker.groupalarm_lgw_fuhrung_einsatzort
        name: +
    hours_to_show: 1
    default_zoom: 17
```

## Status

Früher Entwicklungsstand. API-Response-Strukturen können je nach GroupAlarm-Alarmierung abweichen.

## Version 0.2.3

- `Aktiver Einsatz` wurde fachlich durch `Aktive Alarmierung` ersetzt.
- `Einsatzende` wurde fachlich durch `Rückmeldefrist Ende` ersetzt.
- Neuer Sensor `Rückmeldefrist Countdown` zählt bis `endDate` herunter.
- Die Feedback-Buttons sind nur verfügbar, solange die Alarmierung aktiv ist.
- Nach Ablauf der Rückmeldefrist bleibt eine bestätigte eigene Rückmeldung weiterhin sichtbar.
- Rückmeldungen werden weiterhin erst nach erfolgreicher Serverbestätigung übernommen.

### Bedeutung der Zeiten

- `startDate` = Start der Alarmierung
- `endDate` = Ende der Rückmeldefrist / Alarmierung geschlossen

`endDate` ist nicht als Einsatzende zu verstehen.
