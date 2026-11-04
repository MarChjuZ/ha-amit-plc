![AMiT](https://raw.githubusercontent.com/MarChjuZ/ha-amit-plc/main/custom_components/amit_plc/brand/icon@2x.png)

# AMiT PLC (WebSocket) for Home Assistant

Home Assistant integration for **AMiT** stations (ADiS, AMiNi, AMR-CP… programmed in DetStudio)
that talks to the station over its built-in **WebSocket / JSON** protocol
(`MESSAGEPACK_WS-JSON_DEC_EN_100`).

* one persistent connection, polling as fast as **100 ms** (configurable, minimum 20 ms),
* everything is configured from the UI – no YAML,
* variables are read from the PLC, you only choose which ones to show and how to name them,
* inputs → `binary_sensor`, numbers → `sensor`, outputs → `switch` (read + write).

## Diegimas per HACS

1. HACS → ⋮ (viršuje dešinėje) → **Custom repositories**.
2. **Repository**: šio GitHub saugyklos adresas, **Type**: `Integration` → **Add**.
3. HACS → raskite **AMiT PLC (WebSocket)** → **Download**.
4. **Perkraukite Home Assistant** (Settings → System → Restart).

Be HACS: nukopijuokite aplanką `custom_components/amit_plc` į `/config/custom_components/` ir perkraukite.

## Pirminė konfigūracija (komunikaciniai parametrai)

Settings → Devices & services → **+ Add integration** → **AMiT PLC**:

| Laukas | Reikšmė |
|---|---|
| PLC IP address | pvz. `192.168.1.190` |
| WebSocket port | AMiT pavyzdyje `80` |
| User / Password | tik jei DetStudio projekte sukurti vartotojai (slaptažodis siunčiamas kaip MD5) |
| Polling interval | ms, numatyta `100` |

Prisijungimas patikrinamas iš karto (perskaitomas stoties tipas).

## Kintamųjų pridėjimas

Settings → Devices & services → **AMiT PLC** → **Configure**:

* **Add variable** – 1/2: pasirinkite kintamąjį iš PLC sąrašo (arba įrašykite vardą ranka);
  2/2: tipas (įėjimas / skaičius / išėjimas), pavadinimas Home Assistant, vienetas, klasė, skaitmenys po kablelio.
* **Remove variables**, **Change polling interval**.
* Pabaigoje **Save and apply** – integracija persikrauna pati.

## Pastabos

* Galima pridėti **kelis valdiklius** (Add integration kiekvienam IP/prievadui; kiekvienam galima suteikti pavadinimą, pvz. „Katilinė“). Kintamųjų vardus kiekvienam valdikliui pridedate atskirai.
* Naudojamas JSON režimas (tekstiniai kadrai). Vienas atsakymas stotyje ribojamas ~16 kB, todėl labai daug
  kintamųjų vienoje užklausoje nerekomenduojama.
* Jei kintamasis nerastas PLC, objektas rodo `unavailable`, o žurnale (`amit_plc`) matysite, kuris.
* `manifest.json` laukuose `documentation` ir `issue_tracker` pakeiskite `MarChjuZ` savo GitHub vartotojo vardu.

## Analog output (slider, e.g. dimmable lamp 0–100 %)

When adding a variable choose type **Analog output (slider)** and type the minimum, maximum and step by hand
(default 0 / 100 / 1). The entity appears as a `number` slider; the value is written to the PLC variable and read back every cycle.
