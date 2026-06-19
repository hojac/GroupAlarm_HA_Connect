# GroupAlarm HA Connect

> Ab Version 0.3.5 können mehrere Instanzen mit unterschiedlichen Organisationsauswahlen parallel eingerichtet werden.

Home Assistant Integration für GroupAlarm mit Unterstützung für Alarmierungen, Rückmeldungen, Einsatzorte und Alarmmonitor-Dashboards.

> **Hinweis zu Version 0.3.0:**  
> Die Integrations-Domain wurde von `groupalarm` auf `groupalarm_ha_connect` geändert. Dadurch ist diese Version eine neue Integration für Home Assistant. Entferne bei Bedarf die alte Testintegration und richte diese Version neu ein.


## Hinweis zu Entity-IDs ab 0.3.5

Home Assistant Entity-IDs dürfen keine Bindestriche enthalten. Daher verwendet die Integration den Präfix `groupalarm_ha_connect` statt `groupalarm-ha-connect`.

Ab Version 0.3.5 wird der Gerätename auf **GroupAlarm HA Connect <Organisation>** gesetzt. Bei einer Neueinrichtung entstehen dadurch Entity-IDs wie:

```text
sensor.groupalarm_ha_connect_lgw_fuhrung_einsatzmeldung
binary_sensor.groupalarm_ha_connect_lgw_fuhrung_aktive_alarmierung
button.groupalarm_ha_connect_lgw_fuhrung_komme
```

Bei bestehenden Installationen benennt Home Assistant bereits registrierte Entitäten nicht automatisch um. Entferne die alte Integration und richte sie neu ein, wenn du die neuen Entity-IDs automatisch erzeugen lassen möchtest.

## Features

- Anmeldung über Personal Access Token (PAT)
- Automatische Erkennung verfügbarer Organisationen
- Unterstützung mehrerer Organisationen
- Aktive Alarmierung als Binary Sensor
- Alarmnummer, Alarmtext und Einsatzort als Sensoren
- Rückmeldungen direkt aus Home Assistant
  - Komme
  - Komme nicht
- Anzeige der eigenen Rückmeldung
- Rückmeldungsstatistik (positiv, negativ, offen)
- Geokoordinaten des Einsatzortes
- Device Tracker für Kartenansicht
- Countdown bis zum Ende der Rückmeldefrist
- Home Assistant Config Flow
- HACS-kompatible Struktur

## Installation über HACS

### Benutzerdefiniertes Repository hinzufügen

1. HACS öffnen
2. Integrationen auswählen
3. Menü (⋮) → Benutzerdefinierte Repositorys
4. Repository hinzufügen:

```text
https://github.com/hojac/GroupAlarm_HA_Connect
```

Typ:

```text
Integration
```

5. Repository hinzufügen
6. GroupAlarm HA Connect installieren
7. Home Assistant neu starten

## Manuelle Installation

1. Den Ordner

```text
custom_components/groupalarm_ha_connect
```

nach Home Assistant kopieren:

```text
/config/custom_components/groupalarm_ha_connect
```

2. Home Assistant neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → **GroupAlarm HA Connect**

## Einrichtung

1. Einstellungen → Geräte & Dienste
2. Integration hinzufügen
3. **GroupAlarm HA Connect** auswählen
4. Personal Access Token eingeben
5. Gewünschte Organisation(en) auswählen

## Entitäten

Die Entity-IDs enthalten den Namen der ausgewählten Organisation. Bei mehreren Organisationen werden die Entitäten je Organisation angelegt.

Beispiel:

```text
sensor.groupalarm_ha_connect_lgw_fuhrung_einsatzmeldung
binary_sensor.groupalarm_ha_connect_lgw_fuhrung_aktive_alarmierung
button.groupalarm_ha_connect_lgw_fuhrung_komme
```

### Sensoren

| Entität | Beschreibung |
|---|---|
| Einsatzmeldung | Alarmtext |
| Einsatznummer | Alarmnummer / Einsatzstichwort |
| Einsatzort | Alarmadresse |
| Alarmierung Start | Zeitpunkt der Alarmierung |
| Rückmeldefrist Ende | Ende der Alarmierung/Rückmeldefrist |
| Rückmeldefrist Countdown | Verbleibende Zeit bis zum Ende der Rückmeldefrist |
| Meine Rückmeldung | Eigene Rückmeldung |
| Rückmeldungen Positiv | Anzahl positiver Rückmeldungen der Einheit |
| Rückmeldungen Negativ | Anzahl negativer Rückmeldungen der Einheit |
| Rückmeldungen Offen | Anzahl offener Rückmeldungen der Einheit |
| Latitude | Breitengrad |
| Longitude | Längengrad |
| User ID | Eigene GroupAlarm User-ID |

