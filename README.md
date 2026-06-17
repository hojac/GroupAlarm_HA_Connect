# GroupAlarm HA Connect

Home Assistant Integration für GroupAlarm mit Unterstützung für Alarmierungen, Rückmeldungen, Einsatzorte und Alarmmonitor-Dashboards.

## Features

* Anmeldung über Personal Access Token (PAT)
* Automatische Erkennung verfügbarer Organisationen
* Unterstützung mehrerer Organisationen
* Aktive Alarmierungen als Binary Sensor
* Alarmnummer, Alarmtext und Einsatzort als Sensoren
* Rückmeldungen direkt aus Home Assistant

  * Komme
  * Komme nicht
* Anzeige der eigenen Rückmeldung
* Rückmeldungsstatistik (positiv, negativ, offen)
* Geokoordinaten des Einsatzortes
* Device Tracker für Kartenansicht
* Countdown bis zum Ende der Rückmeldefrist
* Home Assistant Config Flow
* HACS-kompatibel

---

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

---

## Einrichtung

1. Einstellungen → Geräte & Dienste
2. Integration hinzufügen
3. GroupAlarm HA Connect auswählen
4. Personal Access Token eingeben
5. Gewünschte Organisation(en) auswählen

---

## Entitäten

### Sensoren

| Entität                  | Beschreibung                   |
| ------------------------ | ------------------------------ |
| Einsatzmeldung           | Alarmtext                      |
| Einsatznummer            | Alarmnummer / Einsatzstichwort |
| Einsatzort               | Alarmadresse                   |
| Alarmierung Start        | Zeitpunkt der Alarmierung      |
| Rückmeldefrist Ende      | Ende der Alarmierung           |
| Rückmeldefrist Countdown | Verbleibende Zeit              |
| Meine Rückmeldung        | Eigene Rückmeldung             |
| Rückmeldungen Positiv    | Anzahl positiver Rückmeldungen |
| Rückmeldungen Negativ    | Anzahl negativer Rückmeldungen |
| Rückmeldungen Offen      | Anzahl offener Rückmeldungen   |

### Binary Sensoren

| Entität            | Beschreibung             |
| ------------------ | ------------------------ |
| Aktive Alarmierung | Rückmeldung noch möglich |

### Buttons

| Entität     | Beschreibung         |
| ----------- | -------------------- |
| Komme       | Positive Rückmeldung |
| Komme nicht | Negative Rückmeldung |

### Device Tracker

| Entität    | Beschreibung                            |
| ---------- | --------------------------------------- |
| Einsatzort | Darstellung des Einsatzortes auf Karten |

---

## Beispiel Dashboard

```yaml
type: custom:button-card
entity: binary_sensor.groupalarm_ORGA_aktive_alarmierung
show_icon: true
show_name: true
show_label: true

name: >
  [[[ return states['sensor.groupalarm_ORGA_einsatznummer']?.state || 'Kein Alarm'; ]]]

label: >
  [[[ return states['sensor.groupalarm_ORGA_einsatzmeldung']?.state || ''; ]]]
```

---

## Rückmeldungen

Rückmeldungen werden direkt an die GroupAlarm API übertragen.

Die Buttons werden erst farblich hervorgehoben, nachdem die Rückmeldung erfolgreich vom GroupAlarm Server bestätigt wurde.

Nach Ablauf der Rückmeldefrist bleiben bereits abgegebene Rückmeldungen sichtbar.

---

## Unterstützte Funktionen

* Alarmmonitor
* Wanddisplay
* Dashboard-Karten
* Rückmeldungen
* Kartenansicht
* Mehrere Organisationen

---

## Projektstatus

Aktuelle Version:

```text
0.2.3
```

Die Integration befindet sich in aktiver Entwicklung.

---

## Haftungsausschluss

Dieses Projekt ist ein unabhängiges Open-Source-Projekt und steht in keiner offiziellen Verbindung zur GroupAlarm GmbH.