### Binary Sensoren

| Entität | Beschreibung |
|---|---|
| Aktive Alarmierung | Rückmeldung ist noch möglich |

### Buttons

| Entität | Beschreibung |
|---|---|
| Komme | Positive Rückmeldung |
| Komme nicht | Negative Rückmeldung |

Die Buttons sind nur verfügbar, solange die Alarmierung aktiv ist. Die eigene Rückmeldung wird erst nach erfolgreicher Serverbestätigung aktualisiert.

### Device Tracker

| Entität | Beschreibung |
|---|---|
| Einsatzort | Darstellung des Einsatzortes auf Karten |

## Beispiel Dashboard

Voraussetzung: Die Custom Card `button-card` ist installiert.

Passe die Entity-IDs an deine Organisation an. Das folgende Beispiel verwendet `lgw_fuhrung` als Organisations-Slug.

```yaml
type: vertical-stack
cards:
  - type: custom:button-card
    entity: binary_sensor.groupalarm_ha_connect_lgw_fuhrung_aktive_alarmierung
    icon: mdi:alarm-light
    show_icon: true
    show_name: true
    show_label: true
    name: >
      [[[ return states['sensor.groupalarm_ha_connect_lgw_fuhrung_einsatznummer']?.state || 'Kein Alarm'; ]]]
    label: >
      [[[ return states['sensor.groupalarm_ha_connect_lgw_fuhrung_einsatzmeldung']?.state || ''; ]]]
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
        - text-align: center
      label:
        - font-size: 22px
        - white-space: normal
        - text-align: center

  - type: custom:button-card
    entity: sensor.groupalarm_ha_connect_lgw_fuhrung_ruckmeldefrist_countdown
    name: Rückmeldefrist
    show_icon: true
    icon: mdi:timer-outline
    show_state: true

  - type: horizontal-stack
    cards:
      - type: custom:button-card
        entity: sensor.groupalarm_ha_connect_lgw_fuhrung_meine_ruckmeldung
        name: Komme
        icon: mdi:check-circle
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.groupalarm_ha_connect_lgw_fuhrung_komme
        state:
          - value: komme
            styles:
              card:
                - background-color: "#2e7d32"
              icon:
                - color: white
              name:
                - color: white
        styles:
          card:
            - height: 120px
            - border-radius: 15px
          icon:
            - width: 42px
          name:
            - font-size: 20px
            - font-weight: bold

      - type: custom:button-card
        entity: sensor.groupalarm_ha_connect_lgw_fuhrung_meine_ruckmeldung
        name: Komme nicht
        icon: mdi:close-circle
        tap_action:
          action: call-service
          service: button.press
          target:
            entity_id: button.groupalarm_ha_connect_lgw_fuhrung_komme_nicht
        state:
          - value: komme_nicht
            styles:
              card:
                - background-color: "#b71c1c"
              icon:
                - color: white
              name:
                - color: white
        styles:
          card:
            - height: 120px
            - border-radius: 15px
          icon:
            - width: 42px
          name:
            - font-size: 20px
            - font-weight: bold

  - type: custom:button-card
    entity: sensor.groupalarm_ha_connect_lgw_fuhrung_einsatzort
    show_icon: false
    name: >
      [[[ return states['sensor.groupalarm_ha_connect_lgw_fuhrung_einsatzort']?.state || 'Kein Einsatzort'; ]]]
    styles:
      card:
        - padding: 18px
        - border-radius: 15px
      name:
        - font-size: 22px
        - white-space: normal
        - text-align: center

  - type: map
    entities:
      - entity: device_tracker.groupalarm_ha_connect_lgw_fuhrung_einsatzort
        name: Einsatzort
    hours_to_show: 1
    default_zoom: 17
    aspect_ratio: "1:1"
```

## Rückmeldungen

Rückmeldungen werden über die GroupAlarm API gesendet:

```text
POST /api/v1/messaging/feedback
```

Die Buttons werden erst farblich hervorgehoben, nachdem der GroupAlarm Server die Rückmeldung erfolgreich bestätigt hat. Nach Ablauf der Rückmeldefrist bleiben bereits abgegebene Rückmeldungen sichtbar.


## Icon / Logo

This release includes custom `icon.png` and `logo.png` assets for use by Home Assistant and HACS.

## Projektstatus

Aktuelle Version:

```text
0.3.0
```

Die Integration befindet sich in aktiver Entwicklung.

## Haftungsausschluss

Dieses Projekt ist ein unabhängiges Open-Source-Projekt und steht in keiner offiziellen Verbindung zur GroupAlarm GmbH.


## Aktuelle Version

Aktuelle Version: `0.3.5`


## Branding

This release includes `icon.png` and `logo.png` for HACS and Home Assistant display.
